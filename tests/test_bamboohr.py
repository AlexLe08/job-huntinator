from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import load_fixture

from jobscraper.companies import Company
from jobscraper.discovery import find_boards
from jobscraper.filters import FilterConfig, classify_location
from jobscraper.http import FetchError, PoliteClient
from jobscraper.models import Job
from jobscraper.run import FeedResult, select
from jobscraper.sources import bamboohr
from jobscraper.state import State
from jobscraper.validate import probe

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
ARAS = Company("Aras", "bamboohr", "aras", tier="boston")
PROM = Company("Prometheus Group", "bamboohr", "prometheusgroup", tier="rtp")


def client_for(handler) -> PoliteClient:
    return PoliteClient(retries=0, delay=0, backoff_base=0, transport=httpx.MockTransport(handler))


def aras_jobs() -> dict[str, Job]:
    jobs = [bamboohr.normalize(r, ARAS) for r in load_fixture("bamboohr_aras.json")["result"]]
    return {j.id.rsplit(":", 1)[1]: j for j in jobs}


def test_normalize_onsite_remote_hybrid():
    jobs = aras_jobs()
    onsite = jobs["346"]  # locationType 2 (hybrid) in Andover, MA: `location` only, no country
    assert onsite.id == "bamboohr:aras:346" and onsite.url == "https://aras.bamboohr.com/careers/346"
    assert onsite.location == "Andover, Massachusetts" and onsite.remote is False and onsite.country is None
    assert classify_location(onsite.location, onsite.remote, onsite.country) == "MA"
    assert onsite.department and onsite.posted_at is None and onsite.description == ""

    remote_us = jobs["397"]  # locationType 1: `atsLocation` with country
    assert remote_us.location == "Remote - Andover, Massachusetts, United States"
    assert remote_us.remote is True and remote_us.country == "United States"
    assert classify_location(remote_us.location, remote_us.remote, remote_us.country) == "MA"

    remote_pl = jobs["415"]  # atsLocation.state is literally "Remote": don't repeat it
    assert remote_pl.location == "Remote - Krakow, Poland"
    assert classify_location(remote_pl.location, remote_pl.remote, remote_pl.country) == "non_us"

    assert classify_location(jobs["231"].location, jobs["231"].remote, jobs["231"].country) == "non_us"  # Tokyo


def test_enrich_fills_description_date_country_url():
    job = bamboohr.normalize(
        {"id": "41", "jobOpeningName": "Functional Implementation Consultant", "locationType": "0", "location": {}},
        PROM,
    )
    detail = load_fixture("bamboohr_prometheusgroup_detail.json")
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, json=detail)

    bamboohr.enrich(client_for(handler), job, PROM)
    assert urls == ["https://prometheusgroup.bamboohr.com/careers/41/detail"]
    assert len(job.description) > 500 and "<p>" not in job.description
    assert job.posted_at == datetime(2025, 9, 17, tzinfo=UTC)
    assert job.country == "United States"
    assert job.url == "https://prometheusgroup.bamboohr.com/careers/41"


def test_enrich_country_fixes_unknown_location():
    """Dresden, Saxony classifies as unknown from the list; the detail's country settles it."""
    job = aras_jobs()["390"]
    assert classify_location(job.location, job.remote, job.country) == "unknown"
    detail = {"result": {"jobOpening": {"description": "<p>x</p>", "location": {"addressCountry": "Germany"}}}}
    bamboohr.enrich(client_for(lambda req: httpx.Response(200, json=detail)), job, ARAS)
    assert classify_location(job.location, job.remote, job.country) == "non_us"


def test_fetch_reads_list():
    payload = load_fixture("bamboohr_aras.json")

    def handler(req):
        assert str(req.url) == "https://aras.bamboohr.com/careers/list"
        return httpx.Response(200, json=payload)

    jobs = bamboohr.fetch(client_for(handler), ARAS)
    assert len(jobs) == len(payload["result"]) and all(j.company == "Aras" for j in jobs)


def unknown_subdomain(req):
    if req.url.host == "www.bamboohr.com":
        return httpx.Response(200, text="<html>marketing</html>", headers={"content-type": "text/html"})
    return httpx.Response(302, headers={"location": "https://www.bamboohr.com/"})


def test_unknown_subdomain_redirect_is_a_404():
    with pytest.raises(FetchError) as exc:
        bamboohr.fetch(client_for(unknown_subdomain), Company("Nope", "bamboohr", "nope"))
    assert exc.value.status == 404


def test_validator_probe():
    assert probe(client_for(unknown_subdomain), "bamboohr", "nope") is None
    payload = load_fixture("bamboohr_aras.json")
    p = probe(client_for(lambda req: httpx.Response(200, json=payload)), "bamboohr", "aras")
    assert p is not None and p.jobs == len(payload["result"])


def test_first_poll_without_dates_does_not_flood():
    """The list has no posted_at, so a new board's baseline jobs must not all look fresh on the first poll."""
    jobs = list(aras_jobs().values())
    state = State()
    state.observe("bamboohr:aras", jobs, NOW)
    assert not any(state.is_candidate(j.id, NOW, 48) for j in jobs)
    later = NOW + timedelta(hours=12)
    new = Job(id="bamboohr:aras:999", source="bamboohr", company="Aras", title="Frontend Engineer", location="", url="")
    state.observe("bamboohr:aras", [*jobs, new], later)
    assert state.is_candidate(new.id, later, 48)


def test_select_enriches_bamboohr_candidates():
    job = Job(
        id="bamboohr:aras:1",
        source="bamboohr",
        company="Aras",
        title="Frontend Engineer",
        location="Andover, Massachusetts",
        url="https://aras.bamboohr.com/careers/1",
        posted_at=NOW - timedelta(hours=1),
    )
    called = []
    r = select(
        [FeedResult("bamboohr:aras", ARAS, [job])],
        State(),
        FilterConfig.load(),
        NOW,
        None,
        lambda j, c: called.append(j.id),
    )
    assert called == ["bamboohr:aras:1"] and len(r.matches) == 1


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://acme.bamboohr.com/careers/12", {("bamboohr", "acme")}),
        ("https://acme-inc.bamboohr.com/jobs/view.php?id=3", {("bamboohr", "acme-inc")}),
        ("https://www.bamboohr.com/careers", set()),
        ("https://acme.bamboohr.com/login", set()),
    ],
)
def test_discovery_spots_bamboohr_links(url, expected):
    job = Job(id="x:1", source="x", company="X", title="t", location="", url=url)
    assert find_boards(job) == expected
