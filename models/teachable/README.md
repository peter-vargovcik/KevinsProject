# Teachable Machine model

Put the TensorFlow Lite export from
[Teachable Machine (Image)](https://teachablemachine.withgoogle.com/train/image)
in this folder.

## Export steps

1. Create three classes named exactly: `correct`, `wrong`, `none`.
2. Train with photos from the Pi camera view (arrows + empty / glare scenes).
3. Click **Export Model** → **TensorFlow Lite** → **Download my model**.
4. Unzip so this directory contains:
   - `model.tflite`
   - `labels.txt` (one class name per line)

## Run on the Pi

```bash
# once: install TFLite into the project venv
source ~/arrow-env/bin/activate
pip install tflite-runtime

bash /home/pi/KevinsProject/scripts/run_live_tflite.sh
```

Preview: http://192.168.1.152:8080/
