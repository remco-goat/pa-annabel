"""Google Drive doorzoeken — voor 'zoek het opleverrapport'-achtige opdrachten.

Alleen-lezen. Delen gebeurt via een concept-mail met het bestand als bijlage
(of een link bij grote/Google-native bestanden); Annabel wijzigt nooit
Drive-rechten.
"""
from __future__ import annotations

import io

from ..google_auth import drive_service

EXPORTS = {
    # Google-native bestanden hebben geen bytes; exporteren naar een gangbaar formaat.
    "application/vnd.google-apps.document": (
        "application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": (
        "application/pdf", ".pdf"),
}
MAX_ATTACH_BYTES = 20 * 1024 * 1024


def search(query: str, limit: int = 6) -> list[dict]:
    svc = drive_service()
    safe = query.replace("\\", " ").replace("'", " ")
    res = svc.files().list(
        q=f"(name contains '{safe}' or fullText contains '{safe}') and trashed = false",
        pageSize=limit,
        fields="files(id,name,mimeType,size,modifiedTime,webViewLink,owners(displayName))",
        orderBy="modifiedTime desc",
    ).execute()
    hits = []
    for f in res.get("files", []):
        hits.append(
            {
                "drive_file_id": f["id"],
                "name": f.get("name"),
                "mime_type": f.get("mimeType"),
                "size": int(f.get("size", 0) or 0),
                "modified": f.get("modifiedTime"),
                "link": f.get("webViewLink"),
                "owner": (f.get("owners") or [{}])[0].get("displayName"),
            }
        )
    return hits


def download(file_id: str) -> tuple[str, str, bytes]:
    """Geeft (bestandsnaam, mimetype, bytes). Google-native bestanden worden
    geëxporteerd; te grote bestanden geven een foutmelding."""
    from googleapiclient.http import MediaIoBaseDownload

    svc = drive_service()
    meta = svc.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    name, mime = meta["name"], meta["mimeType"]

    if mime in EXPORTS:
        export_mime, ext = EXPORTS[mime]
        request = svc.files().export_media(fileId=file_id, mimeType=export_mime)
        if not name.endswith(ext):
            name += ext
        mime = export_mime
    else:
        if int(meta.get("size", 0) or 0) > MAX_ATTACH_BYTES:
            raise ValueError(f"bestand te groot om te mailen ({meta.get('size')} bytes) — deel de link")
        request = svc.files().get_media(fileId=file_id)

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return name, mime, buf.getvalue()
