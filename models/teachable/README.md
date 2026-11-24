# Teachable Machine model (active)

Runtime files (used by Flask detection / `live_arrow_tflite.py`):

- `model.tflite` — **quantized** export (from `archives/tfl quantized android.zip`)
- `labels.txt` — class names as exported with that model

## Current classes → app status

| Model label | App status |
|-------------|------------|
| `frwrd`     | correct    |
| `rvrs`      | wrong      |
| `Contrl`    | none       |

Zip archives and the previous float `model.tflite` live under `archives/` (not loaded at runtime).

## Export / replace

1. Train in [Teachable Machine](https://teachablemachine.withgoogle.com/train/image).
2. Export **TensorFlow Lite → Quantized**.
3. Replace `model.tflite` + `labels.txt` here; update mapping in `src/detection_worker.py` (`normalize_status`) if class names change.
4. Deploy to the Pi: `~/KevinsProject/models/teachable/`.
