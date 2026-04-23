import os
import json

from llm.groq_client import generate
from core.tools import TOOLS_SCHEMA, execute_tool
from utils.ui import console

import groq

def call_llm_with_tools(messages):
    retries = 0
    while True:
        try:
            message = generate(messages, tools=TOOLS_SCHEMA)
            retries = 0 # reset retries on success
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
                    # Print internal thoughts using Rich dim style
                    console.print(f"[dim]\n[Agent's Inner Monologue]: {think_match.group(1).strip()}\n[/dim]")
                    
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
                    args = json.loads(tool_call.function.arguments)
                    tool_result = execute_tool(tool_name, args)
                except Exception as e:
                    tool_result = f"Error executing tool (likely invalid JSON arguments): {e}"
                    
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": str(tool_result)
                })
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

PROJECT MEMORY:
You have a persistent long-term memory file at `.agent_memory.md`. Current contents:
--------------------------------------------------
{memory_content}
--------------------------------------------------
IMPORTANT: If you learn something new about the architecture, user preferences, or solve a tricky bug, you MUST update `.agent_memory.md` using `edit_file` to ensure you remember it in future sessions!
"""
        }
    ]

def prune_messages(messages):
    MAX_MESSAGES = 40
    if len(messages) <= MAX_MESSAGES:
        return messages
        
    system_prompt = messages[0]
    tail = messages[-20:]
    
    # Ensure we don't start the tail with a 'tool' role because its 'assistant' call was truncated
    while tail and tail[0]["role"] == "tool":
        tail.pop(0)
        
    return [system_prompt] + tail

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
    
    return result