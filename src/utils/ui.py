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
    """
    Thread-safe, crash-proof broadcast to Dashboard WebSockets.
    This function NEVER raises — if the dashboard isn't running, it's a no-op.
    """
    try:
        from server.broadcaster import broadcaster
        if not broadcaster.active_connections:
            return  # No clients connected, skip entirely
        
        payload = json.dumps({"type": msg_type, "message": message})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(broadcaster.broadcast(payload))
        loop.close()
    except Exception:
        pass  # Dashboard not running or import failed — totally fine
