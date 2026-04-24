import sys
import os
import json
import asyncio
from rich.console import Console

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

console = Console(force_terminal=True)

def broadcast_sync(msg_type: str, message: str):
    """Synchronously broadcast a message to the dashboard WebSockets."""
    try:
        from server.broadcaster import broadcaster
        loop = asyncio.get_event_loop()
    except Exception:
        return
        
    if loop.is_running():
        # Fire and forget
        loop.create_task(broadcaster.broadcast(json.dumps({"type": msg_type, "message": message})))
    else:
        loop.run_until_complete(broadcaster.broadcast(json.dumps({"type": msg_type, "message": message})))
