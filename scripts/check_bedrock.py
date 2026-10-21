#!/usr/bin/env python3
"""Check Amazon Bedrock access for the configured models.

Lists foundation models and inference profiles in AWS_REGION, then makes one tiny Converse
call with BEDROCK_VISION_MODEL_ID and BEDROCK_TEXT_MODEL_ID and says what to fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ai.bedrock import Bedrock, BedrockError  # noqa: E402
from app.config import get_settings  # noqa: E402

ADVICE = {
    "AccessDeniedException": "Enable access to this model in the Bedrock console "
                             "(Model access) for this region, and check your IAM permissions "
                             "include bedrock:InvokeModel.",
    "ValidationException": "If the error mentions on-demand throughput, use an inference "
                           "profile ID instead (for example a 'us.', 'eu.' or 'apac.' prefix "
                           "on the model ID, see the profiles listed above).",
    "ResourceNotFoundException": "The model ID doesn't exist in this region. Pick one "
                                 "from the list above.",
    "UnrecognizedClientException": "AWS credentials are missing or invalid. Run `aws configure`.",
    "NoCredentialsError": "AWS credentials are missing. Run `aws configure`.",
}


def list_models(region: str) -> None:
    import boto3

    bedrock = boto3.client("bedrock", region_name=region)
    try:
        models = bedrock.list_foundation_models()["modelSummaries"]
    except Exception as exc:  # report and continue: the test calls below say more
        print(f"  Could not list models: {exc}")
        return
    vision = [m["modelId"] for m in models if "IMAGE" in m.get("inputModalities", [])
              and "TEXT" in m.get("outputModalities", [])]
    text = [m["modelId"] for m in models if m.get("outputModalities") == ["TEXT"]]
    print(f"  {len(models)} foundation models. Image+text input: {len(vision)}, text: {len(text)}")
    for model_id in sorted(vision)[:25]:
        print(f"    vision-capable: {model_id}")
    try:
        profiles = bedrock.list_inference_profiles()["inferenceProfileSummaries"]
        for profile in profiles[:25]:
            print(f"    inference profile: {profile['inferenceProfileId']}")
    except Exception as exc:
        print(f"  Could not list inference profiles: {exc}")


def tiny_call(bedrock: Bedrock, label: str, model_id: str) -> bool:
    if not model_id:
        print(f"✗ {label}: not set in .env")
        return False
    try:
        reply = bedrock.converse_text(model_id, "Reply with the single word: ready",
                                      reason="setup check", max_tokens=10)
    except BedrockError as exc:
        code = str(exc)
        print(f"✗ {label} ({model_id}): {code}\n  → {ADVICE.get(code, 'See the error above.')}")
        return False
    print(f"✓ {label} ({model_id}) replied: {reply[:40]!r}")
    return True


def main() -> int:
    settings = get_settings()
    print(f"Region: {settings.aws_region}")
    list_models(settings.aws_region)
    bedrock = Bedrock(settings.aws_region)
    ok_vision = tiny_call(bedrock, "vision model", settings.bedrock_vision_model_id)
    ok_text = tiny_call(bedrock, "text model", settings.bedrock_text_model_id)
    if settings.bedrock_guardrail_id:
        guarded = Bedrock(settings.aws_region, guardrail_id=settings.bedrock_guardrail_id,
                          guardrail_version=settings.bedrock_guardrail_version)
        ok_text = tiny_call(guarded, "text model with guardrail",
                            settings.bedrock_text_model_id) and ok_text
    else:
        print("  (no BEDROCK_GUARDRAIL_ID set: run scripts/create_guardrail.py to add one)")
    return 0 if ok_vision and ok_text else 1


if __name__ == "__main__":
    sys.exit(main())
