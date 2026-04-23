from core.agent import init_messages, run_turn, _estimate_tokens
import os
import sys
import time
import random
import subprocess
from dotenv import load_dotenv
from utils.ui import console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.rule import Rule
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich import box

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style as PTStyle

load_dotenv()

BANNER = r"""
██████╗ ███████╗██╗   ██╗██╗
██╔══██╗██╔════╝██║   ██║██║
██████╔╝█████╗  ██║   ██║██║
██╔══██╗██╔══╝  ╚██╗ ██╔╝██║
██║  ██║███████╗ ╚████╔╝ ██║
╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚═╝
"""

TAGLINE = "⚡ R E V I ⚡"

TIPS = [
    "Tip: Use /help to see all available commands",
    "Tip: Type /status to see your session stats at any time",
    "Tip: Use /compact to free up context space when things get slow",
    "Tip: The agent remembers your preferences in .agent_memory.md",
    "Tip: Use /undo to rollback the last git commit instantly",
    "Tip: Press Enter after a response to skip feedback",
    "Tip: The agent can search arXiv papers for ML references",
    "Tip: Say 'f' in the feedback prompt to auto-fix the last response",
    "Tip: The agent auto-heals broken code when it detects errors",
    "Tip: Use /diff to see what the agent changed before committing",
]

GREETINGS = [
    "Ready to build something extraordinary.",
    "Let's write some beautiful code together.",
    "Your AI pair programmer is online.",
    "Warmed up and ready to ship.",
    "All systems nominal. Let's go.",
    "Context loaded. Brain initialized. Let's cook.",
    "Standing by for your instructions, captain.",
    "I've scanned the codebase. What shall we improve?",
    "Time to turn coffee into code.",
    "Another day, another deploy. What's the plan?",
]

THINKING_VERBS = [
    "Analyzing the codebase",
    "Studying the architecture",
    "Crafting the perfect solution",
    "Reasoning about the problem",
    "Exploring possible approaches",
    "Thinking deeply",
    "Mapping out the plan",
    "Searching for the best pattern",
    "Designing the implementation",
    "Building a mental model",
]

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

SLASH_COMMANDS = {
    "/help":    "Show all available commands",
    "/clear":   "Reset context window and start fresh",
    "/compact": "Force-compact context to save tokens",
    "/status":  "Show session stats (turns, tokens, git branch)",
    "/undo":    "Git soft-reset the last commit",
    "/diff":    "Show uncommitted git changes",
    "/commit":  "Auto-commit all current changes",
    "/git ":    "Run any git command (e.g. /git log -5)",
    "exit":     "Quit the agent",
}

class SlashCompleter(Completer):
    """Auto-suggest slash commands when user types /."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd, desc in SLASH_COMMANDS.items():
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=HTML(f"<b>{cmd}</b>"),
                        display_meta=desc,
                    )

# Style for the prompt_toolkit input
PT_STYLE = PTStyle.from_dict({
    "prompt":      "#00d7ff bold",
    "arrow":       "#ffffff bold",
    "completion-menu.completion":          "bg:#1e1e2e #cdd6f4",
    "completion-menu.completion.current":  "bg:#89b4fa #1e1e2e bold",
    "completion-menu.meta.completion":          "bg:#313244 #a6adc8 italic",
    "completion-menu.meta.completion.current":  "bg:#89b4fa #1e1e2e italic",
})

def _typewriter(text, style="bold cyan", delay=0.02):
    """Print text with a typewriter animation."""
    for char in text:
        console.print(char, end="", style=style)
        time.sleep(delay)
    console.print()

def _animated_startup(path, project_name, git_branch):
    """Show a fancy animated startup sequence."""
    # Banner with color fade
    lines = BANNER.strip().split("\n")
    colors = ["bold blue", "bold cyan", "bold green", "bold cyan", "bold blue", "bold magenta"]
    for i, line in enumerate(lines):
        console.print(line, style=colors[i % len(colors)])
        time.sleep(0.05)
    
    # Tagline typewriter
    console.print()
    _typewriter(f"        {TAGLINE}", style="bold white", delay=0.04)
    console.print()
    
    # Info panel with loading dots
    steps = [
        ("Scanning workspace", f"{path}"),
        ("Detecting project", f"{project_name}"),
        ("Checking git", f"{git_branch}"),
        ("Loading memory", ".agent_memory.md"),
        ("Initializing tools", "22 tools ready"),
    ]
    
    for label, value in steps:
        console.print(f"  [dim]●[/dim] [bold white]{label}...[/bold white] [green]{value}[/green]")
        time.sleep(0.12)
    
    console.print()
    console.print(Rule(style="cyan"))
    
    # Random greeting
    greeting = random.choice(GREETINGS)
    tip = random.choice(TIPS)
    console.print(f"\n  [bold white]{greeting}[/bold white]")
    console.print(f"  [dim]{tip}[/dim]\n")
    console.print(Rule(style="cyan"))
    console.print()

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
    
    # Animated Startup
    _animated_startup(path, project_name, git_branch)

    # Create the prompt session with autocomplete
    session = PromptSession(
        completer=SlashCompleter(),
        style=PT_STYLE,
        complete_while_typing=True,
    )

    while True:
        try:
            instruction = session.prompt(
                [("class:prompt", f"{project_name}"), ("class:arrow", " > ")],
                multiline=False,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold red]✗ Session ended.[/bold red]")
            break
            
        cmd = instruction.strip().lower()
        
        if not cmd:
            continue
            
        if cmd in ["exit", "quit"]:
            # Fun goodbye animation
            goodbyes = ["See you next deploy! 🚀", "Happy coding! ✨", "Until next time, captain. 🫡", "May your builds always pass. 💚"]
            console.print(f"\n  [bold cyan]{random.choice(goodbyes)}[/bold cyan]\n")
            break
        
        # ── Slash Commands ──
        if cmd == "/help":
            console.print(Panel(Markdown(HELP_TEXT), title="[bold cyan]⌘ Help", border_style="cyan"))
            continue
        
        if cmd == "/clear":
            messages = init_messages(path)
            turn_count = 0
            console.print("[bold green]✓ Context cleared. Fresh start![/bold green]\n")
            continue
        
        if cmd == "/compact":
            from core.agent import prune_messages
            before = _estimate_tokens(messages)
            pruned = prune_messages(messages)
            messages.clear()
            messages.extend(pruned)
            after = _estimate_tokens(messages)
            console.print(f"[bold green]✓ Compacted: {before} → {after} tokens (freed ~{before - after})[/bold green]\n")
            continue
            
        if cmd == "/status":
            table = Table(title="⚡ Session Status", box=box.ROUNDED, border_style="cyan")
            table.add_column("Metric", style="bold white")
            table.add_column("Value", style="green")
            table.add_row("Turns Completed", str(turn_count))
            table.add_row("Messages in Context", str(len(messages)))
            table.add_row("Context Tokens (~)", f"{_estimate_tokens(messages):,}")
            table.add_row("Total Tokens Used (~)", f"{total_tokens_used:,}")
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
            console.print(Panel(output, title="[bold yellow]📝 Git Diff", border_style="yellow"))
            continue
        
        if cmd == "/commit":
            _git_cmd(path, "add -A")
            output = _git_cmd(path, 'commit -m "auto: agent session checkpoint"')
            console.print(f"[bold green]✓ {output}[/bold green]\n")
            continue
        
        if cmd.startswith("/git "):
            git_subcmd = instruction.strip()[5:]
            output = _git_cmd(path, git_subcmd)
            console.print(Panel(output, title=f"[bold yellow]📌 git {git_subcmd}", border_style="yellow"))
            continue
        
        # ── Normal Agent Turn ──
        turn_count += 1
        console.print()
        
        # Animated turn header
        verb = random.choice(THINKING_VERBS)
        console.print(Rule(f"[bold white] Turn {turn_count} [/bold white]", style="dim"))
        console.print(f"  [dim italic]{verb}...[/dim italic]\n")

        output = run_turn(messages, instruction)
        total_tokens_used += _estimate_tokens(messages)

        console.print()
        console.print(Panel(
            Markdown(output),
            title="[bold blue]◆ Agent Response",
            subtitle=f"[dim]turn {turn_count} • ~{_estimate_tokens(messages):,} tokens[/dim]",
            border_style="blue",
            box=box.ROUNDED,
            padding=(1, 2)
        ))
        console.print()


if __name__ == "__main__":
    main()