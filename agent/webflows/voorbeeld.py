"""Credential-vrije demoflow: bekijk een pagina en vertel wat erop staat.

Bedoeld om de hele keten (dispatch -> Actions -> Playwright -> screenshot ->
Supabase Storage -> app) te bewijzen zonder ergens in te loggen.
"""
from __future__ import annotations

from . import FLOWS


def pagina_check(page, params: dict) -> str:
    """params: {"url": str, "vraag": str} — navigeer, lees titel + eerste tekst.

    De 'vraag' wordt niet beantwoord door een model; hij komt terug in het
    resultaat zodat Remco in de app ziet wáárvoor de pagina bekeken is. Het
    antwoord zelf is de screenshot + de tekst-samenvatting hieronder.
    """
    url = (params or {}).get("url", "").strip()
    if not url:
        raise ValueError("pagina_check heeft params.url nodig")
    vraag = (params or {}).get("vraag", "").strip()

    # Niet op networkidle wachten: zware sites (Google Maps, kaarten, chats)
    # worden nooit netwerk-stil en lopen dan tegen de timeout. DOM + korte
    # rustpauze is genoeg om te lezen en te fotograferen.
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        page.wait_for_timeout(2_500)

    # Cookiemuur: privacyvriendelijk wegklikken (weigeren, nooit accepteren).
    import re as _re
    try:
        knop = page.get_by_role(
            "button", name=_re.compile(r"alles afwijzen|afwijzen|weiger|reject all|decline", _re.I)
        ).first
        if knop.is_visible(timeout=1_500):
            knop.click(timeout=3_000)
            page.wait_for_timeout(1_000)
    except Exception:
        pass  # geen cookiemuur, of niet klikbaar — dan staat hij op de screenshot

    titel = page.title()
    tekst = " ".join(page.inner_text("body").split())[:500]

    # Een nette 404 is voor Playwright een geslaagde navigatie; voor Remco is
    # het een mislukte check. Luid falen, dan komt de kaart als 'mislukt' terug.
    if _re.search(r"niet gevonden|not found|\b404\b", titel, _re.I):
        raise ValueError(f"pagina bestaat niet (titel: {titel!r}) — verkeerde url? {url}")

    delen = [f"Pagina: {titel or url}"]
    if vraag:
        delen.append(f"Vraag: {vraag}")
    delen.append(f"Zichtbare tekst: {tekst}")
    return " | ".join(delen)


FLOWS["pagina_check"] = pagina_check
