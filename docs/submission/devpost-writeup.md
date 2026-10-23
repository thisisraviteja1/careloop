# Devpost write-up: CareLoop

Paste each section into the matching Devpost field. Text in [square brackets] must be filled in or checked before submitting.

**Tagline (one line):** A Ring doorbell that notices when Mum's morning is different, checks gently, and tells family why.

---

## Inspiration

Around 16% of adults aged 60 and over live alone, across the 130 countries Pew Research studied ([Pew Research Center, 2020](https://www.pewresearch.org/short-reads/2020/03/10/older-people-are-more-likely-to-live-alone-in-the-u-s-than-elsewhere-in-the-world/)). In India, people aged 60 and over are projected to make up almost 19.6% of the population by 2050 (UN figure, reported by [Down To Earth](https://www.downtoearth.org.in/health/how-is-india-s-population-ageing-evidence-from-lasi-81770)), and many have children who work in other cities.

Families in that situation usually rely on a daily phone call, or an inactivity alarm with one fixed time for everyone. A fixed alarm either cries wolf for someone who sleeps late or waits hours for someone who is up at 6. We wanted something that learns one person's own routine, checks quietly before worrying anyone, and explains itself in plain words.

## What it does

CareLoop watches the events a Ring doorbell already produces: human motion and button presses at the front door.

- **Learns the person's routine.** For each weekday it learns when the person usually first appears at the door (for example, between 6:52 and 7:11 AM on Wednesdays). It also learns the longest quiet stretch they usually have during the day.
- **Notices two kinds of unusual day.** *Late start*: no one has appeared well after the usual window. *Long silence*: the person was seen in the morning, then nothing for longer than usual.
- **Checks before alarming anyone.** It takes one Ring snapshot and asks an Amazon Bedrock vision model to describe the doorway ("appears to show a milk packet still on the mat"). The image is held in memory only and never stored.
- **Explains why.** The caregiver gets a calm, specific message of 70 words or fewer, in a fixed order: what's unusual, why, what the camera shows, what's been tried, and what to do.
- **Asks people in order.** First the person themselves (one tap on "I'm OK"), then the family caregiver, then a neighbor. Any acknowledgement stops the ladder.
- **Stays honest when the camera is down.** If the doorbell goes offline, CareLoop says "monitoring degraded since 8:05 AM" once, instead of raising a false alarm or going silent.
- **Away mode.** Alerts pause for travel or visits, and those days are left out of the routine it learns.

Every snapshot, model call, message and acknowledgement is listed in a privacy and audit panel on the dashboard.

## How we built it

- **Ring API** (`backend/app/ring/client.py`): `GET /v1/users/me`, `GET /v1/devices`, `GET /v1/devices/{id}/status`, `GET /v1/history/devices/{id}/events`, and `POST /v1/devices/{id}/media/image/download` for the snapshot. It polls with a Playground token, de-duplicates events, and tracks device health.
- **Statistics decide, AI explains.** The routine model and the detectors are pure Python functions: per-weekday p10–p90 windows, with the alert threshold at p90 + 45 minutes. For daytime silences it uses the person's longest gap in each 4-hour block, + 60 minutes. No model ever decides whether to alert.
- **Amazon Bedrock Converse API**: Amazon Nova Lite describes the snapshot (image + text) and phrases the caregiver message (text). Every output passes CareLoop's validator: 70 words or fewer, no alarming or medical words, and every key time present. If anything fails, a deterministic template is sent instead. An optional **Bedrock Guardrail** (created by `scripts/create_guardrail.py`) denies the topic "medical diagnosis".
- **Escalation**: a small state machine with signed, expiring acknowledgement tokens. **Telegram** messages carry an "I'm OK" / "I'm handling it" button, and a **big-button web page** serves people who don't use messaging apps.
- **Dashboard**: one HTML file with SVG charts and no build step. It uses the Atkinson Hyperlegible typeface, meets WCAG AA contrast and is keyboard-friendly.
- FastAPI, SQLite, one asyncio loop, and 111 automated tests. Ring, Bedrock and Telegram are all mocked in the tests, and botocore's Stubber validates every Bedrock request against the real API schema.

## Challenges we ran into

- **Documentation gaps.** Event type names differ between the Ring docs (`motion_detected` with `sub_type: human`) and the official sample (`motion.human`, `ding`), and the event history endpoint documents no time-range or paging parameters. We wrote a probe that saves scrubbed real responses, and made the parser accept both spellings. These are logged in our friction log.
- **Not alarming people.** The hard part was not detection but wording: no diagnosis, no "fall", no "emergency", hedged camera descriptions, and a fixed order that a worried person can scan in five seconds.
- **A dead camera must never look like a missing person.** The device health guard was the most important "boring" feature.
- **AWS access.** We couldn't get into an AWS account before the deadline, so the demo video runs CareLoop's deterministic fallback: "camera image unavailable" and the fixed message template. The Bedrock integration is fully built, and our tests validate every Converse request against the real Bedrock API schema, but it has not been run against live models. Building the fallback first meant the product still works end to end without AI.

## Accomplishments that we're proud of

- An honest evaluation (`docs/evaluation.md`). On the same simulated 90-day histories for two people, every fixed timer failed one of them: an 8 AM timer alerted on 61 of 61 normal days for a late riser, and a 10 AM timer waited 3 hours for an early riser. CareLoop never exceeded 4 of 61 false alarms (7%) in any setting, with no tuning. We also report where it loses: for the early riser, a well-placed 8 AM timer is faster.
- Privacy that you can see: snapshots only on an anomaly, never stored, and every access in an audit log on the dashboard.
- Accessibility built in: the big-button acknowledgement page, a low-vision-friendly typeface, and color never used alone.

## What we learned

- Personal baselines beat clever thresholds. Most of the value came from "compared with her own Wednesdays", not from AI.
- Keeping models out of the decision made the system easier to test, explain and trust. Bedrock is at its best describing and phrasing.
- Writing the friction log as we went made the product feedback specific instead of generic.

## What's next for CareLoop

- Run on weeks of real routines (with consent) to measure real-world accuracy; the evaluation so far is a simulation.
- OAuth account linking and webhooks instead of a Playground token and polling.
- More signals: multiple cameras, indoor sensors, and a weekly "routine summary" for families.
- Local languages for check-ins and alerts.

---

## Built with

`python` `fastapi` `sqlite` `sqlmodel` `httpx` `ring-api` `amazon-bedrock` `amazon-nova` `bedrock-guardrails` `boto3` `telegram-bot-api` `javascript` `svg`

## Track and mini challenges

- **Track:** Ring (priority categories: caretaking, accessibility)
- **Mini challenges:** AWS Builder, Open Source

## AWS services (for the Product Feedback answer)

CareLoop uses **Amazon Bedrock Runtime's Converse API** with **Amazon Nova Lite** twice per anomaly. The first call sends one Ring snapshot as an image block, with a fixed prompt, to describe the doorway in 25 words or fewer. The second sends only a facts JSON and that description, to phrase the caregiver message, with an optional **Amazon Bedrock Guardrail** (denied topic: medical diagnosis; word filter for alarming words). Every call has 10-second timeouts, one retry, and an audit-log row with token counts. Every output is checked by our own validator, and a deterministic template is the fallback. `scripts/check_bedrock.py` uses the Bedrock control plane (`list_foundation_models`, `list_inference_profiles`) to diagnose access. Honest status: we couldn't sign in to an AWS account in time, so these calls were validated with botocore's Stubber against the real API schema but not run against live models, and the demo shows the deterministic fallback.

## Open Source mini challenge

- **Contribution URL:** [PR or fork URL]
- **Project repository:** https://github.com/Bharath0408/careloop
- **GitHub username:** Bharath0408
- **What, how and why:** The official `ring-api-helloworld` starter has a script for every read endpoint except image snapshots. We added `scripts/image_snapshot.py` in the same style: argparse, `--token`, device auto-discovery, and a printed curl equivalent. It calls `POST /v1/devices/{id}/media/image/download`, supports `--components` for multi-camera devices, checks that the response is an image before saving, and prints the error body otherwise. It matters because snapshots are the step every computer-vision integration needs first, and it is the one endpoint new developers currently have no example for.

## Built during the submission period

Yes. All code was written during the hackathon submission period; see the commit history.
