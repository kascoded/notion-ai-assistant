"""
Test script for MCP client transport configuration.
Run: uv run python test_transport.py
"""
import asyncio
import os
from rich import print as rprint
from rich.panel import Panel

from src.notion_assistant.clients.mcp_client import NotionMCPClient


async def test_transport_detection():
    """Test that transport is correctly detected from configuration."""
    
    rprint(Panel("[bold cyan]Testing MCP Transport Detection[/bold cyan]", border_style="cyan"))
    
    # Show current environment
    rprint("\n[bold]Current Environment:[/bold]")
    rprint(f"  NOTION_MCP_URL: {os.getenv('NOTION_MCP_URL', '(not set)')}")
    rprint(f"  NOTION_MCP_PATH: {os.getenv('NOTION_MCP_PATH', '(not set)')}")
    rprint(f"  NOTION_MCP_TRANSPORT: {os.getenv('NOTION_MCP_TRANSPORT', '(not set)')}")
    rprint(f"  NOTION_MCP_TOKEN: {'(set)' if os.getenv('NOTION_MCP_TOKEN') else '(not set)'}")
    
    # Test auto-detection
    rprint("\n[bold]Testing Auto-Detection:[/bold]")
    
    try:
        client = NotionMCPClient()
        rprint(f"  Connection: {client.connection_info}")
        rprint(f"  Is Remote: {client.is_remote}")
        
        # Try to connect
        rprint("\n[bold]Testing Connection:[/bold]")
        async with client as c:
            rprint("[green]  ✓ Connected successfully![/green]")
            
            # Quick test - list databases
            result = await c.list_databases()
            db_count = result.get("count", len(result.get("data_sources", [])))
            rprint(f"[green]  ✓ Found {db_count} databases[/green]")
    
    except FileNotFoundError as e:
        rprint(f"[red]  ✗ File not found: {e}[/red]")
    except ValueError as e:
        rprint(f"[red]  ✗ Configuration error: {e}[/red]")
    except Exception as e:
        rprint(f"[red]  ✗ Connection failed: {e}[/red]")
        import traceback
        traceback.print_exc()


async def test_explicit_transports():
    """Test explicit transport configurations."""
    
    rprint(Panel("[bold cyan]Testing Explicit Transports[/bold cyan]", border_style="cyan"))
    
    # Test 1: Explicit STDIO
    rprint("\n[bold]1. Explicit STDIO Transport:[/bold]")
    path = os.getenv("NOTION_MCP_PATH")
    if path:
        try:
            client = NotionMCPClient(path=path, transport="stdio")
            rprint(f"  Path: {path}")
            async with client as c:
                rprint("[green]  ✓ STDIO connection works![/green]")
        except Exception as e:
            rprint(f"[red]  ✗ STDIO failed: {e}[/red]")
    else:
        rprint("[yellow]  ⚠ NOTION_MCP_PATH not set, skipping STDIO test[/yellow]")
    
    # Test 2: Explicit HTTP (if URL set)
    rprint("\n[bold]2. Explicit HTTP Transport:[/bold]")
    url = os.getenv("NOTION_MCP_URL")
    if url:
        try:
            client = NotionMCPClient(url=url, transport="http")
            rprint(f"  URL: {url}")
            async with client as c:
                rprint("[green]  ✓ HTTP connection works![/green]")
        except Exception as e:
            rprint(f"[red]  ✗ HTTP failed: {e}[/red]")
    else:
        rprint("[yellow]  ⚠ NOTION_MCP_URL not set, skipping HTTP test[/yellow]")
        rprint("[dim]  To test remote: export NOTION_MCP_URL=https://your-server.com/mcp[/dim]")


async def main():
    """Run all transport tests."""
    await test_transport_detection()
    rprint("\n" + "="*60 + "\n")
    await test_explicit_transports()
    
    rprint("\n[bold green]Transport tests complete![/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
