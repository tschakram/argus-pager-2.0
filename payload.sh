#!/bin/bash
# argus-pager 2.0 — minimal launcher
# All UI/logic is in python/main.py (pagerctl-native).
# This script only sets up the environment and hands control to Python.
#
# IMPORTANT: We do NOT use `/etc/init.d/pineapplepager stop` because that
# init script also stops `pineapd`, which manages wlan0mon/wlan1mon. When
# pineapd dies, the wlan0cli interface to Mudi breaks → SSH dies → no
# remote recovery is possible without a hard reboot.
#
# Instead we SIGSTOP just the /pineapple/pineapple UI binary. pineapd keeps
# running (network stays up), pagerctl gets exclusive LCD access, and
# SIGCONT cleanly resumes the framework when we're done.

LOG_DIR=/root/loot/argus/logs
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/payload.$(date +%Y%m%d_%H%M%S).log"
ln -sf "$LOG_FILE" "$LOG_DIR/last.log"
exec >"$LOG_FILE" 2>&1
set -x
echo "=== argus-pager 2.0 launch $(date) ==="

# ── Locate real payload directory ───────────────────────────────────────
if [ -d "/root/payloads/user/reconnaissance/argus-pager-2.0" ]; then
    PAYLOAD_DIR="/root/payloads/user/reconnaissance/argus-pager-2.0"
elif [ -n "$PAYLOAD_PATH" ] && [ -d "$PAYLOAD_PATH" ]; then
    PAYLOAD_DIR="$PAYLOAD_PATH"
elif [ -d "$(dirname "$0")/python" ]; then
    PAYLOAD_DIR="$(cd "$(dirname "$0")" && pwd)"
else
    echo "FATAL: cannot locate payload directory."
    exit 1
fi
cd "$PAYLOAD_DIR"
echo "PAYLOAD_DIR=$PAYLOAD_DIR"

export PATH="/mmc/usr/bin:/mmc/usr/sbin:/mmc/bin:/mmc/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export LD_LIBRARY_PATH="/mmc/root/lib/pagerctl:/mmc/usr/lib:/mmc/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$PAYLOAD_DIR/python:/mmc/root/lib/pagerctl:${PYTHONPATH:-}"
export ARGUS_PAYLOAD_DIR="$PAYLOAD_DIR"

# ── Pre-flight ──────────────────────────────────────────────────────────
for bin in python3 tcpdump iw btmon; do
    command -v "$bin" >/dev/null 2>&1 || { echo "PRE-FLIGHT FAIL: missing $bin"; exit 1; }
done
[ -f /mmc/root/lib/pagerctl/pagerctl.py ] || { echo "PRE-FLIGHT FAIL: pagerctl missing"; exit 1; }
[ -f "$PAYLOAD_DIR/config.json" ] || cp "$PAYLOAD_DIR/config.example.json" "$PAYLOAD_DIR/config.json"

# ── Emergency-recovery script (in case Python hangs) ────────────────────
KILL_SCRIPT="$LOG_DIR/last_kill.sh"
cat > "$KILL_SCRIPT" << 'KILL_EOF'
#!/bin/sh
# Emergency: kill argus python, resume framework, no reboot needed.
echo "killing argus python…"
pkill -9 -f "python.*main.py" 2>/dev/null
pkill -9 -f "argus-pager-2.0/payload.sh" 2>/dev/null
pkill -9 -f "/tmp/payload-" 2>/dev/null
sleep 1
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
[ -n "$PINEAPPLE_PID" ] && kill -CONT "$PINEAPPLE_PID" 2>/dev/null
echo "framework resumed (PID $PINEAPPLE_PID)"
KILL_EOF
chmod +x "$KILL_SCRIPT"

LOG green "argus-pager 2.0 — starting" 2>/dev/null || true

# ── Pause framework UI binary (NOT pineapd!) ────────────────────────────
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
echo "pineapple-pid=$PINEAPPLE_PID"
if [ -n "$PINEAPPLE_PID" ]; then
    kill -STOP "$PINEAPPLE_PID"
    echo "framework UI paused (pineapd & wlan0mon still running)"
fi

# ── Always restore the framework on ANY exit ────────────────────────────
restore() {
    rc=$?
    echo "[trap rc=$rc] resuming framework UI…"
    if [ -n "$PINEAPPLE_PID" ]; then
        kill -CONT "$PINEAPPLE_PID" 2>/dev/null || true
    fi
    # Make sure framework is alive even if our STOP'd PID was dead
    sleep 1
    pgrep -f "/pineapple/pineapple" >/dev/null || /etc/init.d/pineapplepager start 2>/dev/null
}
trap restore EXIT INT TERM HUP

# ── Run python with a 30-min hard ceiling ───────────────────────────────
echo "→ python3 -u python/main.py"
timeout --signal=TERM --kill-after=10s 1800 \
    python3 -u "$PAYLOAD_DIR/python/main.py" "$@"
rc=$?
echo "python main.py exited with rc=$rc"
exit "$rc"
