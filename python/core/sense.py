"""Sensor auto-detection for the splash screen.

One call, ``discover(cfg) -> SensorReport``, runs every probe with a tight
timeout so the splash never hangs. Local probes are filesystem checks
(cheap). Mudi probes piggy-back on ``mudi_client.is_reachable`` (cached) and
collapse all asset existence checks into a single SSH round-trip.

The report is plain data: the splash screen renders it, and the scan engine
later decides which sensors to actually run from the same dict.

Also exposes ``sync_time(cfg)``: pulls UTC from the Mudi (which stays
NTP-synced via LTE) and applies it to the Pager clock. The Pager has no
internet of its own and its ``/etc/TZ`` historically drifted; we still want
a per-run alignment so report filenames and the cross_report 4h cutoff
agree on the same wall clock.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

from . import mudi_client


@dataclass
class SensorReport:
    wifi_monitor: bool = False
    wifi_iface: str | None = None
    bluetooth: bool = False
    mudi: bool = False
    gps_mudi: bool = False
    cell_mudi: bool = False
    imsi_watch: bool = False
    sms_watch: bool = False
    time_synced: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_wifi_iface() -> str | None:
    try:
        with open("/proc/net/dev", "r") as f:
            text = f.read()
    except Exception:
        return None
    for name in ("wlan1mon", "wlan0mon"):
        if f"{name}:" in text:
            return name
    return None


def _detect_bluetooth() -> bool:
    return bool(shutil.which("btmon"))


def _mudi_check_paths(cfg: dict) -> dict[str, bool]:
    """Single SSH round-trip: which raypager assets exist on the Mudi.

    For imsi/sms watchers we accept BOTH the alert .jsonl (only written
    on real events) AND the polling state-file (refreshed on every cycle
    when the daemon is running). That way the splash reports the watcher
    as live even when the environment happens to be clean.
    """
    m = cfg.get("mudi") or {}
    base = m.get("python_dir", "/root/raypager/python")
    loot = m.get("loot_dir", "/root/loot/raypager")
    targets = [
        f"{base}/gps.py",                       # 0
        f"{base}/cell_info.py",                 # 1
        f"{loot}/imsi_alerts.jsonl",            # 2 - real-alert log
        f"{loot}/imsi_monitor_state.json",      # 3 - per-poll heartbeat
        f"{loot}/silent_sms.jsonl",             # 4 - real-alert log
        f"{loot}/silent_sms_seen.json",         # 5 - per-poll heartbeat
    ]
    cmd = "for f in " + " ".join(targets) + '; do [ -e "$f" ] && echo 1 || echo 0; done'
    rc, out, _ = mudi_client._run(cfg, cmd, timeout=8)
    if rc != 0:
        return {"gps": False, "cell": False, "imsi": False, "sms": False}
    flags = (out or "").splitlines()
    flags += ["0"] * (6 - len(flags))
    flags = [f.strip() == "1" for f in flags]
    return {
        "gps":  flags[0],
        "cell": flags[1],
        "imsi": flags[2] or flags[3],   # alerts.jsonl OR state heartbeat
        "sms":  flags[4] or flags[5],   # sms.jsonl   OR seen-state heartbeat
    }


def sync_time(cfg: dict) -> bool:
    """Pull UTC from the Mudi and apply it to the Pager clock.

    Returns True iff the pager date was successfully nudged. Silent on
    network/auth failures - this is best-effort, the scan still runs even
    if time-sync is skipped.
    """
    if not mudi_client.is_reachable(cfg):
        return False
    rc, out, _ = mudi_client._run(cfg, 'date -u +"%Y-%m-%d %H:%M:%S"', timeout=6)
    if rc != 0:
        return False
    stamp = (out or "").strip()
    if not stamp:
        return False
    try:
        p = subprocess.run(
            ["date", "-u", "-s", stamp],
            capture_output=True, text=True, timeout=4,
        )
        return p.returncode == 0
    except Exception:
        return False


def discover(cfg: dict) -> SensorReport:
    """Cheap, splash-friendly sensor probe. Bounded total wall-time (~10s worst case).

    Order matters: time-sync first, then the Mudi-reachable check (which
    primes the SSH ControlMaster mux that the time-sync just opened), then
    the per-asset checks.
    """
    rep = SensorReport()

    iface = _detect_wifi_iface()
    rep.wifi_monitor = iface is not None
    rep.wifi_iface = iface

    rep.bluetooth = _detect_bluetooth()

    try:
        rep.time_synced = sync_time(cfg)
    except Exception as exc:
        rep.notes.append(f"time-sync failed: {exc}")

    try:
        rep.mudi = mudi_client.is_reachable(cfg)
    except Exception as exc:
        rep.mudi = False
        rep.notes.append(f"mudi probe failed: {exc}")

    if rep.mudi:
        try:
            paths = _mudi_check_paths(cfg)
            rep.gps_mudi = paths["gps"]
            rep.cell_mudi = paths["cell"]
            rep.imsi_watch = paths["imsi"]
            rep.sms_watch = paths["sms"]
        except Exception as exc:
            rep.notes.append(f"mudi paths probe failed: {exc}")

    return rep
