from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import pytest
from botocore.stub import ANY, Stubber

from app.ai.bedrock import Bedrock, BedrockError, image_format
from app.ai.explainer import (
    alert_parts,
    checkin_message,
    clock_time,
    degraded_message,
    explain,
    last_seen_phrase,
    neighbor_message,
    template_alert,
    validate_alert,
    window_phrase,
)
from app.ai.safety import blocked_terms
from app.vision.snapshot import CAMERA_UNAVAILABLE, clean_scene, describe, take_snapshot

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 22, 8, 10, tzinfo=IST)  # Thursday
JPEG = (Path(__file__).resolve().parents[2] / "fixtures" / "demo_snapshot.jpg").read_bytes()
FACTS: dict[str, Any] = {
    "kind": "A1", "day": "2026-10-22", "person_name": "Lakshmi",
    "last_seen_ts": "2026-10-21T21:40:00+05:30", "usual_window_start": "06:45",
    "usual_window_end": "07:20", "threshold": "08:05", "weekday": "Thursday",
    "sample_count": 4, "pooled": False, "margin_minutes": 45,
}
SCENE = "a closed front door with a milk packet on the mat; no person visible"


def converse_response(text: str) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 50, "outputTokens": 20, "totalTokens": 70},
        "metrics": {"latencyMs": 100},
    }


class Audit(list):
    def __call__(self, action: str, reason: str, outcome: str) -> None:
        self.append((action, reason, outcome))


@pytest.fixture
def stubbed() -> tuple[Bedrock, Stubber, Audit]:
    client = boto3.client("bedrock-runtime", region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    audit = Audit()
    stubber = Stubber(client)
    stubber.activate()
    yield Bedrock("us-east-1", client=client, audit=audit), stubber, audit
    stubber.deactivate()


# ---- Bedrock wrapper -----------------------------------------------------------------------

def test_image_request_matches_converse_schema(stubbed: tuple) -> None:
    bedrock, stubber, audit = stubbed
    expected = {"modelId": "vision-model", "messages": ANY, "inferenceConfig": ANY}
    stubber.add_response("converse", converse_response(SCENE), expected)
    assert describe(JPEG, bedrock, "vision-model") == SCENE
    stubber.assert_no_pending_responses()
    action, reason, outcome = audit[0]
    assert (action, reason) == ("bedrock.converse.image", "anomaly A1 verification")
    assert outcome.startswith("ok") and "milk" not in outcome  # no content in the audit log


def test_bedrock_exception_falls_back(stubbed: tuple) -> None:
    bedrock, stubber, audit = stubbed
    stubber.add_client_error("converse", service_error_code="ThrottlingException",
                             http_status_code=429)
    with pytest.raises(BedrockError):
        bedrock.converse_text("text-model", "hi", reason="test")
    assert audit[-1][2].startswith("error: ThrottlingException")


def test_missing_model_id_is_audited_not_called(stubbed: tuple) -> None:
    bedrock, _, audit = stubbed
    with pytest.raises(BedrockError):
        bedrock.converse_text("", "hi", reason="test")
    assert "skipped" in audit[-1][2]


def test_image_format_detection() -> None:
    assert image_format(JPEG) == "jpeg"
    assert image_format(b"\x89PNG\r\n\x1a\nrest") == "png"
    assert image_format(b"GIF89a") is None


# ---- vision ---------------------------------------------------------------------------------

def test_missing_image_is_unavailable_without_a_call(stubbed: tuple) -> None:
    bedrock, stubber, audit = stubbed
    assert describe(None, bedrock, "vision-model") == CAMERA_UNAVAILABLE
    assert audit == []


def test_scene_too_long_or_blocked_falls_back(stubbed: tuple) -> None:
    bedrock, stubber, _ = stubbed
    stubber.add_response("converse", converse_response(" ".join(["word"] * 30)))
    stubber.add_response("converse", converse_response("A person who may have fallen."))
    assert describe(JPEG, bedrock, "vision-model") == CAMERA_UNAVAILABLE
    assert describe(JPEG, bedrock, "vision-model") == CAMERA_UNAVAILABLE


def test_scene_vision_error_falls_back(stubbed: tuple) -> None:
    bedrock, stubber, _ = stubbed
    stubber.add_client_error("converse", service_error_code="AccessDeniedException")
    assert describe(JPEG, bedrock, "vision-model") == CAMERA_UNAVAILABLE


def test_clean_scene_strips_prefixes() -> None:
    assert clean_scene('"The image shows a closed door."') == "a closed door"
    assert clean_scene("There is a parcel on the mat.") == "a parcel on the mat"


def test_take_snapshot_audits_and_never_raises() -> None:
    audit = Audit()
    assert take_snapshot(lambda: b"\xff\xd8\xffdata", audit) == b"\xff\xd8\xffdata"

    def broken() -> bytes:
        raise RuntimeError("boom")

    assert take_snapshot(broken, audit) is None
    assert [a[1] for a in audit] == ["anomaly A1 verification"] * 2
    assert "not stored" in audit[0][2]


# ---- explainer -------------------------------------------------------------------------------

def test_time_phrases() -> None:
    assert clock_time(datetime(2026, 1, 1, 21, 40)) == "9:40 PM"
    assert clock_time(datetime(2026, 1, 1, 0, 5)) == "12:05 AM"
    assert window_phrase("06:45", "07:20") == "between 6:45 and 7:20 AM"
    assert window_phrase("11:50", "12:10") == "between 11:50 AM and 12:10 PM"
    assert last_seen_phrase(datetime(2026, 10, 21, 21, 40, tzinfo=IST), NOW) == \
        "9:40 PM yesterday"
    assert last_seen_phrase(datetime(2026, 10, 19, 18, 10, tzinfo=IST), NOW) == \
        "6:10 PM on Monday"


def test_template_matches_target_shape() -> None:
    parts = alert_parts(FACTS, SCENE, NOW, NOW)
    text = template_alert(parts)
    assert text == (
        "No one has been seen at Lakshmi's front door since 9:40 PM yesterday. "
        "Lakshmi usually appears between 6:45 and 7:20 AM on Thursdays. "
        "The doorbell camera appears to show a closed front door with a milk packet on the "
        "mat; no person visible. Lakshmi hasn't answered a check-in sent at 8:10 AM. "
        "Tap below if you're handling this."
    )
    assert validate_alert(text, parts) == []


def test_template_without_camera_or_history() -> None:
    facts = FACTS | {"last_seen_ts": None, "pooled": True}
    text = template_alert(alert_parts(facts, CAMERA_UNAVAILABLE, NOW, NOW))
    assert "today." in text and "most days" in text
    assert "The camera image is unavailable." in text


def test_valid_model_output_is_used(stubbed: tuple) -> None:
    bedrock, stubber, _ = stubbed
    good = ("No one has been seen at Lakshmi's front door since 9:40 PM yesterday; Lakshmi "
            "usually appears between 6:45 and 7:20 AM on Thursdays. The doorbell camera "
            "appears to show a closed door with a milk packet on the mat. Lakshmi hasn't "
            "answered a check-in sent at 8:10 AM. Tap below if you're handling this.")
    stubber.add_response("converse", converse_response(good))
    result = explain(FACTS, SCENE, NOW, NOW, bedrock, "text-model")
    assert (result.source, result.text) == ("bedrock", good)


@pytest.mark.parametrize("bad", [
    "Lakshmi may have fallen at 9:40 and 6:45 7:20 8:10. Tap below if you're handling this.",
    "Lakshmi was not seen this morning. Tap below if you're handling this.",
    " ".join(["Lakshmi 9:40 6:45 7:20 8:10"] + ["calm"] * 70),
])
def test_invalid_model_output_uses_template(stubbed: tuple, bad: str) -> None:
    bedrock, stubber, audit = stubbed
    stubber.add_response("converse", converse_response(bad))
    result = explain(FACTS, SCENE, NOW, NOW, bedrock, "text-model")
    assert result.source == "template"
    assert result.problems
    assert audit[-1][0] == "explainer.validate"


def test_explainer_error_uses_template(stubbed: tuple) -> None:
    bedrock, stubber, _ = stubbed
    stubber.add_client_error("converse", service_error_code="ModelTimeoutException")
    assert explain(FACTS, SCENE, NOW, NOW, bedrock, "text-model").source == "template"


def test_other_messages_are_calm_and_short() -> None:
    texts = [
        checkin_message("Lakshmi", NOW),
        neighbor_message(FACTS, "Suresh", "Meena", NOW),
        degraded_message("Lakshmi", "offline", NOW, NOW),
    ]
    assert texts[0] == "Good morning Lakshmi. Just checking in. Tap OK if all is well."
    for text in texts:
        assert blocked_terms(text) == []
        assert len(text.split()) <= 70
