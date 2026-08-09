"""Lichte runner die alléén opdrachten uit de app verwerkt.

    python -m agent.commands

Bedoeld voor een korte cron-interval (elk half uur): typ je overdag iets in de
app, dan hoeft dat niet op de ochtendrun te wachten. Kost niets als er geen
opdrachten staan — er wordt dan geen Claude-call gedaan.
"""
from __future__ import annotations

from datetime import datetime

from . import config, db, log
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
    if rows:
        db.insert("proposals", rows, returning=False)

    db.update(
        "signals",
        {"status": "briefed"},
        id=f"in.({','.join(str(c['id']) for c in commands)})",
    )
    db.finish_run(
        run_id, ok=True,
        stats={"opdrachten": len(commands), "voorstellen": len(rows), "tokens": result.get("_usage", {})},
    )
    for p in result["proposals"]:
        logger.info("  [%s] %s: %s", p["urgency"], p["kind"], p["title"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
