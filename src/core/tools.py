import os
import re
from dotenv import load_dotenv

load_dotenv()

def get_base_dir(directory: str) -> str:
    if not directory or directory == "." or directory == "./":
        return os.getenv("FOLDER_PATH", ".")
    if not os.path.exists(directory):
        return os.getenv("FOLDER_PATH", ".")
    return directory

def cat_tool(path: str) -> str:
    """Read the contents of a file."""
    # if path is just a filename, assume it's in the target folder
    if not os.path.isabs(path) and not os.path.exists(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
        
    if not os.path.exists(path):
        return f"Error: File {path} does not exist."
    if os.path.isdir(path):
        return f"Error: {path} is a directory."
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"

def grep_tool(directory: str, pattern: str) -> str:
    """Search for a regex pattern in a directory."""
    directory = get_base_dir(directory)
    if not os.path.exists(directory):
        return f"Error: Directory {directory} does not exist."
    
    results = []
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    for root, _, files in os.walk(directory):
        for file in files:
            if not file.endswith(".py"): # Limit to python files for now
                continue
            
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if regex.search(line):
                            results.append(f"{filepath}:{i+1}:{line.strip()}")
            except Exception:
                pass
                
    if not results:
        return "No matches found."
    return "\n".join(results[:50]) # Limit output to prevent massive context


def ls_tool(directory: str) -> str:
    """List contents of a directory."""
    directory = get_base_dir(directory)
    if not os.path.exists(directory):
        return f"Error: Directory {directory} does not exist."
    try:
        items = os.listdir(directory)
        return "\n".join(items) if items else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {e}"

def edit_file_tool(path: str, content: str) -> str:
    """Write content to a file."""
    if not os.path.isabs(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
    
    # Auto-fix double-escaped newlines: 
    # If the LLM sent a single-line string with literal '\\n' sequences, unescape it.
    if "\\n" in content and "\n" not in content:
        content = content.replace("\\n", "\n")
        
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully updated {path}"
    except Exception as e:
        return f"Error writing to {path}: {e}"

def delete_file_tool(path: str) -> str:
    """Delete a file."""
    if not os.path.isabs(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
        
    try:
        if os.path.exists(path):
            os.remove(path)
            return f"Successfully deleted {path}"
        else:
            return f"Error: File {path} does not exist."
    except Exception as e:
        return f"Error deleting {path}: {e}"

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "cat",
            "description": "Read and return the contents of a specific file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The absolute or relative path to the file to read."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a regular expression pattern across all python files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The directory to search in."
                    },
                    "pattern": {
                        "type": "string",
                        "description": "The regex pattern to search for."
                    }
                },
                "required": ["directory", "pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The directory to list."
                    }
                },
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Write or overwrite a file with new code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to edit or create."
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete, raw code to write to the file. Must be the full file content."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete an existing file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to delete."
                    }
                },
                "required": ["path"]
            }
        }
    }
]

def execute_tool(tool_name: str, args: dict) -> str:
    print(f"  [Tool Call]: {tool_name}({', '.join(f'{k}={str(v)[:30]}...' for k,v in args.items())})")
    if tool_name == "cat":
        return cat_tool(args.get("path", ""))
    elif tool_name == "grep":
        return grep_tool(args.get("directory", ""), args.get("pattern", ""))
    elif tool_name == "ls":
        return ls_tool(args.get("directory", ""))
    elif tool_name == "edit_file":
        return edit_file_tool(args.get("path", ""), args.get("content", ""))
    elif tool_name == "delete_file":
        return delete_file_tool(args.get("path", ""))
    else:
        return f"Error: Unknown tool {tool_name}"
