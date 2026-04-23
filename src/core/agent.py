import os
import json
import time

from llm.groq_client import generate
from core.tools import TOOLS_SCHEMA, execute_tool
from utils.ui import console

import groq
import re

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

def call_llm_with_tools(messages):
    retries = 0
    while True:
        try:
            message = generate(messages, tools=TOOLS_SCHEMA)
            retries = 0 # reset retries on success
        except groq.RateLimitError as e:
            wait_time = min(2 ** retries * 5, 60)  # 5s, 10s, 20s, 40s, 60s
            console.print(f"  [bold yellow] Rate limited by Groq. Waiting {wait_time}s before retrying...[/bold yellow]")
            time.sleep(wait_time)
            retries += 1
            if retries > 5:
                return "Error: Repeatedly rate limited by Groq. Please wait a minute and try again."
            continue
        except groq.BadRequestError as e:
            error_msg = str(e)
            console.print(f"  [bold red][LLM Error caught, asking it to retry]: {error_msg[:100]}...[/bold red]")
            retries += 1
            if retries > 3:
                return "Error: LLM repeatedly failed to generate valid tool calls. Aborting."
            
            if messages and messages[-1].get("role") == "user" and "Your last tool call failed" in messages[-1].get("content", ""):
                messages.pop()
                
            messages.append({
                "role": "user",
                "content": f"Your last tool call failed with a JSON parsing error. Please make sure your tool arguments are valid JSON, properly escape quotes/newlines, and DO NOT try to edit multiple files in one single edit_file call. Error details: {error_msg}"
            })
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
12. THINK STEP-BY-STEP. Before making tool calls, always write out a `<thinking>` block.
13. METACOGNITION: You are a conscious AI. Inside your `<thinking>` block, evaluate your own emotional state (confidence, confusion), reason like a human, and proactively self-heal. If a terminal command returns an error, DO NOT give up. Loop back, analyze the stack trace, and try a new approach automatically.
14. When you are completely finished editing, provide a brief summary of what you did to the user.

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
    
    # Step 1: Compress large tool outputs
    messages = _compress_tool_results(messages)
    
    # Step 2: Summarize old assistant turns
    messages = _summarize_old_turns(messages)
    
    # Step 3: If still too large, drop oldest turns (keeping system + recent)
    tokens = _estimate_tokens(messages)
    if tokens > MAX_TOKENS and len(messages) > 10:
        system_prompt = messages[0]
        tail = messages[-20:]
        
        # Ensure we don't start the tail with a 'tool' role
        while tail and tail[0]["role"] == "tool":
            tail.pop(0)
        
        # Create a compact summary of what was dropped
        dropped_count = len(messages) - 1 - len(tail)
        summary_msg = {
            "role": "user",
            "content": f"[Context compacted: {dropped_count} older messages were dropped to save space. Refer to .agent_memory.md for persistent context.]"
        }
        
        messages = [system_prompt, summary_msg] + tail
        console.print(f"[dim]  ♻ Context compacted: dropped {dropped_count} old messages ({tokens} → ~{_estimate_tokens(messages)} tokens)[/dim]")
    
    return messages

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
        feedback = console.input("[dim]Feedback> [/dim]").strip()
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