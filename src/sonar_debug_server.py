#!/usr/bin/env python3
"""Comprehensive RP2040 test UI over Wi‑Fi (Flask on the Pi).

Features:
  - Live STATUS + sonar RANGE3
  - Sonar ON/OFF
  - Pull-over LEFT / RIGHT / ABORT + runtime CFG
  - Virtual joystick (MODE,AUTO + CAP + DRIVE pulses)
  - Throttle caps default 25%; joystick pulse ms
  - Status LEDs: green=ready, yellow=detection armed, red=wrong/pullover
  - Armed TFLite detection → consecutive wrong → auto-pullover
  - Armed-only MJPEG preview

  http://<pi-ip>:8088/
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, render_template_string, request

from detection_worker import DETECTION_DEFAULTS, DetectionWorker  # noqa: E402
from rp2040_uart import Rp2040Client, parse_status  # noqa: E402
from status_leds import get_leds  # noqa: E402

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
    "uart_ready": False,
    "last_event": "",
    "log": [],
}
_joystick_ms = DEFAULT_JOYSTICK_MS
_log: Deque[str] = deque(maxlen=LOG_MAX)
_client: Optional[Rp2040Client] = None
_client_lock = threading.Lock()
_cmd_lock = threading.Lock()
_pi_control = False
_hb_started = False
_status_thread: Optional[threading.Thread] = None
_status_stop = threading.Event()
_uart_fail_streak = 0
_leds = get_leds()
_detection: Optional[DetectionWorker] = None


def _get_detection() -> DetectionWorker:
    global _detection
    if _detection is None:
        _detection = DetectionWorker(
            leds=_leds,
            on_pullover=_auto_pullover,
            on_log=_push_log,
        )
    return _detection


def _auto_pullover(side: str) -> None:
    """Called from detection thread when wrong streak hits threshold."""
    side_u = side.strip().upper()
    try:
        with _cmd_lock:
            c = _get_client()
            try:
                c.sonar_off()
            except Exception:
                pass
            _ensure_heartbeat()
            if side_u == "LEFT":
                msg = c.pullover_left()
            else:
                msg = c.pullover_right()
        _push_log(msg)
        # Wait for DONE/ERR in a short background waiter
        threading.Thread(
            target=_wait_auto_pullover_done, args=(c,), daemon=True, name="pull-wait"
        ).start()
    except Exception as exc:
        _push_log(f"ERR,AUTO_PULLOVER,{exc}")
        _get_detection().set_pullover_busy(False)


def _wait_auto_pullover_done(c: Rp2040Client) -> None:
    try:
        # Do not hold _cmd_lock — wait_line only reads the RX queue.
        line = c.wait_pullover_done(timeout_s=20.0)
        _push_log(line)
    except Exception as exc:
        _push_log(f"ERR,PULLOVER_WAIT,{exc}")
    finally:
        _get_detection().mark_pullover_done()


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
        if line.startswith("DONE,PULLOVER") or line.startswith("ERR,PULLOVER"):
            try:
                _get_detection().mark_pullover_done()
            except Exception:
                pass


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
    snap.update(_get_detection().snapshot())
    return snap


def _set_uart_ready(ok: bool) -> None:
    global _uart_fail_streak
    with _lock:
        _state["uart_ready"] = ok
    if ok:
        _uart_fail_streak = 0
        _leds.set_ready(True)
    else:
        _uart_fail_streak += 1
        if _uart_fail_streak >= 3:
            _leds.set_ready(False)


def _status_loop() -> None:
    global _uart_fail_streak
    while not _status_stop.wait(0.5):
        try:
            with _cmd_lock:
                c = _get_client()
                c.status()
            _set_uart_ready(True)
        except Exception:
            _set_uart_ready(False)


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
  .shell { padding: 0.75rem 1.25rem 1.5rem; }
  .status-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(12rem, 16rem);
    gap: .75rem;
    margin-bottom: .75rem;
    align-items: stretch;
  }
  @media (max-width: 900px) {
    .status-row { grid-template-columns: 1fr; }
  }
  .status-strip {
    background: var(--panel);
    border: 1px solid var(--line);
    padding: .65rem .9rem;
    min-width: 0;
  }
  .status-kv {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: .4rem .9rem;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: .82rem;
  }
  @media (max-width: 700px) {
    .status-kv { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  .stat {
    display: flex; flex-direction: column; gap: .12rem;
    min-width: 0;
  }
  .stat .k { color: var(--muted); font-size: .68rem; letter-spacing: .04em; text-transform: uppercase; }
  .stat .v { color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .quick-actions {
    background: var(--panel);
    border: 1px solid var(--line);
    padding: .65rem .75rem;
    display: flex; flex-direction: column; gap: .45rem;
    justify-content: flex-start;
  }
  .quick-actions h2 { margin: 0 0 .15rem; }
  .quick-actions .row { margin-top: 0; }
  .quick-actions button { width: 100%; text-align: center; }
  .tabs {
    display: flex; flex-wrap: wrap; gap: .35rem;
    border-bottom: 1px solid var(--line);
    margin-bottom: .85rem; padding-bottom: .35rem;
  }
  .tabs button.tab {
    border: 1px solid transparent; background: transparent;
    color: var(--muted); padding: .45rem .85rem; font-weight: 600;
  }
  .tabs button.tab:hover { color: var(--ink); border-color: var(--line); }
  .tabs button.tab.active {
    color: var(--accent); border-color: var(--accent); background: #12171c;
  }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .grid {
    display: grid;
    gap: 1rem;
    grid-template-columns: 1.1fr 1fr;
  }
  @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 1rem 1.1rem 1.15rem;
  }
  .panel.full { grid-column: 1 / -1; }
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
  .preview {
    width: 100%; max-width: 640px; aspect-ratio: 4/3; object-fit: contain;
    background: #0a0e12; border: 1px solid var(--line); display: block; margin-top: .6rem;
  }
  .chk { display: flex; align-items: center; gap: .4rem; font-size: .85rem; color: var(--muted); }
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

<div class="shell">
  <div class="status-row">
    <div class="status-strip">
      <div class="status-kv" id="statusKv"></div>
      <div class="err" id="err"></div>
    </div>
    <aside class="quick-actions">
      <h2>Quick actions</h2>
      <button type="button" id="btnPullL" class="accent">PULLOVER LEFT</button>
      <button type="button" id="btnPullR" class="accent">PULLOVER RIGHT</button>
      <button type="button" id="btnPullAbort" class="bad">ABORT</button>
      <button type="button" id="btnDetArm" class="ok">Arm detection</button>
      <button type="button" id="btnDetDisarm" class="bad">Disarm</button>
      <button type="button" id="btnSonarOn" class="ok">Sonar ON</button>
      <button type="button" id="btnSonarOff" class="bad">Sonar OFF</button>
    </aside>
  </div>

  <nav class="tabs" id="tabBar" role="tablist">
    <button type="button" class="tab active" data-tab="overview">Overview</button>
    <button type="button" class="tab" data-tab="pullover">Pullover</button>
    <button type="button" class="tab" data-tab="detection">Detection</button>
    <button type="button" class="tab" data-tab="drive">Drive</button>
    <button type="button" class="tab" data-tab="log">Log</button>
  </nav>

  <div class="tab-panel active" id="tab-overview">
    <div class="grid">
      <section class="panel full">
        <h2>Sonar</h2>
        <div class="meters">
          <div class="meter"><div class="lab">Front GP14/15</div><div class="val dead" id="v-front">—</div></div>
          <div class="meter"><div class="lab">Left GP8/9</div><div class="val dead" id="v-left">—</div></div>
          <div class="meter"><div class="lab">Right GP16/17</div><div class="val dead" id="v-right">—</div></div>
        </div>
        <p class="hint">Pullover / detection tuning live on their tabs. Quick actions stay beside the status strip.</p>
      </section>
    </div>
  </div>

  <div class="tab-panel" id="tab-pullover">
    <div class="grid">
      <section class="panel full">
        <h2>Pull-over</h2>
        <div class="row">
          <button type="button" id="btnPullL2" class="accent">PULLOVER LEFT</button>
          <button type="button" id="btnPullR2" class="accent">PULLOVER RIGHT</button>
          <button type="button" id="btnPullAbort2" class="bad">ABORT</button>
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
    </div>
  </div>

  <div class="tab-panel" id="tab-detection">
    <div class="grid">
      <section class="panel full">
        <h2>Detection / auto-pullover</h2>
        <div class="row">
          <button type="button" id="btnDetArm2" class="ok">Arm detection</button>
          <button type="button" id="btnDetDisarm2" class="bad">Disarm</button>
        </div>
        <p class="hint">Green = ready · Yellow = armed · Red = wrong/pullover. Consecutive <code>wrong</code> fires pullover. Do not run live_arrow_* while this owns the LEDs.</p>
        <div class="row">
          <label class="cap">Wrong streak N
            <input type="range" id="detStreak" min="2" max="30" value="5"/>
            <span class="capnum"><span id="detStreakN">5</span></span>
          </label>
          <label class="cap">Confidence min
            <input type="range" id="detConf" min="30" max="95" value="60"/>
            <span class="capnum"><span id="detConfN">0.60</span></span>
          </label>
          <label class="cap">Cooldownoldown
            <input type="range" id="detCool" min="3000" max="120000" step="1000" value="15000"/>
            <span class="capnum"><span id="detCoolN">15000</span> ms</span>
          </label>
          <label class="cap">Process every N
            <input type="range" id="detEvery" min="1" max="10" value="2"/>
            <span class="capnum"><span id="detEveryN">2</span></span>
          </label>
          <label class="cap">JPEG quality
            <input type="range" id="detJpeg" min="40" max="85" value="65"/>
            <span class="capnum"><span id="detJpegN">65</span></span>
          </label>
        </div>
        <div class="row">
          <label class="chk"><input type="checkbox" id="detAuto" checked/> Auto-pullover</label>
          <label class="chk"><input type="checkbox" id="detPreview" checked/> Preview</label>
          <label class="chk"><input type="checkbox" id="detNoneReset" checked/> none resets streak</label>
          <label class="chk"><input type="checkbox" id="detCorrectReset" checked/> correct resets streak</label>
          <label class="chk"><input type="checkbox" id="detDisarmAfter"/> Disarm after pullover</label>
          <label class="cap" style="min-width:7rem;flex:0">Side
            <select id="detSide" style="background:#12171c;color:var(--ink);border:1px solid var(--line);padding:.35rem">
              <option value="RIGHT" selected>RIGHT</option>
              <option value="LEFT">LEFT</option>
            </select>
          </label>
        </div>
        <div class="row">
          <button type="button" id="btnDetCfg" class="accent">Apply detection cfg</button>
        </div>
        <img id="detPreviewImg" class="preview" alt="detection preview (armed only)" src=""/>
      </section>
    </div>
  </div>

  <div class="tab-panel" id="tab-drive">
    <div class="grid">
      <section class="panel full">
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
    </div>
  </div>

  <div class="tab-panel" id="tab-log">
    <section class="panel">
      <h2>Event log</h2>
      <pre id="log"></pre>
    </section>
  </div>
</div>

<script>
const state = { pi: false, steer: 0, thr: 0, dragging: false, driveTimer: null };

function $(id) { return document.getElementById(id); }
function setErr(msg) { $("err").textContent = msg || ""; }

function showTab(name) {
  document.querySelectorAll(".tabs .tab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach(p => {
    p.classList.toggle("active", p.id === "tab-" + name);
  });
  try { localStorage.setItem("rcTab", name); } catch (e) {}
}
document.querySelectorAll(".tabs .tab").forEach(btn => {
  btn.onclick = () => showTab(btn.dataset.tab);
});
try {
  const saved = localStorage.getItem("rcTab");
  if (saved && $("tab-" + saved)) showTab(saved);
} catch (e) {}

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
    ["uart ready", s.uart_ready ? "1" : "0"],
    ["detect", s.detection_armed ? "ARMED" : "off"],
    ["pred", `${s.pred_label || "—"} ${(s.pred_conf||0).toFixed?.(2) ?? s.pred_conf} [${s.pred_status||"—"}]`],
    ["wrong streak", `${s.wrong_streak ?? 0} / ${(s.detection_cfg||{}).wrong_streak_n ?? "?"}`],
    ["cool left", (s.cooldown_remaining_ms ?? 0) + " ms"],
    ["pi control", s.pi_control ? "ON" : "OFF"],
    ["uptime", s.uptime_ms + " ms"],
  ];
  $("statusKv").innerHTML = kv.map(([k,v]) =>
    `<div class="stat"><span class="k">${k}</span><span class="v">${v}</span></div>`
  ).join("");
  syncPullSliders(p);
  syncDetCfg(s.detection_cfg);
  const img = $("detPreviewImg");
  if (s.detection_armed && s.preview_enable) {
    if (!img.dataset.live) {
      img.dataset.live = "1";
      img.src = "/api/detection/mjpeg?t=" + Date.now();
    }
  } else {
    img.dataset.live = "";
    img.removeAttribute("src");
  }
  if (typeof s.joystick_ms === "number" &&
      !(document.activeElement && document.activeElement.id === "joyMs")) {
    $("joyMs").value = s.joystick_ms;
    $("joyMsN").textContent = s.joystick_ms;
  }
  if (s.log && s.log.length) $("log").textContent = s.log.join("\n");
  if (s.error) setErr(s.error); else if (!s.error) { /* keep last until cleared */ }
  if (s.detection_error) setErr(s.detection_error);
  state.pi = !!s.pi_control;
}

function syncDetCfg(c) {
  if (!c) return;
  const skip = document.activeElement && document.activeElement.id;
  const set = (id, nid, val, fmt) => {
    if (val === undefined || val === null) return;
    if (skip === id) return;
    $(id).value = val;
    if (nid) $(nid).textContent = fmt ? fmt(val) : val;
  };
  set("detStreak", "detStreakN", c.wrong_streak_n);
  if (c.confidence_min !== undefined && skip !== "detConf") {
    $("detConf").value = Math.round(c.confidence_min * 100);
    $("detConfN").textContent = Number(c.confidence_min).toFixed(2);
  }
  set("detCool", "detCoolN", c.cooldown_ms);
  set("detEvery", "detEveryN", c.process_every_n);
  set("detJpeg", "detJpegN", c.jpeg_quality);
  if (skip !== "detSide" && c.pullover_side) $("detSide").value = c.pullover_side;
  if (skip !== "detAuto") $("detAuto").checked = !!c.auto_pullover_enable;
  if (skip !== "detPreview") $("detPreview").checked = !!c.preview_enable;
  if (skip !== "detNoneReset") $("detNoneReset").checked = !!c.none_resets_streak;
  if (skip !== "detCorrectReset") $("detCorrectReset").checked = !!c.correct_resets_streak;
  if (skip !== "detDisarmAfter") $("detDisarmAfter").checked = !!c.disarm_after_pullover;
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
const pullL = () => post("/api/pullover/left");
const pullR = () => post("/api/pullover/right");
const pullAbort = () => post("/api/pullover/abort");
$("btnPullL").onclick = pullL;
$("btnPullR").onclick = pullR;
$("btnPullAbort").onclick = pullAbort;
$("btnPullL2").onclick = pullL;
$("btnPullR2").onclick = pullR;
$("btnPullAbort2").onclick = pullAbort;
$("btnStop").onclick = () => post("/api/stop");
$("btnReset").onclick = () => post("/api/reset");
$("btnManual").onclick = () => post("/api/manual");
$("btnRefresh").onclick = () => post("/api/status");
$("btnPiOn").onclick = () => post("/api/pi/on");
$("btnPiOff").onclick = () => post("/api/pi/off");
const detArm = () => post("/api/detection/arm");
const detDisarm = () => post("/api/detection/disarm");
$("btnDetArm").onclick = detArm;
$("btnDetDisarm").onclick = detDisarm;
$("btnDetArm2").onclick = detArm;
$("btnDetDisarm2").onclick = detDisarm;

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

$("detStreak").oninput = () => { $("detStreakN").textContent = $("detStreak").value; };
$("detConf").oninput = () => { $("detConfN").textContent = (+$("detConf").value/100).toFixed(2); };
$("detCool").oninput = () => { $("detCoolN").textContent = $("detCool").value; };
$("detEvery").oninput = () => { $("detEveryN").textContent = $("detEvery").value; };
$("detJpeg").oninput = () => { $("detJpegN").textContent = $("detJpeg").value; };

$("btnDetCfg").onclick = () => post("/api/detection/cfg", {
  wrong_streak_n: +$("detStreak").value,
  confidence_min: +$("detConf").value / 100,
  cooldown_ms: +$("detCool").value,
  process_every_n: +$("detEvery").value,
  jpeg_quality: +$("detJpeg").value,
  pullover_side: $("detSide").value,
  auto_pullover_enable: $("detAuto").checked,
  preview_enable: $("detPreview").checked,
  none_resets_streak: $("detNoneReset").checked,
  correct_resets_streak: $("detCorrectReset").checked,
  disarm_after_pullover: $("detDisarmAfter").checked,
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


@app.post("/api/detection/arm")
def api_detection_arm():
    try:
        if not _state.get("uart_ready"):
            # still allow arm if client opens
            _get_client()
        _get_detection().arm()
        _leds.set_armed(True)
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/detection/disarm")
def api_detection_disarm():
    try:
        _get_detection().disarm()
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.post("/api/detection/cfg")
def api_detection_cfg():
    try:
        data = request.get_json(force=True, silent=True) or {}
        cfg = _get_detection().update_cfg(data)
        _push_log(f"OK,DETECTION,CFG,streak={cfg['wrong_streak_n']},side={cfg['pullover_side']}")
        return jsonify(_snapshot())
    except Exception as exc:
        return _err(exc)


@app.get("/api/detection/mjpeg")
def api_detection_mjpeg():
    det = _get_detection()

    def generate():
        while True:
            if not det.armed:
                break
            cfg = det.get_cfg()
            if not cfg.get("preview_enable", True):
                time.sleep(0.2)
                continue
            frame = det.get_jpeg()
            if frame is None:
                time.sleep(0.05)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
            time.sleep(0.05)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/pullover/left")
@app.post("/api/pullover/right")
@app.post("/api/pullover/abort")
def api_pullover():
    global _pi_control
    try:
        with _cmd_lock:
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
                msg = c.pullover_left()
                _pi_control = False
            elif path.endswith("/right"):
                msg = c.pullover_right()
                _pi_control = False
            else:
                msg = c.pullover_abort()
                _get_detection().set_pullover_busy(False)
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


def _shutdown(*_args: Any) -> None:
    try:
        if _detection is not None:
            _detection.disarm()
    except Exception:
        pass
    try:
        _leds.close()
    except Exception:
        pass


def main() -> None:
    atexit.register(_shutdown)
    signal.signal(signal.SIGTERM, lambda *_: (_shutdown(), sys.exit(0)))
    try:
        signal.signal(signal.SIGINT, lambda *_: (_shutdown(), sys.exit(0)))
    except Exception:
        pass

    try:
        _get_client()
        _set_uart_ready(True)
        _start_status_poller()
        try:
            _reload_pullover_cfg()
            print("Pullover CFG loaded from board.")
        except Exception as exc:
            print(f"WARN: PULLOVER,CFG? failed: {exc}", file=sys.stderr)
        print(f"UART open. UI: http://0.0.0.0:{PORT}/")
        print("LEDs: green=ready yellow=armed red=wrong/pullover")
    except Exception as exc:
        _set_uart_ready(False)
        print(f"WARN: UART not open yet: {exc}", file=sys.stderr)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
