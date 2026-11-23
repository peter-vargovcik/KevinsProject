#!/usr/bin/env python3
"""Flask HTML5 UI for live HC-SR04 distances (RP2040 SONAR,ON).

Runs on the Pi (UART to RP2040). Open from a laptop browser:
  http://<pi-ip>:8088/

Usage:
  cd ~/KevinsProject
  source ~/arrow-env/bin/activate
  pip install flask
  python src/sonar_debug_server.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, render_template_string

from rp2040_uart import Rp2040Client  # noqa: E402

HOST = "0.0.0.0"
PORT = 8088

_lock = threading.Lock()
_state: dict[str, Any] = {
    "front": -1,
    "left": -1,
    "right": -1,
    "active": False,
    "updated_ms": 0,
    "error": None,
    "raw": "",
}
_client: Optional[Rp2040Client] = None
_client_lock = threading.Lock()


def _on_line(line: str) -> None:
    if not line.startswith("RANGE3,"):
        return
    parts = line.strip().split(",")
    if len(parts) < 4:
        return
    try:
        front, left, right = int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        return
    with _lock:
        _state["front"] = front
        _state["left"] = left
        _state["right"] = right
        _state["updated_ms"] = int(time.time() * 1000)
        _state["raw"] = line.strip()
        _state["error"] = None


def _get_client() -> Rp2040Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = Rp2040Client(on_line=_on_line, timeout_s=2.0)
            _client.open()
        return _client


def _snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Sonar debug</title>
<style>
  :root {
    --bg: #0e1114;
    --panel: #171b20;
    --ink: #e8ecef;
    --muted: #8b959e;
    --ok: #3dbe7f;
    --bad: #d4574a;
    --accent: #c4a35a;
    --line: #2a3138;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    background:
      radial-gradient(1200px 600px at 10% -10%, #1a2229 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #1c1810 0%, transparent 50%),
      var(--bg);
    color: var(--ink);
  }
  header {
    padding: 1.25rem 1.5rem 0.5rem;
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: baseline;
    justify-content: space-between;
  }
  h1 {
    margin: 0;
    font-size: clamp(1.4rem, 3vw, 2rem);
    font-weight: 600;
    letter-spacing: 0.02em;
  }
  .sub { color: var(--muted); font-size: 0.95rem; }
  .controls { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  button {
    appearance: none;
    border: 1px solid var(--line);
    background: var(--panel);
    color: var(--ink);
    padding: 0.65rem 1.1rem;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  button:hover { border-color: var(--accent); }
  button.on { background: #1e2a22; border-color: var(--ok); color: var(--ok); }
  button.off { background: #2a1c1b; border-color: var(--bad); color: #f0a39c; }
  main {
    padding: 1rem 1.5rem 2rem;
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  @media (max-width: 800px) {
    main { grid-template-columns: 1fr; }
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 1.25rem 1.35rem 1.5rem;
    min-height: 11rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .label {
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 0.75rem;
    color: var(--muted);
  }
  .pin { font-size: 0.8rem; color: var(--muted); }
  .value {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: clamp(2.8rem, 8vw, 4.2rem);
    font-weight: 500;
    line-height: 1.05;
    margin-top: auto;
  }
  .value.dead { color: var(--bad); }
  .value.live { color: var(--ok); }
  .bar {
    height: 4px;
    background: #22282e;
    margin-top: 0.75rem;
    overflow: hidden;
  }
  .bar > span {
    display: block;
    height: 100%;
    width: 0%;
    background: var(--accent);
    transition: width 0.15s linear;
  }
  footer {
    padding: 0 1.5rem 1.5rem;
    color: var(--muted);
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 0.8rem;
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
  }
  .err { color: var(--bad); }
</style>
</head>
<body>
  <header>
    <div>
      <h1>Sonar debug</h1>
      <div class="sub">RP2040 HC-SR04 · live RANGE3 over UART</div>
    </div>
    <div class="controls">
      <button id="btnOn" class="on" type="button">Sonar ON</button>
      <button id="btnOff" class="off" type="button">Sonar OFF</button>
    </div>
  </header>
  <main>
    <section class="card" data-key="front">
      <div class="label">Front</div>
      <div class="pin">TRIG GP14 · ECHO GP15</div>
      <div class="value dead" id="v-front">—</div>
      <div class="bar"><span id="b-front"></span></div>
    </section>
    <section class="card" data-key="left">
      <div class="label">Left</div>
      <div class="pin">TRIG GP8 · ECHO GP9</div>
      <div class="value dead" id="v-left">—</div>
      <div class="bar"><span id="b-left"></span></div>
    </section>
    <section class="card" data-key="right">
      <div class="label">Right</div>
      <div class="pin">TRIG GP16 · ECHO GP17</div>
      <div class="value dead" id="v-right">—</div>
      <div class="bar"><span id="b-right"></span></div>
    </section>
  </main>
  <footer>
    <span id="status">idle</span>
    <span id="raw"></span>
    <span id="err" class="err"></span>
  </footer>
<script>
const MAX_CM = 200;
function fmt(cm) {
  if (cm === null || cm === undefined || cm < 0) return "—";
  return cm + " cm";
}
function setSensor(key, cm) {
  const el = document.getElementById("v-" + key);
  const bar = document.getElementById("b-" + key);
  el.textContent = fmt(cm);
  const live = typeof cm === "number" && cm > 0;
  el.classList.toggle("live", live);
  el.classList.toggle("dead", !live);
  const pct = live ? Math.max(2, Math.min(100, (cm / MAX_CM) * 100)) : 0;
  bar.style.width = pct + "%";
}
function apply(data) {
  setSensor("front", data.front);
  setSensor("left", data.left);
  setSensor("right", data.right);
  document.getElementById("status").textContent =
    (data.active ? "streaming" : "idle") +
    (data.updated_ms ? " · " + new Date(data.updated_ms).toLocaleTimeString() : "");
  document.getElementById("raw").textContent = data.raw || "";
  document.getElementById("err").textContent = data.error || "";
}
async function post(path) {
  const r = await fetch(path, { method: "POST" });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  apply(data);
}
document.getElementById("btnOn").onclick = () =>
  post("/api/sonar/on").catch(e => { document.getElementById("err").textContent = e.message; });
document.getElementById("btnOff").onclick = () =>
  post("/api/sonar/off").catch(e => { document.getElementById("err").textContent = e.message; });

const es = new EventSource("/api/stream");
es.onmessage = (ev) => {
  try { apply(JSON.parse(ev.data)); } catch (_) {}
};
es.onerror = () => {
  document.getElementById("status").textContent = "stream reconnecting…";
};
</script>
</body>
</html>
"""

app = Flask(__name__)


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/state")
def api_state():
    return jsonify(_snapshot())


@app.post("/api/sonar/on")
def api_sonar_on():
    try:
        c = _get_client()
        c.sonar_on()
        with _lock:
            _state["active"] = True
            _state["error"] = None
        return jsonify(_snapshot())
    except Exception as exc:
        with _lock:
            _state["error"] = str(exc)
            _state["active"] = False
        return jsonify(_snapshot()), 500


@app.post("/api/sonar/off")
def api_sonar_off():
    try:
        c = _get_client()
        c.sonar_off()
        with _lock:
            _state["active"] = False
            _state["front"] = -1
            _state["left"] = -1
            _state["right"] = -1
            _state["error"] = None
        return jsonify(_snapshot())
    except Exception as exc:
        with _lock:
            _state["error"] = str(exc)
        return jsonify(_snapshot()), 500


@app.get("/api/stream")
def api_stream():
    def gen():
        last = None
        while True:
            snap = _snapshot()
            payload = json.dumps(snap)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            else:
                yield ": keepalive\n\n"
            time.sleep(0.1)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    # Open UART early so failures show in the terminal
    try:
        _get_client()
        print(f"UART open. UI: http://0.0.0.0:{PORT}/ (use Pi LAN IP from laptop)")
    except Exception as exc:
        print(f"WARN: UART not open yet: {exc}", file=sys.stderr)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
