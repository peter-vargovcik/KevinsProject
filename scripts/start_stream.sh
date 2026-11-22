#!/bin/bash
# Start wrong-way detector in the background
set -euo pipefail
pkill -f '/home/pi/KevinsProject/src/main.py' 2>/dev/null || true
sleep 1
cd /home/pi/KevinsProject
nohup /home/pi/arrow-env/bin/python src/main.py --stream \
  > /tmp/arrow-stream.log 2>&1 &
echo $! > /tmp/arrow-stream.pid
sleep 4
echo "PID=$(cat /tmp/arrow-stream.pid)"
echo '=== LOG ==='
head -40 /tmp/arrow-stream.log
echo '=== PORT ==='
ss -ltn | grep 8080 || true
echo '=== PROC ==='
pgrep -af 'src/main.py' || true
