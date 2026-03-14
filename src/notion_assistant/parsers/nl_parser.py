"""
Natural Language Parser (Dynamic Schema + Controls Version)
Extracts structured intent from user's natural language input.
Uses dynamically fetched schemas and Notion-based AI controls for instructions.

Architecture:
    User Input → Parser (with injected controls) → Structured Intents
    
    Controls are loaded from ai_controls Notion database, allowing
    no-code modification of parsing behavior.
"""
from dotenv import load_dotenv
load_dotenv()

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from enum import Enum

from src.notion_assistant.config.schema_manager import SchemaManager, get_schema_manager
from src.notion_assistant.config.controls_loader import ControlsLoader, get_controls_loader


# ========================================
# Models & Schemas
# ========================================

class ActionType(str, Enum):
    """Valid actions for Notion operations."""
    CREATE = "create"
    SEARCH = "search"
    UPDATE = "update"
    READ = "read"
    APPEND = "append"
    CALENDAR = "calendar"


class NotionIntent(BaseModel):
    """Structured representation of a single user intent for Notion operations."""
    
    action: ActionType = Field(
        description="The action to perform: create, search, update, read, append"
    )
    database: str = Field(
        description="Target database name (must match available database names exactly)"
    )
    title: Optional[str] = Field(
        default=None,
        description="Title for create/update operations"
    )
    content: Optional[str] = Field(
        default=None,
        description="Content for create/append operations (markdown format)"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Tags/categories for the item"
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional properties specific to the database schema"
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Search query for search/read operations"
    )
    page_id: Optional[str] = Field(
        default=None,
        description="Page ID for update/read/append operations"
    )
    target_date: Optional[str] = Field(
        default=None,
        description="ISO date string (YYYY-MM-DD) for the target entry date. Only set when the user specifies a date other than today (e.g. 'yesterday', 'march 12th', 'last Monday'). Leave null if user means today."
    )
    calendar_action: Optional[str] = Field(
        default=None,
        description="Calendar sub-action: 'query' (list events) or 'create' (new event)"
    )
    start_time: Optional[str] = Field(
        default=None,
        description="ISO datetime for calendar events (e.g. 2026-03-20T14:00:00)"
    )
    end_time: Optional[str] = Field(
        default=None,
        description="ISO datetime for calendar events end time"
    )
    confidence: float = Field(
        default=1.0,
        description="Confidence score for this specific intent (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Brief explanation of how this intent was determined"
    )


class ParsedInput(BaseModel):
    """Container for multiple intents parsed from a single input."""
    
    intents: List[NotionIntent] = Field(
        description="List of all intents extracted from the input"
    )
    raw_input: str = Field(
        description="The original user input"
    )
    overall_confidence: float = Field(
        default=1.0,
        description="Overall confidence for the parsing (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )
    model_used: str = Field(
        default="gpt-4o-mini",
        description="Which model was used for parsing"
    )
    escalated: bool = Field(
        default=False,
        description="Whether parsing was escalated to a larger model"
    )


# ========================================
# Parser Implementation
# ========================================

class NaturalLanguageParser:
    """
    Parses natural language input into structured Notion operations.
    
    Features:
    - Multi-intent parsing (one input → multiple database operations)
    - Dynamic schema loading (no hardcoded database configs)
    - Notion-based AI controls for parsing instructions
    - Cost-efficient model escalation (mini first, upgrade if low confidence)
    - Schema-aware parsing using actual database configurations
    
    The parser now loads instructions from the ai_controls Notion database,
    allowing you to modify parsing behavior without code changes.
    
    Example inputs:
        "Create a note about FastMCP 3.0 with tags python and mcp"
        "Worked from home today, did 30 min cardio, ate salmon for dinner"
        "Add a task to review docs by Friday and log $50 expense for lunch"
    """
    
    # Model configuration
    FAST_MODEL = "gpt-4o-mini"
    SMART_MODEL = "gpt-4o"
    CONFIDENCE_THRESHOLD = 0.7  # Escalate if below this
    
    def __init__(
        self,
        schema_manager: Optional[SchemaManager] = None,
        controls_loader: Optional[ControlsLoader] = None,
        temperature: float = 0.1,
        auto_escalate: bool = True
    ):
        """
        Initialize the parser.
        
        Args:
            schema_manager: SchemaManager instance (uses global if not provided)
            controls_loader: ControlsLoader instance (uses global if not provided)
            temperature: LLM temperature (lower = more deterministic)
            auto_escalate: Whether to auto-escalate to smarter model on low confidence
        """
        self.schema_manager = schema_manager or get_schema_manager()
        self.controls_loader = controls_loader or get_controls_loader()
        self.temperature = temperature
        self.auto_escalate = auto_escalate
        
        # Initialize models
        self.fast_llm = ChatOpenAI(model=self.FAST_MODEL, temperature=temperature)
        self.smart_llm = ChatOpenAI(model=self.SMART_MODEL, temperature=temperature)
        
        # Parser for multi-intent output
        self.parser = PydanticOutputParser(pydantic_object=ParsedInput)
    
    def _build_prompt(self, user_input: Optional[str] = None) -> ChatPromptTemplate:
        """Build the parsing prompt with dynamic database context and AI controls.

        Args:
            user_input: If provided, uses hierarchical control loading
                       (only includes relevant controls based on detected databases)
        """
        from datetime import date
        today_iso = date.today().isoformat()  # e.g. "2026-03-13"

        # Get database descriptions from schema manager
        if self.schema_manager.is_initialized:
            db_list = self.schema_manager.generate_parser_prompt()
            db_names = ", ".join(self.schema_manager.database_names)
            examples_dict = self.schema_manager.generate_database_examples()
        else:
            # Fallback if not initialized
            db_list = "(Schema not loaded - defaulting to zettelkasten)"
            db_names = "zettelkasten"
            examples_dict = {"zettelkasten": ["note", "idea"]}
        
        # Format examples for prompt
        examples_text = "\n".join([
            f"- {db}: {', '.join(kws)}"
            for db, kws in examples_dict.items()
        ])
        
        # Get AI controls from Notion - use hierarchical loading if input provided
        controls_section = ""
        if self.controls_loader.is_initialized:
            if user_input:
                # Smart loading: only include relevant controls
                controls_section = self.controls_loader.format_for_input(user_input, include_metadata=True)
            else:
                # Fallback: include all controls
                controls_section = self.controls_loader.format_routing_prompt()
        # Escape braces so LangChain doesn't treat control content as template variables
        controls_section = controls_section.replace("{", "{{").replace("}", "}}")
        
        system_message = f"""You are an expert parser for a personal productivity system connected to Notion.

Your task is to parse user input and extract ALL distinct intents. A single input may contain multiple actions for different databases.

## Today's Date

Today is {today_iso}. Use this when the user refers to "today", "tonight", or similar relative dates.

## Available Databases

{db_list}

## Database Name Reference

IMPORTANT: You must use EXACTLY these database names in your output:
{db_names}

## Keyword Hints (which database to use)

{examples_text}

## Habit Tracker Rules

The `habits` database stores ONE page per day. Each page has 8 checkbox properties:
  sleep, eat, run, workout, stretch, read, draw, jornal (note: "jornal" is the Notion property name — not a typo you should fix)

When the user mentions completing any of these habits, ALWAYS use:
  action: "update"
  database: "habits"
  properties: sleep=true, workout=true, ... (only the habits they mention)
  tags: []

NEVER use action "create" for habits — the handler will create today's page automatically if it doesn't exist.
NEVER put habit names in `tags` — put them as boolean values in `properties`.

If the user specifies a date other than today (e.g. "march 12th", "yesterday", "last Monday"), resolve it to ISO format (YYYY-MM-DD) and set it as target_date. If no date is mentioned, leave target_date null.

Examples:
  "I slept well and worked out"  → update habits, properties: sleep=true, workout=true
  "Did my run and journaling"    → update habits, properties: run=true, jornal=true
  "Checked off sleep, eat, read" → update habits, properties: sleep=true, eat=true, read=true

{controls_section}

## Output Format

Return a ParsedInput object containing a list of NotionIntent objects.

{{format_instructions}}
"""

        return ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "Parse this input:\n\n{input}")
        ])
    
    async def parse(self, user_input: str) -> ParsedInput:
        """
        Parse natural language input into structured intents.
        
        Uses fast model first, escalates to smart model if confidence is low.
        
        Args:
            user_input: User's natural language request
        
        Returns:
            ParsedInput with list of intents and metadata
        """
        # Try fast model first
        result = await self._parse_with_model(user_input, self.fast_llm, self.FAST_MODEL)
        
        # Check if escalation needed
        if self.auto_escalate and result.overall_confidence < self.CONFIDENCE_THRESHOLD:
            result = await self._parse_with_model(user_input, self.smart_llm, self.SMART_MODEL)
            result.escalated = True
        
        # Validate database names against schema
        result = self._validate_database_names(result)
        
        return result
    
    def _validate_database_names(self, result: ParsedInput) -> ParsedInput:
        """Validate and fix database names in parsed result."""
        
        if not self.schema_manager.is_initialized:
            return result
        
        valid_names = set(self.schema_manager.database_names)
        
        for intent in result.intents:
            if intent.action == ActionType.CALENDAR:
                continue  # calendar intents don't map to a Notion database
            if intent.database not in valid_names:
                # Try to find closest match
                closest = self._find_closest_database(intent.database)
                if closest:
                    intent.database = closest
                else:
                    # Default to zettelkasten
                    intent.database = "zettelkasten"
                    intent.confidence = min(intent.confidence, 0.5)
                    intent.reasoning = (intent.reasoning or "") + f" (Unknown database, defaulted)"
        
        return result
    
    def _find_closest_database(self, name: str) -> Optional[str]:
        """Find closest matching database name."""
        name_lower = name.lower().replace(" ", "_").replace("-", "_")
        
        # Common aliases
        aliases = {
            "notes": "zettelkasten",
            "note": "zettelkasten",
            "knowledge": "zettelkasten",
            "habit": "habits",
            "habit_tracker": "habits",
            "task": "project_management",
            "tasks": "project_management",
            "todo": "project_management",
            "food": "calorie_tracker",
            "meal": "calorie_tracker",
            "calories": "calorie_tracker",
            "expense": "expense_tracker",
            "expenses": "expense_tracker",
            "money": "expense_tracker",
            "workout": "workout_schedule",
            "exercise": "exercises",
            "blog": "blog_content",
            "media": "media_library",
        }
        
        if name_lower in aliases:
            return aliases[name_lower]
        
        # Try partial match
        for db_name in self.schema_manager.database_names:
            if name_lower in db_name or db_name in name_lower:
                return db_name
        
        return None
    
    async def parse_with_model(self, user_input: str, model: str) -> ParsedInput:
        """
        Parse using a specific model (no auto-escalation).
        
        Args:
            user_input: User's natural language request
            model: Model name to use ("gpt-4o-mini" or "gpt-4o")
        
        Returns:
            ParsedInput with list of intents
        """
        llm = self.fast_llm if model == self.FAST_MODEL else self.smart_llm
        return await self._parse_with_model(user_input, llm, model)
    
    async def _parse_with_model(self, user_input: str, llm: ChatOpenAI, model_name: str) -> ParsedInput:
        """Internal parsing with specified LLM instance."""
        
        # Build prompt with hierarchical control loading based on input
        prompt = self._build_prompt(user_input)
        chain = prompt | llm | self.parser
        
        try:
            result = await chain.ainvoke({
                "input": user_input,
                "format_instructions": self.parser.get_format_instructions()
            })
            
            # Ensure metadata is set
            result.raw_input = user_input
            result.model_used = model_name
            
            # Calculate overall confidence from individual intents
            if result.intents:
                result.overall_confidence = sum(i.confidence for i in result.intents) / len(result.intents)
            
            return result
            
        except Exception as e:
            # Re-raise so parse_input_node surfaces a real error to the user
            # rather than silently creating a junk zettelkasten note
            raise RuntimeError(f"LLM parsing failed ({model_name}): {e}") from e
    
    def get_available_databases(self) -> List[str]:
        """Get list of available database names."""
        return self.schema_manager.database_names
    
    def set_escalation_threshold(self, threshold: float):
        """Set the confidence threshold for model escalation (0.0-1.0)."""
        self.CONFIDENCE_THRESHOLD = max(0.0, min(1.0, threshold))
    
    def invalidate_prompt_cache(self):
        """Force prompt rebuild on next parse.
        
        Note: With hierarchical loading, prompts are built per-request anyway.
        This method is kept for API compatibility but is now a no-op.
        """
        pass  # Prompts are built fresh for each input now


# ========================================
# Convenience Functions
# ========================================

async def quick_parse(user_input: str, schema_manager: Optional[SchemaManager] = None) -> ParsedInput:
    """One-liner parsing with default configuration."""
    parser = NaturalLanguageParser(schema_manager=schema_manager)
    return await parser.parse(user_input)


# ========================================
# Example Usage
# ========================================

async def main():
    """Example usage of the natural language parser with dynamic schemas and controls."""
    from rich import print as rprint
    from rich.table import Table
    from rich.panel import Panel
    
    from src.notion_assistant.clients.mcp_client import NotionMCPClient
    from src.notion_assistant.config.schema_manager import initialize_schemas
    from src.notion_assistant.config.controls_loader import initialize_controls
    
    rprint("\n[bold cyan]═══ Initializing Parser with Schemas + Controls ═══[/bold cyan]\n")
    
    async with NotionMCPClient() as mcp:
        # Initialize both schemas and controls
        schema_manager = await initialize_schemas(mcp)
        controls_loader = await initialize_controls(mcp)
    
    rprint(f"[green]✓ Loaded {len(schema_manager.database_names)} databases[/green]")
    rprint(f"[green]✓ Loaded {len(controls_loader.controls)} AI controls[/green]\n")
    
    # Show loaded controls
    rprint("[bold]Active Controls:[/bold]")
    for control in controls_loader.controls:
        rprint(f"  • {control.name} ({control.control_type}) - priority {control.priority}")
    rprint()
    
    # Create parser with schemas and controls
    parser = NaturalLanguageParser(
        schema_manager=schema_manager,
        controls_loader=controls_loader
    )
    
    # Example inputs
    examples = [
        "Create a note about FastMCP 3.0 with tags python, mcp, and ai",
        "Ate salmon and rice for dinner, about 650 calories",
        "Finished the deployment task and spent $25 on lunch",
        "Did my morning workout and read for 30 minutes",
        "Quick idea: what if we used webhooks for real-time sync?",
    ]
    
    rprint("[bold cyan]═══ Testing Parser with Notion-based Controls ═══[/bold cyan]\n")
    
    for user_input in examples:
        rprint(f"[bold yellow]Input:[/bold yellow] {user_input}\n")
        
        result = await parser.parse(user_input)
        
        # Show metadata
        rprint(f"[dim]Model: {result.model_used} | Escalated: {result.escalated} | Confidence: {result.overall_confidence:.2f}[/dim]")
        
        # Show each intent
        table = Table(show_header=True, header_style="bold green")
        table.add_column("#")
        table.add_column("Action")
        table.add_column("Database")
        table.add_column("Title")
        table.add_column("Conf")
        
        for i, intent in enumerate(result.intents, 1):
            table.add_row(
                str(i),
                intent.action.value,
                intent.database,
                intent.title or "-",
                f"{intent.confidence:.2f}"
            )
        
        rprint(table)
        rprint()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
