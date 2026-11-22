#!/usr/bin/env python3
"""
Live CSI camera → Teachable Machine TFLite → RGB LEDs.

  Green  GPIO21  — class "correct"
  Yellow GPIO16  — class "none" / low confidence
  Red    GPIO20  — class "wrong"

Place model.tflite + labels.txt in models/teachable/ (see that folder's README).

Usage (on the Pi):
  source ~/arrow-env/bin/activate
  cd ~/KevinsProject
  python src/live_arrow_tflite.py --stream
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

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
from detect_arrow import WrongWayDebouncer  # noqa: E402
from tflite_arrow import TeachableArrowModel  # noqa: E402

# BCM pins (wired on the Pi)
LED_GREEN = 21
LED_YELLOW = 16
LED_RED = 20
STREAM_PORT = 8080
CONFIDENCE_THRESHOLD = 0.60

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = _PROJECT_ROOT / "models" / "teachable"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live TFLite arrow classification → RGB LEDs")
    p.add_argument(
        "--stream",
        action="store_true",
        help=f"MJPEG preview at http://<pi-ip>:{STREAM_PORT}/",
    )
    p.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help=f"Folder with model.tflite + labels.txt (default: {DEFAULT_MODEL_DIR})",
    )
    p.add_argument(
        "--confidence",
        type=float,
        default=CONFIDENCE_THRESHOLD,
        help=f"Min confidence to accept a class (default: {CONFIDENCE_THRESHOLD})",
    )
    return p.parse_args()


def set_leds(green: LED, yellow: LED, red: LED, mode: str) -> None:
    """mode: green | yellow | red"""
    green.value = mode == "green"
    yellow.value = mode == "yellow"
    red.value = mode == "red"


def normalize_status(label: str, confidence: float, threshold: float) -> str:
    """Map model label + confidence to correct | wrong | none."""
    if confidence < threshold:
        return "none"
    key = label.strip().lower()
    if key in ("correct", "wrong", "none"):
        return key
    # Allow common aliases
    if key in ("ok", "right", "good"):
        return "correct"
    if key in ("bad", "wrongway", "wrong_way"):
        return "wrong"
    if key in ("empty", "unknown", "background", "bg"):
        return "none"
    return "none"


def main() -> int:
    args = parse_args()

    try:
        model = TeachableArrowModel(args.model_dir)
    except (FileNotFoundError, ImportError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

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

    wrong_deb = WrongWayDebouncer(WRONG_WAY_DEBOUNCE_FRAMES, CORRECT_DEBOUNCE_FRAMES)
    correct_streak = 0
    none_streak = 0
    mode = "yellow"

    print("Live TFLite arrow LEDs (Ctrl+C to stop)")
    print(f"  model={args.model_dir}")
    print(f"  labels={model.labels}")
    print(f"  green=GPIO{LED_GREEN}  yellow=GPIO{LED_YELLOW}  red=GPIO{LED_RED}")
    print(f"  confidence>={args.confidence}")

    frame_i = 0

    try:
        while True:
            frame = picam2.capture_array()
            frame_i += 1

            if PROCESS_EVERY_N_FRAMES > 1 and (frame_i % PROCESS_EVERY_N_FRAMES) != 0:
                if stream is not None:
                    stream.update(frame)
                continue

            label, conf = model.predict(frame)
            status = normalize_status(label, conf, args.confidence)

            if status == "none":
                none_streak += 1
                correct_streak = 0
                wrong_deb.update("none")
                if none_streak >= CORRECT_DEBOUNCE_FRAMES:
                    mode = "yellow"
            elif status == "correct":
                none_streak = 0
                correct_streak += 1
                wrong_deb.update("correct")
                if correct_streak >= CORRECT_DEBOUNCE_FRAMES:
                    mode = "green"
            elif status == "wrong":
                none_streak = 0
                correct_streak = 0
                if wrong_deb.update("wrong"):
                    mode = "red"
            else:
                none_streak += 1
                correct_streak = 0
                wrong_deb.update("none")
                if none_streak >= CORRECT_DEBOUNCE_FRAMES:
                    mode = "yellow"

            set_leds(green, yellow, red, mode)

            print(
                f"\rpred={label:12s} conf={conf:5.2f} status={status:8s} LED={mode:6s}",
                end="",
                flush=True,
            )

            if stream is not None:
                bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                color = {"green": (0, 220, 0), "yellow": (0, 220, 220), "red": (0, 0, 255)}[mode]
                cv2.putText(
                    bgr,
                    f"{label} {conf:.2f}",
                    (10, 36),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    color,
                    2,
                )
                cv2.putText(
                    bgr,
                    f"LED {mode}",
                    (10, 72),
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
