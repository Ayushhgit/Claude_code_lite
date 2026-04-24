"""
lsp_navigator.py — LSP-Powered Semantic Code Navigation

Provides IDE-grade code navigation without requiring an external LSP server.
Uses Python's ast module for Python files and regex for JS/TS files.

Tools:
- find_references: Find all usages of a symbol across the codebase
- go_to_definition: Locate where a function/class/variable is defined
- find_implementations: Find subclasses or interface implementations
- get_call_graph: Show what functions call a given function
"""

import os
import ast
import re
from collections import defaultdict


SKIP_DIRS = {
    '.git', '.kinda_claude', '__pycache__', 'node_modules', '.venv', 'venv',
    'env', 'build', 'dist', '.ruff_cache', '.mypy_cache', '.pytest_cache',
}

CODE_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx'}


# ─── File Discovery ──────────────────────────────────────────────────────────

def _walk_code_files(directory):
    """Yield (filepath, extension) for all code files in the project."""
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in CODE_EXTENSIONS:
                yield os.path.join(root, f), ext


# ─── Python AST Analysis ────────────────────────────────────────────────────

def _find_python_definitions(filepath, content, symbol):
    """Find all definitions of a symbol in a Python file."""
    results = []
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
            results.append({
                "type": "function",
                "file": filepath,
                "line": node.lineno,
                "context": f"def {node.name}({', '.join(a.arg for a in node.args.args)})",
            })
        elif isinstance(node, ast.ClassDef) and node.name == symbol:
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            results.append({
                "type": "class",
                "file": filepath,
                "line": node.lineno,
                "context": f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
            })
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol:
                    results.append({
                        "type": "variable",
                        "file": filepath,
                        "line": node.lineno,
                        "context": f"{symbol} = ...",
                    })
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname == symbol or alias.name.split('.')[-1] == symbol:
                        results.append({
                            "type": "import",
                            "file": filepath,
                            "line": node.lineno,
                            "context": f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                        })
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == symbol or alias.asname == symbol:
                        results.append({
                            "type": "import",
                            "file": filepath,
                            "line": node.lineno,
                            "context": f"from {node.module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                        })
    return results


def _find_python_references(filepath, content, symbol):
    """Find all references (usages) of a symbol in a Python file."""
    results = []
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        # Fallback to regex
        return _find_regex_references(filepath, content, symbol)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == symbol:
            results.append({
                "file": filepath,
                "line": node.lineno,
                "col": node.col_offset,
            })
        elif isinstance(node, ast.Attribute) and node.attr == symbol:
            results.append({
                "file": filepath,
                "line": node.lineno,
                "col": node.col_offset,
            })
    return results


def _find_python_implementations(filepath, content, class_name):
    """Find classes that inherit from a given class."""
    results = []
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr

                if base_name == class_name:
                    results.append({
                        "type": "subclass",
                        "file": filepath,
                        "line": node.lineno,
                        "context": f"class {node.name}({class_name})",
                    })
    return results


def _get_python_call_graph(filepath, content, function_name):
    """Find all functions that call a given function."""
    results = []
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Walk this function's body for calls
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = None
                    if isinstance(child.func, ast.Name) and child.func.id == function_name:
                        callee = child.func.id
                    elif isinstance(child.func, ast.Attribute) and child.func.attr == function_name:
                        callee = child.func.attr

                    if callee:
                        results.append({
                            "caller": node.name,
                            "file": filepath,
                            "line": child.lineno,
                            "context": f"{node.name}() calls {function_name}()",
                        })
                        break  # Only record once per function
    return results


# ─── Regex Fallback (JS/TS and broken Python) ───────────────────────────────

def _find_regex_references(filepath, content, symbol):
    """Find references using regex (works for any language)."""
    results = []
    # Match word boundaries to avoid partial matches
    pattern = re.compile(r'\b' + re.escape(symbol) + r'\b')
    for i, line in enumerate(content.split('\n'), 1):
        if pattern.search(line):
            results.append({
                "file": filepath,
                "line": i,
                "content": line.strip()[:120],
            })
    return results


def _find_regex_definitions(filepath, content, symbol):
    """Find definitions using regex patterns for JS/TS."""
    results = []
    patterns = [
        (r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+' + re.escape(symbol), "function"),
        (r'(?:export\s+)?(?:const|let|var)\s+' + re.escape(symbol) + r'\s*=', "variable"),
        (r'(?:export\s+)?(?:default\s+)?class\s+' + re.escape(symbol), "class"),
        (r'(?:export\s+)?interface\s+' + re.escape(symbol), "interface"),
        (r'(?:export\s+)?type\s+' + re.escape(symbol), "type"),
    ]
    for pattern, def_type in patterns:
        for i, line in enumerate(content.split('\n'), 1):
            if re.search(pattern, line):
                results.append({
                    "type": def_type,
                    "file": filepath,
                    "line": i,
                    "context": line.strip()[:120],
                })
    return results


# ─── Public API ──────────────────────────────────────────────────────────────

def find_references(symbol: str, directory: str = None) -> str:
    """Find all references to a symbol across the entire codebase."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    all_refs = []
    for filepath, ext in _walk_code_files(directory):
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        if ext == '.py':
            refs = _find_python_references(filepath, content, symbol)
        else:
            refs = _find_regex_references(filepath, content, symbol)

        for ref in refs:
            ref["file"] = os.path.relpath(ref["file"], directory).replace('\\', '/')
        all_refs.extend(refs)

    if not all_refs:
        return f"No references found for '{symbol}'."

    # Deduplicate by file+line
    seen = set()
    unique_refs = []
    for ref in all_refs:
        key = (ref["file"], ref["line"])
        if key not in seen:
            seen.add(key)
            unique_refs.append(ref)

    lines = [f"Found {len(unique_refs)} reference(s) for '{symbol}':"]
    # Group by file
    by_file = defaultdict(list)
    for ref in unique_refs:
        by_file[ref["file"]].append(ref)

    for filepath, refs in sorted(by_file.items()):
        lines.append(f"\n  {filepath}:")
        for ref in sorted(refs, key=lambda r: r["line"]):
            context = ref.get("content", ref.get("context", ""))
            lines.append(f"    L{ref['line']}: {context}")

    return "\n".join(lines[:100])


def go_to_definition(symbol: str, directory: str = None) -> str:
    """Find where a symbol is defined."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    all_defs = []
    for filepath, ext in _walk_code_files(directory):
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        if ext == '.py':
            defs = _find_python_definitions(filepath, content, symbol)
        else:
            defs = _find_regex_definitions(filepath, content, symbol)

        for d in defs:
            d["file"] = os.path.relpath(d["file"], directory).replace('\\', '/')
        all_defs.extend(defs)

    if not all_defs:
        return f"No definition found for '{symbol}'."

    lines = [f"Found {len(all_defs)} definition(s) for '{symbol}':"]
    for d in all_defs:
        lines.append(f"  [{d.get('type', '?')}] {d['file']}:L{d['line']} → {d.get('context', '')}")

    return "\n".join(lines)


def find_implementations(class_name: str, directory: str = None) -> str:
    """Find all subclasses/implementations of a class."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    all_impls = []
    for filepath, ext in _walk_code_files(directory):
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        if ext == '.py':
            impls = _find_python_implementations(filepath, content, class_name)
        else:
            # JS/TS: search for "extends ClassName"
            pattern = re.compile(r'class\s+(\w+)\s+extends\s+' + re.escape(class_name))
            impls = []
            for i, line in enumerate(content.split('\n'), 1):
                match = pattern.search(line)
                if match:
                    impls.append({
                        "type": "subclass",
                        "file": filepath,
                        "line": i,
                        "context": f"class {match.group(1)} extends {class_name}",
                    })

        for impl in impls:
            impl["file"] = os.path.relpath(impl["file"], directory).replace('\\', '/')
        all_impls.extend(impls)

    if not all_impls:
        return f"No implementations/subclasses found for '{class_name}'."

    lines = [f"Found {len(all_impls)} implementation(s) of '{class_name}':"]
    for impl in all_impls:
        lines.append(f"  {impl['file']}:L{impl['line']} → {impl.get('context', '')}")

    return "\n".join(lines)


def get_call_graph(function_name: str, directory: str = None) -> str:
    """Find all functions that call a given function."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    all_callers = []
    for filepath, ext in _walk_code_files(directory):
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        if ext == '.py':
            callers = _get_python_call_graph(filepath, content, function_name)
        else:
            # Regex fallback for JS/TS
            callers = []
            pattern = re.compile(r'\b' + re.escape(function_name) + r'\s*\(')
            for i, line in enumerate(content.split('\n'), 1):
                if pattern.search(line):
                    callers.append({
                        "file": filepath, "line": i,
                        "context": line.strip()[:120],
                    })

        for c in callers:
            c["file"] = os.path.relpath(c["file"], directory).replace('\\', '/')
        all_callers.extend(callers)

    if not all_callers:
        return f"No callers found for '{function_name}'."

    lines = [f"Found {len(all_callers)} caller(s) of '{function_name}()':"]
    for c in all_callers:
        ctx = c.get("context", f"{c.get('caller', '?')}() calls {function_name}()")
        lines.append(f"  {c['file']}:L{c['line']} → {ctx}")

    return "\n".join(lines)
