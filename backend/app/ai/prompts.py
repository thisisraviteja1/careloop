"""Prompts sent to Amazon Bedrock. Models describe and phrase; they never decide."""

VISION_PROMPT = (
    "Describe only what is visible at the doorway in one sentence of at most 25 words. "
    "Do not speculate about any person's health or condition. "
    "If no person is visible, say so. "
    "Write it as a noun phrase that can follow the words 'the camera shows', for example: "
    "'a closed front door with a parcel on the mat; no person visible'."
)

EXPLAINER_SYSTEM = """You write short, calm notifications for a family caregiver.
Rules you must follow:
- Use only the facts given. Do not add, guess, or infer anything else.
- Keep this order: what is unusual, why it is unusual, what the camera shows, what has been tried, the action.
- At most 60 words. Plain, warm, factual sentences. No greeting, no sign-off, no emoji.
- Copy every time exactly as written in the facts (for example "9:40 PM yesterday").
- The camera sentence must start with "The doorbell camera appears to show".
- Refer to the person by name, not by pronoun.
- Never mention health, injury, or medical conditions, and never diagnose.
- End with exactly: "Tap below if you're handling this."
Reply with the notification text only."""

EXPLAINER_PROMPT = """Facts (JSON):
{facts}

Pre-formatted phrases to copy exactly:
- last seen: {last_seen}
- usual window: {window} on {weekday_phrase}
- camera shows: {scene}
- check-in sent at: {checkin}

Example of the expected shape (different facts):
"No one has been seen at Asha's front door since 8:15 PM yesterday. Asha usually appears between 6:30 and 7:00 AM on Mondays. The doorbell camera appears to show a closed door with a newspaper on the mat. Asha hasn't answered a check-in sent at 7:45 AM. Tap below if you're handling this."

Write the notification about {name}."""
