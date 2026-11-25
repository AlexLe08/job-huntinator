#!/bin/bash
# Workday-only scrape pass, run from this Mac by launchd (see scripts/install-workday-launchd.sh).
#
# Cloudflare rate-limits Workday from GitHub's datacenter IPs, so CI runs with --skip-ats workday and this
# script polls only the Workday boards from a home connection. It uses its own state file
# (state/workday/seen.json), reads credentials from the repo's .env, and appends to the same Scraper tab;
# the tracker dedupe (which includes the Scraper tab) keeps the two passes from adding the same job twice.
#
# On success it writes the current UTC time to state/workday/last-success. Output goes to
# state/workday/run.log (counts only, via --quiet). Extra arguments are passed to `jobscraper run`,
# e.g. `scripts/workday-local.sh --dry-run`.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$REPO/state/workday"
LOG="$STATE_DIR/run.log"
PY="$REPO/.venv/bin/python"

notify() {
	# Best effort: a desktop notification so a broken pass doesn't go unnoticed.
	osascript -e "display notification \"$1\" with title \"job-huntinator\"" >/dev/null 2>&1 || true
}

mkdir -p "$STATE_DIR" || exit 1
# Keep the log bounded.
if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 5000 ]; then
	tail -n 2000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') workday pass start"

if [ ! -x "$PY" ]; then
	echo "error: $PY not found (python3 -m venv .venv && .venv/bin/pip install -e .)"
	notify "Workday pass failed: no .venv"
	exit 1
fi

cd "$REPO" || exit 1
"$PY" -m jobscraper run --ats workday --quiet --explain --state "$STATE_DIR/seen.json" "$@"
rc=$?

if [ "$rc" -eq 0 ]; then
	date -u '+%Y-%m-%dT%H:%M:%SZ' >"$STATE_DIR/last-success"
	echo "=== ok"
else
	echo "=== failed (exit $rc)"
	notify "Workday pass failed (exit $rc); see state/workday/run.log"
fi
exit "$rc"
