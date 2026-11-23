"""Seen-jobs state: first-seen tracking, freshness, flood guard, and "already reported" bookkeeping.

File layout (state/seen.json):
{
  "version": 1,
  "feeds": {"greenhouse:vercel": {"first_polled": "...", "last_polled": "..."}},
  "jobs": {
    "<job id>": {"first_seen": "...", "last_seen": "...", "posted_at": "...|null",
                 "baseline": bool, "reported": "...|null", "company": "...", "title": "...", "url": "..."}
  }
}

* A job is a *candidate* if it was never reported and is fresh.
* Fresh = first seen within `freshness_hours`. Exception (flood guard): jobs recorded the first time a feed
  is ever polled are "baseline" -- their own posted_at must be within the window instead, so the very first
  run (or a run after the cache is lost) doesn't report every open role as new.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Job

PRUNE_AFTER_DAYS = 60


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


@dataclass
class State:
    feeds: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: Path | None = None
    loaded_from_disk: bool = False

    # ------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str | Path) -> "State":
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            # Corrupt state: start over; the flood guard keeps this from spamming.
            return cls(path=p)
        return cls(feeds=data.get("feeds", {}), jobs=data.get("jobs", {}), path=p, loaded_from_disk=True)

    def save(self, path: str | Path | None = None) -> None:
        p = Path(path or self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "feeds": self.feeds, "jobs": self.jobs}
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".seen.", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        os.replace(tmp, p)

    # ------------------------------------------------------------ core
    def observe(self, feed: str, jobs: list[Job], now: datetime) -> None:
        """Record a successful poll of `feed` (e.g. "greenhouse:vercel") that returned `jobs`."""
        is_new_feed = feed not in self.feeds
        meta = self.feeds.setdefault(feed, {"first_polled": _iso(now)})
        meta["last_polled"] = _iso(now)
        for job in jobs:
            rec = self.jobs.get(job.id)
            if rec is None:
                self.jobs[job.id] = {
                    "first_seen": _iso(now),
                    "last_seen": _iso(now),
                    "posted_at": _iso(job.posted_at),
                    "baseline": is_new_feed,
                    "reported": None,
                    "company": job.company,
                    "title": job.title,
                    "url": job.url,
                }
            else:
                rec["last_seen"] = _iso(now)

    def is_fresh(self, job_id: str, now: datetime, hours: float) -> bool:
        rec = self.jobs.get(job_id)
        if rec is None:
            return False
        window = timedelta(hours=hours)
        if rec.get("baseline"):
            posted = _dt(rec.get("posted_at"))
            return posted is not None and now - posted <= window
        first = _dt(rec["first_seen"])
        return first is not None and now - first <= window

    def is_candidate(self, job_id: str, now: datetime, hours: float) -> bool:
        rec = self.jobs.get(job_id)
        return bool(rec) and not rec.get("reported") and self.is_fresh(job_id, now, hours)

    def first_seen(self, job_id: str) -> datetime | None:
        rec = self.jobs.get(job_id)
        return _dt(rec["first_seen"]) if rec else None

    def mark_reported(self, job_ids: list[str], now: datetime) -> None:
        for jid in job_ids:
            if jid in self.jobs:
                self.jobs[jid]["reported"] = _iso(now)

    def prune(self, now: datetime, days: int = PRUNE_AFTER_DAYS) -> int:
        cutoff = now - timedelta(days=days)
        stale = [k for k, v in self.jobs.items() if (_dt(v.get("last_seen")) or now) < cutoff]
        for k in stale:
            del self.jobs[k]
        return len(stale)
