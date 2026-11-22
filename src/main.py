#!/usr/bin/env python3
"""Wrong-way arrow detector — run on the Raspberry Pi 4."""

from __future__ import annotations

import argparse
import os
import sys
import time

# Ensure imports work when launched as `python src/main.py` from repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (  # noqa: E402
    CORRECT_DEBOUNCE_FRAMES,
    PROCESS_EVERY_N_FRAMES,
    STREAM_PORT,
    WRONG_WAY_DEBOUNCE_FRAMES,
)
from camera import open_camera  # noqa: E402
from detect_arrow import WrongWayDebouncer, annotate, detect_arrow  # noqa: E402
from led import LedAlert  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wrong-way arrow LED alert (Raspberry Pi 4)")
    p.add_argument(
        "--stream",
        action="store_true",
        help=f"Serve annotated MJPEG at http://<pi-ip>:{STREAM_PORT}/",
    )
    p.add_argument(
        "--mock",
        action="store_true",
        help="Use synthetic camera + mock LED (laptop smoke test)",
    )
    p.add_argument(
        "--mock-wrong",
        action="store_true",
        help="With --mock, draw arrow pointing wrong way",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    debouncer = WrongWayDebouncer(WRONG_WAY_DEBOUNCE_FRAMES, CORRECT_DEBOUNCE_FRAMES)
    led = LedAlert(mock=args.mock)
    camera = open_camera(mock=args.mock)

    stream = None
    if args.stream:
        from stream import MjpegStream

        stream = MjpegStream()
        stream.start()

    if args.mock and hasattr(camera, "set_angle"):
        # Expected correct default is 90° (down); wrong ≈ -90° (up)
        camera.set_angle(-90.0 if args.mock_wrong else 90.0)

    print("[main] starting capture loop (Ctrl+C to stop)")
    frame_i = 0
    last_status = "none"
    last_alert = False

    try:
        camera.start()
        while True:
            frame = camera.capture()
            frame_i += 1

            if PROCESS_EVERY_N_FRAMES > 1 and (frame_i % PROCESS_EVERY_N_FRAMES) != 0:
                if stream is not None:
                    stream.update(frame)
                continue

            det = detect_arrow(frame, assume_rgb=True)
            alert = debouncer.update(det.status if det.found else "none")
            led.set(alert)

            if det.status != last_status or alert != last_alert:
                angle = f"{det.angle_deg:.0f}" if det.angle_deg is not None else "-"
                print(
                    f"[main] status={det.status} angle={angle} "
                    f"LED={'ON' if alert else 'OFF'}"
                )
                last_status = det.status
                last_alert = alert

            if stream is not None:
                stream.update(annotate(frame, det))

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[main] stopped")
    finally:
        led.off()
        led.close()
        camera.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
