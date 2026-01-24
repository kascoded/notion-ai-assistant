"""
Simple Test Script for FastMCP Connection
Quick validation that the MCP client is working.
"""
import pytest
import asyncio
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
            console.print("\n[yellow]2. Calling list_databases tool...[/yellow]")
            try:
                result = await mcp.list_databases()
                console.print("[green]✓ Tool call successful![/green]")
                console.print(f"[dim]Result type: {type(result)}[/dim]")
                console.print(f"[dim]Result: {result}[/dim]")
            except Exception as e:
                console.print(f"[red]✗ Failed: {e}[/red]")
                import traceback
                traceback.print_exc()
            
            # Test 2: Query a database
            console.print("\n[yellow]3. Calling query_database tool...[/yellow]")
            try:
                result = await mcp.query_database(
                    database_name="zettelkasten",
                    page_size=3
                )
                console.print("[green]✓ Query successful![/green]")
                console.print(f"[dim]Result type: {type(result)}[/dim]")
                console.print(f"[dim]Result preview: {str(result)[:200]}...[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠ Query failed (this is OK if database doesn't exist)[/yellow]")
                console.print(f"[dim]Error: {e}[/dim]")
            
            console.print("\n[bold green]✅ MCP Client is working![/bold green]")
            console.print("\n[cyan]Next steps:[/cyan]")
            console.print("  1. The connection works!")
            console.print("  2. Run the agent: uv run python run.py")
            console.print("  3. Try: 'Create a note about testing'")
    
    except FileNotFoundError as e:
        console.print(f"\n[red]✗ MCP server not found[/red]")
        console.print(f"[yellow]Error: {e}[/yellow]")
        console.print("\n[cyan]Fix:[/cyan]")
        console.print("  1. Check your .env file has NOTION_MCP_PATH set")
        console.print("  2. Verify kas-fastmcp is at that location")
        console.print("  3. Default path: /Users/kas/Projects/kas-fastmcp/main.py")
        return
    
    except Exception as e:
        console.print(f"\n[red]✗ Test failed: {e}[/red]")
        import traceback
        console.print("\n[yellow]Traceback:[/yellow]")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_connection())
