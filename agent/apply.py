"""Voert uit wat jij hebt goedgekeurd.

    python -m agent.apply

Draait direct na agent.run in dezelfde cron, zodat wat je gisteren goedkeurde
vanochtend is uitgevoerd. Alleen voorstellen met status 'approved' komen hier
langs — pending en rejected blijven onaangeroerd.
"""
from __future__ import annotations

from . import db, log, notify
from .actuators import gmail_draft
from .collectors.todo import adapter as todo_adapter


def _execute(proposal: dict) -> str:
    action = proposal.get("action") or {}
    kind = proposal["kind"]

    # 'Afvinken' in de app: de bestaande Todoist-taak sluiten i.p.v. iets aanmaken.
    if action.get("complete_task_id"):
        task_id = str(action["complete_task_id"])
        result = todo_adapter().complete(task_id)
        # Meteen uit de takenlijst in de app; de tick-sync zou dit ook doen,
        # maar dan pas een kwartier later.
        db.update("signals", {"status": "handled"},
                  source="eq.todo", external_id=f"eq.{task_id}")
        return result

    if kind == "draft_reply" and action.get("send"):
        # Alleen gezet wanneer Remco in de app expliciet op 'Verstuur' tikte.
        return gmail_draft.send_message(
            to=action.get("draft_to", ""),
            subject=action.get("draft_subject", ""),
            body=action.get("draft_body", ""),
            thread_id=action.get("thread_id", ""),
        )

    if kind == "forward_email":
        return gmail_draft.forward_as_draft(
            message_id=action.get("forward_message_id", ""),
            to=action.get("draft_to", ""),
            note=action.get("draft_body", ""),
        )

    if kind == "web_action":
        # Zwaar (Playwright) → aparte workflow; agent.webrun rondt het proposal
        # daarna zelf af met resultaat + bewijs-screenshot.
        import json as _json
        import os
        import httpx as _httpx
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            import subprocess
            token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
        resp = _httpx.post(
            "https://api.github.com/repos/remco-goat/pa-annabel/actions/workflows/annabel-web.yml/dispatches",
            json={"ref": "main", "inputs": {"proposal_id": str(proposal["id"])}},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "User-Agent": "annabel"},
            timeout=30,
        )
        resp.raise_for_status()
        return "web-actie gestart — resultaat en bewijs volgen op deze kaart"

    if kind == "email_action":
        from .actuators.gmail_actions import apply_email_action
        return apply_email_action(
            action.get("email_action", ""),
            action.get("email_message_ids") or [],
        )

    if kind == "groceries":
        items = action.get("grocery_items") or []
        if not items:
            raise ValueError("geen boodschappenitems in het voorstel")
        try:
            from .actuators.picnic import add_groceries
            return add_groceries(items)
        except Exception as exc:
            # Picnic-koppeling (nog) niet beschikbaar → boodschappenlijst als
            # taak, zodat de opdracht nooit in het niets verdwijnt.
            url = todo_adapter().create(
                "Boodschappen",
                note=f"Picnic-mandje vullen lukte niet ({exc}); handmatig bestellen.",
                subtasks=items,
            )
            return f"Picnic niet beschikbaar — als taak op je lijst gezet: {url}"

    if kind == "create_task":
        result = todo_adapter().create(
            action.get("task_title") or proposal["title"],
            due=action.get("task_due") or None,
            note=proposal.get("detail"),
            subtasks=action.get("task_subtasks") or None,
        )
        _mirror_task(result, action.get("task_title") or proposal["title"],
                     action.get("task_due") or None)
        return result

    if kind == "draft_reply":
        return gmail_draft.create_draft(
            to=action.get("draft_to", ""),
            subject=action.get("draft_subject", ""),
            body=action.get("draft_body", ""),
            thread_id=action.get("thread_id", ""),
            drive_file_id=action.get("drive_attach_file_id", ""),
        )

    if kind in ("buy", "reminder"):
        # Kopen doet de agent niet. Wat hij wél doet: het als taak vastleggen
        # zodat het niet verdwijnt. Afrekenen blijft handwerk.
        result = todo_adapter().create(
            action.get("task_title") or proposal["title"],
            due=action.get("task_due") or None,
            note=proposal.get("detail"),
        )
        _mirror_task(result, action.get("task_title") or proposal["title"],
                     action.get("task_due") or None)
        return result

    if kind == "fyi":
        return "ter kennisgeving — geen actie"

    return f"onbekend type: {kind}"


def _mirror_task(result_url: str, title: str, due: str | None) -> None:
    """Nieuwe Todoist-taak direct in signals zetten, zodat de takenlijst in de
    app niet op de uurlijkse run hoeft te wachten. Status 'briefed': het brein
    kent hem al — hij komt uit een goedgekeurd voorstel."""
    import re
    m = re.search(r"/task/([A-Za-z0-9]+)", result_url or "")
    if not m:
        return
    try:
        db.upsert("signals", [{
            "source": "todo",
            "external_id": m.group(1),
            "kind": "task",
            "title": title,
            "occurred_at": due or db.now_iso(),
            "payload": {"due": due, "overdue": False,
                        "url": f"https://app.todoist.com/app/task/{m.group(1)}"},
            "status": "briefed",
            "last_seen_at": db.now_iso(),
        }], on_conflict="source,external_id", returning=False)
    except Exception:
        logger.exception("taak spiegelen naar de app mislukt (komt goed bij de uur-run)")


logger = log.setup("apply")


def main() -> int:
    # Takenlijst in de app actueel houden: elke tick (kwartier) de open
    # Todoist-taken spiegelen — afgevinkt is afgevinkt, waar dat ook gebeurde.
    try:
        stats = db.sync_todo(todo_adapter().fetch())
        if stats["afgevoerd"] or stats["heropend"]:
            logger.info("takenlijst gesynct: %s", stats)
    except Exception:
        logger.exception("taken-sync mislukt")

    todo = db.approved_proposals()
    if not todo:
        logger.info("Niets goedgekeurd om uit te voeren.")
        return 0

    logger.info("%d goedgekeurde voorstellen uitvoeren", len(todo))
    ok = failed = 0
    for proposal in todo:
        try:
            result = _execute(proposal)
            db.update(
                "proposals",
                {"status": "done", "result": result[:1000], "executed_at": db.now_iso()},
                id=f"eq.{proposal['id']}",
            )
            logger.info("  ✓ %s — %s", proposal["title"], result)
            ok += 1
        except Exception as exc:
            logger.exception("uitvoeren mislukt: %s", proposal["title"])
            db.update(
                "proposals",
                {"status": "failed", "result": str(exc)[:1000], "executed_at": db.now_iso()},
                id=f"eq.{proposal['id']}",
            )
            failed += 1

    if failed:
        notify.push("Annabel", f"{failed} actie(s) mislukt — kijk even in de app")
    logger.info("Klaar: %d gelukt, %d mislukt.", ok, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
