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

    # Zoekplan: eerst kort bepalen wát er nodig is (mail, Drive, stijl-
    # voorbeelden, financiële context), dan gericht ophalen.
    mail_hits: list[dict] = []
    drive_hits: list[dict] = []
    style_examples: dict[str, list[str]] = {}
    finance_context = ""
    try:
        from .brain import search_plan
        plan = search_plan(commands, model=config.MODEL_COMMANDS)

        from .collectors.gmail import search as gmail_search
        for q in plan["mail_queries"]:
            logger.info("  mail-zoekopdracht: %s", q)
            for hit in gmail_search(q, limit=5):
                if hit["message_id"] not in {h["message_id"] for h in mail_hits}:
                    mail_hits.append(hit)

        if plan["drive_queries"]:
            from .collectors.drive import search as drive_search
            for q in plan["drive_queries"]:
                logger.info("  drive-zoekopdracht: %s", q)
                for hit in drive_search(q, limit=5):
                    if hit["drive_file_id"] not in {h["drive_file_id"] for h in drive_hits}:
                        drive_hits.append(hit)

        if plan["personen"]:
            from .collectors.gmail import sent_examples
            for naam in plan["personen"]:
                voorbeelden = sent_examples(naam)
                if voorbeelden:
                    style_examples[naam] = voorbeelden
                    logger.info("  stijlvoorbeelden voor %s: %d", naam, len(voorbeelden))

        if plan.get("financieel"):
            from .finance import overview
            finance_context = overview()
            logger.info("  financiële context meegegeven")

        if mail_hits or drive_hits:
            logger.info("  treffers: %d mail, %d drive", len(mail_hits), len(drive_hits))
    except Exception:
        logger.exception("zoeken mislukt — opdrachten gaan door zonder zoekresultaten")

    try:
        result = think(commands, {}, open_tasks, datetime.now(config.TZ), commands_only=True,
                       model=config.MODEL_COMMANDS, mail_hits=mail_hits, drive_hits=drive_hits,
                       style_examples=style_examples, finance_context=finance_context)
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
                    "forward_message_id": p.get("forward_message_id", ""),
                    "grocery_items": p.get("grocery_items", []),
                    "email_action": p.get("email_action", ""),
                    "email_message_ids": p.get("email_message_ids", []),
                    "drive_attach_file_id": p.get("drive_attach_file_id", ""),
                    "web_flow": p.get("web_flow", ""),
                    "web_params_json": p.get("web_params_json", ""),
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
