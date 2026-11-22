#!/usr/bin/env python3
"""Run arrow detection on all images in a folder; write annotated outputs."""

from __future__ import annotations

import os
import sys

import cv2

# Allow running from repo root or scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from detect_arrow import annotate, detect_arrow  # noqa: E402


def main() -> int:
    images_dir = os.path.join(ROOT, "images")
    out_dir = os.path.join(ROOT, "images", "out")
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(
        f
        for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        and not f.lower().startswith("det_")
        and not f.lower().startswith("arrow_closeup")
    )
    if not files:
        print(f"No images in {images_dir}")
        return 1

    print(f"Processing {len(files)} image(s) from {images_dir}")
    for name in files:
        path = os.path.join(images_dir, name)
        bgr = cv2.imread(path)
        if bgr is None:
            print(f"  FAIL read {name}")
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        det = detect_arrow(rgb, assume_rgb=True)
        annotated = annotate(rgb, det)
        out_path = os.path.join(out_dir, f"det_{name}")
        cv2.imwrite(out_path, cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
        if det.found:
            print(
                f"  {name}: found status={det.status} "
                f"angle={det.angle_deg:.1f} tip={det.tip} -> {out_path}"
            )
        else:
            print(f"  {name}: NOT FOUND -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
