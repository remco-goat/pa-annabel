"""Eenmalige Picnic-login — bewust interactief.

    .venv/bin/python -m agent.picnic_login

Vraagt je e-mailadres en wachtwoord (wachtwoord blijft in dit proces, wordt
nergens opgeslagen of getoond) en bewaart alléén de sessiesleutel in
.secrets/picnic_token. De agent gebruikt daarna uitsluitend die sleutel —
zelfde patroon als het Google-token.
"""
from __future__ import annotations

import getpass

from python_picnic_api2 import PicnicAPI

from . import config

TOKEN_FILE = config.ROOT / ".secrets" / "picnic_token"


def main() -> int:
    email = input("Picnic e-mailadres: ").strip()
    password = getpass.getpass("Picnic wachtwoord (onzichtbaar): ")
    api = PicnicAPI(username=email, password=password)

    user = api.get_user()
    token = api.session.auth_token
    if not token:
        print("Geen sessiesleutel ontvangen — inloggen mislukt?")
        return 1

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    naam = (user.get("firstname") or "") + " " + (user.get("lastname") or "")
    print(f"Ingelogd als {naam.strip() or email}. Sleutel opgeslagen in {TOKEN_FILE}")
    print("Zeg tegen Claude dat de login gelukt is; die zet de sleutel dan ook in GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
