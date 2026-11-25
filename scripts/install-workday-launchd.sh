#!/bin/bash
# Install (or reinstall) the launchd agent that runs scripts/workday-local.sh at 8:15 and 14:15 local time.
#   scripts/install-workday-launchd.sh            install / update and load
#   scripts/install-workday-launchd.sh uninstall  unload and remove
set -euo pipefail

LABEL="com.jobhuntinator.workday"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "uninstall" ]; then
	rm -f "$DEST"
	echo "removed $LABEL"
	exit 0
fi

mkdir -p "$REPO/state/workday" "$(dirname "$DEST")"
# Escape for sed replacement and XML (the repo path may contain spaces or &).
esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/[\\|&]/\\&/g'; }
sed -e "s|__SCRIPT__|$(esc "$REPO/scripts/workday-local.sh")|" \
	-e "s|__LOGDIR__|$(esc "$REPO/state/workday")|" \
	"$REPO/scripts/$LABEL.plist" >"$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $DEST"
echo "run now:     launchctl kickstart -p $DOMAIN/$LABEL"
echo "last ok:     cat '$REPO/state/workday/last-success'"
echo "log:         tail '$REPO/state/workday/run.log'"
