"""End-to-end with fakes: the real service, API and ladder, with a stubbed clock, an
in-memory database, a fake notifier and no Bedrock/Ring/Telegram calls."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.ai.bedrock import Bedrock
from app.config import get_settings
from app.core import clock
from app.core.clock import Clock
from app.db import session as db_session
from app.db.models import Anomaly, AuditLog, EscalationStep, NotificationLog
from app.db.session import init_engine, session_scope
from app.main import create_app
from app.notify.base import Recipient, SendResult
from app.service import CareLoop

IST = ZoneInfo("Asia/Kolkata")


class FakeNotifier:
    name = "fake"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, recipient: Recipient, text: str, ack_token: str | None = None) -> SendResult:
        self.sent.append((recipient.role, text))
        return SendResult("sent")


class NoBedrock(Bedrock):
    """Behaves like Bedrock with no model access: every call falls back."""

    def __init__(self) -> None:
        super().__init__("us-east-1", client=object())


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[CareLoop, FakeNotifier]]:
    previous_clock, previous_engine = clock.get_clock(), db_session._engine
    clock.set_clock(Clock(IST, speed=0, start=datetime(2026, 10, 22, 5, 0, tzinfo=IST)))
    init_engine("sqlite://")
    settings = replace(get_settings(), demo_mode=True, ack_secret="e2e-secret",
                       telegram_bot_token="", ring_access_token="",
                       bedrock_vision_model_id="", bedrock_text_model_id="",
                       person_name="Lakshmi", caregiver_name="Suresh", neighbor_name="Meena")
    fake = FakeNotifier()
    service = CareLoop(settings, bedrock=NoBedrock(), notifiers=[fake])
    yield service, fake
    clock.set_clock(previous_clock)
    db_session._engine = previous_engine


def run_until_done(service: CareLoop, max_minutes: int = 180) -> None:
    clock.get_clock().set_speed(0)
    for _ in range(max_minutes):
        service.tick()
        if service.demo.finished:
            return
        clock.get_clock().advance(timedelta(minutes=1))
    raise AssertionError("scenario did not finish")


def test_missed_morning_full_ladder(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    service.demo_seed(28)
    service.demo_run("missed-morning")
    run_until_done(service)
    with session_scope() as session:
        anomalies = session.exec(select(Anomaly)).all()
        assert len(anomalies) == 1
        anomaly = anomalies[0]
        assert anomaly.state == "EXHAUSTED"
        assert anomaly.explanation_source == "template"
        assert anomaly.scene_description == "camera image unavailable"
        levels = [s.level for s in session.exec(select(EscalationStep)).all()]
        assert levels == ["L1", "L2", "L3"]
        actions = {a.action for a in session.exec(select(AuditLog)).all()}
        assert {"ring.snapshot", "anomaly.detected", "notify.send"} <= actions
        assert len(session.exec(select(NotificationLog)).all()) == 3
    assert [role for role, _ in fake.sent] == ["elder", "caregiver", "neighbor"]
    assert fake.sent[0][1].startswith("Good morning Lakshmi.")
    assert "No one has been seen at Lakshmi's front door since 9:40 PM yesterday." in \
        fake.sent[1][1]
    assert "Meena" in fake.sent[2][1]


def test_elder_replies_stops_at_l1(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    service.demo_seed(28)
    service.demo_run("elder-replies")
    run_until_done(service)
    with session_scope() as session:
        anomaly = session.exec(select(Anomaly)).one()
        assert (anomaly.state, anomaly.acked_by) == ("ACKNOWLEDGED", "elder")
    assert [role for role, _ in fake.sent] == ["elder"]


def test_late_but_normal_raises_nothing(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    service.demo_seed(28)
    service.demo_run("late-but-normal")
    run_until_done(service)
    with session_scope() as session:
        assert session.exec(select(Anomaly)).all() == []
    assert fake.sent == []
    assert any("simulated event" in line["text"] for line in service.demo.log)


def test_camera_offline_degrades_without_false_alarm(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    service.demo_seed(28)
    service.demo_run("camera-offline")
    run_until_done(service)
    with session_scope() as session:
        assert session.exec(select(Anomaly)).all() == []
    assert len(fake.sent) == 1  # the caregiver is told once
    role, text = fake.sent[0]
    assert role == "caregiver" and "degraded since" in text


def test_api_end_to_end(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    client = TestClient(create_app(service.settings, start_loops=False, careloop=service))
    assert client.post("/api/demo/seed").json()["events"] > 100
    status = client.get("/api/status").json()
    assert status["status"] in {"normal", "waiting"} or status["label"] == "All normal"

    baseline = client.get("/api/baseline").json()
    assert baseline["state"] == "ready" and len(baseline["samples"]) == 4
    assert baseline["threshold"] == baseline["window"][1] + 45

    assert client.post("/api/demo/run", json={"scenario": "missed-morning"}).json()["ok"]
    clock.get_clock().set_speed(0)
    for _ in range(5):
        service.tick()
        clock.get_clock().advance(timedelta(minutes=1))
    status = client.get("/api/status").json()
    assert status["status"] == "escalating"
    anomaly_id = status["anomaly"]["id"]
    assert status["anomaly"]["level"] == "L1"

    ack = client.post(f"/api/anomalies/{anomaly_id}/ack", json={"by": "caregiver"})
    assert ack.json()["ok"]
    assert client.get(f"/api/anomalies/{anomaly_id}").json()["state"] == "ACKNOWLEDGED"
    assert client.get("/api/anomalies").json()["anomalies"][0]["acked_by"] == "caregiver"

    timeline = client.get("/api/timeline").json()
    assert timeline["threshold"] is not None
    audit = client.get("/api/audit").json()["entries"]
    assert any(e["action"] == "ack" for e in audit)
    assert client.get("/api/ring/health").json()["connected"] is False

    error = client.post("/api/demo/run", json={"scenario": "nope"})
    assert error.status_code == 400 and error.json()["error"]["code"] == "bad_scenario"
    assert client.get("/api/anomalies/999").json()["error"]["code"] == "not_found"
    assert client.get("/api/timeline?date=bad").json()["error"]["code"] == "bad_date"


def test_demo_endpoints_need_demo_mode(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, _ = svc
    service.settings = replace(service.settings, demo_mode=False)
    client = TestClient(create_app(service.settings, start_loops=False, careloop=service))
    response = client.post("/api/demo/seed")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "demo_disabled"


def test_long_silence_scenario(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    service.demo_seed(28)
    service.demo_run("long-silence")
    run_until_done(service, max_minutes=400)
    with session_scope() as session:
        anomaly = session.exec(select(Anomaly)).one()
        assert anomaly.kind == "A2" and anomaly.state == "EXHAUSTED"
        assert anomaly.facts["last_seen_ts"].endswith("09:30:00+05:30")
        reasons = {a.reason for a in session.exec(select(AuditLog)).all()}
        assert {"anomaly A2 verification", "anomaly A2 escalation L1"} <= reasons
        assert not any(r.startswith("anomaly A1") for r in reasons)
    assert [role for role, _ in fake.sent] == ["elder", "caregiver", "neighbor"]
    assert "since 9:30 AM today" in fake.sent[1][1]
    assert service.demo.log[0]["text"].startswith("Scenario long-silence starts. Long-silence")


def test_away_day_scenario(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, fake = svc
    service.demo_seed(28)
    service.demo_run("away-day")
    run_until_done(service)
    with session_scope() as session:
        assert session.exec(select(Anomaly)).all() == []
    assert fake.sent == []
    # another scenario afterwards removes the demo away period again
    service.demo_run("missed-morning")
    run_until_done(service)
    with session_scope() as session:
        assert len(session.exec(select(Anomaly)).all()) == 1


def test_away_api(svc: tuple[CareLoop, FakeNotifier]) -> None:
    service, _ = svc
    client = TestClient(create_app(service.settings, start_loops=False, careloop=service))
    client.post("/api/demo/seed")
    today = clock.now().astimezone(IST).date().isoformat()
    created = client.post("/api/away", json={"start": today, "end": today, "note": "Wedding"})
    assert created.json()["ok"]
    listing = client.get("/api/away").json()
    assert listing["away_today"] is True and listing["periods"][0]["note"] == "Wedding"
    assert client.get("/api/status").json()["status"] == "away"

    bad = client.post("/api/away", json={"start": today, "end": "2020-01-01"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_away_period"
    too_long = client.post("/api/away", json={"start": "2026-01-01", "end": "2026-12-31"})
    assert too_long.status_code == 400

    period_id = listing["periods"][0]["id"]
    assert client.delete(f"/api/away/{period_id}").json()["ok"]
    assert client.delete(f"/api/away/{period_id}").status_code == 404
    assert client.get("/api/status").json()["status"] != "away"
    actions = [e["action"] for e in client.get("/api/audit").json()["entries"]]
    assert "away.add" in actions and "away.remove" in actions
