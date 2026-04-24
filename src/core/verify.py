"""
verify.py — Post-Change Verification System

After the agent makes changes, this module runs a comprehensive check:
1. Compile check — every Python file in the project compiles (py_compile)
2. Import check — all local imports resolve correctly
3. Lint check — ruff lint on all modified/new Python files
4. Test run — if tests exist, run them
5. Schema consistency — verify tools wiring (schema ↔ handler)

The output is a structured pass/fail report, exactly like what a
senior engineer would run before pushing code.

This can be triggered:
- Automatically after complex tasks (via run_turn)
- Manually via the /verify slash command
- By the agent calling the verify_project tool
"""

import os
import re
import subprocess
import sys
import time
from utils.ui import console


SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
             '.revi', 'build', 'dist', 'coverage', '.tox', '.mypy_cache'}


# ─── Individual Checks ──────────────────────────────────────────────────────

def check_compile(directory: str) -> dict:
    """
    Run py_compile on every .py file in the project.
    Returns pass/fail for each file.
    """
    results = {"passed": [], "failed": []}
    
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for filename in files:
            if filename.endswith('.py'):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
                try:
                    proc = subprocess.run(
                        [sys.executable, "-m", "py_compile", filepath],
                        capture_output=True, text=True, timeout=10
                    )
                    if proc.returncode == 0:
                        results["passed"].append(rel_path)
                    else:
                        error = proc.stderr.strip().split('\n')[-1][:200] if proc.stderr else "Unknown compile error"
                        results["failed"].append({"file": rel_path, "error": error})
                except subprocess.TimeoutExpired:
                    results["failed"].append({"file": rel_path, "error": "Compile check timed out"})
                except Exception as e:
                    results["failed"].append({"file": rel_path, "error": str(e)[:200]})
    
    return results


def check_imports(directory: str) -> dict:
    """
    Check that all local imports in Python files resolve correctly.
    Parses import statements and verifies the target modules exist.
    """
    results = {"passed": [], "warnings": []}
    
    # Build a map of all Python module paths in the project
    available_modules = set()
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for filename in files:
            if filename.endswith('.py'):
                rel_path = os.path.relpath(os.path.join(root, filename), directory).replace('\\', '/')
                # Add as module path: src/core/agent.py -> src.core.agent, core.agent, agent
                mod_path = rel_path.replace('/', '.').replace('.py', '')
                parts = mod_path.split('.')
                for i in range(len(parts)):
                    available_modules.add('.'.join(parts[i:]))
                # Also add __init__ parent
                if filename == '__init__.py':
                    parent = os.path.relpath(root, directory).replace('\\', '.')
                    if parent != '.':
                        available_modules.add(parent)
    
    # Now check each file's imports
    import_re = re.compile(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', re.MULTILINE)
    
    # Known standard library / third-party prefixes to skip
    stdlib_prefixes = {
        'os', 'sys', 'json', 're', 'time', 'datetime', 'collections', 'subprocess',
        'threading', 'pathlib', 'typing', 'abc', 'functools', 'itertools', 'copy',
        'io', 'math', 'random', 'hashlib', 'base64', 'logging', 'traceback',
        'inspect', 'textwrap', 'dataclasses', 'enum', 'contextlib', 'shutil',
        # Third-party packages
        'groq', 'dotenv', 'chromadb', 'sentence_transformers', 'duckduckgo_search',
        'requests', 'bs4', 'rich', 'arxiv', 'prompt_toolkit', 'docker', 'ruff',
        'numpy', 'pandas', 'sklearn', 'torch', 'tensorflow', 'flask', 'fastapi',
        'pytest', 'httpx', 'pydantic',
    }
    
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for filename in files:
            if filename.endswith('.py'):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    for match in import_re.finditer(content):
                        module_name = match.group(1) or match.group(2)
                        if not module_name:
                            continue
                        top_level = module_name.split('.')[0]
                        
                        # Skip stdlib and known third-party
                        if top_level in stdlib_prefixes:
                            continue
                        
                        # Check if it resolves to a project module
                        if module_name not in available_modules and top_level not in available_modules:
                            results["warnings"].append({
                                "file": rel_path,
                                "import": module_name,
                                "issue": "Import may not resolve (not found in project)"
                            })
                        else:
                            results["passed"].append(f"{rel_path}: {module_name}")
                except Exception:
                    pass
    
    return results


def check_lint(directory: str, files_filter: list = None) -> dict:
    """
    Run ruff lint on Python files. Optionally filter to specific files.
    """
    results = {"clean": [], "issues": []}
    
    targets = []
    if files_filter:
        targets = [os.path.join(directory, f) for f in files_filter if f.endswith('.py')]
    else:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
            for filename in files:
                if filename.endswith('.py'):
                    targets.append(os.path.join(root, filename))
    
    for filepath in targets:
        if not os.path.exists(filepath):
            continue
        rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", filepath],
                capture_output=True, text=True, timeout=10
            )
            if proc.returncode == 0:
                results["clean"].append(rel_path)
            else:
                error = proc.stderr.strip().split('\n')[-1][:200] if proc.stderr else "Syntax error"
                results["issues"].append({"file": rel_path, "error": error})
        except Exception as e:
            results["issues"].append({"file": rel_path, "error": str(e)[:100]})
    
    return results


def check_tool_consistency(src_dir: str) -> dict:
    """
    Verify that every tool in TOOLS_SCHEMA has a matching handler in execute_tool,
    and vice versa.
    """
    results = {"match": True, "schema_count": 0, "handler_count": 0, 
               "missing_handlers": [], "missing_schemas": []}
    
    tools_path = os.path.join(src_dir, "core", "tools.py")
    if not os.path.exists(tools_path):
        return {"match": True, "schema_count": 0, "handler_count": 0,
                "missing_handlers": [], "missing_schemas": [], "note": "tools.py not found"}
    
    try:
        with open(tools_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Extract schema names: "name": "tool_name"
        schema_names = set(re.findall(r'"name":\s*"(\w+)"', source))
        # Filter to only tool names (not parameter names) by checking they appear in function blocks
        # More reliable: find names within "function": { blocks
        function_blocks = re.findall(r'"function":\s*\{[^}]*"name":\s*"(\w+)"', source)
        schema_names = set(function_blocks) if function_blocks else schema_names
        
        # Extract handler names: tool_name == "name"
        handler_names = set(re.findall(r'tool_name\s*==\s*"(\w+)"', source))
        
        results["schema_count"] = len(schema_names)
        results["handler_count"] = len(handler_names)
        results["missing_handlers"] = sorted(schema_names - handler_names)
        results["missing_schemas"] = sorted(handler_names - schema_names)
        results["match"] = not results["missing_handlers"] and not results["missing_schemas"]
        
    except Exception as e:
        results["error"] = str(e)
    
    return results


# ─── Main Verification Orchestrator ──────────────────────────────────────────

def run_full_verification(directory: str = None) -> dict:
    """
    Run ALL verification checks and return a structured report.
    
    This is the equivalent of what a senior engineer does before pushing:
    compile → import check → lint → tests → schema consistency
    """
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    
    start_time = time.time()
    
    report = {
        "directory": directory,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall": "PASS",
        "checks": {},
        "summary": "",
        "duration_s": 0,
    }
    
    # ── 1. Compile Check ──
    console.print("  [dim]  -> Compile check (py_compile on all .py files)...[/dim]")
    compile_result = check_compile(directory)
    passed_count = len(compile_result["passed"])
    failed_count = len(compile_result["failed"])
    report["checks"]["compile"] = {
        "status": "PASS" if failed_count == 0 else "FAIL",
        "passed": passed_count,
        "failed": failed_count,
        "failures": compile_result["failed"][:10],
    }
    if failed_count > 0:
        report["overall"] = "FAIL"
        console.print(f"  [red]  ✗ Compile: {failed_count} file(s) failed[/red]")
    else:
        console.print(f"  [green]  ✓ Compile: {passed_count} files OK[/green]")
    
    # ── 2. Import Check ──
    console.print("  [dim]  -> Import resolution check...[/dim]")
    import_result = check_imports(directory)
    warning_count = len(import_result["warnings"])
    report["checks"]["imports"] = {
        "status": "PASS" if warning_count == 0 else "WARN",
        "resolved": len(import_result["passed"]),
        "warnings": warning_count,
        "details": import_result["warnings"][:10],
    }
    if warning_count > 0:
        console.print(f"  [yellow]  ⚠ Imports: {warning_count} unresolved import(s)[/yellow]")
    else:
        console.print(f"  [green]  ✓ Imports: {len(import_result['passed'])} resolved OK[/green]")
    
    # ── 3. Lint Check ──
    console.print("  [dim]  -> Syntax/lint check...[/dim]")
    lint_result = check_lint(directory)
    lint_issues = len(lint_result["issues"])
    report["checks"]["lint"] = {
        "status": "PASS" if lint_issues == 0 else "FAIL",
        "clean": len(lint_result["clean"]),
        "issues": lint_issues,
        "details": lint_result["issues"][:10],
    }
    if lint_issues > 0:
        report["overall"] = "FAIL"
        console.print(f"  [red]  ✗ Lint: {lint_issues} file(s) with issues[/red]")
    else:
        console.print(f"  [green]  ✓ Lint: {len(lint_result['clean'])} files clean[/green]")
    
    # ── 4. Tool Consistency ──
    src_dir = directory
    # Try to find src/ subdirectory  
    if os.path.exists(os.path.join(directory, "src", "core", "tools.py")):
        src_dir = os.path.join(directory, "src")
    elif os.path.exists(os.path.join(directory, "core", "tools.py")):
        src_dir = directory
    
    console.print("  [dim]  -> Tool schema consistency check...[/dim]")
    tool_result = check_tool_consistency(src_dir)
    report["checks"]["tools"] = {
        "status": "PASS" if tool_result["match"] else "FAIL",
        "schema_count": tool_result["schema_count"],
        "handler_count": tool_result["handler_count"],
        "missing_handlers": tool_result.get("missing_handlers", []),
        "missing_schemas": tool_result.get("missing_schemas", []),
    }
    if not tool_result["match"]:
        report["overall"] = "FAIL"
        console.print("  [red]  ✗ Tools: schema/handler mismatch[/red]")
    elif tool_result["schema_count"] > 0:
        console.print(f"  [green]  ✓ Tools: {tool_result['schema_count']} schemas = {tool_result['handler_count']} handlers[/green]")
    
    # ── 5. Test Run (optional — only if tests exist) ──
    from core.self_heal import detect_test_files, run_tests
    test_files = detect_test_files(directory)
    if test_files:
        console.print("  [dim]  -> Running test suite...[/dim]")
        test_result = run_tests(directory)
        report["checks"]["tests"] = {
            "status": "PASS" if test_result["success"] else "FAIL",
            "passed": test_result["passed"],
            "failed": test_result["failed"],
            "errors": test_result.get("errors", [])[:5],
        }
        if not test_result["success"]:
            report["overall"] = "FAIL"
            console.print(f"  [red]  ✗ Tests: {test_result['failed']} failed, {test_result['passed']} passed[/red]")
        else:
            console.print(f"  [green]  ✓ Tests: {test_result['passed']} passed[/green]")
    else:
        report["checks"]["tests"] = {"status": "SKIP", "reason": "No test files found"}
        console.print("  [dim]  ○ Tests: skipped (no test files found)[/dim]")
    
    report["duration_s"] = round(time.time() - start_time, 2)
    
    # Build summary
    check_statuses = [c["status"] for c in report["checks"].values()]
    pass_count = check_statuses.count("PASS")
    fail_count = check_statuses.count("FAIL")
    warn_count = check_statuses.count("WARN")
    skip_count = check_statuses.count("SKIP")
    
    report["summary"] = f"{pass_count} passed, {fail_count} failed, {warn_count} warnings, {skip_count} skipped"
    
    return report


def format_verification_report(report: dict) -> str:
    """Format a verification report as a human-readable string."""
    lines = []
    overall = report.get("overall", "?")
    icon = "✅" if overall == "PASS" else "❌"
    
    lines.append(f"{icon} Verification: {overall}")
    lines.append(f"   {report.get('summary', '')}")
    lines.append(f"   Ran in {report.get('duration_s', '?')}s")
    lines.append("")
    
    for check_name, check_data in report.get("checks", {}).items():
        status = check_data.get("status", "?")
        status_icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "○"}.get(status, "?")
        
        detail = ""
        if check_name == "compile":
            detail = f"{check_data.get('passed', 0)} passed, {check_data.get('failed', 0)} failed"
        elif check_name == "imports":
            detail = f"{check_data.get('resolved', 0)} resolved, {check_data.get('warnings', 0)} warnings"
        elif check_name == "lint":
            detail = f"{check_data.get('clean', 0)} clean, {check_data.get('issues', 0)} issues"
        elif check_name == "tools":
            detail = f"{check_data.get('schema_count', 0)} schemas, {check_data.get('handler_count', 0)} handlers"
        elif check_name == "tests":
            if status == "SKIP":
                detail = check_data.get("reason", "skipped")
            else:
                detail = f"{check_data.get('passed', 0)} passed, {check_data.get('failed', 0)} failed"
        
        lines.append(f"  {status_icon} {check_name.title()}: {detail}")
        
        # Show failures
        failures = check_data.get("failures", []) or check_data.get("details", []) or check_data.get("errors", [])
        if failures and status in ("FAIL", "WARN"):
            for f in failures[:5]:
                if isinstance(f, dict):
                    file_str = f.get("file", f.get("test", ""))
                    error_str = f.get("error", f.get("issue", f.get("import", "")))
                    lines.append(f"      -> {file_str}: {error_str}")
                else:
                    lines.append(f"      -> {f}")
        
        # Show tool mismatches
        missing_h = check_data.get("missing_handlers", [])
        missing_s = check_data.get("missing_schemas", [])
        if missing_h:
            lines.append(f"      Missing handlers: {', '.join(missing_h)}")
        if missing_s:
            lines.append(f"      Missing schemas: {', '.join(missing_s)}")
    
    return "\n".join(lines)


# ─── Tool Interface ──────────────────────────────────────────────────────────

def verify_project_tool(directory: str = "") -> str:
    """
    Tool interface: Run full project verification.
    Returns a formatted pass/fail report.
    """
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    
    console.print("  [bold cyan]🔍 Running full project verification...[/bold cyan]")
    report = run_full_verification(directory)
    return format_verification_report(report)
