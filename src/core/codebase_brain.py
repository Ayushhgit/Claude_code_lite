"""
codebase_brain.py — Deep Codebase Understanding & Persistent Brain

This is the system that makes REVI actually understand the codebase the way
a senior developer would. When the user says "scan the codebase", this module:

1. Walks every file in the project
2. Reads each file's content and extracts what it DOES (not just its structure)
3. Builds a "brain document" — a rich, human-readable map that includes:
   - What each module is responsible for
   - Key functions/classes and what they do
   - How modules connect to each other (imports, calls)
   - Configuration and environment setup
   - Entry points and main flows
4. Stores the brain document at .kinda_claude/codebase_brain.md
5. Auto-injects a compact version into the LLM context on every turn

This means when the user later says "add authentication", the agent already knows:
- Where the routes are
- Where the middleware goes
- What database layer exists
- What the existing patterns look like

No need to re-scan — the brain persists across sessions.
"""

import os
import json
import time
import datetime
from core.repo_map import build_repo_map, format_repo_map, SKIP_DIRS, SUPPORTED_EXTENSIONS
from utils.ui import console


def _human_size(size_bytes):
    """Convert bytes to human readable string."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.0f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


BRAIN_DIR = ".kinda_claude"
BRAIN_FILE = "codebase_brain.md"
BRAIN_JSON = "codebase_brain.json"

# Files that are especially important for understanding a project
PRIORITY_FILES = [
    "main.py", "app.py", "index.py", "server.py", "__init__.py",
    "index.js", "index.ts", "app.js", "app.ts", "server.js", "server.ts",
    "routes.py", "urls.py", "views.py", "models.py", "schema.py",
    "config.py", "settings.py", "constants.py",
    "requirements.txt", "package.json", "pyproject.toml",
    ".env", ".env.example", "Dockerfile", "docker-compose.yml",
    "README.md", "Makefile",
]


# ─── Core Scan Logic ─────────────────────────────────────────────────────────

def deep_scan(directory: str) -> dict:
    """
    Perform a deep scan of the codebase. Reads every file, extracts
    structure AND semantics, builds a complete understanding.

    Returns a dict with everything the agent needs to know about the project.
    """
    start_time = time.time()

    brain = {
        "project_root": directory,
        "project_name": os.path.basename(directory),
        "scanned_at": datetime.datetime.now().isoformat(),
        "summary": "",
        "tech_stack": [],
        "entry_points": [],
        "config_files": {},
        "modules": {},        # path -> {purpose, key_elements, imports, exports}
        "other_files": {},    # non-code files: .md, .bat, .txt, models, data, etc.
        "directories": [],    # all directories including empty ones
        "dependencies": [],
        "file_tree": [],
        "stats": {},
    }

    # ── Step 1: Build AST map for structure ──
    repo_map = build_repo_map(directory, force_refresh=True)
    brain["stats"] = repo_map.get("stats", {})

    # ── Step 2: Detect tech stack ──
    brain["tech_stack"] = _detect_tech_stack(directory)

    # ── Step 3: Read and analyze EVERY file (not just code) ──
    # Non-code extensions that are still important to capture
    TEXT_EXTENSIONS = {'.md', '.txt', '.rst', '.csv', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.bat', '.sh', '.cmd', '.ps1', '.env', '.gitignore', '.dockerignore', '.editorconfig'}
    MODEL_EXTENSIONS = {'.pkl', '.pickle', '.h5', '.hdf5', '.pt', '.pth', '.onnx', '.pb', '.tflite', '.bin', '.safetensors', '.ckpt', '.joblib', '.npy', '.npz'}
    DATA_EXTENSIONS = {'.csv', '.tsv', '.parquet', '.feather', '.sqlite', '.db', '.xlsx', '.xls'}
    IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.bmp'}
    
    all_files = []
    all_dirs = []
    
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        
        # Track ALL directories (including empty ones — this matters for project structure)
        for d in dirs:
            dir_rel = os.path.relpath(os.path.join(root, d), directory).replace('\\', '/')
            dir_contents = os.listdir(os.path.join(root, d))
            all_dirs.append({
                "path": dir_rel,
                "empty": len(dir_contents) == 0,
                "file_count": len([f for f in dir_contents if os.path.isfile(os.path.join(root, d, f))]),
            })
        
        for filename in files:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
            ext = os.path.splitext(filename)[1].lower()
            
            try:
                file_size = os.path.getsize(filepath)
            except OSError:
                file_size = 0
            
            all_files.append(rel_path)

            # Read priority files fully (configs, manifests, entry points)
            if filename in PRIORITY_FILES:
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    brain["config_files"][rel_path] = content[:2000]
                    if any(ep in filename for ep in ["main", "app", "index", "server"]):
                        brain["entry_points"].append(rel_path)
                except Exception:
                    pass

            # Analyze code files with AST
            if ext in SUPPORTED_EXTENSIONS:
                file_info = repo_map.get("files", {}).get(rel_path, {})
                if file_info and not file_info.get("error"):
                    module_info = _analyze_module(rel_path, file_info, filepath)
                    brain["modules"][rel_path] = module_info
            
            # Capture NON-code files (models, data, docs, scripts, configs)
            elif ext not in SUPPORTED_EXTENSIONS:
                file_entry = {
                    "size": file_size,
                    "size_human": _human_size(file_size),
                }
                
                if ext in MODEL_EXTENSIONS:
                    file_entry["type"] = "model"
                elif ext in DATA_EXTENSIONS:
                    file_entry["type"] = "data"
                elif ext in IMAGE_EXTENSIONS:
                    file_entry["type"] = "image"
                elif ext in TEXT_EXTENSIONS or ext in ('.bat', '.sh', '.cmd', '.ps1'):
                    file_entry["type"] = "text/script"
                    # Read text content for small text files
                    if file_size < 50000:
                        try:
                            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                                file_entry["preview"] = f.read()[:500]
                        except Exception:
                            pass
                else:
                    file_entry["type"] = "other"
                
                brain["other_files"][rel_path] = file_entry

    brain["file_tree"] = sorted(all_files)
    brain["directories"] = all_dirs

    # ── Step 4: Detect dependencies ──
    brain["dependencies"] = _extract_dependencies(directory, brain["config_files"])

    # ── Step 5: Build module connection graph ──
    _build_connection_graph(brain)

    # ── Step 6: Generate summary ──
    brain["summary"] = _generate_summary(brain)

    brain["stats"]["scan_time_s"] = round(time.time() - start_time, 2)

    return brain


def _detect_tech_stack(directory: str) -> list:
    """Detect what technologies the project uses."""
    stack = []

    checks = {
        "Python": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
        "Node.js": ["package.json"],
        "TypeScript": ["tsconfig.json"],
        "React": ["package.json"],  # Will check contents
        "Next.js": ["next.config.js", "next.config.ts", "next.config.mjs"],
        "Django": ["manage.py"],
        "Flask": ["requirements.txt"],  # Will check contents
        "FastAPI": ["requirements.txt"],  # Will check contents
        "Docker": ["Dockerfile", "docker-compose.yml"],
        "Git": [".git"],
    }

    for tech, files in checks.items():
        for f in files:
            if os.path.exists(os.path.join(directory, f)):
                # Extra content checks
                if tech == "React":
                    try:
                        with open(os.path.join(directory, f), "r") as fp:
                            if "react" in fp.read().lower():
                                stack.append("React")
                    except Exception:
                        pass
                    continue
                elif tech in ("Flask", "FastAPI"):
                    try:
                        with open(os.path.join(directory, f), "r") as fp:
                            content = fp.read().lower()
                            if tech.lower() in content:
                                stack.append(tech)
                    except Exception:
                        pass
                    continue
                else:
                    if tech not in stack:
                        stack.append(tech)
                break

    return stack


def _analyze_module(rel_path: str, file_info: dict, abs_path: str) -> dict:
    """Analyze a single module to understand its PURPOSE, not just structure."""
    module = {
        "purpose": "",
        "classes": [],
        "functions": [],
        "imports": file_info.get("imports", []),
        "exports": file_info.get("exports", []),
        "globals": file_info.get("globals", []),
        "lines": file_info.get("_lines", 0),
        "connections": [],  # Other modules this imports from
    }

    # Extract class info
    for cls in file_info.get("classes", []):
        class_summary = {
            "name": cls["name"],
            "methods": [m["name"] for m in cls.get("methods", [])],
            "docstring": cls.get("docstring", "")[:100],
        }
        if cls.get("bases"):
            class_summary["bases"] = cls["bases"]
        module["classes"].append(class_summary)

    # Extract function info
    for func in file_info.get("functions", []):
        func_summary = {
            "name": func["name"],
            "args": func.get("args", []),
            "docstring": func.get("docstring", "")[:100],
        }
        if func.get("return_type"):
            func_summary["return_type"] = func["return_type"]
        module["functions"].append(func_summary)

    # Infer purpose from filename + content
    module["purpose"] = _infer_purpose(rel_path, module)

    # Extract local connections (which project modules does this import?)
    for imp in module["imports"]:
        # Check if it's a local import (not from stdlib/pip)
        parts = imp.split(".")
        if parts[0] in ("core", "llm", "utils", "src", "app", "api", "models", "routes", "services"):
            module["connections"].append(imp)

    return module


def _infer_purpose(rel_path: str, module: dict) -> str:
    """Infer what a module does based on its name, classes, and functions."""
    filename = os.path.basename(rel_path).replace(".py", "").replace(".js", "").replace(".ts", "")

    # Common pattern matching
    purpose_map = {
        "agent": "Core agent orchestration and LLM interaction loop",
        "tools": "Tool definitions, schemas, and execution dispatcher",
        "router": "Intent classification and task routing",
        "memory": "Vector database (ChromaDB) for semantic code search",
        "prompt": "System prompt templates for the LLM",
        "planner": "Multi-agent task planning (Architect/Reviewer)",
        "self_heal": "Self-healing loop with linting and test running",
        "sandbox": "Docker-based sandboxed command execution",
        "scratchpad": "Persistent task tracking and scratchpad",
        "lsp_navigator": "Semantic code navigation (references, definitions)",
        "repo_map": "AST-based repository structure mapping",
        "codebase_brain": "Deep codebase understanding and brain document",
        "main": "CLI entry point and interactive REPL",
        "app": "Application entry point",
        "server": "HTTP server setup and configuration",
        "models": "Data models and database schemas",
        "routes": "URL routes and API endpoints",
        "views": "View controllers and request handlers",
        "config": "Configuration and settings",
        "utils": "Utility functions and helpers",
        "ui": "User interface components and formatting",
        "auth": "Authentication and authorization",
        "middleware": "Request/response middleware",
        "tests": "Test suite",
        "migrations": "Database migrations",
    }

    if filename in purpose_map:
        return purpose_map[filename]

    # Try to infer from docstrings
    for cls in module.get("classes", []):
        if cls.get("docstring"):
            return cls["docstring"][:100]
    for func in module.get("functions", []):
        if func.get("docstring"):
            return func["docstring"][:100]

    # Fall back to path-based inference
    parts = rel_path.split("/")
    if len(parts) > 1:
        return f"Module in {parts[0]}/ package"

    return "Utility module"


def _extract_dependencies(directory: str, config_files: dict) -> list:
    """Extract project dependencies from manifest files."""
    deps = []

    # Python: requirements.txt
    req_content = config_files.get("requirements.txt", "")
    if req_content:
        for line in req_content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
                if pkg:
                    deps.append(pkg)

    # Node: package.json
    pkg_content = config_files.get("package.json", "")
    if pkg_content:
        try:
            pkg = json.loads(pkg_content)
            for section in ["dependencies", "devDependencies"]:
                if section in pkg:
                    deps.extend(pkg[section].keys())
        except json.JSONDecodeError:
            pass

    return deps


def _build_connection_graph(brain: dict):
    """Build a graph of which modules depend on which other modules."""
    for path, module in brain.get("modules", {}).items():
        connections = set()
        for imp in module.get("imports", []):
            # Try to resolve the import to a file in the project
            parts = imp.split(".")
            for other_path in brain.get("modules", {}):
                other_name = os.path.splitext(os.path.basename(other_path))[0]
                if other_name in parts and other_path != path:
                    connections.add(other_path)
        module["connections"] = list(connections)


def _generate_summary(brain: dict) -> str:
    """Generate a human-readable one-paragraph summary of the project."""
    name = brain.get("project_name", "Unknown")
    stack = ", ".join(brain.get("tech_stack", [])) or "Unknown stack"
    code_count = brain["stats"].get("total_files", 0)
    total_count = len(brain.get("file_tree", []))
    func_count = brain["stats"].get("total_functions", 0)
    class_count = brain["stats"].get("total_classes", 0)
    other_count = len(brain.get("other_files", {}))
    deps = brain.get("dependencies", [])
    entries = brain.get("entry_points", [])

    summary = f"{name} is a {stack} project with {total_count} total files ({code_count} code, {other_count} other), {class_count} classes, and {func_count} functions."
    if deps:
        summary += f" Key dependencies: {', '.join(deps[:8])}."
    if entries:
        summary += f" Entry points: {', '.join(entries[:3])}."

    return summary


# ─── Brain Document Generator ────────────────────────────────────────────────

def generate_brain_document(brain: dict) -> str:
    """Generate the persistent brain document (markdown) from scan results."""
    lines = []
    lines.append("# 🧠 REVI Codebase Brain\n")
    lines.append(f"**Scanned**: {brain.get('scanned_at', 'Unknown')}")
    lines.append(f"**Project**: {brain.get('project_name', '?')}")
    lines.append(f"**Stack**: {', '.join(brain.get('tech_stack', []))}")
    lines.append(f"**Files**: {brain['stats'].get('total_files', 0)} | "
                 f"**Classes**: {brain['stats'].get('total_classes', 0)} | "
                 f"**Functions**: {brain['stats'].get('total_functions', 0)}")
    lines.append(f"\n## Summary\n{brain.get('summary', '')}\n")

    # Entry points
    entries = brain.get("entry_points", [])
    if entries:
        lines.append("## Entry Points")
        for ep in entries:
            lines.append(f"- `{ep}`")
        lines.append("")

    # Dependencies
    deps = brain.get("dependencies", [])
    if deps:
        lines.append("## Dependencies")
        lines.append(f"{', '.join(deps[:20])}")
        lines.append("")

    # Module-by-module breakdown
    lines.append("## Module Map\n")
    for path, module in sorted(brain.get("modules", {}).items()):
        purpose = module.get("purpose", "")
        lines.append(f"### `{path}`")
        if purpose:
            lines.append(f"**Purpose**: {purpose}")

        # Classes
        for cls in module.get("classes", []):
            bases = f"({', '.join(cls.get('bases', []))})" if cls.get("bases") else ""
            methods = ", ".join(cls.get("methods", [])[:8])
            lines.append(f"- **class {cls['name']}{bases}**: methods=[{methods}]")
            if cls.get("docstring"):
                lines.append(f"  - _{cls['docstring']}_")

        # Functions
        for func in module.get("functions", []):
            args = ", ".join(func.get("args", [])[:5])
            ret = f" -> {func['return_type']}" if func.get("return_type") else ""
            lines.append(f"- **def {func['name']}**({args}){ret}")
            if func.get("docstring"):
                lines.append(f"  - _{func['docstring']}_")

        # Connections
        connections = module.get("connections", [])
        if connections:
            lines.append(f"- **imports from**: {', '.join(connections[:5])}")

        lines.append("")

    # Non-code files section
    other_files = brain.get("other_files", {})
    if other_files:
        lines.append("## Other Files (non-code)\n")
        # Group by type
        by_type = {}
        for path, info in sorted(other_files.items()):
            ftype = info.get("type", "other")
            by_type.setdefault(ftype, []).append((path, info))
        
        for ftype, files_list in sorted(by_type.items()):
            lines.append(f"### {ftype.title()} ({len(files_list)} files)")
            for path, info in files_list:
                size = info.get("size_human", "?")
                lines.append(f"- `{path}` ({size})")
            lines.append("")

    # Directories section
    dirs_info = brain.get("directories", [])
    empty_dirs = [d for d in dirs_info if d.get("empty")]
    if empty_dirs:
        lines.append("## Empty Directories")
        for d in empty_dirs:
            lines.append(f"- `{d['path']}/` (empty)")
        lines.append("")

    # Config files (abbreviated)
    config = brain.get("config_files", {})
    if config:
        lines.append("## Configuration Files\n")
        for path, content in sorted(config.items()):
            lines.append(f"### `{path}`")
            lines.append(f"```\n{content[:500]}\n```\n")

    lines.append(f"---\n*Scanned in {brain['stats'].get('scan_time_s', '?')}s*")

    return "\n".join(lines)


def generate_compact_brain(brain: dict) -> str:
    """
    Generate a compact version of the brain for LLM context injection.
    This is what gets included in the system prompt every turn — it needs to be
    small enough to not waste tokens but rich enough to be useful.
    """
    lines = []
    lines.append(f"PROJECT: {brain.get('project_name', '?')} [{', '.join(brain.get('tech_stack', []))}]")
    lines.append(f"FILES: {brain['stats'].get('total_files', 0)} | CLASSES: {brain['stats'].get('total_classes', 0)} | FUNCS: {brain['stats'].get('total_functions', 0)}")

    entries = brain.get("entry_points", [])
    if entries:
        lines.append(f"ENTRY: {', '.join(entries[:3])}")

    lines.append("")

    # Compact module listing
    for path, module in sorted(brain.get("modules", {}).items()):
        purpose = module.get("purpose", "")
        classes = [c["name"] for c in module.get("classes", [])]
        funcs = [f["name"] for f in module.get("functions", [])]
        parts = []
        if classes:
            parts.append(f"classes=[{','.join(classes[:4])}]")
        if funcs:
            parts.append(f"funcs=[{','.join(funcs[:4])}]")
        detail = " | ".join(parts)
        lines.append(f"  {path}: {purpose[:60]} -> {detail}")

    # Show non-code files compactly
    other_files = brain.get("other_files", {})
    if other_files:
        by_type = {}
        for path, info in other_files.items():
            ftype = info.get("type", "other")
            by_type.setdefault(ftype, []).append(path)
        lines.append("")
        lines.append("OTHER FILES:")
        for ftype, paths in sorted(by_type.items()):
            lines.append(f"  {ftype}: {', '.join(sorted(paths)[:8])}{'...' if len(paths) > 8 else ''}")
    
    # Show empty directories
    dirs_info = brain.get("directories", [])
    empty_dirs = [d["path"] for d in dirs_info if d.get("empty")]
    if empty_dirs:
        lines.append(f"EMPTY DIRS: {', '.join(empty_dirs)}")

    return "\n".join(lines)


# ─── Persistence ──────────────────────────────────────────────────────────────

def save_brain(brain: dict, directory: str = None):
    """Save the brain to disk (both JSON data and markdown document)."""
    if not directory:
        directory = brain.get("project_root", os.getenv("FOLDER_PATH", "."))

    brain_dir = os.path.join(directory, BRAIN_DIR)
    os.makedirs(brain_dir, exist_ok=True)

    # Save JSON (machine-readable)
    json_path = os.path.join(brain_dir, BRAIN_JSON)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(brain, f, indent=2, default=str)
    except Exception:
        pass

    # Save markdown (human-readable)
    md_path = os.path.join(brain_dir, BRAIN_FILE)
    try:
        doc = generate_brain_document(brain)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(doc)
    except Exception:
        pass


def load_brain(directory: str = None) -> dict:
    """Load the saved brain if it exists."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    json_path = os.path.join(directory, BRAIN_DIR, BRAIN_JSON)
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_brain_context(directory: str = None) -> str:
    """
    Get the compact brain content for injection into the LLM's system prompt.
    Returns empty string if no brain exists (user hasn't scanned yet).
    """
    brain = load_brain(directory)
    if brain:
        return generate_compact_brain(brain)
    return ""


# ─── Tool Interface ──────────────────────────────────────────────────────────

def scan_codebase_tool(directory: str = "") -> str:
    """
    Main entry point: Deep scan the codebase and build the brain document.
    Called when the user says "scan the codebase".
    """
    from dotenv import load_dotenv
    load_dotenv()

    if not directory or directory in (".", "./"):
        directory = os.getenv("FOLDER_PATH", ".")

    if not os.path.exists(directory):
        return f"Error: Directory {directory} does not exist."

    console.print("  [bold cyan]🧠 Deep scanning codebase...[/bold cyan]")
    console.print("  [dim]  -> Reading every file, analyzing structure and purpose...[/dim]")

    brain = deep_scan(directory)
    save_brain(brain, directory)

    # Also trigger the vector index for semantic search
    try:
        from core.memory import index_codebase
        console.print("  [dim]  -> Building vector index for semantic search...[/dim]")
        index_codebase(directory)
    except Exception:
        pass

    stats = brain.get("stats", {})
    summary = brain.get("summary", "")

    result_lines = [
        "✅ Deep scan complete! Brain document saved to .kinda_claude/codebase_brain.md",
        "",
        f"📊 {len(brain.get('file_tree', []))} total files | {stats.get('total_files', 0)} code files | {len(brain.get('other_files', {}))} other files",
        f"📂 {len(brain.get('directories', []))} directories ({len([d for d in brain.get('directories', []) if d.get('empty')])} empty)",
        f"⏱️  Scanned in {stats.get('scan_time_s', '?')}s",
        f"🔧 Tech stack: {', '.join(brain.get('tech_stack', []))}",
        f"🚪 Entry points: {', '.join(brain.get('entry_points', [])[:3])}",
        f"📦 Dependencies: {', '.join(brain.get('dependencies', [])[:8])}",
        "",
        f"📝 Summary: {summary}",
        "",
        "The brain is now active — I'll use it automatically on every turn to know",
        "exactly where to find things and where to make changes.",
    ]

    # Module overview
    modules = brain.get("modules", {})
    if modules:
        result_lines.append(f"\n📂 Module breakdown ({len(modules)} modules):")
        for path, module in sorted(modules.items()):
            purpose = module.get("purpose", "")[:60]
            classes = [c["name"] for c in module.get("classes", [])]
            funcs = [f["name"] for f in module.get("functions", [])]

            detail_parts = []
            if classes:
                detail_parts.append(f"{len(classes)} classes")
            if funcs:
                detail_parts.append(f"{len(funcs)} funcs")
            detail = ", ".join(detail_parts) or "config"

            result_lines.append(f"  {path}: {purpose} ({detail})")

    # Show non-code files
    other_files = brain.get("other_files", {})
    if other_files:
        by_type = {}
        for path, info in other_files.items():
            ftype = info.get("type", "other")
            by_type.setdefault(ftype, []).append((path, info))
        
        result_lines.append(f"\n\ud83d\udcc2 Non-code files:")
        for ftype, files_list in sorted(by_type.items()):
            result_lines.append(f"  {ftype.title()} ({len(files_list)}):") 
            for path, info in files_list[:5]:
                result_lines.append(f"    {path} ({info.get('size_human', '?')})")
            if len(files_list) > 5:
                result_lines.append(f"    ...and {len(files_list) - 5} more")

    return "\n".join(result_lines)
