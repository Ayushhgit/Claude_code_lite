from core.agent import init_messages, run_turn
import os
from dotenv import load_dotenv
from utils.ui import console
from rich.panel import Panel
from rich.markdown import Markdown

load_dotenv()

def main():
    path = os.getenv("FOLDER_PATH")

    if not path:
        console.print("[bold red]FOLDER_PATH not set in .env[/bold red]")
        return

    messages = init_messages(path)
    
    console.print(Panel(f"Agent initialized in [bold green]{path}[/bold green]. Type 'exit' or 'quit' to close.", title="[bold cyan]Agent Startup", border_style="cyan"))

    while True:
        try:
            instruction = console.input("\n[bold cyan]What do you want to change?[/bold cyan]\n> ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold red]Exiting...[/bold red]")
            break
            
        if not instruction.strip():
            continue
            
        if instruction.strip().lower() in ["exit", "quit"]:
            console.print("[bold red]Exiting...[/bold red]")
            break

        with console.status("[bold green]Agent is thinking and acting...", spinner="dots"):
            output = run_turn(messages, instruction)

        console.print("\n")
        console.print(Panel(Markdown(output), title="[bold blue]Agent Finished", border_style="blue"))


if __name__ == "__main__":
    main()