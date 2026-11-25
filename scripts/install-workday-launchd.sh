#!/bin/bash
# Install (or reinstall) the launchd agent that runs scripts/workday-local.sh at 8:15 and 14:15 local time.
#   scripts/install-workday-launchd.sh            install / update and load
#   scripts/install-workday-launchd.sh uninstall  unload and remove
set -euo pipefail

LABEL="com.jobhuntinator.workday"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

LOGFILE="$HOME/Library/Logs/jobhuntinator-workday.log"

if [ "${1:-}" = "uninstall" ]; then
	launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
	rm -f "$DEST"
	echo "removed $LABEL"
	exit 0
fi

# macOS privacy controls (TCC) stop launchd jobs from reading these locations, and a background job can't show the
# "allow access" prompt, so the run would fail with "Operation not permitted" (exit 126, or 78 before it even starts).
case "$REPO" in
/Volumes/* | "$HOME"/Documents/* | "$HOME"/Desktop/* | "$HOME"/Downloads/* | "$HOME"/Library/Mobile\ Documents/*)
	echo "error: $REPO is in a location macOS blocks for background jobs (external drive, Documents, Desktop," >&2
	echo "Downloads or iCloud Drive). Clone the repo somewhere like ~/Developer and install from there." >&2
	exit 1
	;;
esac

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
mkdir -p "$REPO/state/workday" "$(dirname "$DEST")" "$(dirname "$LOGFILE")"
# Escape for sed replacement and XML (the repo path may contain spaces or &).
esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/[\\|&]/\\&/g'; }
sed -e "s|__SCRIPT__|$(esc "$REPO/scripts/workday-local.sh")|" \
	-e "s|__LOGFILE__|$(esc "$LOGFILE")|" \
	"$REPO/scripts/$LABEL.plist" >"$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $DEST"
echo "run now:     launchctl kickstart -p $DOMAIN/$LABEL"
echo "last ok:     cat '$REPO/state/workday/last-success'"
echo "log:         tail '$REPO/state/workday/run.log'"
echo "launch errs: tail '$LOGFILE'"
