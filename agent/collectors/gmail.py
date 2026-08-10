"""Gmail-collector.

Haalt de inbox van de afgelopen X uur op. Notulen zijn hier geen aparte bron:
het zijn gewoon mails met een bijlage of een tekst die op een verslag lijkt, en
die reiken we als document door aan het brein.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .. import config
from ..google_auth import gmail_service

MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024   # Claude accepteert ~32MB request; hou marge
MAX_ATTACHMENTS_PER_MAIL = 3
BODY_CHAR_LIMIT = 8_000

# Woorden die een mail tot notulen-kandidaat maken. Ruim ingesteld: het brein
# beslist uiteindelijk, dit filtert alleen welke bijlagen we meesturen.
MINUTES_HINTS = re.compile(
    r"\b(notulen|verslag|minutes|actiepunten|action items|besluitenlijst|"
    r"meeting notes|gespreksverslag|overleg|recap|transcript)\b",
    re.IGNORECASE,
)


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _walk(part: dict):
    yield part
    for sub in part.get("parts", []) or []:
        yield from _walk(sub)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _body_text(payload: dict) -> str:
    plain, html = "", ""
    for part in _walk(payload):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        if mime == "text/plain" and not plain:
            plain = _decode(data)
        elif mime == "text/html" and not html:
            html = _decode(data)
    text = plain or re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:BODY_CHAR_LIMIT]


def _attachments(svc, msg_id: str, payload: dict) -> list[dict[str, Any]]:
    """Haalt PDF- en tekstbijlagen op van notulen-kandidaten."""
    out: list[dict[str, Any]] = []
    for part in _walk(payload):
        if len(out) >= MAX_ATTACHMENTS_PER_MAIL:
            break
        filename = part.get("filename") or ""
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        att_id = body.get("attachmentId")
        if not filename or not att_id:
            continue
        if mime not in ("application/pdf", "text/plain", "text/markdown"):
            continue
        if body.get("size", 0) > MAX_ATTACHMENT_BYTES:
            continue
        blob = (
            svc.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=att_id)
            .execute()
        )
        raw = base64.urlsafe_b64decode(blob["data"])
        out.append(
            {
                "filename": filename,
                "media_type": mime,
                "data_b64": base64.standard_b64encode(raw).decode(),
            }
        )
    return out


def search(query: str, limit: int = 6) -> list[dict]:
    """Zoekt in de HELE mailbox (Gmail-zoeksyntaxis) — voor opdrachten als
    'zoek het opleverrapport'. Geeft metadata + bijlagenamen terug, geen bodies."""
    svc = gmail_service()
    res = svc.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    hits = []
    for ref in res.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        payload = msg.get("payload", {})
        attachments = [
            part.get("filename")
            for part in _walk(payload)
            if part.get("filename") and (part.get("body") or {}).get("attachmentId")
        ]
        hits.append(
            {
                "message_id": ref["id"],
                "from": _header(payload, "From"),
                "to": _header(payload, "To"),
                "date": _header(payload, "Date"),
                "subject": _header(payload, "Subject"),
                "snippet": (msg.get("snippet") or "")[:200],
                "attachments": attachments,
            }
        )
    return hits


def collect() -> tuple[list[dict], dict[str, list[dict]]]:
    """Geeft (signalen, documenten-per-mail) terug."""
    svc = gmail_service()
    after = datetime.now(timezone.utc) - timedelta(hours=config.LOOKBACK_HOURS)
    query = f"in:inbox -category:promotions -category:social after:{int(after.timestamp())}"

    listed = (
        svc.users()
        .messages()
        .list(userId="me", q=query, maxResults=config.MAX_EMAILS)
        .execute()
    )

    signals: list[dict] = []
    documents: dict[str, list[dict]] = {}

    for ref in listed.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        payload = msg.get("payload", {})
        subject = _header(payload, "Subject") or "(geen onderwerp)"
        sender = _header(payload, "From")
        date_hdr = _header(payload, "Date")
        body = _body_text(payload)

        try:
            occurred = parsedate_to_datetime(date_hdr).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            occurred = datetime.now(timezone.utc).isoformat()

        looks_like_minutes = bool(MINUTES_HINTS.search(f"{subject}\n{body[:2000]}"))
        if looks_like_minutes:
            try:
                docs = _attachments(svc, ref["id"], payload)
            except Exception as exc:  # bijlage mag de hele run niet slopen
                docs = []
                print(f"  ! bijlage van {ref['id']} overgeslagen: {exc}")
            if docs:
                documents[ref["id"]] = docs

        signals.append(
            {
                "source": "gmail",
                "external_id": ref["id"],
                "kind": "minutes" if looks_like_minutes else "email",
                "title": subject,
                "summary": (msg.get("snippet") or "")[:500],
                "occurred_at": occurred,
                "payload": {
                    "from": sender,
                    "to": _header(payload, "To"),
                    "thread_id": msg.get("threadId"),
                    "labels": msg.get("labelIds", []),
                    "body": body,
                    "has_documents": ref["id"] in documents,
                    "url": f"https://mail.google.com/mail/u/0/#inbox/{msg.get('threadId')}",
                },
            }
        )

    return signals, documents
