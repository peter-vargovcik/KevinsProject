# Raspberry Pi connection

SSH / kill / heartbeat cheat sheet: [COMMANDS.md](COMMANDS.md)  
Full session notes: see [CONTEXT.md](CONTEXT.md).

| Item | Value |
|------|--------|
| Board | **Raspberry Pi 4 Model B** |
| Host | `192.168.1.152` (static Wi‑Fi) |
| User | `pi` |
| Project | `/home/pi/KevinsProject` |
| Venv | `~/arrow-env` |
| Camera | OV5647 CSI (ribbon) |
| LEDs | green BCM21, yellow BCM16, red BCM20 |
| Debug stream | http://192.168.1.152:8080/ (main) / :8081 (test) |
| SSH key (laptop) | `%USERPROFILE%\.ssh\id_ed25519_pi` |

Gateway / DNS: `192.168.1.254`  
Wi‑Fi profile: `eir63498627_5GEXT` (NetworkManager, IPv4 manual)  
Demo hotspot (preferred on boot): SSID `Galaxy A20eFF3F` — PSK only in `scripts/pi/wifi-chooser.env` on the Pi (gitignored)

## SSH from this laptop

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519_pi -o IdentitiesOnly=yes pi@192.168.1.152
```

## Deploy from laptop

```powershell
.\scripts\deploy.ps1 -PiHost 192.168.1.152 -PiUser pi -RemotePath /home/pi/KevinsProject
```

Or with the Python helper:

```powershell
$env:PI_HOST='192.168.1.152'; $env:PI_USER='pi'; $env:PI_KEY="$env:USERPROFILE\.ssh\id_ed25519_pi"
py -3 scripts\ssh_pi.py upload .\src /home/pi/KevinsProject/src
```

## Run detector + MJPEG stream

```bash
bash /home/pi/KevinsProject/scripts/start_stream.sh
```

Then open http://192.168.1.152:8080/ on the laptop.

Manual:

```bash
source ~/arrow-env/bin/activate
cd ~/KevinsProject
python src/main.py --stream
```

Stop:

```bash
pkill -f '/home/pi/KevinsProject/src/main.py'
```

## Teachable Machine (TFLite) + LEDs

Put `model.tflite` and `labels.txt` in `models/teachable/` (see that folder's README). Classes: `correct`, `wrong`, `none`.

```bash
source ~/arrow-env/bin/activate
pip install ai-edge-litert   # once (Python 3.13)
bash /home/pi/KevinsProject/scripts/run_live_tflite.sh
```

Or manually:

```bash
cd ~/KevinsProject
python src/live_arrow_tflite.py --stream
```

Stop:

```bash
pkill -f '/home/pi/KevinsProject/src/live_arrow_tflite.py'
```

## RP2040 UART (comms + telemetry)

UART to RP2040: `/dev/serial0` @ 115200 (Pi GPIO14 TX → GP13 RX, GP12 TX → Pi GPIO15 RX, GND).  
Full commands: [COMMANDS.md](COMMANDS.md).

```bash
source ~/arrow-env/bin/activate
pip install pyserial   # once
cd ~/KevinsProject
python src/test_rp2040_uart.py --ping
python src/test_rp2040_uart.py --status
python src/test_rp2040_uart.py --monitor
```

Reusable client: `src/rp2040_uart.py` (for later TFLite integration).

## Camera check

```bash
rpicam-hello --list-cameras
rpicam-still -n -o /tmp/test.jpg
```
