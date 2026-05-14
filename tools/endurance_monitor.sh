#!/bin/sh
# endurance_monitor.sh — passive Beobachter waehrend langer Argus-Runs.
#
# Loggt alle 60s nach /root/loot/argus/logs/endurance.<ts>.log:
#   - load average + free memory
#   - aktuelle disk usage von /mmc und /root/loot
#   - Anzahl PCAPs + BT-JSONs in der laufenden Session
#   - Status of pinneapple/python/tcpdump processes
#
# Greift NICHT in Argus ein - nur Read-Only-Observation.
# Auf Pager im Hintergrund starten:
#   nohup /root/payloads/user/reconnaissance/argus-pager-2.0/tools/endurance_monitor.sh &
#
# Stoppen:
#   pkill -f endurance_monitor.sh

LOG_DIR=/root/loot/argus/logs
TS=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/endurance.$TS.log"
INTERVAL=${1:-60}   # default every 60s, override with arg

mkdir -p "$LOG_DIR"
echo "endurance monitor pid=$$ ts=$TS interval=${INTERVAL}s" > "$LOG"
echo "format: HH:MM | load | freeMB | availMB | mmcFree | argusMB | pcaps | bt | pythonRSS | argusPyAlive"  >> "$LOG"
echo "----------------------------------------------------------------------" >> "$LOG"

while true; do
    NOW=$(date +%H:%M)
    LOAD=$(awk "{print \$1}" /proc/loadavg)
    FREE=$(awk "/^MemFree:/{print int(\$2/1024)}" /proc/meminfo)
    AVAIL=$(awk "/^MemAvailable:/{print int(\$2/1024)}" /proc/meminfo)
    MMC=$(df -m /mmc 2>/dev/null | awk "NR==2{print \$4}")
    ARGUS=$(du -sm /root/loot/argus 2>/dev/null | awk "{print \$1}")
    PCAPS=$(ls /root/loot/argus/pcap/scan_*.pcap 2>/dev/null | wc -l)
    BTS=$(ls /root/loot/argus/bt_*.json 2>/dev/null | wc -l)
    # main.py Python-Prozess RSS in MB
    PYRSS=$(ps w 2>/dev/null | awk "/python.*main\.py/ && !/awk/ {printf \"%d\", \$3/1024}" | head -1)
    [ -z "$PYRSS" ] && PYRSS="-"
    # alive marker
    ALIVE=$(pgrep -f "python.*main.py" >/dev/null 2>&1 && echo Y || echo N)

    printf "%s | load=%s | free=%sMB | avail=%sMB | mmcFree=%sMB | argus=%sMB | pcaps=%s | bt=%s | pyRSS=%sMB | alive=%s\n" \
        "$NOW" "$LOAD" "$FREE" "$AVAIL" "$MMC" "$ARGUS" "$PCAPS" "$BTS" "$PYRSS" "$ALIVE" >> "$LOG"

    sleep "$INTERVAL"
done
