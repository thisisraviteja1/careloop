# CareLoop: project instructions for Claude Code


## What we're building
**CareLoop** detects when an older adult living alone breaks their daily routine, using Ring doorbell events. It then:
1. checks a camera snapshot with an Amazon Bedrock vision model,
2. explains in plain language why the situation is unusual,
3. escalates step by step: the elder first, then family, then a neighbor.

Demo story (fictional people only): Lakshmi (78, elder), Suresh (son, caregiver), Meena (neighbor). Lakshmi normally appears at her front door between about 6:45 and 7:20 AM. By 9:15 AM there is no human motion. The snapshot appears to show a milk packet still outside the door. Lakshmi gets a check-in and doesn't reply. Suresh gets an alert that explains why. If he doesn't acknowledge, Meena is asked to check.

## Principles
- This is a hackathon build. Single household, single person, one doorbell. Don't add features, abstractions, or infrastructure the phases don't ask for.
- **Statistics decide, AI explains.** An LLM never decides whether to alert.
- **Calm, specific, honest.** Alerts state facts, never diagnose, never overclaim.
- **Dignity by default.** The person is asked first. Snapshots only on anomalies, never stored.
- **Everything demo-able.** Every feature must be triggerable in demo mode.

## Hackathon requirements (must be visible in the repo)
- The Ring API is called from our code (`backend/app/ring/client.py`). A README mention is not enough.
- Amazon Bedrock is called from our code (vision and text). The README documents which AWS services we used and how.
- Public repo with an MIT `LICENSE`.
- Synthetic history and fixture images are labelled as such in the UI, the README, and the video.
- Append every real tooling problem to `docs/friction-log.md` as it happens. Each entry has: task, steps taken, expected vs. actual, severity (low/med/high), workaround, actionable suggestion. Submissions with a friction log can earn up to a 10% judging bonus, so write specific entries (aim for 8 or more).
- No third-party trademarks or copyrighted music in the video.

## Fixed stack (do not change without asking)
- Python 3.11+, FastAPI, Uvicorn, SQLModel + SQLite, httpx, boto3 (Bedrock **Converse** API), pytest, ruff. `matplotlib` is allowed as a **dev** dependency for the evaluation chart only.
- Dashboard: one static HTML file with vanilla JS and inline SVG, served by FastAPI. No build step, no React.
- Notifications: Telegram Bot API via httpx with long-polling (`getUpdates`). No webhooks and no public URL.
- Scheduling: one in-process `asyncio` loop. No APScheduler, Celery, Redis, Docker, or cloud infra.
- No Strands SDK. The ladder is a plain state machine.
- A `Makefile` with `setup`, `test`, `demo`, and `lint` targets (so judges can run it in one command).
- New dependencies need a one-line justification in the commit message.

## Architecture rules (MUST)
- **Deterministic detection.** Baseline and detector are pure functions: no LLM, no I/O.
- **One time source.** All code uses `core.clock.now()`. Never `datetime.now()` or `time.time()` in app code.
- **Adapter boundaries.** Ring HTTP only in `ring/`. Bedrock only in `ai/` and `vision/`. Sending only in `notify/`.
- **Degrade, never silence.** Every adapter has a 10 s timeout, one retry, and a fallback. A snapshot failure gives "camera image unavailable". A Bedrock failure gives the deterministic template. A send failure is retried once, logged, and the ladder continues.
- **No snapshot persistence.** Image bytes stay in memory and are never written to disk or logs. The only exception is the committed demo fixture.
- **Audit everything that touches data.** Every snapshot request, model call, notification, and ack is written to an `AuditLog` table (timestamp, action, reason, outcome). Never store image content or message bodies with tokens.
- **No secrets in git.** Env vars only. `.env.example` committed, `.env` ignored. Never log tokens.
- **Fictional names only** in seeds, fixtures, tests, and UI. No real phone numbers or emails.
- Python: type hints on public functions, `ruff` clean, small functions, `logging` not `print`, no commented-out code.

## Ring API facts
Verified from the official docs. **Response shapes are NOT verified. Read the docs and inspect real responses. Never guess a schema.**
- Base URL `https://api.amazonvision.com`. Header `Authorization: Bearer <token>`. JSON:API responses. Server-to-server only (browsers are blocked by CORS).
- Token: Ring Developer Playground, "Generate Token". Lives about 30 minutes. Env `RING_ACCESS_TOKEN`. On HTTP 401, raise a clear "Ring token expired, regenerate in Playground" error.
- **Out of scope:** OAuth account linking, app registration, webhooks, certification. Say so honestly in the README.
- Endpoints we use:
  - `GET /v1/users/me`
  - `GET /v1/devices?include=status,capabilities`
  - `GET /v1/devices/{device_id}/status` (online/offline)
  - `GET /v1/history/devices/{device_id}/events`
  - `POST /v1/devices/{device_id}/media/image/download` (snapshot; body shape from the docs; multi-camera devices use a `components` array)
- Events we care about: human motion and doorbell button press. Confirm the real field names from actual responses.
- **Ring docs MCP server (documentation search, not device control):** `https://knowledge.appstore-mcp.ring.amazon.dev/mcp`. Add it with `claude mcp add --transport http ring-docs https://knowledge.appstore-mcp.ring.amazon.dev/mcp`. Use its `search_docs` tool to confirm response shapes before coding. If it needs early access or fails to authorize, skip it, fetch the docs pages directly, and log it in the friction log.
- Docs to read before writing the client: `https://developer.amazon.com/docs/ring/api-documentation.html` (Event History, Image Snapshots) and the **Computer Vision Guidelines** page in the Ring docs navigation. Follow those guidelines when sending snapshots to a model.
- A Playground token may not expose any device. If the device list is empty, say so, stop, and ask the human.

## Detection spec (implement exactly)
- Timezone `Asia/Kolkata` (env `TIMEZONE`). A "day" starts at 04:00 local.
- **Activity** = human motion or doorbell button press.
- **Baseline per weekday:** first-activity time of day after 04:00 over history. Window = [p10, p90]. **Threshold = p90 + 45 min** (`MARGIN_MINUTES`). Fewer than 4 samples for a weekday: use pooled stats from all days. Under 7 days of total history: state `learning`, no alerts.
- **Anomaly A1 "late start":** if now ≥ today's threshold and there is no activity since 04:00 today, create exactly one anomaly for that day. Store `facts` JSON: `last_seen_ts`, `usual_window_start`, `usual_window_end`, `threshold`, `weekday`, `sample_count`, `person_name`.
- **Device health guard:** if the device status is offline (or events can't be fetched), **do not raise A1**. Show a "monitoring degraded since HH:MM" notice instead, and notify the caregiver once. A dead camera must never look like a missing person, and a dead camera must never hide an alert silently. In demo mode the device status is simulated as online unless the scenario says otherwise.
- Only A1 for the core build. A2 is stretch (Phase 9).

## Alert message rules
- Fixed order: **what's unusual, why it's unusual, what the camera shows, what's been tried, action.**
- Plain local 12-hour times ("9:40 PM", "between 6:45 and 7:20 AM"). Never "2 hrs ago" alone.
- At most **70 words**. Calm and factual. Never use: fall, fallen, emergency, unconscious, collapsed, injured, dead, hurt.
- The camera line is hedged: "The doorbell camera appears to show…".
- Target example: "No one has been seen at Lakshmi's front door since 9:40 PM yesterday. She usually appears between 6:45 and 7:20 AM on Thursdays. The doorbell camera appears to show a milk packet still outside the door. She hasn't answered a check-in sent at 9:15 AM. Tap below if you're handling this."
- The model receives **only** the `facts` JSON plus the scene description and must not add facts. Validate its output (≤70 words, no forbidden words, contains the key times). If invalid or on any error, use the deterministic template.
- Elder check-in: "Good morning Lakshmi. Just checking in. Tap OK if all is well."

## Escalation spec
`DETECTED → L1_PENDING (elder) → L2_PENDING (caregiver) → L3_PENDING (neighbor) → EXHAUSTED`, or `ACKNOWLEDGED` at any point. Default waits: L1 30 min, L2 30 min in clock time (configurable). An ack at any level stops all later levels. Ack sources: Telegram inline button, the **big-button ack page** (`/ack/{token}`, see Phase 4), or the dashboard. Ack tokens are signed, never guessable.

## Demo mode
- `DEMO_MODE=true` enables the accelerated clock (`CLOCK_SPEED`, default 60: 30 simulated minutes take 30 real seconds) and the demo endpoints.
- Seed: **28 days** of synthetic history (first activity about 7:00 ± 15 min, one day at 7:40, a couple at 6:40, weekends slightly later, plus daytime events). Rows have `is_synthetic=true`. 28 days gives 4 samples per weekday, so the per-weekday baseline is real.
- Demo snapshot comes from `fixtures/demo_snapshot.jpg`. The Bedrock vision and text calls are **real**.
- Scenarios: `missed-morning` (must), `late-but-normal` (7:40 first motion, no alert), `elder-replies` (L1 ack stops the ladder), `camera-offline` (degraded notice, no false alarm).
- The UI always shows a banner: "Demo controls · simulated data · fixture image".

## Working agreement
- One phase at a time. Plan first, then code. Small commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`.
- Run `ruff check . && pytest` before saying a phase is done.
- At the end of each phase, update `docs/PROGRESS.md` (done, next, open questions).
- If you need something only a human can provide (tokens, IDs, the image), **stop and say exactly what you need**.
- Tests never call real Ring, Bedrock, or Telegram. Use fixtures and fakes.


## Ring API notes gathered in Phase 0 (update after the first real probe)
- Event history: `GET /v1/history/devices/{id}/events`, JSON:API `data[]`, each item has `attributes.event_type` and `attributes.start` (from the official `ring-api-helloworld` scripts). Optional query param `event_types` (comma-separated).
- Event type names are inconsistent between sources: the API docs list `motion_detected` (with `attributes.sub_type` such as `human`) and `button_press`; the hello-world script's help text suggests filter values `motion.human,ding`. Trust only what `scripts/ring_probe.py` saves in `fixtures/`.
- Device status: `data.attributes.online` (bool).
- Users/me: `data.id` is the account ID; attributes may include name and email (scrubbed in fixtures).
- Snapshot: `POST /v1/devices/{id}/media/image/download` returns JPEG or PNG. Body shape still unconfirmed; the docs mention a `components` array for multi-camera devices.
- Computer Vision Guidelines: treat imagery as sensitive, keep processing in-region and retention short, send only selected still frames, treat VLM output as unverified, check every model text output, define fallback behaviour, expect unreadable media on encrypted (E2EE) devices without retrying.
