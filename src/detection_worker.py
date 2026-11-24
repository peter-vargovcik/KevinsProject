"""Armed CSI + TFLite detection worker for the Flask RC console.

While armed: classify frames, maintain wrong streak, optionally encode MJPEG,
and invoke a pullover callback when streak threshold is met.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np

from status_leds import StatusLeds
from tflite_arrow import TeachableArrowModel

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = _PROJECT_ROOT / "models" / "teachable"

DETECTION_DEFAULTS: dict[str, Any] = {
    "wrong_streak_n": 5,
    "confidence_min": 0.60,
    "none_resets_streak": True,
    "correct_resets_streak": True,
    "pullover_side": "RIGHT",
    "auto_pullover_enable": True,
    "cooldown_ms": 15000,
    "disarm_after_pullover": False,
    "process_every_n": 2,
    "frame_width": 640,
    "frame_height": 480,
    "preview_enable": True,
    "jpeg_quality": 65,
}

DETECTION_CLAMP = {
    "wrong_streak_n": (2, 30),
    "confidence_min": (0.30, 0.95),
    "cooldown_ms": (3000, 120000),
    "process_every_n": (1, 10),
    "frame_width": (320, 1280),
    "frame_height": (240, 720),
    "jpeg_quality": (40, 85),
}


def normalize_status(label: str, confidence: float, threshold: float) -> str:
    """Map model label + confidence → correct | wrong | none."""
    if confidence < threshold:
        return "none"
    key = label.strip().lower()
    if key in ("correct", "wrong", "none"):
        return key
    # Quantized Teachable export currently on disk
    if key in ("frwrd", "forward", "ok", "right", "good"):
        return "correct"
    if key in ("rvrs", "reverse", "bad", "wrongway", "wrong_way"):
        return "wrong"
    if key in ("contrl", "control", "empty", "unknown", "background", "bg"):
        return "none"
    return "none"


class DetectionWorker:
    def __init__(
        self,
        leds: StatusLeds,
        on_pullover: Callable[[str], None],
        on_log: Callable[[str], None],
        model_dir: Path = DEFAULT_MODEL_DIR,
    ) -> None:
        self._leds = leds
        self._on_pullover = on_pullover
        self._on_log = on_log
        self._model_dir = Path(model_dir)
        self._cfg = dict(DETECTION_DEFAULTS)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._jpeg: Optional[bytes] = None
        self._armed = False
        self._pullover_busy = False
        self._last_pullover_ms = 0
        self._state = {
            "detection_armed": False,
            "pred_label": "",
            "pred_conf": 0.0,
            "pred_status": "none",
            "wrong_streak": 0,
            "pullover_pending": False,
            "cooldown_remaining_ms": 0,
            "preview_enable": True,
            "detection_error": None,
            "detection_cfg": dict(self._cfg),
        }

    @property
    def armed(self) -> bool:
        return self._armed

    def get_cfg(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._cfg)

    def update_cfg(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for key, (lo, hi) in DETECTION_CLAMP.items():
                if key not in data:
                    continue
                if key == "confidence_min":
                    self._cfg[key] = max(lo, min(hi, float(data[key])))
                else:
                    self._cfg[key] = max(lo, min(hi, int(data[key])))
            for key in (
                "none_resets_streak",
                "correct_resets_streak",
                "auto_pullover_enable",
                "disarm_after_pullover",
                "preview_enable",
            ):
                if key in data:
                    self._cfg[key] = bool(data[key])
            if "pullover_side" in data:
                side = str(data["pullover_side"]).strip().upper()
                if side in ("LEFT", "RIGHT"):
                    self._cfg["pullover_side"] = side
            self._state["detection_cfg"] = dict(self._cfg)
            self._state["preview_enable"] = bool(self._cfg["preview_enable"])
            return dict(self._cfg)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cfg = self._cfg
            cool = 0
            if self._last_pullover_ms:
                elapsed = int(time.time() * 1000) - self._last_pullover_ms
                cool = max(0, int(cfg["cooldown_ms"]) - elapsed)
            out = dict(self._state)
            out["detection_armed"] = self._armed
            out["cooldown_remaining_ms"] = cool
            out["detection_cfg"] = dict(cfg)
            out["preview_enable"] = bool(cfg["preview_enable"])
            return out

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def set_pullover_busy(self, busy: bool) -> None:
        with self._lock:
            self._pullover_busy = busy
            self._state["pullover_pending"] = busy
        self._leds.set_alert(busy or self._state.get("wrong_streak", 0) > 0)

    def mark_pullover_done(self) -> None:
        with self._lock:
            self._pullover_busy = False
            self._state["pullover_pending"] = False
            self._last_pullover_ms = int(time.time() * 1000)
            self._state["wrong_streak"] = 0
            disarm = bool(self._cfg.get("disarm_after_pullover"))
        self._leds.set_alert(False)
        if disarm:
            self.disarm()

    def arm(self) -> None:
        if self._armed:
            return
        if self._thread and self._thread.is_alive():
            self.disarm()
        self._stop.clear()
        self._armed = True
        self._leds.set_armed(True)
        with self._lock:
            self._state["detection_armed"] = True
            self._state["detection_error"] = None
            self._state["wrong_streak"] = 0
        self._thread = threading.Thread(
            target=self._run, name="detection-worker", daemon=True
        )
        self._thread.start()
        self._on_log("OK,DETECTION,ARM")

    def disarm(self) -> None:
        self._armed = False
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3.0)
        self._thread = None
        self._leds.set_armed(False)
        self._leds.set_alert(False)
        with self._lock:
            self._jpeg = None
            self._state["detection_armed"] = False
            self._state["wrong_streak"] = 0
            self._state["pullover_pending"] = False
            self._state["pred_label"] = ""
            self._state["pred_conf"] = 0.0
            self._state["pred_status"] = "none"
        self._on_log("OK,DETECTION,DISARM")

    def _encode_preview(
        self, rgb: np.ndarray, label: str, conf: float, status: str, streak: int, need: int
    ) -> None:
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        color = {
            "correct": (0, 220, 0),
            "wrong": (0, 0, 255),
            "none": (0, 220, 220),
        }.get(status, (200, 200, 200))
        cv2.putText(
            bgr,
            f"{label} {conf:.2f} [{status}]",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
        )
        cv2.putText(
            bgr,
            f"wrong {streak}/{need}",
            (10, 56),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
        )
        q = int(self._cfg["jpeg_quality"])
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if ok:
            with self._lock:
                self._jpeg = buf.tobytes()

    def _run(self) -> None:
        picam2 = None
        try:
            model = TeachableArrowModel(self._model_dir)
            from picamera2 import Picamera2

            with self._lock:
                w = int(self._cfg["frame_width"])
                h = int(self._cfg["frame_height"])
            picam2 = Picamera2()
            config = picam2.create_preview_configuration(
                main={"size": (w, h), "format": "RGB888"}
            )
            picam2.configure(config)
            picam2.start()
            time.sleep(0.4)

            frame_i = 0
            while not self._stop.is_set() and self._armed:
                frame = picam2.capture_array()
                frame_i += 1
                with self._lock:
                    cfg = dict(self._cfg)
                    busy = self._pullover_busy
                every = max(1, int(cfg["process_every_n"]))
                if frame_i % every != 0:
                    time.sleep(0.01)
                    continue

                label, conf = model.predict(frame)
                status = normalize_status(label, conf, float(cfg["confidence_min"]))
                with self._lock:
                    streak = int(self._state["wrong_streak"])
                    if status == "wrong":
                        streak += 1
                    elif status == "correct" and cfg["correct_resets_streak"]:
                        streak = 0
                    elif status == "none" and cfg["none_resets_streak"]:
                        streak = 0
                    self._state["pred_label"] = label
                    self._state["pred_conf"] = float(conf)
                    self._state["pred_status"] = status
                    self._state["wrong_streak"] = streak
                    need = int(cfg["wrong_streak_n"])
                    preview = bool(cfg["preview_enable"])

                alert = busy or (status == "wrong" and streak > 0)
                self._leds.set_alert(alert)

                if preview:
                    self._encode_preview(frame, label, conf, status, streak, need)
                else:
                    with self._lock:
                        self._jpeg = None

                if (
                    not busy
                    and cfg["auto_pullover_enable"]
                    and status == "wrong"
                    and streak >= need
                ):
                    cool_ok = True
                    now_ms = int(time.time() * 1000)
                    with self._lock:
                        if self._last_pullover_ms:
                            cool_ok = (now_ms - self._last_pullover_ms) >= int(
                                cfg["cooldown_ms"]
                            )
                    if cool_ok:
                        side = str(cfg["pullover_side"])
                        with self._lock:
                            self._pullover_busy = True
                            self._state["pullover_pending"] = True
                            self._state["wrong_streak"] = 0
                        self._leds.set_alert(True)
                        self._on_log(f"OK,DETECTION,TRIGGER,{side}")
                        try:
                            self._on_pullover(side)
                        except Exception as exc:
                            self._on_log(f"ERR,DETECTION,PULLOVER,{exc}")
                            self.set_pullover_busy(False)

                time.sleep(0.01)

        except Exception as exc:
            with self._lock:
                self._state["detection_error"] = str(exc)
            self._on_log(f"ERR,DETECTION,{exc}")
        finally:
            if picam2 is not None:
                try:
                    picam2.stop()
                    picam2.close()
                except Exception:
                    pass
            self._armed = False
            self._leds.set_armed(False)
            with self._lock:
                self._state["detection_armed"] = False
                self._jpeg = None
