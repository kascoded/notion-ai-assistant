"""
Main interface for the Notion Assistant agent.
Builds the LangGraph and provides a simple class to process requests.
"""
import asyncio
from typing import List, Optional
from langgraph.graph import StateGraph, END
from rich.console import Console
from rich.panel import Panel

from src.notion_assistant.states.state import AgentState
from src.notion_assistant.nodes.agent_nodes import (
    parse_input_node,
    router_node,
    execute_intents_node,
    format_response_node,
)
from src.notion_assistant.config.schema_manager import SchemaManager, get_schema_manager
from src.notion_assistant.config.controls_loader import ControlsLoader, get_controls_loader, initialize_controls
from src.notion_assistant.clients.mcp_client import NotionMCPClient


def build_agent() -> StateGraph:
    """
    Build the LangGraph workflow.
    
    Flow:
        User Input → Parse (multi-intent) → Route → Execute (parallel) → Format Response
    """
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("parse", parse_input_node)
    workflow.add_node("route", router_node)
    workflow.add_node("execute", execute_intents_node)
    workflow.add_node("format", format_response_node)
    
    # Define edges
    workflow.set_entry_point("parse")
    workflow.add_edge("parse", "route")
    workflow.add_edge("route", "execute")
    workflow.add_edge("execute", "format")
    workflow.add_edge("format", END)
    
    return workflow.compile()


class NotionAssistant:
    """
    High-level interface for the Notion assistant.
    
    Uses dynamic schema fetching to adapt to your actual Notion workspace.
    
    Usage:
        assistant = NotionAssistant()
        await assistant.initialize()  # Fetch schemas from MCP
        response = await assistant.process("Create a note about FastMCP")
        print(response)
    """
    
    def __init__(self):
        self.agent = build_agent()
        self.console = Console()
        self.schema_manager: Optional[SchemaManager] = None
        self.controls_loader: Optional[ControlsLoader] = None
        self._initialized = False
        self._init_lock: asyncio.Lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """
        Initialize the assistant by fetching schemas from MCP.

        Uses double-checked locking so concurrent callers (e.g. two simultaneous
        Telegram messages at startup) only run initialization once.

        Must be called before processing requests.
        """
        # Fast path — already initialized
        if self._initialized:
            return

        async with self._init_lock:
            # Re-check inside the lock in case another coroutine completed
            # initialization while we were waiting
            if self._initialized:
                return

            self.console.print(Panel(
                "[cyan]Initializing Notion Assistant...[/cyan]\n"
                "Fetching database schemas and AI controls from MCP server",
                border_style="cyan"
            ))

            self.schema_manager = get_schema_manager()
            self.controls_loader = get_controls_loader()

            async with NotionMCPClient() as mcp:
                await self.schema_manager.initialize(mcp)
                await self.controls_loader.initialize(mcp)

            self._initialized = True
        
        # Show available databases
        db_count = len(self.schema_manager.database_names)
        db_list = ", ".join(self.schema_manager.database_names[:5])
        if db_count > 5:
            db_list += f" (+{db_count - 5} more)"
        
        # Show loaded controls
        controls_count = len(self.controls_loader.controls)
        controls_list = ", ".join([c.name for c in self.controls_loader.controls[:3]])
        if controls_count > 3:
            controls_list += f" (+{controls_count - 3} more)"
        
        self.console.print(Panel(
            f"[green]✓ Ready![/green]\n\n"
            f"[bold]Databases:[/bold] {db_list}\n"
            f"[dim]Total: {db_count} databases loaded[/dim]\n\n"
            f"[bold]AI Controls:[/bold] {controls_list}\n"
            f"[dim]Total: {controls_count} controls loaded[/dim]",
            border_style="green"
        ))
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    
    @property
    def available_databases(self) -> List[str]:
        """Get list of available database names."""
        if self.schema_manager:
            return self.schema_manager.database_names
        return []
    
    async def process(self, user_input: str) -> str:
        """
        Process natural language input and return response.
        
        Args:
            user_input: User's natural language request
        
        Returns:
            Formatted response string
        """
        if not self._initialized:
            await self.initialize()
        
        # Display input
        self.console.print(Panel(
            user_input,
            title="[bold cyan]User Input[/bold cyan]",
            border_style="cyan"
        ))
        
        # Run the agent
        result = await self.agent.ainvoke({
            "user_input": user_input,
            "parsed": {},
            "execution_plan": [],
            "intent_results": [],
            "response": "",
            "error": None
        })
        
        # Display result
        response = result["response"]
        
        self.console.print(Panel(
            response,
            title="[bold green]Response[/bold green]",
            border_style="green"
        ))
        
        return response
    
    async def process_batch(self, inputs: List[str]) -> List[str]:
        """
        Process multiple inputs.
        
        Args:
            inputs: List of user inputs
        
        Returns:
            List of responses
        """
        if not self._initialized:
            await self.initialize()
        
        results = []
        for user_input in inputs:
            response = await self.process(user_input)
            results.append(response)
        return results
    
    async def refresh_schemas(self) -> None:
        """Force refresh of database schemas from MCP."""
        if self.schema_manager:
            async with NotionMCPClient() as mcp:
                await self.schema_manager.initialize(mcp)
            
            self.console.print("[green]✓ Schemas refreshed[/green]")
    
    async def refresh_controls(self) -> None:
        """Force refresh of AI controls from Notion."""
        if self.controls_loader:
            async with NotionMCPClient() as mcp:
                await self.controls_loader.refresh(mcp, force=True)
            
            self.console.print(f"[green]✓ Controls refreshed ({len(self.controls_loader.controls)} loaded)[/green]")
    
    async def refresh_all(self) -> None:
        """Force refresh of both schemas and controls."""
        async with NotionMCPClient() as mcp:
            if self.schema_manager:
                await self.schema_manager.initialize(mcp)
            if self.controls_loader:
                await self.controls_loader.refresh(mcp, force=True)
        
        self.console.print("[green]✓ All configurations refreshed[/green]")
    
    def get_database_info(self, database_name: str) -> Optional[dict]:
        """
        Get information about a specific database.
        
        Args:
            database_name: Name of the database
        
        Returns:
            Dict with database info or None if not found
        """
        if not self.schema_manager:
            return None
        
        schema = self.schema_manager.get_schema(database_name)
        if not schema:
            return None
        
        return {
            "name": schema.name,
            "title": schema.title,
            "description": schema.description,
            "properties": list(schema.properties.keys()),
            "title_property": schema.title_property,
        }
