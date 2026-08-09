"""Dunne Supabase-client (PostgREST) met de service_role key.

Bewust geen supabase-py: dit zijn vijf endpoints en httpx doet de rest.
De agent omzeilt RLS met de service key — de PWA doet dat juist niet.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from . import config


def now_iso() -> str:
    """Tijdstempel voor PostgREST.

    Niet de string "now()" gebruiken: PostgREST stuurt die als letterlijke
    tekst mee en Postgres kan 'now()' niet naar timestamptz casten.
    """
    return datetime.now(timezone.utc).isoformat()

_HEADERS = {
    "apikey": config.SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

_client = httpx.Client(
    base_url=f"{config.SUPABASE_URL}/rest/v1",
    headers=_HEADERS,
    timeout=30.0,
)


def _raise(resp: httpx.Response) -> None:
    if resp.is_error:
        raise RuntimeError(f"Supabase {resp.status_code} op {resp.request.url}: {resp.text[:500]}")


def select(table: str, **params: str) -> list[dict[str, Any]]:
    resp = _client.get(f"/{table}", params=params)
    _raise(resp)
    return resp.json()


def insert(table: str, rows: dict | list[dict], *, returning: bool = True) -> list[dict[str, Any]]:
    """Voegt rijen toe.

    PostgREST eist bij een bulk-insert dat élke rij dezelfde sleutels heeft
    ('All object keys must match'); `Prefer: missing=default` wordt op Supabase
    genegeerd. Daarom groeperen we per sleutelset en sturen we per groep één
    verzoek. Zelf met None opvullen kan niet: dat schrijft NULL in plaats van de
    kolomdefault, en `status`/`created_at` zijn NOT NULL.
    """
    headers = {"Prefer": "return=representation" if returning else "return=minimal"}

    if isinstance(rows, dict):
        batches: list[list[dict] | dict] = [rows]
    else:
        if not rows:
            return []
        grouped: dict[frozenset, list[dict]] = {}
        for row in rows:
            grouped.setdefault(frozenset(row), []).append(row)
        batches = list(grouped.values())

    out: list[dict[str, Any]] = []
    for batch in batches:
        resp = _client.post(f"/{table}", json=batch, headers=headers)
        _raise(resp)
        if returning and resp.content:
            out.extend(resp.json())
    return out


def upsert(table: str, rows: list[dict], *, on_conflict: str, returning: bool = True) -> list[dict[str, Any]]:
    headers = {
        "Prefer": f"resolution=merge-duplicates,{'return=representation' if returning else 'return=minimal'}"
    }
    resp = _client.post(f"/{table}", json=rows, params={"on_conflict": on_conflict}, headers=headers)
    _raise(resp)
    return resp.json() if returning and resp.content else []


def update(table: str, patch: dict, **params: str) -> list[dict[str, Any]]:
    headers = {"Prefer": "return=representation"}
    resp = _client.patch(f"/{table}", json=patch, params=params, headers=headers)
    _raise(resp)
    return resp.json() if resp.content else []


# --- helpers op maat ------------------------------------------------------

def start_run() -> int:
    return insert("runs", {})[0]["id"]


def finish_run(run_id: int, *, ok: bool, stats: dict, error: str | None = None) -> None:
    update(
        "runs",
        {"finished_at": now_iso(), "ok": ok, "stats": stats, "error": error},
        id=f"eq.{run_id}",
    )


def record_signals(signals: Iterable[dict], *, persist: bool = True) -> list[dict[str, Any]]:
    """Schrijft signalen weg en geeft alleen de NIEUWE terug.

    Met persist=False (dry run) wordt alleen bepaald wát nieuw is, zonder iets
    weg te schrijven — anders eet een testrun de wachtrij op en levert de
    volgende run niets meer.

    Dit is de dedupe-kern: een signaal dat we gisteren al gezien hebben komt
    hier wel binnen (last_seen_at wordt bijgewerkt) maar gaat niet opnieuw
    naar het brein. Zonder dit krijg je elke ochtend dezelfde vijf mailtjes.
    """
    rows = list(signals)
    if not rows:
        return []

    keys = {(r["source"], r["external_id"]) for r in rows}
    known: set[tuple[str, str]] = set()
    for source in {s for s, _ in keys}:
        ids = [e for s, e in keys if s == source]
        # PostgREST in.(...) — quote waarden met komma's
        quoted = ",".join('"' + i.replace('"', '""') + '"' for i in ids)
        for row in select("signals", source=f"eq.{source}", external_id=f"in.({quoted})", select="source,external_id"):
            known.add((row["source"], row["external_id"]))

    fresh = [r for r in rows if (r["source"], r["external_id"]) not in known]
    if not persist:
        # Dry run: geef de nieuwe signalen terug zoals ze eruit zouden zien, maar
        # laat de database ongemoeid zodat je de run kunt herhalen.
        return [{**r, "id": None} for r in fresh]

    upsert("signals", rows, on_conflict="source,external_id", returning=False)
    if not fresh:
        return []

    quoted = ",".join('"' + r["external_id"].replace('"', '""') + '"' for r in fresh)
    sources = ",".join(sorted({r["source"] for r in fresh}))
    return select(
        "signals",
        source=f"in.({sources})",
        external_id=f"in.({quoted})",
        select="*",
    )


def pending_proposals() -> list[dict[str, Any]]:
    return select("proposals", status="eq.pending", order="created_at.desc")


def approved_proposals() -> list[dict[str, Any]]:
    return select("proposals", status="eq.approved", order="created_at.asc")
