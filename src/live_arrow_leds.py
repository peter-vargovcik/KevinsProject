#!/usr/bin/env python3
"""
Live CSI camera → arrow detection → RGB LEDs.

  Green  GPIO21  — arrow pointing correct way
  Yellow GPIO16  — no arrow / unknown
  Red    GPIO20  — arrow pointing wrong way

Usage (on the Pi):
  source ~/arrow-env/bin/activate
  cd ~/KevinsProject
  python src/live_arrow_leds.py --stream
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
from gpiozero import LED

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (  # noqa: E402
    CORRECT_DEBOUNCE_FRAMES,
    FRAME_FORMAT,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    PROCESS_EVERY_N_FRAMES,
    WRONG_WAY_DEBOUNCE_FRAMES,
)
from detect_arrow_contrast import annotate, detect_arrow  # noqa: E402
from detect_arrow import WrongWayDebouncer  # noqa: E402

# BCM pins (wired on the Pi)
LED_GREEN = 21
LED_YELLOW = 16
LED_RED = 20
STREAM_PORT = 8080


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live arrow detection → RGB LEDs")
    p.add_argument(
        "--stream",
        action="store_true",
        help=f"MJPEG preview at http://<pi-ip>:{STREAM_PORT}/",
    )
    return p.parse_args()


def set_leds(green: LED, yellow: LED, red: LED, mode: str) -> None:
    """mode: green | yellow | red"""
    green.value = mode == "green"
    yellow.value = mode == "yellow"
    red.value = mode == "red"


def main() -> int:
    args = parse_args()

    green = LED(LED_GREEN)
    yellow = LED(LED_YELLOW)
    red = LED(LED_RED)
    set_leds(green, yellow, red, "yellow")

    from picamera2 import Picamera2

    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (FRAME_WIDTH, FRAME_HEIGHT), "format": FRAME_FORMAT}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(0.5)

    stream = None
    if args.stream:
        from stream import MjpegStream

        stream = MjpegStream(port=STREAM_PORT)
        stream.start()
        print(f"Preview: http://192.168.1.152:{STREAM_PORT}/")

    # Reuse wrong-way debouncer; map to three LED states separately
    wrong_deb = WrongWayDebouncer(WRONG_WAY_DEBOUNCE_FRAMES, CORRECT_DEBOUNCE_FRAMES)
    correct_streak = 0
    none_streak = 0
    mode = "yellow"

    print("Live arrow LEDs (Ctrl+C to stop)")
    print(f"  green=GPIO{LED_GREEN}  yellow=GPIO{LED_YELLOW}  red=GPIO{LED_RED}")

    frame_i = 0
    last_mode = ""
    try:
        while True:
            frame = picam2.capture_array()
            frame_i += 1

            if PROCESS_EVERY_N_FRAMES > 1 and (frame_i % PROCESS_EVERY_N_FRAMES) != 0:
                if stream is not None:
                    stream.update(frame)
                continue

            det = detect_arrow(frame, assume_rgb=True)

            if not det.found or det.status == "none":
                none_streak += 1
                correct_streak = 0
                wrong_deb.update("none")
                if none_streak >= CORRECT_DEBOUNCE_FRAMES:
                    mode = "yellow"
            elif det.status == "correct":
                none_streak = 0
                correct_streak += 1
                wrong_deb.update("correct")
                if correct_streak >= CORRECT_DEBOUNCE_FRAMES:
                    mode = "green"
            elif det.status == "wrong":
                none_streak = 0
                correct_streak = 0
                if wrong_deb.update("wrong"):
                    mode = "red"
            else:
                # unknown heading → treat as no clear reading
                none_streak += 1
                correct_streak = 0
                wrong_deb.update("none")
                if none_streak >= CORRECT_DEBOUNCE_FRAMES:
                    mode = "yellow"

            set_leds(green, yellow, red, mode)

            if mode != last_mode or (det.found and det.status):
                angle = f"{det.angle_deg:.0f}" if det.angle_deg is not None else "-"
                print(
                    f"\rstatus={det.status:8s} angle={angle:>5s} LED={mode:6s}",
                    end="",
                    flush=True,
                )
                last_mode = mode

            if stream is not None:
                annotated = annotate(frame, det)
                # Draw LED state on frame
                bgr = cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR)
                color = {"green": (0, 220, 0), "yellow": (0, 220, 220), "red": (0, 0, 255)}[mode]
                cv2.putText(
                    bgr,
                    f"LED {mode}",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    color,
                    2,
                )
                stream.update(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        set_leds(green, yellow, red, "yellow")
        green.close()
        yellow.close()
        red.close()
        picam2.stop()
        picam2.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
