import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.ack import router as ack_router
from app.core.clock import Clock
from app.core.tokens import TokenError, sign_ack, verify_ack
from app.db import session as db_session
from app.db.models import Anomaly, AuditLog, EscalationStep, NotificationLog
from app.escalation.engine import (
    ACKNOWLEDGED,
    DETECTED,
    EXHAUSTED,
    L1_PENDING,
    L2_PENDING,
    Waits,
    step,
)
from app.escalation.runner import EscalationRunner, acknowledge
from app.notify.base import Recipient, SendResult
from app.notify.dashboard import DashboardNotifier
from app.notify.telegram import TelegramNotifier, poll_once

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 10, 22, 8, 0, tzinfo=IST)
SECRET = "test-secret"
WAITS = Waits(timedelta(minutes=30), timedelta(minutes=30), timedelta(minutes=30))
PEOPLE = {
    "elder": Recipient("elder", "Lakshmi", "100"),
    "caregiver": Recipient("caregiver", "Suresh", "200"),
    "neighbor": Recipient("neighbor", "Meena", ""),
}


class FakeNotifier:
    name = "fake"

    def __init__(self, fail: bool = False, explode: bool = False) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.fail, self.explode = fail, explode

    def send(self, recipient: Recipient, text: str, ack_token: str | None = None) -> SendResult:
        self.sent.append((recipient.role, text, ack_token))
        if self.explode:
            raise RuntimeError("adapter crashed")
        return SendResult("failed", "down") if self.fail else SendResult("sent")


def make_anomaly(session: Session) -> Anomaly:
    anomaly = Anomaly(kind="A1", day="2026-10-22", detected_at=T0, facts={}, state=DETECTED)
    session.add(anomaly)
    session.commit()
    return anomaly


def runner(*notifiers: object) -> EscalationRunner:
    return EscalationRunner(waits=WAITS, recipients=PEOPLE, notifiers=list(notifiers),
                            message=lambda a, role, now: f"message for {role}",
                            ack_secret=SECRET)


def roles(fake: FakeNotifier) -> list[str]:
    return [role for role, _, _ in fake.sent]


# ---- pure state machine -----------------------------------------------------------------------

def test_step_timeline() -> None:
    r = step(DETECTED, None, T0, WAITS)
    assert (r.state, [a.role for a in r.actions]) == (L1_PENDING, ["elder"])
    assert step(L1_PENDING, T0, T0 + timedelta(minutes=29), WAITS).actions == ()
    r = step(L1_PENDING, T0, T0 + timedelta(minutes=31), WAITS)
    assert (r.state, r.level_started_at) == (L2_PENDING, T0 + timedelta(minutes=30))
    assert step(ACKNOWLEDGED, T0, T0 + timedelta(hours=5), WAITS).state == ACKNOWLEDGED


# ---- runner ------------------------------------------------------------------------------------

def test_ack_at_l1_stops_everything(session: Session, frozen_clock: Clock) -> None:
    fake = FakeNotifier()
    anomaly = make_anomaly(session)
    run = runner(fake)
    run.advance(session, anomaly, T0)
    assert acknowledge(session, anomaly.id, "elder", "test", T0 + timedelta(minutes=5)).ok
    run.advance(session, anomaly, T0 + timedelta(hours=3))
    assert roles(fake) == ["elder"]
    assert anomaly.state == ACKNOWLEDGED


def test_ack_at_l2_stops_l3(session: Session, frozen_clock: Clock) -> None:
    fake = FakeNotifier()
    anomaly = make_anomaly(session)
    run = runner(fake)
    run.advance(session, anomaly, T0)
    run.advance(session, anomaly, T0 + timedelta(minutes=31))
    assert anomaly.state == L2_PENDING
    acknowledge(session, anomaly.id, "caregiver", "test", T0 + timedelta(minutes=40))
    run.advance(session, anomaly, T0 + timedelta(hours=3))
    assert roles(fake) == ["elder", "caregiver"]


def test_no_ack_reaches_exhausted(session: Session, frozen_clock: Clock) -> None:
    fake = FakeNotifier()
    anomaly = make_anomaly(session)
    run = runner(fake)
    run.advance(session, anomaly, T0)
    run.advance(session, anomaly, T0 + timedelta(hours=2))  # catches up in one tick
    assert roles(fake) == ["elder", "caregiver", "neighbor"]
    assert anomaly.state == EXHAUSTED
    session.commit()
    steps = session.exec(select(EscalationStep).order_by(EscalationStep.id)).all()
    assert [s.level for s in steps] == ["L1", "L2", "L3"]
    assert [s.started_at for s in steps] == [T0 + timedelta(minutes=30 * i) for i in range(3)]
    # an exhausted alert can still be acknowledged
    assert acknowledge(session, anomaly.id, "neighbor", "test", T0 + timedelta(hours=3)).ok


def test_notifier_failure_still_advances_the_ladder(session: Session,
                                                     frozen_clock: Clock) -> None:
    broken, crashing, good = FakeNotifier(fail=True), FakeNotifier(explode=True), FakeNotifier()
    anomaly = make_anomaly(session)
    run = runner(broken, crashing, good)
    run.advance(session, anomaly, T0)
    run.advance(session, anomaly, T0 + timedelta(minutes=31))
    assert anomaly.state == L2_PENDING
    assert roles(broken) == ["elder", "elder", "caregiver", "caregiver"]  # one retry each
    assert roles(good) == ["elder", "caregiver"]
    session.commit()
    statuses = [n.status for n in session.exec(select(NotificationLog)).all()]
    assert statuses.count("failed") == 4 and statuses.count("sent") == 2
    outcomes = [a.outcome for a in session.exec(select(AuditLog)).all()]
    assert any("failed" in o for o in outcomes)


def test_tokens_in_messages_are_valid_and_text_has_no_token(session: Session,
                                                            frozen_clock: Clock) -> None:
    fake = FakeNotifier()
    anomaly = make_anomaly(session)
    runner(fake).advance(session, anomaly, T0)
    role, text, token = fake.sent[0]
    claim = verify_ack(SECRET, token, T0)
    assert (claim.anomaly_id, claim.role) == (anomaly.id, "elder")
    assert len("ack:" + token) <= 64  # fits Telegram callback_data
    session.commit()
    assert all(token not in n.text for n in session.exec(select(NotificationLog)).all())


# ---- tokens ------------------------------------------------------------------------------------

def test_tampered_or_expired_tokens_are_rejected() -> None:
    token = sign_ack(SECRET, 7, "caregiver", T0 + timedelta(hours=1))
    assert verify_ack(SECRET, token, T0).role == "caregiver"
    head, sig = token.rsplit(".", 1)
    for bad in (head.replace("7.", "8.", 1) + "." + sig, head + "." + sig[:-1] + "A",
                "garbage", token + ".x"):
        with pytest.raises(TokenError):
            verify_ack(SECRET, bad, T0)
    with pytest.raises(TokenError):
        verify_ack("other-secret", token, T0)
    with pytest.raises(TokenError, match="expired"):
        verify_ack(SECRET, token, T0 + timedelta(hours=2))


# ---- Telegram ------------------------------------------------------------------------------------

def test_telegram_send_and_callback_round_trip() -> None:
    requests: list[tuple[str, dict]] = []
    token = sign_ack(SECRET, 3, "elder", T0 + timedelta(hours=1))

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path.rsplit("/", 1)[-1], body))
        if request.url.path.endswith("getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [{
                "update_id": 41, "callback_query": {
                    "id": "cb1", "data": f"ack:{token}", "message": {"chat": {"id": 100}}}}]})
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramNotifier("BOT", lambda t: f"http://127.0.0.1:8000/ack/{t}",
                           transport=httpx.MockTransport(handler))
    assert bot.send(PEOPLE["elder"], "Good morning Lakshmi.", token).status == "sent"
    method, body = requests[0]
    assert method == "sendMessage" and body["chat_id"] == "100"
    button = body["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "I'm OK", "callback_data": f"ack:{token}"}
    assert f"/ack/{token}" in body["text"]

    handled: list[tuple[str, str]] = []
    offset = poll_once(bot, None, lambda t, chat: handled.append((t, chat)) or "Thanks!",
                       timeout=0)
    assert offset == 42
    assert handled == [(token, "100")]
    assert requests[-1] == ("answerCallbackQuery", {"callback_query_id": "cb1",
                                                    "text": "Thanks!"})


def test_telegram_skips_people_without_chat_and_reports_api_errors() -> None:
    bot = TelegramNotifier("BOT", str, transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"ok": False, "description": "chat not found"})))
    assert bot.send(PEOPLE["neighbor"], "hi").status == "skipped"
    result = bot.send(PEOPLE["caregiver"], "hi")
    assert (result.status, result.detail) == ("failed", "sendMessage: chat not found")


def test_dashboard_notifier_always_delivers() -> None:
    assert DashboardNotifier().send(PEOPLE["elder"], "hi").status == "sent"


# ---- big-button page --------------------------------------------------------------------------

@pytest.fixture
def ack_app(engine: object, frozen_clock: Clock) -> TestClient:
    previous = db_session._engine
    db_session._engine = engine
    app = FastAPI()
    app.include_router(ack_router)
    app.state.careloop = SimpleNamespace(ack_secret=SECRET,
                                         settings=SimpleNamespace(person_name="Lakshmi"))
    yield TestClient(app)
    db_session._engine = previous


def test_ack_page_flow(ack_app: TestClient, session: Session, frozen_clock: Clock) -> None:
    anomaly = make_anomaly(session)
    now = frozen_clock.now()
    token = sign_ack(SECRET, anomaly.id, "elder", now + timedelta(hours=1))

    page = ack_app.get(f"/ack/{token}")
    assert page.status_code == 200
    html = page.text
    assert "Hello Lakshmi" in html and "I&#x27;m OK" in html
    assert 'lang="en"' in html and "min-height: 88px" in html
    assert html.index("I&#x27;m OK") < html.index("I&#x27;m handling it")

    done = ack_app.post(f"/ack/{token}", content="choice=ok",
                        headers={"content-type": "application/x-www-form-urlencoded"})
    assert done.status_code == 200 and "stopped the alert" in done.text
    session.expire_all()
    stored = session.get(Anomaly, anomaly.id)
    assert (stored.state, stored.acked_by) == (ACKNOWLEDGED, "elder")
    assert stored.ack_source == "ack page (I'm OK)"
    assert "already been handled" in ack_app.get(f"/ack/{token}").text


def test_ack_page_rejects_bad_tokens_calmly(ack_app: TestClient, session: Session) -> None:
    anomaly = make_anomaly(session)
    good = sign_ack(SECRET, anomaly.id, "caregiver", datetime(2030, 1, 1, tzinfo=UTC))
    tampered = good[:-2] + ("AA" if not good.endswith("AA") else "BB")
    for token in (tampered, "nonsense"):
        assert ack_app.get(f"/ack/{token}").status_code == 404
        response = ack_app.post(f"/ack/{token}", content="choice=ok")
        assert response.status_code == 404 and "isn" in response.text
    session.expire_all()
    assert session.get(Anomaly, anomaly.id).state == DETECTED
