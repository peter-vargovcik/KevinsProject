# Wrong-way arrow detection — Raspberry Pi 4

Prototype that watches a CSI camera for a directional arrow. If the arrow points the **wrong way** (opposite the configured correct heading), a GPIO LED turns on.

Target hardware: **Raspberry Pi 4 Model B** + ribbon CSI camera (OV5647). Uses classical OpenCV for a light prototype (still fine on Pi 4; YOLO is optional later).

## Stack

| Piece | Choice |
|-------|--------|
| OS | Raspberry Pi OS (Debian trixie / Bookworm), headless OK |
| Camera | `picamera2` (apt) — required for CSI; do not use `cv2.VideoCapture` |
| Vision | `python3-opencv` (apt) |
| LED | `gpiozero` on BCM **GPIO17** (configurable) |
| Debug | MJPEG stream on port **8080** (view from laptop browser) |

## Wiring (LED)

```
GPIO17 (BCM) → 220Ω resistor → LED anode (+)
LED cathode (−) → GND
```

Change the pin in [`src/config.py`](src/config.py) (`LED_PIN`).

## One-time Pi setup (SSH)

1. Flash Bookworm Lite 32-bit with Raspberry Pi Imager. Enable **SSH**, Wi-Fi, and user.
2. SSH in (see [PI.md](PI.md) for this lab’s host/user/key): `ssh pi@192.168.1.152`
3. Confirm camera (no preview):

```bash
rpicam-hello -t 2000 -n
rpicam-still -n -o /tmp/test.jpg
```

4. Copy this repo to the Pi (from your Windows laptop):

```powershell
.\scripts\deploy.ps1 -PiHost 192.168.1.152 -PiUser pi
```

5. On the Pi, run the setup script:

```bash
cd ~/KevinsProject
chmod +x scripts/setup_pi.sh
./scripts/setup_pi.sh
```

## Run

```bash
bash ~/KevinsProject/scripts/start_stream.sh
# or:
source ~/arrow-env/bin/activate
cd ~/KevinsProject
python src/main.py --stream
```

On the laptop, open: http://192.168.1.152:8080/

You should see the live frame with contour, tip arrow, angle, and `correct` / `wrong` / `unknown`.

Without the stream:

```bash
python src/main.py
```

### Laptop smoke test (no Pi hardware)

Needs OpenCV installed locally (`pip install opencv-python`):

```bash
cd src
python main.py --mock
python main.py --mock --mock-wrong
```

## Calibrating direction

In [`src/config.py`](src/config.py):

- `EXPECTED_CORRECT_DEG` — heading that means “driving the right way” (0=right, 90=down, 180=left, −90=up).
- `CORRECT_TOLERANCE_DEG` / `WRONG_WAY_TOLERANCE_DEG` — cones around correct vs opposite.
- Debounce counts avoid LED flicker.

Point a printed high-contrast arrow at the camera, note the angle on the overlay, then set `EXPECTED_CORRECT_DEG` to that value for “correct.” Flip the arrow 180° — LED should turn on after a few frames.

## Project layout

```
src/config.py         # pins, angles, thresholds
src/camera.py         # picamera2 (+ mock)
src/detect_arrow.py   # contour → heading → correct/wrong
src/led.py            # gpiozero LED (+ mock)
src/stream.py         # MJPEG debug server
src/main.py           # main loop
scripts/setup_pi.sh   # apt + venv on the Pi
scripts/deploy.ps1    # copy from Windows → Pi over SSH
```

## Notes for Pi 4

- Default capture is **1280×720** in `src/config.py` (raise/lower as needed).
- Use a **printed** demo arrow for classical CV; real outdoor road paint needs ROI filtering or ML (see image tests).
- Always create the venv with `--system-site-packages` so apt `picamera2` / OpenCV are visible.
