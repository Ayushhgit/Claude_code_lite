import os
import json

from utils.files import read_file
from utils.file_selector import llm_pick_file
from core.prompt import build_edit_prompt
from core.router import detect_mode, detect_scope
from llm.groq_client import generate
from core.tools import TOOLS_SCHEMA, execute_tool


import groq

def call_llm_with_tools(messages):
    while True:
        try:
            message = generate(messages, tools=TOOLS_SCHEMA)
        except groq.BadRequestError as e:
            error_msg = str(e)
            print(f"  [LLM Error caught, asking it to retry]: {error_msg[:100]}...")
            messages.append({
                "role": "user",
                "content": f"Your last tool call failed with a JSON parsing error. Please make sure your tool arguments are valid JSON, properly escape quotes/newlines, and DO NOT try to edit multiple files in one single edit_file call. Error details: {error_msg}"
            })
            continue

        if getattr(message, "tool_calls", None):
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
    return [
        {
            "role": "system",
            "content": f"""You are an autonomous AI coding agent. 
Your task is to fulfill the user's instruction.
You have access to tools to explore the codebase and modify files.
The root folder you are working in is: {path}

STRICT RULES TO PREVENT MISTAKES:
1. ALWAYS use `ls` or `get_repo_map` FIRST to find out what files actually exist before editing.
2. ALWAYS use `cat` to read the existing file content before calling `edit_file`.
3. NEVER guess filenames. If you are asked to "change all files", you MUST use `ls` to get the list of files first.
4. If you need to understand the GLOBAL architecture (e.g. "analyze the whole codebase"), use `get_repo_map` to see the entire folder tree! Do NOT use `semantic_search` for a global overview.
5. If you need to find specific logic (e.g. "where is the math logic"), run `index_codebase` ONCE, then use `semantic_search` to find relevant code snippets via vector embeddings.
6. NEVER create dummy files, test files, or hallucinated files (e.g. test.py, test2.py) unless the user explicitly tells you to create a new file.
7. Use `edit_file` to modify or create files. IMPORTANT: You MUST call `edit_file` separately for EACH file you want to edit. Do NOT try to combine multiple files into one `edit_file` call.
8. Make sure your tool arguments are valid JSON. To insert newlines in the `content` argument, use a standard JSON newline escape (`\\n`). DO NOT double-escape newlines (like `\\\\n`) or quotes (like `\\\\"`, unless they are actual literal strings inside your code), otherwise literal '\\n' and '\\"' characters will be printed into the file!
9. Use `delete_file` to delete files if requested.
10. When you are completely finished editing, provide a brief summary of what you did to the user.
"""
        }
    ]

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
    
    return result