"""Voert uit wat jij hebt goedgekeurd.

    python -m agent.apply

Draait direct na agent.run in dezelfde cron, zodat wat je gisteren goedkeurde
vanochtend is uitgevoerd. Alleen voorstellen met status 'approved' komen hier
langs — pending en rejected blijven onaangeroerd.
"""
from __future__ import annotations

from . import db
from .actuators import gmail_draft
from .collectors.todo import adapter as todo_adapter


def _execute(proposal: dict) -> str:
    action = proposal.get("action") or {}
    kind = proposal["kind"]

    if kind == "create_task":
        return todo_adapter().create(
            action.get("task_title") or proposal["title"],
            due=action.get("task_due") or None,
            note=proposal.get("detail"),
        )

    if kind == "draft_reply":
        return gmail_draft.create_draft(
            to=action.get("draft_to", ""),
            subject=action.get("draft_subject", ""),
            body=action.get("draft_body", ""),
            thread_id=action.get("thread_id", ""),
        )

    if kind in ("buy", "reminder"):
        # Kopen doet de agent niet. Wat hij wél doet: het als taak vastleggen
        # zodat het niet verdwijnt. Afrekenen blijft handwerk.
        return todo_adapter().create(
            action.get("task_title") or proposal["title"],
            due=action.get("task_due") or None,
            note=proposal.get("detail"),
        )

    if kind == "fyi":
        return "ter kennisgeving — geen actie"

    return f"onbekend type: {kind}"


def main() -> int:
    todo = db.approved_proposals()
    if not todo:
        print("Niets goedgekeurd om uit te voeren.")
        return 0

    print(f"{len(todo)} goedgekeurde voorstellen uitvoeren")
    ok = failed = 0
    for proposal in todo:
        try:
            result = _execute(proposal)
            db.update(
                "proposals",
                {"status": "done", "result": result[:1000], "executed_at": db.now_iso()},
                id=f"eq.{proposal['id']}",
            )
            print(f"  ✓ {proposal['title']} — {result}")
            ok += 1
        except Exception as exc:
            db.update(
                "proposals",
                {"status": "failed", "result": str(exc)[:1000], "executed_at": db.now_iso()},
                id=f"eq.{proposal['id']}",
            )
            print(f"  ✗ {proposal['title']} — {exc}")
            failed += 1

    print(f"Klaar: {ok} gelukt, {failed} mislukt.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
