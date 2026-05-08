#!/bin/sh
# Wrapper for tools/screenshot.py - sets the PATH + LD_LIBRARY_PATH so
# python3 finds libpython3.11.so on the Pager's split /mmc layout.
#
# Usage from a remote SSH session:
#   ssh pager '/root/payloads/user/reconnaissance/argus-pager-2.0/tools/screenshot.sh /tmp/shot.png'
# Or with autonamed file:
#   ssh pager '/root/payloads/user/reconnaissance/argus-pager-2.0/tools/screenshot.sh'

set -e

export PATH="/mmc/usr/bin:/mmc/usr/sbin:/mmc/bin:/mmc/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export LD_LIBRARY_PATH="/mmc/usr/lib:/mmc/lib:${LD_LIBRARY_PATH:-}"

DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/screenshot.py" "$@"
