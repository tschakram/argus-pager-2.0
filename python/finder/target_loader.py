"""Argus Finder — Target-Liste aus Reports + Suspects-DB.

Default: nur Targets aus dem ALLERLETZTEN Argus-Run (last_only=True).
Grund: BLE Privacy Addresses rotieren ~alle 15 Min — alte Adressen sind
fuer den Walking-Finder wertlos. Mit last_only=False wird ueber die
letzten N Reports/Files aggregiert (history-mode).

WiFi-Targets: aus dem letzten Argus-Report (Verdaechtige + 'Alle Geraete'
mit Score >= 0.5).
BT-Targets: aus den bt_*.json-Files der gleichen Session_id wie der
letzte Report (risk=high oder has_tracker).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

# Bootstrap cyt/python to sys.path for mac_ignore import
_CYT_PY = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "cyt", "python"))
if _CYT_PY not in sys.path:
    sys.path.insert(0, _CYT_PY)
from mac_ignore import MacIgnoreSet

DEFAULT_LOOT = "/root/loot/argus"
CYT_LOOT     = "/root/loot/chasing_your_tail"

# Match `| <mac> | <vendor> | <type> | <score> | <appearances> | ...`
# also accept the older format without RSSI col.
_ROW_RE = re.compile(
    r'^\|\s*[🔴🟢]?\s*`?([0-9a-f]{2}(?::[0-9a-f]{2}){5})`?\s*\|'
    r'\s*([^|]+?)\s*\|.*?\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|',
    re.IGNORECASE,
)

_SESSION_RE   = re.compile(r'^\*\*Session:\*\*\s*`?(\d{8}_\d{6})`?', re.MULTILINE)
_BT_FILENAME  = re.compile(r'bt_(\d{8}_\d{6})_r\d+_\d+\.json$')


def _load_ignore(loot_dir: str) -> MacIgnoreSet:
    """Liest ignore_macs aus mac_list.json - inkl. Wildcard-Patterns
    (siehe cyt/python/mac_ignore.py). Wildcards wie "aa:bb:cc:dd:ee:??"
    erfassen BLE-Privacy-Rotation (Samsung TV / iPhone Continuity).
    """
    candidates = [
        os.path.join(loot_dir, "ignore_lists", "mac_list.json"),
        os.path.join(CYT_LOOT, "ignore_lists", "mac_list.json"),
    ]
    out = MacIgnoreSet()
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            with open(p) as fh:
                data = json.load(fh)
            out.update(data.get("ignore_macs", []))
        except Exception:
            pass
    return out


def _latest_report(loot_dir: str) -> str | None:
    reports = sorted(glob.glob(os.path.join(loot_dir, "reports",
                                            "argus_report_*.md")))
    return reports[-1] if reports else None


def _session_id_from_report(report_path: str) -> str | None:
    try:
        with open(report_path) as f:
            txt = f.read(4096)
        m = _SESSION_RE.search(txt)
        return m.group(1) if m else None
    except Exception:
        return None


def latest_session_meta(loot_dir: str = DEFAULT_LOOT) -> dict:
    """Info ueber den letzten Argus-Run (fuer UI-Anzeige)."""
    report = _latest_report(loot_dir)
    if not report:
        return {"report": None, "session_id": None, "mtime": None}
    return {
        "report": report,
        "session_id": _session_id_from_report(report),
        "mtime": os.path.getmtime(report),
    }


def load_wifi_targets(loot_dir: str = DEFAULT_LOOT,
                      last_only: bool = True,
                      max_reports: int = 15,
                      min_score: float = 0.5) -> list[dict]:
    """Sammelt verdaechtige WiFi-MACs.
    last_only=True (default): nur aus letztem Argus-Report.
    last_only=False: aus den letzten ``max_reports`` Reports aggregiert.
    """
    reports = sorted(glob.glob(os.path.join(loot_dir, "reports",
                                            "argus_report_*.md")))
    if not reports:
        return []
    ignore = _load_ignore(loot_dir)
    suspects: dict[str, dict] = {}

    selected = reports[-1:] if last_only else reports[-max_reports:]
    for path in selected:
        try:
            with open(path) as f:
                in_table = False
                for line in f:
                    s = line.strip()
                    if s.startswith('## ') or s.startswith('# '):
                        in_table = ('Verd' in s or 'WARNING' in s or
                                    'Alle Ger' in s or 'TRACKING' in s)
                        continue
                    if not in_table:
                        continue
                    m = _ROW_RE.match(s)
                    if not m:
                        continue
                    mac    = m.group(1).upper()
                    vendor = m.group(2).strip()
                    try:
                        score = float(m.group(3))
                        appearances = int(m.group(4))
                    except ValueError:
                        continue
                    if mac in ignore or score < min_score:
                        continue
                    e = suspects.setdefault(mac, {
                        "mac": mac,
                        "vendor": (vendor or "?")[:18],
                        "score": score,
                        "appearances": 0,
                        "sightings": 0,
                    })
                    e["sightings"] += 1
                    e["appearances"] = max(e["appearances"], appearances)
                    if score > e["score"]:
                        e["score"] = score
        except Exception:
            continue

    # rank: erst sightings (wie oft ueberhaupt aufgetaucht), dann score
    return sorted(suspects.values(),
                  key=lambda x: (-x["sightings"], -x["score"]))


def load_bt_targets(loot_dir: str = DEFAULT_LOOT,
                    last_only: bool = True,
                    max_files: int = 30) -> list[dict]:
    """Sammelt verdaechtige BT-MACs.
    last_only=True (default): nur bt_<session>_*.json wo session_id der
    letzten Argus-Session entspricht. Stellt sicher dass die BLE-
    Privacy-Adressen frisch sind und mit dem letzten WiFi-Snapshot
    konsistent.
    last_only=False: ``max_files`` letzte BT-Files aggregiert.
    """
    bt_files = sorted(glob.glob(os.path.join(loot_dir, "bt_*.json")))
    if not bt_files:
        return []
    ignore = _load_ignore(loot_dir)
    suspects: dict[str, dict] = {}

    if last_only:
        meta = latest_session_meta(loot_dir)
        sess = meta.get("session_id")
        if sess:
            selected = [p for p in bt_files
                        if _BT_FILENAME.search(os.path.basename(p))
                        and _BT_FILENAME.search(os.path.basename(p)).group(1) == sess]
            # Falls keine BT-Files mit gematchter session-id (z.B. weil
            # Argus-Run hatte BT abgeschaltet), Fallback auf neuestes Single-File.
            if not selected:
                selected = bt_files[-1:]
        else:
            selected = bt_files[-1:]
    else:
        selected = bt_files[-max_files:]

    for f in selected:
        try:
            with open(f) as fh:
                data = json.load(fh)
            for mac, info in data.get("bt_devices", {}).items():
                mac_up = mac.upper()
                if mac_up in ignore:
                    continue
                risk = info.get("risk", "")
                tracker = info.get("has_tracker") or info.get("device_type", "").lower().startswith("track")
                if not (tracker or risk in ("high", "medium")):
                    continue
                e = suspects.setdefault(mac_up, {
                    "mac": mac_up,
                    "vendor": (info.get("vendor", "?") or "?")[:18],
                    "name": info.get("name") or "",
                    "risk": risk,
                    "device_type": info.get("device_type", ""),
                    "sightings": 0,
                    "rssi_last": None,
                })
                e["sightings"] += 1
                rssi = info.get("rssi")
                if rssi is not None:
                    e["rssi_last"] = rssi
                # promote risk to highest seen
                if risk == "high":
                    e["risk"] = "high"
        except Exception:
            continue

    risk_rank = {"high": 2, "medium": 1, "": 0, "low": 0, "none": 0}
    return sorted(suspects.values(),
                  key=lambda x: (-risk_rank.get(x.get("risk", ""), 0),
                                 -x["sightings"]))


def short_label(t: dict, mode: str) -> str:
    """Kompakte Anzeige fuer die Auswahl-Liste."""
    last4 = t["mac"].replace(":", "")[-6:]
    vendor = (t.get("vendor") or "?")[:14]
    if mode == "wifi":
        return f"{last4} {vendor} s{t.get('sightings', 0)}"
    name = (t.get("name") or vendor)[:14]
    return f"{last4} {name} s{t.get('sightings', 0)}"
