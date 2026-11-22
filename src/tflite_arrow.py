"""Teachable Machine TensorFlow Lite image classifier helper."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np


def _load_interpreter(model_path: Path):
    Interpreter = None
    last_err: Exception | None = None
    for mod in (
        "ai_edge_litert.interpreter",
        "tflite_runtime.interpreter",
        "tensorflow.lite.python.interpreter",
    ):
        try:
            Interpreter = __import__(mod, fromlist=["Interpreter"]).Interpreter
            break
        except ImportError as exc:
            last_err = exc
    if Interpreter is None:
        raise ImportError(
            "Need ai-edge-litert (or tflite-runtime / tensorflow). On the Pi: "
            "pip install ai-edge-litert"
        ) from last_err
    interpreter = Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    return interpreter


def _load_labels(labels_path: Path) -> List[str]:
    lines = labels_path.read_text(encoding="utf-8").splitlines()
    labels = [ln.strip() for ln in lines if ln.strip()]
    if not labels:
        raise ValueError(f"No labels found in {labels_path}")
    return labels


class TeachableArrowModel:
    """Load a Teachable Machine TFLite export and classify RGB frames."""

    def __init__(self, model_dir: str | Path) -> None:
        self.model_dir = Path(model_dir)
        model_path = self.model_dir / "model.tflite"
        labels_path = self.model_dir / "labels.txt"

        if not model_path.is_file():
            raise FileNotFoundError(
                f"Missing {model_path}. Export TensorFlow Lite from "
                "Teachable Machine and place model.tflite here."
            )
        if not labels_path.is_file():
            raise FileNotFoundError(
                f"Missing {labels_path}. Place labels.txt next to model.tflite."
            )

        self.labels = _load_labels(labels_path)
        self._interpreter = _load_interpreter(model_path)
        self._input = self._interpreter.get_input_details()[0]
        self._output = self._interpreter.get_output_details()[0]

        shape = self._input["shape"]
        # NHWC: [1, H, W, C]
        self.height = int(shape[1])
        self.width = int(shape[2])
        self._dtype = self._input["dtype"]
        self._scale, self._zero = self._input.get("quantization", (0.0, 0))

    def preprocess(self, rgb: np.ndarray) -> np.ndarray:
        """Resize RGB frame to model input; float32/255 or quantized int8/uint8."""
        img = cv2.resize(rgb, (self.width, self.height), interpolation=cv2.INTER_AREA)
        if self._dtype == np.float32:
            x = img.astype(np.float32) / 255.0
        elif self._dtype == np.uint8:
            x = img.astype(np.uint8)
        elif self._dtype == np.int8:
            # Quantized: map [0,1] float into int8 using input scale/zero_point
            x_f = img.astype(np.float32) / 255.0
            if self._scale and self._scale > 0:
                x = (x_f / self._scale + self._zero).astype(np.int8)
            else:
                x = (x_f * 127.0 - 128.0).astype(np.int8)
        else:
            x = img.astype(self._dtype)
        return np.expand_dims(x, axis=0)

    def predict(self, rgb: np.ndarray) -> Tuple[str, float]:
        """Return (label, confidence) for the top class."""
        inp = self.preprocess(rgb)
        self._interpreter.set_tensor(self._input["index"], inp)
        self._interpreter.invoke()
        out = self._interpreter.get_tensor(self._output["index"])[0]

        out_scale, out_zero = self._output.get("quantization", (0.0, 0))
        if out.dtype != np.float32 and out_scale and out_scale > 0:
            probs = (out.astype(np.float32) - out_zero) * out_scale
        else:
            probs = out.astype(np.float32)

        # Softmax if values look like logits (sum not ~1)
        s = float(np.sum(probs))
        if s <= 0 or abs(s - 1.0) > 0.05:
            e = np.exp(probs - np.max(probs))
            probs = e / np.sum(e)

        idx = int(np.argmax(probs))
        label = self.labels[idx] if idx < len(self.labels) else str(idx)
        # Strip Teachable Machine "N ClassName" prefix if present
        parts = label.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            label = parts[1]
        return label, float(probs[idx])
