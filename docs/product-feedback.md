# Product feedback

Draft built from [`friction-log.md`](friction-log.md). Sections marked *to complete* need the team's experience with real credentials.

## Ring API and Developer Playground

**What we used it for:** activity history (human motion and doorbell presses) to learn a person's morning routine, device status to tell a dead camera from a missing person, and one image snapshot per anomaly.

**What worked**
- The Playground's "Generate Token" gives a working bearer token with no OAuth setup, which is the right on-ramp for a hackathon.
- JSON:API responses and a small, clear set of endpoints made a typed client quick to write.
- The official `ring-api-helloworld` scripts are a good, copyable starting point.

**What needs work**
- The API reference doesn't show example responses, query parameters or paging for event history (friction log #2, #6).
- Event type names differ between the docs and the sample (`motion_detected` + `sub_type: human` and `button_press` versus `motion.human` and `ding`) (#3). A wrong filter silently returns nothing, which for a care product looks like an inactive person.
- The sample says events can't be polled, which contradicts the event history endpoint (#5).
- No snapshot example in the sample repo (#4). We wrote one to contribute upstream.
- *To complete:* the Playground token experience and the first real probe.

**Onboarding experience:** fast to a first authenticated call; slow to a confident data model, because the shapes had to be inferred.

**Would we build with it again?** Yes. Event history plus snapshots on demand is exactly what privacy-respecting care tools need: no continuous video, and one frame only when something looks wrong.

## Ring docs MCP server

**What we used it for:** planned for confirming response shapes from the coding agent.

**What happened:** our sandboxed build environment couldn't reach the host (our own network allowlist, friction log #1). *To complete* if a team member uses it from a laptop.

**Suggestion:** also publish the docs as a downloadable bundle or `llms.txt` for locked-down CI and agent sandboxes.

## Amazon Bedrock

**What we used it for:** the Converse API with an image block to describe one doorway snapshot in at most 25 words, and the Converse API (text) to phrase a short caregiver message from a facts JSON. A deterministic validator decides whether the phrasing is used.

**What worked**
- One API (Converse) for both image and text across model families, so swapping models is a config change.
- botocore's `Stubber` validates requests against the real API schema in unit tests, with no network.
- `usage` token counts in every response make cost-aware audit logging easy.

**What needs work**
- *To complete:* model access requests, and whether inference-profile IDs were needed in the chosen region (`scripts/check_bedrock.py` reports both).

**Would we build with it again?** *To complete after real calls.*

## Feature requests

| Priority | Request | Why (problem we hit) |
|---|---|---|
| Critical | Document event history query parameters (time range, paging, page size, max window) | Polls may re-download the whole history (#6) |
| Critical | One canonical list of event type names, used by both the filter and the responses | A wrong name silently returns no events (#3) |
| Important | Per-endpoint reference pages with example responses, or an OpenAPI spec | Shapes had to be inferred (#2) |
| Important | Snapshot example in `ring-api-helloworld` (request body, `components`, response type) | No example to follow (#4) |
| Important | Fix the "no polling API" comment in the sample | Contradicts the docs (#5) |
| Nice to have | Docs bundle or `llms.txt` alongside the MCP server | Sandboxed agents can't reach new hosts (#1) |
