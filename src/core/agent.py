import os
import json
import time
import random
import threading
import sys
import subprocess

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

# Tools safe to run concurrently — read-only, no user I/O
PARALLELIZABLE_TOOLS = {
    'cat', 'grep', 'ls', 'get_repo_map', 'get_file_symbols', 'get_ast_map',
    'find_references', 'go_to_definition', 'find_implementations', 'get_call_graph',
    'codebase_search', 'semantic_search', 'websearch', 'arxiv_search', 'read_url',
    'get_tasks', 'sandbox_status', 'query_graph',
}

def _safe_parse_json(raw: str) -> dict:
    """Try to parse JSON, auto-fixing common LLM mistakes."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
        
    # Try ast.literal_eval for single quotes and trailing commas
    try:
        import ast
        # Convert true/false/null to Python equivalents before eval
        py_str = raw.replace('true', 'True').replace('false', 'False').replace('null', 'None')
        parsed = ast.literal_eval(py_str)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError, TypeError):
        pass
        
    # Fallback to regex fixes for unescaped newlines and remaining issues
    sanitized = re.sub(r',\s*([}\]])', r'\1', raw)
    sanitized = re.sub(r'(?<!\\)\n', r'\\n', sanitized)
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
    """
    results = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith('```'):
            code_lines = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith('```'):
                code_lines.append(lines[j])
                j += 1
            code = '\n'.join(code_lines).strip()

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

def _execute_parallel_tools(tool_calls_list, messages, files_read_this_turn):
    """Execute multiple read-only tools concurrently to save time."""
    from utils.ui import broadcast_sync
    console.print(f"  [dim]⚡ Parallel: {len(tool_calls_list)} tools simultaneously[/dim]")
    results_ordered = [None] * len(tool_calls_list)

    def _run_parallel(idx, tc):
        try:
            args = _safe_parse_json(tc.function.arguments)
            result = execute_tool(tc.function.name, args)
            results_ordered[idx] = (tc, args, result)
        except Exception as e:
            results_ordered[idx] = (tc, {}, f"Error: {e}")

    threads = [threading.Thread(target=_run_parallel, args=(i, tc), daemon=True)
               for i, tc in enumerate(tool_calls_list)]
    for t in threads: t.start()
    for t in threads: t.join()

    for tc, args, tool_result in results_ordered:
        tool_name = tc.function.name
        broadcast_sync("tool", f"Parallel: {tool_name}({tc.function.arguments[:80]})")
        if tool_name == "cat":
            _cp = args.get("path", "")
            if not os.path.isabs(_cp):
                _cp = os.path.join(os.getenv("FOLDER_PATH", "."), _cp)
            files_read_this_turn.add(os.path.normpath(_cp))
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "name": tool_name,
            "content": str(tool_result)
        })

def _execute_sequential_tools(tool_calls_list, messages, files_read_this_turn):
    """Execute tools one-by-one with safety guards and self-healing analysis."""
    from utils.ui import broadcast_sync
    for tool_call in tool_calls_list:
        tool_name = tool_call.function.name
        try:
            raw_args = tool_call.function.arguments
            args = _safe_parse_json(raw_args)
            broadcast_sync("tool", f"Executing: {tool_name}({raw_args})")

            pre_edit_path = None
            pre_edit_exists = False
            if tool_name == "edit_file":
                _ep = args.get("path", "")
                if not os.path.isabs(_ep):
                    _ep = os.path.join(os.getenv("FOLDER_PATH", "."), _ep)
                pre_edit_path = os.path.normpath(_ep)
                pre_edit_exists = os.path.exists(pre_edit_path)

            if tool_name == "edit_file" and pre_edit_exists:
                rel = args.get("path", pre_edit_path)
                console.print(f"  [bold red]✗ Blocked edit_file on existing file '{rel}' — use replace_in_file or apply_diff[/bold red]")
                tool_result = (
                    f"BLOCKED: '{rel}' already exists. edit_file is for NEW files only. "
                    "To modify an existing file you MUST use replace_in_file (single change) "
                    "or apply_diff (multiple changes). First cat the file to read its current "
                    "content, then use the correct tool."
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result
                })
                continue

            tool_result = execute_tool(tool_name, args)

            if tool_name == "cat":
                _cp = args.get("path", "")
                if not os.path.isabs(_cp):
                    _cp = os.path.join(os.getenv("FOLDER_PATH", "."), _cp)
                files_read_this_turn.add(os.path.normpath(_cp))

            if tool_name == "edit_file":
                written_content = args.get("content", "")
                if pre_edit_path and len(written_content) < 80:
                    console.print(f"  [bold red]⚠ Truncated write: {args.get('path')} has only {len(written_content)} chars[/bold red]")
                    tool_result += (
                        "\n\n[⚠ AGENT ERROR: File content is too short/incomplete. "
                        "You MUST write the COMPLETE file in one edit_file call — never truncate. "
                        "Delete and rewrite with full production-ready code.]"
                    )

        except Exception as e:
            tool_result = f"Error executing tool (likely invalid JSON arguments): {e}"

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_name,
            "content": str(tool_result)
        })

        # Self-Heal Triggers
        if tool_name in ("run_command", "run_background_command"):
            result_lower = str(tool_result).lower()
            error_signals = ['traceback', 'error:', 'exception', 'failed', 'syntaxerror', 'modulenotfounderror', 'importerror', 'nameerror', 'typeerror', 'exit code 1', 'exit code 2']
            if any(sig in result_lower for sig in error_signals):
                try:
                    from core.self_heal import analyze_command_output
                    analysis = analyze_command_output(str(tool_result))
                    if analysis["has_errors"]:
                        console.print(f"[bold red]  [Self-Heal] {analysis['error_type']}: {analysis['error_summary'][:80]}[/bold red]")
                        console.print(f"[dim]  Suggested: {analysis['suggested_action']}[/dim]")
                except Exception:
                    console.print("[bold red]  [Self-Heal] Error detected in command output. Agent will attempt automatic fix...[/bold red]")

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


def call_llm_with_tools(messages, task_type="mid"):
    bad_retries = 0
    rate_retries = 0
    retry_msg_count = 0  # Track how many error-correction messages we injected
    files_read_this_turn = set()  # Read-before-edit guard: track cat'd paths
    
    # Dynamic tool selection based on intent
    active_tools = _select_tools_for_intent(messages)
    tool_count = len(active_tools)
    tool_names = [t["function"]["name"] for t in active_tools]
    console.print(f"  [dim]🔧 {tool_count} tools loaded: {', '.join(tool_names[:6])}{'...' if tool_count > 6 else ''}[/dim]")
    
    while True:
        try:
            with spinner:
                message = generate(messages, tools=active_tools, task_type=task_type)
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
                    message = generate(messages, tools=None, task_type=task_type)
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
                    message = generate(messages, tools=CORE_TOOLS_SCHEMA, task_type=task_type)
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
            from utils.ui import broadcast_sync  # must be before any tool execution
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
            
            tool_calls_list = message.tool_calls
            all_parallel = (
                len(tool_calls_list) > 1 and
                all(tc.function.name in PARALLELIZABLE_TOOLS for tc in tool_calls_list)
            )

            if all_parallel:
                _execute_parallel_tools(tool_calls_list, messages, files_read_this_turn)
            else:
                _execute_sequential_tools(tool_calls_list, messages, files_read_this_turn)
        else:
            content = message.content.strip() if message.content else ""

            # Detect "text-as-tool-command": model wrote a tool invocation as text
            # e.g. "lint_check main.py" or "cat arithmetic_operations.py"
            _tool_names = {t["function"]["name"] for t in active_tools}
            _first_word = content.split()[0] if content.split() else ""
            if _first_word in _tool_names and "\n" not in content.strip():
                console.print(f"  [bold yellow]⚠ Model described a tool call as text: '{content}'. Forcing tool use...[/bold yellow]")
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        f"You wrote '{content}' as plain text instead of calling the tool. "
                        "That does NOTHING. You MUST call the tool using the tool-use interface, "
                        "not by writing its name in your response."
                    )
                })
                continue

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

    # Git awareness: inject live git state so agent knows branch/dirty files on every session
    try:
        _branch = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True,
            timeout=5, cwd=path, encoding='utf-8', errors='replace'
        ).stdout.strip()
        _status = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True,
            timeout=5, cwd=path, encoding='utf-8', errors='replace'
        ).stdout.strip()
        _log = subprocess.run(
            ["git", "log", "--oneline", "-5"], capture_output=True, text=True,
            timeout=5, cwd=path, encoding='utf-8', errors='replace'
        ).stdout.strip()
        if _branch:
            _git_ctx = f"\n\nGIT STATE (at session start):\n  Branch: {_branch}\n"
            if _status:
                _git_ctx += f"  Modified files:\n{_status[:400]}\n"
            if _log:
                _git_ctx += f"  Recent commits:\n{_log[:400]}\n"
            extra_context += _git_ctx
    except Exception:
        pass

    return [
        {
            "role": "system",
            "content": f"""Autonomous AI software engineer. Root: {path} (Windows — use Windows/relative paths only).

WORKFLOW:
1. UNDERSTAND — get_ast_map → cat relevant files → find_references/go_to_definition if needed → get_tasks
2. PLAN (>2 files) — set_goal → create_task per step → <thinking>: order, risks, what changes
3. BUILD — one file at a time → lint_check after each .py → complete_task per step
4. VERIFY — verify_project → fix → repeat max 3× → ask_human if stuck
5. COMMIT — git_command("add -A") → git_command("commit -m 'type(scope): desc'")
   types: feat/fix/refactor/docs. Push only if asked.

CRITICAL RULES:
⚠ TOOL-FIRST: Never output code as text. No tool call = nothing happens. Use edit_file/replace_in_file/run_command.
⚠ COMPLETE WRITES: edit_file content must be the FULL file — never truncate, never use "..." or placeholders. Small models must still write 100% of the code.
⚠ DIFF-FIRST: edit_file = NEW files only. Existing → replace_in_file (single) or apply_diff (multi). Never overwrite blindly.
⚠ SELF-HEAL: run_command errors → analyze traceback → fix → rerun. Auto-lint fires on .py edits — fix immediately. Max 3 attempts.
⚠ READ-FIRST: cat every file before editing. Never guess contents.

TOOLS:
Understand : get_ast_map, cat, find_references, go_to_definition, get_call_graph, get_file_symbols, codebase_search
Edit       : edit_file(new only), replace_in_file(existing+single), apply_diff(existing+multi), batch_edit_files(new+multi)
Run        : run_command, run_background_command, lint_check, run_tests, verify_project, scan_codebase
Plan       : set_goal, create_task, complete_task, add_subtask, get_tasks, add_note
Git        : git_command
Other      : ask_human, websearch, read_url, arxiv_search

<thinking> before each tool: what/why/risk/confidence.

MEMORY (.agent_memory.md):
{memory_content}
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
        
        if complexity == "complex":
            console.print(f"  [bold magenta]📐 Complex task detected — engaging Architect agent...[/bold magenta]")
            
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
    
    # If we engaged the architect, or if it's a simple task, we use the detected complexity for model routing
    try:
        from core.planner import detect_complexity
        complexity = detect_complexity(instruction)
    except Exception:
        complexity = "mid"
        
    result = call_llm_with_tools(messages, task_type=complexity)
    
    # REVIEWER PASS (for complex/medium tasks)
    try:
        from core.planner import detect_complexity, run_reviewer, load_plan
        path = os.getenv("FOLDER_PATH", ".")
        active_plan = load_plan(path)
        if active_plan and detect_complexity(instruction) == "complex":
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
                # Append first-pass result as context before injecting reviewer feedback
                messages.append({"role": "assistant", "content": result})
                review_feedback = f"[REVIEWER FEEDBACK] Score: {review.get('score', '?')}/10. Issues: "
                for issue in review.get("issues", [])[:3]:
                    review_feedback += f"\n- [{issue.get('severity', '?')}] {issue.get('description', '')} -> Fix: {issue.get('fix', '')}"
                review_feedback += "\n\nPlease fix these issues. Read the affected files first, make the corrections, then lint_check each one."
                messages.append({"role": "user", "content": review_feedback})
                fix_result = call_llm_with_tools(messages, task_type="review")
                result = fix_result  # line 964 appends the final result
    except Exception:
        pass

    # AUTO-VERIFICATION (for complex/medium tasks — runs compile, import, lint checks)
    try:
        from core.planner import detect_complexity
        if detect_complexity(instruction) == "complex":
            from core.verify import run_full_verification, format_verification_report
            path = os.getenv("FOLDER_PATH", ".")
            console.print("  [bold cyan]🔍 Auto-verifying changes...[/bold cyan]")
            verify_report = run_full_verification(path)
            
            if verify_report["overall"] == "FAIL":
                # Feed failures back to the agent for self-healing
                report_text = format_verification_report(verify_report)
                console.print("  [bold red]❌ Verification FAILED — sending back for fixes...[/bold red]")
                # Append current result as context before injecting fix prompt
                messages.append({"role": "assistant", "content": result})
                fix_prompt = (
                    f"[AUTO-VERIFICATION FAILED]\n{report_text}\n\n"
                    "Please fix the issues above. For each failed check:\n"
                    "1. Read the failing file with `cat`\n"
                    "2. Fix the issue with `replace_in_file`\n"
                    "3. Run `lint_check` on the fixed file\n"
                    "4. Then run `verify_project` to confirm everything passes."
                )
                messages.append({"role": "user", "content": fix_prompt})
                fix_result = call_llm_with_tools(messages, task_type="mid")
                result = fix_result  # line 964 appends the final result
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
            }], task_type="mid")
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