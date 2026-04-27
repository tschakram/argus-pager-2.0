"""Analyser fan-out — calls into cyt + raypager scripts after capture.

This is intentionally a thin wrapper; the heavy logic lives in the submodules.
``run_all()`` returns the dict consumed by the report screen:

    {
        "threat_level": "clean" | "low" | "medium" | "high",
        "findings":     ["short bullet 1", ...],
        "report_path":  "/root/loot/argus/reports/<session>.md" | None,
    }
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PAYLOAD_DIR = Path(os.environ.get("ARGUS_PAYLOAD_DIR", Path(__file__).resolve().parents[2]))
CYT_PY      = PAYLOAD_DIR / "cyt"      / "python"
RAYPAGER_PY = PAYLOAD_DIR / "raypager" / "python"


def _run(cmd: list[str], *, timeout: int = 180) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 255, str(e)


def run_all(config: dict, preset: dict, *,
            pcaps: list[Path], bt_files: list[Path],
            gps_track: Path, report_dir: Path,
            session_id: str,
            deauth_summary: dict | None = None) -> dict:
    findings: list[str] = []
    threat = "clean"

    report_path: Path | None = None
    cfg_path = PAYLOAD_DIR / "config.json"

    # CYT writes `argus_report_<its-own-timestamp>.md` and that timestamp
    # never matches our session_id (it's the moment the CYT process
    # decided to write, not when the scan started). To still match the
    # report we just produced, we record the wall-clock at the start of
    # the analyser run and consider any .md modified at or after that
    # point a valid candidate.
    import time
    run_started = time.time() - 1   # 1s slop for clock skew

    # Deauth flood detection (always evaluated when WiFi was on)
    if preset.get("wifi") and deauth_summary:
        floods = int(deauth_summary.get("flood_count", 0))
        total  = int(deauth_summary.get("total", 0))
        if floods > 0:
            findings.append(
                f"DEAUTH FLOOD: {floods} bursts, {total} frames")
            threat = _max(threat, "high")
        elif total > 30:
            findings.append(f"deauth: elevated {total} frames")
            threat = _max(threat, "medium")
        elif total > 0:
            findings.append(f"deauth: {total} frames (background)")

    # ── CYT analysis (probe persistence + tracker fingerprint) ───────
    if (preset.get("wifi") or preset.get("bt")) and pcaps:
        rc, out = _run([
            sys.executable, str(CYT_PY / "analyze_pcap.py"),
            "--pcaps", ",".join(str(p) for p in pcaps),
            "--config", str(cfg_path),
            "--session", session_id,
        ], timeout=300)
        if rc == 0:
            findings.append(f"CYT analysis OK: {len(pcaps)} pcap(s)")
        else:
            findings.append("CYT analysis failed")
        if rc == 2:
            threat = _max(threat, "medium")

    # ── Hotel scan (cameras) ─────────────────────────────────────────
    if preset.get("cameras") and pcaps:
        rc, out = _run([
            sys.executable, str(CYT_PY / "hotel_scan.py"),
            "--pcap", ",".join(str(p) for p in pcaps),
            "--bt-scan", ",".join(str(b) for b in bt_files),
            "--config", str(cfg_path),
            "--session", session_id,
        ], timeout=300)
        if rc == 2:
            threat = _max(threat, "high")
            findings.append("hotel_scan: suspicious cameras found")

    # ── Camera-Activity (bandwidth spikes) ───────────────────────────
    if preset.get("cameras") and pcaps:
        rc, out = _run([
            sys.executable, str(CYT_PY / "camera_activity.py"),
            "--pcap", ",".join(str(p) for p in pcaps),
            "--threshold", "200",
        ], timeout=120)
        if "ACTIVITY:" in out:
            findings.append("camera activity spikes detected")
            threat = _max(threat, "medium")

    # ── Cross-Report (multi-round persistence) ───────────────────────
    if preset.get("cross_report"):
        rc, out = _run([
            sys.executable, str(CYT_PY / "cross_report.py"),
            "--hours", "4", "--min-reports", "2", "--min-distance", "200",
        ], timeout=120)
        if "n_crit" in out and "0" not in out.split("n_crit")[1][:6]:
            findings.append("cross-report flagged persistent devices")
            threat = _max(threat, "medium")

    # ── Surveillance analyser (KML + clusters) ───────────────────────
    if preset.get("wifi") and gps_track.exists():
        _run([sys.executable, str(CYT_PY / "surveillance_analyzer.py"),
              "--gps", str(gps_track), "--config", str(cfg_path)], timeout=90)

    # Locate the markdown report CYT just wrote. Strategy: any *.md
    # under report_dir whose mtime is >= run_started. Pick the newest.
    # Falls back to a session_id-substring match (older naming scheme)
    # so existing reports keep being discoverable for re-runs.
    fresh = []
    for p in report_dir.glob("*.md"):
        try:
            if p.stat().st_mtime >= run_started:
                fresh.append(p)
        except Exception:
            continue
    if fresh:
        report_path = max(fresh, key=lambda p: p.stat().st_mtime)
    else:
        legacy = sorted(report_dir.glob(f"*{session_id}*.md"))
        if legacy:
            report_path = legacy[-1]

    return {
        "threat_level": threat,
        "findings":     findings or ["no findings"],
        "report_path":  str(report_path) if report_path else None,
    }


_LEVELS = {"clean": 0, "low": 1, "medium": 2, "high": 3}


def _max(a: str, b: str) -> str:
    return a if _LEVELS.get(a, 0) >= _LEVELS.get(b, 0) else b
