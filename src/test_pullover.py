#!/usr/bin/env python3
"""Request RP2040 pull-over (LEFT or RIGHT) with live telemetry.

Edit SIDE below, or pass left/right interactively when run with no args menu.

Requires BT_project_v5 on the RP2040, HC-SR04 wired (see docs/HC_SR04_Wiring.md),
transmitter on with a live RC link. Pi seizes control even if sticks are not
centered. Keep wheels lifted for first tests.

Usage:
  cd ~/KevinsProject
  source ~/arrow-env/bin/activate
  python src/test_pullover.py
"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rp2040_uart import DEFAULT_PORT, Rp2040Client, parse_status  # noqa: E402

# Change to "left" or "right" for a non-interactive run default
SIDE = "right"
TELEMETRY_INTERVAL_S = 0.5


def on_line(line: str) -> None:
    print(f"RX  {line}", flush=True)
    if line.startswith("STATUS,"):
        try:
            print(f"TEL {parse_status(line).dashboard()}", flush=True)
        except ValueError:
            pass


def telemetry_loop(client: Rp2040Client, stop: threading.Event) -> None:
    while not stop.wait(TELEMETRY_INTERVAL_S):
        try:
            st = client.status()
            print(f"--- {st.dashboard()}", flush=True)
        except Exception as exc:
            print(f"WARN telemetry: {exc}", flush=True)


def main() -> int:
    side = SIDE
    if len(sys.argv) > 1:
        side = sys.argv[1].strip().lower()
    else:
        choice = input(f"Pull-over side [left/right] (default {SIDE}): ").strip().lower()
        if choice in ("left", "right", "l", "r"):
            side = "left" if choice.startswith("l") else "right"

    if side not in ("left", "right"):
        print("SIDE must be left or right", file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"PULLOVER TEST → {side.upper()}")
    print("Sonar on RP2040 only during manoeuvre; Ctrl+C aborts")
    print("=" * 60)

    try:
        client = Rp2040Client(on_line=on_line, timeout_s=2.0)
        client.open()
    except Exception as exc:
        print(f"ERROR opening {DEFAULT_PORT}: {exc}", file=sys.stderr)
        return 1

    tel_stop = threading.Event()
    tel_thread = threading.Thread(
        target=telemetry_loop, args=(client, tel_stop), daemon=True
    )

    try:
        st = client.status()
        print(f"Pre-check: {st.dashboard()}")
        if not st.rc_ok:
            print("ERROR: need rcOK (live receiver link)", file=sys.stderr)
            return 1

        tel_thread.start()
        client.start_heartbeat(0.1)

        if side == "left":
            print(client.pullover_left())
        else:
            print(client.pullover_right())

        print("Waiting for DONE,PULLOVER ...")
        print(client.wait_pullover_done(timeout_s=20.0))
        print("Pull-over complete")
        return 0

    except (TimeoutError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        try:
            client.pullover_abort()
        except Exception:
            try:
                client.stop()
            except Exception:
                pass
        return 1

    except KeyboardInterrupt:
        print("\nAborting...")
        try:
            print(client.pullover_abort())
        except Exception:
            pass
        return 130

    finally:
        tel_stop.set()
        tel_thread.join(timeout=1.0)
        client.stop_heartbeat()
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
