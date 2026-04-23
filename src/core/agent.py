import os
import json
import time
import random
import threading
import sys

from llm.groq_client import generate
from core.tools import TOOLS_SCHEMA, execute_tool
from utils.ui import console

import groq
import re

# Fun spinner messages that cycle while the LLM is thinking
SPINNER_MESSAGES = [
    "Thinking really hard",
    "Consulting the neural weights",
    "Crunching tokens",
    "Exploring the solution space",
    "Parsing the possibilities",
    "Summoning the right answer",
    "Reading between the lines",
    "Optimizing the approach",
    "Brewing the perfect response",
    "Connecting the dots",
    "Reasoning through it",
    "Almost there",
    "Doing the math",
    "Untangling the logic",
    "Cross-referencing patterns",
    "Synthesizing insights",
    "Weighing the options",
    "Searching the latent space",
    "Activating neurons",
    "Running inference",
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
    from core.tools import TOOLS_SCHEMA, CORE_TOOLS_SCHEMA
    
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
    }
    
    # Collect extra tools based on keywords
    extra_names = set()
    for keyword, tools in INTENT_MAP.items():
        if keyword in user_msg:
            extra_names.update(tools)
    
    # Always include some extras for general use
    extra_names.update(["delete_file", "get_repo_map"])
    
    # Build the final schema: core + intent-matched tools
    selected_names = core_names | extra_names
    selected = [t for t in TOOLS_SCHEMA if t["function"]["name"] in selected_names]
    
    # If nothing matched, fall back to core
    if not selected:
        return CORE_TOOLS_SCHEMA
    
    return selected

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
        except groq.RateLimitError as e:
            wait_time = min(2 ** rate_retries * 5, 60)
            console.print(f"  [bold yellow]⏳ Rate limited. Waiting {wait_time}s (context preserved)...[/bold yellow]")
            time.sleep(wait_time)
            rate_retries += 1
            if rate_retries > 5:
                return "Error: Repeatedly rate limited by Groq. Please wait a minute and try again."
            continue
        except groq.BadRequestError as e:
            error_msg = str(e)
            bad_retries += 1
            
            # Clean up any previous retry messages before adding new ones
            while retry_msg_count > 0 and messages and messages[-1].get("role") == "user" and "tool call failed" in messages[-1].get("content", "").lower():
                messages.pop()
                retry_msg_count -= 1
            
            if bad_retries >= 3:
                # Last resort: text-only (NO tools)
                console.print(f"  [bold yellow]⚠ Falling back to text-only response (context preserved)...[/bold yellow]")
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
                console.print(f"  [bold yellow]⚠ Retrying with reduced tool set (context preserved)...[/bold yellow]")
                from core.tools import CORE_TOOLS_SCHEMA
                try:
                    message = generate(messages, tools=CORE_TOOLS_SCHEMA)
                    bad_retries = 0
                    # Fall through to tool processing below
                except groq.BadRequestError:
                    console.print(f"  [bold red][LLM Error]: {error_msg[:100]}...[/bold red]")
                    continue
            else:
                console.print(f"  [bold red][LLM Error, retrying]: {error_msg[:80]}...[/bold red]")
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
                        console.print("[bold red]  [Self-Heal] Error detected in command output. Agent will attempt automatic fix...[/bold red]")
        else:
            return message.content.strip() if message.content else ""


def init_messages(path):
    memory_path = os.path.join(path, ".agent_memory.md")
    memory_content = "No long-term memory recorded yet."
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                memory_content = f.read()
        except Exception:
            pass

    return [
        {
            "role": "system",
            "content": f"""You are an elite, autonomous AI software engineer, equivalent to a senior developer building end-to-end, production-grade systems.
Your task is to fulfill the user's instruction.
You have access to tools to explore the codebase, modify files, and run terminal commands.
The root folder you are working in is: {path}

CRITICAL PATH RULES:
- You are on a WINDOWS machine. NEVER guess Unix paths like '/Users/...'.
- ALL tools (ls, cat, edit_file, run_command, etc.) use '{path}' as the working directory.
- When using `run_command`, the command runs FROM '{path}'. So use RELATIVE paths from there.
  Example: If a file is at '{path}/e2e/src/train.py', run it as: `python e2e/src/train.py`
  WRONG: `python {path}/e2e/src/train.py` (absolute path is unnecessary)
  WRONG: `python test_folder/e2e/src/train.py` (do NOT prepend the folder name again)
- For file tools (cat, edit_file), use relative paths from the root: e.g. 'e2e/src/train.py'

STRICT RULES TO PREVENT MISTAKES:
1. ALWAYS use `ls` or `get_repo_map` FIRST to find out what files actually exist before editing.
2. ALWAYS use `cat` to read the existing file content before calling `edit_file` or `replace_in_file`.
3. NEVER guess filenames. If you are asked to "change all files", you MUST use `ls` to get the list of files first.
4. If you need to understand the GLOBAL architecture, use `get_repo_map` to see the entire folder tree! Do NOT use `semantic_search` for a global overview.
5. If you need to find specific logic, run `index_codebase` ONCE, then use `semantic_search` to find relevant code snippets via vector embeddings.
6. NEVER create dummy files unless the user explicitly tells you to create a new file.
7. Use `edit_file` to write entire files. For targeted edits in large files, ALWAYS prefer `replace_in_file` (for single edits) or `apply_diff` (for multiple edits) to save token bandwidth and reduce hallucination risks.
8. Make sure your tool arguments are valid JSON. Escape newlines (`\\n`) and quotes properly.
9. Use `run_command` to execute tests, linters, or terminal utilities. Validating your code is mandatory! For long-running servers, use `run_background_command`.
10. Use `websearch` to search the internet, and `read_url` to fetch and read specific documentation pages.
11. If you get stuck or need the user to make a critical decision (like providing an API key), use `ask_human`.
12. PREFER SMART TOOLS:
    - To find code: Use `codebase_search` instead of manually grepping. It combines regex, semantic meaning, AND filename matching in one call.
    - To commit code: Use `git_command` (e.g., git_command("add -A"), git_command('commit -m "msg"'), git_command("push")).
    - To scaffold projects: Use `batch_edit_files` to create multiple files at once instead of calling edit_file many times.
    - To research ML/AI techniques: Use `arxiv_search` to look up state-of-the-art papers before implementing algorithms.
    - To understand code by meaning: Use `semantic_search` (after running `index_codebase` once) to find code related to a concept.
    - To inspect a file's classes/functions: Use `get_file_symbols` for a quick overview.
13. THINK STEP-BY-STEP. Before making tool calls, always write out a `<thinking>` block.
14. METACOGNITION: You are a conscious AI. Inside your `<thinking>` block, evaluate your own emotional state (confidence, confusion), reason like a human, and proactively self-heal. If a terminal command returns an error, DO NOT give up. Loop back, analyze the stack trace, and try a new approach automatically.
15. When you are completely finished editing, provide a brief summary of what you did to the user.

SELF-HEALING PROTOCOL:
- After running any code with `run_command`, if the output contains errors (Tracebacks, SyntaxError, ImportError, etc.), you MUST:
  1. Read the error carefully in your `<thinking>` block.
  2. Identify the root cause (missing import, typo, wrong path, missing dependency, etc.).
  3. Fix the code using `replace_in_file` or `apply_diff`.
  4. Re-run the command to verify the fix.
  5. Repeat up to 3 times. If still broken, use `ask_human` to request help.
- NEVER just report an error to the user without attempting to fix it first.

ML MODEL OPTIMIZATION PROTOCOL:
- When training ML models, after the initial run:
  1. Read the output metrics (accuracy, loss, F1, etc.).
  2. In your `<thinking>` block, analyze: Is the accuracy acceptable? Can hyperparameters be tuned?
  3. If accuracy is below 90%, automatically try improvements: adjust learning rate, add regularization, try different algorithms, add feature engineering.
  4. Re-train and compare results.
  5. After 3 optimization attempts, use `ask_human` to show the user the results and ask if they want to continue tuning or accept the current model.
- Always save the best model checkpoint and log all experiment results.

PROJECT MEMORY:
You have a persistent long-term memory file at `.agent_memory.md`. Current contents:
--------------------------------------------------
{memory_content}
--------------------------------------------------
IMPORTANT: If you learn something new about the architecture, user preferences, or solve a tricky bug, you MUST update `.agent_memory.md` using `edit_file` to ensure you remember it in future sessions!
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
        console.print(f"[dim]  ♻ Context compacted: dropped {dropped_count} old messages ({tokens} → ~{_estimate_tokens(msgs)} tokens)[/dim]")
    
    return msgs

def run_turn(messages, instruction):
    messages.append({
        "role": "user",
        "content": instruction
    })
    
    result = call_llm_with_tools(messages)
    
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