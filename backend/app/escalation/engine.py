"""The escalation ladder as a pure state machine.

DETECTED → L1_PENDING (elder) → L2_PENDING (caregiver) → L3_PENDING (neighbor) → EXHAUSTED,
or ACKNOWLEDGED at any point. An ack at any level stops every later level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

DETECTED = "DETECTED"
L1_PENDING = "L1_PENDING"
L2_PENDING = "L2_PENDING"
L3_PENDING = "L3_PENDING"
EXHAUSTED = "EXHAUSTED"
ACKNOWLEDGED = "ACKNOWLEDGED"

PENDING = (L1_PENDING, L2_PENDING, L3_PENDING)
ACTIVE = (DETECTED, *PENDING)
LEVEL_ROLE = {L1_PENDING: "elder", L2_PENDING: "caregiver", L3_PENDING: "neighbor"}
LEVEL_NAME = {L1_PENDING: "L1", L2_PENDING: "L2", L3_PENDING: "L3"}
NEXT = {DETECTED: L1_PENDING, L1_PENDING: L2_PENDING, L2_PENDING: L3_PENDING,
        L3_PENDING: EXHAUSTED}


@dataclass(frozen=True)
class Waits:
    """How long each level waits for an ack before the next one starts."""

    l1: timedelta = timedelta(minutes=30)
    l2: timedelta = timedelta(minutes=30)
    l3: timedelta = timedelta(minutes=30)

    def for_state(self, state: str) -> timedelta:
        return {L1_PENDING: self.l1, L2_PENDING: self.l2, L3_PENDING: self.l3}[state]


@dataclass(frozen=True)
class Notify:
    level: str  # "L1" | "L2" | "L3"
    role: str  # "elder" | "caregiver" | "neighbor"


@dataclass(frozen=True)
class StepResult:
    state: str
    level_started_at: datetime | None
    actions: tuple[Notify, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        return bool(self.actions) or self.state == EXHAUSTED


def step(state: str, level_started_at: datetime | None, now: datetime,
         waits: Waits) -> StepResult:
    """Advance at most one level. Call again until no actions are returned."""
    if state == DETECTED:
        return StepResult(L1_PENDING, now, (Notify("L1", "elder"),))
    if state in PENDING:
        started = level_started_at or now
        due = started + waits.for_state(state)
        if now < due:
            return StepResult(state, started)
        nxt = NEXT[state]
        if nxt == EXHAUSTED:
            return StepResult(EXHAUSTED, due)
        # The next level's clock starts when the previous one ran out, not when we noticed.
        return StepResult(nxt, due, (Notify(LEVEL_NAME[nxt], LEVEL_ROLE[nxt]),))
    return StepResult(state, level_started_at)


def can_acknowledge(state: str) -> bool:
    """Any open alert can be acknowledged, including one whose ladder is exhausted."""
    return state in ACTIVE or state == EXHAUSTED
