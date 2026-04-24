import sys
import os
from rich.console import Console

# Force UTF-8 output on Windows to prevent cp1252 encoding crashes
# when printing Unicode characters like ✓, ✗, →, etc.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    # Also set the environment variable for subprocesses
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

console = Console(force_terminal=True)
