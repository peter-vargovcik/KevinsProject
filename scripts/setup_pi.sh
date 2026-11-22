#!/usr/bin/env bash
# Run ONCE on the Raspberry Pi Zero 2 WH (Bookworm Lite recommended).
set -euo pipefail

echo "==> Updating apt"
sudo apt update

echo "==> Installing camera, OpenCV, GPIO, Flask (system packages)"
sudo apt install -y \
  python3-picamera2 \
  python3-opencv \
  python3-gpiozero \
  python3-flask \
  python3-venv \
  git

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${HOME}/arrow-env"

echo "==> Creating venv with system site packages at ${VENV_DIR}"
python3 -m venv --system-site-packages "${VENV_DIR}"

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Verifying imports"
python3 - <<'PY'
import cv2
print("opencv", cv2.__version__)
try:
    from picamera2 import Picamera2
    print("picamera2 OK")
except Exception as e:
    print("picamera2:", e)
try:
    import gpiozero
    print("gpiozero OK")
except Exception as e:
    print("gpiozero:", e)
import flask
print("flask", flask.__version__)
PY

echo ""
echo "Camera smoke test (no preview):"
echo "  rpicam-hello -t 2000 -n"
echo "  rpicam-still -n -o /tmp/test.jpg"
echo ""
echo "Activate and run:"
echo "  source ${VENV_DIR}/bin/activate"
echo "  cd ${PROJECT_DIR}"
echo "  python src/main.py --stream"
echo ""
echo "Done."
