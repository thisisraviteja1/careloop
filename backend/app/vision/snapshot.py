"""Snapshot verification: fetch one still frame, describe it with a Bedrock vision model.

Image bytes stay in memory. They are never written to disk, the database, or logs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from app.ai.bedrock import Bedrock, BedrockError
from app.ai.prompts import VISION_PROMPT
from app.ai.safety import blocked_terms, word_count
from app.audit import AuditFn

logger = logging.getLogger(__name__)

CAMERA_UNAVAILABLE = "camera image unavailable"
SNAPSHOT_REASON = "anomaly A1 verification"
MAX_SCENE_WORDS = 25
_PREFIXES = re.compile(
    r"^(the (image|photo|picture|camera|frame) (shows|depicts|contains)|this (image|photo) "
    r"shows|i (can )?see|there (is|are)|it shows|shows)\s*:?\s*", re.IGNORECASE)


def take_snapshot(fetch: Callable[[], bytes | None], audit: AuditFn,
                  reason: str = SNAPSHOT_REASON) -> bytes | None:
    """Call `fetch` once and audit the request. Returns bytes in memory or None."""
    try:
        image = fetch()
    except Exception as exc:  # the Ring client already retried; any failure means "unavailable"
        audit("ring.snapshot", reason, f"error: {exc.__class__.__name__}")
        return None
    audit("ring.snapshot", reason,
          f"ok, {len(image)} bytes held in memory, not stored" if image else "unavailable")
    return image


def clean_scene(text: str) -> str:
    """One line, no quotes, no 'The image shows' prefix, no trailing period."""
    line = " ".join(text.strip().strip("\"'").split())
    line = _PREFIXES.sub("", line).strip().rstrip(".").strip()
    return line[:1].lower() + line[1:] if line else line


def validate_scene(text: str) -> str | None:
    """The cleaned description, or None if it breaks a rule."""
    scene = clean_scene(text)
    if not scene or word_count(scene) > MAX_SCENE_WORDS or blocked_terms(scene):
        return None
    return scene


def describe(image: bytes | None, bedrock: Bedrock | None, model_id: str,
             reason: str = SNAPSHOT_REASON) -> str:
    """A short hedged-ready scene description, or 'camera image unavailable'."""
    if not image or bedrock is None or not model_id:
        return CAMERA_UNAVAILABLE
    try:
        raw = bedrock.converse_image(model_id, VISION_PROMPT, image, reason=reason)
    except BedrockError:
        return CAMERA_UNAVAILABLE
    scene = validate_scene(raw)
    if scene is None:
        bedrock.audit("vision.validate", reason, "rejected model output, using fallback")
        return CAMERA_UNAVAILABLE
    return scene
