"""Workday behind Cloudflare: keep partial results on a later 429, and stop hammering after consecutive 429s."""

import contextlib
import logging
from datetime import UTC, datetime, timedelta

import pytest
from conftest import load_fixture

from jobscraper.companies import Company
from jobscraper.filters import FilterConfig
from jobscraper.http import FetchError, PartialFetch
from jobscraper.models import Job
from jobscraper.run import fetch_all, fetch_company, select
from jobscraper.sources import workday
from jobscraper.state import State

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
POSTINGS = load_fixture("workday_redhat.json")["jobPostings"]


def wd(token):
    return Company(
        token.title(), "workday", token, tier="rtp", extra={"host": f"{token}.wd5.myworkdayjobs.com", "site": "jobs"}
    )


class FakeClient:
    """post_json stand-in. `plan(url, body, n)` returns a payload or raises; n counts calls per board URL."""

    def __init__(self, plan):
        self.plan = plan
        self.calls: list[tuple[str, dict]] = []

    def post_json(self, url, body):
        n = sum(1 for u, _ in self.calls if u == url)
        self.calls.append((url, body))
        return self.plan(url, body, n)

    def boards_called(self):
        return {u.split("/")[2].split(".")[0] for u, _ in self.calls}


def blocked(url, body, n):
    raise FetchError(f"giving up on {url}: HTTP 429", 429)


def ok(url, body, n):
    return {"jobPostings": POSTINGS if body["searchText"] == "frontend" else []}


def test_later_429_keeps_jobs_from_earlier_queries():
    def plan(url, body, n):
        if body["searchText"] == "frontend":
            return {"jobPostings": POSTINGS}
        raise FetchError(f"giving up on {url}: HTTP 429", 429)

    with pytest.raises(PartialFetch) as ei:
        workday.fetch(FakeClient(plan), wd("redhat"), NOW)
    assert ei.value.status == 429
    assert len(ei.value.jobs) == len({p["externalPath"] for p in POSTINGS}) > 0


def test_first_request_failure_is_a_plain_failure():
    with pytest.raises(FetchError) as ei:
        workday.fetch(FakeClient(blocked), wd("redhat"), NOW)
    assert not isinstance(ei.value, PartialFetch)


def test_fetch_company_turns_partial_into_feed_with_jobs(caplog):
    def plan(url, body, n):
        if n == 0:
            return {"jobPostings": POSTINGS}
        raise FetchError(f"giving up on {url}: HTTP 429", 429)

    with caplog.at_level(logging.WARNING):
        r = fetch_company(FakeClient(plan), wd("redhat"))
    assert r.error is None and r.partial == "HTTP 429" and r.jobs
    # CI logs are public: no job titles or job links in the warning.
    for job in r.jobs:
        assert job.title not in caplog.text and job.url not in caplog.text
    assert "kept" in caplog.text


@pytest.mark.parametrize(
    ("outcomes", "expect_tripped"),
    [
        ([429, 429, 429], True),
        ([429, 429], False),
        ([429, 429, 200, 429, 429], False),  # a success resets the streak
        ([429, 500, 429, 429], False),  # only 429s count: a 500 is a broken board, not a block
        ([200, 429, 429, 429], True),
    ],
)
def test_breaker_counts_consecutive_first_request_429s(outcomes, expect_tripped):
    def plan(url, body, n):
        board = url.split("/")[2].split(".")[0]
        if board == "next" or outcomes[int(board.removeprefix("b"))] == 200:
            return ok(url, body, n)
        raise FetchError("x", outcomes[int(board.removeprefix("b"))])

    client = FakeClient(plan)
    for i in range(len(outcomes)):
        with contextlib.suppress(FetchError):
            workday.fetch(client, wd(f"b{i}"), NOW)
    try:
        workday.fetch(client, wd("next"), NOW)
        skipped = False
    except workday.WorkdayBlocked:
        skipped = True
    assert skipped == expect_tripped
    assert ("next" in client.boards_called()) != expect_tripped


def test_breaker_skips_remaining_boards_without_requests():
    client = FakeClient(blocked)
    companies = [wd(f"b{i}") for i in range(8)]
    results = fetch_all(companies, {"workday": client}, workers=1)
    assert all(r.error for r in results)
    assert len(client.calls) == workday.BLOCK_THRESHOLD  # boards after the third make no request
    skipped = [r for r in results if "skipped" in r.error]
    assert len(skipped) == 8 - workday.BLOCK_THRESHOLD


def test_breaker_is_per_client():
    first = FakeClient(blocked)
    for i in range(workday.BLOCK_THRESHOLD):
        with pytest.raises(FetchError):
            workday.fetch(first, wd(f"b{i}"), NOW)
    fresh = FakeClient(ok)
    assert workday.fetch(fresh, wd("redhat"), NOW)  # a new run (new client) starts with a clean slate


def test_later_429_does_not_trip_breaker():
    def plan(url, body, n):
        if n == 0:
            return {"jobPostings": POSTINGS}
        raise FetchError("x", 429)

    client = FakeClient(plan)
    for i in range(workday.BLOCK_THRESHOLD + 1):
        with pytest.raises(PartialFetch):
            workday.fetch(client, wd(f"b{i}"), NOW)


def job(i, posted):
    return Job(
        id=f"workday:acme:R{i}",
        source="workday",
        company="Acme",
        title=f"Role {i}",
        location="",
        url=f"u{i}",
        posted_at=posted,
    )


def test_partial_poll_of_new_feed_does_not_mark_it_polled():
    s = State()
    old, recent = NOW - timedelta(days=30), NOW - timedelta(hours=2)
    s.observe("workday:acme", [job(1, recent)], NOW, complete=False)
    assert "workday:acme" not in s.feeds
    assert s.jobs["workday:acme:R1"]["baseline"] is True
    # The next complete poll is still treated as the first: an old job it adds is baseline, not "new".
    later = NOW + timedelta(hours=12)
    s.observe("workday:acme", [job(1, recent), job(2, old)], later)
    assert "workday:acme" in s.feeds
    assert s.jobs["workday:acme:R2"]["baseline"] is True
    assert not s.is_fresh("workday:acme:R2", later, 48)


def test_partial_poll_of_known_feed_behaves_normally():
    s = State()
    s.observe("workday:acme", [], NOW - timedelta(days=1))
    s.observe("workday:acme", [job(1, None)], NOW, complete=False)
    assert s.feeds["workday:acme"]["last_polled"].startswith("2026-11-22T12")
    assert s.jobs["workday:acme:R1"]["baseline"] is False


def test_select_passes_partial_flag_to_state():
    def plan(url, body, n):
        if n == 0:
            return {"jobPostings": POSTINGS}
        raise FetchError("x", 429)

    r = fetch_company(FakeClient(plan), wd("redhat"))
    s = State()
    result = select([r], s, FilterConfig.load(), NOW)
    assert "workday:redhat" not in s.feeds and all(j.id in s.jobs for j in r.jobs)
    assert result.partial == [r] and result.failed == []
