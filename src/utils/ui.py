import sys
import os
import json
import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

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
    """
    try:
        from server.broadcaster import broadcaster
        if not broadcaster.active_connections:
            return
        
        payload = json.dumps({"type": msg_type, "message": message})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(broadcaster.broadcast(payload))
        loop.close()
    except Exception:
        pass

def emit(event_type: str, payload: str, style: str = None, panel: bool = False, title: str = None):
    """
    Unified event emitter.
    Prints to local CLI with Rich, and broadcasts to Dashboard.
    """
    if panel:
        console.print(Panel(payload, title=title, border_style=style or "blue"))
    else:
        if style:
            console.print(f"[{style}]{payload}[/{style}]")
        else:
            console.print(payload)
            
    broadcast_sync(event_type, payload)
