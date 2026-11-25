"""Guards for .github/workflows/scrape.yml: the daily maintenance job (keepalive + cache prune) and permissions."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "scrape.yml"


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WORKFLOW.read_text())


def _step(job, name):
    return next(s for s in job["steps"] if s.get("name") == name)


def test_only_maintenance_can_write_actions(wf):
    assert wf["permissions"] == {"contents": "read"}
    for name, job in wf["jobs"].items():
        perms = job.get("permissions", {})
        if name == "maintenance":
            assert perms == {"actions": "write"}
        else:
            assert "actions" not in perms


def test_maintenance_runs_once_a_day_without_checkout_or_secrets(wf):
    job = wf["jobs"]["maintenance"]
    crons = [s["cron"] for s in wf[True]["schedule"]]  # PyYAML parses the `on:` key as True
    assert "30 11 * * *" in crons
    assert "github.event.schedule == '30 11 * * *'" in job["if"]
    assert "environment" not in job
    assert "secrets." not in json.dumps(job)
    assert not any("checkout" in s.get("uses", "") for s in job["steps"])


def test_keepalive_reenables_the_workflow(wf):
    run = _step(wf["jobs"]["maintenance"], "Reset the 60-day inactivity timer")["run"]
    assert "gh api -X PUT" in run
    assert "actions/workflows/scrape.yml/enable" in run


def test_state_cache_key_matches_prune_prefix(wf):
    steps = wf["jobs"]["scrape"]["steps"]
    keys = [s["with"]["key"] for s in steps if "actions/cache" in s.get("uses", "")]
    assert keys and all(k.startswith("jobscraper-state-") for k in keys)


# Runs the workflow's real prune script against a fake `gh` (jq is real).
FAKE_GH = """#!/usr/bin/env bash
# `cache list` prints $FAKE_CACHES; `cache delete ID` records ID (fails for IDs in $FAKE_FAIL).
echo "$*" >> "$FAKE_LOG"
if [ "$1 $2" = "cache list" ]; then cat "$FAKE_CACHES"; exit 0; fi
if [ "$1 $2" = "cache delete" ]; then
  for bad in $FAKE_FAIL; do [ "$3" = "$bad" ] && exit 1; done
  echo "$3" >> "$FAKE_DELETED"; exit 0
fi
exit 2
"""


def _run_prune(wf, tmp_path, caches, fail=""):
    if not (shutil.which("bash") and shutil.which("jq")):
        pytest.skip("needs bash and jq")
    script = _step(wf["jobs"]["maintenance"], "Prune old state caches")["run"]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "caches.json").write_text(json.dumps(caches))
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CACHES": str(tmp_path / "caches.json"),
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_DELETED": str(tmp_path / "deleted.log"),
        "FAKE_FAIL": fail,
    }
    out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True)
    deleted_log = tmp_path / "deleted.log"
    deleted = deleted_log.read_text().split() if deleted_log.exists() else []
    return deleted, out.stdout, (tmp_path / "calls.log").read_text()


def _cache(i, key=None):
    # Higher i = newer. IDs run opposite to creation order so the test proves sorting is by createdAt.
    return {
        "id": 1000 - i,
        "key": key or f"jobscraper-state-{40000 + i}",
        "createdAt": f"2026-11-{i + 1:02d}T11:30:00Z",
    }


def test_prune_keeps_newest_five_state_caches(wf, tmp_path):
    caches = [_cache(i) for i in range(8)]
    caches.reverse()  # input order must not matter
    deleted, out, calls = _run_prune(wf, tmp_path, caches)
    assert sorted(deleted) == ["1000", "998", "999"]  # the 3 oldest
    assert "Pruned 3 old state cache(s); kept the newest 5." in out
    assert "--key jobscraper-state-" in calls


def test_prune_never_touches_other_caches(wf, tmp_path):
    caches = [_cache(i) for i in range(6)] + [_cache(i, key=f"codeql-overlay-{i}") for i in range(10, 20)]
    deleted, out, _ = _run_prune(wf, tmp_path, caches)
    assert deleted == ["1000"]  # only the oldest state cache
    assert "Pruned 1 " in out


@pytest.mark.parametrize("count", [0, 5])
def test_prune_with_five_or_fewer_deletes_nothing(wf, tmp_path, count):
    deleted, out, calls = _run_prune(wf, tmp_path, [_cache(i) for i in range(count)])
    assert deleted == []
    assert "cache delete" not in calls
    assert "Pruned 0 " in out


def test_prune_failed_delete_warns_and_continues(wf, tmp_path):
    deleted, out, _ = _run_prune(wf, tmp_path, [_cache(i) for i in range(7)], fail="1000")
    assert deleted == ["999"]
    assert "::warning::could not delete cache 1000" in out
    assert "Pruned 1 " in out
