"""CareLoop orchestration: one tick = poll Ring (live) → detect → verify and explain new
anomalies → escalate. Also owns demo scenarios and acknowledgements."""

from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, delete, select

from app import audit
from app.ai.bedrock import Bedrock
from app.ai.explainer import (
    checkin_message,
    clock_time,
    degraded_message,
    explain,
    neighbor_message,
)
from app.baseline.model import at_minutes, day_key, day_start
from app.config import REPO_ROOT, Settings
from app.core import clock
from app.core.tokens import TokenError, verify_ack
from app.db.models import (
    Anomaly,
    DeviceHealth,
    EscalationStep,
    Event,
    NotificationLog,
    from_db,
    to_db,
)
from app.db.session import get_engine, reset_db, session_scope
from app.demo.scenarios import SCENARIOS, DemoState, plan
from app.demo.seed import DEMO_DEVICE_ID, seed_history
from app.detection.runner import DetectionResult, run_detection
from app.escalation.engine import ACKNOWLEDGED, ACTIVE, L1_PENDING, Waits
from app.escalation.runner import AckResult, EscalationRunner, acknowledge, deliver
from app.notify.base import Notifier, Recipient
from app.notify.dashboard import DashboardNotifier
from app.notify.telegram import TelegramNotifier
from app.ring.client import RingAuthError, RingClient, RingError
from app.ring.events import is_activity
from app.ring.poller import sync_once, update_health
from app.vision.snapshot import describe, take_snapshot

logger = logging.getLogger(__name__)

FIXTURE_SNAPSHOT = REPO_ROOT / "fixtures" / "demo_snapshot.jpg"
UNSAFE_SECRETS = {"", "change-me"}


@dataclass
class RingStatus:
    mode: str
    ok: bool
    message: str
    checked_at: datetime | None = None


class CareLoop:
    def __init__(self, settings: Settings, *, ring: RingClient | None = None,
                 bedrock: Bedrock | None = None,
                 notifiers: list[Notifier] | None = None) -> None:
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self.ack_secret = settings.ack_secret
        if self.ack_secret in UNSAFE_SECRETS:
            self.ack_secret = secrets.token_urlsafe(32)
            logger.warning("ACK_SECRET is not set: using a random secret for this run. "
                           "Ack links stop working after a restart.")
        self.ring_status = RingStatus("demo" if settings.demo_mode else settings.ring_mode,
                                      True, "not checked yet")
        self.ring = ring
        if ring is None and not settings.demo_mode:
            try:
                self.ring = RingClient(settings.ring_mode, settings.ring_access_token)
            except RingError as exc:
                self.ring_status = RingStatus(settings.ring_mode, False, str(exc))
        self.bedrock = bedrock if bedrock is not None else Bedrock(settings.aws_region)
        self.telegram: TelegramNotifier | None = None
        if notifiers is None:
            notifiers = [DashboardNotifier()]
            if settings.telegram_bot_token:
                self.telegram = TelegramNotifier(settings.telegram_bot_token, self.ack_url)
                notifiers.append(self.telegram)
        self.notifiers = notifiers
        self.waits = Waits(timedelta(minutes=settings.l1_wait_minutes),
                           timedelta(minutes=settings.l2_wait_minutes),
                           timedelta(minutes=settings.l2_wait_minutes))
        self.demo: DemoState | None = None
        self._device_id = settings.ring_device_id
        self._lock = threading.RLock()

    # ---- wiring ----------------------------------------------------------------------------

    @property
    def device_id(self) -> str:
        if self.settings.demo_mode:
            return DEMO_DEVICE_ID
        if not self._device_id and self.ring is not None:
            self._device_id = self.ring.first_device_id() or ""
        return self._device_id

    def ack_url(self, token: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/ack/{token}"

    def recipients(self) -> dict[str, Recipient]:
        s = self.settings
        return {
            "elder": Recipient("elder", s.person_name, s.telegram_chat_elder),
            "caregiver": Recipient("caregiver", s.caregiver_name, s.telegram_chat_caregiver),
            "neighbor": Recipient("neighbor", s.neighbor_name, s.telegram_chat_neighbor),
        }

    def message_for(self, anomaly: Anomaly, role: str, now: datetime) -> str:
        local = now.astimezone(self.tz)
        if role == "elder":
            return checkin_message(self.settings.person_name, local)
        if role == "neighbor":
            return neighbor_message(anomaly.facts, self.settings.caregiver_name,
                                    self.settings.neighbor_name, local)
        return anomaly.explanation or ""

    def runner(self) -> EscalationRunner:
        return EscalationRunner(waits=self.waits, recipients=self.recipients(),
                                notifiers=self.notifiers, message=self.message_for,
                                ack_secret=self.ack_secret)

    def detect(self, session: Session, create: bool = True) -> DetectionResult:
        return run_detection(session, tz=self.tz, margin=self.settings.margin_minutes,
                             person_name=self.settings.person_name, device_id=self.device_id,
                             create=create)

    # ---- the tick ----------------------------------------------------------------------------

    def tick(self) -> None:
        """One pass of the loop. Safe to call from a worker thread."""
        with self._lock, session_scope() as session:
            now = clock.now()
            if self.demo is not None:
                self._apply_demo(session, now)
            elif self.ring is not None:
                self._poll(session)
            result = self.detect(session)
            if result.created and result.anomaly is not None:
                self._on_new_anomaly(session, result.anomaly, now)
            if result.notify_degraded and result.health is not None:
                self._notify_degraded(session, result, now)
            runner = self.runner()
            for anomaly in session.exec(select(Anomaly).where(Anomaly.state.in_(ACTIVE))).all():
                runner.advance(session, anomaly, now)
            if self.demo is not None:
                self._demo_after_tick(session, now)

    def _poll(self, session: Session) -> None:
        if not self.device_id:
            self.ring_status = RingStatus("live", False, "No Ring device visible to this token.",
                                          clock.now())
            return
        try:
            result = sync_once(session, self.ring, self.device_id)
        except RingAuthError as exc:
            update_health(session, self.device_id, "error")
            self.ring_status = RingStatus("live", False, str(exc), clock.now())
            return
        ok = result.error is None
        self.ring_status = RingStatus("live", ok, "connected" if ok else result.error or "",
                                      clock.now())

    def _on_new_anomaly(self, session: Session, anomaly: Anomaly, now: datetime) -> None:
        record = audit.recorder(session)
        self.bedrock.audit = record
        audit.record(session, "anomaly.detected", "A1 late start",
                     f"no activity by {anomaly.facts.get('threshold')}")
        if self.settings.demo_mode or self.ring is None:
            image = take_snapshot(self._fixture_snapshot, record)
        else:
            image = take_snapshot(lambda: self.ring.get_snapshot(self.device_id), record)
        anomaly.scene_description = describe(image, self.bedrock,
                                             self.settings.bedrock_vision_model_id)
        del image  # bytes never leave memory
        explanation = explain(anomaly.facts, anomaly.scene_description, now,
                              now.astimezone(self.tz), self.bedrock,
                              self.settings.bedrock_text_model_id)
        anomaly.explanation = explanation.text
        anomaly.explanation_source = explanation.source
        session.add(anomaly)
        session.flush()

    @staticmethod
    def _fixture_snapshot() -> bytes | None:
        return FIXTURE_SNAPSHOT.read_bytes() if FIXTURE_SNAPSHOT.is_file() else None

    def _notify_degraded(self, session: Session, result: DetectionResult, now: datetime) -> None:
        health = result.health
        text = degraded_message(self.settings.person_name, health.status, from_db(health.since),
                                now.astimezone(self.tz))
        deliver(session, self.notifiers, self.recipients()["caregiver"], text, None,
                anomaly_id=None, kind="monitoring degraded",
                reason="device health guard", now=now)
        health.caregiver_notified = True
        session.add(health)

    # ---- acknowledgements --------------------------------------------------------------------

    def acknowledge(self, anomaly_id: int, role: str, source: str) -> AckResult:
        with self._lock, session_scope() as session:
            return acknowledge(session, anomaly_id, role, source, clock.now())

    def handle_telegram_ack(self, token: str, chat_id: str) -> str:
        try:
            claim = verify_ack(self.ack_secret, token, clock.now())
        except TokenError:
            return "This button has expired. Nothing else is needed."
        label = "I'm OK" if claim.role == "elder" else "I'm handling it"
        return self.acknowledge(claim.anomaly_id, claim.role, f"telegram ({label})").message

    # ---- demo ----------------------------------------------------------------------------------

    def demo_seed(self, days: int = 28) -> int:
        """Fresh database with synthetic history; the clock waits at 05:30 today."""
        with self._lock:
            self.demo = None
            reset_db(get_engine())
            today = day_key(clock.now().astimezone(self.tz))
            with session_scope() as session:
                count = seed_history(session, today, days, self.tz)
                audit.record(session, "demo.seed", "demo controls",
                             f"{count} synthetic events over {days} days")
            clock.get_clock().set_time(day_start(today, self.tz).replace(hour=5, minute=30))
            clock.get_clock().set_speed(0)
            return count

    def demo_run(self, scenario: str, speed: float | None = None) -> DemoState:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        with self._lock:
            with session_scope() as session:
                if not session.exec(select(Event).where(Event.is_synthetic == True)).first():  # noqa: E712
                    seed_history(session, day_key(clock.now().astimezone(self.tz)), 28, self.tz)
            with session_scope() as session:
                today = day_key(clock.now().astimezone(self.tz))
                self._clear_day(session, today)
                clock.get_clock().set_time(day_start(today, self.tz).replace(hour=5))
                result = self.detect(session, create=False)
                if result.baseline.threshold is None:
                    raise ValueError("Not enough history: seed first.")
                threshold_at = at_minutes(today, result.baseline.threshold, self.tz)
                state = plan(scenario, day_start(today, self.tz), threshold_at)
                health = session.get(DeviceHealth, DEMO_DEVICE_ID) or DeviceHealth(
                    device_id=DEMO_DEVICE_ID)
                health.status, health.since = state.device_status, to_db(state.started_at)
                health.caregiver_notified = False
                session.add(health)
                audit.record(session, "demo.run", "demo controls", scenario)
            self.demo = state
            self._log(f"Scenario {scenario} starts. Alert threshold today: "
                      f"{clock_time(threshold_at)}.", state.started_at)
            clock.get_clock().set_time(state.started_at)
            clock.get_clock().set_speed(speed or self.settings.clock_speed)
            return state

    def demo_reset(self) -> None:
        with self._lock:
            self.demo = None
            reset_db(get_engine())
            clock.get_clock().reset_to_real_time()

    def _clear_day(self, session: Session, today: date) -> None:
        start = day_start(today, self.tz)
        ids = [a.id for a in session.exec(select(Anomaly).where(Anomaly.day == today.isoformat()))]
        if ids:
            session.exec(delete(EscalationStep).where(EscalationStep.anomaly_id.in_(ids)))
            session.exec(delete(NotificationLog).where(NotificationLog.anomaly_id.in_(ids)))
            session.exec(delete(Anomaly).where(Anomaly.id.in_(ids)))
        session.exec(delete(NotificationLog).where(NotificationLog.anomaly_id == None,  # noqa: E711
                                                   NotificationLog.ts >= to_db(start)))
        session.exec(delete(Event).where(Event.ts >= to_db(start)))

    def _log(self, text: str, at: datetime | None = None) -> None:
        if self.demo is None:
            return
        moment = (at or clock.now()).astimezone(self.tz)
        self.demo.log.append({"time": clock_time(moment), "text": text})
        logger.info("[demo %s] %s", clock_time(moment), text)

    def _apply_demo(self, session: Session, now: datetime) -> None:
        demo = self.demo
        due = [e for e in demo.events if e.at <= now]
        for event in due:
            session.add(Event(ring_event_id=f"demo-{event.at.isoformat()}",
                              device_id=DEMO_DEVICE_ID, type=event.type, sub_type=event.sub_type,
                              ts=event.at, is_activity=is_activity(event.type, event.sub_type),
                              is_synthetic=True))
            self._log(f"Doorbell sees {event.sub_type or event.type} motion "
                      f"(simulated event).", event.at)
        demo.events = [e for e in demo.events if e.at > now]
        if due:
            session.flush()

    def _demo_after_tick(self, session: Session, now: datetime) -> None:
        demo = self.demo
        today = day_key(now.astimezone(self.tz)).isoformat()
        anomaly = session.exec(select(Anomaly).where(Anomaly.day == today)).first()
        if anomaly is not None:
            self._log_ladder(session, anomaly)
            if (demo.elder_ack_delay and anomaly.state == L1_PENDING
                    and now >= from_db(anomaly.level_started_at) + demo.elder_ack_delay):
                acknowledge(session, anomaly.id, "elder", "demo (simulated tap on I'm OK)", now)
                self._log(f"{self.settings.person_name} taps “I'm OK” (simulated). "
                          "The ladder stops.", now)
            if anomaly.state in (ACKNOWLEDGED, "EXHAUSTED"):
                self._finish(f"Alert {anomaly.state.lower()}.")
        if demo.finish_after and now >= demo.finish_after and not demo.finished:
            self._finish("Threshold passed without an alert." if anomaly is None
                         else "Scenario window over.")

    def _log_ladder(self, session: Session, anomaly: Anomaly) -> None:
        seen = {e["text"] for e in self.demo.log}
        text = f"No activity by the threshold: alert raised ({anomaly.explanation_source})."
        if text not in seen and anomaly.explanation:
            self._log(text, from_db(anomaly.detected_at))
        steps = session.exec(select(EscalationStep).where(
            EscalationStep.anomaly_id == anomaly.id).order_by(EscalationStep.id)).all()
        names = {"elder": "check-in", "caregiver": "caregiver alert", "neighbor": "neighbor"}
        for s in steps:
            line = f"{s.level}: {names[s.recipient_role]} sent to {s.recipient_role} ({s.outcome})."
            if line not in seen:
                self._log(line, from_db(s.started_at))

    def _finish(self, text: str) -> None:
        if self.demo is None or self.demo.finished:
            return
        self._log(f"{text} Demo finished; clock paused.")
        self.demo.finished = True
        clock.get_clock().set_speed(0)
