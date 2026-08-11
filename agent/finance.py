"""Financiële waakhond — registratie en overzicht.

Het brein herkent facturen/abonnementen in nieuwe mail (finance_items in de
run-output); hier worden ze opgeslagen als signals (source='finance') en
geaggregeerd tot een compacte context zodat het brein afwijkingen kan zien
("Azure is ineens 3x zo duur") en vragen kan beantwoorden ("wat geef ik uit?").
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import db


def store(items: list[dict]) -> int:
    """Slaat herkende posten op; dubbelen (zelfde mail+leverancier+bedrag)
    worden door de dedupe op (source, external_id) genegeerd."""
    rows = []
    for it in items or []:
        supplier = (it.get("supplier") or "?").strip()
        amount = float(it.get("amount") or 0)
        rows.append(
            {
                "source": "finance",
                "external_id": f"{it.get('source_id','?')}:{supplier}:{amount}",
                "kind": it.get("kind") or "other",
                "title": f"{supplier} — {amount:.2f} {it.get('currency') or 'EUR'}",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "status": "handled",   # geen actie-item, puur registratie
                "payload": {
                    "supplier": supplier,
                    "amount": amount,
                    "currency": it.get("currency") or "EUR",
                    "kind": it.get("kind") or "other",
                    "mail_id": it.get("source_id", ""),
                },
            }
        )
    if not rows:
        return 0
    db.upsert("signals", rows, on_conflict="source,external_id", returning=False)
    return len(rows)


def overview(days: int = 60) -> str:
    """Compact tekstoverzicht per leverancier over de afgelopen periode."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.select(
        "signals",
        source="eq.finance",
        occurred_at=f"gte.{since}",
        select="payload,occurred_at",
        order="occurred_at.desc",
    )
    if not rows:
        return ""

    per: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for r in rows:
        pl = r.get("payload") or {}
        per[pl.get("supplier", "?")].append(
            (float(pl.get("amount") or 0), r["occurred_at"][:10])
        )

    regels = [f"Geregistreerde facturen/abonnementen, laatste {days} dagen:"]
    for supplier, posten in sorted(per.items(), key=lambda kv: -sum(a for a, _ in kv[1])):
        totaal = sum(a for a, _ in posten)
        laatste = max(d for _, d in posten)
        bedragen = ", ".join(f"{a:.2f}" for a, _ in posten[:6])
        regels.append(f"- {supplier}: {len(posten)}x, totaal {totaal:.2f} EUR (laatste {laatste}; bedragen: {bedragen})")
    return "\n".join(regels[:25])
