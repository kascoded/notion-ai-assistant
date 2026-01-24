"""
Test Script for FastMCP Connection
Quick validation that everything is working.
"""
import pytest
import asyncio
import sys
from pathlib import Path

from src.notion_assistant.clients.mcp_client import NotionMCPClient
from rich.console import Console
from rich.panel import Panel

console = Console()


@pytest.mark.asyncio
async def test_connection():
    """Test basic connection to MCP server."""
    console.print(Panel(
        "[bold cyan]Testing FastMCP Connection[/bold cyan]",
        border_style="cyan"
    ))
    
    try:
        console.print("\n[yellow]1. Connecting to MCP server...[/yellow]")
        
        async with NotionMCPClient() as mcp:
            console.print("[green]✓ Connected successfully![/green]")
            
            # Test 1: List databases
            console.print("\n[yellow]2. Listing databases...[/yellow]")
            result = await mcp.list_databases()
            
            # Access the underlying data from the CallToolResult object
            # Assuming CallToolResult has a .data attribute containing the actual dictionary
            response_data = result.data if hasattr(result, 'data') else result 
            
            data_sources = response_data.get("data_sources", [])
            db_names = [ds.get("title", "Untitled") for ds in data_sources]
            console.print(f"[green]✓ Listed databases successfully[/green]")
            console.print(f"  Databases found: {', '.join(db_names) or 'None'}")

            
            # Test 2: Query a database (first 3 items)
            if db_names:
                db_name = "zettelkasten"  # Change to your database name
                console.print(f"\n[yellow]3. Querying '{db_name}' database...[/yellow]")
                
                try:
                    result = await mcp.query_database(
                        database_name=db_name,
                        page_size=3
                    )
                    
                    console.print(f"[green]✓ Query successful[/green]")
                    console.print(f"  Result: {str(result)[:100]}...")  # Show first 100 chars
                
                except Exception as e:
                    console.print(f"[yellow]⚠ Query failed (database may not exist): {e}[/yellow]")
                    console.print(f"[yellow]  Configure your database in kas-fastmcp/databases.yaml[/yellow]")
            
            console.print("\n[bold green]✅ All tests passed![/bold green]")
            console.print("\n[cyan]Next steps:[/cyan]")
            console.print("  1. Run the agent: python run.py")
            console.print("  2. Try: 'Create a note about testing with tags test, demo'")
            
    except FileNotFoundError as e:
        console.print(f"\n[red]✗ MCP server not found[/red]")
        console.print(f"[yellow]Error: {e}[/yellow]")
        console.print("\n[cyan]Fix:[/cyan]")
        console.print("  1. Check your .env file has NOTION_MCP_PATH set")
        console.print("  2. Verify kas-fastmcp is at that location")
        console.print("  3. Default path: /Users/kas/Projects/kas-fastmcp/main.py")
        sys.exit(1)
    
    except Exception as e:
        console.print(f"\n[red]✗ Test failed: {e}[/red]")
        import traceback
        console.print("\n[yellow]Traceback:[/yellow]")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_connection())
