import os
import re
import subprocess
from dotenv import load_dotenv

load_dotenv()

def get_base_dir(directory: str) -> str:
    if not directory or directory == "." or directory == "./":
        return os.getenv("FOLDER_PATH", ".")
    if not os.path.exists(directory):
        return os.getenv("FOLDER_PATH", ".")
    return directory

def cat_tool(path: str, start_line: int = 1, end_line: int = None) -> str:
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
            lines = f.readlines()
            
        total_lines = len(lines)
        start = max(0, start_line - 1) if start_line else 0
        end = min(total_lines, end_line) if end_line else total_lines
        
        # Enforce max 1000 lines at a time to prevent context overflow
        if end - start > 1000:
            end = start + 1000
            
        snippet = "".join(lines[start:end])
        header = f"--- File: {path} (Lines {start+1}-{end} of {total_lines}) ---\n"
        
        if end < total_lines:
            header += "Note: Output truncated to 1000 lines. Use start_line and end_line to view more.\n"
            
        return header + snippet
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

    for root, dirs, files in os.walk(directory):
        # Skip hidden directories and massive build folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'build', 'dist', '__pycache__', 'coverage', 'out', 'venv', 'env')]
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
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'build', 'dist', '__pycache__', 'coverage', 'out', 'venv', 'env')]
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

def run_command_tool(command: str) -> str:
    """Run a shell command."""
    cwd = os.getenv("FOLDER_PATH", ".")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        if not output.strip():
            output = f"Command '{command}' executed successfully with no output (Exit code {result.returncode})."
        return output[:8000] # Limit output size to prevent context overflow
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."
    except Exception as e:
        return f"Error executing command: {e}"

def replace_in_file_tool(path: str, target: str, replacement: str) -> str:
    """Replace a specific target string with a replacement string in a file."""
    if not os.path.isabs(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
        
    if not os.path.exists(path):
        return f"Error: File {path} does not exist."
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if target not in content:
            return "Error: Target content not found in file exactly as provided. Please verify spacing and newlines."
            
        new_content = content.replace(target, replacement)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        # Update index
        try:
            from core.memory import index_file
            index_file(path, new_content)
        except:
            pass
            
        return f"Successfully replaced content in {path}."
    except Exception as e:
        return f"Error replacing in file: {e}"

def apply_diff_tool(path: str, diffs: list) -> str:
    """Apply multiple search and replace blocks to a file."""
    if not os.path.isabs(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
        
    if not os.path.exists(path):
        return f"Error: File {path} does not exist."
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            
        new_content = content
        
        # Verify all targets exist first
        for idx, diff in enumerate(diffs):
            target = diff.get("search", "")
            if target not in new_content:
                return f"Error applying diffs: Target content for block {idx} not found in file exactly as provided. Please verify spacing and newlines."
                
        # Apply replacements
        for diff in diffs:
            target = diff.get("search", "")
            replacement = diff.get("replace", "")
            new_content = new_content.replace(target, replacement)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        # Update index
        try:
            from core.memory import index_file
            index_file(path, new_content)
        except:
            pass
            
        return f"Successfully applied {len(diffs)} diff block(s) to {path}."
    except Exception as e:
        return f"Error applying diffs: {e}"

def websearch_tool(query: str) -> str:
    """Search the web for information."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            
        if not results:
            return "No results found for your query."
            
        output = f"Web Search Results for '{query}':\n\n"
        for i, res in enumerate(results):
            output += f"{i+1}. {res.get('title', 'No Title')}\n"
            output += f"   URL: {res.get('href', 'No URL')}\n"
            output += f"   Snippet: {res.get('body', 'No Snippet')}\n\n"
            
        return output
    except ImportError:
        return "Error: duckduckgo-search package is not installed. Please run 'pip install duckduckgo-search'."
    except Exception as e:
        return f"Error performing web search: {e}"

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
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional. The line number to start reading from (1-indexed)."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional. The line number to stop reading at (1-indexed)."
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
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the workspace directory. Use this to install dependencies, run tests, build projects, or use utility scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Replace a specific snippet of text in a file with new text. Use this instead of edit_file for making small to medium edits in large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to modify."
                    },
                    "target": {
                        "type": "string",
                        "description": "The exact string to be replaced. Must match exactly, including indentation and newlines. Include sufficient context (e.g., full lines) to ensure the target is unique in the file."
                    },
                    "replacement": {
                        "type": "string",
                        "description": "The new string to replace the target with."
                    }
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_diff",
            "description": "Apply a set of diff blocks to a file. Useful for making multiple independent edits across a large file simultaneously without rewriting the whole file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to modify."
                    },
                    "diffs": {
                        "type": "array",
                        "description": "A list of diff blocks containing search and replace strings.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "search": {
                                    "type": "string",
                                    "description": "The exact lines to find and replace. Must match exactly, including indentation and newlines. Include sufficient context (e.g., full lines) to ensure the search string is unique in the file."
                                },
                                "replace": {
                                    "type": "string",
                                    "description": "The new lines to replace them with."
                                }
                            },
                            "required": ["search", "replace"]
                        }
                    }
                },
                "required": ["path", "diffs"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "websearch",
            "description": "Search the internet for documentation, updates, latest news, or coding solutions using DuckDuckGo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query."
                    }
                },
                "required": ["query"]
            }
        }
    }
]

def execute_tool(tool_name: str, args: dict) -> str:
    print(f"  [Tool Call]: {tool_name}({', '.join(f'{k}={str(v)[:30]}...' for k,v in args.items())})")
    if tool_name == "cat":
        return cat_tool(args.get("path", ""), args.get("start_line"), args.get("end_line"))
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
    elif tool_name == "run_command":
        return run_command_tool(args.get("command", ""))
    elif tool_name == "replace_in_file":
        return replace_in_file_tool(args.get("path", ""), args.get("target", ""), args.get("replacement", ""))
    elif tool_name == "apply_diff":
        return apply_diff_tool(args.get("path", ""), args.get("diffs", []))
    elif tool_name == "websearch":
        return websearch_tool(args.get("query", ""))
    else:
        return f"Error: Unknown tool {tool_name}"
