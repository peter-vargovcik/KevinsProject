#!/bin/bash
set -euo pipefail
pkill -f '/home/pi/KevinsProject/src/main.py' 2>/dev/null || true
pkill -f '/home/pi/KevinsProject/temp/test_script.py' 2>/dev/null || true
sleep 1
cd /home/pi/KevinsProject
nohup /home/pi/arrow-env/bin/python temp/test_script.py --stream \
  > /tmp/test_script.log 2>&1 &
echo $! > /tmp/test_script.pid
sleep 5
echo "PID=$(cat /tmp/test_script.pid)"
echo '=== LOG ==='
tail -40 /tmp/test_script.log
echo '=== PORT ==='
ss -ltn | grep 8081 || true
