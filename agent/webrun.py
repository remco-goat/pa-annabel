"""Voert één web_action-voorstel uit in GitHub Actions (annabel-web.yml).

    python -m agent.webrun <proposal_id>

Apart van agent.apply, omdat web-acties Playwright + Chromium nodig hebben en
de gewone tick licht moet blijven: playwright staat NIET in requirements.txt,
alleen de web-workflow installeert het. De hoofdsessie dispatch't deze
workflow vanuit apply.py zodra een web_action-voorstel is goedgekeurd.

Het voorstel levert in action: web_flow (naam uit agent.webflows.FLOWS) en
web_params (dict). Resultaat = tekst van de flow + signed URL naar de
full-page screenshot in Supabase Storage (bucket 'bewijs') als bewijs.
"""
from __future__ import annotations

import sys

from . import db, log, notify
from .webflows import FlowError, run_flow
from .webflows.storage import upload_screenshot

logger = log.setup("webrun")


def _bewijs(proposal_id: str, flow_name: str, png: bytes | None) -> str | None:
    """Screenshot uploaden; None als er geen is of de upload zelf faalt
    (het bewijs mag de uitkomst van de flow niet alsnog laten omvallen)."""
    if not png:
        return None
    try:
        return upload_screenshot(png, f"{proposal_id}-{flow_name}.png")
    except Exception:
        logger.exception("screenshot uploaden mislukt")
        return None


def main(proposal_id: str) -> int:
    rows = db.select("proposals", id=f"eq.{proposal_id}")
    if not rows:
        logger.error("voorstel %s niet gevonden", proposal_id)
        return 1
    proposal = rows[0]

    action = proposal.get("action") or {}
    flow_name = action.get("web_flow") or ""
    params = action.get("web_params") or {}

    run_id = db.start_run()
    logger.info("webflow %r voor voorstel %s (%s)", flow_name, proposal_id, proposal.get("title"))

    try:
        result, png = run_flow(flow_name, params)
        url = _bewijs(proposal_id, flow_name, png)
        tekst = result + (f" | bewijs: {url}" if url else "")
        db.update(
            "proposals",
            {"status": "done", "result": tekst[:1000], "executed_at": db.now_iso()},
            id=f"eq.{proposal_id}",
        )
        db.finish_run(run_id, ok=True, stats={"web_flow": flow_name})
        logger.info("  ✓ %s", tekst)
        return 0
    except Exception as exc:
        logger.exception("webflow mislukt: %s", flow_name)
        url = _bewijs(proposal_id, flow_name, getattr(exc, "screenshot", None) if isinstance(exc, FlowError) else None)
        tekst = str(exc) + (f" | bewijs: {url}" if url else "")
        db.update(
            "proposals",
            {"status": "failed", "result": tekst[:1000], "executed_at": db.now_iso()},
            id=f"eq.{proposal_id}",
        )
        db.finish_run(run_id, ok=False, stats={"web_flow": flow_name}, error=str(exc)[:1000])
        notify.push("Annabel", f"Web-actie mislukt: {proposal.get('title', flow_name)} — kijk even in de app")
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("gebruik: python -m agent.webrun <proposal_id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1].strip()))
