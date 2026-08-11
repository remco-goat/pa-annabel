"""Gedeelde Google OAuth voor Gmail en Calendar.

Eenmalig `python -m agent.google_auth` draaien: dat opent je browser, jij geeft
toestemming, en het token belandt in .secrets/google_token.json. Daarna ververst
de agent het token zelf en hoeft er nooit meer een browser aan te pas te komen.

Werkt met beide OAuth-clienttypes:
  Desktop app  — aanbevolen; loopback op een willekeurige poort, niets te
                 registreren in de Google Cloud Console.
  Web app      — moet op een vaste poort draaien én die redirect-URI moet
                 exact geregistreerd staan, anders krijg je redirect_uri_mismatch.
"""
from __future__ import annotations

import json
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config

WEB_PORT = 8080
WEB_REDIRECT = f"http://localhost:{WEB_PORT}/"


def _client_type() -> str:
    data = json.loads(config.GOOGLE_CREDENTIALS_FILE.read_text())
    return "web" if "web" in data else "installed"


def _check_web_client() -> None:
    data = json.loads(config.GOOGLE_CREDENTIALS_FILE.read_text())
    uris = data["web"].get("redirect_uris") or []
    if WEB_REDIRECT not in uris:
        raise RuntimeError(
            "Dit is een OAuth-client van het type 'Web application' zonder de juiste "
            f"redirect-URI.\n\nKies één van beide:\n\n"
            f"  A. Maak een client van het type 'Desktop app' aan (aanbevolen, niets te "
            f"configureren):\n"
            f"     https://console.cloud.google.com/apis/credentials?project="
            f"{data['web'].get('project_id', '')}\n"
            f"     Download het JSON-bestand naar {config.GOOGLE_CREDENTIALS_FILE}\n\n"
            f"  B. Voeg bij deze web-client onder 'Authorized redirect URIs' exact toe:\n"
            f"     {WEB_REDIRECT}\n"
            f"     Download daarna het bijgewerkte JSON-bestand opnieuw."
        )


def credentials() -> Credentials:
    creds: Credentials | None = None
    missing_scopes: set[str] = set()
    if config.GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(config.GOOGLE_TOKEN_FILE), config.GOOGLE_SCOPES
        )
        # from_authorized_user_file zet de GEVRAAGDE scopes op het object;
        # wat er werkelijk verleend is staat alleen in het bestand zelf.
        granted = json.loads(config.GOOGLE_TOKEN_FILE.read_text()).get("scopes") or []
        missing_scopes = set(config.GOOGLE_SCOPES) - set(granted)

    # Een geldig token met te wéinig rechten (bijv. van vóór de Drive-scope)
    # telt niet — refreshen met de volle scope-lijst geeft dan invalid_scope,
    # dus er moet opnieuw toestemming gevraagd worden.
    if creds and missing_scopes:
        creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if missing_scopes and not sys.stdin.isatty():
            raise RuntimeError(
                f"Google-token mist scope(s) {sorted(missing_scopes)} en her-consent "
                "kan alleen in een browser. Draai lokaal `python -m agent.google_auth` "
                "(vink op het toestemmingsscherm ALLE onderdelen aan, ook Drive) en "
                "ververs daarna het secret: gh secret set GOOGLE_TOKEN_JSON "
                "-R remco-goat/pa-annabel < .secrets/google_token.json"
            )
        if not config.GOOGLE_CREDENTIALS_FILE.exists():
            raise RuntimeError(
                f"Geen Google client secret gevonden op {config.GOOGLE_CREDENTIALS_FILE}. "
                "Zie README stap 3."
            )
        is_web = _client_type() == "web"
        if is_web:
            _check_web_client()

        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.GOOGLE_CREDENTIALS_FILE), config.GOOGLE_SCOPES
        )
        # Desktop-clients mogen elke loopback-poort gebruiken; web-clients moeten
        # exact overeenkomen met wat er geregistreerd staat.
        creds = flow.run_local_server(
            port=WEB_PORT if is_web else 0,
            prompt="consent",          # forceert een refresh_token, ook bij hergebruik
            access_type="offline",
        )
        # Google laat je op het consent-scherm onderdelen uitvinken; een half
        # token opslaan geeft later alleen maar invalid_scope in de cloud.
        not_granted = set(config.GOOGLE_SCOPES) - set(creds.scopes or [])
        if not_granted:
            raise RuntimeError(
                f"Toestemming onvolledig — niet verleend: {sorted(not_granted)}. "
                "Draai opnieuw en vink op het toestemmingsscherm ALLE onderdelen aan "
                "(ook 'Alle Google Drive-bestanden bekijken en downloaden')."
            )

    config.GOOGLE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.GOOGLE_TOKEN_FILE.write_text(creds.to_json())
    config.GOOGLE_TOKEN_FILE.chmod(0o600)
    return creds


def drive_service():
    return build("drive", "v3", credentials=credentials(), cache_discovery=False)


def gmail_service():
    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)


def calendar_service():
    return build("calendar", "v3", credentials=credentials(), cache_discovery=False)


if __name__ == "__main__":
    creds = credentials()
    print(f"Google-token OK ({_client_type()}-client), opgeslagen in {config.GOOGLE_TOKEN_FILE}")
    if not creds.refresh_token:
        print("LET OP: geen refresh_token ontvangen — over een uur moet je opnieuw inloggen.")
