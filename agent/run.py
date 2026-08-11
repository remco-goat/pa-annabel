"""Dagelijkse run: verzamelen → nadenken → voorstellen klaarzetten.

    python -m agent.run

Voert zelf niets uit. Alles wat de agent wil doen belandt als 'pending' in
Supabase en wacht op jouw tik in de PWA. Uitvoeren doet agent.apply.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from . import config, db, log
from .brain import think
from . import notify
from .collectors import calendar as calendar_collector
from .collectors import gmail as gmail_collector
from .collectors import todo as todo_collector


logger = log.setup("run")


def _collect(name: str, fn):
    try:
        return fn()
    except Exception:
        logger.exception("collector %s faalde", name)
        return None


def main() -> int:
    now = datetime.now(config.TZ)

    # Uurvenster-guard: de scheduler (pg_cron) kent geen tijdzones en vuurt in
    # UTC iets ruimer dan het gewenste NL-venster. Bij geplande runs bepalen we
    # hier zelf of het lokale uur binnen 07:00-19:00 valt; handmatige runs en
    # tests (zonder ANNABEL_SCHEDULED=1) draaien altijd door.
    if os.environ.get("ANNABEL_SCHEDULED") == "1" and not 7 <= now.hour <= 19:
        logger.info("buiten het brief-venster (%d:00 NL) — overgeslagen", now.hour)
        return 0

    run_id = db.start_run()
    logger.info("Run %s — %s", run_id, f"{now:%Y-%m-%d %H:%M}")

    stats: dict[str, int] = {}

    gmail_result = _collect("gmail", gmail_collector.collect) or ([], {})
    mail_signals, documents = gmail_result
    cal_signals = _collect("calendar", calendar_collector.collect) or []
    todo_signals = _collect("todo", todo_collector.collect) or []

    stats |= {
        "gmail": len(mail_signals),
        "calendar": len(cal_signals),
        "todo": len(todo_signals),
        "documents": sum(len(d) for d in documents.values()),
    }
    logger.info("  verzameld: %s", stats)

    all_signals = mail_signals + cal_signals + todo_signals
    if not all_signals:
        db.finish_run(run_id, ok=True, stats=stats | {"note": "niets verzameld"})
        logger.info("  niets te doen.")
        return 0

    # Dedupe: alleen wat we nog niet eerder hebben gezien gaat naar het brein.
    fresh = db.record_signals(all_signals, persist=not config.DRY_RUN)
    stats["nieuw"] = len(fresh)
    logger.info("  nieuw sinds vorige run: %d", len(fresh))

    # Opdrachten uit de app staan al in de database (de PWA schrijft ze daar
    # rechtstreeks in) en tellen dus niet als collector-signaal — apart ophalen.
    commands = db.select("signals", source="eq.command", status="eq.new")
    if commands:
        stats["opdrachten"] = len(commands)
        logger.info("  opdrachten uit de app: %d", len(commands))
        fresh = fresh + commands

    if not fresh:
        db.finish_run(run_id, ok=True, stats=stats | {"note": "geen nieuwe signalen"})
        logger.info("  geen nieuwe signalen — geen brief.")
        return 0

    # Bijlagen alleen meesturen voor mails die daadwerkelijk nieuw zijn.
    fresh_ids = {s["external_id"] for s in fresh}
    docs_for_fresh = {k: v for k, v in documents.items() if k in fresh_ids}

    open_tasks = [
        {"title": s["title"], "due": (s.get("payload") or {}).get("due"),
         "overdue": (s.get("payload") or {}).get("overdue")}
        for s in todo_signals
    ]

    from . import finance
    try:
        fin_ctx = finance.overview()
    except Exception:
        logger.exception("financieel overzicht ophalen mislukt")
        fin_ctx = ""

    try:
        result = think(fresh, docs_for_fresh, open_tasks, now, finance_context=fin_ctx)
    except Exception as exc:
        logger.exception("brein faalde")
        db.finish_run(run_id, ok=False, stats=stats, error=str(exc))
        # Traceback staat in het logbestand; niet ook naar stderr —
        # in GitHub Actions zijn die logs publiek.
        raise SystemExit(1)

    try:
        n_fin = finance.store(result.get("finance_items") or [])
        if n_fin:
            stats["financieel"] = n_fin
            logger.info("  financiële posten geregistreerd: %d", n_fin)
    except Exception:
        logger.exception("financiële posten opslaan mislukt")

    stats["voorstellen"] = len(result["proposals"])
    stats["tokens"] = result.get("_usage", {})
    logger.info("  brief: %s", result["headline"])
    logger.info("  voorstellen: %d", len(result["proposals"]))

    if config.DRY_RUN:
        for p in result["proposals"]:
            logger.info("    [%s] %s: %s", p["urgency"], p["kind"], p["title"])
        db.finish_run(run_id, ok=True, stats=stats | {"dry_run": True})
        return 0

    db.insert(
        "briefs",
        {
            "run_id": run_id,
            "headline": result["headline"],
            # Losse punten als JSON-array; de app rendert ze afstreepbaar.
            "body": json.dumps(result["brief_points"], ensure_ascii=False),
        },
        returning=False,
    )

    by_external = {s["external_id"]: s["id"] for s in fresh}
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
                    "source": p.get("source", ""),
                },
            }
        )
    if rows:
        db.insert("proposals", rows, returning=False)
        n = notify.push("Annabel", f"{len(rows)} nieuwe voorstellen — {result['headline']}")
        logger.info("  pushmelding naar %d apparaat/apparaten", n)

    db.update(
        "signals",
        {"status": "briefed"},
        id=f"in.({','.join(str(s['id']) for s in fresh)})",
    )

    db.finish_run(run_id, ok=True, stats=stats)
    logger.info("  klaar. Open de app om goed te keuren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
