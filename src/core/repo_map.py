"""
repo_map.py — AST-Based Repository Mapping Engine

Generates a compressed, token-efficient "skeleton" of the entire codebase
showing every file's classes, methods, function signatures, and imports
without implementation bodies. Cached with mtime-based invalidation.
"""

import os
import ast
import re
import json
import time

CACHE_DIR = ".revi"
CACHE_FILE = "repo_map.json"

SKIP_DIRS = {
    '.git', '.revi', '__pycache__', 'node_modules', '.venv', 'venv',
    'env', 'build', 'dist', '.next', 'coverage', 'out', '.ruff_cache',
    '.mypy_cache', '.pytest_cache',
}

SUPPORTED_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.go', '.rs', '.rb', '.cpp', '.c', '.h'}


def _parse_python_file(filepath, content):
    result = {"language": "python", "imports": [], "classes": [], "functions": [], "globals": []}
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        result["error"] = "SyntaxError"
        return result

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result["imports"].append(f"{module}.{alias.name}")
        elif isinstance(node, ast.ClassDef):
            result["classes"].append(_parse_class(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append(_parse_function(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    result["globals"].append(target.id)
    return result


def _parse_class(node):
    bases = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
    methods = []
    class_vars = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_parse_function(item))
        elif isinstance(item, ast.Assign):
            for t in item.targets:
                if isinstance(t, ast.Name):
                    class_vars.append(t.id)
    return {
        "name": node.name, "bases": bases, "methods": methods,
        "class_vars": class_vars, "line": node.lineno,
        "docstring": (ast.get_docstring(node) or "")[:100],
    }


def _parse_function(node):
    args = []
    for arg in node.args.args:
        arg_info = arg.arg
        if arg.annotation:
            try:
                arg_info += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        args.append(arg_info)
    return_type = None
    if node.returns:
        try:
            return_type = ast.unparse(node.returns)
        except Exception:
            pass
    decorators = []
    for dec in node.decorator_list:
        try:
            decorators.append(ast.unparse(dec))
        except Exception:
            pass
    return {
        "name": node.name, "args": args, "return_type": return_type,
        "decorators": decorators, "is_async": isinstance(node, ast.AsyncFunctionDef),
        "line": node.lineno, "docstring": (ast.get_docstring(node) or "")[:100],
    }


def _parse_js_ts_file(filepath, content):
    result = {"language": "javascript/typescript", "imports": [], "classes": [], "functions": [], "exports": []}
    import_pat = re.compile(r'''import\s+.*?from\s+['"]([^'"]+)['"]''', re.MULTILINE)
    for m in import_pat.finditer(content):
        result["imports"].append(m.group(1))
    class_pat = re.compile(r'^(?:export\s+)?(?:default\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?', re.MULTILINE)
    for m in class_pat.finditer(content):
        result["classes"].append({"name": m.group(1), "bases": [m.group(2)] if m.group(2) else [], "line": content[:m.start()].count('\n')+1})
    func_pat = re.compile(r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE)
    for m in func_pat.finditer(content):
        result["functions"].append({"name": m.group(1), "args": [a.strip() for a in m.group(2).split(',') if a.strip()], "line": content[:m.start()].count('\n')+1})
    arrow_pat = re.compile(r'^(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(?([^)]*)\)?\s*=>', re.MULTILINE)
    for m in arrow_pat.finditer(content):
        result["functions"].append({"name": m.group(1), "args": [a.strip() for a in m.group(2).split(',') if a.strip()], "line": content[:m.start()].count('\n')+1})
    return result


def parse_file(filepath, content):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.py':
        return _parse_python_file(filepath, content)
    elif ext in ('.js', '.jsx', '.ts', '.tsx'):
        return _parse_js_ts_file(filepath, content)
    return {"language": ext, "functions": [], "classes": []}


def _get_cache_path(base_dir):
    cache_dir = os.path.join(base_dir, CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, CACHE_FILE)


def _load_cache(base_dir):
    cache_path = _get_cache_path(base_dir)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(base_dir, cache):
    try:
        with open(_get_cache_path(base_dir), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
    except OSError:
        pass


def build_repo_map(directory, force_refresh=False):
    start_time = time.time()
    cache = {} if force_refresh else _load_cache(directory)
    cached_files = cache.get("files", {})
    repo_map = {}
    total_classes = total_functions = files_parsed = files_cached = 0

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
            try:
                current_mtime = os.path.getmtime(filepath)
            except OSError:
                continue
            if rel_path in cached_files and cached_files[rel_path].get("_mtime", 0) >= current_mtime:
                repo_map[rel_path] = cached_files[rel_path]
                total_classes += len(cached_files[rel_path].get("classes", []))
                total_functions += len(cached_files[rel_path].get("functions", []))
                files_cached += 1
                continue
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                file_map = parse_file(filepath, content)
                file_map["_mtime"] = current_mtime
                file_map["_lines"] = content.count('\n') + 1
                repo_map[rel_path] = file_map
                total_classes += len(file_map.get("classes", []))
                total_functions += len(file_map.get("functions", []))
                files_parsed += 1
            except Exception:
                repo_map[rel_path] = {"error": "could not parse", "_mtime": current_mtime}

    elapsed = (time.time() - start_time) * 1000
    result = {
        "files": repo_map,
        "stats": {"total_files": len(repo_map), "total_classes": total_classes, "total_functions": total_functions,
                  "files_parsed": files_parsed, "files_cached": files_cached, "scan_time_ms": round(elapsed, 1)}
    }
    _save_cache(directory, result)
    return result


def format_repo_map(repo_map, verbose=False):
    lines = []
    stats = repo_map.get("stats", {})
    lines.append(f"=== Repository Map ({stats.get('total_files',0)} files, {stats.get('total_classes',0)} classes, {stats.get('total_functions',0)} functions) ===\n")

    for filepath, info in sorted(repo_map.get("files", {}).items()):
        if info.get("error"):
            continue
        lang = info.get("language", "?")
        lines.append(f"  {filepath} [{lang}, {info.get('_lines',0)}L]")
        imports = info.get("imports", [])
        if imports:
            lines.append(f"    imports: {', '.join(imports[:5])}{'...' if len(imports)>5 else ''}")
        for cls in info.get("classes", []):
            bases = f"({', '.join(cls.get('bases',[]))})" if cls.get('bases') else ""
            lines.append(f"    class {cls['name']}{bases} @L{cls.get('line','?')}")
            if verbose and cls.get('docstring'):
                lines.append(f"      \"{cls['docstring'][:80]}\"")
            for method in cls.get('methods', []):
                prefix = "async " if method.get('is_async') else ""
                args_str = ', '.join(method.get('args', []))
                ret = f" -> {method['return_type']}" if method.get('return_type') else ""
                lines.append(f"      {prefix}def {method['name']}({args_str}){ret}")
        for func in info.get("functions", []):
            prefix = "async " if func.get('is_async') else ""
            args_str = ', '.join(func.get('args', []))
            ret = f" -> {func.get('return_type','')}" if func.get('return_type') else ""
            lines.append(f"    {prefix}def {func['name']}({args_str}){ret} @L{func.get('line','?')}")
        lines.append("")

    lines.append(f"--- Scan: {stats.get('files_parsed',0)} parsed, {stats.get('files_cached',0)} cached, {stats.get('scan_time_ms',0)}ms ---")
    return "\n".join(lines)


def get_ast_repo_map(directory, verbose=False):
    """Main entry point called by the tool system."""
    from dotenv import load_dotenv
    load_dotenv()
    if not directory or directory in (".", "./"):
        directory = os.getenv("FOLDER_PATH", ".")
    if not os.path.exists(directory):
        return f"Error: Directory {directory} does not exist."
    return format_repo_map(build_repo_map(directory), verbose=verbose)
