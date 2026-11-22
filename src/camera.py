"""CSI camera capture via picamera2 (not cv2.VideoCapture)."""

from __future__ import annotations

from typing import Optional

import numpy as np

from config import FRAME_FORMAT, FRAME_HEIGHT, FRAME_WIDTH


class Camera:
    """Thin wrapper around Picamera2 for headless RGB frames."""

    def __init__(
        self,
        width: int = FRAME_WIDTH,
        height: int = FRAME_HEIGHT,
        pixel_format: str = FRAME_FORMAT,
    ) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise ImportError(
                "picamera2 is not installed. On the Pi run: "
                "sudo apt install -y python3-picamera2"
            ) from exc

        self._picam2 = Picamera2()
        config = self._picam2.create_preview_configuration(
            main={"size": (width, height), "format": pixel_format}
        )
        self._picam2.configure(config)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._picam2.start()
            self._started = True

    def capture(self) -> np.ndarray:
        """Return an RGB888 numpy array (H, W, 3)."""
        if not self._started:
            self.start()
        return self._picam2.capture_array()

    def stop(self) -> None:
        if self._started:
            self._picam2.stop()
            self._started = False

    def close(self) -> None:
        self.stop()
        try:
            self._picam2.close()
        except Exception:
            pass

    def __enter__(self) -> "Camera":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.close()


class MockCamera:
    """Synthetic frames for syntax checks on a laptop without a CSI camera."""

    def __init__(self, width: int = FRAME_WIDTH, height: int = FRAME_HEIGHT) -> None:
        self.width = width
        self.height = height
        self._angle = 90.0

    def start(self) -> None:
        pass

    def capture(self) -> np.ndarray:
        import cv2

        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (40, 40, 40)
        cx, cy = self.width // 2, self.height // 2
        # Draw a simple filled arrow pointing at self._angle
        length = min(self.width, self.height) // 3
        rad = np.deg2rad(self._angle)
        tip = (int(cx + length * np.cos(rad)), int(cy + length * np.sin(rad)))
        base = (int(cx - length * 0.6 * np.cos(rad)), int(cy - length * 0.6 * np.sin(rad)))
        perp = np.array([-np.sin(rad), np.cos(rad)])
        wing = 25
        left = (int(base[0] + wing * perp[0]), int(base[1] + wing * perp[1]))
        right = (int(base[0] - wing * perp[0]), int(base[1] - wing * perp[1]))
        pts = np.array([tip, left, right], np.int32)
        cv2.fillPoly(frame, [pts], (220, 220, 220))
        return frame

    def set_angle(self, degrees: float) -> None:
        self._angle = degrees

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> "MockCamera":
        return self

    def __exit__(self, *args) -> None:
        pass


def open_camera(mock: bool = False) -> Camera | MockCamera:
    if mock:
        return MockCamera()
    return Camera()
