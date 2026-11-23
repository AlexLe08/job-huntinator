from datetime import datetime, timedelta, timezone

from jobscraper.companies import Company
from jobscraper.filters import FilterConfig, classify_location
from jobscraper.sources import recruitee, smartrecruiters, workable, workday

from conftest import load_fixture

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, payload):
        self.payload, self.urls = payload, []

    def get_json(self, url):
        self.urls.append(url)
        return self.payload


def test_smartrecruiters_list_and_enrich():
    c = Company("ServiceNow", "smartrecruiters", "ServiceNow")
    raw = load_fixture("smartrecruiters_servicenow.json")["content"]
    jobs = [smartrecruiters.normalize(r, c) for r in raw]
    j = jobs[0]
    assert j.id.startswith("smartrecruiters:ServiceNow:")
    assert j.url.startswith("https://jobs.smartrecruiters.com/ServiceNow/")
    assert "Santa Clara" in j.location and j.country == "US"
    assert j.posted_at is not None and j.description == ""
    detail = load_fixture("smartrecruiters_servicenow_detail.json")
    client = FakeClient(detail)
    smartrecruiters.enrich(client, j, c)
    assert client.urls[0].endswith(f"/postings/{j.id.rsplit(':', 1)[1]}")
    assert len(j.description) > 200 and "<" not in j.description
    assert j.url == detail["postingUrl"]


def test_workable_normalize():
    c = Company("Hugging Face", "workable", "huggingface")
    jobs = [workable.normalize(r, c) for r in load_fixture("workable_huggingface.json")["jobs"]]
    us = next(j for j in jobs if "US Remote" in j.title)
    assert us.country == "US" and us.remote is True and us.location.startswith("Remote")
    assert us.url.startswith("https://apply.workable.com/j/")
    assert classify_location(us.location, us.remote, us.country) == "us_remote"
    emea = next(j for j in jobs if "EMEA" in j.title)
    assert classify_location(emea.location, emea.remote, emea.country) == "non_us"
    assert all(j.description and j.posted_at for j in jobs)


def test_recruitee_normalize():
    c = Company("bunq", "recruitee", "bunq")
    jobs = [recruitee.normalize(r, c) for r in load_fixture("recruitee_bunq.json")["offers"]]
    j = jobs[0]
    assert j.title == "Copywriter" and j.country == "NL"
    assert j.url == "https://careers.bunq.com/o/copywriter-3"
    assert j.posted_at == datetime(2026, 11, 18, 16, 23, 32, tzinfo=timezone.utc)
    assert "Amsterdam" in j.location and j.description


def test_workday_normalize_and_enrich():
    c = Company("Red Hat", "workday", "redhat", tier="rtp", extra={"host": "redhat.wd5.myworkdayjobs.com", "site": "jobs"})
    raw = load_fixture("workday_redhat.json")["jobPostings"]
    jobs = [workday.normalize(r, c, NOW) for r in raw]
    j = jobs[0]
    assert j.id.startswith("workday:redhat:R-")
    assert j.url.startswith("https://redhat.wd5.myworkdayjobs.com/jobs/job/")
    remote_us = next(x for x in jobs if x.location.startswith("Remote") and " US " in f" {x.location} ")
    assert classify_location(remote_us.location, remote_us.remote, remote_us.country) == "us_remote"
    detail = load_fixture("workday_redhat_detail.json")
    client = FakeClient(detail)
    workday.enrich(client, j, c)
    assert client.urls[0].startswith("https://redhat.wd5.myworkdayjobs.com/wday/cxs/redhat/jobs/job/")
    assert j.description and j.url == detail["jobPostingInfo"]["externalUrl"]
    assert j.posted_at.date().isoformat() == detail["jobPostingInfo"]["startDate"]


def test_workday_posted_on_parsing():
    assert workday.parse_posted_on("Posted Today", NOW) == NOW
    assert workday.parse_posted_on("Posted Yesterday", NOW) == NOW - timedelta(days=1)
    assert workday.parse_posted_on("Posted 3 Days Ago", NOW) == NOW - timedelta(days=3)
    assert workday.parse_posted_on("Posted 30+ Days Ago", NOW) == NOW - timedelta(days=30)
    assert workday.parse_posted_on(None, NOW) is None


def test_workday_requires_host_and_site():
    import pytest
    with pytest.raises(ValueError):
        workday.board_url(Company("X", "workday", "x"))


def test_enricher_runs_only_for_cheap_filter_passes():
    from jobscraper.models import Job
    from jobscraper.run import FeedResult, select
    from jobscraper.state import State

    cfg = FilterConfig.load()
    c = Company("Acme", "smartrecruiters", "acme")
    def mk(i, title, loc):
        return Job(id=f"smartrecruiters:acme:{i}", source="smartrecruiters", company="Acme", title=title,
                   location=loc, url=f"https://x/{i}", posted_at=NOW - timedelta(hours=1))
    jobs = [mk(1, "Frontend Engineer", "Boston, MA"), mk(2, "Account Executive", "Boston, MA"),
            mk(3, "Frontend Engineer", "Berlin, Germany"), mk(4, "Web Developer", "Austin, TX")]
    called = []
    def enricher(job, company):
        called.append(job.id)
        if job.id.endswith(":4"):
            job.description = "Requires an active TS/SCI clearance."
    r = select([FeedResult("smartrecruiters:acme", c, jobs)], State(), cfg, NOW, None, enricher)
    assert called == ["smartrecruiters:acme:1", "smartrecruiters:acme:4"]
    assert [m.job.title for m in r.matches] == ["Frontend Engineer"]
    assert r.drop_reasons["red-flag:clearance"] == 1
