#!/bin/bash
# argus-finder (BT) — Walking-Mode RSSI-Tracker fuer BT-Verdaechtige.
# Nutzt argus-pager-2.0 stack (pagerctl direct, kein DuckyScript-Builtin).

LOG_DIR=/root/loot/argus/logs
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/finder_bt.$(date +%Y%m%d_%H%M%S).log"
ln -sf "$LOG_FILE" "$LOG_DIR/finder_bt.last.log"
exec >"$LOG_FILE" 2>&1
set -x
echo "=== argus-finder (BT) launch $(date) ==="

# argus-pager-2.0 muss daneben liegen (Code wird wiederverwendet)
ARGUS_DIR="/root/payloads/user/reconnaissance/argus-pager-2.0"
if [ ! -d "$ARGUS_DIR/python/finder" ]; then
    echo "FATAL: $ARGUS_DIR/python/finder/ fehlt - argus-pager-2.0 deploy noetig."
    exit 1
fi
cd "$ARGUS_DIR"

export PATH="/mmc/usr/bin:/mmc/usr/sbin:/mmc/bin:/mmc/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export LD_LIBRARY_PATH="/mmc/root/lib/pagerctl:/mmc/usr/lib:/mmc/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$ARGUS_DIR/python:/mmc/root/lib/pagerctl:${PYTHONPATH:-}"
export ARGUS_PAYLOAD_DIR="$ARGUS_DIR"

for bin in python3 btmon; do
    command -v "$bin" >/dev/null 2>&1 || { echo "PRE-FLIGHT FAIL: missing $bin"; exit 1; }
done
[ -f /mmc/root/lib/pagerctl/pagerctl.py ] || { echo "PRE-FLIGHT FAIL: pagerctl missing"; exit 1; }

# Emergency-recovery script
KILL_SCRIPT="$LOG_DIR/finder_kill.sh"
cat > "$KILL_SCRIPT" << 'KILL_EOF'
#!/bin/sh
echo "killing finder python..."
pkill -9 -f "finder/main.py" 2>/dev/null
pkill -9 btmon 2>/dev/null
pkill -9 -f "argus-finder/payload.sh" 2>/dev/null
sleep 1
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
[ -n "$PINEAPPLE_PID" ] && kill -CONT "$PINEAPPLE_PID" 2>/dev/null
echo "framework resumed (PID $PINEAPPLE_PID)"
KILL_EOF
chmod +x "$KILL_SCRIPT"

# Pause framework UI (gleicher Ansatz wie argus-pager-2.0)
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
echo "pineapple-pid=$PINEAPPLE_PID"
if [ -n "$PINEAPPLE_PID" ]; then
    kill -STOP "$PINEAPPLE_PID"
fi

restore() {
    rc=$?
    echo "[trap rc=$rc] resuming framework UI..."
    if [ -n "$PINEAPPLE_PID" ]; then
        kill -CONT "$PINEAPPLE_PID" 2>/dev/null || true
    fi
    pkill btmon 2>/dev/null
    sleep 1
    pgrep -f "/pineapple/pineapple" >/dev/null || /etc/init.d/pineapplepager start 2>/dev/null
}
trap restore EXIT INT TERM HUP

echo "-> python3 -u python/finder/main.py --mode bt"
# 1h Hard-ceiling - Walking-Session sollte selten laenger gehen, Akku-Schutz
timeout --signal=TERM --kill-after=10s 3600 \
    python3 -u "$ARGUS_DIR/python/finder/main.py" --mode bt
rc=$?
echo "finder/main.py exited with rc=$rc"
exit "$rc"
