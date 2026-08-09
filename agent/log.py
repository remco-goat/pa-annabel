"""Logging voor alle runners.

Elke runner logt naar logs/<naam>.log (roterend, max ~2MB x 5 bestanden) én
naar de console. In de bestanden staan timestamps en volledige tracebacks;
de console blijft leesbaar kort. Cron hoeft dus niets meer te redirecten.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from . import config


def setup(name: str) -> logging.Logger:
    logdir = config.ROOT / "logs"
    logdir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        logdir / f"{name}.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    # In CI (GitHub Actions) zijn de logs van een publieke repo publiek —
    # daar horen geen mailonderwerpen of brief-teksten in. Alleen problemen.
    if os.environ.get("CI"):
        console.setLevel(logging.WARNING)
    root.addHandler(console)

    # Bibliotheken die op INFO elke HTTP-call loggen — alleen echte problemen.
    for noisy in ("httpx", "httpcore", "googleapiclient", "google", "urllib3", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(name)
