from datetime import UTC, datetime

from conftest import load_fixture

from jobscraper.companies import Company
from jobscraper.sources import ashby, greenhouse, lever
from jobscraper.text import extract_comp, html_to_text


def _by_title(jobs, title):
    return next(j for j in jobs if j.title == title)


class TestGreenhouse:
    company = Company("Vercel", "greenhouse", "vercel", tier="frontend-product")

    def jobs(self):
        return [greenhouse.normalize(r, self.company) for r in load_fixture("greenhouse_vercel.json")["jobs"]]

    def test_core_fields(self):
        j = _by_title(self.jobs(), "Engineering Manager, Dashboard")
        assert j.id == "greenhouse:vercel:6115908004"
        assert j.source == "greenhouse"
        assert j.company == "Vercel"
        assert j.tier == "frontend-product"
        assert j.url == "https://job-boards.greenhouse.io/vercel/jobs/6115908004"
        assert j.location == "Hybrid - San Francisco"
        assert j.department == "Engineering"

    def test_uses_first_published_not_updated_at(self):
        j = _by_title(self.jobs(), "Engineering Manager, Dashboard")
        assert j.posted_at == datetime(2026, 9, 22, 20, 38, 55, tzinfo=UTC)
        assert j.updated_at is not None and j.updated_at != j.posted_at

    def test_double_escaped_html_becomes_plain_text(self):
        j = self.jobs()[0]
        assert "&lt;" not in j.description and "<div" not in j.description
        assert j.description.startswith("About Vercel:")

    def test_comp_extracted_from_content(self):
        assert _by_title(self.jobs(), "Engineering Manager, Dashboard").compensation == "$226,000-$325,000"

    def test_remote_flag_from_location(self):
        assert _by_title(self.jobs(), "Customer Support Engineer").remote is True

    def test_nbsp_stripped_from_title(self):
        assert all("\xa0" not in j.title for j in self.jobs())


class TestLever:
    company = Company("Spotify", "lever", "spotify")

    def jobs(self):
        return [lever.normalize(r, self.company) for r in load_fixture("lever_spotify.json")]

    def test_core_fields(self):
        j = _by_title(self.jobs(), "Backend Engineer - Music")
        assert j.id.startswith("lever:spotify:")
        assert j.url.startswith("https://jobs.lever.co/spotify/")
        assert "Boston, MA" in j.location
        assert j.country == "US"
        assert j.department == "Engineering"
        assert j.posted_at.tzinfo is not None

    def test_salary_range_object_preferred(self):
        j = _by_title(self.jobs(), "Accounting Analyst, Content Accounting")
        assert j.compensation == "$76K–$95K USD /year"

    def test_comp_falls_back_to_text(self):
        j = next(j for j in self.jobs() if j.title.startswith("Account Executive") and j.country == "US")
        assert j.compensation == "$87,069-$124,385"

    def test_workplace_type_maps_to_remote(self):
        j = _by_title(self.jobs(), "AV Engineer - Platform")
        assert j.remote is False

    def test_error_payload_returns_no_jobs(self):
        class FakeClient:
            def get_json(self, url):
                return {"ok": False, "error": "Document not found"}

        assert lever.fetch(FakeClient(), self.company) == []


class TestAshby:
    company = Company("Linear", "ashby", "linear")

    def jobs(self):
        return [ashby.normalize(r, self.company) for r in load_fixture("ashby_linear.json")["jobs"]]

    def test_core_fields(self):
        j = next(j for j in self.jobs() if j.title == "Product Engineer")
        assert j.id.startswith("ashby:linear:")
        assert j.url.startswith("https://jobs.ashbyhq.com/linear/")
        assert j.location == "North America"
        assert j.country == "United States"
        assert j.remote is True
        assert j.compensation == "$174K – $245K • Offers Equity"
        assert j.department == "Product / Engineering"
        assert j.description

    def test_missing_comp_is_none(self):
        assert any(j.compensation is None for j in self.jobs())


def test_html_to_text_blocks_and_entities():
    assert html_to_text("<p>Hello&nbsp;<b>world</b></p><ul><li>One</li><li>Two</li></ul>") == "Hello world\nOne\nTwo"


def test_extract_comp_variants():
    assert extract_comp("Pay: $120K - $150K per year") == "$120K - $150K"
    assert extract_comp("between $55/hr to $65/hr") == "$55/hr to $65/hr"
    assert extract_comp("We raised $50 million") is None


def test_greenhouse_placeholder_location_falls_back_to_offices():
    raw = {
        "id": 1,
        "title": "Software Engineer",
        "absolute_url": "https://x",
        "location": {"name": "N/A"},
        "offices": [{"name": "US", "location": None}],
        "content": "",
    }
    j = greenhouse.normalize(raw, Company("Stripe", "greenhouse", "stripe"))
    assert j.location == "US"
