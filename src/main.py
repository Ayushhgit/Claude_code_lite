from core.agent import init_messages, run_turn, _estimate_tokens
import os
import subprocess
from dotenv import load_dotenv
from utils.ui import console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.rule import Rule
from rich.table import Table
from rich import box

load_dotenv()

BANNER = r"""
██████╗ ███████╗██╗   ██╗██╗
██╔══██╗██╔════╝██║   ██║██║
██████╔╝█████╗  ██║   ██║██║
██╔══██╗██╔══╝  ╚██╗ ██╔╝██║
██║  ██║███████╗ ╚████╔╝ ██║
╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚═╝

        ⚡ R E V I ⚡
"""

HELP_TEXT = """
## Slash Commands

| Command     | Description                              |
|-------------|------------------------------------------|
| `/help`     | Show this help menu                      |
| `/clear`    | Reset context window                     |
| `/compact`  | Force-compact context to save tokens     |
| `/status`   | Show session stats                       |
| `/undo`     | Git undo last commit                     |
| `/diff`     | Show uncommitted git changes             |
| `/commit`   | Auto-commit all changes                  |
| `/git <cmd>`| Run any git command                      |
| `exit`      | Quit the agent                           |
"""

def _git_cmd(path, cmd):
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            f"git {cmd}", shell=True, cwd=path,
            capture_output=True, text=True, timeout=15
        )
        return (result.stdout + result.stderr).strip() or "Done (no output)."
    except Exception as e:
        return f"Git error: {e}"

def main():
    path = os.getenv("FOLDER_PATH")

    if not path:
        console.print("[bold red]✗ FOLDER_PATH not set in .env[/bold red]")
        return

    messages = init_messages(path)
    project_name = os.path.basename(path)
    turn_count = 0
    total_tokens_used = 0
    
    # Check git status
    git_branch = _git_cmd(path, "branch --show-current") or "N/A"
    
    # Startup
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print(Rule(style="cyan"))
    console.print(f"  [bold white]Workspace:[/bold white]  [green]{path}[/green]")
    console.print(f"  [bold white]Project:[/bold white]    [green]{project_name}[/green]")
    console.print(f"  [bold white]Git:[/bold white]        [green]{git_branch}[/green]")
    console.print(f"  [bold white]Commands:[/bold white]   [dim]Type /help for all commands[/dim]")
    console.print(Rule(style="cyan"))
    console.print()

    while True:
        try:
            instruction = console.input(f"[bold cyan]{project_name}[/bold cyan] [bold white]>[/bold white] ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold red]✗ Session ended.[/bold red]")
            break
            
        cmd = instruction.strip().lower()
        
        if not cmd:
            continue
            
        if cmd in ["exit", "quit"]:
            console.print("[bold red]✗ Goodbye![/bold red]")
            break
        
        # ── Slash Commands ──
        if cmd == "/help":
            console.print(Panel(Markdown(HELP_TEXT), title="[bold cyan]Help", border_style="cyan"))
            continue
        
        if cmd == "/clear":
            messages = init_messages(path)
            turn_count = 0
            console.print("[bold green]✓ Context cleared.[/bold green]\n")
            continue
        
        if cmd == "/compact":
            from core.agent import prune_messages
            before = _estimate_tokens(messages)
            pruned = prune_messages(messages)
            messages.clear()
            messages.extend(pruned)
            after = _estimate_tokens(messages)
            console.print(f"[bold green]✓ Compacted: {before} → {after} tokens[/bold green]\n")
            continue
            
        if cmd == "/status":
            table = Table(title="Session Status", box=box.ROUNDED, border_style="cyan")
            table.add_column("Metric", style="bold white")
            table.add_column("Value", style="green")
            table.add_row("Turns", str(turn_count))
            table.add_row("Messages in Context", str(len(messages)))
            table.add_row("Context Tokens (~)", str(_estimate_tokens(messages)))
            table.add_row("Total Tokens Used (~)", str(total_tokens_used))
            table.add_row("Git Branch", git_branch)
            table.add_row("Workspace", path)
            console.print(table)
            console.print()
            continue
        
        if cmd == "/undo":
            output = _git_cmd(path, "reset --soft HEAD~1")
            console.print(f"[bold yellow]↩ Undo: {output}[/bold yellow]\n")
            continue
        
        if cmd == "/diff":
            output = _git_cmd(path, "diff --stat")
            if not output or "fatal" in output:
                output = "No uncommitted changes."
            console.print(Panel(output, title="[bold yellow]Git Diff", border_style="yellow"))
            continue
        
        if cmd == "/commit":
            _git_cmd(path, "add -A")
            output = _git_cmd(path, 'commit -m "auto: agent session checkpoint"')
            console.print(f"[bold green]✓ {output}[/bold green]\n")
            continue
        
        if cmd.startswith("/git "):
            git_subcmd = instruction.strip()[5:]
            output = _git_cmd(path, git_subcmd)
            console.print(Panel(output, title=f"[bold yellow]git {git_subcmd}", border_style="yellow"))
            continue
        
        # ── Normal Agent Turn ──
        turn_count += 1
        console.print()
        console.print(Rule(f"[bold white] Turn {turn_count} [/bold white]", style="dim"))
        console.print()

        output = run_turn(messages, instruction)
        total_tokens_used += _estimate_tokens(messages)

        console.print()
        console.print(Panel(
            Markdown(output),
            title="[bold blue]◆ Agent Response",
            border_style="blue",
            box=box.ROUNDED,
            padding=(1, 2)
        ))
        console.print()


if __name__ == "__main__":
    main()