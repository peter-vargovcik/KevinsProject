#!/usr/bin/env python3
"""Comprehensive RP2040 test UI over Wi‑Fi (Flask on the Pi).

Features:
  - Live STATUS + sonar RANGE3
  - Sonar ON/OFF
  - Pull-over LEFT / RIGHT / ABORT
  - Virtual joystick (MODE,AUTO + CAP + DRIVE pulses)
  - Throttle caps default 25% (user-adjustable 0–100)
  - Pullover tunables (SIDE/BAND/FRONT/CREEP/STEER/STABLE/TIMEOUT)
  - Joystick pulse duration (Flask-local)
  - STOP / RESET / MANUAL

  http://<pi-ip>:8088/
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, render_template_string, request

from rp2040_uart import Rp2040Client, parse_status  # noqa: E402

HOST = "0.0.0.0"
PORT = 8088
DEFAULT_CAP = 25
DEFAULT_JOYSTICK_MS = 280
LOG_MAX = 80

PULLOVER_DEFAULTS = {
    "side": 10,
    "band": 2,
    "front": 25,
    "creep": 10,
    "steer": 28,
    "stable": 400,
    "timeout": 15000,
}
PULLOVER_KEYS = ("side", "band", "front", "creep", "steer", "stable", "timeout")
PULLOVER_SET_KEY = {
    "side": "SIDE",
    "band": "BAND",
    "front": "FRONT",
    "creep": "CREEP",
    "steer": "STEER",
    "stable": "STABLE",
    "timeout": "TIMEOUT",
}
PULLOVER_CLAMP = {
    "side": (5, 80),
    "band": (1, 20),
    "front": (10, 100),
    "creep": (5, 40),
    "steer": (5, 50),
    "stable": (100, 3000),
    "timeout": (3000, 60000),
}

_lock = threading.Lock()
_state: dict[str, Any] = {
    "front": -1,
    "left": -1,
    "right": -1,
    "sonar_active": False,
    "updated_ms": 0,
    "error": None,
    "raw": "",
    "mode": "?",
    "armed": False,
    "rc_ok": False,
    "steer_in": 0,
    "thr_in": 0,
    "steer_out": 0,
    "thr_out": 0,
    "forward_cap": DEFAULT_CAP,
    "reverse_cap": DEFAULT_CAP,
    "drive_active": False,
    "uptime_ms": 0,
    "pi_control": False,
    "joystick_ms": DEFAULT_JOYSTICK_MS,
    "pullover": dict(PULLOVER_DEFAULTS),
    "last_event": "",
    "log": [],
}
_joystick_ms = DEFAULT_JOYSTICK_MS
_log: Deque[str] = deque(maxlen=LOG_MAX)
_client: Optional[Rp2040Client] = None
_client_lock = threading.Lock()
_pi_control = False
_hb_started = False
_status_thread: Optional[threading.Thread] = None
_status_stop = threading.Event()


def _push_log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    entry = f"{ts} {msg}"
    _log.appendleft(entry)
    with _lock:
        _state["last_event"] = msg
        _state["log"] = list(_log)


def _on_line(line: str) -> None:
    line = line.strip()
    if not line:
        return
    with _lock:
        _state["raw"] = line
        _state["updated_ms"] = int(time.time() * 1000)

    if line.startswith("RANGE3,"):
        parts = line.split(",")
        if len(parts) >= 4:
            try:
                f, l, r = int(parts[1]), int(parts[2]), int(parts[3])
            except ValueError:
                return
            with _lock:
                _state["front"] = f
                _state["left"] = l
                _state["right"] = r
                _state["error"] = None
        return

    if line.startswith("RANGE,"):
        # pullover: RANGE,front,side
        parts = line.split(",")
        if len(parts) >= 3:
            try:
                f, s = int(parts[1]), int(parts[2])
            except ValueError:
                return
            with _lock:
                _state["front"] = f
                # side channel mirrors active manoeuvre; show on both gauges
                _state["left"] = s
                _state["right"] = s
        _push_log(line)
        return

    if line.startswith("STATUS,"):
        try:
            st = parse_status(line)
        except ValueError:
            return
        with _lock:
            _state["mode"] = st.mode
            _state["armed"] = st.armed
            _state["rc_ok"] = st.rc_ok
            _state["steer_in"] = st.rc_steer
            _state["thr_in"] = st.rc_throttle
            _state["steer_out"] = st.steer_out
            _state["thr_out"] = st.throttle_out
            _state["forward_cap"] = st.forward_cap
            _state["reverse_cap"] = st.reverse_cap
            _state["drive_active"] = st.drive_active
            _state["uptime_ms"] = st.uptime_ms
        return

    if line.startswith(
        ("DONE,", "ERR,", "OK,PULLOVER", "OK,SONAR", "OK,DRIVE", "OK,AUTO", "OK,MANUAL", "OK,STOP", "OK,RESET")
    ):
        _push_log(line)


def _get_client() -> Rp2040Client:
    global _client, _hb_started
    with _client_lock:
        if _client is None:
            _client = Rp2040Client(on_line=_on_line, timeout_s=2.0)
            _client.open()
        return _client


def _ensure_heartbeat() -> None:
    global _hb_started
    c = _get_client()
    if not _hb_started:
        c.start_heartbeat(0.1)
        _hb_started = True


def _snapshot() -> dict[str, Any]:
    with _lock:
        snap = dict(_state)
        snap["pi_control"] = _pi_control
        snap["joystick_ms"] = _joystick_ms
        snap["pullover"] = dict(_state.get("pullover") or PULLOVER_DEFAULTS)
        snap["log"] = list(_log)
        return snap


def _status_loop() -> None:
    while not _status_stop.wait(0.5):
        try:
            c = _get_client()
            c.status()
        except Exception:
            pass


def _start_status_poller() -> None:
    global _status_thread
    if _status_thread and _status_thread.is_alive():
        return
    _status_stop.clear()
    _status_thread = threading.Thread(target=_status_loop, name="status-poll", daemon=True)
    _status_thread.start()


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"/>
<title>RC test console</title>
<style>
  :root {
    --bg: #0c0f12;
    --panel: #151a1f;
    --ink: #e7ecef;
    --muted: #8b959e;
    --ok: #3dbe7f;
    --bad: #d4574a;
    --accent: #c4a35a;
    --line: #2a3138;
    --joy: #1c242c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    background:
      radial-gradient(900px 500px at 0% 0%, #1a2229 0%, transparent 55%),
      radial-gradient(700px 400px at 100% 10%, #1c1810 0%, transparent 45%),
      var(--bg);
    color: var(--ink);
  }
  header {
    padding: 1rem 1.25rem;
    display: flex; flex-wrap: wrap; gap: .75rem 1.25rem;
    align-items: baseline; justify-content: space-between;
    border-bottom: 1px solid var(--line);
  }
  h1 { margin: 0; font-size: 1.45rem; font-weight: 600; letter-spacing: .02em; }
  .sub { color: var(--muted); font-size: .9rem; }
  .grid {
    display: grid;
    gap: 1rem;
    padding: 1rem 1.25rem 1.5rem;
    grid-template-columns: 1.1fr 1fr;
  }
  @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 1rem 1.1rem 1.15rem;
  }
  .panel h2 {
    margin: 0 0 .75rem;
    font-size: .72rem;
    text-transform: uppercase;
    letter-spacing: .14em;
    color: var(--muted);
    font-weight: 600;
  }
  .row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  .row + .row { margin-top: .65rem; }
  button, .btn {
    appearance: none; border: 1px solid var(--line); background: #12171c;
    color: var(--ink); padding: .55rem .9rem; font: inherit; font-weight: 600;
    cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button.ok { border-color: #2f6b4a; color: var(--ok); }
  button.bad { border-color: #7a3530; color: #f0a39c; }
  button.accent { border-color: var(--accent); color: var(--accent); }
  button:disabled { opacity: .45; cursor: not-allowed; }
  .meters {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: .6rem;
  }
  .meter { background: #10151a; border: 1px solid var(--line); padding: .7rem .75rem; }
  .meter .lab { font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
  .meter .val {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 1.65rem; margin-top: .2rem;
  }
  .meter .val.live { color: var(--ok); }
  .meter .val.dead { color: var(--bad); }
  .kv {
    display: grid; grid-template-columns: auto 1fr; gap: .25rem .75rem;
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .82rem;
  }
  .kv span:nth-child(odd) { color: var(--muted); }
  label.cap {
    display: flex; flex-direction: column; gap: .25rem; min-width: 9rem; flex: 1;
    font-size: .8rem; color: var(--muted);
  }
  input[type=range] { width: 100%; }
  .capnum { color: var(--ink); font-family: "IBM Plex Mono", ui-monospace, monospace; }
  #stickWrap {
    position: relative; width: min(280px, 100%); aspect-ratio: 1;
    margin: .5rem auto 0; background: var(--joy); border: 1px solid var(--line);
    touch-action: none; user-select: none;
  }
  #stickBase {
    position: absolute; inset: 12%; border: 1px dashed #33404a; border-radius: 50%;
  }
  #stickKnob {
    position: absolute; width: 56px; height: 56px; margin: -28px 0 0 -28px;
    left: 50%; top: 50%; border-radius: 50%;
    background: #2a3540; border: 2px solid var(--accent);
    box-shadow: 0 0 0 1px #0008;
  }
  .joyread {
    text-align: center; margin-top: .55rem;
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .85rem; color: var(--muted);
  }
  #log {
    height: 9.5rem; overflow: auto; margin: 0;
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .72rem;
    background: #0e1317; border: 1px solid var(--line); padding: .5rem .65rem;
    color: #b7c0c7; white-space: pre-wrap;
  }
  .err { color: var(--bad); min-height: 1.2em; margin-top: .5rem; font-size: .85rem; }
  .hint { color: var(--muted); font-size: .8rem; margin-top: .45rem; line-height: 1.35; }
</style>
</head>
<body>
<header>
  <div>
    <h1>RC test console</h1>
    <div class="sub">Pi ↔ RP2040 · Wi‑Fi bench · default throttle cap 25%</div>
  </div>
  <div class="row">
    <button type="button" id="btnRefresh" class="accent">Refresh STATUS</button>
    <button type="button" id="btnStop" class="bad">STOP</button>
    <button type="button" id="btnReset">RESET</button>
    <button type="button" id="btnManual">MANUAL</button>
  </div>
</header>

<div class="grid">
  <section class="panel">
    <h2>Status</h2>
    <div class="kv" id="statusKv"></div>
    <div class="err" id="err"></div>
  </section>

  <section class="panel">
    <h2>Sonar</h2>
    <div class="row">
      <button type="button" id="btnSonarOn" class="ok">Sonar ON</button>
      <button type="button" id="btnSonarOff" class="bad">Sonar OFF</button>
    </div>
    <div class="meters" style="margin-top:.75rem">
      <div class="meter"><div class="lab">Front GP14/15</div><div class="val dead" id="v-front">—</div></div>
      <div class="meter"><div class="lab">Left GP8/9</div><div class="val dead" id="v-left">—</div></div>
      <div class="meter"><div class="lab">Right GP16/17</div><div class="val dead" id="v-right">—</div></div>
    </div>
  </section>

  <section class="panel">
    <h2>Pull-over</h2>
    <div class="row">
      <button type="button" id="btnPullL" class="accent">PULLOVER LEFT</button>
      <button type="button" id="btnPullR" class="accent">PULLOVER RIGHT</button>
      <button type="button" id="btnPullAbort" class="bad">ABORT</button>
    </div>
    <p class="hint">Takes over even if TX sticks are not centered. Uses front + side sonar. Keep clear / wheels lifted for first runs.</p>
    <div class="row">
      <label class="cap">Side target
        <input type="range" id="poSide" min="5" max="80" value="10"/>
        <span class="capnum"><span id="poSideN">10</span> cm</span>
      </label>
      <label class="cap">Side band ±
        <input type="range" id="poBand" min="1" max="20" value="2"/>
        <span class="capnum"><span id="poBandN">2</span> cm</span>
      </label>
      <label class="cap">Front stop
        <input type="range" id="poFront" min="10" max="100" value="25"/>
        <span class="capnum"><span id="poFrontN">25</span> cm</span>
      </label>
    </div>
    <div class="row">
      <label class="cap">Creep
        <input type="range" id="poCreep" min="5" max="40" value="10"/>
        <span class="capnum"><span id="poCreepN">10</span>%</span>
      </label>
      <label class="cap">Steer max
        <input type="range" id="poSteer" min="5" max="50" value="28"/>
        <span class="capnum"><span id="poSteerN">28</span>%</span>
      </label>
      <label class="cap">Stable hold
        <input type="range" id="poStable" min="100" max="3000" step="50" value="400"/>
        <span class="capnum"><span id="poStableN">400</span> ms</span>
      </label>
      <label class="cap">Timeout
        <input type="range" id="poTimeout" min="3000" max="60000" step="1000" value="15000"/>
        <span class="capnum"><span id="poTimeoutN">15000</span> ms</span>
      </label>
    </div>
    <div class="row">
      <button type="button" id="btnApplyPullCfg" class="accent">Apply pullover params</button>
      <button type="button" id="btnReloadPullCfg">Reload from board</button>
    </div>
  </section>

  <section class="panel">
    <h2>Virtual joystick</h2>
    <div class="row">
      <button type="button" id="btnPiOn" class="ok">Pi control ON</button>
      <button type="button" id="btnPiOff" class="bad">Pi control OFF</button>
    </div>
    <div class="row">
      <label class="cap">Forward cap
        <input type="range" id="capFwd" min="0" max="100" value="25"/>
        <span class="capnum"><span id="capFwdN">25</span>%</span>
      </label>
      <label class="cap">Reverse cap
        <input type="range" id="capRev" min="0" max="100" value="25"/>
        <span class="capnum"><span id="capRevN">25</span>%</span>
      </label>
      <label class="cap">Pulse duration
        <input type="range" id="joyMs" min="80" max="800" step="20" value="280"/>
        <span class="capnum"><span id="joyMsN">280</span> ms</span>
      </label>
    </div>
    <div class="row">
      <button type="button" id="btnApplyCaps" class="accent">Apply caps</button>
      <button type="button" id="btnApplyJoyMs">Apply pulse ms</button>
    </div>
    <div id="stickWrap"><div id="stickBase"></div><div id="stickKnob"></div></div>
    <div class="joyread" id="joyRead">steer 0 · thr 0 · idle</div>
    <p class="hint">Engage Pi control first. Stick sends capped DRIVE pulses (AUTO). Release stick to coast to stop.</p>
  </section>

  <section class="panel" style="grid-column: 1 / -1">
    <h2>Event log</h2>
    <pre id="log"></pre>
  </section>
</div>

<script>
const state = { pi: false, steer: 0, thr: 0, dragging: false, driveTimer: null };

function $(id) { return document.getElementById(id); }
function setErr(msg) { $("err").textContent = msg || ""; }

function fmtCm(cm) {
  if (cm === null || cm === undefined || cm < 0) return "—";
  return cm + " cm";
}
function setMeter(id, cm) {
  const el = $(id);
  el.textContent = fmtCm(cm);
  const live = typeof cm === "number" && cm > 0;
  el.classList.toggle("live", live);
  el.classList.toggle("dead", !live);
}

function syncPullSliders(p) {
  if (!p) return;
  const map = [
    ["poSide", "poSideN", "side"],
    ["poBand", "poBandN", "band"],
    ["poFront", "poFrontN", "front"],
    ["poCreep", "poCreepN", "creep"],
    ["poSteer", "poSteerN", "steer"],
    ["poStable", "poStableN", "stable"],
    ["poTimeout", "poTimeoutN", "timeout"],
  ];
  for (const [id, nid, key] of map) {
    if (p[key] === undefined || p[key] === null) continue;
    if (document.activeElement && document.activeElement.id === id) continue;
    $(id).value = p[key];
    $(nid).textContent = p[key];
  }
}

function render(s) {
  setMeter("v-front", s.front);
  setMeter("v-left", s.left);
  setMeter("v-right", s.right);
  const p = s.pullover || {};
  const kv = [
    ["mode", s.mode],
    ["armed", s.armed ? "1" : "0"],
    ["rcOK", s.rc_ok ? "1" : "0"],
    ["steer in/out", `${s.steer_in}/${s.steer_out}`],
    ["thr in/out", `${s.thr_in}/${s.thr_out}`],
    ["caps F/R", `${s.forward_cap}% / ${s.reverse_cap}%`],
    ["pull side/band", `${p.side ?? "?"} / ±${p.band ?? "?"} cm`],
    ["pull front/creep", `${p.front ?? "?"} cm / ${p.creep ?? "?"}%`],
    ["pull stable/to", `${p.stable ?? "?"} / ${p.timeout ?? "?"} ms`],
    ["joy pulse", (s.joystick_ms ?? "?") + " ms"],
    ["drive", s.drive_active ? "1" : "0"],
    ["sonar", s.sonar_active ? "ON" : "OFF"],
    ["pi control", s.pi_control ? "ON" : "OFF"],
    ["uptime", s.uptime_ms + " ms"],
  ];
  $("statusKv").innerHTML = kv.map(([k,v]) => `<span>${k}</span><span>${v}</span>`).join("");
  syncPullSliders(p);
  if (typeof s.joystick_ms === "number" &&
      !(document.activeElement && document.activeElement.id === "joyMs")) {
    $("joyMs").value = s.joystick_ms;
    $("joyMsN").textContent = s.joystick_ms;
  }
  if (s.log && s.log.length) $("log").textContent = s.log.join("\n");
  if (s.error) setErr(s.error); else if (!s.error) { /* keep last until cleared */ }
  state.pi = !!s.pi_control;
}

async function api(path, opts={}) {
  const r = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? {"Content-Type": "application/json"} : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || data.message || r.statusText);
  render(data);
  return data;
}

async function post(path, body) {
  try {
    setErr("");
    return await api(path, { method: "POST", body: body || {} });
  } catch (e) {
    setErr(e.message);
    throw e;
  }
}

$("btnSonarOn").onclick = () => post("/api/sonar/on");
$("btnSonarOff").onclick = () => post("/api/sonar/off");
$("btnPullL").onclick = () => post("/api/pullover/left");
$("btnPullR").onclick = () => post("/api/pullover/right");
$("btnPullAbort").onclick = () => post("/api/pullover/abort");
$("btnStop").onclick = () => post("/api/stop");
$("btnReset").onclick = () => post("/api/reset");
$("btnManual").onclick = () => post("/api/manual");
$("btnRefresh").onclick = () => post("/api/status");
$("btnPiOn").onclick = () => post("/api/pi/on");
$("btnPiOff").onclick = () => post("/api/pi/off");

function syncCapLabels() {
  $("capFwdN").textContent = $("capFwd").value;
  $("capRevN").textContent = $("capRev").value;
}
$("capFwd").oninput = syncCapLabels;
$("capRev").oninput = syncCapLabels;
$("btnApplyCaps").onclick = () => post("/api/caps", {
  forward: +$("capFwd").value,
  reverse: +$("capRev").value,
});

function bindPullLabel(id, nid) {
  $(id).oninput = () => { $(nid).textContent = $(id).value; };
}
bindPullLabel("poSide", "poSideN");
bindPullLabel("poBand", "poBandN");
bindPullLabel("poFront", "poFrontN");
bindPullLabel("poCreep", "poCreepN");
bindPullLabel("poSteer", "poSteerN");
bindPullLabel("poStable", "poStableN");
bindPullLabel("poTimeout", "poTimeoutN");
$("joyMs").oninput = () => { $("joyMsN").textContent = $("joyMs").value; };

$("btnApplyPullCfg").onclick = () => post("/api/pullover/cfg", {
  side: +$("poSide").value,
  band: +$("poBand").value,
  front: +$("poFront").value,
  creep: +$("poCreep").value,
  steer: +$("poSteer").value,
  stable: +$("poStable").value,
  timeout: +$("poTimeout").value,
});
$("btnReloadPullCfg").onclick = () => post("/api/pullover/cfg/reload");
$("btnApplyJoyMs").onclick = () => post("/api/joystick/ms", {
  duration_ms: +$("joyMs").value,
});

/* ---- joystick ---- */
const wrap = $("stickWrap");
const knob = $("stickKnob");
function joyNorm(clientX, clientY) {
  const r = wrap.getBoundingClientRect();
  const cx = r.left + r.width/2, cy = r.top + r.height/2;
  const max = Math.min(r.width, r.height) * 0.38;
  let dx = clientX - cx, dy = clientY - cy;
  const mag = Math.hypot(dx, dy) || 1;
  if (mag > max) { dx = dx/mag*max; dy = dy/mag*max; }
  knob.style.left = (50 + (dx/r.width)*100) + "%";
  knob.style.top = (50 + (dy/r.height)*100) + "%";
  // x: steer -100..100, y: throttle +forward / -reverse (screen y down)
  const steer = Math.round((dx/max) * 100);
  const thr = Math.round((-dy/max) * 100);
  state.steer = Math.max(-100, Math.min(100, steer));
  state.thr = Math.max(-100, Math.min(100, thr));
  $("joyRead").textContent = `steer ${state.steer} · thr ${state.thr}` + (state.pi ? " · driving" : " · engage Pi control");
}
function joyReset() {
  knob.style.left = "50%"; knob.style.top = "50%";
  state.steer = 0; state.thr = 0; state.dragging = false;
  $("joyRead").textContent = "steer 0 · thr 0 · idle";
  stopDriveLoop();
}
function startDriveLoop() {
  stopDriveLoop();
  const tick = async () => {
    if (!state.pi) return;
    if (Math.abs(state.steer) < 8 && Math.abs(state.thr) < 8) return;
    try {
      await api("/api/drive", {
        method: "POST",
        body: { steer: state.steer, throttle: state.thr, duration_ms: 280 },
      });
    } catch (e) { setErr(e.message); }
  };
  state.driveTimer = setInterval(tick, 150);
  tick();
}
function stopDriveLoop() {
  if (state.driveTimer) { clearInterval(state.driveTimer); state.driveTimer = null; }
}
function onDown(ev) {
  state.dragging = true;
  const t = ev.touches ? ev.touches[0] : ev;
  joyNorm(t.clientX, t.clientY);
  if (state.pi) startDriveLoop();
  ev.preventDefault();
}
function onMove(ev) {
  if (!state.dragging) return;
  const t = ev.touches ? ev.touches[0] : ev;
  joyNorm(t.clientX, t.clientY);
  ev.preventDefault();
}
function onUp() { joyReset(); }
wrap.addEventListener("mousedown", onDown);
window.addEventListener("mousemove", onMove);
window.addEventListener("mouseup", onUp);
wrap.addEventListener("touchstart", onDown, {passive:false});
wrap.addEventListener("touchmove", onMove, {passive:false});
wrap.addEventListener("touchend", onUp);

const es = new EventSource("/api/stream");
es.onmessage = (ev) => { try { render(JSON.parse(ev.data)); } catch(_){} };
es.onerror = () => { $("joyRead").textContent = "stream reconnecting…"; };

post("/api/status").catch(() => {});
syncCapLabels();
</script>
</body>
</html>
"""

app = Flask(__name__)


def _err(exc: Exception, code: int = 500):
    with _lock:
        _state["error"] = str(exc)
    body = _snapshot()
    body["error"] = str(exc)
    return jsonify(body), code


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/health")
def api_health():
    uart_ok = False
    with _client_lock:
        uart_ok = _client is not None and _client._ser is not None and _client._ser.is_open
    return jsonify({"ok": True, "uart": uart_ok, "port": PORT}), 200


@app.get("/api/state")
@app.get("/api/stream")
def api_stream_or_state():
    if request.path.endswith("/state"):
        return jsonify(_snapshot())

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
            time.sleep(0.12)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/status")
def api_status():
    try:
        c = _get_client()
        st = c.status()
        with _lock:
            _state["error"] = None
        _push_log(st.dashboard())
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/sonar/on")
def api_sonar_on():
    try:
        c = _get_client()
        c.sonar_on()
        with _lock:
            _state["sonar_active"] = True
            _state["error"] = None
        _push_log("OK,SONAR,ON")
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/sonar/off")
def api_sonar_off():
    try:
        c = _get_client()
        c.sonar_off()
        with _lock:
            _state["sonar_active"] = False
            _state["front"] = -1
            _state["left"] = -1
            _state["right"] = -1
            _state["error"] = None
        _push_log("OK,SONAR,OFF")
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/caps")
def api_caps():
    try:
        data = request.get_json(force=True, silent=True) or {}
        fwd = int(data.get("forward", DEFAULT_CAP))
        rev = int(data.get("reverse", DEFAULT_CAP))
        fwd = max(0, min(100, fwd))
        rev = max(0, min(100, rev))
        c = _get_client()
        c.set_cap("FORWARD", fwd)
        c.set_cap("REVERSE", rev)
        with _lock:
            _state["forward_cap"] = fwd
            _state["reverse_cap"] = rev
            _state["error"] = None
        _push_log(f"OK,CAP F={fwd} R={rev}")
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/pi/on")
def api_pi_on():
    global _pi_control
    try:
        c = _get_client()
        # leave sonar diag if needed
        try:
            c.sonar_off()
        except Exception:
            pass
        with _lock:
            _state["sonar_active"] = False
        data = request.get_json(force=True, silent=True) or {}
        fwd = int(data.get("forward", _state.get("forward_cap", DEFAULT_CAP)))
        rev = int(data.get("reverse", _state.get("reverse_cap", DEFAULT_CAP)))
        fwd = max(0, min(100, fwd))
        rev = max(0, min(100, rev))
        c.set_cap("FORWARD", fwd)
        c.set_cap("REVERSE", rev)
        _ensure_heartbeat()
        c.mode_auto()
        _pi_control = True
        with _lock:
            _state["forward_cap"] = fwd
            _state["reverse_cap"] = rev
            _state["pi_control"] = True
            _state["error"] = None
        _push_log("OK,AUTO (Pi control)")
        c.status()
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/pi/off")
def api_pi_off():
    global _pi_control
    try:
        c = _get_client()
        c.mode_manual()
        _pi_control = False
        with _lock:
            _state["pi_control"] = False
            _state["error"] = None
        _push_log("OK,MANUAL")
        c.status()
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/drive")
def api_drive():
    """Joystick pulse: steer -100..100, throttle -100..100 (neg=reverse)."""
    try:
        if not _pi_control:
            raise RuntimeError("Pi control is OFF — engage first")
        data = request.get_json(force=True, silent=True) or {}
        steer = int(data.get("steer", 0))
        thr = int(data.get("throttle", 0))
        dur = int(data.get("duration_ms", _joystick_ms))
        steer = max(-100, min(100, steer))
        thr = max(-100, min(100, thr))
        dur = max(50, min(1000, dur))
        if abs(steer) < 8 and abs(thr) < 8:
            return jsonify(_snapshot())
        direction = 1 if thr >= 0 else 2
        c = _get_client()
        _ensure_heartbeat()
        c.drive(direction, steer, dur)
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/joystick/ms")
def api_joystick_ms():
    global _joystick_ms
    try:
        data = request.get_json(force=True, silent=True) or {}
        ms = int(data.get("duration_ms", DEFAULT_JOYSTICK_MS))
        ms = max(80, min(800, ms))
        _joystick_ms = ms
        with _lock:
            _state["joystick_ms"] = ms
            _state["error"] = None
        _push_log(f"OK,JOYSTICK_MS,{ms}")
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


def _apply_pullover_cfg(data: dict[str, Any]) -> dict[str, int]:
    c = _get_client()
    applied: dict[str, int] = {}
    for key in PULLOVER_KEYS:
        if key not in data:
            continue
        lo, hi = PULLOVER_CLAMP[key]
        val = int(data[key])
        val = max(lo, min(hi, val))
        c.pullover_set(PULLOVER_SET_KEY[key], val)
        applied[key] = val
    cfg = c.pullover_cfg()
    with _lock:
        _state["pullover"] = cfg
        _state["error"] = None
    return cfg


def _reload_pullover_cfg() -> dict[str, int]:
    c = _get_client()
    cfg = c.pullover_cfg()
    with _lock:
        _state["pullover"] = cfg
        _state["error"] = None
    return cfg


@app.post("/api/pullover/cfg")
def api_pullover_cfg():
    try:
        data = request.get_json(force=True, silent=True) or {}
        cfg = _apply_pullover_cfg(data)
        _push_log(
            "OK,PULLOVER,CFG,"
            f"{cfg['side']},{cfg['band']},{cfg['front']},"
            f"{cfg['creep']},{cfg['steer']},{cfg['stable']},{cfg['timeout']}"
        )
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/pullover/cfg/reload")
def api_pullover_cfg_reload():
    try:
        cfg = _reload_pullover_cfg()
        _push_log(
            "OK,PULLOVER,CFG,"
            f"{cfg['side']},{cfg['band']},{cfg['front']},"
            f"{cfg['creep']},{cfg['steer']},{cfg['stable']},{cfg['timeout']}"
        )
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/pullover/left")
@app.post("/api/pullover/right")
@app.post("/api/pullover/abort")
def api_pullover():
    global _pi_control
    try:
        c = _get_client()
        try:
            c.sonar_off()
        except Exception:
            pass
        with _lock:
            _state["sonar_active"] = False
        _ensure_heartbeat()
        path = request.path
        if path.endswith("/left"):
            # pullover seizes control itself; heartbeat still required
            msg = c.pullover_left()
            _pi_control = False
        elif path.endswith("/right"):
            msg = c.pullover_right()
            _pi_control = False
        else:
            msg = c.pullover_abort()
        _push_log(msg)
        with _lock:
            _state["error"] = None
            _state["pi_control"] = _pi_control
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/stop")
def api_stop():
    global _pi_control
    try:
        c = _get_client()
        msg = c.stop()
        _pi_control = False
        with _lock:
            _state["pi_control"] = False
            _state["error"] = None
        _push_log(msg)
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/reset")
def api_reset():
    try:
        c = _get_client()
        msg = c.reset()
        with _lock:
            _state["error"] = None
        _push_log(msg)
        c.status()
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/manual")
def api_manual():
    global _pi_control
    try:
        c = _get_client()
        msg = c.mode_manual()
        _pi_control = False
        with _lock:
            _state["pi_control"] = False
            _state["error"] = None
        _push_log(msg)
        c.status()
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


def main() -> None:
    try:
        _get_client()
        _start_status_poller()
        try:
            _reload_pullover_cfg()
            print("Pullover CFG loaded from board.")
        except Exception as exc:
            print(f"WARN: PULLOVER,CFG? failed: {exc}", file=sys.stderr)
        print(f"UART open. UI: http://0.0.0.0:{PORT}/")
    except Exception as exc:
        print(f"WARN: UART not open yet: {exc}", file=sys.stderr)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
