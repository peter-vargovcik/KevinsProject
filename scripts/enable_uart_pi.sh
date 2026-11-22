#!/bin/bash
set -euo pipefail

# Disable serial login console; keep UART hardware
sudo raspi-config nonint do_serial_cons 1 || true
sudo raspi-config nonint do_serial_hw 0 || true

CMD=/boot/firmware/cmdline.txt
if [[ -f "$CMD" ]]; then
  sudo cp "$CMD" "${CMD}.bak.$(date +%Y%m%d%H%M%S)"
  # Remove kernel serial console so /dev/serial0 is free for RP2040
  sudo sed -i -E 's/ ?console=serial0,[0-9]+//g; s/ ?console=ttyAMA0,[0-9]+//g' "$CMD"
  echo "cmdline: $(cat "$CMD")"
fi

CFG=/boot/firmware/config.txt
if ! grep -q '^enable_uart=1' "$CFG"; then
  echo 'enable_uart=1' | sudo tee -a "$CFG"
fi
# Prefer PL011 UART over mini-UART (Bluetooth moves off UART0)
if ! grep -q '^dtoverlay=disable-bt' "$CFG"; then
  echo 'dtoverlay=disable-bt' | sudo tee -a "$CFG"
fi

echo "--- uart config ---"
grep -E 'enable_uart|disable-bt' "$CFG" || true
echo "Rebooting in 2s..."
sleep 2
sudo reboot
