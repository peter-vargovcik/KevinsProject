# Project context — Wrong-way arrow + RC pull-over

Updated: **2026-11-23** (end of day).

## Goal

1. Detect directional arrows with a CSI camera (wrong-way → LED alert).
2. RP2040 RC car control from Pi UART; **pull-over** with 3× HC-SR04.

## Hardware / access

| Item | Detail |
|------|--------|
| Pi | Raspberry Pi 4, `pi@192.168.1.152` (Wi‑Fi can drop — power-cycle if SSH times out) |
| SSH | `%USERPROFILE%\.ssh\id_ed25519_pi` |
| Project on Pi | `/home/pi/KevinsProject` · venv `~/arrow-env` |
| RP2040 | Generic RP2040, USB **COM4**, Boot Stage 2 **Generic SPI /4** |
| Firmware | `Documents\Arduino\BT_project_v5\` (= repo `firmware/BT_project_v5/`) |
| GitHub | https://github.com/peter-vargovcik/KevinsProject.git (`main`) |

## Sonar pins (current)

ECHO via **dual 10 kΩ** divider. VCC=5 V, GND common.

| Sensor | TRIG | ECHO |
|--------|------|------|
| Front | GP14 | GP15 |
| Left | GP8 | GP9 |
| Right | GP16 | GP17 |

(Old GP6/7 and GP10/11 unused.)

## Status 2026-11-23

- [x] PULLOVER LEFT/RIGHT with Pi takeover (sticks need not be centered)
- [x] Front collision path exists (`ERR,PULLOVER,FRONT` if front &lt; 25 cm)
- [x] Sonar debug: `SONAR,ON` / `OFF` / `?` → `RANGE3,f,l,r`
- [x] Flask **RC test console** on Pi: port **8088** (sonar, pullover + runtime CFG, joystick @ default 25% caps, STOP/RESET); systemd `sonar-debug` + 60s watchdog
- [x] Pullover tunables over UART: `PULLOVER,CFG?` / `PULLOVER,SET,<KEY>,<val>` (SIDE/BAND/FRONT/CREEP/STEER/STABLE/TIMEOUT)
- [x] Detection arm in Flask: quantized TFLite, LEDs (G ready / Y armed / R alert), consecutive wrong → auto-pullover, armed-only MJPEG
- [x] USB Serial diag without Pi: send `SONAR,ON` on COM4; see `RANGE3` + `DIAG F= L= R=`
- [x] Fixed right channel always `-1` (stale timeout + fair round-robin in diag)
- [x] All three sensors reading on USB bench (F~8, L~40s, R~8–9 cm) after right module replace
- [ ] Pi was intermittently unreachable tonight — restore Wi‑Fi / power-cycle before Flask tests
- [ ] End-to-end front-collision pullover test with reliable reflections
- [ ] Arrow / TFLite path still available under `src/live_arrow_tflite.py`

## Resume tomorrow

1. Bring Pi online: `ping 192.168.1.152` then SSH; confirm `systemctl status sonar-debug` and http://192.168.1.152:8088/
2. Or USB-only: COM4 115200, send `SONAR,ON`, watch ranges; `SONAR,OFF` when done
3. Flash note: `arduino-cli` FQBN needs `boot2=boot2_generic_03h_4_padded_checksum`; if upload misses drive, copy UF2 to `RPI-RP2`
4. Optional: pullover RIGHT/LEFT + block front for `ERR,PULLOVER,FRONT`

## Key commands

```powershell
# Pi
ssh -i $env:USERPROFILE\.ssh\id_ed25519_pi -o IdentitiesOnly=yes pi@192.168.1.152
# UI
# http://192.168.1.152:8088/
```

```text
USB (COM4): SONAR,ON   /   SONAR,OFF
Pi UART:    same commands via Flask or test_sonar_diag.py
```
