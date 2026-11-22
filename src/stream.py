"""Optional MJPEG debug stream for viewing annotated frames from a laptop browser."""

from __future__ import annotations

import threading
from typing import Optional

import cv2
import numpy as np

from config import JPEG_QUALITY, STREAM_HOST, STREAM_PORT


class MjpegStream:
    """Serves the latest annotated frame at http://<pi-ip>:8080/"""

    def __init__(self, host: str = STREAM_HOST, port: int = STREAM_PORT) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._jpeg: Optional[bytes] = None
        self._thread: Optional[threading.Thread] = None
        self._app = None

    def update(self, frame_rgb: np.ndarray) -> None:
        bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            return
        with self._lock:
            self._jpeg = buf.tobytes()

    def _get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def start(self) -> None:
        try:
            from flask import Flask, Response
        except ImportError as exc:
            raise ImportError(
                "Flask is required for --stream. On the Pi: sudo apt install -y python3-flask"
            ) from exc

        app = Flask(__name__)
        stream = self

        @app.route("/")
        def index():
            return (
                "<html><head><title>Wrong-way arrow</title></head>"
                "<body style='margin:0;background:#111;color:#eee;font-family:sans-serif'>"
                "<h3 style='padding:8px'>Wrong-way arrow debug</h3>"
                "<img src='/video' style='max-width:100%'/>"
                "</body></html>"
            )

        @app.route("/video")
        def video():
            def generate():
                while True:
                    frame = stream._get_jpeg()
                    if frame is None:
                        continue
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )

            return Response(
                generate(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

        self._app = app

        def run():
            app.run(host=self.host, port=self.port, threaded=True, use_reloader=False)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        print(f"[stream] MJPEG at http://<pi-ip>:{self.port}/")
