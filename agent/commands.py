"""Lichte runner die alléén opdrachten uit de app verwerkt.

    python -m agent.commands

Draait op korte cron-interval. Kost niets als er geen opdrachten staan.

Opdrachten worden DIRECT uitgevoerd, zonder goedkeuringsronde: een opdracht die
Remco zelf typt is al zijn goedkeuring. Dat kan omdat de uitvoerders alleen
onschuldige dingen doen (taak aanmaken, concept klaarzetten) — nooit versturen,
kopen of verwijderen. Alleen fyi-antwoorden blijven als kaart staan om te lezen.
"""
from __future__ import annotations

from datetime import datetime

from . import config, db, log
from . import notify
from .apply import _execute
from .brain import think
from .collectors import todo as todo_collector


logger = log.setup("commands")


def main() -> int:
    commands = db.select("signals", source="eq.command", status="eq.new")
    if not commands:
        return 0  # stil: dit draait vaak, en meestal is er niets

    logger.info("%d opdracht(en) uit de app", len(commands))
    run_id = db.start_run()

    # Open taken als context, zodat "zet X op mijn lijst" geen duplicaat wordt.
    try:
        todo_signals = todo_collector.collect()
    except Exception:
        todo_signals = []
    open_tasks = [
        {"title": s["title"], "due": (s.get("payload") or {}).get("due")}
        for s in todo_signals
    ]

    try:
        result = think(commands, {}, open_tasks, datetime.now(config.TZ), commands_only=True)
    except Exception as exc:
        logger.exception("brein faalde op opdrachten")
        db.finish_run(run_id, ok=False, stats={"opdrachten": len(commands)}, error=str(exc))
        # Traceback staat in het logbestand; niet ook naar stderr —
        # in GitHub Actions zijn die logs publiek.
        raise SystemExit(1)

    by_external = {s["external_id"]: s["id"] for s in commands}
    rows = []
    for p in result["proposals"]:
        rows.append(
            {
                "run_id": run_id,
                "signal_id": by_external.get(p.get("source_id") or ""),
                "kind": p["kind"],
                "title": p["title"],
                "detail": p["detail"],
                "urgency": p["urgency"],
                "action": {
                    "task_title": p.get("task_title", ""),
                    "task_due": p.get("task_due", ""),
                    "draft_to": p.get("draft_to", ""),
                    "draft_subject": p.get("draft_subject", ""),
                    "draft_body": p.get("draft_body", ""),
                    "thread_id": p.get("thread_id", ""),
                    "source": "command",
                },
            }
        )
    made = db.insert("proposals", rows) if rows else []

    # Direct uitvoeren — behalve fyi, dat is een antwoord om te lezen.
    done = failed = 0
    for proposal in made:
        if proposal["kind"] == "fyi":
            continue
        try:
            outcome = _execute(proposal)
            db.update(
                "proposals",
                {"status": "done", "result": outcome[:1000],
                 "decided_at": db.now_iso(), "executed_at": db.now_iso()},
                id=f"eq.{proposal['id']}",
            )
            logger.info("  direct uitgevoerd: %s — %s", proposal["title"], outcome)
            done += 1
        except Exception as exc:
            db.update(
                "proposals",
                {"status": "failed", "result": str(exc)[:1000], "executed_at": db.now_iso()},
                id=f"eq.{proposal['id']}",
            )
            logger.exception("direct uitvoeren mislukt: %s", proposal["title"])
            failed += 1

    db.update(
        "signals",
        {"status": "briefed"},
        id=f"in.({','.join(str(c['id']) for c in commands)})",
    )
    fyi = [p for p in made if p["kind"] == "fyi"]
    if fyi:
        notify.push("Annabel", f"Antwoord klaar: {fyi[0]['title']}")
    if failed:
        notify.push("Annabel", f"{failed} opdracht(en) mislukt — kijk even in de app")

    db.finish_run(
        run_id, ok=failed == 0,
        stats={"opdrachten": len(commands), "voorstellen": len(rows),
               "uitgevoerd": done, "mislukt": failed, "tokens": result.get("_usage", {})},
    )
    for p in result["proposals"]:
        logger.info("  [%s] %s: %s", p["urgency"], p["kind"], p["title"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
