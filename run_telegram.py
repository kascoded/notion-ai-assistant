#!/usr/bin/env python3
"""
Run the Telegram bot for Notion Assistant.

Usage:
    python run_telegram.py
    
    # Or with uv
    uv run python run_telegram.py

Environment Variables Required:
    TELEGRAM_BOT_TOKEN - Get from @BotFather on Telegram
    
Optional:
    TELEGRAM_ALLOWED_USERS - Comma-separated user IDs for allowlist
    
Example .env:
    TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    TELEGRAM_ALLOWED_USERS=123456789,987654321
"""
import sys
import logging
from rich.console import Console
from rich.panel import Panel

console = Console()

def main():
    # Show startup banner
    console.print(Panel(
        "[bold cyan]Notion Assistant - Telegram Bot[/bold cyan]\n\n"
        "Starting bot interface...\n"
        "Press Ctrl+C to stop.",
        border_style="cyan"
    ))
    
    try:
        from src.notion_assistant.interfaces.telegram_bot import run_bot
        run_bot()
    except ImportError as e:
        console.print(f"[red]Import error: {e}[/red]")
        console.print("\n[yellow]Make sure you've installed dependencies:[/yellow]")
        console.print("  uv add python-telegram-bot")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        console.print("\n[yellow]Make sure you've set up your .env file:[/yellow]")
        console.print("  TELEGRAM_BOT_TOKEN=your-token-from-botfather")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
