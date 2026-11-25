#!/usr/bin/env bash
# The checks CI runs (.github/workflows/tests.yml): ruff lint, ruff format,
# then the offline test suite. No network, .env or secrets needed. CI's
# pip-audit step is left out (it needs uv and the network).
# Prints one line per step; the full output of each goes to
# .logs/<step>.log, and a failing step also prints its last 30 lines.
# In a fresh worktree, run scripts/setup-worktree.sh first.
#
# Usage: scripts/check.sh
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
logs="$root/.logs"
bin="$root/.venv/bin"
cd "$root"

if [[ ! -x "$bin/pytest" || ! -x "$bin/ruff" ]]; then
  echo "no .venv with the dev extras here; run scripts/setup-worktree.sh first" >&2
  exit 2
fi
mkdir -p "$logs"
failed=0

# run <name> <command...>
run() {
  local name=$1
  shift
  local log="$logs/$name.log"
  if "$@" >"$log" 2>&1; then
    echo "pass  $name"
  else
    echo "FAIL  $name  (full log: .logs/$name.log)"
    tail -n 30 "$log"
    failed=1
  fi
}

run lint "$bin/ruff" check .
run format "$bin/ruff" format --check .
run test "$bin/pytest" -q

exit "$failed"
