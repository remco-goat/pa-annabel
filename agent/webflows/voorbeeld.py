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

    page.goto(url, wait_until="networkidle", timeout=60_000)
    titel = page.title()
    tekst = " ".join(page.inner_text("body").split())[:500]

    delen = [f"Pagina: {titel or url}"]
    if vraag:
        delen.append(f"Vraag: {vraag}")
    delen.append(f"Zichtbare tekst: {tekst}")
    return " | ".join(delen)


FLOWS["pagina_check"] = pagina_check
