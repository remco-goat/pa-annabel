"""Centrale configuratie. Alles komt uit .env — geen secrets in code."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Amsterdam")


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Ontbrekende env-variabele: {name} (zie .env.example)")
    return value


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# --- Supabase -------------------------------------------------------------
SUPABASE_URL = _require("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_KEY = _require("SUPABASE_SERVICE_KEY")

# --- Google (Gmail + Calendar) -------------------------------------------
GOOGLE_CREDENTIALS_FILE = ROOT / os.environ.get("GOOGLE_CREDENTIALS_FILE", ".secrets/google_client.json")
GOOGLE_TOKEN_FILE = ROOT / os.environ.get("GOOGLE_TOKEN_FILE", ".secrets/google_token.json")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# --- To-do ----------------------------------------------------------------
# TODO_PROVIDER: "todoist" | "microsoft" | "none"
TODO_PROVIDER = os.environ.get("TODO_PROVIDER", "none").lower()
TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN", "")

# --- Claude ---------------------------------------------------------------
MODEL = os.environ.get("ASSISTANT_MODEL", "claude-opus-5")
EFFORT = os.environ.get("ASSISTANT_EFFORT", "medium")  # low | medium | high | xhigh | max

# --- Gedrag ---------------------------------------------------------------
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "36"))
MAX_EMAILS = int(os.environ.get("MAX_EMAILS", "60"))
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")
