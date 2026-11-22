"""Tunable settings for the wrong-way arrow prototype."""

# Camera (Pi 4: 640–1280 is fine; raise if you need more detail)
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
FRAME_FORMAT = "RGB888"

# GPIO — BCM numbering: pin → resistor → LED → GND
LED_PIN = 17

# Arrow detection (white road paint)
MIN_CONTOUR_AREA = 600  # reject tiny speckles; road arrows are larger
BLUR_KERNEL = 5
# Expected "correct" heading: road arrow pointing away from camera ≈ up in image = -90°
# (0 = right, 90 = down, 180 = left, -90 = up)
EXPECTED_CORRECT_DEG = -90.0
CORRECT_TOLERANCE_DEG = 55.0
WRONG_WAY_TOLERANCE_DEG = 60.0

# Debounce: require N consecutive wrong-way frames before lighting LED
WRONG_WAY_DEBOUNCE_FRAMES = 5
CORRECT_DEBOUNCE_FRAMES = 3

# Optional MJPEG debug stream (view from laptop browser)
STREAM_HOST = "0.0.0.0"
STREAM_PORT = 8080
JPEG_QUALITY = 70

# Process every Nth frame (1 = every frame)
PROCESS_EVERY_N_FRAMES = 1
