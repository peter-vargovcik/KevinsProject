#!/usr/bin/env python3
"""Debug top white contours for one image."""
import os, sys
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from detect_arrow import _arrow_score, _road_roi_mask, _white_mask  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "images", "03.png")
bgr = cv2.imread(path)
h, w = bgr.shape[:2]
white = cv2.bitwise_and(_white_mask(bgr), _road_roi_mask(h, w))
contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
rows = []
for c in contours:
    area = cv2.contourArea(c)
    if area < 200:
        continue
    x, y, bw, bh = cv2.boundingRect(c)
    M = cv2.moments(c)
    cx = M["m10"] / M["m00"] if M["m00"] else 0
    cy = M["m01"] / M["m00"] if M["m00"] else 0
    s = _arrow_score(c, w, h, bgr)
    rows.append((s, area, bw, bh, cx, cy))
rows.sort(reverse=True)
print(f"image={path} size={w}x{h} contours={len(rows)}")
for i, (s, area, bw, bh, cx, cy) in enumerate(rows[:12]):
    print(f"  #{i} score={s:.1f} area={area:.0f} box={bw}x{bh} c=({cx:.0f},{cy:.0f})")
