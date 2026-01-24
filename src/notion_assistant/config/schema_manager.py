"""
Dynamic Schema Manager
Fetches and caches Notion database schemas from the MCP server.
Eliminates hardcoded database configurations.
"""
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

from rich import print as rprint


@dataclass
class PropertySchema:
    """Schema for a single database property."""
    name: str
    type: str
    id: str
    options: List[str] = field(default_factory=list)  # For select/multi_select
    
    def is_title(self) -> bool:
        return self.type == "title"
    
    def is_select(self) -> bool:
        return self.type in ("select", "multi_select")
    
    def is_number(self) -> bool:
        return self.type == "number"
    
    def is_checkbox(self) -> bool:
        return self.type == "checkbox"
    
    def is_date(self) -> bool:
        return self.type == "date"
    
    def is_text(self) -> bool:
        return self.type == "rich_text"
    
    def is_url(self) -> bool:
        return self.type == "url"
    
    def is_relation(self) -> bool:
        return self.type == "relation"
    
    def is_readonly(self) -> bool:
        """Properties that can't be set via API."""
        return self.type in ("formula", "rollup", "created_time", "last_edited_time", "created_by", "last_edited_by")


@dataclass
class DatabaseSchema:
    """Complete schema for a Notion database."""
    name: str  # Config name (e.g., "zettelkasten")
    data_source_id: str
    title: str  # Display title from Notion
    title_property: str  # Name of the title property
    description: str
    properties: Dict[str, PropertySchema] = field(default_factory=dict)
    url: Optional[str] = None
    fetched_at: Optional[datetime] = None
    
    def get_title_property(self) -> Optional[PropertySchema]:
        """Get the title property schema."""
        for prop in self.properties.values():
            if prop.is_title():
                return prop
        return None
    
    def get_writable_properties(self) -> Dict[str, PropertySchema]:
        """Get properties that can be written via API."""
        return {
            name: prop 
            for name, prop in self.properties.items() 
            if not prop.is_readonly()
        }
    
    def get_select_properties(self) -> Dict[str, PropertySchema]:
        """Get select/multi_select properties with their options."""
        return {
            name: prop 
            for name, prop in self.properties.items() 
            if prop.is_select()
        }
    
    def has_property(self, name: str) -> bool:
        """Check if property exists (case-insensitive)."""
        return name.lower() in {n.lower() for n in self.properties.keys()}
    
    def get_property(self, name: str) -> Optional[PropertySchema]:
        """Get property by name (case-insensitive)."""
        for prop_name, prop in self.properties.items():
            if prop_name.lower() == name.lower():
                return prop
        return None
    
    def to_prompt_description(self) -> str:
        """Generate a description for use in LLM prompts."""
        lines = [f"**{self.name}**"]
        lines.append(f"  - Purpose: {self.description or 'General database'}")
        
        # Key properties (writable, non-title)
        writable = self.get_writable_properties()
        key_props = [p.name for p in writable.values() if not p.is_title()][:5]
        if key_props:
            lines.append(f"  - Key properties: {', '.join(key_props)}")
        
        # Select options (useful for LLM to know valid values)
        selects = self.get_select_properties()
        for prop_name, prop in list(selects.items())[:2]:  # Limit to 2 select props
            if prop.options:
                opts = prop.options[:5]  # Limit options shown
                more = f" (+{len(prop.options) - 5} more)" if len(prop.options) > 5 else ""
                lines.append(f"  - {prop_name} options: {', '.join(opts)}{more}")
        
        return "\n".join(lines)


class SchemaManager:
    """
    Manages Notion database schemas with caching.
    
    Features:
    - Fetches schemas from MCP server on demand
    - Caches schemas to avoid repeated API calls
    - Provides schema validation helpers
    - Generates dynamic prompts for the NL parser
    
    Usage:
        manager = SchemaManager()
        await manager.initialize(mcp_client)
        
        schema = manager.get_schema("zettelkasten")
        prompt = manager.generate_parser_prompt()
    """
    
    # Cache TTL - refresh schemas after this period
    CACHE_TTL = timedelta(hours=1)
    
    def __init__(self):
        self._schemas: Dict[str, DatabaseSchema] = {}
        self._initialized = False
        self._last_refresh: Optional[datetime] = None
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    
    @property
    def database_names(self) -> List[str]:
        """Get list of available database names."""
        return list(self._schemas.keys())
    
    async def initialize(self, mcp_client) -> None:
        """
        Initialize by fetching all database schemas from MCP.
        
        Args:
            mcp_client: Connected NotionMCPClient instance
        """
        rprint("[cyan]📊 Fetching database schemas from MCP...[/cyan]")
        
        try:
            # Get list of all databases
            databases_result = await mcp_client.list_databases()
            data_sources = databases_result.get("data_sources", [])
            
            rprint(f"[dim]Found {len(data_sources)} databases[/dim]")
            
            # Fetch schema for each database
            for ds in data_sources:
                await self._fetch_database_schema(mcp_client, ds)
            
            self._initialized = True
            self._last_refresh = datetime.now()
            
            rprint(f"[green]✓ Loaded {len(self._schemas)} database schemas[/green]")
            
        except Exception as e:
            rprint(f"[red]✗ Failed to initialize schemas: {e}[/red]")
            raise
    
    async def _fetch_database_schema(self, mcp_client, data_source: Dict[str, Any]) -> None:
        """Fetch and parse schema for a single database."""
        
        # Extract basic info
        ds_id = data_source.get("id", "")
        title = data_source.get("title", "unknown")
        url = data_source.get("url", "")
        
        # Try to get detailed schema via get_data_source
        # We need to find the config name that maps to this data_source_id
        # For now, use title as the lookup key
        config_name = self._normalize_name(title)
        
        try:
            schema_result = await mcp_client.get_data_source_schema(config_name)
            
            # Parse properties
            properties = {}
            raw_props = schema_result.get("properties", {})
            
            for prop_name, prop_data in raw_props.items():
                prop_type = prop_data.get("type", "unknown")
                prop_id = prop_data.get("id", "")
                
                # Extract options for select types
                options = []
                if prop_type in ("select", "multi_select"):
                    options = prop_data.get("options", [])
                
                properties[prop_name] = PropertySchema(
                    name=prop_name,
                    type=prop_type,
                    id=prop_id,
                    options=options
                )
            
            # Find title property
            title_prop = "title"
            for prop_name, prop in properties.items():
                if prop.is_title():
                    title_prop = prop_name
                    break
            
            # Create schema object
            self._schemas[config_name] = DatabaseSchema(
                name=config_name,
                data_source_id=ds_id,
                title=title,
                title_property=title_prop,
                description=self._infer_description(config_name, properties),
                properties=properties,
                url=url,
                fetched_at=datetime.now()
            )
            
            rprint(f"[dim]  ✓ {config_name}: {len(properties)} properties[/dim]")
            
        except Exception as e:
            rprint(f"[yellow]  ⚠ {title}: Could not fetch schema ({e})[/yellow]")
            
            # Create minimal schema entry
            self._schemas[config_name] = DatabaseSchema(
                name=config_name,
                data_source_id=ds_id,
                title=title,
                title_property="title",
                description="",
                url=url,
                fetched_at=datetime.now()
            )
    
    def _normalize_name(self, title: str) -> str:
        """Normalize database title to config name format."""
        # Handle special characters and spaces
        normalized = title.lower().strip()
        
        # Common mappings (title → config name)
        mappings = {
            "habit_tracker": "habits",
            "calorie tracker": "calorie_tracker",
            "weekly meal plan": "meal_planning",
            "recipe collection": "recipe_collection",
            "workout schedule": "workout_schedule",
            "kas.blog": "blog_content",
            "ikigai⋆ reading list": "reading_list",
            "media": "media_library",
        }
        
        return mappings.get(normalized, normalized.replace(" ", "_"))
    
    def _infer_description(self, name: str, properties: Dict[str, PropertySchema]) -> str:
        """Infer a description based on database name and properties."""
        descriptions = {
            "zettelkasten": "Personal knowledge management - notes, ideas, learnings, research",
            "habits": "Daily habit tracking - exercise, reading, journaling streaks",
            "project_management": "Tasks, projects, deadlines, content production tracking",
            "calorie_tracker": "Food logging, nutrition tracking, meals and calories",
            "meal_planning": "Weekly meal planning and organization",
            "recipe_collection": "Saved recipes and cooking instructions",
            "workout_schedule": "Planned workouts and exercise schedules",
            "exercises": "Exercise library with sets, reps, and muscle groups",
            "expense_tracker": "Financial tracking, expenses, subscriptions",
            "blog_content": "Blog posts and content publishing workflow",
            "media_library": "Movies, shows, books, podcasts - media consumption",
            "reading_list": "Books to read and reading progress",
            "ai_controls": "AI automation controls and routing rules",
        }
        
        return descriptions.get(name, f"Database for {name.replace('_', ' ')}")
    
    def get_schema(self, name: str) -> Optional[DatabaseSchema]:
        """Get schema by database name."""
        # Try exact match first
        if name in self._schemas:
            return self._schemas[name]
        
        # Try case-insensitive
        for schema_name, schema in self._schemas.items():
            if schema_name.lower() == name.lower():
                return schema
        
        return None
    
    def get_all_schemas(self) -> Dict[str, DatabaseSchema]:
        """Get all database schemas."""
        return self._schemas.copy()
    
    def generate_parser_prompt(self) -> str:
        """
        Generate dynamic database descriptions for the NL parser prompt.
        
        Returns:
            Formatted string describing all databases for LLM context
        """
        sections = []
        
        for name, schema in sorted(self._schemas.items()):
            sections.append(schema.to_prompt_description())
        
        return "\n\n".join(sections)
    
    def generate_database_examples(self) -> Dict[str, List[str]]:
        """
        Generate example keywords for each database.
        Used by the parser to identify which database to target.
        """
        examples = {
            "zettelkasten": ["note", "idea", "thought", "learning", "research", "concept"],
            "habits": ["habit", "streak", "daily", "workout done", "read", "journal"],
            "project_management": ["task", "project", "deadline", "to-do", "action item"],
            "calorie_tracker": ["ate", "food", "breakfast", "lunch", "dinner", "snack", "calories"],
            "meal_planning": ["meal plan", "planning meals", "weekly menu"],
            "recipe_collection": ["recipe", "how to cook", "ingredients"],
            "workout_schedule": ["workout", "gym", "exercise plan", "training"],
            "exercises": ["exercise", "sets", "reps", "muscle"],
            "expense_tracker": ["spent", "bought", "paid", "cost", "expense", "subscription"],
            "blog_content": ["blog post", "article", "publish", "draft"],
            "media_library": ["watched", "movie", "show", "book", "podcast", "reading"],
            "reading_list": ["book", "want to read", "reading list"],
            "ai_controls": ["ai rule", "automation", "control"],
        }
        
        # Only return examples for databases that exist
        return {
            name: examples.get(name, [name.replace("_", " ")])
            for name in self._schemas.keys()
        }
    
    def validate_properties(
        self, 
        database_name: str, 
        properties: Dict[str, Any]
    ) -> tuple[Dict[str, Any], List[str]]:
        """
        Validate and fix property names/values against schema.
        
        Args:
            database_name: Target database
            properties: Properties dict to validate
        
        Returns:
            Tuple of (fixed_properties, warnings)
        """
        schema = self.get_schema(database_name)
        if not schema:
            return properties, [f"Unknown database: {database_name}"]
        
        fixed = {}
        warnings = []
        
        for prop_name, prop_value in properties.items():
            # Find matching property (case-insensitive)
            actual_prop = schema.get_property(prop_name)
            
            if not actual_prop:
                warnings.append(f"Unknown property '{prop_name}' in {database_name}")
                continue
            
            if actual_prop.is_readonly():
                warnings.append(f"Property '{prop_name}' is read-only, skipping")
                continue
            
            # Use the correct property name
            correct_name = actual_prop.name
            
            # Validate select options
            if actual_prop.is_select() and actual_prop.options:
                if isinstance(prop_value, str) and prop_value not in actual_prop.options:
                    # Try case-insensitive match
                    matched = next(
                        (opt for opt in actual_prop.options if opt.lower() == prop_value.lower()),
                        None
                    )
                    if matched:
                        prop_value = matched
                    else:
                        warnings.append(
                            f"Invalid option '{prop_value}' for {correct_name}. "
                            f"Valid: {actual_prop.options[:5]}"
                        )
            
            fixed[correct_name] = prop_value
        
        return fixed, warnings
    
    def format_property_value(
        self,
        database_name: str,
        property_name: str,
        value: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Format a raw value into Notion API format based on schema.
        
        Args:
            database_name: Target database
            property_name: Property to format
            value: Raw value
        
        Returns:
            Notion API formatted property value, or None if invalid
        """
        schema = self.get_schema(database_name)
        if not schema:
            return None
        
        prop = schema.get_property(property_name)
        if not prop:
            return None
        
        # Format based on type
        if prop.is_title():
            return {"title": [{"text": {"content": str(value)}}]}
        
        elif prop.type == "rich_text":
            return {"rich_text": [{"text": {"content": str(value)}}]}
        
        elif prop.type == "number":
            try:
                return {"number": float(value)}
            except (TypeError, ValueError):
                return None
        
        elif prop.type == "checkbox":
            return {"checkbox": bool(value)}
        
        elif prop.type == "select":
            return {"select": {"name": str(value)}}
        
        elif prop.type == "multi_select":
            if isinstance(value, list):
                return {"multi_select": [{"name": str(v)} for v in value]}
            else:
                return {"multi_select": [{"name": str(value)}]}
        
        elif prop.type == "date":
            # Assume ISO format string
            return {"date": {"start": str(value)}}
        
        elif prop.type == "url":
            return {"url": str(value)}
        
        # Unknown type - return as-is
        return value
    
    async def refresh_if_stale(self, mcp_client) -> bool:
        """
        Refresh schemas if cache is stale.
        
        Returns:
            True if refresh occurred
        """
        if not self._last_refresh:
            await self.initialize(mcp_client)
            return True
        
        if datetime.now() - self._last_refresh > self.CACHE_TTL:
            await self.initialize(mcp_client)
            return True
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Export schemas to dict for debugging/caching."""
        return {
            name: {
                "data_source_id": schema.data_source_id,
                "title": schema.title,
                "title_property": schema.title_property,
                "description": schema.description,
                "properties": {
                    p.name: {"type": p.type, "options": p.options}
                    for p in schema.properties.values()
                }
            }
            for name, schema in self._schemas.items()
        }


# Singleton instance for convenience
_schema_manager: Optional[SchemaManager] = None


def get_schema_manager() -> SchemaManager:
    """Get or create the global SchemaManager instance."""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = SchemaManager()
    return _schema_manager


async def initialize_schemas(mcp_client) -> SchemaManager:
    """Initialize the global schema manager with MCP client."""
    manager = get_schema_manager()
    await manager.initialize(mcp_client)
    return manager
