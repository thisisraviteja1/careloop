"""Plain-language messages. A deterministic template is always built first; a Bedrock text
model may rephrase it from the same facts, and its output is used only if it passes the
validator. The model receives only the facts JSON and the scene description."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.ai.bedrock import Bedrock, BedrockError
from app.ai.prompts import EXPLAINER_PROMPT, EXPLAINER_SYSTEM
from app.ai.safety import blocked_terms, word_count
from app.detection.detector import duration_text
from app.vision.snapshot import CAMERA_UNAVAILABLE

logger = logging.getLogger(__name__)

MAX_ALERT_WORDS = 70
ACTION_LINE = "Tap below if you're handling this."
EXPLAIN_REASON = "anomaly A1 caregiver explanation"


@dataclass(frozen=True)
class Explanation:
    text: str
    source: str  # "bedrock" or "template"
    problems: tuple[str, ...] = ()


# ---- time formatting ------------------------------------------------------------------------

def clock_time(moment: datetime) -> str:
    """'9:40 PM' (12-hour, no leading zero)."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def hhmm_to_parts(value: str) -> tuple[str, str]:
    """'06:52' → ('6:52', 'AM'). Accepts minutes past 24h by wrapping."""
    hours, minutes = (int(x) for x in value.split(":"))
    hours %= 24
    return f"{hours % 12 or 12}:{minutes:02d}", "AM" if hours < 12 else "PM"


def window_phrase(start: str, end: str) -> str:
    """'between 6:45 and 7:20 AM', or 'between 11:50 AM and 12:10 PM' across noon."""
    (s, s_mer), (e, e_mer) = hhmm_to_parts(start), hhmm_to_parts(end)
    if s_mer == e_mer:
        return f"between {s} and {e} {e_mer}"
    return f"between {s} {s_mer} and {e} {e_mer}"


def last_seen_phrase(last_seen: datetime, now_local: datetime) -> str:
    """'9:40 PM yesterday', '7:05 AM today', '6:10 PM on Monday' or '6:10 PM on 12 Oct'."""
    seen = last_seen.astimezone(now_local.tzinfo)
    days = (now_local.date() - seen.date()).days
    if days == 0:
        return f"{clock_time(seen)} today"
    if days == 1:
        return f"{clock_time(seen)} yesterday"
    if days < 7:
        return f"{clock_time(seen)} on {seen.strftime('%A')}"
    return f"{clock_time(seen)} on {seen.day} {seen.strftime('%b')}"


def scene_sentence(scene: str) -> str:
    if not scene or scene == CAMERA_UNAVAILABLE:
        return "The camera image is unavailable."
    return f"The doorbell camera appears to show {scene}."


# ---- deterministic messages -----------------------------------------------------------------

@dataclass(frozen=True)
class AlertParts:
    name: str
    last_seen: str | None
    window: str
    weekday_phrase: str
    scene: str
    checkin: str


def alert_parts(facts: dict[str, Any], scene: str, checkin_at: datetime,
                now_local: datetime) -> AlertParts:
    last = facts.get("last_seen_ts")
    return AlertParts(
        name=facts["person_name"],
        last_seen=last_seen_phrase(datetime.fromisoformat(last), now_local) if last else None,
        window=window_phrase(facts["usual_window_start"], facts["usual_window_end"]),
        weekday_phrase="most days" if facts.get("pooled") else f"{facts['weekday']}s",
        scene=scene,
        checkin=clock_time(checkin_at.astimezone(now_local.tzinfo)),
    )


def template_alert(parts: AlertParts) -> str:
    """The deterministic caregiver alert, in the fixed order."""
    if parts.last_seen:
        unusual = f"No one has been seen at {parts.name}'s front door since {parts.last_seen}."
    else:
        unusual = f"No one has been seen at {parts.name}'s front door today."
    return " ".join([
        unusual,
        f"{parts.name} usually appears {parts.window} on {parts.weekday_phrase}.",
        scene_sentence(parts.scene),
        f"{parts.name} hasn't answered a check-in sent at {parts.checkin}.",
        ACTION_LINE,
    ])


def required_snippets(parts: AlertParts) -> list[str]:
    """Strings a model rephrasing must keep verbatim (the key times)."""
    snippets = [parts.checkin.split(" ")[0]]
    snippets += [t for t in parts.window.replace("between ", "").replace(" and ", " ").split()
                 if ":" in t]
    if parts.last_seen:
        snippets.append(parts.last_seen.split(" ")[0])
    return snippets


def validate_alert(text: str, parts: AlertParts) -> list[str]:
    """Problems with a candidate alert; an empty list means it is acceptable."""
    problems: list[str] = []
    if word_count(text) > MAX_ALERT_WORDS:
        problems.append(f"too long ({word_count(text)} words)")
    if terms := blocked_terms(text):
        problems.append(f"blocked words: {', '.join(terms)}")
    missing = [s for s in required_snippets(parts) if s not in text]
    if missing:
        problems.append(f"missing times: {', '.join(missing)}")
    if parts.name not in text:
        problems.append("missing name")
    return problems


def silence_alert(facts: dict[str, Any], scene: str, checkin_at: datetime,
                  now_local: datetime) -> str:
    """The deterministic caregiver alert for A2 (long silence), in the same fixed order."""
    name = facts["person_name"]
    seen = last_seen_phrase(datetime.fromisoformat(facts["last_seen_ts"]), now_local)
    start, start_mer = hhmm_to_parts(facts["bucket_start"])
    end, end_mer = hhmm_to_parts(facts["bucket_end"])
    span = (f"{start.removesuffix(':00')} to {end.removesuffix(':00')} {end_mer}"
            if start_mer == end_mer else
            f"{start.removesuffix(':00')} {start_mer} to {end.removesuffix(':00')} {end_mer}")
    return " ".join([
        f"No one has been seen at {name}'s front door since {seen}.",
        f"Quiet stretches running into {span} usually last up to about "
        f"{duration_text(5 * round(facts['typical_max_gap_minutes'] / 5))}; this one has "
        f"lasted {duration_text(facts['gap_minutes'])}.",
        scene_sentence(scene),
        f"{name} hasn't answered a check-in sent at "
        f"{clock_time(checkin_at.astimezone(now_local.tzinfo))}.",
        ACTION_LINE,
    ])


def explain(facts: dict[str, Any], scene: str, checkin_at: datetime, now_local: datetime,
            bedrock: Bedrock | None = None, model_id: str = "") -> Explanation:
    """The caregiver alert: Bedrock phrasing if it validates, otherwise the template.
    A2 (long silence) always uses its deterministic template."""
    if facts.get("kind") == "A2":
        return Explanation(silence_alert(facts, scene, checkin_at, now_local), "template")
    parts = alert_parts(facts, scene, checkin_at, now_local)
    template = template_alert(parts)
    if bedrock is None or not model_id:
        return Explanation(template, "template")
    prompt = EXPLAINER_PROMPT.format(
        facts=json.dumps(facts, indent=2), last_seen=parts.last_seen or "not seen today",
        window=parts.window, weekday_phrase=parts.weekday_phrase,
        scene=scene if scene != CAMERA_UNAVAILABLE else "the camera image is unavailable",
        checkin=parts.checkin, name=parts.name,
    )
    try:
        text = " ".join(bedrock.converse_text(model_id, prompt, system=EXPLAINER_SYSTEM,
                                              reason=EXPLAIN_REASON).split()).strip('"')
    except BedrockError as exc:
        return Explanation(template, "template", (str(exc) or "bedrock error",))
    problems = validate_alert(text, parts)
    if problems:
        bedrock.audit("explainer.validate", EXPLAIN_REASON,
                      f"rejected model output ({'; '.join(problems)}), using template")
        return Explanation(template, "template", tuple(problems))
    return Explanation(text, "bedrock")


def checkin_message(name: str, now_local: datetime) -> str:
    """The gentle first message to the person themselves."""
    greeting = "Good morning" if now_local.hour < 12 else "Hello"
    return f"{greeting} {name}. Just checking in. Tap OK if all is well."


def neighbor_message(facts: dict[str, Any], caregiver: str, neighbor: str,
                     now_local: datetime) -> str:
    name = facts["person_name"]
    last = facts.get("last_seen_ts")
    seen = (f"since {last_seen_phrase(datetime.fromisoformat(last), now_local)}" if last
            else "today")
    when = "this morning" if facts.get("kind", "A1") == "A1" else "since then"
    return (f"Hi {neighbor}. No one has been seen at {name}'s front door {seen}, and "
            f"{name} and {caregiver} haven't answered messages {when}. Could you knock on "
            f"{name}'s door when you can? {ACTION_LINE}")


def degraded_message(name: str, status: str, since: datetime | None, now_local: datetime) -> str:
    cause = "the doorbell is offline" if status == "offline" else "Ring events can't be fetched"
    when = clock_time(since.astimezone(now_local.tzinfo)) if since else clock_time(now_local)
    return (f"CareLoop monitoring for {name} is degraded since {when}: {cause}, so routine "
            f"alerts are paused. Please check the doorbell's power and Wi-Fi.")

