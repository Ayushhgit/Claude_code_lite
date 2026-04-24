import os
import re
import subprocess
import uuid
import ast
import difflib
from dotenv import load_dotenv

load_dotenv()

# Global state for background processes
BACKGROUND_PROCESSES = {}

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

def _log_edit_to_memory(filepath: str, action: str):
    """Auto-append a log entry to .agent_memory.md after every edit."""
    import datetime
    folder = os.getenv("FOLDER_PATH", ".")
    memory_path = os.path.join(folder, ".agent_memory.md")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n- [{timestamp}] {action}: `{os.path.basename(filepath)}`\n"
    try:
        existing = ""
        if os.path.exists(memory_path):
            with open(memory_path, "r", encoding="utf-8") as f:
                existing = f.read()
        # Only append if not already logged (avoid duplicates in same second)
        if entry.strip() not in existing:
            with open(memory_path, "a", encoding="utf-8") as f:
                f.write(entry)
    except Exception:
        pass

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
        
        _log_edit_to_memory(path, "Created/Updated")
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
            _log_edit_to_memory(path, "Deleted")
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
        # Skip hidden directories like .git or .revi
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        level = root.replace(directory, '').count(os.sep)
        indent = ' ' * 4 * (level)
        tree_str += f"{indent}{os.path.basename(root)}/\n"
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            if not f.startswith('.'):
                tree_str += f"{subindent}{f}\n"
                
    return tree_str

# Commands that are always safe (no approval needed)
SAFE_COMMANDS = [
    'ls', 'dir', 'cat', 'type', 'echo', 'pwd', 'cd', 'mkdir',
    'python ', 'python3 ', 'pip install', 'pip list', 'pip --version',
    'uv run', 'uv pip', 'npm install', 'npm run', 'npx ',
    'node ', 'python --version', 'node --version', 'npm --version',
    'git status', 'git log', 'git diff', 'git branch',
]

# Patterns that are BLOCKED unless user explicitly approves
DANGEROUS_PATTERNS = [
    'rm -rf', 'rmdir /s', 'del /s', 'del /f', 'format ', 'fdisk',
    'shutdown', 'reboot', ':(){', 'mkfs', 'dd if=',
    'chmod 777', 'curl | bash', 'wget | sh', 'sudo ',
    '> /dev/', 'reg delete', 'reg add',
]

def _approve_command(command: str) -> bool:
    """Ask user for approval before running a command."""
    from utils.ui import console
    
    # Check if it's a safe command
    cmd_lower = command.strip().lower()
    for safe in SAFE_COMMANDS:
        if cmd_lower.startswith(safe):
            return True
    
    # Check if it's a dangerous command
    is_dangerous = any(pattern in cmd_lower for pattern in DANGEROUS_PATTERNS)
    
    if is_dangerous:
        console.print(f"\n  [bold red]⚠  DANGEROUS COMMAND DETECTED[/bold red]")
    else:
        console.print(f"\n  [bold yellow]⚡ Command requires approval[/bold yellow]")
    
    console.print(f"  [dim]$[/dim] [bold white]{command}[/bold white]")
    
    try:
        from prompt_toolkit import prompt as pt_prompt
        answer = pt_prompt("  Allow? (y/n): ").strip().lower()
        if answer in ('y', 'yes'):
            console.print("  [bold green]✓ Approved[/bold green]")
            return True
        else:
            console.print("  [bold red]✗ Rejected[/bold red]")
            return False
    except (KeyboardInterrupt, EOFError):
        console.print("  [bold red]✗ Rejected[/bold red]")
        return False

def run_command_tool(command: str) -> str:
    """Run a shell command with user approval and live output."""
    from utils.ui import console
    if not _approve_command(command):
        return "Command rejected by user."
    
    cwd = os.getenv("FOLDER_PATH", ".")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120
        )
        output = result.stdout + result.stderr
        if not output.strip():
            output = f"Command '{command}' executed successfully with no output (Exit code {result.returncode})."
        
        # Display output to user in a styled box
        display_output = output.strip()[:2000]  # Show first 2000 chars to user
        exit_style = "green" if result.returncode == 0 else "red"
        console.print(f"  [dim]┌─ Output (exit code: [{exit_style}]{result.returncode}[/{exit_style}]) ─[/dim]")
        for line in display_output.split('\n')[:30]:  # Max 30 lines displayed
            console.print(f"  [dim]│[/dim] {line}")
        if len(output.strip()) > 2000 or output.count('\n') > 30:
            console.print(f"  [dim]│ ... (truncated, full output sent to agent)[/dim]")
        console.print(f"  [dim]└────[/dim]")
        
        return output[:8000]  # Full output to agent for analysis
    except subprocess.TimeoutExpired:
        console.print(f"  [bold red]  ⏱ Command timed out after 120s[/bold red]")
        return "Error: Command timed out after 120 seconds."
    except Exception as e:
        console.print(f"  [bold red]  ✗ {e}[/bold red]")
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
        except Exception:
            pass
        
        _log_edit_to_memory(path, "Replaced snippet in")
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
        except Exception:
            pass
        
        _log_edit_to_memory(path, f"Applied {len(diffs)} diff(s) to")
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

def arxiv_search_tool(query: str, max_results: int = 5) -> str:
    """Search arXiv for academic papers."""
    try:
        import arxiv
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        results = list(client.results(search))
        
        if not results:
            return "No papers found on arXiv for your query."
        
        output = f"arXiv Search Results for '{query}':\n\n"
        for i, paper in enumerate(results):
            authors = ', '.join(a.name for a in paper.authors[:3])
            if len(paper.authors) > 3:
                authors += ' et al.'
            output += f"{i+1}. {paper.title}\n"
            output += f"   Authors: {authors}\n"
            output += f"   Published: {paper.published.strftime('%Y-%m-%d')}\n"
            output += f"   URL: {paper.entry_id}\n"
            output += f"   PDF: {paper.pdf_url}\n"
            summary = paper.summary.replace('\n', ' ')[:300]
            output += f"   Abstract: {summary}...\n\n"
        
        return output
    except ImportError:
        return "Error: arxiv package is not installed. Please run 'pip install arxiv'."
    except Exception as e:
        return f"Error searching arXiv: {e}"

def read_url_tool(url: str) -> str:
    """Fetch and extract text from a webpage."""
    try:
        import requests
        from bs4 import BeautifulSoup
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator='\n', strip=True)
        return text[:15000]
    except ImportError:
        return "Error: requests and beautifulsoup4 packages are required."
    except Exception as e:
        return f"Error reading URL: {e}"

def run_background_command_tool(command: str) -> str:
    """Start a shell command in the background with user approval."""
    if not _approve_command(command):
        return "Command rejected by user."
    
    cwd = os.getenv("FOLDER_PATH", ".")
    try:
        job_id = str(uuid.uuid4())[:8]
        out_file = os.path.join(cwd, f".agent_job_{job_id}.log")
        f = open(out_file, "w", encoding="utf-8")
        process = subprocess.Popen(command, shell=True, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, text=True)
        BACKGROUND_PROCESSES[job_id] = {"process": process, "out_file": out_file, "file_obj": f, "command": command}
        return f"Started background process '{command}' with Job ID: {job_id}. Output is being logged. Use read_terminal_output to check its status."
    except Exception as e:
        return f"Error starting background command: {e}"

def read_terminal_output_tool(job_id: str) -> str:
    """Check the status and output of a background job."""
    if job_id not in BACKGROUND_PROCESSES:
        return f"Error: No active background job found with ID {job_id}."
    job = BACKGROUND_PROCESSES[job_id]
    process = job["process"]
    out_file = job["out_file"]
    status = process.poll()
    status_str = "RUNNING" if status is None else f"FINISHED (Exit code: {status})"
    try:
        with open(out_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        output = "".join(lines[-100:])
        return f"Job {job_id} ({job['command']}) - Status: {status_str}\n\nLast 100 lines of output:\n{output}"
    except Exception as e:
        return f"Error reading output: {e}"

def get_file_symbols_tool(path: str) -> str:
    """Parse a python file and return its structure."""
    if not os.path.isabs(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
    if not os.path.exists(path):
        return f"Error: File {path} does not exist."
    if not path.endswith('.py'):
        return "Error: get_file_symbols currently only supports Python (.py) files."
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(f"class {node.name}:")
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                args = [a.arg for a in node.args.args]
                symbols.append(f"  def {node.name}({', '.join(args)}):")
        if not symbols:
            return "No classes or functions found."
        return "\n".join(symbols)
    except Exception as e:
        return f"Error parsing symbols: {e}"

def ask_human_tool(question: str) -> str:
    """Pause execution and ask the human user a question."""
    from utils.ui import console
    console.print(f"\n  [bold magenta]💬 Agent has a question:[/bold magenta]")
    console.print(f"  [white]{question}[/white]")
    try:
        from prompt_toolkit import prompt as pt_prompt
        answer = pt_prompt("  > ")
        return f"User replied: {answer}"
    except Exception as e:
        return f"Error getting user input: {e}"

def git_command_tool(command: str) -> str:
    """Run a git command with approval for write operations."""
    from utils.ui import console
    cwd = os.getenv("FOLDER_PATH", ".")
    cmd_lower = command.strip().lower()
    
    # Block dangerous git operations entirely
    blocked = ['push --force', 'reset --hard', 'clean -fd', 'branch -D']
    if any(b in cmd_lower for b in blocked):
        console.print(f"\n  [bold red]⚠  Dangerous git command blocked: git {command}[/bold red]")
        console.print(f"  [dim]Use the terminal directly if you really need this.[/dim]")
        return "Blocked: This git command is destructive and requires manual execution."
    
    # Operations that need user approval
    needs_approval = ['commit', 'push', 'add', 'merge', 'rebase', 'checkout -b', 'tag']
    if any(op in cmd_lower for op in needs_approval):
        console.print(f"\n  [bold yellow]📌 Git operation requires approval[/bold yellow]")
        console.print(f"  [dim]$[/dim] [bold white]git {command}[/bold white]")
        try:
            from prompt_toolkit import prompt as pt_prompt
            answer = pt_prompt("  Allow? (y/n): ").strip().lower()
            if answer not in ('y', 'yes'):
                console.print("  [bold red]✗ Rejected[/bold red]")
                return "Git command rejected by user."
            console.print("  [bold green]✓ Approved[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("  [bold red]✗ Rejected[/bold red]")
            return "Git command rejected by user."
    
    try:
        result = subprocess.run(
            f"git {command}", shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip()
        return output or f"git {command} executed successfully."
    except Exception as e:
        return f"Git error: {e}"

def codebase_search_tool(query: str, regex: str = None, directory: str = None) -> str:
    """Combined semantic + regex codebase search."""
    results = []
    base_dir = get_base_dir(directory or "")
    
    # Part 1: Regex search (if pattern provided)
    if regex:
        regex_results = grep_tool(base_dir, regex)
        if regex_results and "Error" not in regex_results:
            results.append("═══ Regex Matches ═══\n")
            results.append(regex_results)
            results.append("")
    
    # Part 2: Semantic search (always)
    try:
        from core.memory import semantic_search, collection
        if collection.count() > 0:
            semantic_results = semantic_search(query, n_results=5)
            if semantic_results and "empty" not in semantic_results.lower():
                results.append("═══ Semantic Matches (by meaning) ═══\n")
                results.append(semantic_results)
        else:
            results.append("[Semantic index is empty. Run index_codebase first for semantic results.]")
    except Exception as e:
        results.append(f"[Semantic search unavailable: {e}]")
    
    # Part 3: Filename search (always — find files matching the query words)
    try:
        query_words = query.lower().split()
        matching_files = []
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', '.venv', 'venv')]
            for f in files:
                fname_lower = f.lower()
                if any(w in fname_lower for w in query_words):
                    rel_path = os.path.relpath(os.path.join(root, f), base_dir)
                    matching_files.append(rel_path)
        if matching_files:
            results.append("\n═══ Matching Filenames ═══\n")
            for mf in matching_files[:10]:
                results.append(f"  📄 {mf}")
    except Exception:
        pass
    
    if not results:
        return f"No results found for '{query}'" + (f" with regex '{regex}'" if regex else "")
    
    return "\n".join(results)

def batch_edit_files_tool(edits: list) -> str:
    """Edit multiple files in a single tool call."""
    results = []
    for edit in edits:
        filepath = edit.get("path", "")
        content = edit.get("content", "")
        res = edit_file_tool(filepath, content)
        results.append(f"{filepath}: {res}")
    return "\n".join(results)

def semantic_replace_tool(path: str, target: str, replacement: str) -> str:
    """Replace text using fuzzy matching if exact match fails."""
    exact_res = replace_in_file_tool(path, target, replacement)
    if "Error: Target content not found" not in exact_res:
        return exact_res
        
    if not os.path.isabs(path):
        folder = os.getenv("FOLDER_PATH", ".")
        path = os.path.join(folder, path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        target_lines = target.strip().split('\n')
        content_lines = content.split('\n')
        best_ratio = 0
        best_idx = -1
        target_len = len(target_lines)
        if target_len == 0 or len(content_lines) < target_len:
            return "Error: Target is empty or file is smaller than target."
            
        for i in range(len(content_lines) - target_len + 1):
            window = "\n".join(content_lines[i:i+target_len])
            ratio = difflib.SequenceMatcher(None, target.strip(), window).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
                
        if best_ratio > 0.85:
            matched_text = "\n".join(content_lines[best_idx:best_idx+target_len])
            new_content = content.replace(matched_text, replacement)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            try:
                from core.memory import index_file
                index_file(path, new_content)
            except Exception:
                pass
            return f"Exact match failed. Performed fuzzy replacement (Confidence: {best_ratio:.2f}) in {path}."
        else:
            return f"Error: Fuzzy match failed (Best confidence: {best_ratio:.2f} < 0.85). Please review your target string."
    except Exception as e:
        return f"Error in semantic replace: {e}"

# Minimal tool set for smaller models that can't handle 24+ tools
CORE_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "cat",
            "description": "Read a file's contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read."},
                    "start_line": {"type": "integer", "description": "Optional start line."},
                    "end_line": {"type": "integer", "description": "Optional end line."},
                    "line_start": {"type": "integer", "description": "Alias for start_line."},
                    "line_end": {"type": "integer", "description": "Alias for end_line."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List directory contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to list."}
                },
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Create or overwrite a file with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "content": {"type": "string", "description": "Full file content."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run."}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a regex pattern in files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to search."},
                    "pattern": {"type": "string", "description": "Regex pattern."}
                },
                "required": ["directory", "pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_repo_map",
            "description": "Get a tree map of the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Root directory."}
                },
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Replace exact text in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "target": {"type": "string", "description": "Text to find."},
                    "replacement": {"type": "string", "description": "Replacement text."}
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_human",
            "description": "Ask the user a question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question to ask."}
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "codebase_search",
            "description": "Search the codebase using BOTH semantic similarity AND regex. Best tool for finding specific code, functions, or patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you're looking for."},
                    "regex": {"type": "string", "description": "Optional regex pattern."},
                    "directory": {"type": "string", "description": "Optional subdirectory."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_command",
            "description": "Run a git command (e.g., 'status', 'add -A', 'commit -m \"msg\"', 'push').",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Git subcommand without 'git' prefix."}
                },
                "required": ["command"]
            }
        }
    }
]

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
                    },
                    "line_start": {
                        "type": "integer",
                        "description": "Alias for start_line."
                    },
                    "line_end": {
                        "type": "integer",
                        "description": "Alias for end_line."
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
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Fetch and extract clean text from any URL (e.g., to read documentation pages).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to read."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_background_command",
            "description": "Start a long-running shell command in the background (like starting a dev server). Returns a Job ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run in the background."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_terminal_output",
            "description": "Read the last 100 lines of output from a background job.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The ID of the background job."
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_symbols",
            "description": "Parse a Python file and return a skeleton of all classes and functions without their bodies. Extremely token-efficient for exploring architecture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the .py file."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_human",
            "description": "Pause execution to explicitly ask the human user a question or for clarification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user in the terminal."
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_replace",
            "description": "Like replace_in_file, but uses fuzzy matching to find the target code if the exact match fails (e.g., if you messed up the indentation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file."
                    },
                    "target": {
                        "type": "string",
                        "description": "The block of code you want to replace."
                    },
                    "replacement": {
                        "type": "string",
                        "description": "The new block of code."
                    }
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "arxiv_search",
            "description": "Search arXiv for academic research papers. Returns titles, authors, abstracts, and PDF links. Use this when implementing ML algorithms, looking for state-of-the-art techniques, or referencing research.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (e.g., 'transformer attention mechanism', 'YOLO object detection')."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Optional. Max number of papers to return (default 5)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_command",
            "description": "Run a git command (e.g., 'status', 'add -A', 'commit -m \"msg\"', 'log -5', 'diff'). Dangerous operations like force-push are blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The git subcommand to run (without 'git' prefix)."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_edit_files",
            "description": "Create or overwrite multiple files in one tool call. Each edit is {path, content}. Use this for scaffolding projects with many files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"}
                            },
                            "required": ["path", "content"]
                        },
                        "description": "Array of {path, content} objects."
                    }
                },
                "required": ["edits"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "codebase_search",
            "description": "Search the codebase using BOTH semantic similarity AND regex. Combines vector-based search (finds code by meaning), regex grep (finds exact patterns), and filename matching. Best tool for finding specific code, functions, or patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what you're looking for (e.g., 'database connection setup', 'authentication logic')."
                    },
                    "regex": {
                        "type": "string",
                        "description": "Optional. A regex pattern to search for exact matches (e.g., 'def train_model', 'import torch')."
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional. Subdirectory to limit the search to."
                    }
                },
                "required": ["query"]
            }
        }
    },
    # ══════════════════════════════════════════════════════════════
    # NEW v2 TOOLS — Repository Mapping, LSP Navigation, Self-Heal,
    #                Task Tracking, Sandbox
    # ══════════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "get_ast_map",
            "description": "Generate an AST-based architectural map of the entire codebase. Shows every file's classes, methods, function signatures, and imports WITHOUT the code bodies. Extremely token-efficient for understanding large codebases at a glance. Cached for performance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Root directory to map."},
                    "verbose": {"type": "boolean", "description": "If true, include docstrings and decorators."}
                },
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_references",
            "description": "Find ALL usages of a symbol (function, class, variable) across the entire codebase. Like an IDE's 'Find All References'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "The symbol name to search for."},
                    "directory": {"type": "string", "description": "Optional root directory."}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_definition",
            "description": "Find where a function, class, or variable is DEFINED. Like an IDE's 'Go to Definition'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "The symbol to find the definition of."},
                    "directory": {"type": "string", "description": "Optional root directory."}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_implementations",
            "description": "Find all subclasses or implementations of a class/interface across the codebase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string", "description": "The class/interface name."},
                    "directory": {"type": "string", "description": "Optional root directory."}
                },
                "required": ["class_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_call_graph",
            "description": "Find all functions that CALL a given function. Useful for impact analysis before refactoring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string", "description": "The function name."},
                    "directory": {"type": "string", "description": "Optional root directory."}
                },
                "required": ["function_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lint_check",
            "description": "Run linter (ruff) on a Python file and return all lint errors with line numbers and codes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to the file to lint."}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the project's test suite (auto-detects pytest/npm test). Returns pass/fail counts and error details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_command": {"type": "string", "description": "Optional custom test command. Auto-detected if not provided."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task in the persistent scratchpad. Use this to track multi-step work and stay oriented.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short task title."},
                    "description": {"type": "string", "description": "Optional detailed description."},
                    "priority": {"type": "string", "description": "Priority: high, normal, or low."}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as complete in the scratchpad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The task ID to mark complete."}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "View all current tasks and their status from the scratchpad.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_subtask",
            "description": "Add a subtask to an existing task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Parent task ID."},
                    "subtask": {"type": "string", "description": "Subtask description."}
                },
                "required": ["task_id", "subtask"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": "Add a free-form note to the scratchpad for future reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The note text."}
                },
                "required": ["note"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": "Set the high-level session goal. This is displayed in the scratchpad and helps maintain focus.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "The session goal."}
                },
                "required": ["goal"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_status",
            "description": "Check the Docker sandbox status (enabled/disabled, active containers, resource limits).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_codebase",
            "description": "Deep scan the ENTIRE codebase — reads every file (code, models, data, docs, scripts, configs), understands what each module does, maps connections between them, detects the tech stack, and saves a persistent brain document. Use this when the user says 'scan the codebase' or when you need to deeply understand a project before making changes. After scanning, the brain auto-injects into your context on every turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Root directory to scan. Defaults to FOLDER_PATH."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_project",
            "description": "Run full project verification: compile check all Python files, validate imports resolve, lint check, run tests if they exist, and verify tool schema consistency. Returns a structured pass/fail report. Use this AFTER making changes to verify nothing is broken.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Root directory to verify. Defaults to FOLDER_PATH."}
                },
                "required": []
            }
        }
    }
]

def execute_tool(tool_name: str, args: dict) -> str:
    from utils.ui import console
    
    TOOL_ICONS = {
        'cat': '📄', 'grep': '🔍', 'ls': '📁', 'edit_file': '✏️',
        'delete_file': '🗑️', 'get_repo_map': '🗺️', 'run_command': '⚡',
        'replace_in_file': '🔧', 'apply_diff': '🔧', 'websearch': '🌐',
        'read_url': '🌐', 'run_background_command': '⚡', 'read_terminal_output': '📋',
        'get_file_symbols': '🔬', 'ask_human': '💬', 'semantic_replace': '🔧',
        'index_codebase': '📇', 'semantic_search': '🧠', 'arxiv_search': '📚',
        'git_command': '📌', 'batch_edit_files': '📦', 'codebase_search': '🔮',
        # New tools from v2 features
        'get_ast_map': '🧬', 'find_references': '🔗', 'go_to_definition': '🎯',
        'find_implementations': '🏗️', 'get_call_graph': '📊',
        'lint_check': '🩺', 'run_tests': '🧪',
        'create_task': '📋', 'complete_task': '✅', 'get_tasks': '📝',
        'add_subtask': '📎', 'add_note': '🗒️', 'set_goal': '🎯',
        'sandbox_status': '🐳',
        'scan_codebase': '🧠',
        'verify_project': '🔍',
    }
    icon = TOOL_ICONS.get(tool_name, '🔧')
    
    # Build a short, readable summary of the args
    short_args = ', '.join(f'{k}={str(v)[:40]}' for k,v in args.items())
    console.print(f"  {icon} [bold yellow]{tool_name}[/bold yellow][dim]({short_args})[/dim]")
    if tool_name == "cat":
        # Accept both naming conventions LLMs use
        start = args.get("start_line") or args.get("line_start")
        end = args.get("end_line") or args.get("line_end")
        return cat_tool(args.get("path", ""), start, end)
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
    elif tool_name == "read_url":
        return read_url_tool(args.get("url", ""))
    elif tool_name == "run_background_command":
        return run_background_command_tool(args.get("command", ""))
    elif tool_name == "read_terminal_output":
        return read_terminal_output_tool(args.get("job_id", ""))
    elif tool_name == "get_file_symbols":
        return get_file_symbols_tool(args.get("path", ""))
    elif tool_name == "ask_human":
        return ask_human_tool(args.get("question", ""))
    elif tool_name == "semantic_replace":
        return semantic_replace_tool(args.get("path", ""), args.get("target", ""), args.get("replacement", ""))
    elif tool_name == "arxiv_search":
        return arxiv_search_tool(args.get("query", ""), args.get("max_results", 5))
    elif tool_name == "git_command":
        return git_command_tool(args.get("command", ""))
    elif tool_name == "batch_edit_files":
        return batch_edit_files_tool(args.get("edits", []))
    elif tool_name == "codebase_search":
        return codebase_search_tool(args.get("query", ""), args.get("regex"), args.get("directory"))
    # ── New v2 tools ──
    elif tool_name == "get_ast_map":
        from core.repo_map import get_ast_repo_map
        return get_ast_repo_map(args.get("directory", ""), args.get("verbose", False))
    elif tool_name == "find_references":
        from core.lsp_navigator import find_references
        return find_references(args.get("symbol", ""), args.get("directory"))
    elif tool_name == "go_to_definition":
        from core.lsp_navigator import go_to_definition
        return go_to_definition(args.get("symbol", ""), args.get("directory"))
    elif tool_name == "find_implementations":
        from core.lsp_navigator import find_implementations
        return find_implementations(args.get("class_name", ""), args.get("directory"))
    elif tool_name == "get_call_graph":
        from core.lsp_navigator import get_call_graph
        return get_call_graph(args.get("function_name", ""), args.get("directory"))
    elif tool_name == "lint_check":
        from core.self_heal import lint_check_tool
        return lint_check_tool(args.get("filepath", ""))
    elif tool_name == "run_tests":
        from core.self_heal import run_tests_tool
        return run_tests_tool(args.get("test_command"))
    elif tool_name == "create_task":
        from core.scratchpad import create_task_tool
        return create_task_tool(args.get("title", ""), args.get("description", ""), args.get("priority", "normal"))
    elif tool_name == "complete_task":
        from core.scratchpad import complete_task_tool
        return complete_task_tool(int(args.get("task_id", 0)))
    elif tool_name == "get_tasks":
        from core.scratchpad import get_tasks_tool
        return get_tasks_tool()
    elif tool_name == "add_subtask":
        from core.scratchpad import add_subtask_tool
        return add_subtask_tool(int(args.get("task_id", 0)), args.get("subtask", ""))
    elif tool_name == "add_note":
        from core.scratchpad import add_note_tool
        return add_note_tool(args.get("note", ""))
    elif tool_name == "set_goal":
        from core.scratchpad import set_goal_tool
        return set_goal_tool(args.get("goal", ""))
    elif tool_name == "sandbox_status":
        from core.sandbox import sandbox_status_tool
        return sandbox_status_tool()
    elif tool_name == "scan_codebase":
        from core.codebase_brain import scan_codebase_tool
        return scan_codebase_tool(args.get("directory", ""))
    elif tool_name == "verify_project":
        from core.verify import verify_project_tool
        return verify_project_tool(args.get("directory", ""))
    else:
        return f"Error: Unknown tool {tool_name}"
