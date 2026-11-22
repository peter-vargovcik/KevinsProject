# HC-SR04 wiring (RP2040 pull-over)

Three ultrasonic sensors for `BT_project_v5` pull-over. Sonar is **off** until `PULLOVER,LEFT` / `PULLOVER,RIGHT`.

## Pin map

Already used: GP2/3 RC in, GP4/5 servo/ESC, GP12/13 UART to Pi.

| Sensor | TRIG (3.3 V out) | ECHO (via divider into GPIO) |
|--------|------------------|------------------------------|
| Front  | GP6              | GP7                          |
| Left   | GP8              | GP9                          |
| Right  | GP10             | GP11                         |

## Electrical

- HC-SR04 **VCC = 5 V** (BEC/regulated), **GND common** with RP2040.
- TRIG: RP2040 GPIO → sensor TRIG (3.3 V is accepted).
- ECHO: sensor ECHO is **5 V** — do **not** wire straight to RP2040.
  - Each ECHO: **10 kΩ series** from sensor, then **16 kΩ to GND**, tap between resistors → GPIO.
  - Same divider style as the RC receiver inputs.

## Power / safety

- Common ground between pack/BEC, RP2040, and sensors.
- Fit sensors before enabling pull-over on a moving car.
- Validate dividers with a meter before first power-up.
