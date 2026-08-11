"""Mailbox-beheer: op gelezen zetten, archiveren, naar de prullenbak.

Grens: de prullenbak is het eindstation (30 dagen terug te halen).
Definitief wissen kan en doet Annabel niet — dat staat de Gmail-scope
(gmail.modify) ook niet toe.
"""
from __future__ import annotations

from ..google_auth import gmail_service

ACTIONS = {
    "mark_read": {"removeLabelIds": ["UNREAD"]},
    "mark_unread": {"addLabelIds": ["UNREAD"]},
    "archive": {"removeLabelIds": ["INBOX", "UNREAD"]},
    "trash": None,  # eigen endpoint
}


def apply_email_action(action: str, message_ids: list[str]) -> str:
    if action not in ACTIONS:
        raise ValueError(f"onbekende mail-actie: {action}")
    if not message_ids:
        raise ValueError("geen message_ids opgegeven")

    svc = gmail_service()
    ok, failed = 0, []
    for mid in message_ids:
        try:
            if action == "trash":
                svc.users().messages().trash(userId="me", id=mid).execute()
            else:
                svc.users().messages().modify(userId="me", id=mid, body=ACTIONS[action]).execute()
            ok += 1
        except Exception as exc:
            failed.append(f"{mid} ({exc})")

    labels = {"mark_read": "op gelezen gezet", "mark_unread": "op ongelezen gezet",
              "archive": "gearchiveerd", "trash": "naar de prullenbak"}
    out = f"{ok} mail(s) {labels[action]}"
    if failed:
        out += f" | mislukt: {'; '.join(failed[:3])}"
    return out
