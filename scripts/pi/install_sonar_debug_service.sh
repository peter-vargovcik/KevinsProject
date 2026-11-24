#!/bin/bash
# Install / enable sonar-debug Flask on boot + watchdog timer.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UNIT_DIR=/etc/systemd/system

sudo cp "$ROOT/scripts/pi/sonar-debug.service" "$UNIT_DIR/sonar-debug.service"
sudo cp "$ROOT/scripts/pi/sonar-debug-watchdog.service" "$UNIT_DIR/sonar-debug-watchdog.service"
sudo cp "$ROOT/scripts/pi/sonar-debug-watchdog.timer" "$UNIT_DIR/sonar-debug-watchdog.timer"
sudo chmod +x "$ROOT/scripts/pi/sonar-debug-watchdog.sh"
sudo chmod +x "$ROOT/scripts/pi/install_sonar_debug_service.sh"

# Passwordless halt for Flask "Power off Pi" button
SUDOERS_DST=/etc/sudoers.d/sonar-debug-shutdown
sudo cp "$ROOT/scripts/pi/sonar-debug-shutdown.sudoers" "$SUDOERS_DST"
sudo chmod 440 "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"

# Stop any manual nohup instance
if [ -f /home/pi/KevinsProject/logs/sonar_debug.pid ]; then
  kill "$(cat /home/pi/KevinsProject/logs/sonar_debug.pid)" 2>/dev/null || true
  rm -f /home/pi/KevinsProject/logs/sonar_debug.pid
fi
pkill -f '/KevinsProject/src/sonar_debug_server.py' 2>/dev/null || true
sleep 1

sudo systemctl daemon-reload
sudo systemctl enable --now sonar-debug.service
sudo systemctl enable --now sonar-debug-watchdog.timer
sudo systemctl restart sonar-debug.service
sleep 2
systemctl --no-pager --full status sonar-debug.service || true
curl -fsS http://127.0.0.1:8088/api/health
echo
echo "OK: sonar-debug enabled on boot; watchdog every 60s"
