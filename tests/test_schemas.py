"""
Test script for dynamic schema loading.
Run: uv run python test_schemas.py
"""
import asyncio
from rich import print as rprint
from rich.table import Table
from rich.panel import Panel

from src.notion_assistant.clients.mcp_client import NotionMCPClient
from src.notion_assistant.config.schema_manager import SchemaManager, initialize_schemas


async def test_schema_loading():
    """Test that schemas load correctly from MCP."""
    
    rprint(Panel("[bold cyan]Testing Dynamic Schema Loading[/bold cyan]", border_style="cyan"))
    
    # Initialize schema manager
    async with NotionMCPClient() as mcp:
        manager = await initialize_schemas(mcp)
    
    # Display loaded databases
    rprint(f"\n[green]✓ Loaded {len(manager.database_names)} databases[/green]\n")
    
    # Create table of databases
    table = Table(title="Available Databases", show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan")
    table.add_column("Title Property")
    table.add_column("Properties", style="dim")
    table.add_column("Select Props", style="yellow")
    
    for name in sorted(manager.database_names):
        schema = manager.get_schema(name)
        if schema:
            prop_count = len(schema.properties)
            select_count = len(schema.get_select_properties())
            table.add_row(
                name,
                schema.title_property,
                str(prop_count),
                str(select_count)
            )
    
    rprint(table)
    
    # Test prompt generation
    rprint("\n[bold]Generated Parser Prompt (excerpt):[/bold]\n")
    prompt = manager.generate_parser_prompt()
    # Show first 3 databases
    lines = prompt.split("\n\n")[:3]
    for line in lines:
        rprint(f"[dim]{line}[/dim]")
    rprint("[dim]...[/dim]\n")
    
    # Test specific database info
    test_db = "zettelkasten"
    rprint(f"\n[bold]Schema Details: {test_db}[/bold]")
    schema = manager.get_schema(test_db)
    if schema:
        rprint(f"  Title property: {schema.title_property}")
        rprint(f"  Description: {schema.description}")
        
        # Show select properties with options
        selects = schema.get_select_properties()
        if selects:
            rprint("  Select properties:")
            for prop_name, prop in list(selects.items())[:2]:
                opts = prop.options[:5]
                rprint(f"    - {prop_name}: {opts}")
    
    rprint("\n[green]✓ Schema test complete![/green]")


async def test_parser_with_schemas():
    """Test the parser with dynamic schemas."""
    from src.notion_assistant.parsers.nl_parser import NaturalLanguageParser
    
    rprint(Panel("[bold cyan]Testing Parser with Dynamic Schemas[/bold cyan]", border_style="cyan"))
    
    # Initialize schemas
    async with NotionMCPClient() as mcp:
        manager = await initialize_schemas(mcp)
    
    # Create parser
    parser = NaturalLanguageParser(schema_manager=manager)
    
    rprint(f"\n[green]Available databases:[/green] {', '.join(parser.get_available_databases())}\n")
    
    # Test parsing
    test_inputs = [
        "Create a note about dynamic schemas with tags python, mcp",
        "Ate oatmeal for breakfast",
        "Finished the API integration task",
    ]
    
    for user_input in test_inputs:
        rprint(f"[yellow]Input:[/yellow] {user_input}")
        result = await parser.parse(user_input)
        
        for intent in result.intents:
            rprint(f"  → [{intent.action.value}] {intent.database}: {intent.title or '(no title)'}")
            if intent.properties:
                rprint(f"    Properties: {intent.properties}")
        rprint()
    
    rprint("[green]✓ Parser test complete![/green]")


async def main():
    """Run all tests."""
    await test_schema_loading()
    rprint("\n" + "="*60 + "\n")
    await test_parser_with_schemas()


if __name__ == "__main__":
    asyncio.run(main())
