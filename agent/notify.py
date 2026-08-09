"""Pushmeldingen naar de PWA (web push, VAPID).

De abonnementen staan als rijen in `signals` (source='push_sub') — de app
schrijft ze daar zelf in, zodat er geen extra tabel/migratie nodig was.
Meldingen zijn bewust karig van inhoud: de details staan in de app.
"""
from __future__ import annotations

import json
import logging

from pywebpush import WebPushException, webpush

from . import config, db

logger = logging.getLogger(__name__)


def push(title: str, body: str) -> int:
    """Stuurt een melding naar alle geregistreerde apparaten. Faalt stil:
    een kapotte melding mag nooit een run breken."""
    if not config.VAPID_PRIVATE_KEY:
        return 0

    try:
        subs = db.select("signals", source="eq.push_sub", status="eq.new")
    except Exception:
        logger.exception("push-abonnementen ophalen mislukt")
        return 0

    sent = 0
    for sub in subs:
        info = sub.get("payload") or {}
        try:
            webpush(
                subscription_info=info,
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": "mailto:r.kuilman@aviclaim.nl"},
                ttl=3600,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                # Abonnement is dood (app verwijderd, meldingen uitgezet):
                # opruimen zodat we er niet elke run tegenaan lopen.
                try:
                    db.update("signals", {"status": "ignored"}, id=f"eq.{sub['id']}")
                except Exception:
                    pass
                logger.info("dood push-abonnement opgeruimd (%s)", status)
            else:
                logger.warning("push mislukt: %s", exc)
        except Exception:
            logger.exception("push mislukt")
    return sent
