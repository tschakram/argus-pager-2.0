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

import json
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
            deauth_summary: dict | None = None,
            scan_settings: dict | None = None,
            wifi_probes: dict | None = None) -> dict:
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

    # CYT analysis (probe persistence + tracker fingerprint).
    # Real CLI from cyt/python/analyze_pcap.py --help:
    #   --pcaps PCAPS  --config CONFIG  --output-dir DIR
    #   --threshold N  --min-appearances N  --bt-scans CSV
    # NB: there is no --session flag. The script writes
    # `argus_report_<its-own-now>.md` into --output-dir.
    if (preset.get("wifi") or preset.get("bt")) and pcaps:
        cmd = [
            sys.executable, str(CYT_PY / "analyze_pcap.py"),
            "--pcaps",      ",".join(str(p) for p in pcaps),
            "--config",     str(cfg_path),
            "--output-dir", str(report_dir),
        ]
        if bt_files:
            cmd += ["--bt-scans", ",".join(str(b) for b in bt_files)]
        rc, out = _run(cmd, timeout=300)
        if rc == 0:
            findings.append(f"CYT analysis OK: {len(pcaps)} pcap(s)")
        elif rc == 2:
            # cyt convention: rc=2 means suspicious devices found, not error
            findings.append(f"CYT analysis: suspects found ({len(pcaps)} pcap(s))")
            threat = _max(threat, "medium")
        else:
            findings.append(f"CYT analysis failed (rc={rc})")
            print(f"[analyser] analyze_pcap rc={rc}, last output:",
                  file=sys.stderr)
            print(out[-500:], file=sys.stderr)

    # Hotel scan (cameras).
    # Real CLI: --pcap CSV  --bt-scan PATH|"live"  --bt-duration N
    #           --output-dir DIR
    # No --config / --session.
    if preset.get("cameras") and pcaps:
        cmd = [
            sys.executable, str(CYT_PY / "hotel_scan.py"),
            "--pcap",       ",".join(str(p) for p in pcaps),
            "--output-dir", str(report_dir),
        ]
        if bt_files:
            cmd += ["--bt-scan", ",".join(str(b) for b in bt_files)]
        rc, out = _run(cmd, timeout=300)
        if rc == 2:
            threat = _max(threat, "high")
            findings.append("hotel_scan: suspicious cameras found")
        elif rc != 0:
            print(f"[analyser] hotel_scan rc={rc}: {out[-300:]}",
                  file=sys.stderr)

    # Camera-Activity (bandwidth spikes).
    # Real CLI: --pcap CSV  --suspects JSON  --threshold N  --output-dir DIR
    if preset.get("cameras") and pcaps:
        rc, out = _run([
            sys.executable, str(CYT_PY / "camera_activity.py"),
            "--pcap",       ",".join(str(p) for p in pcaps),
            "--threshold",  "200",
            "--output-dir", str(report_dir),
        ], timeout=120)
        if "ACTIVITY:" in out:
            findings.append("camera activity spikes detected")
            threat = _max(threat, "medium")

    # Cross-Report (multi-round persistence).
    # Real CLI: --report-dir DIR  --gps-track PATH  --hours N
    #           --min-reports N  --min-distance M  --output PATH
    if preset.get("cross_report"):
        cross_out = report_dir / f"cross_report_{session_id}.md"
        cmd = [
            sys.executable, str(CYT_PY / "cross_report.py"),
            "--report-dir",   str(report_dir),
            "--hours",        "4",
            "--min-reports",  "2",
            "--min-distance", "200",
            "--output",       str(cross_out),
        ]
        if gps_track.exists():
            cmd += ["--gps-track", str(gps_track)]
        rc, out = _run(cmd, timeout=120)
        if "n_crit" in out and "0" not in out.split("n_crit")[1][:6]:
            findings.append("cross-report flagged persistent devices")
            threat = _max(threat, "medium")

    # Surveillance analyser is intentionally skipped here - its real CLI
    # wants --kismet-db, which we don't produce in this pipeline. Probe-
    # persistence stalking is already covered by analyze_pcap.py +
    # cross_report.py above.

    # Locate the markdown report CYT just wrote. We deliberately pick from
    # argus_report_*.md only — cross_report_*.md is also written during this
    # run (later, so mtime-newer) but is a stub when fewer than 2 reports
    # exist in the time window. Showing that stub on the device hid the real
    # findings behind "Mindestens 2 Reports nötig".
    fresh = []
    for p in report_dir.glob("argus_report_*.md"):
        try:
            if p.stat().st_mtime >= run_started:
                fresh.append(p)
        except Exception:
            continue
    if fresh:
        report_path = max(fresh, key=lambda p: p.stat().st_mtime)
    else:
        legacy = sorted(report_dir.glob(f"argus_report_*{session_id}*.md"))
        if legacy:
            report_path = legacy[-1]

    # WiFi <-> BT pairing DB: per-session correlation of probe-MACs with
    # BT devices. Persistent across scans so a randomising stalker can
    # be tracked through their stable BT-anchor.
    pairing_summary = None
    if report_path is not None and wifi_probes is not None and bt_files:
        try:
            from . import pairing
            pairings_path = Path(
                ((config.get("paths") or {}).get("pairings"))
                or (Path(report_dir).parent / "pairings.json")
            )
            # bt_scanner ran with --duration matching scan_engine's
            # bt_dur computation; mirror it here so the pairing window
            # matches the actual capture window.
            round_dur = int(preset.get("duration_s", 120))
            bt_scan_duration_s = max(15, round_dur - 25)
            pairing_summary = pairing.update(
                pairing_path=pairings_path,
                session_id=session_id,
                bt_files=bt_files,
                wifi_probes=wifi_probes,
                bt_scan_duration_s=bt_scan_duration_s,
            )
            block = pairing.render_report_block(pairing_summary)
            if block:
                with report_path.open("a", encoding="utf-8") as f:
                    f.write("\n")
                    f.write(block)
            if pairing_summary.get("established"):
                findings.append(
                    f"WiFi/BT pairing: {len(pairing_summary['established'])} "
                    f"stable device(s)")
                threat = _max(threat, "medium")
        except Exception as e:
            print(f"[analyser] pairing-DB update failed: {e}",
                  file=sys.stderr)

    # External intel (InternetDB / Shodan / Fingerbank) - always-on.
    if report_path is not None:
        try:
            from . import external_intel
            pairings_path = Path(
                ((config.get("paths") or {}).get("pairings"))
                or (Path(report_dir).parent / "pairings.json")
            )
            ext = external_intel.run(
                config=config,
                pcaps=pcaps,
                bt_files=bt_files,
                pairings_path=pairings_path,
                session_id=session_id,
            )
            if ext.get("report_block"):
                with report_path.open("a", encoding="utf-8") as f:
                    f.write("\n")
                    f.write(ext["report_block"])
            for f_ in ext.get("findings") or []:
                findings.append(f_)
            if ext.get("threat_bump"):
                threat = _max(threat, ext["threat_bump"])
        except Exception as e:
            print(f"[analyser] external_intel failed: {e}",
                  file=sys.stderr)

    # Cellular & catcher block (cell tower OpenCelliD lookup + IMSI alerts
    # + silent-SMS hits from the Mudi watchers). All gated by reachability —
    # if Mudi is offline the block is silently skipped. The three Mudi
    # round-trips (each ~5-20s SSH-mux) are run in parallel because they
    # are independent; sequential they were ~30-40s of finish() time.
    if report_path is not None and (preset.get("cell")
                                    or preset.get("imsi_watch")
                                    or preset.get("sms_watch")):
        try:
            from concurrent.futures import ThreadPoolExecutor
            from . import mudi_client
            with ThreadPoolExecutor(max_workers=3) as ex:
                f_cell = ex.submit(
                    lambda: (mudi_client.cell_lookup(config)
                             or mudi_client.cell_info(config))
                ) if preset.get("cell") else None
                f_imsi = ex.submit(
                    mudi_client.imsi_alerts_recent, config, hours=2
                ) if preset.get("imsi_watch") else None
                f_sms = ex.submit(
                    mudi_client.silent_sms_recent, config, hours=24
                ) if preset.get("sms_watch") else None
                cell        = f_cell.result()  if f_cell else None
                imsi_alerts = f_imsi.result()  if f_imsi else []
                silent_sms  = f_sms.result()   if f_sms  else []
            block = _render_cellular_block(cell, imsi_alerts, silent_sms)
            if block:
                with report_path.open("a", encoding="utf-8") as f:
                    f.write("\n")
                    f.write(block)
            if cell:
                # opencellid.py emits ``threat`` (int 0..3) + ``threat_label``;
                # legacy cell_info had ``threat`` as str. Normalise both.
                tlab = cell.get("threat_label")
                if tlab is None:
                    tval = cell.get("threat") or cell.get("opencellid_threat")
                    tlab = tval if isinstance(tval, str) else None
                tlab = (tlab or "").upper()
                if tlab in ("MISMATCH", "GHOST"):
                    findings.append(f"cell tower: {tlab}")
                    threat = _max(threat, "high")
                elif tlab == "UNKNOWN":
                    findings.append("cell tower not in OpenCelliD")
                    threat = _max(threat, "medium")
            if imsi_alerts:
                findings.append(f"IMSI alerts (2h): {len(imsi_alerts)}")
                threat = _max(threat, "medium")
            if silent_sms:
                findings.append(f"silent-SMS hits (24h): {len(silent_sms)}")
                threat = _max(threat, "high")
        except Exception as e:
            print(f"[analyser] cellular block failed: {e}",
                  file=sys.stderr)

    # Forensic incidents: list any deauth_*.json archived during this run.
    incident_count = 0
    if report_path is not None:
        try:
            incidents_dir = Path(report_dir).parent / "incidents"
            incidents = _collect_session_incidents(incidents_dir, run_started)
            incident_count = len(incidents)
            block = _render_incidents_block(incidents)
            if block:
                with report_path.open("a", encoding="utf-8") as f:
                    f.write("\n")
                    f.write(block)
            if incident_count > 0:
                findings.append(f"deauth incidents archived: {incident_count}")
                threat = _max(threat, "high")
        except Exception as e:
            print(f"[analyser] incidents block failed: {e}",
                  file=sys.stderr)

    # Headers prepend in REVERSE order so the final document reads:
    #   <threat summary>  <scan settings>  <cyt body>  <pairing>  <incidents>
    if report_path is not None and scan_settings:
        try:
            _prepend_settings_header(report_path, scan_settings, len(pcaps),
                                     len(bt_files))
        except Exception as e:
            print(f"[analyser] could not prepend settings: {e}",
                  file=sys.stderr)

    # Collapse the long "Ignorierte Geräte" list into <details> so the
    # default report view stays focused on actual findings.
    if report_path is not None:
        try:
            _collapse_ignored_block(report_path)
        except Exception as e:
            print(f"[analyser] could not collapse ignored block: {e}",
                  file=sys.stderr)

    if report_path is not None:
        try:
            _prepend_threat_summary(
                report_path,
                threat=threat,
                findings=findings,
                session_id=session_id,
                pairing_summary=pairing_summary,
                incident_count=incident_count,
                bt_count=len(bt_files),
                pcap_count=len(pcaps),
            )
        except Exception as e:
            print(f"[analyser] could not prepend threat summary: {e}",
                  file=sys.stderr)

    return {
        "threat_level":    threat,
        "findings":        findings or ["no findings"],
        "report_path":     str(report_path) if report_path else None,
        "pairing_summary": pairing_summary,
        "incident_count":  incident_count,
    }


def _render_cellular_block(cell: dict | None,
                           imsi_alerts: list[dict],
                           silent_sms: list[dict]) -> str:
    """Cellular tower / IMSI / silent-SMS section."""
    lines: list[str] = []
    lines.append("## Cellular & Catcher")
    lines.append("")
    if cell:
        # opencellid.py uses int threat + threat_label; cell_info uses str.
        threat_s = (cell.get("threat_label")
                    or cell.get("threat")
                    or cell.get("opencellid_threat") or "—")
        if isinstance(threat_s, int):
            threat_s = ["CLEAN", "UNKNOWN", "MISMATCH", "GHOST"][threat_s] \
                if 0 <= threat_s <= 3 else str(threat_s)
        mcc = cell.get("mcc", "?")
        mnc = cell.get("mnc", "?")
        cid = cell.get("cell_id", cell.get("cid", "?"))
        tac = cell.get("tac", cell.get("lac", "?"))
        rat = cell.get("rat", cell.get("radio", "?"))
        rssi = cell.get("rssi", cell.get("signal", "—"))
        lines.append(
            f"- **Tower:** MCC={mcc} MNC={mnc} CID={cid} TAC={tac} "
            f"RAT={rat} RSSI={rssi}")
        lines.append(f"- **OpenCelliD:** `{threat_s}`")
        if cell.get("operator"):
            lines.append(f"- **Operator:** {cell['operator']}")
    else:
        lines.append("- _No live cell info (Mudi unreachable or `cell` "
                     "preset off)._")
    lines.append("")
    if imsi_alerts:
        lines.append(f"### IMSI alerts (last 2h, {len(imsi_alerts)})")
        for a in imsi_alerts[:8]:
            kind = a.get("type") or a.get("kind") or "?"
            ts   = a.get("ts") or a.get("time") or ""
            note = a.get("note") or a.get("detail") or ""
            lines.append(f"- `{kind}` {ts} {note}")
        if len(imsi_alerts) > 8:
            lines.append(f"- ... ({len(imsi_alerts)-8} more)")
        lines.append("")
    if silent_sms:
        lines.append(f"### Silent-SMS hits (last 24h, {len(silent_sms)})")
        for s in silent_sms[:8]:
            kind = s.get("type") or s.get("kind") or "silent"
            ts   = s.get("ts") or s.get("time") or ""
            src  = s.get("src") or s.get("from") or "?"
            lines.append(f"- `{kind}` {ts} from `{src}`")
        if len(silent_sms) > 8:
            lines.append(f"- ... ({len(silent_sms)-8} more)")
        lines.append("")
    return "\n".join(lines)


def _prepend_settings_header(report: Path, settings: dict,
                             n_pcaps: int, n_bt: int) -> None:
    """Write a Scan-Settings block at the top of the report .md file."""
    p     = settings.get("preset") or {}
    chans = settings.get("channels") or {}
    name  = settings.get("preset_name") or p.get("_name") or "?"
    iface = settings.get("iface") or "?"
    sid   = settings.get("session_id") or ""

    # Foreground sensors that show up in the report header. imsi_watch /
    # sms_watch are Mudi background daemons, not foreground sensors, and
    # only relevant when Mudi is actually engaged (cell or gps_mudi); we
    # surface them in a separate line below.
    UI_SENSORS = ("wifi", "bt", "gps_mudi", "cell",
                  "cross_report", "cameras", "shodan")
    sensors = [k for k in UI_SENSORS if p.get(k)]
    sensors_str = ", ".join(sensors) if sensors else "(none)"

    mudi_engaged = bool(p.get("cell") or p.get("gps_mudi"))
    mudi_daemons = []
    if mudi_engaged:
        for k in ("imsi_watch", "sms_watch"):
            if p.get(k):
                mudi_daemons.append(k)

    rounds   = p.get("rounds")
    duration = p.get("duration_s")

    lines = [
        "# Scan-Settings",
        "",
        f"- **Session:** `{sid}`",
        f"- **Preset:** `{name}`",
        f"- **Sensors:** {sensors_str}",
        f"- **Rounds x Duration:** {rounds} x {duration}s",
        f"- **Capture iface:** `{iface}`",
        f"- **PCAPs:** {n_pcaps}    **BT-files:** {n_bt}",
    ]
    if mudi_engaged and mudi_daemons:
        lines.append(f"- **Mudi background watchers:** {', '.join(mudi_daemons)}")
    f24 = chans.get("2.4") or []
    f5  = chans.get("5")   or []
    f6  = chans.get("6")   or []
    if f24 or f5 or f6:
        lines += [
            f"- **2.4 GHz** ({len(f24)} freqs): "
            + (", ".join(str(x) for x in f24) if f24 else "-"),
            f"- **5 GHz** ({len(f5)} freqs incl. DFS): "
            + (", ".join(str(x) for x in f5) if f5 else "-"),
            f"- **6 GHz** ({len(f6)} PSC freqs): "
            + (", ".join(str(x) for x in f6) if f6 else "-"),
        ]
    err = (settings.get("hopper_errors") or "").strip()
    if err:
        lines += ["",
                  "<details><summary>Channel-Hopper errors</summary>",
                  "",
                  "```",
                  err,
                  "```",
                  "</details>"]
    lines += ["", "---", ""]

    header = "\n".join(lines)
    body   = report.read_text(encoding="utf-8")
    report.write_text(header + body, encoding="utf-8")


_LEVELS = {"clean": 0, "low": 1, "medium": 2, "high": 3}


def _max(a: str, b: str) -> str:
    return a if _LEVELS.get(a, 0) >= _LEVELS.get(b, 0) else b


# ── Threat summary (prepended after settings, ends up at top) ───────────

_THREAT_BANNER = {
    "clean":  ("CLEAN",       "no immediate threat"),
    "low":    ("LOW",         "background activity"),
    "medium": ("MEDIUM",      "review suspicious findings"),
    "high":   ("HIGH",        "urgent attention required"),
}


def _prepend_threat_summary(report: Path, *, threat: str, findings: list[str],
                            session_id: str, pairing_summary: dict | None,
                            incident_count: int, bt_count: int,
                            pcap_count: int) -> None:
    """Top-of-report dashboard. Auto-mode users want the verdict first;
    Scan-Settings + cyt body follow below."""
    banner, hint = _THREAT_BANNER.get(threat, ("UNKNOWN", ""))
    lines = [
        "# Argus Auto-Report",
        "",
        f"**Threat: {banner}** - {hint}",
        f"**Session:** `{session_id}`",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| WiFi PCAPs            | {pcap_count} |",
        f"| BT JSON files         | {bt_count} |",
        f"| Deauth incidents      | {incident_count} |",
    ]
    if pairing_summary:
        est = len(pairing_summary.get("established") or [])
        new = len(pairing_summary.get("new_pairs") or [])
        bt_seen = int(pairing_summary.get("bt_seen", 0))
        wifi_seen = int(pairing_summary.get("wifi_seen", 0))
        lines.append(f"| BT devices (this session) | {bt_seen} |")
        lines.append(f"| WiFi probe MACs           | {wifi_seen} |")
        lines.append(f"| Pairing - established     | {est} |")
        lines.append(f"| Pairing - new pairs       | {new} |")
    lines.append("")
    if findings:
        lines.append("### Findings")
        lines.append("")
        for f in findings[:6]:
            lines.append(f"- {f}")
        if len(findings) > 6:
            lines.append(f"- ... ({len(findings) - 6} more)")
        lines.append("")
    lines += ["---", ""]
    header = "\n".join(lines)
    body = report.read_text(encoding="utf-8")
    report.write_text(header + body, encoding="utf-8")


# ── Forensic incidents block (appended after pairing) ───────────────────

def _collect_session_incidents(incidents_dir: Path, since_ts: float) -> list[dict]:
    """Return deauth_*.json metadata files written during this scan."""
    if not incidents_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(incidents_dir.glob("deauth_*.json")):
        try:
            if p.stat().st_mtime < since_ts:
                continue
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _collapse_ignored_block(report: Path) -> None:
    """Wrap '## Ignorierte Geräte' + its bullet list in <details>.

    cyt always emits the full ignore-list (often 40+ MACs) inline; on the
    pager screen and in shared reports that's noise. The collapse keeps
    the data for forensic/debug purposes but hides it by default.
    """
    text = report.read_text(encoding="utf-8")
    marker = "## Ignorierte Geräte"
    idx = text.find(marker)
    if idx < 0:
        return
    # Find end of the block: next top-level "## " heading, or EOF.
    after = idx + len(marker)
    next_h = text.find("\n## ", after)
    end = next_h if next_h >= 0 else len(text)
    block = text[idx:end].rstrip() + "\n"
    bullets = [l for l in block.splitlines() if l.startswith("- ")]
    n = len(bullets)
    new_block = (
        f"<details><summary>Ignorierte Geraete ({n})</summary>\n\n"
        + block
        + "\n</details>\n\n"
    )
    report.write_text(text[:idx] + new_block + text[end:], encoding="utf-8")


def _render_incidents_block(incidents: list[dict]) -> str:
    if not incidents:
        return ""
    lines = ["", "## Forensic Incidents (Deauth Floods)", ""]
    lines.append("Diese PCAP- und Metadaten-Dateien sind in "
                 "`/root/loot/argus/incidents/` archiviert und werden "
                 "**nicht** durch spätere Scans überschrieben - relevant "
                 "für eine Anzeige bei der Polizei.")
    lines += ["", "| UTC | Source | Target | Rate/s | Window | GPS |",
              "|---|---|---|---|---|---|"]
    for inc in incidents:
        lines.append(
            f"| {inc.get('ts_utc','?')} | "
            f"`{inc.get('src_mac','?')}` | `{inc.get('target_mac','?')}` | "
            f"{inc.get('rate_per_s','?')} | "
            f"{inc.get('window_s','?')}s | "
            f"{inc.get('gps','?')} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


