from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from app.core import clock as clock_module
from app.core.clock import Clock
from app.db.session import make_engine

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def frozen_clock() -> Iterator[Clock]:
    """A stopped clock at Thu 22 Oct 2026, 05:00 IST. Tests move it with set_time/advance."""
    previous = clock_module.get_clock()
    test_clock = Clock(IST, speed=0, start=datetime(2026, 10, 22, 5, 0, tzinfo=IST))
    clock_module.set_clock(test_clock)
    yield test_clock
    clock_module.set_clock(previous)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s
