"""The single time source for CareLoop.

App code must call `now()` from this module, never `datetime.now()` or `time.time()`.
The clock can run faster than real time (demo mode), be set to any moment, or be frozen
(speed 0) so tests control time exactly.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo


class Clock:
    """A timezone-aware clock with a speed multiplier and an adjustable anchor."""

    def __init__(self, tz: tzinfo | str = "Asia/Kolkata", speed: float = 1.0,
                 start: datetime | None = None) -> None:
        self.tz = ZoneInfo(tz) if isinstance(tz, str) else tz
        self._lock = threading.Lock()
        self._speed = float(speed)
        self._anchor_sim = (start or self._real_now()).astimezone(self.tz)
        self._anchor_real = time.monotonic()

    def _real_now(self) -> datetime:
        return datetime.now(self.tz)

    @property
    def speed(self) -> float:
        return self._speed

    def now(self) -> datetime:
        """Current simulated time, aware, in the configured timezone."""
        with self._lock:
            elapsed = (time.monotonic() - self._anchor_real) * self._speed
            return self._anchor_sim + timedelta(seconds=elapsed)

    def set_time(self, moment: datetime) -> None:
        """Jump to `moment` and keep running at the current speed from there."""
        if moment.tzinfo is None:
            raise ValueError("set_time needs a timezone-aware datetime")
        with self._lock:
            self._anchor_sim = moment.astimezone(self.tz)
            self._anchor_real = time.monotonic()

    def set_speed(self, speed: float) -> None:
        """Change the multiplier without jumping in time. Speed 0 freezes the clock."""
        current = self.now()
        with self._lock:
            self._speed = float(speed)
            self._anchor_sim = current
            self._anchor_real = time.monotonic()

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by `delta` (used by tests and the demo runner)."""
        self.set_time(self.now() + delta)

    def reset_to_real_time(self) -> None:
        """Return to the real wall clock at speed 1."""
        with self._lock:
            self._speed = 1.0
            self._anchor_sim = self._real_now()
            self._anchor_real = time.monotonic()


_clock = Clock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    """Replace the process-wide clock (startup configuration and tests)."""
    global _clock
    _clock = clock


def now() -> datetime:
    """The current time according to CareLoop's clock."""
    return _clock.now()
