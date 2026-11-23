"""End-to-end pipeline tests with mocked HTTP (respx) and fixture payloads."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import respx

from jobscraper import cli
from jobscraper.companies import Company
from jobscraper.dedupe import TrackerIndex
from jobscraper.filters import FilterConfig
from jobscraper.http import PoliteClient
from jobscraper.run import fetch_all, select
from jobscraper.state import State

from conftest import load_fixture

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
CFG = FilterConfig.load()


def gh_board(*jobs):
    return {"jobs": list(jobs), "meta": {"total": len(jobs)}}


def gh_job(i, title, location="Remote - US", posted=NOW - timedelta(hours=3)):
    return {"id": i, "title": title, "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{i}",
            "location": {"name": location}, "first_published": posted.isoformat(),
            "updated_at": posted.isoformat(), "content": "&lt;p&gt;Build UIs in React.&lt;/p&gt;", "departments": []}


def clients():
    return {k: PoliteClient(delay=0, retries=1, backoff_base=0) for k in ("greenhouse", "lever", "ashby")}


@respx.mock
def test_pipeline_fresh_filtered_and_failure_tolerant():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(return_value=httpx.Response(200, json=gh_board(
        gh_job(1, "Frontend Engineer"),
        gh_job(2, "Staff Frontend Engineer"),
        gh_job(3, "Frontend Engineer", location="London, UK"),
        gh_job(4, "Frontend Engineer II", posted=NOW - timedelta(days=20)),  # old -> flood guard
        gh_job(5, "Senior Web Developer", location="Boston, MA"),
    )))
    respx.get("https://api.lever.co/v0/postings/spotify").mock(return_value=httpx.Response(200, json=load_fixture("lever_spotify.json")))
    respx.get("https://api.ashbyhq.com/posting-api/job-board/broken").mock(return_value=httpx.Response(500))
    companies = [Company("Acme", "greenhouse", "acme", "boston"), Company("Spotify", "lever", "spotify"),
                 Company("Broken", "ashby", "broken")]
    feeds = fetch_all(companies, clients())
    assert [f.error is not None for f in feeds] == [False, False, True]

    state = State()
    r = select(feeds, state, CFG, NOW)
    got = [(m.job.title, m.job.flags, m.location_class) for m in r.matches]
    assert got == [("Frontend Engineer", [], "us_remote"), ("Senior Web Developer", ["senior"], "MA")]
    assert "greenhouse:acme" in state.feeds and "ashby:broken" not in state.feeds

    # Second run, 6h later: one brand-new posting appears; earlier ones already reported.
    state.mark_reported([m.job.id for m in r.matches], NOW)
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(return_value=httpx.Response(200, json=gh_board(
        gh_job(1, "Frontend Engineer"), gh_job(6, "UI Engineer", posted=NOW - timedelta(days=60)))))
    later = NOW + timedelta(hours=6)
    r2 = select(fetch_all(companies[:1], clients()), state, CFG, later)
    assert [m.job.title for m in r2.matches] == ["UI Engineer"]  # new on a known feed: fresh by first-seen


def test_select_skips_tracked_jobs():
    from jobscraper.run import FeedResult
    from jobscraper.sources import greenhouse

    c = Company("Acme", "greenhouse", "acme")
    jobs = [greenhouse.normalize(gh_job(1, "Frontend Engineer"), c)]
    idx = TrackerIndex()
    idx.add("Acme", "Front-End Engineer", "")
    r = select([FeedResult("greenhouse:acme", c, jobs)], State(), CFG, NOW, idx)
    assert r.matches == [] and r.already_tracked[0][1] == "company+title"


@respx.mock
def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.setattr(cli, "ROOT", tmp_path)  # no .env, outputs would land here
    monkeypatch.setattr("jobscraper.run.make_clients", clients)
    monkeypatch.setattr("jobscraper.run.now_utc", lambda: NOW)
    companies = tmp_path / "companies.yaml"
    companies.write_text("companies:\n  - {company: Acme, ats: greenhouse, token: acme, tier: boston}\n")
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=gh_board(gh_job(1, "Frontend Engineer"))))
    state_path = tmp_path / "state" / "seen.json"

    rc = cli.main(["run", "--dry-run", "--no-feeds", "--companies", str(companies), "--state", str(state_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "Frontend Engineer" in out.out
    assert not state_path.exists()
    assert not (tmp_path / "data").exists()


@respx.mock
def test_cli_no_sheet_run_writes_state_and_json_then_reports_once(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("jobscraper.run.make_clients", clients)
    monkeypatch.setattr("jobscraper.run.now_utc", lambda: NOW)
    monkeypatch.setattr("jobscraper.run.default_paths", lambda root: {"state": tmp_path / "seen.json", "matches": tmp_path / "matches"})
    companies = tmp_path / "companies.yaml"
    companies.write_text("companies:\n  - {company: Acme, ats: greenhouse, token: acme}\n")
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=gh_board(gh_job(1, "Frontend Engineer"))))

    assert cli.main(["run", "--no-sheet", "--no-feeds", "--companies", str(companies)]) == 0
    data = json.loads((tmp_path / "matches" / "2026-11-22.json").read_text())
    assert [d["title"] for d in data] == ["Frontend Engineer"]
    assert data[0]["location_class"] == "us_remote"
    capsys.readouterr()
    assert cli.main(["run", "--no-sheet", "--no-feeds", "--companies", str(companies)]) == 0
    assert "(no new matches)" in capsys.readouterr().out


def test_cli_real_run_requires_sheet(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    companies = tmp_path / "companies.yaml"
    companies.write_text("companies:\n  - {company: Acme, ats: greenhouse, token: acme}\n")
    assert cli.main(["run", "--no-feeds", "--companies", str(companies)]) == 2


@respx.mock
def test_cli_quiet_prints_no_job_details(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("jobscraper.run.make_clients", clients)
    monkeypatch.setattr("jobscraper.run.now_utc", lambda: NOW)
    companies = tmp_path / "companies.yaml"
    companies.write_text("companies:\n  - {company: Acme, ats: greenhouse, token: acme}\n")
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=gh_board(gh_job(1, "Frontend Engineer"))))
    assert cli.main(["run", "--dry-run", "--quiet", "--explain", "--no-feeds", "--companies", str(companies)]) == 0
    out = capsys.readouterr()
    assert "Frontend Engineer" not in out.out + out.err
    assert "1 new matches" in out.err
