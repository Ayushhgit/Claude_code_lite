"""
self_heal.py — Self-Healing Execution Loop

After every code edit or command execution, this module:
1. Runs the linter (ruff) on modified Python files
2. Detects test files and runs them
3. If errors are found, packages them into a structured error report
4. Feeds the error back to the agent for automatic fix (up to max retries)
5. Tracks fix history to prevent infinite repair loops

This is the system that makes the agent self-correcting — it never
hands back broken code without trying to fix it first.
"""

import os
import re
import subprocess
import json
import time
from collections import defaultdict
from utils.ui import console


# ─── Configuration ───────────────────────────────────────────────────────────

MAX_HEAL_RETRIES = 3
LINT_TIMEOUT = 30
TEST_TIMEOUT = 120


# ─── Fix History Tracker ─────────────────────────────────────────────────────

class HealTracker:
    """Tracks fix attempts to prevent infinite loops."""

    def __init__(self):
        self._attempts = defaultdict(int)  # file:error_hash -> count
        self._history = []

    def record_attempt(self, filepath: str, error_signature: str):
        key = f"{filepath}:{error_signature[:100]}"
        self._attempts[key] += 1
        self._history.append({
            "file": filepath,
            "error": error_signature[:200],
            "timestamp": time.time(),
            "attempt": self._attempts[key],
        })

    def should_retry(self, filepath: str, error_signature: str) -> bool:
        key = f"{filepath}:{error_signature[:100]}"
        return self._attempts[key] < MAX_HEAL_RETRIES

    def get_attempt_count(self, filepath: str, error_signature: str) -> int:
        key = f"{filepath}:{error_signature[:100]}"
        return self._attempts[key]

    def reset(self):
        self._attempts.clear()
        self._history.clear()

    def get_summary(self) -> str:
        if not self._history:
            return "No healing attempts recorded."
        lines = ["Self-Heal History:"]
        for entry in self._history[-10:]:
            lines.append(f"  [{entry['attempt']}/{MAX_HEAL_RETRIES}] {entry['file']}: {entry['error'][:80]}")
        return "\n".join(lines)


# Global tracker instance
heal_tracker = HealTracker()


# ─── Linter Integration ─────────────────────────────────────────────────────

def run_linter(filepath: str, cwd: str = None) -> dict:
    """
    Run ruff linter on a Python file.

    Returns:
        dict: {
            "success": bool,
            "errors": [{"line": int, "code": str, "message": str}],
            "raw_output": str
        }
    """
    if not filepath.endswith('.py'):
        return {"success": True, "errors": [], "raw_output": "Skipped: not a Python file"}

    if not cwd:
        cwd = os.getenv("FOLDER_PATH", ".")

    # Make filepath absolute if relative
    if not os.path.isabs(filepath):
        filepath = os.path.join(cwd, filepath)

    if not os.path.exists(filepath):
        return {"success": True, "errors": [], "raw_output": "File not found, skipping lint"}

    try:
        # Try ruff first (fast), fall back to py_compile (always available)
        result = subprocess.run(
            ["ruff", "check", filepath, "--output-format", "json"],
            capture_output=True, text=True, timeout=LINT_TIMEOUT, cwd=cwd
        )
        raw_output = result.stdout + result.stderr

        errors = []
        if result.returncode != 0:
            try:
                lint_results = json.loads(result.stdout)
                for item in lint_results:
                    errors.append({
                        "line": item.get("location", {}).get("row", 0),
                        "code": item.get("code", ""),
                        "message": item.get("message", ""),
                        "fix_available": item.get("fix") is not None,
                    })
            except json.JSONDecodeError:
                # Parse text output as fallback
                for line in raw_output.split('\n'):
                    match = re.match(r'.*:(\d+):\d+:\s+(\w+)\s+(.*)', line)
                    if match:
                        errors.append({
                            "line": int(match.group(1)),
                            "code": match.group(2),
                            "message": match.group(3),
                        })

        return {"success": len(errors) == 0, "errors": errors, "raw_output": raw_output[:2000]}

    except FileNotFoundError:
        # ruff not installed, fall back to basic syntax check
        return _syntax_check(filepath)
    except subprocess.TimeoutExpired:
        return {"success": True, "errors": [], "raw_output": "Lint timed out, skipping"}
    except Exception as e:
        return {"success": True, "errors": [], "raw_output": f"Lint error: {e}"}


def _syntax_check(filepath: str) -> dict:
    """Basic Python syntax check using py_compile (always available)."""
    try:
        result = subprocess.run(
            ["python", "-m", "py_compile", filepath],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {
                "success": False,
                "errors": [{"line": 0, "code": "SyntaxError", "message": result.stderr.strip()[:300]}],
                "raw_output": result.stderr[:500]
            }
        return {"success": True, "errors": [], "raw_output": "Syntax OK"}
    except Exception as e:
        return {"success": True, "errors": [], "raw_output": f"Syntax check failed: {e}"}


# ─── Test Runner ─────────────────────────────────────────────────────────────

def detect_test_files(directory: str) -> list:
    """Find all test files in the project."""
    test_files = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}]
        for f in files:
            if f.startswith('test_') and f.endswith('.py'):
                test_files.append(os.path.join(root, f))
            elif f.endswith('_test.py'):
                test_files.append(os.path.join(root, f))
    return test_files


def run_tests(directory: str = None, test_command: str = None) -> dict:
    """
    Run the project's test suite.

    Args:
        directory: Project root
        test_command: Optional custom test command

    Returns:
        dict: {
            "success": bool,
            "passed": int,
            "failed": int,
            "errors": [{"test": str, "error": str}],
            "raw_output": str
        }
    """
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    # Determine test command
    if not test_command:
        # Auto-detect test framework
        if os.path.exists(os.path.join(directory, "pytest.ini")) or \
           os.path.exists(os.path.join(directory, "setup.cfg")) or \
           os.path.exists(os.path.join(directory, "pyproject.toml")):
            test_command = "python -m pytest --tb=short -q"
        elif detect_test_files(directory):
            test_command = "python -m pytest --tb=short -q"
        elif os.path.exists(os.path.join(directory, "package.json")):
            test_command = "npm test"
        else:
            return {"success": True, "passed": 0, "failed": 0, "errors": [], "raw_output": "No test framework detected"}

    try:
        result = subprocess.run(
            test_command, shell=True, cwd=directory,
            capture_output=True, text=True, timeout=TEST_TIMEOUT
        )
        raw_output = result.stdout + result.stderr

        # Parse test results
        passed = failed = 0
        errors = []

        # pytest format
        pytest_match = re.search(r'(\d+) passed', raw_output)
        if pytest_match:
            passed = int(pytest_match.group(1))
        pytest_fail = re.search(r'(\d+) failed', raw_output)
        if pytest_fail:
            failed = int(pytest_fail.group(1))

        # Extract failure details
        if failed > 0:
            fail_blocks = re.findall(r'FAILED\s+(\S+)(?:\s*-\s*(.+))?', raw_output)
            for test_name, error_msg in fail_blocks:
                errors.append({"test": test_name, "error": error_msg or "See full output"})

        success = result.returncode == 0
        return {
            "success": success, "passed": passed, "failed": failed,
            "errors": errors, "raw_output": raw_output[:3000]
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "passed": 0, "failed": 0, "errors": [{"test": "timeout", "error": f"Tests timed out after {TEST_TIMEOUT}s"}], "raw_output": "Timeout"}
    except Exception as e:
        return {"success": True, "passed": 0, "failed": 0, "errors": [], "raw_output": f"Test runner error: {e}"}


# ─── Self-Healing Orchestrator ───────────────────────────────────────────────

def check_and_heal(filepath: str, cwd: str = None) -> dict:
    """
    Run lint + syntax checks on a file after it was edited.
    Returns a structured report for the agent to act on.

    This is called automatically after every edit_file / replace_in_file operation.
    """
    if not cwd:
        cwd = os.getenv("FOLDER_PATH", ".")

    report = {
        "filepath": filepath,
        "lint": None,
        "needs_fix": False,
        "error_report": "",
    }

    # Only lint Python files for now
    if not filepath.endswith('.py'):
        return report

    lint_result = run_linter(filepath, cwd)
    report["lint"] = lint_result

    if not lint_result["success"] and lint_result["errors"]:
        error_sig = str(lint_result["errors"][0].get("message", ""))

        if heal_tracker.should_retry(filepath, error_sig):
            heal_tracker.record_attempt(filepath, error_sig)
            attempt = heal_tracker.get_attempt_count(filepath, error_sig)
            report["needs_fix"] = True

            error_lines = []
            for err in lint_result["errors"][:10]:
                error_lines.append(f"  Line {err.get('line', '?')}: [{err.get('code', '?')}] {err.get('message', '')}")

            report["error_report"] = (
                f"[Self-Heal] Lint errors detected in {os.path.basename(filepath)} "
                f"(attempt {attempt}/{MAX_HEAL_RETRIES}):\n"
                + "\n".join(error_lines)
                + "\n\nPlease fix these issues. Read the file first, then use replace_in_file to correct the problems."
            )

            console.print(f"  [bold yellow]🔧 Self-Heal: {len(lint_result['errors'])} lint error(s) in {os.path.basename(filepath)} (attempt {attempt}/{MAX_HEAL_RETRIES})[/bold yellow]")
        else:
            console.print(f"  [bold red]⚠ Self-Heal: Max retries reached for {os.path.basename(filepath)}, skipping auto-fix[/bold red]")

    return report


def analyze_command_output(output: str) -> dict:
    """
    Analyze the output of a shell command for errors.

    Returns:
        dict: {
            "has_errors": bool,
            "error_type": str,
            "error_summary": str,
            "suggested_action": str
        }
    """
    output_lower = output.lower()

    error_patterns = {
        "traceback": {"type": "RuntimeError", "action": "Read the traceback, identify the failing file and line, fix the code"},
        "syntaxerror": {"type": "SyntaxError", "action": "Fix the syntax error in the file mentioned in the traceback"},
        "modulenotfounderror": {"type": "ImportError", "action": "Install the missing module with pip/npm or fix the import path"},
        "importerror": {"type": "ImportError", "action": "Fix the import statement or install the missing package"},
        "nameerror": {"type": "NameError", "action": "Define the missing variable or fix the typo"},
        "typeerror": {"type": "TypeError", "action": "Fix the type mismatch in the function call"},
        "filenotfounderror": {"type": "FileNotFoundError", "action": "Create the missing file or fix the path"},
        "permission denied": {"type": "PermissionError", "action": "Check file permissions or run with elevated privileges"},
        "command not found": {"type": "CommandNotFound", "action": "Install the missing tool or check the PATH"},
        "exit code 1": {"type": "NonZeroExit", "action": "Review the error output above and fix the issue"},
    }

    for pattern, info in error_patterns.items():
        if pattern in output_lower:
            # Extract the most relevant error line
            lines = output.strip().split('\n')
            error_line = ""
            for line in reversed(lines):
                if any(sig in line.lower() for sig in ['error', 'exception', 'failed']):
                    error_line = line.strip()[:200]
                    break

            return {
                "has_errors": True,
                "error_type": info["type"],
                "error_summary": error_line or f"Detected {info['type']}",
                "suggested_action": info["action"],
            }

    return {"has_errors": False, "error_type": None, "error_summary": "", "suggested_action": ""}


# ─── Tool Interfaces ─────────────────────────────────────────────────────────

def lint_check_tool(filepath: str) -> str:
    """Tool interface for running lint on a specific file."""
    cwd = os.getenv("FOLDER_PATH", ".")
    result = run_linter(filepath, cwd)
    if result["success"]:
        return f"✓ {filepath}: No lint errors found."
    else:
        lines = [f"✗ {filepath}: {len(result['errors'])} lint error(s):"]
        for err in result["errors"][:15]:
            lines.append(f"  Line {err.get('line', '?')}: [{err.get('code', '?')}] {err.get('message', '')}")
        return "\n".join(lines)


def run_tests_tool(test_command: str = None) -> str:
    """Tool interface for running the project's test suite."""
    cwd = os.getenv("FOLDER_PATH", ".")
    result = run_tests(cwd, test_command)
    if result["success"]:
        return f"✓ Tests passed: {result['passed']} passed, {result['failed']} failed."
    else:
        lines = [f"✗ Tests failed: {result['passed']} passed, {result['failed']} failed."]
        for err in result["errors"][:10]:
            lines.append(f"  FAILED: {err['test']}: {err.get('error', '')}")
        lines.append(f"\nFull output:\n{result['raw_output'][:2000]}")
        return "\n".join(lines)
