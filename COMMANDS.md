# Pi commands

Host: `pi@192.168.1.152` (home). On the school hotspot, use the Pi’s DHCP address from the phone’s hotspot client list.

### Boot Wi‑Fi chooser

On boot, `wifi-chooser.service` prefers the demo hotspot SSID, else the home/dev SSID. While offline it **blinks red (GPIO20)**. Config on the Pi only: `scripts/pi/wifi-chooser.env` (from `wifi-chooser.env.example`; **not in git**).

```
sudo systemctl status wifi-chooser
sudo journalctl -u wifi-chooser -n 50 --no-pager
```  
Project: `/home/pi/KevinsProject`  
Preview (if streaming): http://192.168.1.152:8080/

---

## Connect (from WSL)

```
ssh -i /mnt/c/Users/peter/.ssh/id_ed25519_pi -o IdentitiesOnly=yes pi@192.168.1.152
```

Then on the Pi:

```
cd ~/KevinsProject
source ~/arrow-env/bin/activate
```

---

## Heartbeat / status

```
ping 192.168.1.152
```

On the Pi after SSH:

```
hostname
uptime
date
```

```
pgrep -af live_arrow_tflite.py
```

```
pgrep -af live_arrow_leds.py
```

```
ss -ltn | grep 8080
```

```
tail -30 /tmp/live_arrow_tflite.log
```

```
tail -f /tmp/live_arrow_tflite.log
```

```
rpicam-hello --list-cameras
```

---

## Kill scripts

```
pkill -f live_arrow_tflite.py
```

```
pkill -f live_arrow_leds.py
```

```
pkill -f main.py
```

Force kill if GPIO stays busy:

```
pkill -9 -f live_arrow_tflite.py
pkill -9 -f live_arrow_leds.py
pkill -9 -f main.py
```

---

## Start TFLite (Teachable Machine)

No video stream (better for headless):

```
cd ~/KevinsProject
source ~/arrow-env/bin/activate
python src/live_arrow_tflite.py
```

With video stream:

```
cd ~/KevinsProject
source ~/arrow-env/bin/activate
python src/live_arrow_tflite.py --stream
```

Or use the helper script (starts with stream):

```
bash ~/KevinsProject/scripts/run_live_tflite.sh
```

Restart:

```
pkill -f live_arrow_tflite.py
cd ~/KevinsProject
source ~/arrow-env/bin/activate
python src/live_arrow_tflite.py
```

---

## Start OpenCV contrast + LEDs

```
cd ~/KevinsProject
source ~/arrow-env/bin/activate
python src/live_arrow_leds.py --stream
```

Or:

```
bash ~/KevinsProject/scripts/run_live_leds.sh
```

---

## Sync rule (laptop ↔ Pi)

**This laptop is the source of truth.** Anything that goes onto the Pi must also exist here under `C:\Users\peter\Cursor\KevinsProject`. Prefer editing on the laptop, then deploy. If you edit on the Pi, pull back immediately.

Deploy (laptop → Pi) from PowerShell:

```
.\scripts\deploy.ps1 -PiHost 192.168.1.152 -PiUser pi
```

Pull (Pi → laptop) after on-device edits:

```
.\scripts\pull_from_pi.ps1
```

## Deploy from WSL (laptop → Pi)

Copy code and model:

```
cd /mnt/c/Users/peter/Cursor/KevinsProject
scp -i /mnt/c/Users/peter/.ssh/id_ed25519_pi -o IdentitiesOnly=yes -r src scripts models docs COMMANDS.md PI.md CONTEXT.md requirements-pi.txt README.md pi@192.168.1.152:~/KevinsProject/
```

Pull from Pi (WSL):

```
cd /mnt/c/Users/peter/Cursor/KevinsProject
scp -i /mnt/c/Users/peter/.ssh/id_ed25519_pi -o IdentitiesOnly=yes -r pi@192.168.1.152:~/KevinsProject/src pi@192.168.1.152:~/KevinsProject/scripts pi@192.168.1.152:~/KevinsProject/models .
```

Copy model only:

```
cd /mnt/c/Users/peter/Cursor/KevinsProject
scp -i /mnt/c/Users/peter/.ssh/id_ed25519_pi -o IdentitiesOnly=yes models/teachable/model.tflite models/teachable/labels.txt pi@192.168.1.152:~/KevinsProject/models/teachable/
```

---

## Camera

```
rpicam-hello --list-cameras
rpicam-still -n -o /tmp/test.jpg
```

---

## Power

```
sudo reboot
```

```
sudo shutdown -h now
```

---

## RP2040 UART (comms test + telemetry)

Wiring: Pi GPIO14 TX → RP2040 GP13 RX; RP2040 GP12 TX → Pi GPIO15 RX; common GND.  
Device: `/dev/serial0` at 115200.

Enable UART once (then reboot):

```
sudo raspi-config
```

Interface Options → Serial → login shell **No**, serial hardware **Yes**.

```
ls -l /dev/serial0
```

Install and test (on the Pi):

```
cd ~/KevinsProject
source ~/arrow-env/bin/activate
pip install pyserial
python src/run_telemetry.py
python src/test_rp2040_uart.py --ping
python src/test_rp2040_uart.py --status
python src/test_rp2040_uart.py --monitor
python src/test_rp2040_uart.py
```

`run_telemetry.py` needs no arguments — prints STATUS every 0.5 s.

Takeover test (Pi AUTO → forward 20% + right 70% for 2 s → MANUAL, caps restored):

```
python src/test_takeover.py
```

Keep wheels lifted for first runs. Transmitter on with live RC (Pi seizes control; sticks need not be centered).

## Pull-over (BT_project_v5 + HC-SR04)

Wiring: [docs/HC_SR04_Wiring.md](docs/HC_SR04_Wiring.md) (Front GP14/15, Left GP8/9, Right GP16/17).  
Plan PDF: [docs/RP2040_PullOver_Plan.pdf](docs/RP2040_PullOver_Plan.pdf).

On the Pi (after sensors are fitted):

```
cd ~/KevinsProject
source ~/arrow-env/bin/activate
python src/test_pullover.py
python src/test_pullover.py right
python src/test_pullover.py left
```

### RC test console (Flask Wi‑Fi UI)

Browser: `http://192.168.1.152:8088/`

- Live STATUS + sonar gauges (`SONAR,ON` / `OFF`)
- Pull-over LEFT / RIGHT / ABORT
- Pullover params (SIDE/BAND/FRONT/CREEP/STEER/STABLE/TIMEOUT) via `PULLOVER,SET` / `CFG?`
- **Detection arm** → CSI + quantized TFLite; consecutive `wrong` → auto-pullover
- Armed-only MJPEG preview (`/api/detection/mjpeg`)
- Virtual joystick (Pi control ON → AUTO + capped DRIVE pulses)
- Throttle caps default **25%**; joystick pulse ms
- STOP / RESET / MANUAL / **Power off Pi** (confirm → `sudo shutdown -h now`)

**LEDs (owned by `sonar-debug`):** green GPIO21 = ready (UART+UI), yellow GPIO16 = detection armed, red GPIO20 = wrong streak / pullover. Do not run `live_arrow_*` at the same time (GPIO busy).

UART (examples):

```
PULLOVER,CFG?
PULLOVER,SET,SIDE,15
PULLOVER,SET,STABLE,800
```

**Start on boot** (systemd + 60 s health watchdog):

```
cd ~/KevinsProject
bash scripts/pi/install_sonar_debug_service.sh
sudo systemctl status sonar-debug
curl -s http://127.0.0.1:8088/api/health
```

After updating the UI script on the Pi:

```
sudo systemctl restart sonar-debug
```

CLI one-shot (3 s): firmware also accepts `SONAR?`. Continuous: `SONAR,ON` / `SONAR,OFF`.

Firmware sketch: `firmware/BT_project_v5/` (also under `Documents\Arduino\BT_project_v5\`).
`--monitor` and the interactive menu print every RX line plus a parsed STATUS dashboard.

Keep wheels lifted for early tests. Use `stop` if needed.

---

## Notes

- LEDs: green GPIO21 = console ready, yellow GPIO16 = detection armed, red GPIO20 = wrong/pullover
- Model: quantized `~/KevinsProject/models/teachable/model.tflite` + `labels.txt` (`frwrd`→correct, `rvrs`→wrong, `Contrl`→none)
- One-time TFLite install: `pip install ai-edge-litert`
- One-time UART client: `pip install pyserial`
- If you see `GPIO busy`, force kill, wait a few seconds, start again
