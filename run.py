"CLI for running the Notion Assistant."
import asyncio
from rich.prompt import Prompt
from rich.console import Console
from rich.panel import Panel
from src.notion_assistant.agent import NotionAssistant

async def main():
    console = Console()
    assistant = NotionAssistant()
    
    console.print(Panel(
        "[bold cyan]Notion Assistant[/bold cyan]\n\n"
        "Natural language interface to your Notion workspace.\n"
        "Now supports multi-intent parsing!\n\n"
        "[bold]Try:[/bold]\n"
        "  • Create a note about X with tags Y, Z\n"
        "  • Ate breakfast, did 30 min cardio, finished task\n"
        "  • Search for notes about machine learning\n\n"
        "[dim]Using GPT-4o-mini with auto-escalation[/dim]\n\n"
        "Type 'quit' to exit.",
        border_style="cyan"
    ))
    
    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
            
            if user_input.lower() in ["quit", "exit", "q"]:
                console.print("[yellow]Goodbye! 👋[/yellow]")
                break
            
            if not user_input.strip():
                continue
            
            await assistant.process(user_input)
        
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type 'quit' to exit.[/yellow]")
            continue
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
