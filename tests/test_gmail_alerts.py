import base64
from datetime import datetime, timezone

from jobscraper.sources import gmail_alerts

from conftest import FIXTURES


def gmail_message(html: str, sender: str, ts_ms: int = 1795000000000) -> dict:
    data = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
    return {"id": "m1", "internalDate": str(ts_ms), "payload": {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": "New jobs"}],
        "parts": [{"mimeType": "text/plain", "body": {"data": ""}},
                  {"mimeType": "text/html", "body": {"data": data}}]}}


def test_linkedin_alert_parsing():
    html = (FIXTURES / "gmail" / "linkedin_alert.html").read_text()
    jobs = gmail_alerts.parse_message(gmail_message(html, "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"))
    assert [(j.id, j.title, j.company, j.location) for j in jobs] == [
        ("linkedin:4012345678", "Frontend Engineer", "Acme Robotics", "Boston, MA (Hybrid)"),
        ("linkedin:4099999999", "UI Engineer, Design Systems", "Globex", "United States (Remote)"),
    ]
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert jobs[1].remote is True
    assert jobs[0].posted_at == datetime.fromtimestamp(1795000000, tz=timezone.utc)


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
    jobs = gmail_alerts.fetch(c, {"query": "label:job-alerts newer_than:3d", "max_messages": 5}, datetime.now(timezone.utc), token="tok")
    assert len(jobs) == 2  # same jobs in both messages -> deduped
    assert "q=label%3Ajob-alerts" in c.calls[0][0] and c.calls[0][1] == {"Authorization": "Bearer tok"}


def test_missing_credentials(monkeypatch):
    import pytest
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)
    with pytest.raises(gmail_alerts.MissingCredentials):
        gmail_alerts.access_token()
