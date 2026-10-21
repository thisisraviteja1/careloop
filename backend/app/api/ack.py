"""The big-button ack page: one large, accessible "I'm OK" button for people who don't use
Telegram, plus a second button for caregivers. Works without JavaScript."""

from __future__ import annotations

from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import audit
from app.core import clock
from app.core.tokens import AckClaim, TokenError, verify_ack
from app.db.models import Anomaly
from app.db.session import session_scope
from app.escalation.runner import acknowledge

router = APIRouter()

CHOICES = {"ok": "I'm OK", "handling": "I'm handling it"}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · CareLoop</title>
<style>
  :root {{ --bg: #f7f5f0; --ink: #1d1f1e; --muted: #4a4f4c; --ok: #0f5c2e; --ok-ink: #ffffff;
          --alt: #ffffff; --alt-ink: #1d1f1e; --line: #1d1f1e; --focus: #b45309; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #141615; --ink: #f2f1ed; --muted: #c9cbc6; --ok: #3fb26b; --ok-ink: #0b1a10;
            --alt: #1f2321; --alt-ink: #f2f1ed; --line: #c9cbc6; --focus: #f59e0b; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font: 20px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 34rem; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
  h1 {{ font-size: 2rem; line-height: 1.2; margin: 0 0 .5rem; }}
  p {{ color: var(--muted); margin: 0 0 1.5rem; }}
  form {{ display: grid; gap: 1rem; }}
  button {{ width: 100%; min-height: 88px; border-radius: 16px; font: inherit;
           font-size: 1.6rem; font-weight: 700; cursor: pointer; border: 3px solid var(--line); }}
  .primary {{ background: var(--ok); color: var(--ok-ink); border-color: var(--ok); }}
  .secondary {{ min-height: 64px; font-size: 1.25rem; background: var(--alt);
               color: var(--alt-ink); }}
  button:focus-visible {{ outline: 4px solid var(--focus); outline-offset: 4px; }}
  .done {{ font-size: 1.5rem; color: var(--ink); }}
</style>
</head>
<body><main>{body}</main></body>
</html>"""


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=escape(title), body=body), status_code=status)


def calm(message: str, status: int = 200) -> HTMLResponse:
    return page("CareLoop", f'<h1>CareLoop</h1><p class="done" role="status">'
                            f"{escape(message)}</p>", status)


def _claim(request: Request, token: str) -> AckClaim | None:
    try:
        return verify_ack(request.app.state.careloop.ack_secret, token, clock.now())
    except TokenError:
        return None


@router.get("/ack/{token}", response_class=HTMLResponse)
def ack_page(request: Request, token: str) -> HTMLResponse:
    claim = _claim(request, token)
    if claim is None:
        return calm("This link has expired or isn't valid. Nothing else is needed from you.",
                    status=404)
    name = request.app.state.careloop.settings.person_name
    with session_scope() as session:
        anomaly = session.get(Anomaly, claim.anomaly_id)
        audit.record(session, "ack.page_view", f"link for {claim.role}", "shown")
        if anomaly is not None and anomaly.state == "ACKNOWLEDGED":
            return calm("This has already been handled. Thank you.")
    if claim.role == "elder":
        heading, intro = f"Hello {name}", "Just checking in. Tap the green button if all is well."
    else:
        heading, intro = (f"Checking in on {name}",
                          f"Tap “I'm handling it” if you're looking after {name} now.")
    primary, secondary = (("ok", "handling") if claim.role == "elder" else ("handling", "ok"))
    body = (
        f"<h1>{escape(heading)}</h1><p>{escape(intro)}</p>"
        f'<form method="post" action="/ack/{escape(token)}">'
        f'<button class="primary" type="submit" name="choice" value="{primary}">'
        f"{escape(CHOICES[primary])}</button>"
        f'<button class="secondary" type="submit" name="choice" value="{secondary}">'
        f"{escape(CHOICES[secondary])}</button></form>"
    )
    return page(heading, body)


@router.post("/ack/{token}", response_class=HTMLResponse)
async def ack_submit(request: Request, token: str) -> HTMLResponse:
    claim = _claim(request, token)
    if claim is None:
        return calm("This link has expired or isn't valid. Nothing else is needed from you.",
                    status=404)
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    choice = (form.get("choice") or ["ok"])[0]
    label = CHOICES.get(choice, CHOICES["ok"])
    with session_scope() as session:
        result = acknowledge(session, claim.anomaly_id, claim.role, f"ack page ({label})",
                             clock.now())
    return calm(result.message, status=200 if result.ok else 409)
