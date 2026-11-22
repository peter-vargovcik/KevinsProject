#!/usr/bin/env python3
"""Print RP2040 UART telemetry every 0.5 s. No arguments needed.

Usage (on the Pi):
  cd ~/KevinsProject
  source ~/arrow-env/bin/activate
  python src/run_telemetry.py

Or:
  chmod +x src/run_telemetry.py
  ./src/run_telemetry.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rp2040_uart import DEFAULT_PORT, Rp2040Client, parse_status  # noqa: E402

INTERVAL_S = 0.5


def on_line(line: str) -> None:
    print(f"RX  {line}", flush=True)
    if line.startswith("STATUS,"):
        try:
            print(f"TEL {parse_status(line).dashboard()}", flush=True)
        except ValueError:
            pass


def main() -> int:
    print(f"Telemetry every {INTERVAL_S}s on {DEFAULT_PORT} (Ctrl+C to stop)")
    try:
        client = Rp2040Client(on_line=on_line)
        client.open()
    except Exception as exc:
        print(f"ERROR opening {DEFAULT_PORT}: {exc}", file=sys.stderr)
        return 1

    try:
        while True:
            try:
                st = client.status()
                print(f"--- {st.dashboard()}", flush=True)
            except TimeoutError as exc:
                print(f"WARN: {exc}", flush=True)
            time.sleep(INTERVAL_S)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
