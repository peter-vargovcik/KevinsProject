# HC-SR04 wiring (RP2040 pull-over)

Three ultrasonic sensors for `BT_project_v5` pull-over. Sonar is **off** until `PULLOVER,LEFT` / `PULLOVER,RIGHT`.

## Pin map

Already used: GP2/3 RC in, GP4/5 servo/ESC, GP12/13 UART to Pi.  
(GP6/7 and GP10/11 are free — previous front/right pins; do not reuse without updating firmware.)

| Sensor | TRIG (3.3 V out) | ECHO (via divider into GPIO) |
|--------|------------------|------------------------------|
| Front  | GP14             | GP15                         |
| Left   | GP8              | GP9                          |
| Right  | GP16             | GP17                         |

## Electrical

- HC-SR04 **VCC = 5 V** (BEC/regulated), **GND common** with RP2040.
- TRIG: RP2040 GPIO → sensor TRIG (3.3 V is accepted).
- ECHO: sensor ECHO is **5 V** — do **not** wire straight to RP2040.
  - Each ECHO: **dual 10 kΩ** divider — series 10 kΩ from sensor, 10 kΩ to GND, tap between → GPIO (~2.5 V).

## Power / safety

- Common ground between pack/BEC, RP2040, and sensors.
- Fit sensors before enabling pull-over on a moving car.
- Validate dividers with a meter before first power-up.
