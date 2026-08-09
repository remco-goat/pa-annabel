"""Schrijft een CONCEPT in Gmail. Verstuurt nooit.

Bewuste grens: de agent mag schrijven, jij drukt op verzenden. Een concept is
terug te draaien, een verstuurde mail niet.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage

from ..google_auth import gmail_service


def send_message(*, to: str, subject: str, body: str, thread_id: str = "") -> str:
    """Verstuurt een mail. Wordt UITSLUITEND aangeroepen wanneer Remco in de
    app expliciet op 'Verstuur' heeft getikt bij dít specifieke concept —
    Annabel zelf zet nooit iets op verzenden."""
    if not to:
        raise ValueError("geen ontvanger — versturen geweigerd")
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = to
    msg["Subject"] = subject or "(geen onderwerp)"

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload: dict = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id

    svc = gmail_service()
    sent = svc.users().messages().send(userId="me", body=payload).execute()
    return f"verstuurd aan {to} (id {sent['id']})"


def create_draft(*, to: str, subject: str, body: str, thread_id: str = "") -> str:
    msg = EmailMessage()
    msg.set_content(body)
    if to:
        msg["To"] = to
    msg["Subject"] = subject or "(geen onderwerp)"

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload: dict = {"message": {"raw": raw}}
    if thread_id:
        payload["message"]["threadId"] = thread_id

    svc = gmail_service()
    draft = svc.users().drafts().create(userId="me", body=payload).execute()
    return f"concept aangemaakt: https://mail.google.com/mail/u/0/#drafts/{draft['id']}"
