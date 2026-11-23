"""The scrape pipeline: fetch -> record in state -> fresh candidates -> filters -> tracker dedupe -> output."""
from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .companies import Company
from .dedupe import TrackerIndex
from typing import Callable

from .filters import FilterConfig, classify_location, classify_title, evaluate
from .http import PoliteClient
from .models import Job
from .sources.base import COMPANY_SOURCES, get_company_source
from .state import State

log = logging.getLogger(__name__)


@dataclass
class FeedResult:
    feed: str  # "greenhouse:vercel"
    company: Company
    jobs: list[Job] = field(default_factory=list)
    error: str | None = None


@dataclass
class Match:
    job: Job
    location_class: str | None


@dataclass
class RunResult:
    feeds: list[FeedResult]
    matches: list[Match]
    drop_reasons: Counter
    already_tracked: list[tuple[Job, str]]

    @property
    def failed(self) -> list[FeedResult]:
        return [f for f in self.feeds if f.error]


def fetch_company(client: PoliteClient, company: Company) -> FeedResult:
    feed = f"{company.ats}:{company.token}"
    try:
        jobs = get_company_source(company.ats).fetch(client, company)
        return FeedResult(feed, company, jobs)
    except Exception as exc:  # one bad board must never kill the run
        log.warning("fetch failed for %s (%s): %s", company.company, feed, exc)
        return FeedResult(feed, company, error=str(exc))


def fetch_all(companies: list[Company], clients: dict[str, PoliteClient], workers: int = 6) -> list[FeedResult]:
    """Parallel across hosts; each host's client enforces its own polite spacing."""
    supported = [c for c in companies if c.ats in COMPANY_SOURCES]
    for c in companies:
        if c.ats not in COMPANY_SOURCES:
            log.info("skipping %s: ats %s not supported", c.company, c.ats)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda c: fetch_company(clients[c.ats], c), supported))


def fetch_aggregators(feeds: dict[str, dict], now: datetime, cfg: FilterConfig) -> list[FeedResult]:
    from .sources.aggregators import AGGREGATORS, FeedSkipped
    from .sources.adzuna import MissingCredentials
    from .sources.gmail_alerts import MissingCredentials as GmailMissing

    def one(name: str) -> FeedResult | None:
        pseudo = Company(company=name, ats=name, token=name, tier=name)
        client = PoliteClient()
        try:
            return FeedResult(name, pseudo, AGGREGATORS[name](client, feeds[name], now, cfg))
        except (FeedSkipped, MissingCredentials, GmailMissing) as exc:
            log.warning("feed %s skipped: %s", name, exc)
            return None
        except Exception as exc:
            log.warning("feed %s failed: %s", name, exc)
            return FeedResult(name, pseudo, error=str(exc))
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=max(1, len(feeds))) as pool:
        return [r for r in pool.map(one, list(feeds)) if r is not None]


def select(
    feeds: list[FeedResult],
    state: State,
    cfg: FilterConfig,
    now: datetime,
    tracker: TrackerIndex | None = None,
    enricher: Callable[[Job, Company], None] | None = None,
) -> RunResult:
    reasons: Counter = Counter()
    matches: list[Match] = []
    tracked: list[tuple[Job, str]] = []
    seen_ids: set[str] = set()
    # Company boards first: they carry the canonical employer link. Every job they list (fresh or not)
    # goes into `ats_index`, so an aggregator repost of the same role is recognised as a duplicate.
    feeds = sorted(feeds, key=lambda f: f.company.ats not in COMPANY_SOURCES)
    ats_index = TrackerIndex()
    for f in feeds:
        if not f.error and f.company.ats in COMPANY_SOURCES:
            for job in f.jobs:
                ats_index.add(job.company, job.title, job.url)
    kept_index = TrackerIndex()
    for f in feeds:
        if f.error:
            continue
        is_aggregator = f.company.ats not in COMPANY_SOURCES
        state.observe(f.feed, f.jobs, now)
        for job in f.jobs:
            if job.id in seen_ids:
                continue
            seen_ids.add(job.id)
            if not state.is_candidate(job.id, now, cfg.freshness_hours):
                reasons["not-fresh-or-reported"] += 1
                continue
            if enricher and not job.description and _passes_cheap_filters(job, cfg):
                try:
                    enricher(job, f.company)
                except Exception as exc:  # keep the job; red-flag scan just has less text
                    log.warning("enrich failed for %s: %s", job.url, exc)
                    job.flags.append("no-desc")
            v = evaluate(job, cfg)
            if not v.keep:
                reasons[v.reason.split(":")[0] if v.reason.startswith("title-exclude") else v.reason] += 1
                continue
            job.flags = list(dict.fromkeys(job.flags + v.flags))
            if tracker is not None and (why := tracker.match(job, cfg.title_similarity)):
                tracked.append((job, why))
                reasons[f"already-tracked:{why}"] += 1
                continue
            if is_aggregator and (ats_index.match(job, cfg.title_similarity) or kept_index.match(job, cfg.title_similarity)):
                reasons["duplicate-of-other-source"] += 1
                continue
            kept_index.add(job.company, job.title, job.url)
            matches.append(Match(job, v.location_class))
    matches.sort(key=lambda m: (m.job.match_tier or 9, "senior" in m.job.flags, m.job.company.lower()))
    return RunResult(feeds, matches, reasons, tracked)


def _passes_cheap_filters(job: Job, cfg: FilterConfig) -> bool:
    return classify_title(job.title, cfg).keep and \
        classify_location(job.location, job.remote, job.country) in cfg.location_keep


def make_enricher(clients: dict[str, PoliteClient]) -> Callable[[Job, Company], None]:
    def enrich(job: Job, company: Company) -> None:
        if job.source not in COMPANY_SOURCES:
            return
        src = get_company_source(job.source)
        if hasattr(src, "enrich"):
            src.enrich(clients[job.source], job, company)

    return enrich


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_clients() -> dict[str, PoliteClient]:
    return {ats: PoliteClient() for ats in COMPANY_SOURCES}


def default_paths(root: Path) -> dict[str, Path]:
    return {"state": root / "state" / "seen.json", "matches": root / "data" / "matches"}
