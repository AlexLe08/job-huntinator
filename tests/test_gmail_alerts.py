import base64
import gzip
import json
from datetime import UTC, datetime

from conftest import FIXTURES

from jobscraper.sources import gmail_alerts


def gmail_message(html: str, sender: str, ts_ms: int = 1795000000000) -> dict:
    data = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
    return {
        "id": "m1",
        "internalDate": str(ts_ms),
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": "New jobs"}],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": ""}},
                {"mimeType": "text/html", "body": {"data": data}},
            ],
        },
    }


def test_linkedin_alert_parsing():
    html = (FIXTURES / "gmail" / "linkedin_alert.html").read_text()
    jobs = gmail_alerts.parse_message(gmail_message(html, "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"))
    assert [(j.id, j.title, j.company, j.location) for j in jobs] == [
        ("linkedin:4012345678", "Frontend Engineer", "Acme Robotics", "Boston, MA (Hybrid)"),
        ("linkedin:4099999999", "UI Engineer, Design Systems", "Globex", "United States (Remote)"),
    ]
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert jobs[1].remote is True
    assert jobs[0].posted_at == datetime.fromtimestamp(1795000000, tz=UTC)


def test_indeed_alert_parsing():
    html = (FIXTURES / "gmail" / "indeed_alert.html").read_text()
    jobs = gmail_alerts.parse_message(gmail_message(html, "Indeed <alert@indeed.com>"))
    assert [(j.id, j.title, j.company, j.location) for j in jobs] == [
        ("indeed:a1b2c3d4e5f60718", "Front End Developer", "Initech", "Raleigh, NC"),
        ("indeed:ffeeddccbbaa0099", "Web Developer", "Hooli", "Remote"),
    ]
    assert jobs[0].url == "https://www.indeed.com/viewjob?jk=a1b2c3d4e5f60718"


def test_unknown_sender_tries_both_and_no_html_is_empty():
    html = (FIXTURES / "gmail" / "linkedin_alert.html").read_text()
    assert len(gmail_alerts.parse_message(gmail_message(html, "me@example.com"))) == 2
    assert gmail_alerts.parse_message({"payload": {"mimeType": "text/plain", "body": {"data": ""}}}) == []


def test_fetch_lists_then_reads_messages():
    html = (FIXTURES / "gmail" / "indeed_alert.html").read_text()

    class FakeClient:
        def __init__(self):
            self.calls = []

        def get_json(self, url, headers=None):
            self.calls.append((url, headers))
            if "/messages?" in url:
                return {"messages": [{"id": "m1"}, {"id": "m2"}]}
            return gmail_message(html, "alert@indeed.com")

    c = FakeClient()
    jobs = gmail_alerts.fetch(
        c, {"query": "label:job-alerts newer_than:3d", "max_messages": 5}, datetime.now(UTC), token="tok"
    )
    assert len(jobs) == 2  # same jobs in both messages -> deduped
    assert "q=label%3Ajob-alerts" in c.calls[0][0] and c.calls[0][1] == {"Authorization": "Bearer tok"}


def test_missing_credentials(monkeypatch):
    import pytest

    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)
    with pytest.raises(gmail_alerts.MissingCredentials):
        gmail_alerts.access_token()


def test_real_linkedin_alert_whole_card_is_one_link():
    # Real "Jobs you might be interested in" email (Nov 2026), sanitized: one <a> wraps each card.
    html = (FIXTURES / "gmail" / "linkedin_real_2026-11.html").read_text()
    jobs = gmail_alerts.parse_message(gmail_message(html, "LinkedIn <jobs-noreply@linkedin.com>"))
    assert [(j.id, j.title, j.company, j.location) for j in jobs] == [
        ("linkedin:4475006561", "Senior Software Engineer I - Front End", "Compass", "Boston, MA (Hybrid)"),
        ("linkedin:4492221237", "Senior Front-End Engineer - CAD", "Mark43", "Boston, MA (Hybrid)"),
        ("linkedin:4474715207", "Senior Software Engineer II - Front End", "Compass", "Boston, MA (Hybrid)"),
        (
            "linkedin:4477709375",
            "Sr Software Engineer I ( Web Application & Cloud Development)",
            "Siemens Healthineers",
            "Newton, MA",
        ),
        ("linkedin:4432707829", "Front End Software Engineer", "MORSE Corp", "Cambridge, MA (On-site)"),
        ("linkedin:4481602154", "Senior Frontend Engineer", "Mobi.AI", "Somerville, MA (Hybrid)"),
    ]
    assert all(j.url == f"https://www.linkedin.com/jobs/view/{j.id.split(':')[1]}/" for j in jobs)
    assert all(j.tier == "linkedin-alert" for j in jobs)


def test_real_linkedin_daily_job_alert():
    # Real daily job-alert email from jobalerts-noreply@ (Nov 2026), sanitized: logo, title and card are
    # separate links to the same job, and cards carry "N company alumni" / "1 connection" badges.
    html = (FIXTURES / "gmail" / "linkedin_jobalert_real_2026-11.html").read_text()
    jobs = gmail_alerts.parse_message(gmail_message(html, "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"))
    assert [(j.id, j.title, j.company, j.location) for j in jobs] == [
        ("linkedin:4493279270", "Software Engineer", "Optum", "Hartford, CT"),
        ("linkedin:4486491615", "Software Engineer - Fern", "Postman", "New York, NY"),
        (
            "linkedin:4494730578",
            "Junior Front End Software Engineer",
            "ESChat",
            "Greater San Luis Obispo Area (Hybrid)",
        ),
        ("linkedin:4490966442", "Forward Deployed Software Engineer", "ICF", "Reston, VA"),
        ("linkedin:4493030227", "Full Stack Engineer (E1)", "Lockheed Martin", "Brandon, FL (Remote)"),
        ("linkedin:4494177697", "Software Engineer", "Cisco", "Arlington, VA"),
    ]
    assert [j.remote for j in jobs] == [None, None, None, None, True, None]


def test_alumni_badge_is_never_a_title():
    html = (
        '<a href="https://www.linkedin.com/comm/jobs/view/1/">'
        "<p>36 company alumni</p><p>UI Engineer</p><p>Acme · Remote</p></a>"
    )
    jobs = gmail_alerts.parse_alert_html(html, "linkedin", None)
    assert [(j.title, j.company, j.location) for j in jobs] == [("UI Engineer", "Acme", "Remote")]


def test_card_text_does_not_leak_into_footer_or_skip_links():
    html = (
        '<a href="https://www.linkedin.com/comm/jobs/view/1/"><div>Frontend Engineer</div><p>Acme · Remote</p>'
        "<p>Easy Apply</p></a>"
        '<a href="https://www.linkedin.com/comm/jobs/search-results/">See all jobs</a>'
        "<p>This email was intended for Someone</p>"
        '<a href="https://www.linkedin.com/comm/jobs/view/2/"><img src="logo.png"></a>'
    )
    jobs = gmail_alerts.parse_alert_html(html, "linkedin", None)
    assert [(j.id, j.title, j.company, j.location, j.remote) for j in jobs] == [
        ("linkedin:1", "Frontend Engineer", "Acme", "Remote", True)
    ]


def test_real_indeed_job_match_email():
    # Real Indeed "job match" email from donotreply@match.indeed.com (Nov 2026), sanitized: every link is a
    # cts.indeed.com/v3/<gzip+base64 JSON> redirect, re-encoded here with only the target URL kept.
    html = (FIXTURES / "gmail" / "indeed_match_real_2026-11.html").read_text()
    jobs = gmail_alerts.parse_message(gmail_message(html, "Indeed <donotreply@match.indeed.com>"))
    assert [(j.id, j.title, j.company, j.location, j.remote) for j in jobs] == [
        ("indeed:5c1f6cd011f053a0", "Software Engineer II", "Indeed", "Remote", True)
    ]
    assert jobs[0].url == "https://www.indeed.com/viewjob?jk=5c1f6cd011f053a0"
    assert jobs[0].tier == "indeed-alert"


def _cts(target: str) -> str:
    data = gzip.compress(json.dumps({"u": target, "m": {"tk": "x"}}).encode())
    return "https://cts.indeed.com/v3/" + base64.urlsafe_b64encode(data).decode().rstrip("=")


def test_indeed_redirect_unwrap():
    assert gmail_alerts._unwrap_indeed_redirect(_cts("https://www.indeed.com/rc/clk?jk=abc")) == (
        "https://www.indeed.com/rc/clk?jk=abc"
    )
    # not a redirect, or a corrupt / non-gzip / non-JSON-object blob: no crash, no target
    assert gmail_alerts._unwrap_indeed_redirect("https://www.indeed.com/viewjob?jk=abc") is None
    assert gmail_alerts._unwrap_indeed_redirect("https://cts.indeed.com/v3/H4sIAAAAAAAA_notreallygzip") is None
    junk = base64.urlsafe_b64encode(gzip.compress(b"[1, 2]")).decode().rstrip("=")
    assert gmail_alerts._unwrap_indeed_redirect("https://cts.indeed.com/v3/" + junk) is None
    # a redirect to a non-job page never becomes a job
    html = f'<a href="{_cts("https://match.indeed.com/invitations/pause")}">Pause these emails</a>'
    assert gmail_alerts.parse_alert_html(html, "indeed", None) == []
