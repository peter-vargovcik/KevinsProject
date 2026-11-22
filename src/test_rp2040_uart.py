#!/usr/bin/env python3
"""
Bench / CLI test for RP2040 UART + live telemetry printout.

Safety: keep wheels lifted or motor disconnected for early tests.

Usage (on the Pi):
  source ~/arrow-env/bin/activate
  cd ~/KevinsProject
  python src/test_rp2040_uart.py
  python src/test_rp2040_uart.py --ping
  python src/test_rp2040_uart.py --status
  python src/test_rp2040_uart.py --monitor
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rp2040_uart import (  # noqa: E402
    DEFAULT_BAUD,
    DEFAULT_PORT,
    Rp2040Client,
    parse_status,
)


class TelemetryPrinter:
    """Print raw RX lines and parsed STATUS dashboards."""

    def __init__(self, raw_only: bool = False) -> None:
        self.raw_only = raw_only
        self._lock = __import__("threading").Lock()

    def __call__(self, line: str) -> None:
        with self._lock:
            print(f"RX  {line}", flush=True)
            if self.raw_only:
                return
            if line.startswith("STATUS,"):
                try:
                    st = parse_status(line)
                    print(f"TEL {st.dashboard()}", flush=True)
                except ValueError:
                    pass


def build_client(args: argparse.Namespace) -> Rp2040Client:
    printer = TelemetryPrinter(raw_only=args.raw)
    client = Rp2040Client(
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        on_line=printer,
    )
    client.open()
    return client


def cmd_ping(client: Rp2040Client) -> int:
    uptime = client.ping()
    print(f"PONG uptime_ms={uptime}")
    if client.consume_restart_flag():
        print("NOTE: RP2040 restart detected (uptime dropped)")
    return 0


def cmd_status(client: Rp2040Client) -> int:
    st = client.status()
    print(st.dashboard())
    return 0


def cmd_caps(client: Rp2040Client, forward: int, reverse: int) -> int:
    print(client.set_cap("FORWARD", forward))
    print(client.set_cap("REVERSE", reverse))
    return 0


def cmd_stop(client: Rp2040Client) -> int:
    print(client.stop())
    return 0


def cmd_monitor(client: Rp2040Client, interval_s: float) -> int:
    print(
        f"Monitoring telemetry (STATUS? every {interval_s:.2f}s). Ctrl+C to stop.",
        flush=True,
    )
    try:
        while True:
            try:
                st = client.status()
                # STATUS also printed via on_line; show dashboard once more clearly
                print(f"--- {st.dashboard()}", flush=True)
            except TimeoutError as exc:
                print(f"WARN: {exc}", flush=True)
            if client.consume_restart_flag():
                print("NOTE: RP2040 restart detected", flush=True)
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\nMonitor stopped")
    return 0


def interactive(client: Rp2040Client, interval_s: float) -> int:
    help_text = """
Commands:
  ping                 PING / PONG
  status               STATUS?
  caps <fwd> <rev>     set throttle caps 0..100
  manual               MODE,MANUAL
  auto                 MODE,AUTO (requires armed + neutral)
  drive <dir> <ang> <ms>   DRIVE (dir 1/2, ang -100..100, ms 1..5000)
  stop                 STOP
  reset                RESET (safe conditions required)
  hb on | hb off       heartbeat 100 ms PING
  monitor              live STATUS + async telemetry (Ctrl+C back to menu)
  help
  quit
"""
    print(help_text)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        try:
            if cmd in ("q", "quit", "exit"):
                break
            if cmd == "help":
                print(help_text)
            elif cmd == "ping":
                cmd_ping(client)
            elif cmd == "status":
                cmd_status(client)
            elif cmd == "caps":
                if len(parts) != 3:
                    print("usage: caps <forward> <reverse>")
                    continue
                cmd_caps(client, int(parts[1]), int(parts[2]))
            elif cmd == "manual":
                print(client.mode_manual())
            elif cmd == "auto":
                st = client.latest_status() or client.status()
                if not (st.armed and st.rc_ok):
                    print(
                        f"Refusing AUTO: need armed+rcOK "
                        f"(armed={st.armed} rcOK={st.rc_ok})"
                    )
                    continue
                print(client.mode_auto())
            elif cmd == "drive":
                if len(parts) != 4:
                    print("usage: drive <dir 1|2> <angle> <ms>")
                    continue
                confirm = input(
                    f"Confirm DRIVE {parts[1]},{parts[2]},{parts[3]}? [y/N] "
                ).strip().lower()
                if confirm != "y":
                    print("Cancelled")
                    continue
                print(
                    client.drive(int(parts[1]), int(parts[2]), int(parts[3]))
                )
            elif cmd == "stop":
                cmd_stop(client)
            elif cmd == "reset":
                print(client.reset())
            elif cmd == "hb":
                if len(parts) != 2 or parts[1] not in ("on", "off"):
                    print("usage: hb on | hb off")
                    continue
                if parts[1] == "on":
                    client.start_heartbeat()
                    print("Heartbeat ON (PING every 100 ms)")
                else:
                    client.stop_heartbeat()
                    print("Heartbeat OFF")
            elif cmd == "monitor":
                cmd_monitor(client, interval_s)
            else:
                print(f"Unknown command: {cmd} (type help)")
        except (TimeoutError, RuntimeError, ValueError) as exc:
            print(f"ERROR: {exc}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test RP2040 UART + print live telemetry"
    )
    p.add_argument("--port", default=DEFAULT_PORT, help=f"default {DEFAULT_PORT}")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--timeout", type=float, default=1.0, help="reply timeout seconds")
    p.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="STATUS poll interval for --monitor",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="print raw RX only (skip parsed STATUS dashboard)",
    )
    p.add_argument("--ping", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument(
        "--caps",
        nargs=2,
        type=int,
        metavar=("FWD", "REV"),
        help="set forward and reverse caps",
    )
    p.add_argument("--stop", action="store_true")
    p.add_argument(
        "--monitor",
        action="store_true",
        help="live telemetry: STATUS? + async lines",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    scripted = any(
        [
            args.ping,
            args.status,
            args.caps is not None,
            args.stop,
            args.monitor,
        ]
    )

    try:
        client = build_client(args)
    except Exception as exc:
        print(f"ERROR opening {args.port}: {exc}", file=sys.stderr)
        print(
            "Check: UART enabled (serial login off), wiring TX<->RX + GND, "
            "RP2040 powered, pyserial installed.",
            file=sys.stderr,
        )
        return 1

    try:
        if not scripted:
            return interactive(client, args.interval)
        rc = 0
        if args.ping:
            rc = cmd_ping(client) or rc
        if args.status:
            rc = cmd_status(client) or rc
        if args.caps is not None:
            rc = cmd_caps(client, args.caps[0], args.caps[1]) or rc
        if args.stop:
            rc = cmd_stop(client) or rc
        if args.monitor:
            rc = cmd_monitor(client, args.interval) or rc
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
