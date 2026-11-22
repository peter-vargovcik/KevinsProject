# Project context — Wrong-way arrow prototype

Updated: 2026-10-04 — fresh OS reinstall on Pi 4.

## Goal

Detect directional arrows with a CSI camera. Wrong-way heading → LED alert. Develop from the Windows laptop over SSH.

## Hardware / access

| Item | Detail |
|------|--------|
| Board | **Raspberry Pi 4 Model B** |
| Camera | OV5647 CSI ribbon |
| LEDs (BCM) | **Green GPIO21**, **Yellow GPIO16**, **Red GPIO20** |
| Host | `192.168.1.152` (**static** Wi‑Fi) |
| Wi‑Fi | `eir63498627_5GEXT` (NetworkManager) |
| Gateway/DNS | `192.168.1.254` |
| User | **`pi`** (reinstalled OS; was `peter`) |
| Password | set at image time (default lab: `raspberry` — change if exposed) |
| SSH key | `%USERPROFILE%\.ssh\id_ed25519_pi` |
| Project on Pi | `/home/pi/KevinsProject` |
| Venv | `/home/pi/arrow-env` |

## Software stack

- OS: Debian / Raspberry Pi OS **trixie** aarch64
- apt: `python3-picamera2`, `python3-opencv`, `python3-gpiozero`, `python3-flask`
- venv with `--system-site-packages`

## Repo (laptop + Pi)

```
src/                  # main wrong-way detector (single LED_PIN in config still 17)
temp/test_script.py   # contrast → green/yellow/red LEDs; --stream :8081
images/               # real road samples (classical CV failed)
scripts/              # deploy, setup_pi, ssh_pi, start/run helpers
PI.md / CONTEXT.md
```

## Status after reinstall (2026-10-04)

- [x] SSH key installed for `pi`
- [x] Static IP `192.168.1.152` via nmcli
- [x] Project files copied to `/home/pi/KevinsProject`
- [x] apt packages + `~/arrow-env` venv
- [x] Contrast pipeline (`detect_arrow_contrast.py`) + live LEDs (`live_arrow_leds.py`)
- [ ] Main app multi-LED in `src/main.py` (still old single-LED path)
- [ ] Further harden false positives (ceiling glare mostly handled)

### End of day 2026-10-04
- Live script stopped; Pi shut down.
- Resume: SSH `pi@192.168.1.152`, then `bash ~/KevinsProject/scripts/run_live_leds.sh`
- LEDs: green=correct (GPIO21), yellow=none (GPIO16), red=wrong (GPIO20)
- Preview: http://192.168.1.152:8080/

## Commands

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519_pi -o IdentitiesOnly=yes pi@192.168.1.152
.\scripts\deploy.ps1 -PiHost 192.168.1.152 -PiUser pi -RemotePath /home/pi/KevinsProject
```

```bash
# On Pi (once packages installed)
cd ~/KevinsProject && ./scripts/setup_pi.sh
source ~/arrow-env/bin/activate
python temp/test_script.py --stream   # http://192.168.1.152:8081/
python src/main.py --stream           # http://192.168.1.152:8080/
```
