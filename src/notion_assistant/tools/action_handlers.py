"""
Action handlers for executing parsed intents against the Notion API.
Uses dynamic schema validation for property formatting.
"""
from datetime import date as date_type
from typing import Any, Dict, Optional
from src.notion_assistant.parsers.nl_parser import NotionIntent, ActionType
from src.notion_assistant.clients.mcp_client import NotionMCPClient
from src.notion_assistant.config.schema_manager import SchemaManager

# Exact property names in the habit_tracker Notion database
# Note: "jornal" is a typo in the actual Notion DB — keep it as-is
HABITS_DB_NAME = "habits"
HABITS_CHECKBOXES = {"sleep", "eat", "run", "workout", "stretch", "read", "draw", "jornal"}
# Map common aliases to the actual Notion property names
HABITS_ALIASES = {"journal": "jornal", "journaling": "jornal", "cardio": "run", "running": "run"}


def format_property_with_schema(
    schema_manager: Optional[SchemaManager],
    database: str,
    property_name: str,
    value: Any
) -> Dict[str, Any]:
    """
    Format a property value using schema information.
    Falls back to type inference if schema unavailable.
    """
    # Try schema-based formatting first
    if schema_manager and schema_manager.is_initialized:
        formatted = schema_manager.format_property_value(database, property_name, value)
        if formatted is not None:
            return formatted
    
    # Fallback: infer type from value
    return format_notion_property_fallback(property_name, value)


def format_notion_property_fallback(property_name: str, value: Any) -> Dict[str, Any]:
    """Fallback property formatting using type inference."""
    
    if isinstance(value, str):
        return {"rich_text": [{"text": {"content": value}}]}
    elif isinstance(value, (int, float)):
        return {"number": value}
    elif isinstance(value, bool):
        return {"checkbox": value}
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        return {"multi_select": [{"name": item} for item in value]}
    
    # Already formatted or unknown type - return as-is
    return value


async def handle_create(
    mcp: NotionMCPClient, 
    intent: NotionIntent,
    schema_manager: Optional[SchemaManager] = None
) -> Dict[str, Any]:
    """
    Handle create action with schema-aware property formatting.
    """
    properties = {}
    
    # Get database schema for title property name
    title_prop_name = "title"  # Default
    if schema_manager and schema_manager.is_initialized:
        schema = schema_manager.get_schema(intent.database)
        if schema:
            title_prop_name = schema.title_property
    
    # Set title using correct property name
    title_value = intent.title or "Untitled"
    properties[title_prop_name] = {
        "title": [{"text": {"content": title_value}}]
    }
    
    # Add tags if present
    if intent.tags:
        # Check if database has a tags property
        tags_prop_name = "tags"  # Default
        if schema_manager and schema_manager.is_initialized:
            schema = schema_manager.get_schema(intent.database)
            if schema:
                # Find tags or similar property
                for prop_name in ["tags", "Tags", "Categories", "categories"]:
                    if schema.has_property(prop_name):
                        tags_prop_name = prop_name
                        break
        
        properties[tags_prop_name] = {
            "multi_select": [{"name": tag} for tag in intent.tags]
        }
    
    # Merge additional properties with schema-aware formatting
    for prop_name, prop_value in intent.properties.items():
        if prop_name.lower() not in [title_prop_name.lower(), "tags"]:
            formatted = format_property_with_schema(
                schema_manager, 
                intent.database, 
                prop_name, 
                prop_value
            )
            
            # Use correct property name from schema
            if schema_manager and schema_manager.is_initialized:
                schema = schema_manager.get_schema(intent.database)
                if schema:
                    actual_prop = schema.get_property(prop_name)
                    if actual_prop:
                        prop_name = actual_prop.name
            
            properties[prop_name] = formatted
    
    return await mcp.create_page(
        database_name=intent.database,
        properties=properties,
        content_markdown=intent.content
    )


async def handle_search(mcp: NotionMCPClient, intent: NotionIntent) -> Dict[str, Any]:
    """Handle search action."""
    
    if intent.search_query:
        return await mcp.search(query=intent.search_query, page_size=10)
    else:
        return await mcp.query_database(database_name=intent.database, page_size=10)


async def handle_read(mcp: NotionMCPClient, intent: NotionIntent) -> Dict[str, Any]:
    """Handle read action."""
    
    if intent.page_id:
        return await mcp.get_page_content(page_id=intent.page_id)
    elif intent.title:
        return await mcp.find_page_by_name(
            database_name=intent.database,
            page_name=intent.title
        )
    else:
        raise ValueError("Need either page_id or title for read operation")


async def handle_update(
    mcp: NotionMCPClient, 
    intent: NotionIntent,
    schema_manager: Optional[SchemaManager] = None
) -> Dict[str, Any]:
    """
    Handle update action with schema-aware property formatting.
    """
    if not intent.page_id:
        # Try to find page by title first
        if intent.title or intent.search_query:
            search_term = intent.title or intent.search_query
            found = await mcp.find_page_by_name(
                database_name=intent.database,
                page_name=search_term
            )
            if found.get("found") == False:
                raise ValueError(f"Page '{search_term}' not found in {intent.database}")
            intent.page_id = found.get("page_id")
        else:
            raise ValueError("page_id, title, or search_query required for update operation")
    
    properties = {}
    
    # Get title property name from schema
    title_prop_name = "title"
    if schema_manager and schema_manager.is_initialized:
        schema = schema_manager.get_schema(intent.database)
        if schema:
            title_prop_name = schema.title_property
    
    if intent.title:
        properties[title_prop_name] = {
            "title": [{"text": {"content": intent.title}}]
        }
    
    if intent.tags:
        properties["tags"] = {
            "multi_select": [{"name": tag} for tag in intent.tags]
        }
    
    # Format additional properties with schema awareness
    for prop_name, prop_value in intent.properties.items():
        if prop_name.lower() not in [title_prop_name.lower(), "tags"]:
            formatted = format_property_with_schema(
                schema_manager,
                intent.database,
                prop_name,
                prop_value
            )
            
            # Get correct property name from schema
            if schema_manager and schema_manager.is_initialized:
                schema = schema_manager.get_schema(intent.database)
                if schema:
                    actual_prop = schema.get_property(prop_name)
                    if actual_prop:
                        prop_name = actual_prop.name
            
            properties[prop_name] = formatted
    
    return await mcp.update_page(
        page_id=intent.page_id,
        properties=properties if properties else None
    )


async def handle_habits_update(
    mcp: NotionMCPClient,
    intent: NotionIntent,
    today_iso: str,
) -> Dict[str, Any]:
    """
    Handle habit_tracker database updates.

    Finds today's page by the `date` property, creates it if missing,
    then patches the specified checkbox properties.

    Habits are extracted from:
      - intent.properties  (e.g. {"workout": True, "sleep": True})
      - intent.tags        (e.g. ["run", "read"])
    Aliases like "journal" → "jornal" are resolved automatically.
    """

    def _resolve(name: str) -> Optional[str]:
        """Normalize a habit name to the Notion property key."""
        lower = name.lower().strip()
        lower = HABITS_ALIASES.get(lower, lower)
        return lower if lower in HABITS_CHECKBOXES else None

    # Use explicitly parsed date if LLM extracted one, else fall back to today
    target_date = intent.target_date or today_iso

    # Query for the target date's page
    query_result = await mcp.query_database(
        database_name=HABITS_DB_NAME,
        filter={"property": "date", "date": {"equals": target_date}},
        page_size=1,
    )
    pages = query_result.get("results", [])

    if pages:
        page_id = pages[0].get("id") or pages[0].get("page_id")
    else:
        # Create the page for the target date
        created = await mcp.create_page(
            database_name=HABITS_DB_NAME,
            properties={
                "title": {"title": [{"text": {"content": target_date}}]},
                "date": {"date": {"start": target_date}},
            },
        )
        page_id = created.get("id") or created.get("page_id")

    # Collect checkbox updates
    properties: Dict[str, Any] = {}

    for prop_name, prop_value in intent.properties.items():
        key = _resolve(prop_name)
        if key:
            properties[key] = {"checkbox": bool(prop_value)}

    for tag in intent.tags:
        key = _resolve(tag)
        if key and key not in properties:
            properties[key] = {"checkbox": True}

    if not properties:
        return {"page_id": page_id, "updated": [], "message": "No matching habits found in input"}

    result = await mcp.update_page(page_id=page_id, properties=properties)
    result["updated_habits"] = list(properties.keys())
    result["target_date"] = target_date
    return result


async def handle_append(mcp: NotionMCPClient, intent: NotionIntent) -> Dict[str, Any]:
    """Handle append action."""
    
    if not intent.page_id:
        # Try to find page by title
        if intent.title or intent.search_query:
            search_term = intent.title or intent.search_query
            found = await mcp.find_page_by_name(
                database_name=intent.database,
                page_name=search_term
            )
            if found.get("found") == False:
                raise ValueError(f"Page '{search_term}' not found in {intent.database}")
            intent.page_id = found.get("page_id")
        else:
            raise ValueError("page_id or title required for append operation")
    
    if not intent.content:
        raise ValueError("content required for append operation")
    
    return await mcp.append_content(
        page_id=intent.page_id,
        content_markdown=intent.content
    )
