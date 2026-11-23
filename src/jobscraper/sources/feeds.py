"""Shared bits for aggregator feeds (sources that aren't one-company job boards)."""

from __future__ import annotations

import re

ATS_LINK = re.compile(
    r"https?://(?:boards|job-boards)\.greenhouse\.io/|https?://jobs\.lever\.co/|https?://jobs\.ashbyhq\.com/|"
    r"https?://apply\.workable\.com/|https?://[a-z0-9-]+\.recruitee\.com/|https?://jobs\.smartrecruiters\.com/|"
    r"https?://[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/|[?&]gh_jid=",
    re.I,
)


def best_link(links: list[str], fallback: str) -> str:
    """Prefer an ATS posting link, then any non-social link, else the fallback (e.g. the HN comment)."""
    for u in links:
        if ATS_LINK.search(u):
            return u
    for u in links:
        if not re.search(r"(news\.ycombinator\.com|twitter\.com|x\.com|linkedin\.com|mailto:)", u, re.I):
            return u
    return fallback
