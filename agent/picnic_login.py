"""Eenmalige Picnic-login — bewust interactief.

    .venv/bin/python -m agent.picnic_login

Vraagt e-mailadres + wachtwoord (blijft in dit proces, wordt nergens opgeslagen)
en doorloopt daarna Picnic's sms-verificatie. Alleen de definitieve sessiesleutel
wordt bewaard in .secrets/picnic_token — zelfde patroon als het Google-token.
"""
from __future__ import annotations

import getpass

from python_picnic_api2 import PicnicAPI

from . import config

TOKEN_FILE = config.ROOT / ".secrets" / "picnic_token"


def _needs_2fa(api: PicnicAPI) -> bool:
    out = api.get_user()
    return isinstance(out, dict) and (out.get("error") or {}).get("code") == "TWO_FACTOR_AUTHENTICATION_REQUIRED"


def _save(api: PicnicAPI) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(api.session.auth_token)
    TOKEN_FILE.chmod(0o600)


def main() -> int:
    email = input("Picnic e-mailadres: ").strip()
    password = getpass.getpass("Picnic wachtwoord (onzichtbaar): ")
    api = PicnicAPI(username=email, password=password)

    if _needs_2fa(api):
        print("Picnic wil een sms-verificatie — code wordt nu verstuurd...")
        resp = api.session.post(api._base_url + "/user/2fa/generate", json={"channel": "SMS"})
        if resp.status_code >= 400:
            print(f"Code aanvragen mislukt (HTTP {resp.status_code}): {resp.text[:200]}")
            return 1
        code = input("Sms-code: ").strip()
        resp = api.session.post(api._base_url + "/user/2fa/verify", json={"otp": code})
        if resp.status_code >= 400:
            print(f"Verificatie mislukt (HTTP {resp.status_code}): {resp.text[:200]}")
            return 1

    user = api.get_user()
    if isinstance(user, dict) and user.get("error"):
        print("Nog steeds geen volledige sessie:", user["error"])
        return 1

    _save(api)
    naam = ((user.get("firstname") or "") + " " + (user.get("lastname") or "")).strip()
    print(f"Ingelogd als {naam or email}. Sleutel opgeslagen in {TOKEN_FILE}")
    print("Zeg tegen Claude dat de login gelukt is; die zet de sleutel dan ook in GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
