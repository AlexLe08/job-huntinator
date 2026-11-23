"""Format matches for the sheet, JSON, and terminal."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Job

EASTERN = ZoneInfo("America/New_York")
DESC_CHARS = 500


def _date(dt: datetime | None, fmt: str = "%Y-%m-%d") -> str:
    return dt.astimezone(EASTERN).strftime(fmt) if dt else ""


def tier_label(job: Job) -> str:
    return " · ".join(filter(None, [f"T{job.match_tier}" if job.match_tier else None, job.tier]))


def sheet_row(job: Job, found_at: datetime) -> list[str]:
    return [
        _date(found_at, "%Y-%m-%d %H:%M"),
        job.company,
        job.title,
        job.location,
        job.url,
        _date(job.posted_at),
        job.compensation or "",
        job.source,
        tier_label(job),
        ", ".join(job.flags),
    ]


def match_record(job: Job, found_at: datetime, location_class: str | None) -> dict:
    d = job.to_dict()
    d["description"] = (job.description or "")[:DESC_CHARS]
    d["found_at"] = found_at.isoformat(timespec="seconds")
    d["location_class"] = location_class
    return d


def write_json(records: list[dict], out_dir: str | Path, now: datetime) -> Path:
    """Append to data/matches/YYYY-MM-DD.json (Eastern date), keeping earlier runs from the same day."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{_date(now)}.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    seen = {r["id"] for r in existing}
    existing.extend(r for r in records if r["id"] not in seen)
    path.write_text(json.dumps(existing, indent=1, ensure_ascii=False))
    return path


def table(jobs: list[Job]) -> str:
    if not jobs:
        return "(no new matches)"
    lines = []
    for j in jobs:
        flags = f"  [{', '.join(j.flags)}]" if j.flags else ""
        comp = f"  {j.compensation}" if j.compensation else ""
        lines.append(f"{tier_label(j):<22} {j.company[:22]:<22} {j.title[:48]:<48} {j.location[:32]:<32}{comp}{flags}\n{'':22} {j.url}")
    return "\n".join(lines)
