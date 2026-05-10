#!/bin/bash
# argus-probe - Aktiver Identifikations-Probe (BT-GATT, Network, mDNS, ...)
#
# WARNUNG: Probes sind aktiv - das Pager-Geraet wird vom Zielgeraet
# gesehen. NICHT fuer covert surveillance benutzen. Nur fuer:
# - Bestaetigung eines bereits gefundenen, lokalisierten Geraets
# - Eigene Geraete identifizieren
# - Forensik nach physischer Sicherstellung
#
# Optional aktiviert MAC-Randomisierung (bdaddr-Spoof) zur Anonymisierung.

LOG_DIR=/root/loot/argus/logs
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/probe.$(date +%Y%m%d_%H%M%S).log"
ln -sf "$LOG_FILE" "$LOG_DIR/probe.last.log"
exec >"$LOG_FILE" 2>&1
set -x
echo "=== argus-probe launch $(date) ==="

ARGUS_DIR="/root/payloads/user/reconnaissance/argus-pager-2.0"
if [ ! -d "$ARGUS_DIR/python/probe" ]; then
    echo "FATAL: $ARGUS_DIR/python/probe/ fehlt - argus-pager-2.0 deploy noetig."
    exit 1
fi
cd "$ARGUS_DIR"

export PATH="/mmc/usr/bin:/mmc/usr/sbin:/mmc/bin:/mmc/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export LD_LIBRARY_PATH="/mmc/root/lib/pagerctl:/mmc/usr/lib:/mmc/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$ARGUS_DIR/python:/mmc/root/lib/pagerctl:${PYTHONPATH:-}"
export ARGUS_PAYLOAD_DIR="$ARGUS_DIR"

# Pre-Flight
for bin in python3 gatttool bluetoothctl hciconfig; do
    command -v "$bin" >/dev/null 2>&1 || { echo "PRE-FLIGHT FAIL: missing $bin"; exit 1; }
done
[ -f /mmc/root/lib/pagerctl/pagerctl.py ] || { echo "PRE-FLIGHT FAIL: pagerctl missing"; exit 1; }

# Emergency-Recovery
KILL_SCRIPT="$LOG_DIR/probe_kill.sh"
cat > "$KILL_SCRIPT" << 'KILL_EOF'
#!/bin/sh
echo "killing probe python..."
pkill -9 -f "probe/main.py" 2>/dev/null
pkill -9 gatttool bluetoothctl 2>/dev/null
sleep 1
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
[ -n "$PINEAPPLE_PID" ] && kill -CONT "$PINEAPPLE_PID" 2>/dev/null
echo "framework resumed (PID $PINEAPPLE_PID)"
KILL_EOF
chmod +x "$KILL_SCRIPT"

# Pause framework UI
PINEAPPLE_PID=$(ps w | awk '/\/pineapple\/pineapple/ && !/awk/ {print $1; exit}')
echo "pineapple-pid=$PINEAPPLE_PID"
[ -n "$PINEAPPLE_PID" ] && kill -STOP "$PINEAPPLE_PID"

restore() {
    rc=$?
    echo "[trap rc=$rc] resuming framework UI..."
    [ -n "$PINEAPPLE_PID" ] && kill -CONT "$PINEAPPLE_PID" 2>/dev/null || true
    pkill gatttool bluetoothctl 2>/dev/null
    sleep 1
    pgrep -f "/pineapple/pineapple" >/dev/null || /etc/init.d/pineapplepager start 2>/dev/null
}
trap restore EXIT INT TERM HUP

echo "-> python3 -u python/probe/main.py"
timeout --signal=TERM --kill-after=10s 1800 \
    python3 -u "$ARGUS_DIR/python/probe/main.py"
rc=$?
echo "probe/main.py exited with rc=$rc"
exit "$rc"
