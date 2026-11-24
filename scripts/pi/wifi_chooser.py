#!/usr/bin/env python3
"""Boot Wi‑Fi chooser: prefer demo hotspot, else home/dev SSID.

If neither connects, blink red LED (BCM20) until connectivity appears
(or forever). Releases the LED before exit so sonar-debug can own it.

Config: /home/pi/KevinsProject/scripts/pi/wifi-chooser.env
  (see wifi-chooser.env.example). Passwords are NOT stored in git.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

LED_RED = 20
ENV_PATH = Path(__file__).resolve().parent / "wifi-chooser.env"
DEFAULTS = {
    "HOTSPOT_SSID": "Galaxy A20eFF3F",
    "HOTSPOT_CONN": "Galaxy-Hotspot",
    # Comma-separated fallbacks for home/dev (2.4 + 5 GHz profiles)
    "HOME_SSID": "eir63498627_2GEXT,eir63498627_5GEXT",
    "HOME_CONN": "eir63498627_2GEXT,eir63498627_5GEXT",
    "SCAN_WAIT_S": "8",
    "CONNECT_TIMEOUT_S": "25",
    "RETRY_ROUNDS": "6",
    "BLINK_MS": "500",
}


def _split_list(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def load_env(path: Path) -> dict[str, str]:
    cfg = dict(DEFAULTS)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    # Environment overrides
    for k in list(cfg.keys()) + ["HOTSPOT_PSK", "HOME_PSK"]:
        if k in os.environ and os.environ[k]:
            cfg[k] = os.environ[k]
    return cfg


def run(cmd: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def nmcli(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return run(["nmcli", *args], timeout=timeout)


def wifi_connected() -> bool:
    r = nmcli("-t", "-f", "DEVICE,TYPE,STATE", "device", timeout=10)
    for line in (r.stdout or "").splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "wifi" and parts[2] == "connected":
            return True
    # Also accept general connectivity
    r2 = nmcli("-t", "-f", "CONNECTIVITY", "networking", timeout=10)
    return (r2.stdout or "").strip() in ("full", "limited", "portal")


def active_ssid() -> str:
    r = nmcli("-t", "-f", "ACTIVE,SSID", "dev", "wifi", timeout=15)
    for line in (r.stdout or "").splitlines():
        # ACTIVE:SSID  → yes:MySSID
        if line.startswith("yes:"):
            return line.split(":", 1)[1]
    return ""


def ensure_radio_on() -> None:
    nmcli("radio", "wifi", "on", timeout=15)
    nmcli("networking", "on", timeout=15)


def scan_ssids() -> set[str]:
    nmcli("dev", "wifi", "rescan", timeout=20)
    time.sleep(2.0)
    r = nmcli("-t", "-f", "SSID", "dev", "wifi", "list", timeout=20)
    out: set[str] = set()
    for line in (r.stdout or "").splitlines():
        ssid = line.strip()
        if ssid:
            out.add(ssid)
    return out


def connection_exists(name: str) -> bool:
    r = nmcli("-t", "-f", "NAME", "connection", "show", timeout=15)
    names = {(ln.split(":")[0] if ":" in ln else ln).strip() for ln in (r.stdout or "").splitlines()}
    return name in names


def ensure_wifi_connection(conn_name: str, ssid: str, psk: str) -> None:
    """Create or update a NetworkManager Wi‑Fi profile (DHCP)."""
    if not connection_exists(conn_name):
        print(f"[wifi] creating connection {conn_name!r} for SSID {ssid!r}")
        args = [
            "connection",
            "add",
            "type",
            "wifi",
            "con-name",
            conn_name,
            "ifname",
            "*",
            "ssid",
            ssid,
        ]
        if psk:
            args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk]
        r = nmcli(*args, timeout=30)
        if r.returncode != 0:
            print(f"[wifi] add failed: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
    else:
        # Keep SSID in sync; update PSK if provided
        nmcli("connection", "modify", conn_name, "wifi.ssid", ssid, timeout=15)
        if psk:
            nmcli(
                "connection",
                "modify",
                conn_name,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                psk,
                timeout=15,
            )
    nmcli("connection", "modify", conn_name, "connection.autoconnect", "yes", timeout=15)


def try_connect(conn_name: str, timeout_s: float) -> bool:
    print(f"[wifi] activating {conn_name!r} …")
    r = nmcli("--wait", str(int(timeout_s)), "connection", "up", conn_name, timeout=timeout_s + 10)
    if r.returncode != 0:
        print(f"[wifi] up failed: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
        return False
    time.sleep(1.0)
    ok = wifi_connected()
    print(f"[wifi] active SSID={active_ssid()!r} connected={ok}")
    return ok


class RedBlinker:
    def __init__(self) -> None:
        self._led = None
        self._mock = False
        try:
            from gpiozero import LED

            self._led = LED(LED_RED)
        except Exception as exc:
            print(f"[wifi] LED mock ({exc})")
            self._mock = True

    def set(self, on: bool) -> None:
        if self._led is not None:
            self._led.value = bool(on)

    def close(self) -> None:
        self.set(False)
        if self._led is not None:
            try:
                self._led.close()
            except Exception:
                pass
            self._led = None


def blink_sleep(led: RedBlinker, seconds: float, blink_ms: int) -> None:
    """Sleep while blinking; returns early if Wi‑Fi comes up."""
    period = max(0.1, blink_ms / 1000.0)
    end = time.monotonic() + seconds
    on = True
    while time.monotonic() < end:
        if wifi_connected():
            return
        led.set(on)
        on = not on
        time.sleep(period)
    led.set(False)


def forever_blink(led: RedBlinker, blink_ms: int) -> None:
    print("[wifi] no network — blinking red LED (BCM20)")
    period = max(0.1, blink_ms / 1000.0)
    on = True
    while True:
        if wifi_connected():
            print("[wifi] link came up — stopping blink")
            led.set(False)
            return
        led.set(on)
        on = not on
        time.sleep(period)


def main() -> int:
    cfg = load_env(ENV_PATH)
    hotspot_ssid = cfg["HOTSPOT_SSID"]
    hotspot_conn = cfg["HOTSPOT_CONN"]
    home_ssids = _split_list(cfg["HOME_SSID"])
    home_conns = _split_list(cfg["HOME_CONN"])
    if len(home_conns) < len(home_ssids):
        home_conns = home_ssids[:]  # conn name defaults to SSID
    while len(home_ssids) < len(home_conns):
        home_ssids.append(home_conns[len(home_ssids)])
    home_pairs = list(zip(home_ssids, home_conns))
    hotspot_psk = cfg.get("HOTSPOT_PSK", "")
    home_psk = cfg.get("HOME_PSK", "")
    scan_wait = float(cfg["SCAN_WAIT_S"])
    connect_timeout = float(cfg["CONNECT_TIMEOUT_S"])
    rounds = max(1, int(cfg["RETRY_ROUNDS"]))
    blink_ms = int(cfg["BLINK_MS"])

    print(f"[wifi] chooser start hotspot={hotspot_ssid!r} home={home_ssids!r}")
    led = RedBlinker()
    try:
        ensure_radio_on()
        if hotspot_psk:
            ensure_wifi_connection(hotspot_conn, hotspot_ssid, hotspot_psk)
        elif not connection_exists(hotspot_conn):
            print(
                f"[wifi] WARN: no PSK and no profile {hotspot_conn!r} — create wifi-chooser.env",
                file=sys.stderr,
            )
        # Home profiles usually already exist; only create if PSK given
        if home_psk:
            for ssid, conn in home_pairs:
                ensure_wifi_connection(conn, ssid, home_psk)

        # Prefer hotspot when already associated
        if wifi_connected() and active_ssid() == hotspot_ssid:
            print("[wifi] already on hotspot")
            return 0

        for attempt in range(1, rounds + 1):
            print(f"[wifi] attempt {attempt}/{rounds}")
            blink_sleep(led, scan_wait, blink_ms)
            if wifi_connected() and active_ssid() == hotspot_ssid:
                print("[wifi] connected to hotspot")
                return 0

            seen = scan_ssids()
            print(f"[wifi] scan saw {len(seen)} SSIDs")

            if hotspot_ssid in seen and connection_exists(hotspot_conn):
                # Drop home wifi so we can prefer hotspot
                if wifi_connected() and active_ssid() != hotspot_ssid:
                    for _, conn in home_pairs:
                        if connection_exists(conn):
                            nmcli("connection", "down", conn, timeout=20)
                if try_connect(hotspot_conn, connect_timeout):
                    return 0

            for ssid, conn in home_pairs:
                if ssid in seen and connection_exists(conn):
                    if try_connect(conn, connect_timeout):
                        return 0

            # Fallback: try known profiles even if scan missed them
            if connection_exists(hotspot_conn) and try_connect(hotspot_conn, connect_timeout):
                return 0
            for _, conn in home_pairs:
                if connection_exists(conn) and try_connect(conn, connect_timeout):
                    return 0

        forever_blink(led, blink_ms)
        # If link appeared during forever blink:
        return 0
    finally:
        led.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
