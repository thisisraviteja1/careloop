"""JSON API for the dashboard. Errors use {"error": {"code", "message", "details"}}."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.ai.explainer import clock_time, last_seen_phrase
from app.baseline.model import (
    MIN_HISTORY_DAYS,
    at_minutes,
    compute_baseline,
    day_key,
    day_start,
    first_activity_by_day,
    minutes_after_midnight,
)
from app.core import clock
from app.db.models import (
    Anomaly,
    AuditLog,
    EscalationStep,
    Event,
    NotificationLog,
    from_db,
    to_db,
)
from app.db.session import session_scope
from app.demo.scenarios import SCENARIOS
from app.detection.detector import WEEKDAYS
from app.detection.runner import activity_times
from app.escalation.engine import ACTIVE, LEVEL_NAME
from app.ring.client import RingClient, RingError
from app.service import CareLoop

router = APIRouter(prefix="/api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def service(request: Request) -> CareLoop:
    return request.app.state.careloop


def local(moment: datetime | None, svc: CareLoop) -> str | None:
    return moment.astimezone(svc.tz).isoformat() if moment else None


def parse_day(value: str | None, svc: CareLoop) -> date:
    if not value:
        return day_key(clock.now().astimezone(svc.tz))
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(400, "bad_date", "Use YYYY-MM-DD.", {"date": value}) from exc


def require_demo(svc: CareLoop) -> None:
    if not svc.settings.demo_mode:
        raise ApiError(403, "demo_disabled", "Demo controls need DEMO_MODE=true.")


# ---- status --------------------------------------------------------------------------------

STATUS_TEXT = {
    "normal": ("All normal", "✅"),
    "waiting": ("All normal", "✅"),
    "unusual": ("Unusual", "⚠️"),
    "escalating": ("Escalating", "🔔"),
    "degraded": ("Monitoring degraded", "🛠"),
    "learning": ("Learning routine", "📚"),
}


@router.get("/status")
def get_status(request: Request) -> dict[str, Any]:
    svc = service(request)
    now = clock.now().astimezone(svc.tz)
    with session_scope() as session:
        result = svc.detect(session, create=False)
        anomaly = result.anomaly
        status = result.decision.status
        if status == "anomaly" or (anomaly and anomaly.state in ("EXHAUSTED", "DETECTED")):
            status = "unusual"
        if anomaly and anomaly.state in ACTIVE and anomaly.state != "DETECTED":
            status = "escalating"
        if result.decision.status == "degraded":
            status = "degraded"
        label, icon = STATUS_TEXT.get(status, STATUS_TEXT["normal"])
        last_seen = result.last_seen
        health = result.health
        payload: dict[str, Any] = {
            "status": status, "label": label, "icon": icon, "reason": result.decision.reason,
            "now": now.isoformat(), "now_text": clock_time(now),
            "person_name": svc.settings.person_name,
            "people": {"elder": svc.settings.person_name,
                       "caregiver": svc.settings.caregiver_name,
                       "neighbor": svc.settings.neighbor_name},
            "last_seen": local(last_seen, svc),
            "last_seen_text": last_seen_phrase(last_seen, now) if last_seen else None,
            "threshold_text": clock_time(result.decision.threshold_at)
            if result.decision.threshold_at else None,
            "learning_days": min(result.baseline.history_days, MIN_HISTORY_DAYS),
            "learning_needed": MIN_HISTORY_DAYS,
            "device": {"status": health.status if health else "unknown",
                       "since": local(from_db(health.since), svc) if health else None,
                       "since_text": clock_time(from_db(health.since).astimezone(svc.tz))
                       if health and health.since else None},
            "anomaly": anomaly_summary(session, anomaly, svc) if anomaly else None,
            "demo_mode": svc.settings.demo_mode,
            "clock_speed": clock.get_clock().speed,
        }
    return payload


# ---- timeline and baseline -----------------------------------------------------------------

@router.get("/timeline")
def get_timeline(request: Request, date: str | None = None) -> dict[str, Any]:  # noqa: A002
    svc = service(request)
    day = parse_day(date, svc)
    start = day_start(day, svc.tz)
    now = clock.now()
    end = min(start + timedelta(days=1), now)
    with session_scope() as session:
        rows = session.exec(select(Event).where(Event.ts >= to_db(start), Event.ts <= to_db(end))
                            .order_by(Event.ts)).all()
        baseline = compute_baseline(
            first_activity_by_day(activity_times(session, now), svc.tz), day,
            svc.settings.margin_minutes)
    return {
        "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
        "start": local(start, svc), "now": local(now, svc),
        "now_minutes": minutes_after_midnight(now.astimezone(svc.tz), day),
        "window": [baseline.window_start, baseline.window_end],
        "threshold": baseline.threshold,
        "events": [{
            "ts": local(from_db(e.ts), svc), "time": clock_time(from_db(e.ts).astimezone(svc.tz)),
            "minutes": minutes_after_midnight(from_db(e.ts).astimezone(svc.tz), day),
            "type": e.type, "sub_type": e.sub_type, "is_activity": e.is_activity,
            "is_synthetic": e.is_synthetic,
        } for e in rows],
    }


@router.get("/baseline")
def get_baseline(request: Request, date: str | None = None) -> dict[str, Any]:  # noqa: A002
    svc = service(request)
    day = parse_day(date, svc)
    now = clock.now()
    with session_scope() as session:
        first = first_activity_by_day(activity_times(session, now), svc.tz)
    baseline = compute_baseline(first, day, svc.settings.margin_minutes)
    history = {d: m for d, m in first.items() if d < day}
    used = [d for d, m in sorted(history.items())
            if baseline.pooled or d.weekday() == day.weekday()]
    return {
        "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
        "state": baseline.state, "pooled": baseline.pooled,
        "history_days": baseline.history_days,
        "samples": [{"date": d.isoformat(), "minutes": history[d],
                     "time": clock_time(at_minutes(d, history[d], svc.tz))} for d in used],
        "window": [baseline.window_start, baseline.window_end],
        "threshold": baseline.threshold, "margin": baseline.margin,
        "window_text": [clock_time(at_minutes(day, m, svc.tz)) if m is not None else None
                        for m in (baseline.window_start, baseline.window_end)],
        "threshold_text": clock_time(at_minutes(day, baseline.threshold, svc.tz))
        if baseline.threshold is not None else None,
        "today_minutes": first.get(day),
        "now_minutes": minutes_after_midnight(now.astimezone(svc.tz), day),
    }


# ---- anomalies ----------------------------------------------------------------------------

def anomaly_summary(session: Session, anomaly: Anomaly, svc: CareLoop) -> dict[str, Any]:
    steps = session.exec(select(EscalationStep).where(EscalationStep.anomaly_id == anomaly.id)
                         .order_by(EscalationStep.id)).all()
    notes = session.exec(select(NotificationLog).where(NotificationLog.anomaly_id == anomaly.id)
                         .order_by(NotificationLog.id)).all()
    acked = from_db(anomaly.acked_at)
    return {
        "id": anomaly.id, "kind": anomaly.kind, "day": anomaly.day, "state": anomaly.state,
        "level": LEVEL_NAME.get(anomaly.state),
        "detected_at": local(from_db(anomaly.detected_at), svc),
        "detected_text": clock_time(from_db(anomaly.detected_at).astimezone(svc.tz)),
        "facts": anomaly.facts, "scene_description": anomaly.scene_description,
        "explanation": anomaly.explanation, "explanation_source": anomaly.explanation_source,
        "acked_at": local(acked, svc),
        "acked_text": clock_time(acked.astimezone(svc.tz)) if acked else None,
        "acked_by": anomaly.acked_by, "ack_source": anomaly.ack_source,
        "steps": [{"level": s.level, "role": s.recipient_role, "outcome": s.outcome,
                   "time": clock_time(from_db(s.started_at).astimezone(svc.tz))} for s in steps],
        "notifications": [{"channel": n.channel, "role": n.recipient_role, "status": n.status,
                           "kind": n.kind, "text": n.text,
                           "time": clock_time(from_db(n.ts).astimezone(svc.tz))} for n in notes],
    }


@router.get("/anomalies")
def list_anomalies(request: Request) -> dict[str, Any]:
    svc = service(request)
    with session_scope() as session:
        rows = session.exec(select(Anomaly).order_by(Anomaly.id.desc()).limit(20)).all()
        return {"anomalies": [anomaly_summary(session, a, svc) for a in rows]}


@router.get("/anomalies/{anomaly_id}")
def get_anomaly(request: Request, anomaly_id: int) -> dict[str, Any]:
    svc = service(request)
    with session_scope() as session:
        anomaly = session.get(Anomaly, anomaly_id)
        if anomaly is None:
            raise ApiError(404, "not_found", "No such alert.", {"id": anomaly_id})
        return anomaly_summary(session, anomaly, svc)


class AckBody(BaseModel):
    by: str = "caregiver"


@router.post("/anomalies/{anomaly_id}/ack")
def ack_anomaly(request: Request, anomaly_id: int, body: AckBody | None = None) -> dict[str, Any]:
    svc = service(request)
    role = (body or AckBody()).by
    if role not in {"elder", "caregiver", "neighbor"}:
        raise ApiError(400, "bad_role", "by must be elder, caregiver or neighbor.")
    result = svc.acknowledge(anomaly_id, role, "dashboard")
    if not result.ok:
        raise ApiError(404 if result.anomaly is None else 409, "ack_failed", result.message)
    return {"ok": True, "message": result.message}


# ---- audit and Ring health ------------------------------------------------------------------

@router.get("/audit")
def get_audit(request: Request, limit: int = 50) -> dict[str, Any]:
    svc = service(request)
    with session_scope() as session:
        rows = session.exec(select(AuditLog).order_by(AuditLog.id.desc())
                            .limit(max(1, min(limit, 500)))).all()
        return {"entries": [{
            "ts": local(from_db(r.ts), svc), "time": clock_time(from_db(r.ts).astimezone(svc.tz)),
            "action": r.action, "reason": r.reason, "outcome": r.outcome} for r in rows]}


@router.get("/ring/health")
def ring_health(request: Request) -> dict[str, Any]:
    """A live `GET /v1/users/me` call when a token is configured, even in demo mode."""
    svc = service(request)
    token = svc.settings.ring_access_token
    data_source = "synthetic demo history" if svc.settings.demo_mode else svc.settings.ring_mode
    if not token:
        return {"connected": False, "mode": data_source,
                "message": "No Ring token set. Demo data is synthetic."}
    client = None
    try:
        client = RingClient("live", token)
        client.users_me()
        devices = len(client.list_devices())
    except RingError as exc:
        return {"connected": False, "mode": data_source, "message": str(exc)}
    finally:
        if client is not None:
            client.close()
    return {"connected": True, "mode": data_source, "devices": devices,
            "message": f"Ring API connected ({devices} device{'s' if devices != 1 else ''})."}


# ---- demo -------------------------------------------------------------------------------------

class RunBody(BaseModel):
    scenario: str = "missed-morning"
    speed: float | None = None


@router.get("/demo/state")
def demo_state(request: Request) -> dict[str, Any]:
    svc = service(request)
    demo = svc.demo
    return {"enabled": svc.settings.demo_mode, "scenarios": SCENARIOS,
            "scenario": demo.scenario if demo else None,
            "finished": demo.finished if demo else None,
            "log": demo.log if demo else [], "speed": clock.get_clock().speed}


@router.post("/demo/seed")
def demo_seed(request: Request) -> dict[str, Any]:
    svc = service(request)
    require_demo(svc)
    return {"ok": True, "events": svc.demo_seed(28)}


@router.post("/demo/run")
def demo_run(request: Request, body: RunBody) -> dict[str, Any]:
    svc = service(request)
    require_demo(svc)
    if body.scenario not in SCENARIOS:
        raise ApiError(400, "bad_scenario", "Unknown scenario.", {"choices": list(SCENARIOS)})
    if body.speed is not None and not 1 <= body.speed <= 600:
        raise ApiError(400, "bad_speed", "Speed must be between 1 and 600.")
    state = svc.demo_run(body.scenario, body.speed)
    return {"ok": True, "scenario": state.scenario, "starts_at": local(state.started_at, svc)}


@router.post("/demo/reset")
def demo_reset(request: Request) -> dict[str, Any]:
    svc = service(request)
    require_demo(svc)
    svc.demo_reset()
    return {"ok": True}
