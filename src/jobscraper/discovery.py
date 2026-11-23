"""Spot employer ATS boards linked from aggregator posts that aren't in companies.yaml yet.
Suggestions accumulate in state/suggestions.json and render to data/companies.suggested.md. Nothing is auto-added."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .companies import Company
from .models import Job

PATTERNS = [
    (
        "greenhouse",
        re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I),
    ),
    ("lever", re.compile(r"https?://jobs\.lever\.co/([a-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([a-z0-9_.%-]+)", re.I)),
    ("workable", re.compile(r"https?://apply\.workable\.com/(?!j/|api/)([a-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("smartrecruiters", re.compile(r"https?://jobs\.smartrecruiters\.com/([a-z0-9_-]+)", re.I)),
]
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
IGNORE_TOKENS = {"embed", "api", "v1", "jobs", "j", "o"}


def find_boards(job: Job) -> set[tuple[str, str]]:
    blobs = [job.url, *URL_RE.findall(job.description or "")]
    found = set()
    for blob in blobs:
        for ats, rx in PATTERNS:
            for m in rx.finditer(blob or ""):
                tok = m.group(1).strip("/").lower()
                if tok and tok not in IGNORE_TOKENS:
                    found.add((ats, tok))
    return found


def update_suggestions(jobs: list[Job], companies: list[Company], path: str | Path, now: datetime) -> dict:
    p = Path(path)
    data = json.loads(p.read_text()) if p.exists() else {}
    known = {(c.ats, c.token.lower()) for c in companies}
    for key in [k for k, r in data.items() if (r["ats"], r["token"]) in known]:
        del data[key]  # added to companies.yaml since: stop suggesting it
    for job in jobs:
        for ats, tok in find_boards(job):
            if (ats, tok) in known:
                continue
            key = f"{ats}:{tok}"
            rec = data.setdefault(
                key,
                {
                    "ats": ats,
                    "token": tok,
                    "company": job.company,
                    "count": 0,
                    "first_seen": now.isoformat(timespec="seconds"),
                    "example": job.url,
                },
            )
            rec["count"] += 1
            rec["last_seen"] = now.isoformat(timespec="seconds")
            rec["last_title"] = job.title
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, sort_keys=True))
    return data


def render_markdown(data: dict, path: str | Path) -> None:
    rows = sorted(data.values(), key=lambda r: (-r["count"], r["company"].lower()))
    lines = [
        "# Suggested companies (seen on aggregator posts, not in companies.yaml)",
        "",
        "Copy the ones you want into config/companies.yaml, then run `python -m jobscraper validate-companies`.",
        "",
    ]
    for r in rows:
        lines.append(
            f"- {r['company'] or '?'}: `{{company: {r['company'] or r['token']}, ats: {r['ats']}, "
            f"token: {r['token']}, tier: discovered}}`  -- seen {r['count']}x, e.g. {r.get('last_title', '')}"
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")


def summary_markdown(data: dict, now: datetime, limit: int = 30) -> str:
    """Short markdown for the GitHub Actions job summary. Company names and board tokens only (no job titles):
    the repo is public, so its run pages are too."""
    rows = sorted(data.values(), key=lambda r: (-r["count"], (r["company"] or "").lower()))
    if not rows:
        return "### Company suggestions\n\nNo unlisted ATS boards seen yet.\n"
    run_stamp = now.isoformat(timespec="seconds")
    lines = [
        "### Company suggestions",
        "",
        f"{len(rows)} ATS boards linked from aggregator posts are not in `config/companies.yaml`. "
        'Paste the ones you want, then run `python -m jobscraper validate-companies --only "<name>"`.',
        "",
        "| Seen | New this run | YAML line |",
        "|---:|:---:|---|",
    ]
    for r in rows[:limit]:
        name = (r["company"] or r["token"]).replace("|", "/")
        new = "yes" if r.get("first_seen") == run_stamp else ""
        lines.append(
            f"| {r['count']} | {new} | `- {{company: {name}, ats: {r['ats']}, token: {r['token']}, tier: discovered}}` |"
        )
    if len(rows) > limit:
        lines.append(f"\n_{len(rows) - limit} more with fewer sightings not shown._")
    return "\n".join(lines) + "\n"
