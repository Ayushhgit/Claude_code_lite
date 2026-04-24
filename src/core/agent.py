import os
import json
import time
import random
import threading
import sys

from llm.client import generate
from core.tools import TOOLS_SCHEMA, execute_tool
from utils.ui import console

import groq
import openai
import re
from llm.client import QuotaExhaustedError

# Fun spinner messages that cycle while the LLM is thinking
SPINNER_MESSAGES = [
    "Thinking… but in a cool way",
    "Consulting my inner vibes",
    "Vibing with the tokens",
    "Poking around the idea space",
    "Sniffing out a good answer",
    "Asking the brain gremlins",
    "Doing some light overthinking",
    "Pretending this is easy",
    "Connecting suspicious dots",
    "Squinting at the problem",
    "Running entirely legal computations",
    "Googling internally (don’t tell anyone)",
    "Making educated guesses",
    "Untangling spaghetti logic",
    "Whispering to the algorithms",
    "Summoning a decent response",
    "Cooking up something smart",
    "Applying questionable genius",
    "Almost sounding confident",
    "Finalizing something impressive-ish",
]

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

class _Spinner:
    """A threaded spinner with rotating fun messages."""
    def __init__(self):
        self._running = False
        self._thread = None
    
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        # Clear the spinner line
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()
    
    def _animate(self):
        msg = random.choice(SPINNER_MESSAGES)
        frame_idx = 0
        cycles = 0
        while self._running:
            frame = SPINNER_FRAMES[frame_idx % len(SPINNER_FRAMES)]
            display = f"\r  {frame} {msg}..."
            sys.stdout.write(display)
            sys.stdout.flush()
            time.sleep(0.08)
            frame_idx += 1
            cycles += 1
            # Change message every ~3 seconds
            if cycles % 38 == 0:
                sys.stdout.write("\r" + " " * 60 + "\r")
                sys.stdout.flush()
                msg = random.choice(SPINNER_MESSAGES)
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, *args):
        self.stop()

spinner = _Spinner()

def _safe_parse_json(raw: str) -> dict:
    """Try to parse JSON, auto-fixing common LLM mistakes."""
    # First try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    
    # Fix 1: Remove trailing commas before } or ]
    sanitized = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass
    
    # Fix 2: Replace single quotes with double quotes
    sanitized = sanitized.replace("'", '"')
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass
    
    # Fix 3: Escape unescaped newlines inside string values
    sanitized = re.sub(r'(?<!\\)\n', r'\\n', raw)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass
    
    # Give up, raise original error
    return json.loads(raw)

def _select_tools_for_intent(messages):
    """Dynamically select relevant tools based on the user's latest message.
    
    Small models fail with 24+ tools. This analyzes intent keywords and
    returns only the 8-12 tools relevant to the current task, keeping
    the CORE set always available.
    """
    from core.tools import CORE_TOOLS_SCHEMA
    
    # Get the latest user message
    user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user" and not msg.get("content", "").startswith("["):
            user_msg = msg.get("content", "").lower()
            break
    
    # Always start with core tools (cat, ls, edit_file, run_command, grep, 
    # get_repo_map, replace_in_file, ask_human, codebase_search, git_command)
    core_names = {t["function"]["name"] for t in CORE_TOOLS_SCHEMA}
    
    # Build a keyword → tool name mapping for advanced tools
    INTENT_MAP = {
        # Git operations
        "commit":     ["git_command"],
        "push":       ["git_command"],
        "branch":     ["git_command"],
        "merge":      ["git_command"],
        "git":        ["git_command"],
        # Search & discovery
        "search":     ["codebase_search", "semantic_search", "websearch"],
        "find":       ["codebase_search", "semantic_search", "grep"],
        "where":      ["codebase_search", "grep"],
        # ML & research
        "train":      ["run_command", "arxiv_search"],
        "model":      ["run_command", "arxiv_search"],
        "accuracy":   ["run_command", "arxiv_search"],
        "paper":      ["arxiv_search"],
        "arxiv":      ["arxiv_search"],
        "research":   ["arxiv_search", "websearch"],
        # Web
        "web":        ["websearch", "read_url"],
        "url":        ["read_url"],
        "http":       ["read_url"],
        "documentation": ["websearch", "read_url"],
        # File operations
        "delete":     ["delete_file"],
        "remove":     ["delete_file"],
        "create":     ["edit_file", "batch_edit_files"],
        "scaffold":   ["batch_edit_files"],
        "multiple files": ["batch_edit_files"],
        # Code understanding
        "symbol":     ["get_file_symbols"],
        "class":      ["get_file_symbols"],
        "function":   ["get_file_symbols", "codebase_search"],
        "index":      ["index_codebase", "semantic_search"],
        # Advanced editing
        "diff":       ["apply_diff"],
        "replace":    ["replace_in_file", "semantic_replace"],
        "refactor":   ["replace_in_file", "semantic_replace", "apply_diff"],
        # Background processes
        "server":     ["run_background_command", "read_terminal_output"],
        "background": ["run_background_command", "read_terminal_output"],
        "long":       ["run_background_command"],
        # v2: LSP Navigation
        "reference":  ["find_references", "go_to_definition"],
        "definition": ["go_to_definition", "find_references"],
        "usage":      ["find_references", "get_call_graph"],
        "caller":     ["get_call_graph"],
        "call graph": ["get_call_graph"],
        "subclass":   ["find_implementations"],
        "implement":  ["find_implementations"],
        "inherit":    ["find_implementations"],
        # v2: AST Map
        "architecture": ["get_ast_map"],
        "structure":  ["get_ast_map"],
        "skeleton":   ["get_ast_map"],
        "ast":        ["get_ast_map"],
        "map":        ["get_ast_map", "get_repo_map"],
        "overview":   ["get_ast_map", "get_repo_map"],
        # v2: Self-Heal
        "lint":       ["lint_check"],
        "test":       ["run_tests", "lint_check"],
        "fix":        ["lint_check", "run_tests"],
        "check":      ["lint_check", "run_tests"],
        # v2: Task Tracking
        "task":       ["create_task", "complete_task", "get_tasks"],
        "plan":       ["create_task", "get_tasks", "set_goal"],
        "todo":       ["create_task", "get_tasks"],
        "goal":       ["set_goal", "get_tasks"],
        "note":       ["add_note"],
        # v2: Sandbox
        "sandbox":    ["sandbox_status"],
        "docker":     ["sandbox_status"],
        "container":  ["sandbox_status"],
        # v2: Deep Scan
        "scan":       ["scan_codebase", "get_ast_map", "index_codebase"],
        "brain":      ["scan_codebase"],
        "understand":  ["scan_codebase", "get_ast_map"],
        # v2: Verification
        "verify":     ["verify_project", "lint_check", "run_tests"],
        "validate":   ["verify_project"],
        # GitHub integration
        "github":     ["github_comment", "github_pr_review"],
        "pr":         ["github_pr_review", "github_comment"],
        "pull request": ["github_pr_review", "github_comment"],
        "review":     ["github_pr_review"],
        "approve":    ["github_pr_review"],
        "comment":    ["github_comment", "github_pr_review"],
        "issue":      ["github_comment"],
    }
    
    # Collect extra tools based on keywords
    extra_names = set()
    for keyword, tools in INTENT_MAP.items():
        if keyword in user_msg:
            extra_names.update(tools)
    
    # Always include some extras for general use
    extra_names.update(["delete_file", "get_repo_map", "get_ast_map", "get_tasks", "scan_codebase", "verify_project"])
    
    # Build the final schema: core + intent-matched tools
    selected_names = core_names | extra_names
    selected = [t for t in TOOLS_SCHEMA if t["function"]["name"] in selected_names]
    
    # If nothing matched, fall back to core
    if not selected:
        return CORE_TOOLS_SCHEMA
    
    return selected

def _rescue_code_blocks(text):
    """
    Parse code blocks from a text-only LLM response.
    Returns list of (filename, code) pairs where a filename could be detected.
    Looks for patterns before each ``` block: **file.ext**, `file.ext`, file.ext:
    """
    results = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith('```'):
            # Collect code until closing fence
            code_lines = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith('```'):
                code_lines.append(lines[j])
                j += 1
            code = '\n'.join(code_lines).strip()

            # Try to find a filename in the preceding 3 lines
            filename = None
            for k in range(max(0, i - 3), i):
                prev = lines[k].strip()
                m = re.match(r'^(?:\*{1,2}|`)?([A-Za-z0-9_\-]+\.[a-zA-Z0-9]+)(?:\*{1,2}|`)?:?\s*$', prev)
                if m:
                    filename = m.group(1)
                    break

            if filename and code:
                results.append((filename, code))
            i = j + 1
        else:
            i += 1
    return results


def call_llm_with_tools(messages):
    bad_retries = 0
    rate_retries = 0
    retry_msg_count = 0  # Track how many error-correction messages we injected
    
    # Dynamic tool selection based on intent
    active_tools = _select_tools_for_intent(messages)
    tool_count = len(active_tools)
    tool_names = [t["function"]["name"] for t in active_tools]
    console.print(f"  [dim]🔧 {tool_count} tools loaded: {', '.join(tool_names[:6])}{'...' if tool_count > 6 else ''}[/dim]")
    
    while True:
        try:
            with spinner:
                message = generate(messages, tools=active_tools)
            # Success! Clean up any retry messages we injected
            if retry_msg_count > 0:
                for _ in range(retry_msg_count):
                    if messages and messages[-1].get("role") == "user" and "tool call failed" in messages[-1].get("content", "").lower():
                        messages.pop()
                retry_msg_count = 0
            bad_retries = 0
        except QuotaExhaustedError as e:
            provider = os.getenv("PROVIDER", "groq").upper()
            console.print(f"  [bold red]✗ {provider} quota exhausted.[/bold red] Switch provider or wait for quota reset.")
            console.print(f"  [dim]Tip: set PROVIDER=groq in .env to use Groq instead.[/dim]")
            return f"Error: {provider} API quota exhausted. Check billing/plan or switch PROVIDER in .env."
        except (groq.RateLimitError, openai.RateLimitError):
            wait_time = min(2 ** rate_retries * 5, 60)
            provider = os.getenv("PROVIDER", "groq").upper()
            console.print(f"  [bold yellow]⏳ {provider} rate limited. Waiting {wait_time}s...[/bold yellow]")
            time.sleep(wait_time)
            rate_retries += 1
            if rate_retries > 5:
                return f"Error: Repeatedly rate limited by {provider}. Wait a minute and try again."
            continue
        except groq.BadRequestError as e:
            error_msg = str(e)
            bad_retries += 1
            
            # Clean up any previous retry messages before adding new ones
            while retry_msg_count > 0 and messages and messages[-1].get("role") == "user" and "tool call failed" in messages[-1].get("content", "").lower():
                messages.pop()
                retry_msg_count -= 1
            
            if bad_retries >= 3:
                console.print(f"  [bold red][LLM Error full]: {error_msg}[/bold red]")
                # Last resort: text-only (NO tools)
                console.print("  [bold yellow]⚠ Falling back to text-only response (context preserved)...[/bold yellow]")
                try:
                    message = generate(messages, tools=None)
                    result = message.content.strip() if message.content else "Error: Agent could not generate a response."
                    # Preserve context by appending the response
                    messages.append({"role": "assistant", "content": result})
                    return result
                except Exception:
                    return "Error: LLM repeatedly failed. Please try a simpler request."
            
            if bad_retries >= 2:
                # Fallback: core tools only
                console.print("  [bold yellow]⚠ Retrying with reduced tool set (context preserved)...[/bold yellow]")
                from core.tools import CORE_TOOLS_SCHEMA
                try:
                    message = generate(messages, tools=CORE_TOOLS_SCHEMA)
                    bad_retries = 0
                    # Fall through to tool processing below
                except groq.BadRequestError:
                    console.print(f"  [bold red][LLM Error]: {error_msg[:100]}...[/bold red]")
                    continue
            else:
                console.print(f"  [bold red][LLM Error, retrying]: {error_msg[:300]}[/bold red]")
                messages.append({
                    "role": "user",
                    "content": f"Your last tool call failed validation. Use ONLY the exact parameter names from the tool schema. Do NOT add extra parameters. Error: {error_msg[:200]}"
                })
                retry_msg_count += 1
                continue

        if getattr(message, "tool_calls", None):
            import re
            if message.content:
                think_match = re.search(r'<thinking>(.*?)</thinking>', message.content, re.DOTALL)
                if think_match:
                    from rich.panel import Panel
                    console.print(Panel(
                        f"[dim italic]{think_match.group(1).strip()}[/dim italic]",
                        title="[dim]🧠 Thinking[/dim]",
                        border_style="dim",
                        padding=(0, 1)
                    ))
                    from utils.ui import broadcast_sync
                    broadcast_sync("thought", think_match.group(1).strip())
                    
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in message.tool_calls
                ]
            })
            
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    raw_args = tool_call.function.arguments
                    args = _safe_parse_json(raw_args)
                    broadcast_sync("tool", f"Executing: {tool_name}({raw_args})")
                    tool_result = execute_tool(tool_name, args)
                except Exception as e:
                    tool_result = f"Error executing tool (likely invalid JSON arguments): {e}"
                    
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": str(tool_result)
                })
                
                # SELF-HEALING: If run_command returned an error, inject an auto-fix prompt
                if tool_name in ("run_command", "run_background_command"):
                    result_lower = str(tool_result).lower()
                    error_signals = ['traceback', 'error:', 'exception', 'failed', 'syntaxerror', 'modulenotfounderror', 'importerror', 'nameerror', 'typeerror', 'exit code 1', 'exit code 2']
                    if any(sig in result_lower for sig in error_signals):
                        # Use self_heal to analyze the error
                        try:
                            from core.self_heal import analyze_command_output
                            analysis = analyze_command_output(str(tool_result))
                            if analysis["has_errors"]:
                                console.print(f"[bold red]  [Self-Heal] {analysis['error_type']}: {analysis['error_summary'][:80]}[/bold red]")
                                console.print(f"[dim]  Suggested: {analysis['suggested_action']}[/dim]")
                        except Exception:
                            console.print("[bold red]  [Self-Heal] Error detected in command output. Agent will attempt automatic fix...[/bold red]")
                
                # SELF-HEAL on file edits: auto-lint after writes
                if tool_name in ("edit_file", "replace_in_file", "apply_diff", "batch_edit_files"):
                    try:
                        from core.self_heal import check_and_heal
                        edited_path = args.get("path", "")
                        if edited_path and edited_path.endswith('.py'):
                            heal_report = check_and_heal(edited_path)
                            if heal_report.get("needs_fix") and heal_report.get("error_report"):
                                messages.append({
                                    "role": "user",
                                    "content": heal_report["error_report"]
                                })
                    except Exception:
                        pass
        else:
            content = message.content.strip() if message.content else ""
            # Model outputted code as text instead of using tools — attempt auto-rescue
            if "```" in content:
                rescued = _rescue_code_blocks(content)
                if rescued:
                    console.print(f"  [bold yellow]⚠ Model skipped tools. Auto-creating {len(rescued)} file(s)...[/bold yellow]")
                    for filename, code in rescued:
                        base = os.getenv("FOLDER_PATH", ".")
                        full_path = os.path.join(base, filename)
                        execute_tool("edit_file", {"path": full_path, "content": code})
                        console.print(f"  [green]✓ Created:[/green] {filename}")
                    return "Files created: " + ", ".join(f for f, _ in rescued)
                else:
                    # Can't extract filenames — push correction back and retry once
                    console.print("  [bold yellow]⚠ Model output code as text instead of using tools. Correcting...[/bold yellow]")
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "You output code as plain text. That does NOT create any files. "
                            "You MUST use the edit_file or batch_edit_files tool to create the files. "
                            "Do not write code in your response — call the tool instead."
                        )
                    })
                    continue
            return content


def init_messages(path):
    memory_path = os.path.join(path, ".agent_memory.md")
    memory_content = "No long-term memory recorded yet."
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                memory_content = f.read()
        except Exception:
            pass

# Try to load scratchpad context
    scratchpad_context = ""
    try:
        from core.scratchpad import get_scratchpad_context
        scratchpad_context = get_scratchpad_context(path)
    except Exception:
        pass

    # Try to load active plan context
    plan_context = ""
    try:
        from core.planner import load_plan, format_plan_for_context
        active_plan = load_plan(path)
        if active_plan:
            plan_context = format_plan_for_context(active_plan)
    except Exception:
        pass

    extra_context = ""
    if scratchpad_context:
        extra_context += f"\n\nACTIVE SCRATCHPAD:\n{scratchpad_context}"
    if plan_context:
        extra_context += f"\n\nACTIVE PLAN:\n{plan_context}"

    # Try to load brain context (deep codebase understanding)
    brain_context = ""
    try:
        from core.codebase_brain import get_brain_context
        brain_context = get_brain_context(path)
    except Exception:
        pass
    if brain_context:
        extra_context += f"\n\nCODEBASE BRAIN (deep understanding from last scan):\n{brain_context}"

    return [
        {
            "role": "system",
            "content": f"""You are an elite, autonomous AI software engineer. You work like a senior developer — methodical, systematic, and thorough. You NEVER rush. You ALWAYS understand before you act.

The root folder you are working in is: {path}

═══════════════════════════════════════════════════════════════
YOUR METHODOLOGY — Follow this EXACT workflow for EVERY task:
═══════════════════════════════════════════════════════════════

PHASE 1 — UNDERSTAND (mandatory before ANY code changes):
  Before writing or editing a SINGLE line of code, you MUST first understand the codebase:
  1. Run `get_ast_map` to see the full architecture (all classes, functions, imports, file structure).
  2. Read all relevant files with `cat` — do NOT guess what's inside a file. Read it.
  3. If the task involves a specific module, use `find_references` and `go_to_definition` to understand how it connects to other parts of the code.
  4. Use `get_call_graph` if you need to understand who calls what before refactoring.
  5. Check `get_tasks` to see if there's an active scratchpad from a previous turn.
  ONLY after you have a complete mental model of the relevant code should you proceed.

PHASE 2 — PLAN (for medium/complex tasks):
  For any task that touches more than 2 files or creates new modules:
  1. Use `set_goal` to declare the high-level objective.
  2. Use `create_task` for each distinct piece of work, ordered by dependency.
  3. Write your implementation approach in a `<thinking>` block:
     - What new files/functions need to be created?
     - What existing files need modification?
     - What is the dependency order? (foundation → implementation → integration → verification)
     - What could go wrong?
  The system automatically engages an Architect agent for complex tasks that creates a formal plan.

PHASE 3 — BUILD (systematic, module by module):
  Execute the plan step by step:
  1. Build each piece ONE AT A TIME. Do not try to create 10 files in parallel.
  2. After creating/editing each file, IMMEDIATELY run `lint_check` on it.
  3. If lint errors appear, fix them BEFORE moving to the next file.
  4. Use `complete_task` after each step so you stay oriented.
  5. For new files: use `edit_file` or `batch_edit_files`.
  6. For modifications to existing files: ALWAYS use `cat` to read first, then `replace_in_file` for single edits or `apply_diff` for multiple edits. NEVER blindly overwrite.
  7. Match the existing project's patterns — naming conventions, import style, file organization.

PHASE 4 — VERIFY (mandatory after ALL changes):
  After you believe you're done:
  1. Run `verify_project` — this runs ALL checks at once:
     - Compile check (py_compile on every .py file)
     - Import resolution (validates all imports resolve)
     - Lint check (syntax validation)
     - Test suite (if tests exist)
     - Tool schema consistency (if applicable)
  2. If any check fails, fix the issue and re-run `verify_project`.
  3. Repeat up to 3 times. If still broken, use `ask_human`.
  4. NEVER report success without verification passing.
  The system also auto-verifies after complex tasks — if it fails, you'll get the report automatically.

PHASE 5 — COMMIT (with proper messages):
  After verification passes:
  1. Use `git_command("add -A")` to stage changes.
  2. Use `git_command('commit -m "type(scope): description"')` with conventional commit format:
     - `feat(scope):` for new features
     - `fix(scope):` for bug fixes
     - `refactor(scope):` for restructuring
     - `docs(scope):` for documentation
  3. Include a multi-line commit body for significant changes.
  4. Only push if the user asks you to.

═══════════════════════════════════════════════════════════════
ENVIRONMENT RULES:
═══════════════════════════════════════════════════════════════
- You are on a WINDOWS machine. NEVER guess Unix paths like '/Users/...'.
- ALL tools use '{path}' as the working directory.
- When using `run_command`, use RELATIVE paths from '{path}'.
- For file tools (cat, edit_file), use relative paths from the root.

═══════════════════════════════════════════════════════════════
TOOL USAGE GUIDE:
═══════════════════════════════════════════════════════════════
UNDERSTANDING TOOLS (use these FIRST):
  - `get_ast_map` — See entire codebase skeleton (classes, methods, signatures). Use this before ANY task.
  - `cat` — Read a file's contents. ALWAYS read before editing.
  - `find_references` — Find all usages of a symbol (like IDE "Find All References").
  - `go_to_definition` — Find where something is defined (like IDE "Go to Definition").
  - `find_implementations` — Find subclasses/implementations of a class.
  - `get_call_graph` — See who calls a function. Critical before refactoring.
  - `get_file_symbols` — Quick overview of a file's classes and functions.
  - `codebase_search` — Combined semantic + regex search. Best for finding specific patterns.

EDITING TOOLS:
  - `edit_file` — Create or fully overwrite a file.
  - `replace_in_file` — Replace exact text in a file (for single targeted edits).
  - `apply_diff` — Apply multiple search/replace blocks to a file.
  - `batch_edit_files` — Create/overwrite multiple files at once (for scaffolding).

EXECUTION TOOLS:
  - `run_command` — Execute a shell command (with user approval for unsafe commands).
  - `run_background_command` — Start a long-running process (dev servers, etc.).
  - `lint_check` — Run linter on a Python file. USE AFTER EVERY EDIT.
  - `run_tests` — Run the project's test suite. USE AFTER ALL CHANGES.
  - `verify_project` — Run FULL verification (compile + imports + lint + tests + schema check). USE AFTER COMPLEX TASKS.
  - `scan_codebase` — Deep scan entire codebase and build persistent brain document. USE AT START OF SESSION.

PLANNING TOOLS:
  - `set_goal` — Declare the session's high-level objective.
  - `create_task` — Create a tracked task in the scratchpad.
  - `complete_task` — Mark a task done. Keeps you oriented across turns.
  - `add_subtask` — Break a task into smaller pieces.
  - `get_tasks` — View all current tasks.
  - `add_note` — Record observations or decisions for future reference.

GIT TOOLS:
  - `git_command` — Run git commands (status, add, commit, log, diff, etc.).

OTHER TOOLS:
  - `ask_human` — Ask the user a question when you're stuck or need a decision.
  - `websearch` — Search the internet for documentation or solutions.
  - `read_url` — Read a webpage.
  - `arxiv_search` — Search academic papers.

═══════════════════════════════════════════════════════════════
CRITICAL — TOOL-FIRST RULE (NEVER BREAK THIS):
═══════════════════════════════════════════════════════════════
NEVER output code, file contents, or implementations as plain text in your response.
If you need to create or edit a file, you MUST call edit_file or batch_edit_files.
If you need to run something, you MUST call run_command.
Outputting code as text does NOTHING — it does not create files. The user cannot see your
reasoning, only the results of your tool calls. A response with code blocks but no tool
calls is a FAILURE. Always act through tools, never through text.

═══════════════════════════════════════════════════════════════
THINKING PROTOCOL:
═══════════════════════════════════════════════════════════════
Before EVERY tool call, write a `<thinking>` block that includes:
1. What you currently understand about the problem
2. What you're about to do and WHY
3. What could go wrong
4. Your confidence level (high/medium/low)

═══════════════════════════════════════════════════════════════
SELF-HEALING PROTOCOL:
═══════════════════════════════════════════════════════════════
- After `run_command`: if the output has errors, IMMEDIATELY analyze the traceback, fix the code, and re-run. Never just report an error.
- After `edit_file`/`replace_in_file`: the system auto-lints Python files. If lint errors appear, fix them immediately.
- Max 3 fix attempts per error. If still broken, use `ask_human`.

═══════════════════════════════════════════════════════════════
MEMORY:
═══════════════════════════════════════════════════════════════
You have a persistent memory file at `.agent_memory.md`. Current contents:
--------------------------------------------------
{memory_content}
--------------------------------------------------
Update this file when you learn something important about the codebase, user preferences, or solve a tricky problem.
{extra_context}
"""
        }
    ]

def _estimate_tokens(messages):
    """Rough token estimate: ~4 chars per token."""
    total = 0
    for msg in messages:
        content = msg.get("content", "") or ""
        total += len(content) // 4
    return total

def _compress_tool_results(messages):
    """Compress large tool outputs to save context space."""
    MAX_TOOL_CHARS = 3000
    for msg in messages:
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if len(content) > MAX_TOOL_CHARS:
                # Keep first and last portion
                head = content[:1500]
                tail = content[-1000:]
                msg["content"] = f"{head}\n\n... [TRUNCATED {len(content) - 2500} chars to save context] ...\n\n{tail}"
    return messages

def _summarize_old_turns(messages):
    """Summarize old assistant messages into compact notes."""
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and i < len(messages) - 10:
            content = msg.get("content", "") or ""
            if len(content) > 500:
                msg["content"] = content[:400] + "\n\n[... response truncated for context efficiency ...]"
    return messages

def prune_messages(messages):
    """Claude Code-style context compaction."""
    MAX_TOKENS = 12000  # Keep well under most model limits
    
    # Work on a copy so the caller's .clear() doesn't wipe our result
    msgs = [m.copy() for m in messages]
    
    # Step 1: Compress large tool outputs
    msgs = _compress_tool_results(msgs)
    
    # Step 2: Summarize old assistant turns
    msgs = _summarize_old_turns(msgs)
    
    # Step 3: If still too large, drop oldest turns (keeping system + recent)
    tokens = _estimate_tokens(msgs)
    if tokens > MAX_TOKENS and len(msgs) > 10:
        system_prompt = msgs[0]
        tail = msgs[-20:]
        
        # Ensure we don't start the tail with a 'tool' role
        while tail and tail[0]["role"] == "tool":
            tail.pop(0)
        
        # Create a compact summary of what was dropped
        dropped_count = len(msgs) - 1 - len(tail)
        summary_msg = {
            "role": "user",
            "content": f"[Context compacted: {dropped_count} older messages were dropped to save space. Refer to .agent_memory.md for persistent context.]"
        }
        
        msgs = [system_prompt, summary_msg] + tail
        console.print(f"[dim]  >> Context compacted: dropped {dropped_count} old messages ({tokens} -> ~{_estimate_tokens(msgs)} tokens)[/dim]")
    
    return msgs

def run_turn(messages, instruction):
    # Detect task complexity and optionally engage the Architect
    try:
        from core.planner import detect_complexity, run_architect, save_plan, format_plan_for_context
        from core.repo_map import get_ast_repo_map
        complexity = detect_complexity(instruction)
        
        if complexity in ("complex", "medium"):
            level_label = "Complex" if complexity == "complex" else "Multi-file"
            console.print(f"  [bold magenta]📐 {level_label} task detected — engaging Architect agent...[/bold magenta]")
            
            # Get repo context for the architect
            path = os.getenv("FOLDER_PATH", ".")
            repo_context = ""
            try:
                repo_context = get_ast_repo_map(path)
            except Exception:
                pass
            
            plan = run_architect(instruction, repo_context)
            if plan:
                save_plan(plan, path)
                plan_summary = format_plan_for_context(plan)
                
                # Build a methodology-aware instruction injection
                plan_injection = f"""

[ARCHITECT'S PLAN — Follow this systematically]
{plan_summary}

YOUR EXECUTION INSTRUCTIONS:
1. First, use `set_goal` to record the objective: "{plan.get('summary', instruction[:80])}"
2. Use `create_task` for each step in the plan above.
3. Execute steps in order. For EACH step:
   a. Read all relevant files with `cat` BEFORE editing them.
   b. Make the changes.
   c. Run `lint_check` on each modified Python file.
   d. Use `complete_task` to mark the step done.
4. After ALL steps are done, run `run_tests` to verify everything works.
5. If tests pass, use `git_command("add -A")` then `git_command('commit -m "..."')` with a proper conventional commit message.
6. Provide a summary of what you did.
"""
                instruction = instruction + plan_injection
    except Exception as e:
        console.print(f"  [dim]Planner skipped: {e}[/dim]")

    messages.append({
        "role": "user",
        "content": instruction
    })
    
    result = call_llm_with_tools(messages)
    
    # REVIEWER PASS (for complex/medium tasks)
    try:
        from core.planner import detect_complexity, run_reviewer, load_plan
        path = os.getenv("FOLDER_PATH", ".")
        active_plan = load_plan(path)
        if active_plan and detect_complexity(instruction) in ("complex", "medium"):
            # Get actual git diff for the reviewer (much better than text summary)
            import subprocess
            diff_context = ""
            try:
                diff_result = subprocess.run(
                    ["git", "diff", "--stat"], capture_output=True, text=True,
                    timeout=10, cwd=path, encoding='utf-8', errors='replace'
                )
                diff_context = diff_result.stdout[:1500]

                # Also get the actual code diff (abbreviated)
                full_diff = subprocess.run(
                    ["git", "diff"], capture_output=True, text=True,
                    timeout=10, cwd=path, encoding='utf-8', errors='replace'
                )
                diff_context += "\n\nCode changes:\n" + full_diff.stdout[:2500]
            except Exception:
                diff_context = result[:2000] if result else ""
            
            console.print("  [bold cyan]🔍 Running Reviewer agent...[/bold cyan]")
            review = run_reviewer(instruction, diff_context)
            if review and review.get("verdict") == "request_changes":
                console.print("  [yellow]📝 Reviewer requested changes — sending back to executor...[/yellow]")
                review_feedback = f"[REVIEWER FEEDBACK] Score: {review.get('score', '?')}/10. Issues: "
                for issue in review.get("issues", [])[:3]:
                    review_feedback += f"\n- [{issue.get('severity', '?')}] {issue.get('description', '')} -> Fix: {issue.get('fix', '')}"
                review_feedback += "\n\nPlease fix these issues. Read the affected files first, make the corrections, then lint_check each one."
                messages.append({"role": "user", "content": review_feedback})
                fix_result = call_llm_with_tools(messages)
                messages.append({"role": "assistant", "content": fix_result})
                result = fix_result
    except Exception:
        pass

    # AUTO-VERIFICATION (for complex/medium tasks — runs compile, import, lint checks)
    try:
        from core.planner import detect_complexity
        if detect_complexity(instruction) in ("complex", "medium"):
            from core.verify import run_full_verification, format_verification_report
            path = os.getenv("FOLDER_PATH", ".")
            console.print("  [bold cyan]🔍 Auto-verifying changes...[/bold cyan]")
            verify_report = run_full_verification(path)
            
            if verify_report["overall"] == "FAIL":
                # Feed failures back to the agent for self-healing
                report_text = format_verification_report(verify_report)
                console.print("  [bold red]❌ Verification FAILED — sending back for fixes...[/bold red]")
                fix_prompt = (
                    f"[AUTO-VERIFICATION FAILED]\n{report_text}\n\n"
                    "Please fix the issues above. For each failed check:\n"
                    "1. Read the failing file with `cat`\n"
                    "2. Fix the issue with `replace_in_file`\n"
                    "3. Run `lint_check` on the fixed file\n"
                    "4. Then run `verify_project` to confirm everything passes."
                )
                messages.append({"role": "user", "content": fix_prompt})
                fix_result = call_llm_with_tools(messages)
                messages.append({"role": "assistant", "content": fix_result})
                result = fix_result
            else:
                console.print(f"  [bold green]✅ Verification PASSED ({verify_report.get('summary', '')})[/bold green]")
    except Exception:
        pass

    # Save the agent's final response to memory
    messages.append({
        "role": "assistant",
        "content": result
    })
    
    pruned = prune_messages(messages)
    messages.clear()
    messages.extend(pruned)
    
    # Show token usage
    token_count = _estimate_tokens(messages)
    console.print(f"[dim]  📊 Context: ~{token_count} tokens | {len(messages)} messages[/dim]")
    
    # HUMAN-IN-THE-LOOP FEEDBACK
    console.print("[dim]  ─── Press Enter to continue, 'f' to request a fix, or type feedback ───[/dim]")
    try:
        from prompt_toolkit import prompt as pt_prompt
        feedback = pt_prompt("  Feedback> ").strip()
        if feedback.lower() == 'f':
            console.print("[bold cyan]Sending fix request back to agent...[/bold cyan]")
            fix_result = call_llm_with_tools(messages + [{
                "role": "user",
                "content": "The user reviewed your work and wants you to fix or improve it. Re-read the files you just edited, find any issues, and fix them. Then re-run any tests to verify."
            }])
            messages.append({"role": "assistant", "content": fix_result})
            pruned = prune_messages(messages)
            messages.clear()
            messages.extend(pruned)
            return fix_result
        elif feedback:
            messages.append({
                "role": "user", 
                "content": f"[User Feedback on your last output]: {feedback}. Please take note of this for future work and update .agent_memory.md if it reflects a preference."
            })
    except (KeyboardInterrupt, EOFError):
        pass
    
    return result