"""
Node functions for the Notion Assistant agent graph.
Uses dynamic schemas for validation and property formatting.
"""
import asyncio
from typing import Dict, Any, List

from rich import print as rprint

from src.notion_assistant.states.state import AgentState, IntentResult
from src.notion_assistant.parsers.nl_parser import NaturalLanguageParser, NotionIntent, ActionType
from src.notion_assistant.clients.mcp_client import NotionMCPClient
from src.notion_assistant.config.schema_manager import get_schema_manager
from src.notion_assistant.tools.action_handlers import (
    handle_create,
    handle_search,
    handle_read,
    handle_update,
    handle_append,
)


async def parse_input_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 1: Parse natural language input into structured intents.
    Handles multi-intent parsing (one input → multiple actions).
    Uses dynamic schemas from the schema manager.
    """
    rprint("[cyan]🧠 Parsing natural language...[/cyan]")
    
    try:
        # Get schema manager for dynamic database info
        schema_manager = get_schema_manager()
        
        # Initialize schemas if not already done
        if not schema_manager.is_initialized:
            rprint("[dim]Initializing schemas from MCP...[/dim]")
            async with NotionMCPClient() as mcp:
                await schema_manager.initialize(mcp)
        
        # Create parser with schema manager
        parser = NaturalLanguageParser(schema_manager=schema_manager)
        parsed = await parser.parse(state["user_input"])
        
        # Log parsing results
        rprint(f"[dim]Model: {parsed.model_used} | Escalated: {parsed.escalated}[/dim]")
        rprint(f"[green]✓ Found {len(parsed.intents)} intent(s)[/green]")
        
        for i, intent in enumerate(parsed.intents, 1):
            rprint(f"  {i}. [{intent.action.value}] → {intent.database}: {intent.title or intent.search_query or '(no title)'}")
        
        return {
            "parsed": parsed.model_dump(),
            "error": None
        }
    
    except Exception as e:
        rprint(f"[red]✗ Parsing failed:[/red] {e}")
        import traceback
        traceback.print_exc()
        return {
            "parsed": {"intents": [], "raw_input": state["user_input"], "overall_confidence": 0},
            "error": f"Failed to parse input: {str(e)}"
        }


async def router_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 2: Analyze parsed intents and create execution plan.
    Validates intents against database schemas.
    Decides whether to execute sequentially or in parallel.
    """
    rprint("[cyan]🔀 Planning execution...[/cyan]")
    
    if state.get("error"):
        return {"execution_plan": [], "error": state["error"]}
    
    parsed = state["parsed"]
    intents = parsed.get("intents", [])
    
    if not intents:
        return {
            "execution_plan": [],
            "error": "No intents found in input"
        }
    
    # Get schema manager for validation
    schema_manager = get_schema_manager()
    
    # Build execution plan with validation
    execution_plan = []
    warnings = []
    
    for i, intent_dict in enumerate(intents):
        # Validate database exists
        db_name = intent_dict.get("database", "")
        schema = schema_manager.get_schema(db_name) if schema_manager.is_initialized else None
        
        if schema_manager.is_initialized and not schema:
            warnings.append(f"Unknown database '{db_name}', defaulting to zettelkasten")
            intent_dict["database"] = "zettelkasten"
            schema = schema_manager.get_schema("zettelkasten")
        
        # Validate and fix properties if schema available
        if schema and intent_dict.get("properties"):
            fixed_props, prop_warnings = schema_manager.validate_properties(
                intent_dict["database"],
                intent_dict["properties"]
            )
            intent_dict["properties"] = fixed_props
            warnings.extend(prop_warnings)
        
        plan_item = {
            "index": i,
            "intent": intent_dict,
            "can_parallel": True,  # Most operations can run in parallel
            "depends_on": None,    # Future: for dependent operations
            "priority": _get_priority(intent_dict),
            "schema_validated": schema is not None,
        }
        
        # Check for dependencies
        # e.g., if an intent needs a page_id from a previous create
        if intent_dict.get("action") in ["update", "append"] and not intent_dict.get("page_id"):
            # Needs to find page first - mark as sequential
            plan_item["can_parallel"] = False
        
        execution_plan.append(plan_item)
    
    # Sort by priority
    execution_plan.sort(key=lambda x: x["priority"])
    
    parallel_count = sum(1 for p in execution_plan if p["can_parallel"])
    sequential_count = len(execution_plan) - parallel_count
    
    rprint(f"[green]✓ Plan: {parallel_count} parallel, {sequential_count} sequential[/green]")
    
    # Show any warnings
    for warning in warnings[:3]:  # Limit warnings shown
        rprint(f"[yellow]⚠ {warning}[/yellow]")
    
    return {
        "execution_plan": execution_plan,
        "error": None
    }


def _get_priority(intent: Dict[str, Any]) -> int:
    """Determine execution priority (lower = higher priority)."""
    action = intent.get("action", "")
    
    # Priority order: create > update > append > search > read
    priority_map = {
        "create": 1,
        "update": 2,
        "append": 3,
        "search": 4,
        "read": 5
    }
    
    return priority_map.get(action, 10)


async def execute_intents_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 3: Execute all intents according to the plan.
    Runs parallel-safe operations concurrently.
    Uses schema manager for property formatting.
    """
    rprint("[cyan]📝 Executing Notion operations...[/cyan]")
    
    if state.get("error"):
        return {"intent_results": [], "error": state["error"]}
    
    execution_plan = state.get("execution_plan", [])
    
    if not execution_plan:
        return {"intent_results": [], "error": "No execution plan"}
    
    # Separate parallel and sequential operations
    parallel_ops = [p for p in execution_plan if p["can_parallel"]]
    sequential_ops = [p for p in execution_plan if not p["can_parallel"]]
    
    results: List[IntentResult] = []
    
    # Get schema manager for property formatting
    schema_manager = get_schema_manager()
    
    async with NotionMCPClient() as mcp:
        # Execute parallel operations concurrently
        if parallel_ops:
            rprint(f"[dim]Running {len(parallel_ops)} operations in parallel...[/dim]")
            
            tasks = [
                _execute_single_intent(mcp, p["intent"], schema_manager)
                for p in parallel_ops
            ]
            
            parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for plan_item, result in zip(parallel_ops, parallel_results):
                if isinstance(result, Exception):
                    results.append({
                        "intent": plan_item["intent"],
                        "result": {},
                        "success": False,
                        "error": str(result)
                    })
                else:
                    results.append(result)
        
        # Execute sequential operations one by one
        for plan_item in sequential_ops:
            rprint(f"[dim]Running sequential: {plan_item['intent'].get('action')}...[/dim]")
            
            result = await _execute_single_intent(mcp, plan_item["intent"], schema_manager)
            results.append(result)
    
    # Count successes
    success_count = sum(1 for r in results if r["success"])
    rprint(f"[green]✓ Completed: {success_count}/{len(results)} successful[/green]")
    
    return {
        "intent_results": results,
        "error": None
    }


async def _execute_single_intent(
    mcp: NotionMCPClient, 
    intent_dict: Dict[str, Any],
    schema_manager
) -> IntentResult:
    """Execute a single intent and return result."""
    
    intent = NotionIntent(**intent_dict)
    
    try:
        if intent.action == ActionType.CREATE:
            result = await handle_create(mcp, intent, schema_manager)
        elif intent.action == ActionType.SEARCH:
            result = await handle_search(mcp, intent)
        elif intent.action == ActionType.READ:
            result = await handle_read(mcp, intent)
        elif intent.action == ActionType.UPDATE:
            result = await handle_update(mcp, intent, schema_manager)
        elif intent.action == ActionType.APPEND:
            result = await handle_append(mcp, intent)
        else:
            raise ValueError(f"Unknown action: {intent.action}")
        
        return {
            "intent": intent_dict,
            "result": result,
            "success": True,
            "error": None
        }
    
    except Exception as e:
        return {
            "intent": intent_dict,
            "result": {},
            "success": False,
            "error": str(e)
        }


async def format_response_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 4: Aggregate all results into a user-friendly response.
    """
    rprint("[cyan]💬 Formatting response...[/cyan]")
    
    # Check for top-level errors
    if state.get("error"):
        return {"response": f"❌ Error: {state['error']}"}
    
    intent_results = state.get("intent_results", [])
    parsed = state.get("parsed", {})
    
    if not intent_results:
        return {"response": "❌ No operations were executed"}
    
    # Build response sections
    response_parts = []
    
    # Add model info if escalated
    if parsed.get("escalated"):
        response_parts.append(f"🔄 *Used enhanced parsing (confidence was low)*\n")
    
    # Format each result
    successes = []
    failures = []
    
    for ir in intent_results:
        intent = NotionIntent(**ir["intent"])
        
        if ir["success"]:
            formatted = _format_single_result(intent, ir["result"])
            successes.append(formatted)
        else:
            failures.append(f"❌ {intent.action.value} → {intent.database}: {ir['error']}")
    
    # Combine results
    if successes:
        response_parts.extend(successes)
    
    if failures:
        response_parts.append("\n**Issues:**")
        response_parts.extend(failures)
    
    response = "\n".join(response_parts)
    
    rprint("[green]✓ Response ready[/green]")
    
    return {"response": response}


def _format_single_result(intent: NotionIntent, result: Dict[str, Any]) -> str:
    """Format a single intent result."""
    
    if intent.action == ActionType.CREATE:
        title = result.get("title", intent.title or "Untitled")
        url = result.get("url", "")
        return f"✅ Created **{title}** in {intent.database}\n   🔗 {url}"
    
    elif intent.action == ActionType.SEARCH:
        results_list = result.get("results", [])
        count = len(results_list)
        
        if count == 0:
            return f"🔍 No results found for '{intent.search_query}'"
        
        lines = [f"🔍 Found {count} result(s):"]
        for i, page in enumerate(results_list[:5], 1):
            page_title = _extract_title(page)
            lines.append(f"   {i}. {page_title}")
        
        if count > 5:
            lines.append(f"   ... and {count - 5} more")
        
        return "\n".join(lines)
    
    elif intent.action == ActionType.READ:
        title = result.get("title", "Page")
        content = result.get("content", "")
        preview = content[:200] + "..." if len(content) > 200 else content
        return f"📄 **{title}**\n{preview}"
    
    elif intent.action == ActionType.UPDATE:
        return f"✅ Updated page in {intent.database}"
    
    elif intent.action == ActionType.APPEND:
        return f"✅ Appended content to page"
    
    return f"✅ Completed {intent.action.value}"


def _extract_title(page: Dict[str, Any]) -> str:
    """Extract title from a Notion page object."""
    properties = page.get("properties", {})
    
    # Try common title property names
    for prop_name in ["title", "Name", "name", "Title"]:
        prop = properties.get(prop_name, {})
        
        if prop.get("type") == "title":
            title_array = prop.get("title", [])
            if title_array:
                return title_array[0].get("text", {}).get("content", "Untitled")
        elif "title" in prop:
            title_array = prop.get("title", [])
            if title_array:
                return title_array[0].get("text", {}).get("content", "Untitled")
    
    return "Untitled"
