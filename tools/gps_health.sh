#!/bin/sh
# gps_health.sh — Quick check ob der u-blox M8130 GPS-Stick am Mudi
# gerade fixed ist. Ohne Argus zu starten.
#
# Vom Pager:    /root/payloads/user/reconnaissance/argus-pager-2.0/tools/gps_health.sh
# Vom Laptop:   ssh pager '/root/payloads/.../tools/gps_health.sh'
#
# Output:
#   FIX OK     lat=54.84 lon=25.46 sats=8 hdop=1.2  - alles gruen
#   NO FIX     sats=0 (in_view=0)                    - Stick liefert NMEA aber kein Fix
#   NMEA STREAM ONLY                                  - Stick liefert nur Boot-Banner
#   STICK DEAD                                        - kein NMEA Output (kabel/usb?)

ssh mudi '
# 6 Sekunden NMEA capture
RAW=$(timeout 6 head -c 8000 /dev/ttyACM0 2>/dev/null | tr -d "\r")

if [ -z "$RAW" ]; then
    echo "STICK DEAD: kein NMEA-Output von /dev/ttyACM0"
    echo "Diagnose: usb-Kabel ab? Mudi-Reboot? ls -la /dev/ttyACM*"
    ls -la /dev/ttyACM* 2>&1 | head -3
    exit 2
fi

# GGA-Line mit fix-quality + sat-count
GGA=$(echo "$RAW" | grep -oE "GNGGA,[^*]+\*" | tail -1)
if [ -z "$GGA" ]; then
    echo "NMEA STREAM ONLY: nur Boot-Banner / GNTXT, kein GGA"
    echo "Diagnose: GPS-Stick startet noch (warte 10-30s)"
    exit 1
fi

# GNGGA Format: GNGGA,time,lat,N/S,lon,E/W,fix_quality,sats,hdop,...
FIX_Q=$(echo "$GGA" | awk -F, "{print \$7}")
SATS=$(echo "$GGA" | awk -F, "{print \$8}")
HDOP=$(echo "$GGA" | awk -F, "{print \$9}")

# GSV-View Sat-Count (in_view)
INVIEW=$(echo "$RAW" | grep -oE "G[PNB]GSV,[0-9]+,[0-9]+,[0-9]+" | tail -1 | awk -F, "{print \$4}")
INVIEW=${INVIEW:-0}

if [ "${FIX_Q:-0}" = "0" ] || [ -z "$FIX_Q" ]; then
    echo "NO FIX: sats_in_use=${SATS:-0} sats_in_view=$INVIEW"
    echo "Diagnose: Stick näher ans Fenster oder offen Bereich"
    exit 1
fi

# Lat/Lon dezimal (gps.py macht das, aber wir lassen es kurz)
LAT=$(echo "$GGA" | awk -F, "{print \$3}")
NS=$(echo "$GGA" | awk -F, "{print \$4}")
LON=$(echo "$GGA" | awk -F, "{print \$5}")
EW=$(echo "$GGA" | awk -F, "{print \$6}")

echo "FIX OK     fix_q=$FIX_Q sats_used=$SATS in_view=$INVIEW hdop=$HDOP"
echo "           raw: $LAT$NS / $LON$EW"
echo "           gps.py-Output:"
python3 /root/raypager/python/gps.py --timeout 5 2>&1 | sed "s/^/             /"
exit 0
'
