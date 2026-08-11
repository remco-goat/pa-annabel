"""Screenshots als bewijs naar Supabase Storage (bucket 'bewijs', privé).

Zelfde stijl als agent/db.py: dunne httpx-laag met de service_role key,
bewust geen supabase-py. De app toont het bewijs via een signed URL die
zeven dagen geldig is — de bucket zelf blijft dicht.
"""
from __future__ import annotations

import httpx

from .. import config

BUCKET = "bewijs"
SIGN_EXPIRES = 604_800  # 7 dagen, in seconden

_HEADERS = {
    "apikey": config.SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
}

_client = httpx.Client(
    base_url=f"{config.SUPABASE_URL}/storage/v1",
    headers=_HEADERS,
    timeout=60.0,
)


def _raise(resp: httpx.Response) -> None:
    if resp.is_error:
        raise RuntimeError(
            f"Supabase Storage {resp.status_code} op {resp.request.url}: {resp.text[:500]}"
        )


def _ensure_bucket() -> None:
    """Maakt de bucket aan als hij nog niet bestaat (idempotent)."""
    resp = _client.post(
        "/bucket",
        json={"id": BUCKET, "name": BUCKET, "public": False},
        headers={"Content-Type": "application/json"},
    )
    if resp.is_error and "already exists" not in resp.text.lower() and resp.status_code != 409:
        _raise(resp)


def upload_screenshot(png: bytes, name: str) -> str:
    """Uploadt een png naar de bewijs-bucket en geeft een signed URL terug."""
    upload = lambda: _client.post(  # noqa: E731 — twee identieke pogingen
        f"/object/{BUCKET}/{name}",
        content=png,
        headers={"Content-Type": "image/png", "x-upsert": "true"},
    )

    resp = upload()
    if resp.is_error:
        # Meest waarschijnlijke oorzaak: bucket bestaat nog niet — aanmaken
        # en één keer opnieuw proberen.
        _ensure_bucket()
        resp = upload()
    _raise(resp)

    resp = _client.post(
        f"/object/sign/{BUCKET}/{name}",
        json={"expiresIn": SIGN_EXPIRES},
        headers={"Content-Type": "application/json"},
    )
    _raise(resp)
    signed_path = resp.json()["signedURL"]
    return f"{config.SUPABASE_URL}/storage/v1{signed_path}"
