"""Raspberry Pi UART client for the RP2040 RC car controller.

Protocol (115200 8N1, LF-terminated ASCII) — see BT_project_v3.ino /
docs/RC_Car_RP2040_RPi_Knowledge_Transfer.docx.

Wiring (typical):
  Pi GPIO14 TX  -> RP2040 GP13 RX
  RP2040 GP12 TX -> Pi GPIO15 RX
  common GND
  Device: /dev/serial0
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional

try:
    import serial
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pyserial is required. On the Pi: pip install pyserial"
    ) from exc


DEFAULT_PORT = "/dev/serial0"
DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT_S = 1.0
HEARTBEAT_INTERVAL_S = 0.1


@dataclass
class ControllerStatus:
    """Parsed STATUS,<12 fields> from the RP2040."""

    mode: str  # MANUAL | AUTO | STOPPED
    armed: bool
    rc_ok: bool
    rc_steer: int
    rc_throttle: int
    steer_out: int
    throttle_out: int
    forward_cap: int
    reverse_cap: int
    drive_active: bool
    uptime_ms: int
    raw: str = ""

    def dashboard(self) -> str:
        return (
            f"mode={self.mode} armed={int(self.armed)} rcOK={int(self.rc_ok)} "
            f"steerIn/Out={self.rc_steer}/{self.steer_out} "
            f"thrIn/Out={self.rc_throttle}/{self.throttle_out} "
            f"caps={self.forward_cap}/{self.reverse_cap} "
            f"drive={int(self.drive_active)} up={self.uptime_ms}"
        )


def parse_status(line: str) -> ControllerStatus:
    """Parse STATUS,mode,armed,rcOK,rcSteer,rcThrottle,steerOut,throttleOut,fCap,rCap,drive,uptime."""
    parts = line.strip().split(",")
    if len(parts) < 12 or parts[0] != "STATUS":
        raise ValueError(f"Bad STATUS line: {line!r}")
    return ControllerStatus(
        mode=parts[1],
        armed=parts[2] == "1",
        rc_ok=parts[3] == "1",
        rc_steer=int(parts[4]),
        rc_throttle=int(parts[5]),
        steer_out=int(parts[6]),
        throttle_out=int(parts[7]),
        forward_cap=int(parts[8]),
        reverse_cap=int(parts[9]),
        drive_active=parts[10] == "1",
        uptime_ms=int(parts[11]),
        raw=line.strip(),
    )


class Rp2040Client:
    """Thread-safe UART client with background reader and optional heartbeat."""

    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baud: int = DEFAULT_BAUD,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        on_line: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
        self.on_line = on_line

        self._ser: Optional[serial.Serial] = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None

        self._lines: Deque[str] = deque(maxlen=256)
        self._lines_cond = threading.Condition()
        self._latest_status: Optional[ControllerStatus] = None
        self._status_lock = threading.Lock()

        self._last_pong_uptime: Optional[int] = None
        self._restart_detected = False

        self._hb_stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None

    # ---- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if self._ser is not None and self._ser.is_open:
            return
        self._ser = serial.Serial(
            self.port,
            self.baud,
            timeout=0.05,
            write_timeout=self.timeout_s,
        )
        time.sleep(0.05)
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        self._stop.clear()
        self._reader = threading.Thread(
            target=self._reader_loop, name="rp2040-uart-rx", daemon=True
        )
        self._reader.start()

    def close(self) -> None:
        self.stop_heartbeat()
        self._stop.set()
        with self._lines_cond:
            self._lines_cond.notify_all()
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def __enter__(self) -> "Rp2040Client":
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ---- reader ------------------------------------------------------------

    def _reader_loop(self) -> None:
        buf = bytearray()
        assert self._ser is not None
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(128)
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.02)
                continue
            if not chunk:
                continue
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw = bytes(buf[:nl]).decode("utf-8", errors="replace").strip("\r")
                del buf[: nl + 1]
                if not raw:
                    continue
                self._dispatch_line(raw)

    def _dispatch_line(self, line: str) -> None:
        if line.startswith("STATUS,"):
            try:
                st = parse_status(line)
                with self._status_lock:
                    self._latest_status = st
            except ValueError:
                pass
        elif line.startswith("PONG,"):
            try:
                uptime = int(line.split(",", 1)[1])
                if (
                    self._last_pong_uptime is not None
                    and uptime + 1000 < self._last_pong_uptime
                ):
                    # Allow 32-bit wrap; treat large drop as restart.
                    self._restart_detected = True
                self._last_pong_uptime = uptime
            except (IndexError, ValueError):
                pass

        with self._lines_cond:
            self._lines.append(line)
            self._lines_cond.notify_all()

        if self.on_line is not None:
            try:
                self.on_line(line)
            except Exception:
                pass

    # ---- send / wait -------------------------------------------------------

    def send_raw(self, command: str) -> None:
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Serial port is not open")
        payload = (command.rstrip("\r\n") + "\n").encode("utf-8")
        with self._write_lock:
            self._ser.write(payload)
            self._ser.flush()

    def wait_line(
        self,
        prefix: Optional[str] = None,
        timeout_s: Optional[float] = None,
        contains: Optional[str] = None,
        prefixes: Optional[tuple[str, ...]] = None,
    ) -> str:
        """Wait for a line matching prefix(es) and/or contains. Raises TimeoutError."""
        deadline = time.monotonic() + (
            self.timeout_s if timeout_s is None else timeout_s
        )
        wanted = prefixes
        if wanted is None and prefix is not None:
            wanted = (prefix,)

        with self._lines_cond:
            while True:
                for i, line in enumerate(self._lines):
                    if wanted is not None and not any(
                        line.startswith(p) for p in wanted
                    ):
                        continue
                    if contains is not None and contains not in line:
                        continue
                    del self._lines[i]
                    return line
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timeout waiting for line "
                        f"prefixes={wanted!r} contains={contains!r}"
                    )
                self._lines_cond.wait(timeout=remaining)

    def drain_lines(self) -> list[str]:
        with self._lines_cond:
            out = list(self._lines)
            self._lines.clear()
            return out

    def latest_status(self) -> Optional[ControllerStatus]:
        with self._status_lock:
            return self._latest_status

    def consume_restart_flag(self) -> bool:
        flag = self._restart_detected
        self._restart_detected = False
        return flag

    # ---- protocol helpers --------------------------------------------------

    def ping(self, timeout_s: Optional[float] = None) -> int:
        """Send PING; return PONG uptime_ms."""
        self.send_raw("PING")
        line = self.wait_line(prefix="PONG,", timeout_s=timeout_s)
        return int(line.split(",", 1)[1])

    def status(self, timeout_s: Optional[float] = None) -> ControllerStatus:
        self.send_raw("STATUS?")
        line = self.wait_line(prefix="STATUS,", timeout_s=timeout_s)
        return parse_status(line)

    def set_cap(self, direction: str, percent: int, timeout_s: Optional[float] = None) -> str:
        direction = direction.upper()
        if direction not in ("FORWARD", "REVERSE"):
            raise ValueError("direction must be FORWARD or REVERSE")
        if not 0 <= percent <= 100:
            raise ValueError("percent must be 0..100")
        self.send_raw(f"CAP,{direction},{percent}")
        line = self.wait_line(
            prefixes=("OK,CAP,", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def mode_manual(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("MODE,MANUAL")
        return self.wait_line(prefix="OK,MANUAL", timeout_s=timeout_s)

    def mode_auto(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("MODE,AUTO")
        line = self.wait_line(
            prefixes=("OK,AUTO", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def drive(
        self,
        direction: int,
        angle: int,
        duration_ms: int,
        timeout_s: Optional[float] = None,
    ) -> str:
        if direction not in (1, 2):
            raise ValueError("direction must be 1 (forward) or 2 (backward)")
        if not -100 <= angle <= 100:
            raise ValueError("angle must be -100..100")
        if not 1 <= duration_ms <= 5000:
            raise ValueError("duration_ms must be 1..5000")
        self.send_raw(f"DRIVE,{direction},{angle},{duration_ms}")
        line = self.wait_line(
            prefixes=("OK,DRIVE", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def stop(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("STOP")
        return self.wait_line(prefix="OK,STOP", timeout_s=timeout_s)

    def reset(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("RESET")
        line = self.wait_line(
            prefixes=("OK,RESET", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def pullover_left(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("PULLOVER,LEFT")
        line = self.wait_line(
            prefixes=("OK,PULLOVER,LEFT", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def pullover_right(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("PULLOVER,RIGHT")
        line = self.wait_line(
            prefixes=("OK,PULLOVER,RIGHT", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def pullover_abort(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("PULLOVER,ABORT")
        line = self.wait_line(
            prefixes=("ERR,PULLOVER,ABORT", "OK,PULLOVER,ABORT", "ERR,"),
            timeout_s=timeout_s,
        )
        return line

    def wait_pullover_done(self, timeout_s: float = 20.0) -> str:
        """Wait for DONE,PULLOVER or a PULLOVER error."""
        line = self.wait_line(
            prefixes=("DONE,PULLOVER", "ERR,PULLOVER,"),
            timeout_s=timeout_s,
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def sonar_on(self, timeout_s: Optional[float] = None) -> str:
        """Enable continuous RANGE3,front,left,right (no motion)."""
        self.send_raw("SONAR,ON")
        line = self.wait_line(
            prefixes=("OK,SONAR,ON", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def sonar_off(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("SONAR,OFF")
        line = self.wait_line(
            prefixes=("OK,SONAR,OFF", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def override_on(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("OVERRIDE,ON")
        return self.wait_line(prefix="OK,OVERRIDE,ON", timeout_s=timeout_s)

    def override_off(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("OVERRIDE,OFF")
        line = self.wait_line(
            prefixes=("OK,OVERRIDE,OFF", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def override_arm(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("OVERRIDE,ARM")
        line = self.wait_line(
            prefixes=("OK,OVERRIDE,ARM", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def override_steer(self, angle: int, timeout_s: Optional[float] = None) -> str:
        if not -100 <= angle <= 100:
            raise ValueError("angle must be -100..100")
        self.send_raw(f"OVERRIDE,STEER,{angle}")
        line = self.wait_line(
            prefixes=("OK,OVERRIDE,STEER", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def override_drive(
        self,
        direction: int,
        angle: int,
        duration_ms: int,
        timeout_s: Optional[float] = None,
    ) -> str:
        if direction not in (1, 2):
            raise ValueError("direction must be 1 or 2")
        if not -100 <= angle <= 100:
            raise ValueError("angle must be -100..100")
        if not 1 <= duration_ms <= 1500:
            raise ValueError("duration_ms must be 1..1500")
        self.send_raw(f"OVERRIDE,DRIVE,{direction},{angle},{duration_ms}")
        line = self.wait_line(
            prefixes=("OK,OVERRIDE,DRIVE", "ERR,"), timeout_s=timeout_s
        )
        if line.startswith("ERR,"):
            raise RuntimeError(line)
        return line

    def estop(self, timeout_s: Optional[float] = None) -> str:
        self.send_raw("ESTOP")
        return self.wait_line(prefix="OK,ESTOP", timeout_s=timeout_s)

    # ---- heartbeat ---------------------------------------------------------

    def start_heartbeat(self, interval_s: float = HEARTBEAT_INTERVAL_S) -> None:
        self.stop_heartbeat()
        self._hb_stop.clear()

        def _loop() -> None:
            while not self._hb_stop.wait(interval_s):
                try:
                    self.send_raw("PING")
                except Exception:
                    pass

        self._hb_thread = threading.Thread(
            target=_loop, name="rp2040-heartbeat", daemon=True
        )
        self._hb_thread.start()

    def stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=1.0)
            self._hb_thread = None
