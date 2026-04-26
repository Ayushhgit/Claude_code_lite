import os
import json
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
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>REVI — Command Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=JetBrains+Mono:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/force-graph"></script>
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        :root {
            --bg:         #0a0a0f;
            --surface:    #0d1117;
            --surface-2:  #161b22;
            --surface-3:  #1c2128;
            --border:     #21262d;
            --blue:       #3b82f6;
            --blue-dim:   rgba(59,130,246,0.10);
            --cyan:       #06b6d4;
            --cyan-dim:   rgba(6,182,212,0.10);
            --amber:      #f59e0b;
            --amber-dim:  rgba(245,158,11,0.10);
            --green:      #10b981;
            --green-dim:  rgba(16,185,129,0.10);
            --red:        #ef4444;
            --purple:     #a855f7;
            --text-1:     #e6edf3;
            --text-2:     #8b949e;
            --text-3:     #484f58;
            --font-ui:    'Geist', system-ui, -apple-system, sans-serif;
            --font-mono:  'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
        }

        html, body { height: 100%; overflow: hidden; background: var(--bg); color: var(--text-1); font-family: var(--font-ui); font-size: 13px; -webkit-font-smoothing: antialiased; }

        #app { display: flex; flex-direction: column; height: 100vh; }

        /* ── Statusbar ── */
        #statusbar {
            height: 44px; min-height: 44px;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            display: flex; align-items: center; padding: 0 16px; gap: 0;
            position: relative; z-index: 10;
        }
        #statusbar::after {
            content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
            background: linear-gradient(90deg, transparent 0%, var(--blue) 50%, transparent 100%);
            opacity: 0; transition: opacity 0.6s;
        }
        #statusbar.live::after { opacity: 0.5; }

        .sb-logo {
            display: flex; align-items: center; gap: 8px;
            font-weight: 600; font-size: 13px; letter-spacing: 0.1em;
            color: var(--text-1); text-transform: uppercase;
            flex-shrink: 0; min-width: 110px;
        }
        .sb-logo-mark {
            width: 22px; height: 22px; border-radius: 5px;
            background: var(--blue); display: flex; align-items: center; justify-content: center;
            font-size: 11px; font-weight: 700; color: #fff; letter-spacing: 0;
        }

        .sb-center {
            flex: 1; display: flex; align-items: center; justify-content: center; gap: 18px;
        }
        .sb-chip {
            display: flex; align-items: center; gap: 5px;
        }
        .sb-chip-label {
            font-size: 10px; font-weight: 500; color: var(--text-3);
            text-transform: uppercase; letter-spacing: 0.07em;
        }
        .sb-chip-value {
            font-family: var(--font-mono); font-size: 11px; color: var(--text-2);
        }
        .sb-divider { color: var(--border); font-size: 14px; }

        .sb-right {
            display: flex; align-items: center; gap: 14px;
            flex-shrink: 0; min-width: 150px; justify-content: flex-end;
        }
        .ws-pill {
            display: flex; align-items: center; gap: 6px;
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 20px; padding: 3px 10px;
            font-size: 11px; color: var(--text-2);
        }
        .ws-dot {
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--text-3); transition: background 0.3s, box-shadow 0.3s;
        }
        .ws-dot.live { background: var(--green); box-shadow: 0 0 7px var(--green); animation: blink 2s ease-in-out infinite; }
        .ws-dot.err  { background: var(--red);   box-shadow: 0 0 7px var(--red); }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }

        .sb-clients { font-family: var(--font-mono); font-size: 11px; color: var(--text-3); }

        /* ── Panels ── */
        #main { display: flex; flex: 1; overflow: hidden; }

        .panel { display: flex; flex-direction: column; flex: 1; overflow: hidden; }
        .panel + .panel { border-left: 1px solid var(--border); }

        .panel-header {
            height: 36px; min-height: 36px;
            background: var(--surface); border-bottom: 1px solid var(--border);
            display: flex; align-items: center; padding: 0 12px; gap: 7px;
        }
        .ph-dot { width: 5px; height: 5px; border-radius: 50%; }
        .ph-title {
            font-size: 10.5px; font-weight: 500; color: var(--text-2);
            text-transform: uppercase; letter-spacing: 0.09em;
        }
        .ph-badge {
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 10px; padding: 1px 7px;
            font-size: 10px; font-family: var(--font-mono); color: var(--text-3);
            transition: color .3s, border-color .3s;
        }
        .ph-badge.hot { color: var(--blue); border-color: rgba(59,130,246,.3); }
        .ph-actions { margin-left: auto; display: flex; gap: 4px; }
        .ph-btn {
            width: 22px; height: 22px; border-radius: 4px;
            background: transparent; border: 1px solid var(--border);
            color: var(--text-2); font-size: 12px; cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: all .15s;
        }
        .ph-btn:hover { background: var(--surface-2); border-color: var(--text-3); color: var(--text-1); }
        .ph-btn.on { background: var(--green-dim); border-color: rgba(16,185,129,.3); color: var(--green); }

        /* ── Log Stream ── */
        #log-window {
            flex: 1; overflow-y: auto; background: var(--bg); padding: 6px 0;
        }
        #log-window::-webkit-scrollbar { width: 3px; }
        #log-window::-webkit-scrollbar-track { background: transparent; }
        #log-window::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

        .log-entry {
            display: flex; align-items: baseline; gap: 9px;
            padding: 2px 14px; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.65;
            border-left: 2px solid transparent;
            animation: slidein .12s ease-out forwards; opacity: 0; transform: translateX(-3px);
        }
        @keyframes slidein { to { opacity:1; transform:none; } }
        .log-entry:hover { background: var(--surface); }

        .log-entry.thought { border-left-color: var(--blue); }
        .log-entry.tool    { border-left-color: var(--cyan); }
        .log-entry.system  { border-left-color: var(--amber); }
        .log-entry.success { border-left-color: var(--green); }
        .log-entry.error   { border-left-color: var(--red); }

        .log-ts {
            color: var(--text-3); font-size: 10px; white-space: nowrap;
            flex-shrink: 0; width: 56px; font-variant-numeric: tabular-nums;
        }
        .log-badge {
            font-size: 9.5px; font-weight: 500; letter-spacing: .05em;
            padding: 1px 5px; border-radius: 3px; flex-shrink: 0;
            text-transform: uppercase; width: 54px; text-align: center;
        }
        .log-badge.thought { background: var(--blue-dim);  color: var(--blue);  border: 1px solid rgba(59,130,246,.18); }
        .log-badge.tool    { background: var(--cyan-dim);  color: var(--cyan);  border: 1px solid rgba(6,182,212,.18); }
        .log-badge.system  { background: var(--amber-dim); color: var(--amber); border: 1px solid rgba(245,158,11,.18); }
        .log-badge.success { background: var(--green-dim); color: var(--green); border: 1px solid rgba(16,185,129,.18); }
        .log-badge.error   { background: rgba(239,68,68,.1); color: var(--red); border: 1px solid rgba(239,68,68,.18); }

        .log-msg { color: var(--text-2); word-break: break-word; white-space: pre-wrap; flex: 1; }
        .log-entry.thought .log-msg { color: #93c5fd; }
        .log-entry.tool    .log-msg { color: #67e8f9; }
        .log-entry.system  .log-msg { color: #fcd34d; }
        .log-entry.success .log-msg { color: #6ee7b7; }
        .log-entry.error   .log-msg { color: #fca5a5; }

        .log-placeholder {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            height: 100%; gap: 10px; color: var(--text-3); font-family: var(--font-mono); font-size: 12px;
        }
        .log-placeholder-icon { font-size: 26px; opacity: .3; }

        /* ── Graph Panel ── */
        #graph-container {
            flex: 1; position: relative; overflow: hidden; background: var(--bg);
        }

        .graph-empty-state {
            position: absolute; inset: 0; display: flex; flex-direction: column;
            align-items: center; justify-content: center; gap: 12px; color: var(--text-3);
        }
        .ges-icon  { font-size: 34px; opacity: .25; }
        .ges-title { font-size: 13px; font-weight: 500; color: var(--text-2); }
        .ges-cmd   {
            font-family: var(--font-mono); font-size: 12px;
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 4px; padding: 4px 11px; color: var(--cyan);
        }

        #graph-legend {
            position: absolute; bottom: 14px; left: 14px;
            background: rgba(13,17,23,.9); backdrop-filter: blur(8px);
            border: 1px solid var(--border); border-radius: 8px;
            padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
            z-index: 5; pointer-events: none;
        }
        .lg-title { font-size: 9px; font-weight: 500; color: var(--text-3); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 2px; }
        .lg-row   { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--text-2); font-family: var(--font-mono); }
        .lg-dot   { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

        #node-tooltip {
            position: absolute; background: rgba(13,17,23,.96); backdrop-filter: blur(8px);
            border: 1px solid var(--border); border-radius: 6px;
            padding: 6px 10px; font-size: 11px; font-family: var(--font-mono);
            color: var(--text-1); pointer-events: none; z-index: 20;
            display: none; max-width: 240px; word-break: break-all;
        }
        .tt-kind { font-size: 9.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 2px; }
    </style>
</head>
<body>
<div id="app">

    <div id="statusbar">
        <div class="sb-logo">
            <div class="sb-logo-mark">R</div>
            REVI
        </div>
        <div class="sb-center">
            <div class="sb-chip">
                <span class="sb-chip-label">project</span>
                <span class="sb-chip-value" id="sb-project">—</span>
            </div>
            <span class="sb-divider">·</span>
            <div class="sb-chip">
                <span class="sb-chip-label">model</span>
                <span class="sb-chip-value" id="sb-model">—</span>
            </div>
            <span class="sb-divider">·</span>
            <div class="sb-chip">
                <span class="sb-chip-label">via</span>
                <span class="sb-chip-value" id="sb-provider">—</span>
            </div>
            <span class="sb-divider">·</span>
            <div class="sb-chip" title="Session prompt tokens sent to LLM">
                <span class="sb-chip-label">↑ in</span>
                <span class="sb-chip-value" id="sb-tok-in" style="color:var(--cyan)">0</span>
            </div>
            <span class="sb-divider">·</span>
            <div class="sb-chip" title="Session completion tokens received from LLM">
                <span class="sb-chip-label">↓ out</span>
                <span class="sb-chip-value" id="sb-tok-out" style="color:var(--green)">0</span>
            </div>
            <span class="sb-divider">·</span>
            <div class="sb-chip" title="KV cache hits (saved tokens)">
                <span class="sb-chip-label">⚡ cache</span>
                <span class="sb-chip-value" id="sb-cache" style="color:var(--amber)">0</span>
            </div>
        </div>
        <div class="sb-right">
            <div class="ws-pill">
                <div class="ws-dot" id="ws-dot"></div>
                <span id="ws-label">connecting</span>
            </div>
            <span class="sb-clients"><span id="sb-clients">0</span> clients</span>
        </div>
    </div>

    <div id="main">

        <!-- Thought Stream -->
        <div class="panel">
            <div class="panel-header">
                <div class="ph-dot" style="background:var(--blue)"></div>
                <span class="ph-title">Thought Stream</span>
                <span class="ph-badge" id="log-count">0</span>
                <div class="ph-actions">
                    <button class="ph-btn" id="clear-btn" title="Clear">✕</button>
                    <button class="ph-btn on" id="scroll-btn" title="Auto-scroll">↓</button>
                </div>
            </div>
            <div id="log-window">
                <div class="log-placeholder" id="log-placeholder">
                    <div class="log-placeholder-icon">◎</div>
                    <span>Waiting for REVI…</span>
                </div>
            </div>
        </div>

        <!-- Semantic Graph -->
        <div class="panel">
            <div class="panel-header">
                <div class="ph-dot" style="background:var(--cyan)"></div>
                <span class="ph-title">Semantic Graph</span>
                <span class="ph-badge" id="node-count"></span>
                <div class="ph-actions">
                    <button class="ph-btn" id="graph-refresh" title="Refresh">↺</button>
                </div>
            </div>
            <div id="graph-container">
                <div class="graph-empty-state" id="graph-empty">
                    <div class="ges-icon">⬡</div>
                    <div class="ges-title">No semantic graph yet</div>
                    <div class="ges-cmd">/scan</div>
                </div>
            </div>
            <div id="graph-legend">
                <div class="lg-title">Nodes</div>
                <div class="lg-row"><div class="lg-dot" style="background:#3b82f6"></div>File</div>
                <div class="lg-row"><div class="lg-dot" style="background:#a855f7"></div>Class</div>
                <div class="lg-row"><div class="lg-dot" style="background:#06b6d4"></div>Function</div>
                <div class="lg-row"><div class="lg-dot" style="background:#8b949e"></div>Other</div>
            </div>
            <div id="node-tooltip">
                <div class="tt-kind" id="tt-kind"></div>
                <div id="tt-name"></div>
            </div>
        </div>

    </div>
</div>

<script>
(function () {
    // ── helpers ──────────────────────────────────────────────────────────
    function ts() {
        const d = new Date();
        return [d.getHours(), d.getMinutes(), d.getSeconds()]
            .map(n => String(n).padStart(2, '0')).join(':');
    }
    function esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── log stream ───────────────────────────────────────────────────────
    const logWin      = document.getElementById('log-window');
    const placeholder = document.getElementById('log-placeholder');
    const logCountEl  = document.getElementById('log-count');
    const scrollBtn   = document.getElementById('scroll-btn');
    const clearBtn    = document.getElementById('clear-btn');
    let count = 0, autoScroll = true;

    scrollBtn.addEventListener('click', () => {
        autoScroll = !autoScroll;
        scrollBtn.classList.toggle('on', autoScroll);
        scrollBtn.textContent = autoScroll ? '↓' : '⏸';
    });
    clearBtn.addEventListener('click', () => {
        logWin.innerHTML = '';
        logWin.appendChild(placeholder);
        placeholder.style.display = 'flex';
        count = 0;
        logCountEl.textContent = '0';
        logCountEl.classList.remove('hot');
    });

    function addEntry(type, message) {
        if (placeholder.style.display !== 'none') placeholder.style.display = 'none';
        const row = document.createElement('div');
        row.className = 'log-entry ' + (type || 'system');
        row.innerHTML =
            '<span class="log-ts">' + ts() + '</span>' +
            '<span class="log-badge ' + esc(type) + '">' + esc(type) + '</span>' +
            '<span class="log-msg">' + esc(message) + '</span>';
        logWin.appendChild(row);
        count++;
        logCountEl.textContent = count;
        logCountEl.classList.add('hot');
        if (autoScroll) logWin.scrollTop = logWin.scrollHeight;
    }

    // ── token budget chips ────────────────────────────────────────────────
    const sbTokIn  = document.getElementById('sb-tok-in');
    const sbTokOut = document.getElementById('sb-tok-out');
    const sbCache  = document.getElementById('sb-cache');

    function fmtK(n) { return n >= 1000 ? (n/1000).toFixed(1)+'k' : String(n); }

    function updateTokenChips(msg) {
        // msg format: "in=1234 out=456 calls=7 cache=89"
        const kv = {};
        msg.split(' ').forEach(p => { const [k,v] = p.split('='); kv[k]=parseInt(v)||0; });
        if (sbTokIn)  sbTokIn.textContent  = fmtK(kv.in  || 0);
        if (sbTokOut) sbTokOut.textContent = fmtK(kv.out  || 0);
        if (sbCache)  sbCache.textContent  = fmtK(kv.cache || 0);
    }

    // Fetch initial token stats from API
    function fetchTokens() {
        fetch('/api/tokens').then(r => r.json()).then(d => {
            if (sbTokIn)  sbTokIn.textContent  = fmtK(d.prompt_tokens || 0);
            if (sbTokOut) sbTokOut.textContent = fmtK(d.completion_tokens || 0);
            if (sbCache)  sbCache.textContent  = fmtK(d.cache_read_tokens || 0);
        }).catch(() => {});
    }
    fetchTokens();

    // ── websocket ────────────────────────────────────────────────────────
    const wsDot    = document.getElementById('ws-dot');
    const wsLabel  = document.getElementById('ws-label');
    const statusbar = document.getElementById('statusbar');

    function setWs(state) {
        wsDot.className = 'ws-dot ' + state;
        wsLabel.textContent = {live:'live', err:'error'}[state] || 'connecting';
        statusbar.classList.toggle('live', state === 'live');
    }

    function connectWs() {
        const ws = new WebSocket('ws://' + window.location.host + '/ws');
        ws.onopen    = () => setWs('live');
        ws.onclose   = () => { setWs('err'); setTimeout(connectWs, 3000); };
        ws.onerror   = () => setWs('err');
        ws.onmessage = (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.type === 'tokens') {
                    updateTokenChips(d.message);
                } else {
                    addEntry(d.type, d.message);
                }
            } catch (_) {}
        };
    }
    connectWs();

    // ── status polling ───────────────────────────────────────────────────
    const sbProject  = document.getElementById('sb-project');
    const sbModel    = document.getElementById('sb-model');
    const sbProvider = document.getElementById('sb-provider');
    const sbClients  = document.getElementById('sb-clients');

    function fetchStatus() {
        fetch('/api/status').then(r => r.json()).then(d => {
            const p = d.project || '—';
            sbProject.textContent  = p.length > 30 ? '…' + p.slice(-28) : p;
            sbModel.textContent    = d.model    || '—';
            sbProvider.textContent = d.provider || '—';
            sbClients.textContent  = d.connected_clients ?? 0;
        }).catch(() => {});
    }
    fetchStatus();
    setInterval(fetchStatus, 5000);

    // ── semantic graph ───────────────────────────────────────────────────
    const graphCont  = document.getElementById('graph-container');
    const graphEmpty = document.getElementById('graph-empty');
    const nodeCountEl = document.getElementById('node-count');
    const tooltip    = document.getElementById('node-tooltip');
    const ttKind     = document.getElementById('tt-kind');
    const ttName     = document.getElementById('tt-name');
    let graphInst    = null;

    const TYPE_COLOR = {
        file: '#3b82f6', module: '#3b82f6',
        class: '#a855f7',
        function: '#06b6d4', method: '#06b6d4',
    };
    function nColor(n) { return TYPE_COLOR[(n.type || '').toLowerCase()] || '#8b949e'; }

    function loadGraph() {
        fetch('/api/graph').then(r => r.json()).then(data => {
            if (!data.nodes || data.nodes.length === 0) {
                graphEmpty.style.display = 'flex';
                return;
            }
            graphEmpty.style.display = 'none';
            nodeCountEl.textContent  = data.nodes.length + ' nodes';

            if (graphInst) {
                graphInst.graphData({ nodes: data.nodes, links: data.links || [] });
                return;
            }

            graphInst = ForceGraph()(graphCont)
                .graphData({ nodes: data.nodes, links: data.links || [] })
                .width(graphCont.offsetWidth)
                .height(graphCont.offsetHeight)
                .nodeId('id')
                .nodeColor(nColor)
                .nodeVal(n => { const t = (n.type||'').toLowerCase(); return t==='file'||t==='module'?6:3; })
                .nodeLabel(() => '')
                .linkColor(() => 'rgba(139,148,158,0.2)')
                .linkWidth(0.7)
                .linkDirectionalArrowLength(3)
                .linkDirectionalArrowRelPos(1)
                .linkLabel(l => l.relation || '')
                .backgroundColor('#0a0a0f')
                .onNodeHover(node => {
                    if (node) {
                        ttKind.textContent = node.type || 'node';
                        ttName.textContent = node.id;
                        tooltip.style.display = 'block';
                    } else {
                        tooltip.style.display = 'none';
                    }
                });

            graphCont.addEventListener('mousemove', e => {
                if (tooltip.style.display !== 'block') return;
                const r = graphCont.getBoundingClientRect();
                let x = e.clientX - r.left + 14, y = e.clientY - r.top + 14;
                if (x + 250 > r.width) x = e.clientX - r.left - 254;
                tooltip.style.left = x + 'px';
                tooltip.style.top  = y + 'px';
            });

            window.addEventListener('resize', () => {
                graphInst.width(graphCont.offsetWidth).height(graphCont.offsetHeight);
            });
        }).catch(err => {
            graphEmpty.innerHTML =
                '<div class="ges-icon">⚠</div>' +
                '<div class="ges-title">Failed to load graph</div>' +
                '<div style="font-size:11px;font-family:var(--font-mono);color:var(--red)">' + esc(String(err)) + '</div>';
            graphEmpty.style.display = 'flex';
        });
    }

    loadGraph();
    document.getElementById('graph-refresh').addEventListener('click', loadGraph);
})();
</script>
</body>
</html>
"""

@app.get("/")
async def get():
    return HTMLResponse(HTML_CONTENT)

@app.get("/api/graph")
async def get_graph():
    from dotenv import load_dotenv
    load_dotenv()
    directory = os.getenv("FOLDER_PATH", ".")
    path = os.path.join(directory, ".revi", "semantic_graph.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # NetworkX node_link_data uses "edges", but force-graph expects "links"
        if "edges" in data and "links" not in data:
            data["links"] = data.pop("edges")
        # Ensure each link has 'source' and 'target' (NetworkX may use different keys)
        for link in data.get("links", []):
            if "source" not in link and "from" in link:
                link["source"] = link["from"]
            if "target" not in link and "to" in link:
                link["target"] = link["to"]
        return JSONResponse(data)
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
        body_bytes = await request.body()
        payload = json.loads(body_bytes.decode('utf-8'))
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON payload"}, status_code=400)
        
    # --- Security: HMAC Signature Verification ---
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if webhook_secret:
        import hmac
        import hashlib
        signature_header = request.headers.get("X-Hub-Signature-256")
        if not signature_header:
            return JSONResponse({"status": "error", "message": "Missing X-Hub-Signature-256"}, status_code=401)
            
        expected_hash = hmac.new(
            webhook_secret.encode('utf-8'),
            msg=body_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        expected_signature = f"sha256={expected_hash}"
        if not hmac.compare_digest(signature_header, expected_signature):
            return JSONResponse({"status": "error", "message": "Invalid HMAC signature"}, status_code=401)
            
    action = payload.get("action", "")
    
    # --- Issue Fix Trigger ---
    if "issue" in payload and action in ["opened", "labeled"]:
        issue = payload["issue"]
        labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
        
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

@app.get("/api/tokens")
async def get_tokens():
    """Real-time session token budget from LLM API responses."""
    try:
        import sys
        if 'src' not in sys.path:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from llm.client import get_session_stats
        stats = get_session_stats()
        stats["total_tokens"] = stats["prompt_tokens"] + stats["completion_tokens"]
        cache_pct = int(100 * stats["cache_read_tokens"] / stats["prompt_tokens"]) if stats["prompt_tokens"] > 0 else 0
        stats["cache_hit_pct"] = cache_pct
        return JSONResponse(stats)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

def start_server():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

