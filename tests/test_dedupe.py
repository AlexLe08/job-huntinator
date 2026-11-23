from datetime import UTC

import pytest

from jobscraper.dedupe import TrackerIndex, job_key, normalize_company, normalize_url
from jobscraper.models import Job
from jobscraper.output import sheet_row
from jobscraper.sheets import _safe, index_rows

APPS_HEADER = [
    "Company",
    "Role",
    "Last Updated",
    "Status",
    "Location",
    "Job Posting Link",
    "Tailored Resume",
    "Contact / Recruiter",
    "Next Step",
    "Follow-up By",
    "Notes",
]
LEADS_HEADER = ["Date Found", "Company", "Role", "Location", "Job Posting Link", "Status", "Notes"]


def job(title="Frontend Engineer", company="Acme", url="https://job-boards.greenhouse.io/acme/jobs/123"):
    return Job(
        id="greenhouse:acme:123", source="greenhouse", company=company, title=title, location="Remote - US", url=url
    )


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://boards.greenhouse.io/acme/jobs/123?gh_src=abc", "https://job-boards.greenhouse.io/acme/jobs/123"),
        ("HTTPS://www.Example.com/careers/42/", "https://example.com/careers/42"),
        (
            "https://jobs.lever.co/acme/0b6c4a8e-1111-2222-3333-444455556666/apply",
            "https://jobs.lever.co/acme/0b6c4a8e-1111-2222-3333-444455556666",
        ),
    ],
)
def test_normalize_url_equivalents(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_job_key_from_embed_and_board():
    assert job_key("https://acme.com/careers?gh_jid=123") == "gh:123"
    assert job_key("https://job-boards.greenhouse.io/acme/jobs/123") == "gh:123"
    assert (
        job_key("https://jobs.ashbyhq.com/acme/0B6C4A8E-1111-2222-3333-444455556666")
        == "ashbyhq:0b6c4a8e-1111-2222-3333-444455556666"
    )
    assert job_key("https://example.com/job/1") is None


def test_normalize_company():
    assert normalize_company("Acme, Inc.") == normalize_company("acme") == "acme"
    assert normalize_company("Anysphere (Cursor)") == "anysphere"


def _index():
    return index_rows(
        {
            "Applications": [
                APPS_HEADER,
                ["Acme Inc", "Front End Engineer", "", "Applied", "", "https://acme.com/careers?gh_jid=999"],
            ],
            "Archive": [
                APPS_HEADER,
                ["Globex", "UI Engineer", "", "Rejected", "", "https://boards.greenhouse.io/globex/jobs/555"],
            ],
            "Leads": [
                LEADS_HEADER,
                ["2026-11-01", "Initech", "Web Developer", "Boston", "https://jobs.lever.co/initech/abc"],
            ],
        }
    )


def test_match_by_url():
    idx = _index()
    assert (
        idx.match(job(company="Globex", title="Whatever", url="https://job-boards.greenhouse.io/globex/jobs/555"), 0.85)
        == "url"
    )


def test_match_by_job_id_across_domains():
    idx = _index()
    assert (
        idx.match(job(company="Acme", title="Other", url="https://job-boards.greenhouse.io/acme/jobs/999"), 0.85)
        == "job-id"
    )


def test_match_by_company_and_similar_title():
    idx = _index()
    assert idx.match(job(company="ACME", title="Frontend Engineer", url="https://x.com/1"), 0.85) == "company+title"
    assert idx.match(job(company="Initech", title="Web Developer II", url="https://x.com/2"), 0.85) == "company+title"


def test_no_match_for_different_role():
    idx = _index()
    assert idx.match(job(company="Acme", title="Solutions Engineer", url="https://x.com/3"), 0.85) is None
    assert idx.match(job(company="Hooli", title="Frontend Engineer", url="https://x.com/4"), 0.85) is None


def test_index_tolerates_short_rows_and_missing_tabs():
    idx = index_rows({"Applications": [APPS_HEADER, ["Acme"], []], "Leads": []})
    assert isinstance(idx, TrackerIndex)


def test_sheet_row_shape_and_formula_escaping():
    from datetime import datetime

    j = job()
    j.match_tier, j.tier, j.flags, j.compensation = 1, "boston", ["senior"], "$100K – $120K"
    row = sheet_row(j, datetime(2026, 11, 22, 17, 0, tzinfo=UTC))
    assert row == [
        "2026-11-22 12:00",
        "Acme",
        "Frontend Engineer",
        "Remote - US",
        "https://job-boards.greenhouse.io/acme/jobs/123",
        "",
        "$100K – $120K",
        "greenhouse",
        "T1 · boston",
        "senior",
    ]
    assert _safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
