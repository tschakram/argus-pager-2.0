#!/bin/sh
# Pull the most recent ARGUS auto-screenshot session off the pager.
# Run this from your laptop, after a payload run with ARGUS_SCREENSHOTS=1.
#
# Usage:
#   tools/pull_screenshots.sh                       # pull to ./screenshots-pulled/
#   tools/pull_screenshots.sh /path/to/dest         # pull to /path/to/dest/

set -e

DEST="${1:-./screenshots-pulled}"
SSH_HOST="${PAGER_SSH:-pager}"

LATEST=$(ssh "$SSH_HOST" 'ls -1dt /root/loot/argus/screenshots/* 2>/dev/null | head -1')
if [ -z "$LATEST" ]; then
    echo "no screenshot session found on the pager." >&2
    exit 1
fi

echo "pulling $LATEST -> $DEST/$(basename "$LATEST")/"
mkdir -p "$DEST"
scp -r "$SSH_HOST:$LATEST" "$DEST/"
echo
echo "pulled: $(ls -1 "$DEST/$(basename "$LATEST")" | wc -l) files"
ls -la "$DEST/$(basename "$LATEST")" | head -20
