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

def run_revi_agent(instruction: str):
    """Background task to run the agent."""
    import sys
    sys.path.insert(0, 'src')
    from core.agent import run_turn, init_messages
    
    # Send a broadcast that we're starting
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(broadcaster.broadcast(json.dumps({
        "type": "system",
        "message": f"Webhook triggered agent: {instruction}"
    })))
    
    # Run the agent (simulated background run)
    try:
        messages = init_messages(os.getenv("FOLDER_PATH", "."))
        run_turn(messages, instruction, turn_count=1)
    except Exception as e:
        loop.run_until_complete(broadcaster.broadcast(json.dumps({
            "type": "system",
            "message": f"Agent crashed: {e}"
        })))

@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    action = payload.get("action")
    
    if "issue" in payload and action in ["opened", "labeled"]:
        issue = payload["issue"]
        labels = [l["name"] for l in issue.get("labels", [])]
        
        if "revi-fix" in labels:
            instruction = f"Fix GitHub Issue #{issue['number']}: {issue['title']}\n\nDescription:\n{issue['body']}"
            background_tasks.add_task(run_revi_agent, instruction)
            return {"status": "accepted", "message": "REVI agent started to fix issue."}
            
    return {"status": "ignored"}

def start_server():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
