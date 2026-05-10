#!/bin/bash
# argus-finder-wifi — Walking-Mode RSSI-Tracker fuer WiFi-Probe-Verdaechtige.
# Nutzt argus-pager-2.0 stack (pagerctl direct, kein DuckyScript-Builtin).

LOG_DIR=/root/loot/argus/logs
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/finder_wifi.$(date +%Y%m%d_%H%M%S).log"
ln -sf "$LOG_FILE" "$LOG_DIR/finder_wifi.last.log"
exec >"$LOG_FILE" 2>&1
set -x
echo "=== argus-finder-wifi launch $(date) ==="

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

for bin in python3 tcpdump iw; do
    command -v "$bin" >/dev/null 2>&1 || { echo "PRE-FLIGHT FAIL: missing $bin"; exit 1; }
done
[ -f /mmc/root/lib/pagerctl/pagerctl.py ] || { echo "PRE-FLIGHT FAIL: pagerctl missing"; exit 1; }

# wlan1mon muss vorhanden sein (wird von Pineapple/argus angelegt)
if ! ip link show wlan1mon >/dev/null 2>&1; then
    echo "PRE-FLIGHT FAIL: wlan1mon nicht vorhanden. Erst Argus-Scan starten."
    # Wir lassen Python das selbst handhaben (zeigt Fehler-Card im LCD)
fi

KILL_SCRIPT="$LOG_DIR/finder_kill.sh"
cat > "$KILL_SCRIPT" << 'KILL_EOF'
#!/bin/sh
echo "killing finder python..."
pkill -9 -f "finder/main.py" 2>/dev/null
pkill -9 tcpdump 2>/dev/null
pkill -9 -f "argus-finder-wifi/payload.sh" 2>/dev/null
sleep 1
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
[ -n "$PINEAPPLE_PID" ] && kill -CONT "$PINEAPPLE_PID" 2>/dev/null
echo "framework resumed (PID $PINEAPPLE_PID)"
KILL_EOF
chmod +x "$KILL_SCRIPT"

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
    pkill tcpdump 2>/dev/null
    sleep 1
    pgrep -f "/pineapple/pineapple" >/dev/null || /etc/init.d/pineapplepager start 2>/dev/null
}
trap restore EXIT INT TERM HUP

echo "-> python3 -u python/finder/main.py --mode wifi"
timeout --signal=TERM --kill-after=10s 3600 \
    python3 -u "$ARGUS_DIR/python/finder/main.py" --mode wifi
rc=$?
echo "finder/main.py exited with rc=$rc"
exit "$rc"
