#!/bin/bash
set -euo pipefail

# Stop any previous monitor (match by absolute script path only)
mapfile -t PIDS < <(pgrep -f '/home/pi/KevinsProject/src/test_rp2040_uart.py' || true)
if ((${#PIDS[@]})); then
  kill -9 "${PIDS[@]}" 2>/dev/null || true
  sleep 1
fi

cd /home/pi/KevinsProject

# Live telemetry on HDMI console + log file
nohup /home/pi/arrow-env/bin/python src/test_rp2040_uart.py --monitor \
  > /tmp/uart_monitor.log 2>&1 &
echo $! > /tmp/uart_monitor.pid

# Also mirror to tty1 if available (physical monitor)
if [[ -c /dev/tty1 ]]; then
  nohup sudo sh -c "tail -f /tmp/uart_monitor.log > /dev/tty1" \
    > /tmp/uart_tty1_tail.log 2>&1 &
  echo $! > /tmp/uart_tty1_tail.pid
fi

sleep 2
echo "PID=$(cat /tmp/uart_monitor.pid)"
pgrep -af '/home/pi/KevinsProject/src/test_rp2040_uart.py' || echo "not running"
echo "=== log ==="
tail -15 /tmp/uart_monitor.log || true
