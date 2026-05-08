#!/usr/bin/env python3
"""Recover analyser run when payload.sh got SIGKILLed mid-scan.

Usage:
    python3 tools/rerun_analyser.py <session_id>

Picks all <session_id>_r*.pcap and <session_id>_r*.bt.json from
/root/loot/argus/{pcap,pcap}/ and runs analyser.run_all() on them.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

PAYLOAD = Path("/root/payloads/user/reconnaissance/argus-pager-2.0")
sys.path.insert(0, str(PAYLOAD / "python"))

from core import analyser  # noqa: E402

LOOT       = Path("/root/loot/argus")
PCAP_DIR   = LOOT / "pcap"
REPORT_DIR = LOOT / "reports"
GPS_TRACK  = LOOT / "gps_track.csv"

def main(session_id: str) -> int:
    pcaps    = sorted(PCAP_DIR.glob(f"{session_id}_r*.pcap"))
    bt_files = sorted(PCAP_DIR.glob(f"{session_id}_r*.bt.json"))
    if not pcaps:
        print(f"no pcaps for session {session_id}", file=sys.stderr)
        return 1

    cfg = json.loads((PAYLOAD / "config.json").read_text())

    preset = {
        "_name":        "AUTO",
        "rounds":       0,
        "duration_s":   120,
        "wifi":         True,
        "bt":           True,
        "gps_mudi":     True,
        "cell":         True,
        "cross_report": True,
        "cameras":      False,
        "shodan":       False,
        "imsi_watch":   True,
        "sms_watch":    True,
    }

    scan_settings = {
        "preset_name":   "AUTO",
        "preset":        dict(preset),
        "iface":         "wlan1mon",
        "channels":      [],
        "session_id":    session_id,
        "hopper_errors": "",
        "recovery":      "post-SIGKILL re-run",
    }

    print(f"pcaps    : {len(pcaps)}")
    print(f"bt_files : {len(bt_files)}")
    print(f"gps_track: {GPS_TRACK} ({GPS_TRACK.stat().st_size}B)")
    print(f"-> analyser.run_all() ...")

    res = analyser.run_all(
        cfg, preset,
        pcaps=pcaps, bt_files=bt_files,
        gps_track=GPS_TRACK,
        report_dir=REPORT_DIR,
        session_id=session_id,
        deauth_summary=None,
        scan_settings=scan_settings,
        wifi_probes={},
    )
    print("result:", json.dumps(res, indent=2, default=str))
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
