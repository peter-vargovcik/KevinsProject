"""GPIO LED control with a mock fallback for laptop development."""

from __future__ import annotations

from config import LED_PIN


class LedAlert:
    """Turns an LED on when wrong-way driving is detected."""

    def __init__(self, pin: int = LED_PIN, mock: bool = False) -> None:
        self.pin = pin
        self._mock = mock
        self._on = False
        self._led = None

        if not mock:
            try:
                from gpiozero import LED

                self._led = LED(pin)
            except Exception as exc:
                print(f"[led] gpiozero unavailable ({exc}); using mock LED")
                self._mock = True

    @property
    def is_on(self) -> bool:
        return self._on

    def on(self) -> None:
        self._on = True
        if self._led is not None:
            self._led.on()
        elif self._mock:
            # Avoid spamming; caller may print status
            pass

    def off(self) -> None:
        self._on = False
        if self._led is not None:
            self._led.off()

    def set(self, wrong_way: bool) -> None:
        if wrong_way:
            self.on()
        else:
            self.off()

    def close(self) -> None:
        self.off()
        if self._led is not None:
            try:
                self._led.close()
            except Exception:
                pass
