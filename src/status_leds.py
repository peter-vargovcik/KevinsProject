"""BCM status LEDs: green=ready, yellow=armed, red=wrong/pullover."""

from __future__ import annotations

from typing import Optional

# Wired on the Pi (see COMMANDS.md)
LED_GREEN = 21
LED_YELLOW = 16
LED_RED = 20


class StatusLeds:
    """gpiozero LEDs with mock fallback when GPIO is unavailable."""

    def __init__(self, mock: bool = False) -> None:
        self._mock = mock
        self._green = None
        self._yellow = None
        self._red = None
        self.ready = False
        self.armed = False
        self.alert = False
        if not mock:
            try:
                from gpiozero import LED

                self._green = LED(LED_GREEN)
                self._yellow = LED(LED_YELLOW)
                self._red = LED(LED_RED)
            except Exception as exc:
                print(f"[leds] gpiozero unavailable ({exc}); mock LEDs")
                self._mock = True
        self.apply()

    def set_ready(self, on: bool) -> None:
        self.ready = bool(on)
        self.apply()

    def set_armed(self, on: bool) -> None:
        self.armed = bool(on)
        self.apply()

    def set_alert(self, on: bool) -> None:
        self.alert = bool(on)
        self.apply()

    def apply(self) -> None:
        g, y, r = self.ready, self.armed, self.alert
        if self._mock:
            return
        if self._green is not None:
            self._green.value = g
        if self._yellow is not None:
            self._yellow.value = y
        if self._red is not None:
            self._red.value = r

    def all_off(self) -> None:
        self.ready = False
        self.armed = False
        self.alert = False
        self.apply()

    def close(self) -> None:
        self.all_off()
        for led in (self._green, self._yellow, self._red):
            if led is not None:
                try:
                    led.close()
                except Exception:
                    pass
        self._green = self._yellow = self._red = None


_leds: Optional[StatusLeds] = None


def get_leds() -> StatusLeds:
    global _leds
    if _leds is None:
        _leds = StatusLeds()
    return _leds
