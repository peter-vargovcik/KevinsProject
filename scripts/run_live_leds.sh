#!/bin/bash
set -euo pipefail
pkill -f '/home/pi/KevinsProject/src/live_arrow_leds.py' 2>/dev/null || true
pkill -f '/home/pi/KevinsProject/temp/test_script.py' 2>/dev/null || true
pkill -f '/home/pi/KevinsProject/src/main.py' 2>/dev/null || true
sleep 1
cd /home/pi/KevinsProject
nohup /home/pi/arrow-env/bin/python src/live_arrow_leds.py --stream \
  > /tmp/live_arrow_leds.log 2>&1 &
echo $! > /tmp/live_arrow_leds.pid
sleep 5
echo "PID=$(cat /tmp/live_arrow_leds.pid)"
echo '=== LOG ==='
tail -50 /tmp/live_arrow_leds.log
echo '=== PORT ==='
ss -ltn | grep 8080 || true
