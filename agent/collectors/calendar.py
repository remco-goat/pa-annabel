"""Agenda-collector: wat staat er de komende twee dagen op de rol."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..google_auth import calendar_service

HORIZON_DAYS = 2


def collect() -> list[dict]:
    svc = calendar_service()
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=HORIZON_DAYS)

    events = (
        svc.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=horizon.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    signals: list[dict] = []
    for ev in events.get("items", []):
        start = ev.get("start", {})
        when = start.get("dateTime") or start.get("date")
        signals.append(
            {
                "source": "calendar",
                "external_id": ev["id"],
                "kind": "event",
                "title": ev.get("summary") or "(geen titel)",
                "summary": (ev.get("description") or "")[:500],
                "occurred_at": when,
                "payload": {
                    "start": when,
                    "end": (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date"),
                    "location": ev.get("location"),
                    "attendees": [a.get("email") for a in ev.get("attendees", []) if a.get("email")],
                    "all_day": "date" in start,
                    "url": ev.get("htmlLink"),
                },
            }
        )
    return signals
