"""ContextFlow Web Gateway & Real-Time Data Hub.

Serves a dual-panel web interface:
  - Left: Fully interactive, smooth, scrollable terminal (ttyd + Claude Code CLI)
  - Right: Drag-and-drop file upload zone + live file & snapshot inspector
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import aiohttp
from aiohttp import web

ROOT_DIR = Path(__file__).parent.resolve()
DATA_FILES_DIR = ROOT_DIR / "data" / "files"
SNAPSHOTS_DIR = ROOT_DIR / "snapshots"
DATA_FILES_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

TTYD_PORT = 7682
TTYD_URL = f"http://127.0.0.1:{TTYD_PORT}"

# HTML Template with Obsidian Dark Theme and HydraDB Orange styling
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ContextFlow | Graph-RAG Terminal & Data Hub</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #0b0c10;
      --bg-panel: #111319;
      --bg-card: #161922;
      --border: #202432;
      --border-focus: #ff5719;
      --orange: #ff5719;
      --orange-hover: #ff733d;
      --peach: #ffa066;
      --text-main: #f1f5f9;
      --text-muted: #828c9e;
      --green: #10b981;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-dark);
      color: var(--text-main);
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    header {
      height: 48px;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
    }
    .logo-badge {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 0.5px;
    }
    .logo-badge .dot {
      width: 10px;
      height: 10px;
      background: var(--orange);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--orange);
    }
    .status-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--peach);
      background: #1d1712;
      border: 1px solid #3d2417;
      padding: 4px 10px;
      border-radius: 12px;
      font-family: 'JetBrains Mono', monospace;
    }
    .main-layout {
      flex: 1;
      display: flex;
      height: calc(100vh - 48px);
      overflow: hidden;
    }
    .terminal-pane {
      flex: 1;
      height: 100%;
      background: #000000;
      border-right: 1px solid var(--border);
      position: relative;
    }
    .terminal-pane iframe {
      width: 100%;
      height: 100%;
      border: none;
      display: block;
    }
    .sidebar-pane {
      width: 380px;
      background: var(--bg-panel);
      height: 100%;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      padding: 18px;
      gap: 18px;
    }
    .sidebar-pane::-webkit-scrollbar { width: 6px; }
    .sidebar-pane::-webkit-scrollbar-thumb { background: #232838; border-radius: 3px; }
    .panel-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .dropzone {
      border: 2px dashed var(--border);
      border-radius: 10px;
      padding: 20px 14px;
      text-align: center;
      background: var(--bg-card);
      cursor: pointer;
      transition: all 0.2s ease;
    }
    .dropzone:hover, .dropzone.dragover {
      border-color: var(--orange);
      background: #1c1a20;
    }
    .drop-icon {
      font-size: 28px;
      margin-bottom: 6px;
    }
    .drop-text {
      font-weight: 600;
      font-size: 13px;
      margin-bottom: 2px;
    }
    .drop-hint {
      font-size: 11px;
      color: var(--text-muted);
    }
    .notification {
      display: none;
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-family: 'JetBrains Mono', monospace;
      animation: fadeIn 0.3s ease;
    }
    .notification.success {
      background: #0d281e;
      border: 1px solid #10b981;
      color: #6ee7b7;
      display: block;
    }
    .notification.loading {
      background: #231b12;
      border: 1px solid var(--orange);
      color: var(--peach);
      display: block;
    }
    .datasets-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .dataset-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      transition: border-color 0.2s ease;
    }
    .dataset-card:hover {
      border-color: #2f364a;
    }
    .dataset-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 4px;
    }
    .dataset-name {
      font-weight: 600;
      font-size: 12.5px;
      color: var(--text-main);
      font-family: 'JetBrains Mono', monospace;
      word-break: break-all;
    }
    .dataset-pill {
      font-size: 10px;
      color: var(--green);
      background: #0d251a;
      border: 1px solid #14532d;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: 'JetBrains Mono', monospace;
      flex-shrink: 0;
      margin-left: 6px;
    }
    .dataset-stats {
      font-size: 11.5px;
      color: var(--text-muted);
      font-family: 'JetBrains Mono', monospace;
    }
    .sample-btn {
      width: 100%;
      text-align: left;
      background: #12141c;
      border: 1px solid #1d212d;
      color: var(--peach);
      font-size: 11px;
      padding: 6px 8px;
      border-radius: 6px;
      cursor: pointer;
      margin-top: 6px;
      font-family: 'JetBrains Mono', monospace;
      transition: all 0.2s;
    }
    .sample-btn:hover {
      background: #1b1c24;
      border-color: var(--orange);
      color: #ffffff;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
  </style>
</head>
<body>
  <header>
    <div class="logo-badge">
      <div class="dot"></div>
      <span>CONTEXT FLOW</span>
      <span style="color: var(--text-muted); font-weight: 400; font-size: 13px;">| Graph-RAG Terminal</span>
    </div>
    <div class="status-badge">
      <span>● ZERO-INFRA LOCAL ENGINE</span>
    </div>
  </header>

  <div class="main-layout">
    <div class="terminal-pane">
      <iframe src="/terminal/" id="term-frame"></iframe>
    </div>

    <div class="sidebar-pane">
      <div>
        <div class="panel-title">
          <span>Drop New Document</span>
        </div>
        <div class="dropzone" id="dropzone">
          <div class="drop-icon">📂</div>
          <div class="drop-text">Drop PDF, TXT, MD, or JSON</div>
          <div class="drop-hint">Auto-builds HydraDB Snapshot</div>
          <input type="file" id="file-input" style="display:none" accept=".pdf,.txt,.md,.json" />
        </div>
      </div>

      <div id="status-box" class="notification"></div>

      <div>
        <div class="panel-title">
          <span>Active Files (data/files)</span>
          <span id="files-count" style="font-weight: 400; font-size: 11px;">0 files</span>
        </div>
        <div class="datasets-list" id="files-container">
          <div class="dataset-stats" style="padding: 8px;">Loading files...</div>
        </div>
      </div>

      <div>
        <div class="panel-title">
          <span>Compiled Graph Snapshots</span>
          <span id="snapshots-count" style="font-weight: 400; font-size: 11px;">0 snapshots</span>
        </div>
        <div class="datasets-list" id="snapshots-container">
          <div class="dataset-stats" style="padding: 8px;">Loading snapshots...</div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const statusBox = document.getElementById('status-box');

    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        uploadFile(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        uploadFile(fileInput.files[0]);
      }
    });

    async function uploadFile(file) {
      statusBox.className = 'notification loading';
      statusBox.innerHTML = `⚡ Extracting graph & compiling snapshot for <b>${file.name}</b>...`;

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
          statusBox.className = 'notification success';
          statusBox.innerHTML = `✔ <b>${data.filename}</b> compiled!<br>${data.vertices} vertices · ${data.edges} edges.<br><i>Ready to query in the left terminal!</i>`;
          loadDatasets();
        } else {
          statusBox.className = 'notification';
          statusBox.style.display = 'block';
          statusBox.style.borderColor = '#ef4444';
          statusBox.style.color = '#fca5a5';
          statusBox.innerText = 'Upload failed: ' + data.error;
        }
      } catch (err) {
        statusBox.className = 'notification';
        statusBox.style.display = 'block';
        statusBox.style.borderColor = '#ef4444';
        statusBox.style.color = '#fca5a5';
        statusBox.innerText = 'Network error: ' + err.message;
      }
    }

    function copyQuery(q) {
      navigator.clipboard.writeText(q);
      const prev = statusBox.style.display;
      statusBox.className = 'notification success';
      statusBox.innerHTML = `Copied to clipboard:<br><i>"${q}"</i><br>Paste it directly into the terminal!`;
      setTimeout(() => { statusBox.style.display = prev; }, 3500);
    }

    async function loadDatasets() {
      try {
        const res = await fetch('/api/snapshots');
        const data = await res.json();

        // 1. Render files in data/files
        if (data.files) {
          const filesContainer = document.getElementById('files-container');
          document.getElementById('files-count').innerText = `${data.files.length} file(s)`;
          filesContainer.innerHTML = data.files.map(f => `
            <div class="dataset-card">
              <div class="dataset-header">
                <span class="dataset-name">📄 ${f.name}</span>
                <span class="dataset-pill">${f.has_snapshot ? 'Snapshot Ready' : 'Pending'}</span>
              </div>
              <div class="dataset-stats">${f.size_kb} KB · ${f.snapshot_name || 'No snapshot'}</div>
            </div>
          `).join('');
        }

        // 2. Render snapshots in snapshots/
        if (data.snapshots) {
          const snapsContainer = document.getElementById('snapshots-container');
          document.getElementById('snapshots-count').innerText = `${data.snapshots.length} snapshot(s)`;
          snapsContainer.innerHTML = data.snapshots.map(s => {
            let sampleBtn = '';
            if (s.name.includes('incidents')) {
              sampleBtn = `<button class="sample-btn" onclick="copyQuery('Which change caused INC-1042 and who owns it?')">➔ "Which change caused INC-1042?"</button>`;
            } else if (s.name.includes('ArtOfWar')) {
              sampleBtn = `<button class="sample-btn" onclick="copyQuery('What are the five constant factors in the art of war?')">➔ "What are the 5 constant factors?"</button>`;
            } else if (s.name.includes('architecture')) {
              sampleBtn = `<button class="sample-btn" onclick="copyQuery('Which team maintains the checkout-api service?')">➔ "Who maintains checkout-api?"</button>`;
            }
            return `
              <div class="dataset-card">
                <div class="dataset-header">
                  <span class="dataset-name">◆ ${s.name}</span>
                  <span class="dataset-pill">Active</span>
                </div>
                <div class="dataset-stats">${s.vertices} vertices · ${s.edges} edges (${s.size_kb} KB)</div>
                ${sampleBtn}
              </div>
            `;
          }).join('');
        }
      } catch (e) {}
    }

    window.addEventListener('DOMContentLoaded', () => {
      loadDatasets();
      setInterval(loadDatasets, 4000);
    });
  </script>
</body>
</html>
"""


async def index_handler(request: web.Request) -> web.Response:
    """Serve the dual-panel web dashboard."""
    return web.Response(text=HTML_PAGE, content_type="text/html")


async def upload_handler(request: web.Request) -> web.Response:
    """Handle drag-and-drop file upload and auto-generate HydraDB snapshot."""
    reader = await request.multipart()
    field = await reader.next()
    if not field or not field.filename:
        return web.json_response({"success": False, "error": "No file uploaded"}, status=400)

    filename = Path(field.filename).name
    save_path = DATA_FILES_DIR / filename

    size = 0
    with open(save_path, "wb") as f:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)

    # Auto-compile snapshot
    try:
        from prepare_snapshot import build_file_snapshot
        snapshot = build_file_snapshot(save_path)
        out_path = SNAPSHOTS_DIR / f"{save_path.stem}.snapshot.json"
        out_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        v_count = snapshot.get("counts", {}).get("vertices", len(snapshot.get("vertices", [])))
        e_count = snapshot.get("counts", {}).get("edges", len(snapshot.get("edges", [])))
        return web.json_response({
            "success": True,
            "filename": filename,
            "vertices": v_count,
            "edges": e_count,
            "snapshot": out_path.name,
        })
    except Exception as exc:
        return web.json_response({
            "success": True,
            "filename": filename,
            "vertices": 1,
            "edges": 0,
            "warning": f"Uploaded as raw document: {exc}",
        })


async def snapshots_handler(request: web.Request) -> web.Response:
    """Return list of files in data/files/ and snapshots in snapshots/."""
    files_list = []
    for f in sorted(DATA_FILES_DIR.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            snap_path = SNAPSHOTS_DIR / f"{f.stem}.snapshot.json"
            files_list.append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "has_snapshot": snap_path.exists(),
                "snapshot_name": snap_path.name if snap_path.exists() else None,
            })

    snaps_list = []
    for s in sorted(SNAPSHOTS_DIR.glob("*.snapshot.json")):
        try:
            d = json.loads(s.read_text(encoding="utf-8"))
            counts = d.get("counts", {})
            v = counts.get("vertices", len(d.get("vertices", [])))
            e = counts.get("edges", len(d.get("edges", [])))
            snaps_list.append({
                "name": s.name,
                "vertices": v,
                "edges": e,
                "size_kb": round(s.stat().st_size / 1024, 1),
            })
        except Exception:
            snaps_list.append({
                "name": s.name,
                "vertices": "active",
                "edges": "",
                "size_kb": round(s.stat().st_size / 1024, 1),
            })

    return web.json_response({
        "files": files_list,
        "snapshots": snaps_list
    })


async def ttyd_proxy_handler(request: web.Request) -> web.StreamResponse:
    """Proxy HTTP and WebSocket requests to background ttyd process."""
    path = request.match_info.get("path", "")
    target_url = f"{TTYD_URL}/terminal/{path}"
    if request.query_string:
        target_url += f"?{request.query_string}"

    # WebSocket Proxy
    if request.headers.get("Upgrade", "").lower() == "websocket":
        ws_client = web.WebSocketResponse()
        await ws_client.prepare(request)

        ws_url = target_url.replace("http://", "ws://").replace("https://", "wss://")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(ws_url) as ws_ttyd:
                    async def forward_to_ttyd():
                        async for msg in ws_client:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await ws_ttyd.send_str(msg.data)
                            elif msg.type == aiohttp.WSMsgType.BINARY:
                                await ws_ttyd.send_bytes(msg.data)
                            elif msg.type == aiohttp.WSMsgType.CLOSE:
                                await ws_ttyd.close()
                                break

                    async def forward_to_client():
                        async for msg in ws_ttyd:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await ws_client.send_str(msg.data)
                            elif msg.type == aiohttp.WSMsgType.BINARY:
                                await ws_client.send_bytes(msg.data)
                            elif msg.type == aiohttp.WSMsgType.CLOSE:
                                await ws_client.close()
                                break

                    await asyncio.gather(forward_to_ttyd(), forward_to_client())
            except Exception:
                pass
        return ws_client

    # HTTP Proxy
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                request.method,
                target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")},
                data=await request.read(),
                allow_redirects=False,
            ) as resp:
                body = await resp.read()
                headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "transfer-encoding")}
                return web.Response(body=body, status=resp.status, headers=headers)
        except Exception as e:
            return web.Response(text=f"Connecting to terminal backend... ({e})", status=502)


def main():
    port = int(os.getenv("PORT", "10000"))

    # Spawn background ttyd process attached to tui.py
    ttyd_bin = shutil.which("ttyd") or "/usr/local/bin/ttyd" or "/usr/bin/ttyd"
    py_bin = str(ROOT_DIR / ".venv" / "bin" / "python")
    if not Path(py_bin).exists():
        py_bin = sys.executable

    print(f"Launching background ttyd on 127.0.0.1:{TTYD_PORT} with base-path /terminal...")
    env = os.environ.copy()
    env["TTY_ATTACHED"] = "1"
    subprocess.Popen(
        [
            ttyd_bin,
            "-p", str(TTYD_PORT),
            "-i", "127.0.0.1",
            "-b", "/terminal",
            "-W",
            "-w", str(ROOT_DIR),
            "-t", "fontSize=14",
            "-t", "fontFamily=ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace",
            "-t", "letterSpacing=0",
            "-t", "lineHeight=1.2",
            "-t", "theme={\"background\": \"#0b0c10\", \"foreground\": \"#eceff4\", \"cursor\": \"#FF5719\"}",
            py_bin,
            str(ROOT_DIR / "tui.py"),
        ],
        cwd=str(ROOT_DIR),
        env=env,
    )

    app = web.Application(client_max_size=50 * 1024 * 1024)
    app.router.add_get("/", index_handler)
    app.router.add_post("/api/upload", upload_handler)
    app.router.add_get("/api/snapshots", snapshots_handler)
    app.router.add_route("*", "/terminal", ttyd_proxy_handler)
    app.router.add_route("*", "/terminal/{path:.*}", ttyd_proxy_handler)

    print(f"Starting ContextFlow Web Gateway on http://0.0.0.0:{port}...")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
