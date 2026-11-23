"""Registry of aggregator feeds. Each entry: fetch(client, settings, now, cfg) -> list[Job]."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml

from . import adzuna, gmail_alerts, hn, remote_boards

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"

AGGREGATORS: dict[str, Callable] = {
    "hn": lambda client, settings, now, cfg: hn.fetch(client, settings, now, cfg),
    "remotive": lambda client, settings, now, cfg: remote_boards.fetch_remotive(client, settings, now),
    "remoteok": lambda client, settings, now, cfg: remote_boards.fetch_remoteok(client, settings, now),
    "himalayas": lambda client, settings, now, cfg: remote_boards.fetch_himalayas(client, settings, now),
    "weworkremotely": lambda client, settings, now, cfg: remote_boards.fetch_wwr(client, settings, now),
    "adzuna": lambda client, settings, now, cfg: adzuna.fetch(client, settings, now),
    "gmail_alerts": lambda client, settings, now, cfg: gmail_alerts.fetch(client, settings, now),
}


class FeedSkipped(Exception):
    """Raised for a feed that can't run (e.g. missing secrets). Logged as a warning, not a failure."""


def register(name: str, fn: Callable) -> None:
    AGGREGATORS[name] = fn


def load_settings(path: str | Path | None = None) -> dict[str, dict]:
    p = Path(path or DEFAULT_PATH)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def enabled_feeds(settings: dict[str, dict], only: list[str] | None = None) -> dict[str, dict]:
    out = {}
    for name, conf in settings.items():
        conf = conf or {}
        if only is not None and name not in only:
            continue
        if not conf.get("enabled", True) and only is None:
            continue
        if name in AGGREGATORS:
            out[name] = conf
    return out
