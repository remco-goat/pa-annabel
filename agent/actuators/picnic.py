"""Boodschappen in het Picnic-mandje leggen.

Alleen mandje vullen — bestellen/afrekenen blijft altijd handwerk in de
Picnic-app, dus een verkeerde match kost hooguit een swipe bij het afrekenen.
"""
from __future__ import annotations

from python_picnic_api2 import PicnicAPI

from .. import config


def _client() -> PicnicAPI:
    token = config.PICNIC_AUTH_TOKEN
    if not token:
        raise RuntimeError(
            "Geen Picnic-sessiesleutel. Eenmalig inloggen met: "
            ".venv/bin/python -m agent.picnic_login"
        )
    return PicnicAPI(auth_token=token)


def _first_article(search_result) -> dict | None:
    """De zoek-API geeft geneste blokken terug; pak het eerste echte artikel."""
    stack = list(search_result or [])
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        if node.get("type") in ("SINGLE_ARTICLE", "ARTICLE") or (
            node.get("id") and node.get("name") and "items" not in node
        ):
            return node
        stack.extend(node.get("items", []) or [])
        stack.extend(node.get("links", []) or [])
    return None


def add_groceries(items: list[str]) -> str:
    """Zoekt elk boodschappenitem op en legt de beste match in het mandje.
    Geeft een controleerbare samenvatting terug (wat werd wat)."""
    api = _client()
    added, missed = [], []
    for wanted in items:
        try:
            hit = _first_article(api.search(wanted))
            if not hit:
                missed.append(wanted)
                continue
            api.add_product(str(hit["id"]), count=1)
            naam = hit.get("name", "?")
            added.append(f"{wanted} → {naam}")
        except Exception as exc:
            missed.append(f"{wanted} ({exc})")
    out = []
    if added:
        out.append("in het mandje: " + "; ".join(added))
    if missed:
        out.append("NIET gevonden: " + "; ".join(missed))
    return " | ".join(out) or "niets toegevoegd"
