#!/usr/bin/env python3
import os, sys
import cv2
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from detect_arrow_contrast import _arrow_score, bright_mask, increase_contrast, to_gray

path = sys.argv[1]
bgr = cv2.imread(path)
h, w = bgr.shape[:2]
gray = to_gray(bgr, assume_rgb=False)
contrast = increase_contrast(gray)
mask = bright_mask(contrast, bgr)
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
rows = []
for c in contours:
    area = cv2.contourArea(c)
    if area < 300:
        continue
    x, y, bw, bh = cv2.boundingRect(c)
    M = cv2.moments(c)
    cx = M["m10"] / M["m00"] if M["m00"] else 0
    cy = M["m01"] / M["m00"] if M["m00"] else 0
    s = _arrow_score(c, w, h)
    rows.append((s, area, bw, bh, cx, cy))
rows.sort(reverse=True)
print(f"{path} {w}x{h}")
for i, r in enumerate(rows[:10]):
    print(f"  #{i} score={r[0]:.1f} area={r[1]:.0f} box={r[2]}x{r[3]} c=({r[4]:.0f},{r[5]:.0f})")
