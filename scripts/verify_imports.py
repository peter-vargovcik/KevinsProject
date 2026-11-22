#!/usr/bin/env python3
import cv2

print("opencv", cv2.__version__)
from picamera2 import Picamera2  # noqa: F401

print("picamera2 OK")
import gpiozero  # noqa: F401

print("gpiozero OK")
import flask

print("flask", flask.__version__)
print("venv_ok")
