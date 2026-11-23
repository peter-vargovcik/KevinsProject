#!/bin/bash
# Heartbeat: restart sonar-debug if HTTP health fails.
set -euo pipefail
URL="http://127.0.0.1:8088/api/health"
if curl -fsS --max-time 3 "$URL" >/dev/null; then
  exit 0
fi
logger -t sonar-debug-watchdog "health check failed; restarting sonar-debug.service"
systemctl restart sonar-debug.service
