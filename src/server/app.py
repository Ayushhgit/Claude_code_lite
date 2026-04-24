import os
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from server.broadcaster import broadcaster

app = FastAPI(title="REVI Command Center")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>REVI Command Center</title>
    <script src="https://unpkg.com/force-graph"></script>
    <style>
        body { margin: 0; padding: 0; background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', 'Courier New', monospace; display: flex; height: 100vh; overflow: hidden; }
        #left-panel { flex: 1; border-right: 1px solid #333; display: flex; flex-direction: column; }
        #right-panel { flex: 1; display: flex; flex-direction: column; }
        .header { background: #2d2d2d; padding: 10px; font-weight: bold; border-bottom: 1px solid #333; }
        #log-window { flex: 1; padding: 10px; overflow-y: auto; background: #000; }
        .log-entry { margin-bottom: 5px; }
        .thought { color: #569cd6; }
        .tool { color: #4ec9b0; }
        .system { color: #ce9178; }
        #graph-container { flex: 1; position: relative; }
    </style>
</head>
<body>
    <div id="left-panel">
        <div class="header">⚡ REVI Thought Stream</div>
        <div id="log-window"></div>
    </div>
    <div id="right-panel">
        <div class="header">🕸️ Semantic Code Graph</div>
        <div id="graph-container"></div>
    </div>

    <script>
        // Log Stream
        const ws = new WebSocket("ws://" + window.location.host + "/ws");
        const logWindow = document.getElementById("log-window");
        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            const el = document.createElement("div");
            el.className = "log-entry " + data.type;
            el.innerText = `[${data.type.toUpperCase()}] ${data.message}`;
            logWindow.appendChild(el);
            logWindow.scrollTop = logWindow.scrollHeight;
        };

        // Semantic Graph
        fetch('/api/graph')
            .then(res => res.json())
            .then(data => {
                if (Object.keys(data).length === 0) {
                    document.getElementById('graph-container').innerHTML = "<div style='padding:20px'>Run `/scan` to generate graph.</div>";
                    return;
                }
                const Graph = ForceGraph()(document.getElementById('graph-container'))
                    .graphData(data)
                    .nodeId('id')
                    .nodeLabel('id')
                    .nodeAutoColorBy('type')
                    .linkDirectionalArrowLength(3.5)
                    .linkDirectionalArrowRelPos(1);
            });
    </script>
</body>
</html>
"""

@app.get("/")
async def get():
    return HTMLResponse(HTML_CONTENT)

@app.get("/api/graph")
async def get_graph():
    directory = os.getenv("FOLDER_PATH", ".")
    path = os.path.join(directory, ".revi", "semantic_graph.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return JSONResponse(json.load(f))
    return JSONResponse({})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)

# --- CI/CD Webhook Endpoint ---

def _broadcast_sync(msg_type: str, message: str):
    """Thread-safe broadcast helper for background tasks."""
    import asyncio
    payload = json.dumps({"type": msg_type, "message": message})
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(broadcaster.broadcast(payload))
        loop.close()
    except Exception:
        pass  # Dashboard might not be connected — that's fine

def run_revi_agent(instruction: str, branch_name: str = ""):
    """
    Background task: runs the REVI agent to fix an issue.
    Creates a git branch, runs the agent, commits, and pushes.
    """
    import subprocess
    
    directory = os.getenv("FOLDER_PATH", ".")
    _broadcast_sync("system", f"Agent triggered: {instruction[:120]}...")
    
    # Step 1: Create a branch for the fix (if branch_name provided)
    if branch_name:
        try:
            subprocess.run(["git", "checkout", "-b", branch_name], cwd=directory, capture_output=True, timeout=10)
            _broadcast_sync("system", f"Created branch: {branch_name}")
        except Exception as e:
            _broadcast_sync("system", f"Branch creation warning: {e}")
    
    # Step 2: Run the agent
    try:
        import sys
        if 'src' not in sys.path:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            
        from core.agent import init_messages, run_turn
        
        messages = init_messages(directory)
        result = run_turn(messages, instruction)
        _broadcast_sync("system", f"Agent completed: {str(result)[:200]}")
    except Exception as e:
        _broadcast_sync("system", f"Agent error: {e}")
        return
    
    # Step 3: Commit and push
    if branch_name:
        try:
            subprocess.run(["git", "add", "."], cwd=directory, capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", f"fix: auto-fix from REVI agent\n\n{instruction[:200]}"],
                cwd=directory, capture_output=True, timeout=10
            )
            subprocess.run(["git", "push", "origin", branch_name], cwd=directory, capture_output=True, timeout=30)
            _broadcast_sync("system", f"Pushed fix to branch: {branch_name}")
        except Exception as e:
            _broadcast_sync("system", f"Git push warning: {e}")

@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    GitHub Webhook receiver.
    Triggers:
      - Issue opened/labeled with 'revi-fix' -> spawns agent to fix it.
      - Pull request opened -> spawns agent to review it.
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON payload"}, status_code=400)
    
    action = payload.get("action", "")
    
    # --- Issue Fix Trigger ---
    if "issue" in payload and action in ["opened", "labeled"]:
        issue = payload["issue"]
        labels = [l.get("name", "") for l in issue.get("labels", [])]
        
        if "revi-fix" in labels:
            issue_num = issue.get("number", 0)
            title = issue.get("title", "untitled")
            body = issue.get("body", "") or ""
            branch_name = f"revi/fix-issue-{issue_num}"
            instruction = f"Fix GitHub Issue #{issue_num}: {title}\n\nDescription:\n{body}"
            
            background_tasks.add_task(run_revi_agent, instruction, branch_name)
            return {"status": "accepted", "trigger": "issue", "issue": issue_num, "branch": branch_name}
    
    # --- Pull Request Review Trigger ---
    if "pull_request" in payload and action in ["opened", "synchronize"]:
        pr = payload["pull_request"]
        pr_num = pr.get("number", 0)
        title = pr.get("title", "")
        body = pr.get("body", "") or ""
        diff_url = pr.get("diff_url", "")
        
        instruction = (
            f"Review Pull Request #{pr_num}: {title}\n\n"
            f"Description:\n{body}\n\n"
            f"Diff URL: {diff_url}\n\n"
            f"Please review the code changes, identify bugs, security issues, "
            f"and suggest improvements. Focus on correctness and edge cases."
        )
        background_tasks.add_task(run_revi_agent, instruction)
        return {"status": "accepted", "trigger": "pull_request", "pr": pr_num}
    
    return {"status": "ignored"}

@app.get("/api/status")
async def get_status():
    """Health check endpoint for monitoring."""
    return {
        "status": "running",
        "project": os.getenv("FOLDER_PATH", "."),
        "provider": os.getenv("PROVIDER", "groq"),
        "model": os.getenv("MODEL", "unknown"),
        "connected_clients": len(broadcaster.active_connections)
    }

def start_server():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

