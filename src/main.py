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
from rich import box

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style as PTStyle

load_dotenv()

BANNER = r"""
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

▓▓▓▓▓                ██████╗ ███████╗██╗   ██╗██╗      ██████╗██╗     ██╗
    ▓▓▓▓             ██╔══██╗██╔════╝██║   ██║██║     ██╔════╝██║     ██║
        ▓▓▓▓         ██████╔╝█████╗  ██║   ██║██║     ██║     ██║     ██║
            ▓▓▓▓     ██╔══██╗██╔══╝  ╚██╗ ██╔╝██║     ██║     ██║     ██║
        ▓▓▓▓         ██║  ██║███████╗ ╚████╔╝ ██║     ╚██████╗███████╗██║
    ▓▓▓▓             ╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚═╝      ╚═════╝╚══════╝╚═╝
▓▓▓▓▓

░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
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
    "Tip: Use /map to see the full AST architecture of your codebase",
    "Tip: The agent auto-plans complex tasks using the Architect persona",
    "Tip: Use /tasks to see what the agent is currently working on",
    "Tip: The Reviewer agent validates code quality on complex tasks",
    "Tip: Use /sandbox to check Docker sandboxing status",
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
| `/map`      | Show AST-based codebase architecture     |
| `/scan`     | Deep scan codebase + build brain document|
| `/tasks`    | Show current task scratchpad             |
| `/plan`     | Show the active execution plan           |
| `/sandbox`  | Show Docker sandbox status               |
| `/verify`   | Run full project verification             |
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
    "/map":     "Show AST-based codebase architecture map",
    "/scan":    "Deep scan codebase and build brain document",
    "/tasks":   "Show current task scratchpad",
    "/plan":    "Show the active execution plan",
    "/sandbox": "Show Docker sandbox status",
    "/verify":  "Run full project verification (compile + lint + tests)",
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

def _typewriter(text, delay=0.025):
    """Print text with a typewriter animation using stdout directly."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")
    sys.stdout.flush()

def _animated_startup(path, project_name, git_branch):
    """Show a fancy animated startup sequence."""
    # Banner with color fade
    lines = BANNER.strip().split("\n")
    colors = ["bold blue", "bold cyan", "bold green", "bold cyan", "bold blue", "bold magenta"]
    for i, line in enumerate(lines):
        console.print(line, style=colors[i % len(colors)])
        time.sleep(0.06)
    
    # Tagline typewriter
    console.print()
    _typewriter(f"        {TAGLINE}", delay=0.04)
    console.print()
    
    # Info panel with animated loading dots
    steps = [
        ("🔍 Scanning workspace", f"{path}"),
        ("📂 Detecting project", f"{project_name}"),
        ("🔗 Checking git", f"{git_branch}"),
        ("🧠 Loading memory", ".agent_memory.md"),
        ("🔧 Initializing tools", "38 tools ready"),
    ]
    
    for label, value in steps:
        # Animated dots
        sys.stdout.write(f"  {label}")
        sys.stdout.flush()
        for _ in range(3):
            time.sleep(0.1)
            sys.stdout.write(".")
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print(f"    [green]-> {value}[/green]")
        time.sleep(0.05)
    
    console.print()
    console.print(Rule(style="cyan"))
    
    # Random greeting + tip
    greeting = random.choice(GREETINGS)
    tip = random.choice(TIPS)
    console.print(f"\n  [bold white]✦ {greeting}[/bold white]")
    console.print(f"  [dim italic]{tip}[/dim italic]\n")
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
            console.print(f"[bold green]>> Compacted: {before} -> {after} tokens (freed ~{before - after})[/bold green]\n")
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
        
        if cmd == "/map":
            console.print("  [dim]🧬 Building AST map...[/dim]")
            try:
                from core.repo_map import get_ast_repo_map
                ast_map = get_ast_repo_map(path)
                console.print(Panel(ast_map[:3000], title="[bold green]🧬 AST Repository Map", border_style="green"))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            continue
        
        if cmd == "/scan":
            console.print("  [bold cyan]🧠 Deep scanning entire codebase...[/bold cyan]")
            try:
                from core.codebase_brain import scan_codebase_tool
                result = scan_codebase_tool(path)
                console.print(Panel(result, title="[bold cyan]🧠 Codebase Brain", border_style="cyan"))
                # Re-init messages so brain is injected into system prompt
                messages = init_messages(path)
                console.print("  [green]✓ Brain loaded into context. I now know exactly where everything is.[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            continue
        
        if cmd == "/tasks":
            try:
                from core.scratchpad import get_tasks_tool
                tasks = get_tasks_tool()
                console.print(Panel(tasks, title="[bold cyan]📋 Task Scratchpad", border_style="cyan"))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            continue
        
        if cmd == "/dashboard" or cmd == "/daemon":
            console.print("[bold green]🚀 Starting REVI Command Center & CI/CD Webhook server at http://localhost:8000[/bold green]")
            import subprocess
            import sys
            import webbrowser
            # Run server in a completely separate process to isolate asyncio event loops 
            # and prevent prompt_toolkit/uvicorn conflicts on Windows
            subprocess.Popen([sys.executable, "-c", "from server.app import start_server; start_server()"], 
                             cwd=os.path.dirname(__file__))
            webbrowser.open("http://localhost:8000")
            continue
        
        if cmd == "/plan":
            try:
                from core.planner import load_plan, format_plan_for_context
                plan = load_plan(path)
                if plan:
                    console.print(Panel(format_plan_for_context(plan), title="[bold magenta]🏗️ Active Plan", border_style="magenta"))
                else:
                    console.print("[dim]No active plan. The Architect agent creates plans for complex tasks automatically.[/dim]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            continue
        
        if cmd == "/sandbox":
            try:
                from core.sandbox import sandbox_status_tool
                status = sandbox_status_tool()
                console.print(Panel(status, title="[bold blue]🐳 Sandbox Status", border_style="blue"))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            continue
        
        if cmd == "/verify":
            console.print("  [bold cyan]🔍 Running full project verification...[/bold cyan]")
            try:
                from core.verify import run_full_verification, format_verification_report
                report = run_full_verification(path)
                result_text = format_verification_report(report)
                border = "green" if report["overall"] == "PASS" else "red"
                console.print(Panel(result_text, title=f"[bold {border}]🔍 Verification Report", border_style=border))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
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