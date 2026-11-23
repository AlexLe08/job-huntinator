from datetime import UTC, datetime, timedelta

import httpx
import respx
from conftest import FIXTURES, load_fixture

from jobscraper.companies import Company
from jobscraper.discovery import find_boards, render_markdown, update_suggestions
from jobscraper.filters import FilterConfig, classify_location
from jobscraper.http import PoliteClient
from jobscraper.models import Job
from jobscraper.run import FeedResult, select
from jobscraper.sources import adzuna, hn, remote_boards
from jobscraper.state import State

CFG = FilterConfig.load()
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def client():
    return PoliteClient(delay=0, retries=0, backoff_base=0)


# ------------------------------------------------------------------ HN
def test_hn_parse_header_picks_matching_role():
    company, role, loc = hn.parse_header(
        "Acme | Staff Backend Engineer, Frontend Engineer | Boston, MA / Remote (US) | Full-time | $150k", CFG
    )
    assert (company, role) == ("Acme", "Frontend Engineer")
    assert "Boston, MA" in loc and "Remote" in loc


def test_hn_parse_header_no_roles():
    company, role, _ = hn.parse_header("Acme | We are hiring lots of people", CFG)
    assert company == "Acme" and role == "We are hiring lots of people"


@respx.mock
def test_hn_fetch_only_top_level_recent():
    respx.get(url__startswith="https://hn.algolia.com/api/v1/search_by_date?tags=story").mock(
        return_value=httpx.Response(200, json=load_fixture("hn_stories.json"))
    )
    route = respx.get(url__startswith="https://hn.algolia.com/api/v1/search_by_date?tags=comment").mock(
        return_value=httpx.Response(200, json=load_fixture("hn_comments.json"))
    )
    jobs = hn.fetch(client(), {"lookback_hours": 72}, NOW, CFG)
    assert "story_50338728" in str(route.calls[0].request.url)
    assert "numericFilters=created_at_i" in str(route.calls[0].request.url)
    assert all(j.id.startswith("hn:") and j.source == "hn" for j in jobs)
    companies = [j.company for j in jobs]
    assert "outGoing" in companies and "Joulent" in companies
    assert len(jobs) <= 6  # the reply is excluded
    joulent = next(j for j in jobs if j.company == "Joulent")
    assert joulent.title == "AI Engineer" or joulent.title.startswith("AI Engineer")
    assert "San Francisco" in joulent.location
    assert joulent.compensation and joulent.compensation.startswith("$175k")
    assert all("&#x2F;" not in j.location for j in jobs)


def test_hn_link_prefers_ats():
    hit = {
        "objectID": "1",
        "created_at_i": 1795000000,
        "comment_text": 'Acme | Frontend Engineer | Remote (US)<p>Apply: <a href="https://acme.com/about">site</a> '
        '<a href="https://jobs.lever.co/acme/0b6c4a8e-1111-2222-3333-444455556666">apply</a>',
    }
    j = hn.normalize(hit, CFG)
    assert j.url == "https://jobs.lever.co/acme/0b6c4a8e-1111-2222-3333-444455556666"


def test_hn_non_post_skipped():
    assert hn.normalize({"objectID": "2", "created_at_i": 1, "comment_text": "Is this still open?"}, CFG) is None


# ------------------------------------------------------------------ remote boards
def test_remotive_normalize():
    jobs = [remote_boards.normalize_remotive(j) for j in load_fixture("remotive.json")["jobs"]]
    j = jobs[0]
    assert j.id.startswith("remotive:") and j.url.startswith("https://remotive.com/")
    assert j.location.startswith("Remote - ") and j.remote is True and j.posted_at
    usa = next((x for x in jobs if "USA" in x.location), None)
    if usa:
        assert classify_location(usa.location, usa.remote, usa.country) == "us_remote"


def test_remoteok_skips_legal_notice_and_normalizes():
    raw = load_fixture("remoteok.json")
    jobs = [remote_boards.normalize_remoteok(j) for j in raw if isinstance(j, dict) and j.get("position")]
    assert len(jobs) == len(raw) - 1
    reddit = next(j for j in jobs if j.company == "Reddit")
    assert reddit.location == "Remote - US Only"
    assert classify_location(reddit.location, reddit.remote, reddit.country) == "us_remote"


def test_himalayas_normalize():
    jobs = [remote_boards.normalize_himalayas(j) for j in load_fixture("himalayas.json")["jobs"]]
    j = jobs[0]
    assert j.country == "US" and j.compensation == "$23.50–$25.50/hr"
    assert j.url.startswith("https://himalayas.app/")


def test_wwr_rss_parse():
    jobs = remote_boards.parse_wwr((FIXTURES / "wwr_frontend.xml").read_text())
    assert len(jobs) == 4
    j = jobs[0]
    assert j.company == "OKX" and j.title == "Head of Compliance, LATAM"
    assert j.url.startswith("https://weworkremotely.com/remote-jobs/") and j.posted_at.tzinfo


# ------------------------------------------------------------------ adzuna
def test_adzuna_requires_keys(monkeypatch):
    import pytest

    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    with pytest.raises(adzuna.MissingCredentials):
        adzuna.fetch(client(), {"queries": ["x"]}, NOW)


@respx.mock
def test_adzuna_fetch_dedupes_across_queries(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    payload = {
        "results": [
            {
                "id": "123",
                "title": "<strong>Frontend</strong> Engineer",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Boston, Suffolk County"},
                "redirect_url": "https://www.adzuna.com/details/123",
                "created": "2026-11-17T08:00:00Z",
                "salary_min": 120000,
                "salary_max": 150000,
                "salary_is_predicted": "0",
                "description": "Build React apps",
                "category": {"label": "IT Jobs"},
            }
        ]
    }
    route = respx.get(url__startswith="https://api.adzuna.com/v1/api/jobs/us/search/1").mock(
        return_value=httpx.Response(200, json=payload)
    )
    jobs = adzuna.fetch(client(), {"queries": ["frontend engineer", "ui engineer"]}, NOW)
    assert route.call_count == 2 and len(jobs) == 1
    j = jobs[0]
    assert j.title == "Frontend Engineer" and j.compensation == "$120K–$150K" and j.country == "US"
    assert "app_key=key" in str(route.calls[0].request.url)


# ------------------------------------------------------------------ merge + discovery
def _job(source, i, company, title, url, desc=""):
    return Job(
        id=f"{source}:{i}",
        source=source,
        company=company,
        title=title,
        location="Remote - US",
        url=url,
        posted_at=NOW - timedelta(hours=1),
        description=desc,
    )


def test_aggregator_duplicate_of_ats_job_is_dropped():
    gh = Company("Acme", "greenhouse", "acme")
    ats_jobs = [_job("greenhouse", 1, "Acme", "Frontend Engineer", "https://job-boards.greenhouse.io/acme/jobs/1")]
    agg = [
        _job("remotive", 2, "Acme Inc.", "Frontend Engineer", "https://remotive.com/x"),
        _job("remoteok", 3, "Initech", "UI Engineer", "https://remoteok.com/y"),
        _job("himalayas", 4, "Initech", "UI Engineer", "https://himalayas.app/z"),
    ]
    feeds = [
        FeedResult("remotive", Company("remotive", "remotive", "remotive"), agg[:1]),
        FeedResult("remoteok", Company("remoteok", "remoteok", "remoteok"), agg[1:2]),
        FeedResult("himalayas", Company("himalayas", "himalayas", "himalayas"), agg[2:]),
        FeedResult("greenhouse:acme", gh, ats_jobs),
    ]
    r = select(feeds, State(), CFG, NOW)
    assert sorted(m.job.id for m in r.matches) == ["greenhouse:1", "remoteok:3"]
    assert r.drop_reasons["duplicate-of-other-source"] == 2


def test_discovery_finds_unlisted_boards(tmp_path):
    jobs = [
        _job(
            "hn",
            1,
            "Hooli",
            "Frontend Engineer",
            "https://jobs.ashbyhq.com/hooli/abc",
            desc="also see https://boards.greenhouse.io/acme/jobs/9 and https://apply.workable.com/j/XYZ",
        ),
        _job("hn", 2, "Hooli", "UI Engineer", "https://jobs.ashbyhq.com/hooli/def"),
    ]
    assert find_boards(jobs[0]) == {("ashby", "hooli"), ("greenhouse", "acme")}
    data = update_suggestions(jobs, [Company("Acme", "greenhouse", "acme")], tmp_path / "s.json", NOW)
    assert list(data) == ["ashby:hooli"] and data["ashby:hooli"]["count"] == 2
    render_markdown(data, tmp_path / "s.md")
    assert "token: hooli" in (tmp_path / "s.md").read_text()


def test_suggestions_dropped_once_added_and_summary_has_no_titles(tmp_path):
    from jobscraper.discovery import summary_markdown

    jobs = [
        _job("hn", 1, "Hooli", "Secret Frontend Role", "https://jobs.ashbyhq.com/hooli/abc"),
        _job("hn", 2, "Initech", "Web Dev", "https://jobs.lever.co/initech/def"),
    ]
    path = tmp_path / "s.json"
    data = update_suggestions(jobs, [], path, NOW)
    md = summary_markdown(data, NOW)
    assert "token: hooli" in md and "token: initech" in md and "| yes |" in md
    assert "Secret Frontend Role" not in md and "Web Dev" not in md
    later = NOW + timedelta(hours=6)
    data = update_suggestions([], [Company("Hooli", "ashby", "hooli")], path, later)
    assert list(data) == ["lever:initech"]
    assert "| yes |" not in summary_markdown(data, later)
    assert "No unlisted" in summary_markdown({}, NOW)


@respx.mock
def test_cli_writes_suggestions_to_github_step_summary(tmp_path, monkeypatch):
    from jobscraper import cli
    from jobscraper.sources.aggregators import AGGREGATORS

    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("jobscraper.run.now_utc", lambda: NOW)
    monkeypatch.setattr(
        "jobscraper.run.default_paths",
        lambda root: {"state": tmp_path / "state" / "seen.json", "matches": tmp_path / "data" / "matches"},
    )
    monkeypatch.setitem(
        AGGREGATORS,
        "fake",
        lambda c, s, n, cfg: [_job("fake", 1, "Hooli", "Frontend Engineer", "https://jobs.ashbyhq.com/hooli/abc")],
    )
    sources = tmp_path / "sources.yaml"
    sources.write_text("fake: {enabled: true}\n")
    companies = tmp_path / "companies.yaml"
    companies.write_text("companies: []\n")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert cli.main(["run", "--no-sheet", "--quiet", "--companies", str(companies), "--sources", str(sources)]) == 0
    text = summary.read_text()
    assert "token: hooli" in text and "Frontend Engineer" not in text
