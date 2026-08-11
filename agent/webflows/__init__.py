"""Vooraf gedefinieerde Playwright-flows voor web-acties (kind 'web_action').

Elke flow is een functie ``def flow(page, params: dict) -> str`` (Playwright
sync API); de returnwaarde is de resultaattekst die in het voorstel komt.
Flows registreren zichzelf in ``FLOWS`` — nieuwe flow = nieuw bestand in dit
pakket dat aan het eind van dit ``__init__`` geïmporteerd wordt.

LET OP: playwright staat bewust NIET in requirements.txt. Alleen de aparte
web-workflow (.github/workflows/annabel-web.yml) installeert het, zodat de
gewone tick licht blijft. Daarom gebeurt de playwright-import LAZY binnen
``run_flow`` en nooit op moduleniveau.
"""
from __future__ import annotations

from typing import Callable

FLOWS: dict[str, Callable] = {}


class FlowError(Exception):
    """Een flow die faalde, mét (indien gelukt) een screenshot van de
    pagina waarop het misging — zodat het bewijs ook bij falen in de app komt."""

    def __init__(self, message: str, screenshot: bytes | None = None):
        super().__init__(message)
        self.screenshot = screenshot


def run_flow(name: str, params: dict) -> tuple[str, bytes]:
    """Draait de flow ``name`` headless en geeft (resultaattekst, png) terug.

    De screenshot is full-page en wordt óók gemaakt als de flow een exception
    gooit — dan is het de foutpagina, verpakt in een FlowError.
    """
    flow = FLOWS.get(name)
    if flow is None:
        raise FlowError(f"onbekende webflow: {name!r} (beschikbaar: {sorted(FLOWS)})")

    # Lazy: playwright is alleen in de web-workflow geïnstalleerd.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            try:
                result = flow(page, params)
            except Exception as exc:
                shot = _screenshot(page)
                raise FlowError(f"{type(exc).__name__}: {exc}", screenshot=shot) from exc
            shot = _screenshot(page)
            if shot is None:
                raise FlowError(f"flow {name!r} slaagde, maar screenshot maken mislukte")
            return result, shot
        finally:
            browser.close()


def _screenshot(page) -> bytes | None:
    """Full-page screenshot; None als zelfs dat niet meer lukt (pagina dood)."""
    try:
        return page.screenshot(full_page=True, type="png")
    except Exception:
        return None


# Flows registreren zichzelf bij import — onderaan, zodat FLOWS al bestaat.
from . import voorbeeld  # noqa: E402,F401
