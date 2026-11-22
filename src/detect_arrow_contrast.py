"""Arrow detection via grayscale + contrast boost, then bright-blob geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from config import (
    CORRECT_TOLERANCE_DEG,
    EXPECTED_CORRECT_DEG,
    MIN_CONTOUR_AREA,
    WRONG_WAY_TOLERANCE_DEG,
)


@dataclass
class ArrowDetection:
    found: bool
    angle_deg: Optional[float] = None
    centroid: Optional[Tuple[int, int]] = None
    tip: Optional[Tuple[int, int]] = None
    contour: Optional[np.ndarray] = None
    status: str = "none"  # none | correct | wrong | unknown
    gray: Optional[np.ndarray] = None
    contrast: Optional[np.ndarray] = None
    mask: Optional[np.ndarray] = None


def _angle_diff(a: float, b: float) -> float:
    d = (a - b + 180.0) % 360.0 - 180.0
    return abs(d)


def classify_heading(
    angle_deg: float,
    expected_correct: float = EXPECTED_CORRECT_DEG,
    correct_tol: float = CORRECT_TOLERANCE_DEG,
    wrong_tol: float = WRONG_WAY_TOLERANCE_DEG,
) -> str:
    if _angle_diff(angle_deg, expected_correct) <= correct_tol:
        return "correct"
    opposite = (expected_correct + 180.0) % 360.0
    if opposite > 180:
        opposite -= 360.0
    if _angle_diff(angle_deg, opposite) <= wrong_tol:
        return "wrong"
    return "unknown"


def to_gray(frame_bgr_or_rgb: np.ndarray, assume_rgb: bool = True) -> np.ndarray:
    if assume_rgb:
        return cv2.cvtColor(frame_bgr_or_rgb, cv2.COLOR_RGB2GRAY)
    return cv2.cvtColor(frame_bgr_or_rgb, cv2.COLOR_BGR2GRAY)


def increase_contrast(gray: np.ndarray, clip_limit: float = 3.0) -> np.ndarray:
    """CLAHE local contrast boost — helps faded white paint on asphalt."""
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    boosted = clahe.apply(gray)
    # Mild global stretch on top
    lo, hi = np.percentile(boosted, (2, 98))
    if hi <= lo + 1:
        return boosted
    stretched = np.clip((boosted.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255)
    return stretched.astype(np.uint8)


def bright_mask(contrast_gray: np.ndarray, bgr: np.ndarray) -> np.ndarray:
    """Bright regions after contrast boost, limited to low-saturation (paint, not gravel)."""
    blur = cv2.GaussianBlur(contrast_gray, (5, 5), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(np.percentile(blur, 88))
    _, pct = cv2.threshold(blur, thr, 255, cv2.THRESH_BINARY)
    mask = cv2.bitwise_and(otsu, pct)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Keep only unsaturated bright paint (drop yellow dashes + green/gravel)
    low_sat = cv2.inRange(hsv, (0, 0, 0), (180, 55, 255))
    not_yellow = cv2.bitwise_not(cv2.inRange(hsv, (15, 40, 60), (45, 255, 255)))
    mask = cv2.bitwise_and(mask, low_sat)
    mask = cv2.bitwise_and(mask, not_yellow)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


def _end_pointiness(pts: np.ndarray, y0: float, y1: float) -> float:
    band = pts[(pts[:, 1] >= y0) & (pts[:, 1] <= y1)]
    if len(band) < 3:
        return 0.0
    return 1.0 / (float(band[:, 0].std()) + 1.5)


def _tip_from_contour(contour: np.ndarray) -> Tuple[Tuple[int, int], Tuple[int, int], float]:
    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        raise ValueError("empty moments")
    cx = int(moments["m10"] / moments["m00"])
    cy = int(moments["m01"] / moments["m00"])
    x, y, bw, bh = cv2.boundingRect(contour)
    pts = contour.reshape(-1, 2).astype(np.float64)
    top_p = _end_pointiness(pts, y, y + 0.10 * bh)
    bot_p = _end_pointiness(pts, y + 0.90 * bh, y + bh)
    if top_p >= bot_p:
        band = pts[pts[:, 1] <= y + 0.12 * bh]
        order = np.lexsort((np.abs(band[:, 0] - (x + bw * 0.5)), band[:, 1]))
        tip_pt = band[order[0]]
    else:
        band = pts[pts[:, 1] >= y + 0.88 * bh]
        order = np.lexsort((np.abs(band[:, 0] - (x + bw * 0.5)), -band[:, 1]))
        tip_pt = band[order[0]]
    tip = (int(tip_pt[0]), int(tip_pt[1]))
    angle_deg = float(np.degrees(np.arctan2(tip[1] - cy, tip[0] - cx)))
    return (cx, cy), tip, angle_deg


def _arrow_score(contour: np.ndarray, frame_w: int, frame_h: int) -> float:
    area = cv2.contourArea(contour)
    if area < MIN_CONTOUR_AREA:
        return -1.0
    if area > frame_w * frame_h * 0.40:
        return -1.0
    x, y, bw, bh = cv2.boundingRect(contour)
    if min(bw, bh) < 28:
        return -1.0
    aspect = max(bw, bh) / float(min(bw, bh) + 1e-6)
    if aspect > 4.5:
        return -1.0

    peri = cv2.arcLength(contour, True)
    if peri < 1:
        return -1.0
    # Reject jagged glare / noise (smooth arrows have higher compactness)
    compact = float(4.0 * np.pi * area / (peri * peri))
    if compact < 0.14:
        return -1.0

    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    # Real arrows ≈ a few vertices; ceiling glare is a messy polyline
    if len(approx) < 5 or len(approx) > 16:
        return -1.0

    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    if hull_area <= 0:
        return -1.0
    solidity = area / hull_area
    if solidity < 0.45 or solidity > 0.96:
        return -1.0
    extent = area / float(bw * bh + 1e-6)
    if extent < 0.22:
        return -1.0

    pts = contour.reshape(-1, 2).astype(np.float64)
    top_p = _end_pointiness(pts, y, y + 0.10 * bh)
    bot_p = _end_pointiness(pts, y + 0.90 * bh, y + bh)
    tip_p = max(top_p, bot_p)
    other_p = min(top_p, bot_p) + 1e-3
    # Must look pointed on one end (glare blobs are blob-like on both ends)
    if tip_p < 0.12 or (tip_p / other_p) < 1.2:
        return -1.0

    M = cv2.moments(contour)
    if M["m00"] == 0:
        return -1.0
    cx = M["m10"] / M["m00"]
    cy = M["m01"] / M["m00"]
    # Prefer lane center-left; drop right shoulder gravel (cx~0.65 on 03.png)
    if cx < frame_w * 0.15 or cx > frame_w * 0.55:
        return -1.0
    center_x = frame_w * 0.38
    center_y = frame_h * 0.55
    dist_norm = ((cx - center_x) ** 2 + (cy - center_y) ** 2) ** 0.5 / (frame_w * 0.35)
    center_boost = 1.0 / (0.25 + dist_norm)
    score = (area ** 1.05) * (0.4 + 0.6 * solidity) * (0.4 + 0.6 * extent) * center_boost
    score *= (0.5 + 2.0 * compact)  # prefer smoother shapes
    if bh >= bw * 1.05:
        score *= 2.0
    elif bh >= bw * 0.85:
        score *= 1.4
    if bw > bh * 1.4:
        score *= 0.35
    return float(score)

def detect_arrow(
    frame_bgr_or_rgb: np.ndarray,
    assume_rgb: bool = True,
    return_debug: bool = False,
) -> ArrowDetection:
    """
    Pipeline:
      1) grayscale
      2) increase contrast (CLAHE + stretch)
      3) bright threshold → contours → best arrow-like blob → tip heading
    """
    gray = to_gray(frame_bgr_or_rgb, assume_rgb=assume_rgb)
    if assume_rgb:
        bgr = cv2.cvtColor(frame_bgr_or_rgb, cv2.COLOR_RGB2BGR)
    else:
        bgr = frame_bgr_or_rgb
    contrast = increase_contrast(gray)
    mask = bright_mask(contrast, bgr)
    h, w = gray.shape[:2]

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    empty = ArrowDetection(
        found=False,
        gray=gray if return_debug else None,
        contrast=contrast if return_debug else None,
        mask=mask if return_debug else None,
    )
    if not contours:
        return empty

    scored: List[Tuple[float, np.ndarray]] = []
    for c in contours:
        s = _arrow_score(c, w, h)
        if s > 0:
            scored.append((s, c))
    if not scored:
        return empty

    scored.sort(key=lambda t: t[0], reverse=True)
    contour = scored[0][1]
    try:
        centroid, tip, angle_deg = _tip_from_contour(contour)
    except ValueError:
        return empty

    status = classify_heading(angle_deg)
    return ArrowDetection(
        found=True,
        angle_deg=angle_deg,
        centroid=centroid,
        tip=tip,
        contour=contour,
        status=status,
        gray=gray if return_debug else None,
        contrast=contrast if return_debug else None,
        mask=mask if return_debug else None,
    )


def annotate(frame_rgb: np.ndarray, det: ArrowDetection) -> np.ndarray:
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
