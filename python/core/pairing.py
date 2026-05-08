"""WiFi <-> BT pairing database.

Hypothesis: a stalker's WiFi MAC randomises (per-burst privacy MAC on iOS /
Android), but their BT MAC is much more stable (BT Classic public address,
many BLE peripherals use a fixed public MAC). If a WiFi probe-MAC and a
BT-device co-occur during the same scan session AND in the same time
window, they are *candidate-paired*. Across multiple sessions, the BT-MAC
stays the same while WiFi-MACs rotate - but a tracker that follows the
user will keep showing up, and we can collect the WiFi-MACs it cycles
through underneath one stable BT-anchor.

Time-aware correlation: each per-round bt_scanner JSON carries a
``timestamp`` (end of the BT scan). Together with the bt-scanner
``--duration`` we infer the round's time window. A WiFi probe-MAC
attaches to a BT-MAC only if the probe's [first_ts, last_ts] overlaps
that window. This filters out the trivial false positives where a
single probe-MAC seen for one second 80s after the BT-scan ended would
otherwise be attributed to that BT device.

Persistence: ``<base>/pairings.json``. Schema::

    {
      "<bt_mac>": {
        "first_seen":   "2026-05-01T10:15:00",
        "last_seen":    "2026-05-01T18:30:00",
        "vendor":       "Samsung Electronics ...",
        "device_type":  "BLE Tracker (SmartTag)",
        "risk":         "high",
        "co_sightings": 3,
        "wifi_macs": {
            "aa:bb:cc:dd:ee:01": {"count": 2, "last_seen": "..."},
            "aa:bb:cc:dd:ee:02": {"count": 1, "last_seen": "..."}
        },
        "sessions":     ["20260501_101500", "20260501_173000", ...]
      }
    }

The DB is updated by ``update(...)`` at scan finish-time. The function
returns a list of "fresh hits" (BT-MACs with new WiFi MACs in this session
or co_sightings reaching a threshold) so the analyser can surface them
in a dedicated report block.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

# Co-sightings threshold to call a pairing "established" rather than "candidate".
ESTABLISHED_MIN = 3

# Retention: BT records (and WiFi sub-records) older than this are dropped.
# Established pairings (>= ESTABLISHED_MIN sessions) get a longer grace
# period so we don't lose the long-tail surveillance evidence too eagerly.
PRUNE_DAYS_DEFAULT     = 90
PRUNE_DAYS_ESTABLISHED = 365


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def prune(db: dict, *, now: datetime | None = None,
          ttl_days: int = PRUNE_DAYS_DEFAULT,
          ttl_days_established: int = PRUNE_DAYS_ESTABLISHED) -> dict:
    """Drop stale BT records + WiFi sub-records.

    Returns a stats dict ``{"bt_dropped": n, "wifi_dropped": n, "kept": n}``.
    Mutates ``db`` in place.
    """
    now = now or datetime.utcnow()
    cutoff_short = now - timedelta(days=ttl_days)
    cutoff_long  = now - timedelta(days=ttl_days_established)
    bt_drop = 0
    wifi_drop = 0
    kept = 0
    for bt_mac in list(db.keys()):
        rec = db[bt_mac]
        last = _parse_iso(rec.get("last_seen", ""))
        is_established = int(rec.get("co_sightings", 0)) >= ESTABLISHED_MIN
        cutoff = cutoff_long if is_established else cutoff_short
        if last is not None and last < cutoff:
            del db[bt_mac]
            bt_drop += 1
            continue
        # prune individual stale wifi sub-records
        wifis = rec.get("wifi_macs") or {}
        for wmac in list(wifis.keys()):
            wlast = _parse_iso((wifis[wmac] or {}).get("last_seen", ""))
            if wlast is not None and wlast < cutoff_short:
                del wifis[wmac]
                wifi_drop += 1
        kept += 1
    return {"bt_dropped": bt_drop, "wifi_dropped": wifi_drop, "kept": kept}


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _bt_rounds_from_files(bt_files: list[Path], bt_scan_duration_s: float
                          ) -> list[dict]:
    """Per-round merge: returns list of dicts ``{window: (start, end), bt: {mac:dev}}``.

    The window is derived from ``timestamp`` (end of bt-scan) minus the
    nominal ``--duration`` we passed to bt_scanner; this is approximate
    but good enough for overlap-checking against probe time-ranges.
    """
    from datetime import datetime
    rounds: list[dict] = []
    for bf in bt_files:
        if not bf.exists():
            continue
        try:
            data = json.loads(bf.read_text(encoding="utf-8"))
        except Exception:
            continue
        ts_str = data.get("timestamp") or ""
        try:
            end_ts = datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            # fall back to file mtime as a best guess
            try:
                end_ts = bf.stat().st_mtime
            except Exception:
                continue
        start_ts = end_ts - max(1.0, bt_scan_duration_s)
        rounds.append({
            "window": (start_ts, end_ts),
            "bt":     {m.lower(): d for m, d in (data.get("bt_devices") or {}).items()},
        })
    return rounds


def _bt_devices_merged(rounds: list[dict]) -> dict[str, dict]:
    """Squash bt_devices across rounds for the per-BT pairing record."""
    merged: dict[str, dict] = {}
    for r in rounds:
        for mac, dev in r["bt"].items():
            existing = merged.get(mac)
            if existing is None:
                merged[mac] = dict(dev)
            else:
                if dev.get("has_tracker") and not existing.get("has_tracker"):
                    existing["has_tracker"] = True
                if not existing.get("vendor") and dev.get("vendor"):
                    existing["vendor"] = dev["vendor"]
                if not existing.get("device_type") and dev.get("device_type"):
                    existing["device_type"] = dev["device_type"]
    return merged


def _probe_overlaps_round(probe: dict, window: tuple[float, float]) -> bool:
    """Time-window overlap check between a probe (first_ts/last_ts) and
    a BT-round window. Empty/zero timestamps fall through to True so we
    keep behaviour permissive when ts metadata is missing."""
    p_first = float(probe.get("first_ts") or 0)
    p_last = float(probe.get("last_ts") or 0)
    if p_first <= 0 and p_last <= 0:
        return True
    w_start, w_end = window
    return p_last >= w_start and p_first <= w_end


def update(
    *,
    pairing_path: Path,
    session_id: str,
    bt_files: list[Path],
    wifi_probes: dict[str, dict],
    bt_scan_duration_s: float = 75.0,
) -> dict:
    """Merge this session's WiFi probes + BT devices into the pairing DB
    using time-window overlap correlation.

    ``wifi_probes`` is the dict from ``WifiWatcher.probe_macs()``: each entry
    has ``first_ts`` / ``last_ts`` / ``count``. ``bt_scan_duration_s`` is the
    ``--duration`` we passed to bt_scanner (defaults to scan_engine's
    typical 75s). Each per-round bt JSON yields a (start, end) window;
    a probe-MAC attaches to a BT-MAC in that round only if the probe's
    time-range overlaps the window.

    Returns a summary dict::

        {
          "session_id":    "20260501_173000",
          "bt_seen":       N,
          "wifi_seen":     M,
          "new_pairs":     [{"bt": "aa:..", "wifi": "11:..", "vendor": ".."}, ...],
          "established":   [{"bt": "aa:..", "co_sightings": 4, ...}, ...]
        }
    """
    pairing_path = Path(pairing_path)
    db = _load(pairing_path)
    prune(db)  # drop stale records before merging this session
    rounds = _bt_rounds_from_files(bt_files, bt_scan_duration_s)
    bt_devices = _bt_devices_merged(rounds)

    now_iso = datetime.utcnow().isoformat()
    new_pairs: list[dict] = []
    established: list[dict] = []

    # Build per-BT attribution by overlap with rounds. probes_for_bt[mac]
    # collects only those WiFi probes whose time-range overlaps at least
    # one round in which this BT MAC was seen.
    probes_for_bt: dict[str, dict[str, dict]] = {bt_mac: {} for bt_mac in bt_devices}
    for r in rounds:
        for bt_mac in r["bt"].keys():
            for wmac, wprobe in wifi_probes.items():
                if _probe_overlaps_round(wprobe, r["window"]):
                    probes_for_bt[bt_mac][wmac.lower()] = wprobe

    for bt_mac, bt_dev in bt_devices.items():
        rec = db.get(bt_mac)
        if rec is None:
            rec = {
                "first_seen":   now_iso,
                "last_seen":    now_iso,
                "vendor":       bt_dev.get("vendor", ""),
                "device_type":  bt_dev.get("device_type", ""),
                "risk":         bt_dev.get("risk", "low"),
                "co_sightings": 0,
                "wifi_macs":    {},
                "sessions":     [],
            }
            db[bt_mac] = rec

        # Update co-sighting metadata (one increment per session, even if
        # the BT MAC appears in multiple per-round JSONs).
        if session_id not in rec["sessions"]:
            rec["sessions"].append(session_id)
            rec["co_sightings"] = rec.get("co_sightings", 0) + 1
        rec["last_seen"] = now_iso
        if bt_dev.get("risk") == "high":
            rec["risk"] = "high"
        if not rec.get("vendor") and bt_dev.get("vendor"):
            rec["vendor"] = bt_dev["vendor"]
        if not rec.get("device_type") and bt_dev.get("device_type"):
            rec["device_type"] = bt_dev["device_type"]

        # Attribute only the WiFi MACs that overlapped this BT in time.
        for wmac, wprobe in probes_for_bt.get(bt_mac, {}).items():
            wrec = rec["wifi_macs"].get(wmac)
            wlast = datetime.utcfromtimestamp(
                float(wprobe.get("last_ts", 0)) or 0,
            ).isoformat() if wprobe.get("last_ts") else now_iso
            if wrec is None:
                rec["wifi_macs"][wmac] = {
                    "count":     int(wprobe.get("count", 1)),
                    "last_seen": wlast,
                }
                new_pairs.append({
                    "bt":     bt_mac,
                    "wifi":   wmac,
                    "vendor": rec.get("vendor", ""),
                })
            else:
                wrec["count"] = int(wrec.get("count", 0)) + int(wprobe.get("count", 1))
                wrec["last_seen"] = wlast

        if rec["co_sightings"] >= ESTABLISHED_MIN:
            established.append({
                "bt":           bt_mac,
                "vendor":       rec.get("vendor", ""),
                "device_type":  rec.get("device_type", ""),
                "co_sightings": rec["co_sightings"],
                "wifi_count":   len(rec["wifi_macs"]),
                "risk":         rec.get("risk", "low"),
            })

    _save(pairing_path, db)
    return {
        "session_id":   session_id,
        "bt_seen":      len(bt_devices),
        "wifi_seen":    len(wifi_probes),
        "new_pairs":    new_pairs,
        "established":  established,
    }


def render_report_block(summary: dict, *, max_pairs: int = 8) -> str:
    """Markdown block for the argus_report. Empty string if nothing to show."""
    if not summary or (summary.get("bt_seen", 0) == 0 and not summary.get("established")):
        return ""
    lines: list[str] = []
    lines.append("## WiFi/BT - Mögliche Verknüpfungen")
    lines.append("")
    est = summary.get("established") or []
    if est:
        lines.append("### Stabil (≥3 Sessions zusammen)")
        lines.append("")
        lines.append("| BT-MAC | Hersteller | Typ | Sessions | WiFi-MACs | Risk |")
        lines.append("|---|---|---|---|---|---|")
        for e in est[:max_pairs]:
            lines.append(
                f"| `{e['bt']}` | {e.get('vendor','')[:25]} | "
                f"{e.get('device_type','')[:20]} | {e['co_sightings']} | "
                f"{e['wifi_count']} | {e.get('risk','')} |"
            )
        lines.append("")
    new = summary.get("new_pairs") or []
    if new:
        lines.append("### Neue Kandidaten in dieser Session")
        lines.append("")
        lines.append("| BT-MAC | WiFi-MAC | Hersteller |")
        lines.append("|---|---|---|")
        for p in new[:max_pairs]:
            lines.append(
                f"| `{p['bt']}` | `{p['wifi']}` | {p.get('vendor','')[:25]} |"
            )
        if len(new) > max_pairs:
            lines.append(f"| ... | ({len(new) - max_pairs} weitere) | |")
        lines.append("")
    return "\n".join(lines) + "\n"
