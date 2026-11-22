#!/usr/bin/env python3
"""
Test grayscale → contrast → arrow detection on images/.

Writes:
  images/out/contrast/det_<name>       annotated color
  images/out/contrast/gray_<name>      grayscale
  images/out/contrast/boost_<name>     contrast-boosted
  images/out/contrast/mask_<name>      bright mask
"""

from __future__ import annotations

import os
import sys

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from detect_arrow_contrast import annotate, detect_arrow  # noqa: E402


def main() -> int:
    images_dir = os.path.join(ROOT, "images")
    out_dir = os.path.join(ROOT, "images", "out", "contrast")
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(
        f
        for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        and not f.lower().startswith("det_")
        and not f.lower().startswith("arrow_")
    )
    if not files:
        print(f"No images in {images_dir}")
        return 1

    print(f"Contrast pipeline on {len(files)} image(s)")
    for name in files:
        path = os.path.join(images_dir, name)
        bgr = cv2.imread(path)
        if bgr is None:
            print(f"  FAIL read {name}")
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        det = detect_arrow(rgb, assume_rgb=True, return_debug=True)
        annotated = annotate(rgb, det)

        stem = os.path.splitext(name)[0]
        cv2.imwrite(os.path.join(out_dir, f"det_{name}"), cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
        if det.gray is not None:
            cv2.imwrite(os.path.join(out_dir, f"gray_{stem}.png"), det.gray)
        if det.contrast is not None:
            cv2.imwrite(os.path.join(out_dir, f"boost_{stem}.png"), det.contrast)
        if det.mask is not None:
            cv2.imwrite(os.path.join(out_dir, f"mask_{stem}.png"), det.mask)

        if det.found:
            print(
                f"  {name}: found status={det.status} "
                f"angle={det.angle_deg:.1f} tip={det.tip}"
            )
        else:
            print(f"  {name}: NOT FOUND")
    print(f"Outputs: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
