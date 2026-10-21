# Progress

## Phase 0: scaffold and Ring probe

**Done**
- Repo structure, MIT LICENSE, README stub, Makefile (`setup`, `test`, `lint`, `probe`, `run`, `demo` placeholder), `.gitignore`, `.env.example` with every env var.
- `pyproject.toml` with the full fixed stack, ruff config, and pytest config.
- `backend/app/config.py` (settings from env / `.env`, no extra dependency) and a minimal FastAPI app with `/healthz`.
- `backend/app/ring/scrub.py`: removes names, emails, addresses, coordinates, tokens and URL query strings, and replaces IDs with stable pseudonyms (`device-1`, `user-1`). Tested.
- `scripts/ring_probe.py`: calls `/v1/users/me`, `/v1/devices?include=status,capabilities`, then device status and event history for the first device; prints HTTP status and trimmed JSON, summarizes the `event_type` / `sub_type` values actually returned, and saves scrubbed fixtures to `fixtures/ring_*.json`. Stops with a clear message if the device list is empty; clear message on 401.
- Friction log started (4 entries).

**Waiting on a human**
- Run `make probe` with a fresh Playground token and commit the scrubbed `fixtures/ring_*.json`. Phase 1 must not start until the real event shape is known.

**Next**
- Phase 1: clock, database, Ring client (live and fixture modes), poller.

**Open questions**
- Real event type names: docs say `motion_detected` + `sub_type: human` and `button_press`; the hello-world script suggests `motion.human` and `ding`. The probe output settles it.
- Event history pagination and time-range query params are not documented on the page we could read. Check the probe's `links` / `meta` output.
- Snapshot request body (the `components` array) is still unconfirmed.

## Phase 1: clock, database, Ring client, poller

**Done**
- `core/clock.py`: one time source with a speed multiplier, `set_time`, `advance`, and freeze (speed 0).
- `db/`: SQLModel tables `Event`, `Anomaly`, `EscalationStep`, `NotificationLog`, `AuditLog`, `DeviceHealth`. All datetimes use our own `UTCDateTime` column type (aware in, aware UTC out), so behaviour doesn't change between SQLModel releases.
- `ring/client.py`: `live` and `fixture` modes; 10 s timeout, one retry on network or 5xx errors, no retry on 4xx; 401 raises "Ring token expired, regenerate in Playground". Snapshot returns bytes only when the response is an image, otherwise `None`.
- `ring/events.py`: parses event history; activity = human motion or doorbell press, accepting both documented spellings until the real probe confirms one.
- `ring/poller.py`: `sync_once` with a cursor (newest stored event), de-duplication by Ring ID, and device health tracking. `python -m app.ring.poller --once` works in fixture mode.
- `fixtures/sample/`: hand-written synthetic responses (labelled) so fixture mode works before the probe runs.

**Open questions**
- Event history has no documented time filter, so the client filters after fetching and follows `links.next` for up to 10 pages. Revisit once the probe shows real paging.

## Phase 2: baseline, detector, seed data

**Done**
- `baseline/model.py` (pure): days start at 04:00; first-activity minute per day; per-weekday [p10, p90] window; threshold = p90 + `MARGIN_MINUTES`; pooled fallback under 4 weekday samples; `learning` under 7 days of history. Only days before the judged day are used.
- `detection/detector.py` (pure): `evaluate` returns degraded / normal / learning / waiting / anomaly, with the A1 `facts` JSON.
- `detection/runner.py`: loads activity, applies the device health guard (offline or event errors mean no A1, and the caregiver is told once), and creates at most one A1 per day.
- `scripts/seed_history.py --days 28`: deterministic synthetic history (`is_synthetic=true`), with one 7:40 day, two 6:40 days, later weekends, daytime and vehicle events, and 9:40 PM as the last sighting the evening before.
- Tests cover every case listed in the plan, plus no-peeking and determinism.

## Phase 3: Bedrock vision, explainer, audit

**Done**
- `ai/bedrock.py`: Converse wrapper (text, and image + text), model IDs from env, 10 s timeouts, one retry (botocore `max_attempts=2`). Every call writes an audit row with action, reason and outcome (model ID and token counts, never content).
- `vision/snapshot.py`: `take_snapshot` (audited with the reason "anomaly A1 verification", bytes kept in memory only) and `describe` (the planned prompt, plus a request for a noun phrase so the hedged sentence reads naturally). Validates at most 25 words and the block list; anything else gives "camera image unavailable".
- `ai/safety.py`: forbidden words plus a block list, applied to every model output (Ring Computer Vision Guidelines).
- `ai/explainer.py`: deterministic template in the fixed order, 12-hour times, hedged camera line; optional Bedrock phrasing from the facts JSON and scene only, kept only if it passes the validator (70 words or fewer, no blocked words, key times and name present). Also builds the check-in, neighbor and degraded messages.
- `scripts/check_bedrock.py` (lists models and inference profiles, test call, advice per error code) and `scripts/try_explainer.py`.
- `fixtures/demo_snapshot.jpg`: a **generated illustration** of a doorway with a milk pouch on the mat, no people. Replace it with a real photo (no faces) for the video if you can.
- Tests use botocore's `Stubber`, which also validates every request against the real Converse API schema.

**Waiting on a human**
- Run `python scripts/check_bedrock.py`, then `python scripts/try_explainer.py`, with real AWS credentials. Real Bedrock output has not been seen yet.

## Phase 4: escalation, Telegram, big-button ack page

**Done**
- `escalation/engine.py`: pure state machine (DETECTED → L1 elder → L2 caregiver → L3 neighbor → EXHAUSTED, or ACKNOWLEDGED). Each level's wait starts when the previous one ran out, so a slow tick never stretches the ladder. An exhausted alert can still be acknowledged.
- `escalation/runner.py`: executes actions on every channel with one retry each, writes `EscalationStep`, `NotificationLog` (message text never contains the token) and `AuditLog` rows. A failing or crashing adapter never stops the ladder.
- `core/tokens.py`: HMAC-signed, expiring ack tokens of 64 bytes or less, so they fit Telegram's `callback_data`.
- `notify/telegram.py`: `sendMessage` with an inline "I'm OK" / "I'm handling it" button plus the big-button link in the text (Telegram rejects localhost URLs on buttons), `getUpdates` long-polling, and `answerCallbackQuery`. People without a chat ID are skipped.
- `notify/dashboard.py`: always-on channel; the dashboard reads `NotificationLog`.
- `/ack/{token}`: big-button page with no JavaScript needed: 88 px primary button, 26 px text, high contrast in light and dark modes, visible focus ring, `lang` set. Invalid, tampered or expired links get a calm message.

**Waiting on a human**
- Human test with a real bot: message arrives with a button, the link opens the page, and the ack is recorded.

## Phase 5: API, loop, demo runner

**Done**
- `service.py`: one tick = Ring poll (live) or demo script → detector → on a new anomaly: audited snapshot (fixture in demo mode), Bedrock description, explanation → degraded notice once → escalation for every open alert. Snapshot bytes are dropped right after the vision call.
- `api/routes.py`: `/api/status`, `/api/timeline`, `/api/baseline`, `/api/anomalies`, `/api/anomalies/{id}`, `POST /api/anomalies/{id}/ack`, `/api/audit`, `/api/ring/health` (a live `users_me` call whenever a token is set, even in demo mode), and `/api/demo/seed|run|reset|state` (demo mode only). Errors use `{"error": {"code", "message", "details"}}`.
- `main.py`: app factory (`uvicorn app.main:create_app --factory`), lifespan with the tick loop (1 s in demo, `POLL_INTERVAL_SECONDS` live) and the Telegram long-poll loop.
- Scenarios: `missed-morning`, `late-but-normal`, `elder-replies` (simulated tap two minutes after the check-in), `camera-offline`. Each starts just before today's threshold, and the clock pauses when it finishes.
- `scripts/demo_scenario.py` and `make demo-cli SCENARIO=…`; `make demo` starts the dashboard in demo mode.
- End-to-end tests for all four scenarios plus the API.
- Measured: `missed-morning` at speed 60 runs from start to EXHAUSTED in 95 real seconds (with Bedrock fallbacks; real Bedrock adds a few seconds).
