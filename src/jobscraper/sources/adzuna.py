"""Adzuna official job-search API (free key). Broad US coverage similar to the big boards."""
from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import urlencode

from ..http import PoliteClient
from ..models import Job
from ..text import fmt_money, html_to_text, parse_iso

FEED = "adzuna"


class MissingCredentials(RuntimeError):
    pass


def fetch(client: PoliteClient, settings: dict, now: datetime) -> list[Job]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise MissingCredentials("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    country = settings.get("country", "us")
    seen: dict[str, Job] = {}
    wheres = [None, *(settings.get("where") or [])]
    for what in settings.get("queries") or []:
        for where in wheres:
            params = {
                "app_id": app_id, "app_key": app_key, "what": what, "max_days_old": settings.get("max_days_old", 2),
                "results_per_page": settings.get("results_per_page", 50), "sort_by": "date",
                "content-type": "application/json",
            }
            if where:
                params["where"] = where
            data = client.get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?{urlencode(params)}")
            for raw in data.get("results", []):
                j = normalize(raw)
                seen.setdefault(j.id, j)
    return list(seen.values())


def normalize(raw: dict) -> Job:
    lo, hi = raw.get("salary_min"), raw.get("salary_max")
    comp = None
    if lo or hi:
        comp = f"{fmt_money(lo)}–{fmt_money(hi)}" if lo and hi and lo != hi else fmt_money(lo or hi)
        if raw.get("salary_is_predicted") in ("1", 1, True):
            comp += " (est.)"
    loc = (raw.get("location") or {}).get("display_name") or ""
    return Job(
        id=f"adzuna:{raw['id']}", source=FEED, company=(raw.get("company") or {}).get("display_name") or "",
        title=html_to_text(raw.get("title")), location=loc, url=raw.get("redirect_url") or "",
        remote=True if "remote" in (raw.get("title", "") + loc).lower() else None, country="US",
        posted_at=parse_iso(raw.get("created")), compensation=comp,
        department=(raw.get("category") or {}).get("label"), description=html_to_text(raw.get("description")),
        tier="adzuna",
    )
