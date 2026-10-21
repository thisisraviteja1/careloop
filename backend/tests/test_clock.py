import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import Clock

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 10, 22, 6, 0, tzinfo=IST)


def test_frozen_clock_does_not_move() -> None:
    clock = Clock(IST, speed=0, start=START)
    assert clock.now() == START
    clock.advance(timedelta(minutes=30))
    assert clock.now() == START + timedelta(minutes=30)


def test_speed_multiplies_elapsed_time() -> None:
    clock = Clock(IST, speed=600, start=START)
    time.sleep(0.05)
    elapsed = (clock.now() - START).total_seconds()
    assert 25 <= elapsed <= 120  # 0.05 s real × 600 = 30 s simulated, with scheduling slack


def test_now_is_aware_and_in_configured_zone() -> None:
    now = Clock("Asia/Kolkata").now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=5, minutes=30)


def test_set_time_requires_aware_datetime() -> None:
    with pytest.raises(ValueError):
        Clock(IST).set_time(datetime(2026, 1, 1))


def test_set_speed_keeps_current_time() -> None:
    clock = Clock(IST, speed=0, start=START)
    clock.set_speed(60)
    assert abs((clock.now() - START).total_seconds()) < 5
