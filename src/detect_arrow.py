"""Detect white road-paint arrows and heading; decide correct vs wrong way."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from config import (
    BLUR_KERNEL,
    CORRECT_TOLERANCE_DEG,
    EXPECTED_CORRECT_DEG,
    MIN_CONTOUR_AREA,
    WRONG_WAY_TOLERANCE_DEG,
)


@dataclass
class ArrowDetection:
    found: bool
    angle_deg: Optional[float] = None  # tip direction: 0=right, 90=down, 180=left, -90=up
    centroid: Optional[Tuple[int, int]] = None
    tip: Optional[Tuple[int, int]] = None
    contour: Optional[np.ndarray] = None
    status: str = "none"  # none | correct | wrong | unknown


def _angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two angles in degrees."""
    d = (a - b + 180.0) % 360.0 - 180.0
    return abs(d)


def classify_heading(
    angle_deg: float,
    expected_correct: float = EXPECTED_CORRECT_DEG,
    correct_tol: float = CORRECT_TOLERANCE_DEG,
    wrong_tol: float = WRONG_WAY_TOLERANCE_DEG,
) -> str:
    """Return 'correct', 'wrong', or 'unknown' for a measured heading."""
    if _angle_diff(angle_deg, expected_correct) <= correct_tol:
        return "correct"
    opposite = (expected_correct + 180.0) % 360.0
    if opposite > 180:
        opposite -= 360.0
    if _angle_diff(angle_deg, opposite) <= wrong_tol:
        return "wrong"
    return "unknown"


def _white_mask(bgr: np.ndarray) -> np.ndarray:
    """Mask white road paint; exclude yellow lane dashes."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # White / light gray paint (V floor a bit lower for Pi camera / shade)
    mask_white = cv2.inRange(hsv, (0, 0, 130), (180, 60, 255))
    # Explicitly drop yellow / amber markings (dashed center lines)
    mask_yellow = cv2.inRange(hsv, (15, 50, 80), (45, 255, 255))
    mask = cv2.bitwise_and(mask_white, cv2.bitwise_not(mask_yellow))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


def _road_roi_mask(h: int, w: int) -> np.ndarray:
    """Most of the frame — live top-down cam needs a wide ROI (not just street-view lane)."""
    mask = np.zeros((h, w), dtype=np.uint8)
    y0 = int(h * 0.05)
    x0 = int(w * 0.08)
    x1 = int(w * 0.92)
    mask[y0:, x0:x1] = 255
    return mask


def _mean_saturation(bgr: np.ndarray, contour: np.ndarray) -> float:
    """Average HSV saturation inside the contour (yellow dashes are high-S)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(bgr.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    mean = cv2.mean(hsv, mask=mask)
    return float(mean[1])


def _arrow_score(contour: np.ndarray, frame_w: int, frame_h: int, bgr: np.ndarray) -> float:
    """Higher = more arrow-like white marking (not lane lines / yellow dashes / gore)."""
    area = cv2.contourArea(contour)
    if area < MIN_CONTOUR_AREA:
        return -1.0
    # Live close-up arrows can be large; only reject near-full-frame blobs
    if area > frame_w * frame_h * 0.35:
        return -1.0
    x, y, bw, bh = cv2.boundingRect(contour)
    # Reject thin dashes / short line segments / stripe fragments
    if min(bw, bh) < 30:
        return -1.0
    if bw < 25 or bh < 25:
        return -1.0
    aspect = max(bw, bh) / float(min(bw, bh) + 1e-6)
    if aspect > 4.0:
        return -1.0
    # Yellow / colored paint → reject
    if _mean_saturation(bgr, contour) > 55:
        return -1.0

    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    if hull_area <= 0:
        return -1.0
    solidity = area / hull_area
    if solidity < 0.40 or solidity > 0.98:
        return -1.0
    extent = area / float(bw * bh + 1e-6)
    if extent < 0.22:
        return -1.0

    M = cv2.moments(contour)
    if M["m00"] == 0:
        return -1.0
    cx = M["m10"] / M["m00"]
    cy = M["m01"] / M["m00"]

    # Allow most of the frame horizontally (top-down camera, centered arrow)
    if cx < frame_w * 0.12 or cx > frame_w * 0.88:
        return -1.0

    center_x = frame_w * 0.50
    center_y = frame_h * 0.55
    dist_norm = ((cx - center_x) ** 2 + (cy - center_y) ** 2) ** 0.5 / (frame_w * 0.45)
    center_boost = 1.0 / (0.25 + dist_norm)

    score = (area ** 1.1) * (0.4 + 0.6 * solidity) * (0.4 + 0.6 * extent) * center_boost
    if bh >= bw * 0.75:
        score *= 1.35
    return float(score)

def _end_pointiness(pts: np.ndarray, y0: float, y1: float) -> float:
    """Higher when the band tapers to a point (low x-spread at that end)."""
    band = pts[(pts[:, 1] >= y0) & (pts[:, 1] <= y1)]
    if len(band) < 3:
        return 0.0
    return 1.0 / (float(band[:, 0].std()) + 1.5)


def _tip_from_contour(contour: np.ndarray) -> Tuple[Tuple[int, int], Tuple[int, int], float]:
    """
    Centroid, tip, and tip angle.

    Decide which bbox end is the tip by "pointiness" (x-std in that band),
    then take the extreme point on that end (topmost or bottommost).
    """
    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        raise ValueError("empty moments")
    cx = int(moments["m10"] / moments["m00"])
    cy = int(moments["m01"] / moments["m00"])

    x, y, bw, bh = cv2.boundingRect(contour)
    pts = contour.reshape(-1, 2).astype(np.float64)
    # Thin bands at the extremes — only the apex is pointy; the full head is wide
    top_p = _end_pointiness(pts, y, y + 0.10 * bh)
    bot_p = _end_pointiness(pts, y + 0.90 * bh, y + bh)

    if top_p >= bot_p:
        band = pts[pts[:, 1] <= y + 0.12 * bh]
        # Top tip: highest point, prefer near horizontal center
        order = np.lexsort((np.abs(band[:, 0] - (x + bw * 0.5)), band[:, 1]))
        tip_pt = band[order[0]]
    else:
        band = pts[pts[:, 1] >= y + 0.88 * bh]
        order = np.lexsort((np.abs(band[:, 0] - (x + bw * 0.5)), -band[:, 1]))
        tip_pt = band[order[0]]

    tip = (int(tip_pt[0]), int(tip_pt[1]))
    angle_deg = float(np.degrees(np.arctan2(tip[1] - cy, tip[0] - cx)))
    return (cx, cy), tip, angle_deg


def detect_arrow(frame_bgr_or_rgb: np.ndarray, assume_rgb: bool = True) -> ArrowDetection:
    """
    Find a white road-paint arrow and estimate tip heading.

    Tuned for outdoor asphalt arrows (bright paint on dark road), not printed demos.
    """
    if assume_rgb:
        bgr = cv2.cvtColor(frame_bgr_or_rgb, cv2.COLOR_RGB2BGR)
    else:
        bgr = frame_bgr_or_rgb

    h, w = bgr.shape[:2]
    white = _white_mask(bgr)
    white = cv2.bitwise_and(white, _road_roi_mask(h, w))

    k = BLUR_KERNEL if BLUR_KERNEL % 2 == 1 else BLUR_KERNEL + 1
    white = cv2.GaussianBlur(white, (k, k), 0)
    _, white = cv2.threshold(white, 40, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return ArrowDetection(found=False)

    scored: List[Tuple[float, np.ndarray]] = []
    for c in contours:
        s = _arrow_score(c, w, h, bgr)
        if s > 0:
            scored.append((s, c))
    if not scored:
        return ArrowDetection(found=False)

    scored.sort(key=lambda t: t[0], reverse=True)
    contour = scored[0][1]

    try:
        centroid, tip, angle_deg = _tip_from_contour(contour)
    except ValueError:
        return ArrowDetection(found=False)

    status = classify_heading(angle_deg)
    return ArrowDetection(
        found=True,
        angle_deg=angle_deg,
        centroid=centroid,
        tip=tip,
        contour=contour,
        status=status,
    )


def annotate(frame_rgb: np.ndarray, det: ArrowDetection) -> np.ndarray:
    """Draw detection overlay. OpenCV draws in BGR; convert for encode."""
    out = frame_rgb.copy()
    bgr = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)

    if det.found and det.contour is not None:
        color = {
            "correct": (0, 200, 0),
            "wrong": (0, 0, 255),
            "unknown": (0, 200, 255),
        }.get(det.status, (255, 255, 255))
        cv2.drawContours(bgr, [det.contour], -1, color, 2)
        if det.centroid and det.tip:
            cv2.circle(bgr, det.centroid, 4, (255, 255, 0), -1)
            cv2.arrowedLine(bgr, det.centroid, det.tip, color, 2, tipLength=0.25)
        label = f"{det.status} {det.angle_deg:.0f}deg" if det.angle_deg is not None else det.status
        cv2.putText(bgr, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    else:
        cv2.putText(bgr, "no arrow", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class WrongWayDebouncer:
    """Require consecutive frames before flipping LED state."""

    def __init__(self, wrong_need: int, correct_need: int) -> None:
        self.wrong_need = wrong_need
        self.correct_need = correct_need
        self._wrong_streak = 0
        self._ok_streak = 0
        self.alert = False

    def update(self, status: str) -> bool:
        if status == "wrong":
            self._wrong_streak += 1
            self._ok_streak = 0
            if self._wrong_streak >= self.wrong_need:
                self.alert = True
        elif status == "correct":
            self._ok_streak += 1
            self._wrong_streak = 0
            if self._ok_streak >= self.correct_need:
                self.alert = False
        else:
            self._wrong_streak = 0
            self._ok_streak += 1
            if self._ok_streak >= self.correct_need * 2:
                self.alert = False
        return self.alert
