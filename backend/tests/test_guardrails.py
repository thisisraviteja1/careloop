from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import pytest
from botocore.stub import ANY, Stubber

from app.ai.bedrock import Bedrock, BedrockError
from app.ai.explainer import explain
from scripts.create_guardrail import guardrail_request

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 22, 8, 10, tzinfo=IST)
JPEG = (Path(__file__).resolve().parents[2] / "fixtures" / "demo_snapshot.jpg").read_bytes()
FACTS = {"kind": "A1", "person_name": "Lakshmi", "last_seen_ts": "2026-10-21T21:40:00+05:30",
         "usual_window_start": "06:45", "usual_window_end": "07:20", "threshold": "08:05",
         "weekday": "Thursday", "sample_count": 4, "pooled": False, "margin_minutes": 45}
GUARD = {"guardrailIdentifier": "gr-123", "guardrailVersion": "1", "trace": "disabled"}


def response(text: str, stop: str = "end_turn") -> dict:
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": stop, "usage": {"inputTokens": 5, "outputTokens": 5, "totalTokens": 10},
            "metrics": {"latencyMs": 1}}


@pytest.fixture
def guarded() -> tuple[Bedrock, Stubber, list]:
    client = boto3.client("bedrock-runtime", region_name="us-east-1",
                          aws_access_key_id="t", aws_secret_access_key="t")
    rows: list = []
    stubber = Stubber(client)
    stubber.activate()
    bedrock = Bedrock("us-east-1", client=client, audit=lambda *r: rows.append(r),
                      guardrail_id="gr-123", guardrail_version="1")
    yield bedrock, stubber, rows
    stubber.deactivate()


def test_text_calls_carry_the_guardrail(guarded: tuple) -> None:
    bedrock, stubber, rows = guarded
    stubber.add_response("converse", response("ready"),
                         {"modelId": "m", "messages": ANY, "inferenceConfig": ANY,
                          "guardrailConfig": GUARD})
    assert bedrock.converse_text("m", "hi", reason="test") == "ready"
    stubber.assert_no_pending_responses()
    assert "guardrail passed" in rows[-1][2]


def test_image_calls_do_not_carry_the_guardrail(guarded: tuple) -> None:
    bedrock, stubber, _ = guarded
    stubber.add_response("converse", response("a closed door"),
                         {"modelId": "v", "messages": ANY, "inferenceConfig": ANY})
    assert bedrock.converse_image("v", "describe", JPEG, reason="test") == "a closed door"


def test_guardrail_intervention_falls_back_to_the_template(guarded: tuple) -> None:
    bedrock, stubber, rows = guarded
    stubber.add_response("converse", response("CareLoop blocked this text.",
                                               stop="guardrail_intervened"))
    result = explain(FACTS, "a closed door", NOW, NOW, bedrock, "m")
    assert result.source == "template"
    assert result.problems == ("guardrail_intervened",)
    assert result.text.startswith("No one has been seen at Lakshmi's front door")
    assert any("blocked by Bedrock Guardrail" in r[2] for r in rows)


def test_no_guardrail_configured_means_no_guardrail_config() -> None:
    client = boto3.client("bedrock-runtime", region_name="us-east-1",
                          aws_access_key_id="t", aws_secret_access_key="t")
    with Stubber(client) as stubber:
        stubber.add_response("converse", response("ok"),
                             {"modelId": "m", "messages": ANY, "inferenceConfig": ANY})
        assert Bedrock("us-east-1", client=client).converse_text("m", "hi", reason="t") == "ok"
    with pytest.raises(BedrockError):
        Bedrock("us-east-1", client=client).converse_text("", "hi", reason="t")


def test_create_guardrail_request_matches_the_bedrock_api() -> None:
    client = boto3.client("bedrock", region_name="us-east-1",
                          aws_access_key_id="t", aws_secret_access_key="t")
    request = guardrail_request("careloop-no-diagnosis")
    with Stubber(client) as stubber:
        stubber.add_response("create_guardrail", {
            "guardrailId": "gr-123", "guardrailArn": "arn:aws:bedrock:us-east-1:1:guardrail/gr-123",
            "version": "DRAFT", "createdAt": datetime(2026, 10, 22, tzinfo=UTC)}, request)
        assert client.create_guardrail(**request)["guardrailId"] == "gr-123"
    topic = request["topicPolicyConfig"]["topicsConfig"][0]
    assert topic["type"] == "DENY" and len(topic["definition"]) <= 200
    assert {"fall", "emergency"} <= {w["text"] for w in request["wordPolicyConfig"]["wordsConfig"]}
