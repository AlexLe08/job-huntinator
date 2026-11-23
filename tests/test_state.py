import json
from datetime import UTC, datetime, timedelta

from jobscraper.models import Job
from jobscraper.state import State

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
H = 48


def job(i, posted=None):
    return Job(
        id=f"greenhouse:acme:{i}",
        source="greenhouse",
        company="Acme",
        title=f"Frontend Engineer {i}",
        location="Remote - US",
        url=f"https://example.com/{i}",
        posted_at=posted,
    )


def test_first_poll_is_baseline_only_recent_posted_are_fresh():
    s = State()
    old = job(1, posted=T0 - timedelta(days=30))
    recent = job(2, posted=T0 - timedelta(hours=5))
    unknown = job(3, posted=None)
    s.observe("greenhouse:acme", [old, recent, unknown], T0)
    assert not s.is_candidate(old.id, T0, H)
    assert s.is_candidate(recent.id, T0, H)
    assert not s.is_candidate(unknown.id, T0, H)


def test_new_job_on_known_feed_is_fresh_regardless_of_posted_at():
    s = State()
    s.observe("greenhouse:acme", [job(1)], T0)
    later = T0 + timedelta(hours=12)
    reposted = job(2, posted=T0 - timedelta(days=90))  # e.g. old req newly opened on the board
    s.observe("greenhouse:acme", [job(1), reposted], later)
    assert s.is_candidate(reposted.id, later, H)


def test_freshness_expires():
    s = State()
    s.observe("greenhouse:acme", [], T0)
    s.observe("greenhouse:acme", [job(1)], T0 + timedelta(hours=1))
    assert s.is_candidate(job(1).id, T0 + timedelta(hours=48), H)
    assert not s.is_candidate(job(1).id, T0 + timedelta(hours=50), H)


def test_first_seen_not_reset_by_later_polls():
    s = State()
    s.observe("greenhouse:acme", [], T0)
    s.observe("greenhouse:acme", [job(1)], T0 + timedelta(hours=1))
    s.observe("greenhouse:acme", [job(1)], T0 + timedelta(hours=40))
    assert s.first_seen(job(1).id) == T0 + timedelta(hours=1)


def test_reported_once():
    s = State()
    s.observe("greenhouse:acme", [], T0)
    s.observe("greenhouse:acme", [job(1)], T0)
    s.mark_reported([job(1).id], T0)
    assert not s.is_candidate(job(1).id, T0 + timedelta(hours=1), H)


def test_round_trip_and_corrupt_file(tmp_path):
    p = tmp_path / "state" / "seen.json"
    s = State.load(p)
    assert not s.loaded_from_disk
    s.observe("lever:acme", [job(1, posted=T0)], T0)
    s.save()
    s2 = State.load(p)
    assert s2.loaded_from_disk and job(1).id in s2.jobs and "lever:acme" in s2.feeds
    p.write_text("{not json")
    assert State.load(p).jobs == {}


def test_prune_drops_long_gone_jobs():
    s = State()
    s.observe("greenhouse:acme", [job(1), job(2)], T0)
    s.observe("greenhouse:acme", [job(2)], T0 + timedelta(days=70))
    assert s.prune(T0 + timedelta(days=70)) == 1
    assert list(s.jobs) == [job(2).id]


def test_saved_file_is_json(tmp_path):
    p = tmp_path / "seen.json"
    s = State(path=p)
    s.observe("ashby:acme", [job(1)], T0)
    s.save()
    data = json.loads(p.read_text())
    assert data["version"] == 1
