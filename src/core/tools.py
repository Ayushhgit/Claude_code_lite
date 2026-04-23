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
            allowed_exts = (".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json")
            if not file.endswith(allowed_exts):
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
            
        # Re-index the file in the background so memory stays fresh
        try:
            from core.memory import index_file
            index_file(path, content)
        except Exception as mem_err:
            print(f"  [Memory Error]: Failed to update index for {path}: {mem_err}")
            
        return f"Successfully updated {path} and updated vector index."
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
            # Remove from index
            try:
                from core.memory import collection
                collection.delete(where={"filepath": path})
            except Exception:
                pass
            return f"Successfully deleted {path}"
        else:
            return f"Error: File {path} does not exist."
    except Exception as e:
        return f"Error deleting {path}: {e}"

def get_repo_map_tool(directory: str) -> str:
    """Returns a tree structure of the repository to understand the whole codebase."""
    directory = get_base_dir(directory)
    if not os.path.exists(directory):
        return f"Error: Directory {directory} does not exist."
    
    tree_str = f"Repository Map for {directory}:\n"
    for root, dirs, files in os.walk(directory):
        # Skip hidden directories like .git or .kinda_claude
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        level = root.replace(directory, '').count(os.sep)
        indent = ' ' * 4 * (level)
        tree_str += f"{indent}{os.path.basename(root)}/\n"
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            if not f.startswith('.'):
                tree_str += f"{subindent}{f}\n"
                
    return tree_str

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
            "description": "Search for a regular expression pattern across all Python, JS, HTML, and CSS files in a directory.",
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
            "name": "semantic_search",
            "description": "Search the codebase index for code related to a specific concept or logic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The natural language query to search for (e.g. 'user authentication logic' or 'database connection setup')."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "index_codebase",
            "description": "Scans and indexes all Python, JS, HTML, and CSS files in the given directory into the Vector Database. You MUST run this once before semantic_search works.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The directory to index."
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
    },
    {
        "type": "function",
        "function": {
            "name": "get_repo_map",
            "description": "Get a structural tree map of the entire repository. Use this to understand the global structure, find out what folders exist, and see all files at a glance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The root directory to map."
                    }
                },
                "required": ["directory"]
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
    elif tool_name == "get_repo_map":
        return get_repo_map_tool(args.get("directory", ""))
    elif tool_name == "semantic_search":
        from core.memory import semantic_search
        return semantic_search(args.get("query", ""))
    elif tool_name == "index_codebase":
        from core.memory import index_codebase
        directory = get_base_dir(args.get("directory", ""))
        return index_codebase(directory)
    elif tool_name == "edit_file":
        return edit_file_tool(args.get("path", ""), args.get("content", ""))
    elif tool_name == "delete_file":
        return delete_file_tool(args.get("path", ""))
    else:
        return f"Error: Unknown tool {tool_name}"
