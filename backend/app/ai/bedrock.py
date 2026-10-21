"""Thin wrapper over the Amazon Bedrock Converse API (text and image + text).

Every call writes an audit row with the action, the reason, and the outcome. Prompts,
images and model output are never written to the audit log.
"""

from __future__ import annotations

import logging
from typing import Any

from app.audit import AuditFn, null_audit

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10


class BedrockError(Exception):
    """A Bedrock call failed after one retry, or returned no text."""


def make_runtime_client(region: str) -> Any:
    """A bedrock-runtime client with 10 s timeouts and one retry."""
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=TIMEOUT_SECONDS, read_timeout=TIMEOUT_SECONDS,
                    retries={"max_attempts": 2, "mode": "standard"})
    return boto3.client("bedrock-runtime", region_name=region, config=config)


def image_format(data: bytes) -> str | None:
    """'jpeg' or 'png' from the file signature, else None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


class Bedrock:
    """Converse calls with audit logging. Pass `client` to inject a stubbed boto3 client."""

    def __init__(self, region: str, *, client: Any | None = None,
                 audit: AuditFn = null_audit, guardrail_id: str = "",
                 guardrail_version: str = "DRAFT") -> None:
        self.region = region
        self._client = client
        self.audit = audit
        self.guardrail_id = guardrail_id
        self.guardrail_version = guardrail_version or "DRAFT"

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = make_runtime_client(self.region)
        return self._client

    def converse_text(self, model_id: str, prompt: str, *, reason: str, system: str = "",
                      max_tokens: int = 300, temperature: float = 0.2) -> str:
        content = [{"text": prompt}]
        return self._converse(model_id, content, system, max_tokens, temperature, reason,
                              action="bedrock.converse.text", guarded=True)

    def converse_image(self, model_id: str, prompt: str, image: bytes, *, reason: str,
                       max_tokens: int = 120) -> str:
        fmt = image_format(image)
        if fmt is None:
            self.audit("bedrock.converse.image", reason, "skipped: unsupported image format")
            raise BedrockError("unsupported image format")
        content = [{"image": {"format": fmt, "source": {"bytes": image}}}, {"text": prompt}]
        return self._converse(model_id, content, "", max_tokens, 0.0, reason,
                              action="bedrock.converse.image")

    def _converse(self, model_id: str, content: list[dict[str, Any]], system: str,
                  max_tokens: int, temperature: float, reason: str, *, action: str,
                  guarded: bool = False) -> str:
        if not model_id:
            self.audit(action, reason, "skipped: no model ID configured")
            raise BedrockError("no model ID configured")
        request: dict[str, Any] = {
            "modelId": model_id,
            "messages": [{"role": "user", "content": content}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        if system:
            request["system"] = [{"text": system}]
        guardrail = guarded and bool(self.guardrail_id)
        if guardrail:
            request["guardrailConfig"] = {"guardrailIdentifier": self.guardrail_id,
                                          "guardrailVersion": self.guardrail_version,
                                          "trace": "disabled"}
        try:
            response = self.client.converse(**request)
        except Exception as exc:  # botocore raises many types; all mean "use the fallback"
            code = _error_code(exc)
            self.audit(action, reason, f"error: {code} ({model_id})")
            logger.warning("Bedrock %s failed: %s", model_id, code)
            raise BedrockError(code) from exc
        if response.get("stopReason") == "guardrail_intervened":
            self.audit(action, reason, f"blocked by Bedrock Guardrail ({model_id}), "
                                       "using fallback")
            raise BedrockError("guardrail_intervened")
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(b["text"] for b in blocks if isinstance(b, dict) and "text" in b).strip()
        usage = response.get("usage", {})
        outcome = (f"ok ({model_id}, {usage.get('inputTokens', '?')} in / "
                   f"{usage.get('outputTokens', '?')} out tokens"
                   f"{', guardrail passed' if guardrail else ''})")
        if not text:
            self.audit(action, reason, f"error: empty response ({model_id})")
            raise BedrockError("empty response")
        self.audit(action, reason, outcome)
        return text


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return exc.__class__.__name__
