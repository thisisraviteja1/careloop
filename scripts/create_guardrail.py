#!/usr/bin/env python3
"""Create the CareLoop Bedrock Guardrail and print the env lines to use it.

The guardrail denies the topic "medical diagnosis" and blocks the alert's forbidden words
in model output. CareLoop's local validator stays in place as the fallback.

Usage: python scripts/create_guardrail.py [--name careloop-no-diagnosis] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ai.safety import FORBIDDEN_WORDS  # noqa: E402
from app.config import get_settings  # noqa: E402

BLOCKED_MESSAGE = "CareLoop blocked this text. The deterministic message is used instead."


def guardrail_request(name: str) -> dict[str, Any]:
    """The create_guardrail parameters (kept separate so tests can validate them)."""
    return {
        "name": name,
        "description": "CareLoop caregiver alerts: no medical diagnosis or alarming wording.",
        "topicPolicyConfig": {"topicsConfig": [{
            "name": "Medical diagnosis",
            "definition": ("Statements or guesses about a person's health, medical condition, "
                           "injury, illness or cause of absence, or advice on treatment."),
            "examples": [
                "She may have had a stroke.",
                "He probably fell and is injured.",
                "This could be a heart problem.",
                "She might be unconscious.",
            ],
            "type": "DENY",
        }]},
        "wordPolicyConfig": {"wordsConfig": [{"text": word} for word in FORBIDDEN_WORDS]},
        "blockedInputMessaging": BLOCKED_MESSAGE,
        "blockedOutputsMessaging": BLOCKED_MESSAGE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="careloop-no-diagnosis")
    parser.add_argument("--dry-run", action="store_true", help="Print the request only")
    args = parser.parse_args()
    request = guardrail_request(args.name)
    if args.dry_run:
        print(json.dumps(request, indent=2))
        return 0

    import boto3

    region = get_settings().aws_region
    bedrock = boto3.client("bedrock", region_name=region)
    try:
        created = bedrock.create_guardrail(**request)
        version = bedrock.create_guardrail_version(guardrailIdentifier=created["guardrailId"],
                                                   description="CareLoop hackathon")
    except Exception as exc:  # report the AWS error as is
        print(f"Could not create the guardrail in {region}: {exc}")
        return 1
    print(f"Created guardrail {created['guardrailId']} version {version['version']} "
          f"in {region}. Add to .env:\n")
    print(f"BEDROCK_GUARDRAIL_ID={created['guardrailId']}")
    print(f"BEDROCK_GUARDRAIL_VERSION={version['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
