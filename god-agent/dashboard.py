"""
dashboard.py — JARVIS live dashboard.

Run alongside main.py:
    Terminal 1: python dashboard.py
    Terminal 2: python main.py
    Browser:    http://localhost:5000

Shows: live agent activity log, shared workspace artifacts, session stats.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow imports from the jarvis package
BASE = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE))

os.environ.setdefault("MEMORY_DB", str(BASE / "memory" / "jarvis.db"))

from flask import Flask, render_template_string, jsonify
from memory.memory import Workspace

app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS — God Agent</title>
<style>
  :root {
    --green:  #00ff88;
    --dim:    #00aa55;
    --cyan:   #00ccff;
    --yellow: #ffcc00;
    --purple: #cc44ff;
    --blue:   #4488ff;
    --red:    #ff4444;
    --bg:     #060608;
    --card:   #0c0d10;
    --border: #1a1c22;
    --text:   #c0c8d0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--green); font-family: 'Courier New', monospace; min-height: 100vh; }

  /* ── Header ── */
  .header { padding: 20px 28px 12px; border-bottom: 1px solid var(--border); }
  .header h1 { font-size: 22px; letter-spacing: 6px; color: #fff; font-weight: 700; }
  .header .sub { color: #444; font-size: 11px; letter-spacing: 3px; margin-top: 2px; }
  .status-bar { display: flex; gap: 24px; margin-top: 10px; font-size: 11px; color: #555; align-items: center; }
  .pulse { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--green); margin-right: 6px; vertical-align: middle; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.15} }
  .stat { color: var(--dim); }
  .stat span { color: var(--green); }

  /* ── Layout ── */
  .main { display: grid; grid-template-columns: 1.4fr 1fr; gap: 0; height: calc(100vh - 82px); }

  /* ── Cards ── */
  .card { border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
  .card:last-child { border-right: none; }
  .card-header { padding: 14px 18px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
  .card-header h3 { font-size: 10px; letter-spacing: 3px; color: #444; text-transform: uppercase; }
  .card-header .badge { font-size: 10px; color: #333; }
  .card-body { flex: 1; overflow-y: auto; padding: 10px 0; }
  .card-body::-webkit-scrollbar { width: 3px; }
  .card-body::-webkit-scrollbar-thumb { background: #1a1c22; }

  /* ── Log entries ── */
  .log-entry { padding: 8px 18px; border-bottom: 1px solid #0d0e12; display: flex; gap: 10px; align-items: flex-start; font-size: 12px; line-height: 1.5; }
  .log-entry:hover { background: #0d0e12; }
  .ts { color: #2a2e38; font-size: 10px; white-space: nowrap; padding-top: 2px; flex-shrink: 0; }
  .agent-tag { padding: 1px 7px; border-radius: 2px; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; white-space: nowrap; flex-shrink: 0; }
  .coding   { background: #001a2e; color: var(--blue); }
  .research { background: #1a1a00; color: var(--yellow); }
  .app      { background: #18001e; color: var(--purple); }
  .god-agent { background: #001a10; color: var(--green); }
  .status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
  .ok   { background: var(--green); }
  .fail { background: var(--red); }
  .task-text { color: #666; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dur { color: #2a2e38; font-size: 10px; white-space: nowrap; flex-shrink: 0; padding-top: 2px; }

  /* ── Workspace entries ── */
  .ws-entry { padding: 10px 18px; border-bottom: 1px solid #0d0e12; }
  .ws-entry:hover { background: #0d0e12; }
  .ws-key { color: var(--green); font-size: 12px; letter-spacing: 0.5px; margin-bottom: 3px; }
  .ws-meta { font-size: 10px; color: #333; }
  .ws-meta .by { color: #444; }

  /* ── Right panel — split ── */
  .right-panel { display: flex; flex-direction: column; }
  .right-panel .card { border-right: none; border-bottom: 1px solid var(--border); }
  .right-panel .card:last-child { border-bottom: none; }

  /* ── Empty state ── */
  .empty { color: #1e2028; font-size: 12px; padding: 24px 18px; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #1a1c22; border-radius: 2px; }
</style>
<script>
let lastLogCount = 0;
let lastWsCount  = 0;

async function refresh() {
  try {
    const [log, ws, stats] = await Promise.all([
      fetch('/api/log').then(r => r.json()),
      fetch('/api/workspace').then(r => r.json()),
      fetch('/api/stats').then(r => r.json()),
    ]);

    // Update stats bar
    document.getElementById('stat-events').textContent = log.entries.length;
    document.getElementById('stat-artifacts').textContent = ws.items.length;
    document.getElementById('stat-success').textContent = stats.success_rate + '%';
    document.getElementById('stat-session').textContent = stats.session || '—';

    // Update log (only if changed)
    if (log.entries.length !== lastLogCount) {
      lastLogCount = log.entries.length;
      const logEl = document.getElementById('log');
      const atBottom = logEl.scrollHeight - logEl.clientHeight <= logEl.scrollTop + 40;

      logEl.innerHTML = log.entries.length === 0
        ? '<div class="empty">Waiting for agent activity...</div>'
        : log.entries.map(e => `
          <div class="log-entry">
            <span class="ts">${e.ts.slice(11, 19)}</span>
            <span class="agent-tag ${e.agent}">${e.agent}</span>
            <span class="status-dot ${e.success ? 'ok' : 'fail'}"></span>
            <span class="task-text">${escHtml(e.task.slice(0, 120))}</span>
            <span class="dur">${e.duration_s ? e.duration_s.toFixed(1) + 's' : ''}</span>
          </div>`).join('');

      if (atBottom) logEl.scrollTop = logEl.scrollHeight;
    }

    // Update workspace (only if changed)
    if (ws.items.length !== lastWsCount) {
      lastWsCount = ws.items.length;
      const wsEl = document.getElementById('workspace');
      wsEl.innerHTML = ws.items.length === 0
        ? '<div class="empty">No artifacts saved yet.</div>'
        : ws.items.map(i => `
          <div class="ws-entry">
            <div class="ws-key">${escHtml(i.key)}</div>
            <div class="ws-meta">
              <span class="by">${i.agent}</span>
              &nbsp;·&nbsp;${i.ts.slice(0, 16)}
              &nbsp;·&nbsp;${i.size.toLocaleString()} chars
            </div>
          </div>`).join('');
    }
  } catch(e) {
    console.warn('refresh error', e);
  }
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

setInterval(refresh, 2000);
refresh();
</script>
</head>
<body>
  <div class="header">
    <h1>⚡ JARVIS</h1>
    <div class="sub">GOD AGENT · MULTI-AGENT AI OPERATING SYSTEM</div>
    <div class="status-bar">
      <span><span class="pulse"></span>LIVE</span>
      <span class="stat">events: <span id="stat-events">—</span></span>
      <span class="stat">artifacts: <span id="stat-artifacts">—</span></span>
      <span class="stat">success: <span id="stat-success">—</span></span>
      <span class="stat">session: <span id="stat-session">—</span></span>
    </div>
  </div>

  <div class="main">
    <!-- Activity log -->
    <div class="card">
      <div class="card-header">
        <h3>Agent Activity Log</h3>
        <span class="badge" id="log-badge"></span>
      </div>
      <div class="card-body" id="log">
        <div class="empty">Waiting for agent activity...</div>
      </div>
    </div>

    <!-- Right panel -->
    <div class="right-panel">
      <!-- Workspace -->
      <div class="card" style="flex: 1;">
        <div class="card-header">
          <h3>Shared Workspace</h3>
          <span class="badge">artifacts</span>
        </div>
        <div class="card-body" id="workspace">
          <div class="empty">No artifacts saved yet.</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/log')
def log():
    log_path = BASE / "logs" / "task_log.jsonl"
    entries = []
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").strip().split('\n')
            for line in lines[-100:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass
    return jsonify({"entries": entries})


@app.route('/api/workspace')
def workspace():
    try:
        ws = Workspace()
        return jsonify({"items": ws.list_keys()})
    except Exception:
        return jsonify({"items": []})


@app.route('/api/stats')
def stats():
    log_path = BASE / "logs" / "task_log.jsonl"
    entries = []
    session = "—"
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").strip().split('\n')
            for line in lines[-200:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass
    if entries:
        session = entries[-1].get("session", "—")
        ok = sum(1 for e in entries if e.get("success"))
        rate = round(ok / len(entries) * 100)
    else:
        rate = 0
    return jsonify({"success_rate": rate, "session": session})


if __name__ == '__main__':
    print("\n  JARVIS Dashboard running at http://localhost:5000")
    print("  Keep this terminal open alongside main.py\n")
    app.run(port=5000, debug=False, use_reloader=False)
