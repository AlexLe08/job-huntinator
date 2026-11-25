#!/usr/bin/env bash
# Prepares a fresh checkout (usually a git worktree under .claude/worktrees/)
# to run: its own .venv with the package installed editable plus the dev
# extras (pytest, respx, ruff), and the main checkout's .env, if it has
# one, so live dry-runs work in the worktree. The tests need neither .env
# nor network: they run offline against tests/fixtures/.
#
# Uses uv when it's installed (`uv sync --locked --extra dev`, as CI does),
# otherwise venv + pip. Safe to re-run; an existing .env in the worktree
# is left alone. state/ and data/ are not copied: the launchd Workday pass
# owns the main checkout's state, and a worktree should not touch it.
#
# The .env holds the sheet ID and key paths. It stays gitignored here too:
# never commit it, and never print it.
#
# Usage: scripts/setup-worktree.sh
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd -P)"
# The first entry of `git worktree list` is always the main checkout.
main_checkout="$(git -C "$root" worktree list --porcelain | head -n 1 | sed 's/^worktree //')"
cd "$root"

if command -v uv >/dev/null 2>&1; then
  echo "uv sync"
  uv sync --quiet --locked --extra dev
else
  echo "pip install -e .[dev]"
  [[ -x .venv/bin/python ]] || python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -e ".[dev]"
fi

if [[ "$root" != "$main_checkout" && -f "$main_checkout/.env" && ! -e "$root/.env" ]]; then
  cp "$main_checkout/.env" "$root/.env"
  echo "copied .env from the main checkout"
fi

echo "ready"
