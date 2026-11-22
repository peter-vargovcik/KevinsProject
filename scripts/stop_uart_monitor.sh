#!/bin/bash
set -euo pipefail
for pat in '/home/pi/KevinsProject/src/test_rp2040_uart.py' 'tail -f /tmp/uart_monitor.log'; do
  mapfile -t PIDS < <(pgrep -f "$pat" || true)
  if ((${#PIDS[@]})); then
    echo "killing $pat -> ${PIDS[*]}"
    kill -9 "${PIDS[@]}" 2>/dev/null || sudo kill -9 "${PIDS[@]}" 2>/dev/null || true
  fi
done
sleep 1
if pgrep -f '/home/pi/KevinsProject/src/test_rp2040_uart.py' >/dev/null; then
  echo still_running
  exit 1
fi
echo stopped
