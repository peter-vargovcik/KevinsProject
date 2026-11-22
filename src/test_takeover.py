#!/usr/bin/env python3
"""Pi takes control, timed drive with telemetry, then returns TX control.

Sequence (no CLI args):
  1. Save current throttle caps
  2. Start telemetry (STATUS every 0.5 s) + AUTO heartbeat
  3. MODE,AUTO
  4. Set forward cap to 20% (DRIVE power = CAP in firmware); reverse uncapped
  5. DRIVE forward, steer right 70%, for 2 seconds
  6. Wait for DONE,DRIVE
  7. MODE,MANUAL and restore the saved caps

Safety: keep wheels lifted or motor disconnected for first runs.
Transmitter must be on, armed, throttle near neutral before AUTO.

Usage:
  cd ~/KevinsProject
  source ~/arrow-env/bin/activate
  python src/test_takeover.py
"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rp2040_uart import DEFAULT_PORT, Rp2040Client, parse_status  # noqa: E402

TELEMETRY_INTERVAL_S = 0.5
FORWARD_POWER_PCT = 20
STEER_RIGHT_PCT = 70
DRIVE_MS = 2000


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


def restore_caps(client: Rp2040Client, forward: int, reverse: int) -> None:
    print(f"Restoring caps FORWARD={forward} REVERSE={reverse}")
    print(client.set_cap("FORWARD", forward))
    print(client.set_cap("REVERSE", reverse))


def main() -> int:
    print("=" * 60)
    print("TAKEOVER TEST")
    print(f"  forward {FORWARD_POWER_PCT}% power, right {STEER_RIGHT_PCT}%, {DRIVE_MS} ms")
    print(f"  telemetry every {TELEMETRY_INTERVAL_S}s")
    print("=" * 60)

    try:
        client = Rp2040Client(on_line=on_line, timeout_s=2.0)
        client.open()
    except Exception as exc:
        print(f"ERROR opening {DEFAULT_PORT}: {exc}", file=sys.stderr)
        return 1

    tel_stop = threading.Event()
    tel_thread: threading.Thread | None = None
    saved_fwd = 20
    saved_rev = 25

    try:
        st = client.status()
        saved_fwd = st.forward_cap
        saved_rev = st.reverse_cap
        print(f"Saved TX caps: FORWARD={saved_fwd} REVERSE={saved_rev}")
        print(f"Pre-check: {st.dashboard()}")

        if not st.rc_ok:
            print("ERROR: receiver not OK — turn on transmitter", file=sys.stderr)
            return 1
        if not st.armed:
            print(
                "ERROR: not armed — hold throttle neutral ~1.5s until armed",
                file=sys.stderr,
            )
            return 1

        # Live telemetry for the whole takeover window
        tel_thread = threading.Thread(
            target=telemetry_loop,
            args=(client, tel_stop),
            name="telemetry",
            daemon=True,
        )
        tel_thread.start()

        print("Starting AUTO heartbeat (PING every 100 ms)")
        client.start_heartbeat(0.1)

        print("Pi taking control: MODE,AUTO")
        print(client.mode_auto())

        # Remove TX speed caps while Pi owns control (firmware: DRIVE power = CAP).
        print("Removing TX caps (FORWARD=100 REVERSE=100)")
        print(client.set_cap("FORWARD", 100))
        print(client.set_cap("REVERSE", 100))

        # Set forward power for this manoeuvre (20%); reverse stays uncapped.
        print(f"Manoeuvre forward power: CAP FORWARD={FORWARD_POWER_PCT}")
        print(client.set_cap("FORWARD", FORWARD_POWER_PCT))

        print(
            f"DRIVE forward, right {STEER_RIGHT_PCT}%, {DRIVE_MS} ms"
        )
        print(client.drive(1, STEER_RIGHT_PCT, DRIVE_MS))

        # Wait for RP2040 to finish timed manoeuvre (async DONE,DRIVE)
        try:
            done = client.wait_line(
                prefix="DONE,DRIVE",
                timeout_s=(DRIVE_MS / 1000.0) + 2.0,
            )
            print(f"Manoeuvre finished: {done}")
        except TimeoutError:
            print("WARN: no DONE,DRIVE — sending STOP")
            try:
                print(client.stop())
            except Exception as exc:
                print(f"WARN STOP: {exc}")

        print("Returning control to transmitter: MODE,MANUAL")
        print(client.mode_manual())
        restore_caps(client, saved_fwd, saved_rev)

        print("Takeover test complete")
        return 0

    except (TimeoutError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        try:
            client.start_heartbeat(0.1)
            client.mode_manual()
        except Exception:
            pass
        try:
            restore_caps(client, saved_fwd, saved_rev)
        except Exception as restore_exc:
            print(f"WARN restore caps: {restore_exc}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        print("\nInterrupted — returning MANUAL and restoring caps")
        try:
            client.mode_manual()
            restore_caps(client, saved_fwd, saved_rev)
        except Exception:
            pass
        return 130

    finally:
        tel_stop.set()
        if tel_thread is not None:
            tel_thread.join(timeout=1.0)
        client.stop_heartbeat()
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
