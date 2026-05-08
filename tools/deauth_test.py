#!/usr/bin/env python3
"""Offline tests for ``core.wifi_watcher`` and the deauth-incident archive.

Five scenarios are simulated by feeding synthetic tcpdump-style lines
directly into ``WifiWatcher._process_line()``. The detector decides
purely from those calls (timestamp + line text), so we can validate the
flood-detection logic and the on_flood -> archive pipeline in seconds
without running tcpdump or sending a single 802.11 frame.

Run on the pager (or anywhere with the project on PYTHONPATH):

    python3 tools/deauth_test.py

Exit code is non-zero if any scenario produced an unexpected result.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Resolve PYTHONPATH so this works regardless of cwd
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "python"))

from core.wifi_watcher import WifiWatcher


# Synthetic tcpdump line format - we only need the MAC tokens to be present.
LINE_TPL = (
    "{ts:.6f} 200000000us tsft 1.0 Mb 2412 MHz 11b -39dB signal "
    "DA:{dst} SA:{src} BSSID:{bss} Deauthentication ({src}): "
    "Reason 7 - Class 3 frame received from non-associated STA"
)
PROBE_TPL = (
    "{ts:.6f} 200000000us tsft 1.0 Mb 2412 MHz 11b -55dB signal "
    "RA:ff:ff:ff:ff:ff:ff TA:{src} BSSID:ff:ff:ff:ff:ff:ff "
    "Probe Request () [1.0]"
)


def _line(ts: float, src: str, dst: str = "ff:ff:ff:ff:ff:ff",
          bss: str | None = None) -> str:
    return LINE_TPL.format(ts=ts, src=src, dst=dst, bss=bss or src)


def _probe(ts: float, src: str) -> str:
    return PROBE_TPL.format(ts=ts, src=src)


def _new_watcher(name: str, threshold: int = 5, window_s: int = 10,
                 on_flood=None) -> WifiWatcher:
    loot = Path(tempfile.mkdtemp(prefix=f"watcher-test-{name}-"))
    return WifiWatcher(
        loot_dir=loot, window_s=window_s,
        flood_threshold=threshold, on_flood=on_flood,
    )


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
    return cond


# ── flood-detection cases ────────────────────────────────────────────────

def case_idle() -> bool:
    print("[case 1/5] idle (zero frames)")
    w = _new_watcher("idle")
    snap = w.snapshot()
    return all([
        _ok("total == 0", snap["total"] == 0),
        _ok("floods == 0", snap["flood_count"] == 0),
        _ok("rate == 0", snap["rate_per_s"] == 0),
        _ok("wifi_devices == 0", snap["wifi_devices"] == 0),
    ])


def case_background() -> bool:
    print("[case 2/5] background trickle (sub-threshold)")
    w = _new_watcher("trickle", threshold=5, window_s=10)
    base = time.time()
    for i in range(4):
        w._process_line(_line(base + i * 2.0, src="aa:bb:cc:dd:ee:ff"),
                        ts=base + i * 2.0)
    snap = w.snapshot()
    return all([
        _ok("total == 4", snap["total"] == 4),
        _ok("flood_count == 0", snap["flood_count"] == 0,
            f"rate {snap['rate_per_s']}/s, threshold 5/s"),
    ])


def case_flood() -> bool:
    print("[case 3/5] active deauth flood")
    w = _new_watcher("flood", threshold=5, window_s=10)
    base = time.time()
    for i in range(60):
        ts = base + i * (1.0 / 30.0)
        w._process_line(_line(ts, src="11:22:33:44:55:66",
                              dst="aa:bb:cc:dd:ee:ff"), ts=ts)
    snap = w.snapshot()
    return all([
        _ok("total == 60", snap["total"] == 60),
        _ok("flood_count >= 1", snap["flood_count"] >= 1,
            f"floods={snap['flood_count']}, rate={snap['rate_per_s']}/s"),
        _ok("top source identified",
            bool(snap["top_sources"])
            and snap["top_sources"][0][0] == "11:22:33:44:55:66"),
    ])


# ── probe-request tracking case (new in WifiWatcher) ─────────────────────

def case_probe_tracking() -> bool:
    print("[case 4/5] probe-request unique-MAC tracking")
    w = _new_watcher("probes")
    base = time.time()
    # 3 unique MACs, one repeats
    for i, mac in enumerate(["aa:00:00:00:00:01",
                             "aa:00:00:00:00:02",
                             "aa:00:00:00:00:01",
                             "aa:00:00:00:00:03"]):
        ts = base + i * 0.5
        w._process_line(_probe(ts, src=mac), ts=ts)
    snap = w.snapshot()
    macs = w.probe_macs()
    return all([
        _ok("wifi_devices == 3", snap["wifi_devices"] == 3),
        _ok("probe_total == 4", snap["probe_total"] == 4),
        _ok("probe_macs has 3 entries", len(macs) == 3),
        _ok("first/last_ts populated",
            all("first_ts" in m and "last_ts" in m for m in macs.values())),
    ])


# ── end-to-end on_flood -> archive pipeline ─────────────────────────────

def case_archive_pipeline() -> bool:
    """Verify on_flood callback -> scan_engine._on_flood -> incidents/

    This is the polish that's invisible from the unit-level: WifiWatcher
    fires on_flood, scan_engine archives the active PCAP plus a sidecar
    JSON. We mock the engine state without spinning up tcpdump."""
    print("[case 5/5] end-to-end deauth -> incidents archive")
    from core import scan_engine

    base_dir = Path(tempfile.mkdtemp(prefix="argus-incident-test-"))
    pcap_dir = base_dir / "pcap"
    pcap_dir.mkdir()
    # Build a 24-byte minimal but valid pcap-file global header
    fake_pcap = pcap_dir / "scan_test_r01_120000.pcap"
    fake_pcap.write_bytes(
        b"\xd4\xc3\xb2\xa1"     # magic
        b"\x02\x00\x04\x00"     # version 2.4
        b"\x00\x00\x00\x00"     # tz=0
        b"\x00\x00\x00\x00"     # sigfigs=0
        b"\xff\xff\x00\x00"     # snaplen 65535
        b"\x69\x00\x00\x00"     # linktype 105 = 802.11
    )

    cfg = {"paths": {"base_dir": str(base_dir)}}
    preset = {"_name": "AUTO", "rounds": 0, "duration_s": 120,
              "wifi": True, "bt": False}
    eng = scan_engine.ScanEngine(cfg, preset)
    eng.pcap_files.append(fake_pcap)
    eng._round_idx = 1
    with eng._stats_lock:
        eng._stats["gps"] = "lock"

    captured = {}
    def on_flood_cb(flood):
        captured["flood"] = flood
        eng._on_flood(flood)

    w = _new_watcher("incident", threshold=5, window_s=10, on_flood=on_flood_cb)
    base = time.time()
    for i in range(50):
        ts = base + i * 0.02
        w._process_line(_line(ts, src="ca:fe:ca:fe:00:01",
                              dst="bc:bc:bc:bc:bc:bc"), ts=ts)

    incidents = base_dir / "incidents"
    pcap_files = sorted(incidents.glob("deauth_*.pcap")) if incidents.exists() else []
    json_files = sorted(incidents.glob("deauth_*.json")) if incidents.exists() else []

    ok = True
    ok &= _ok("on_flood callback fired", "flood" in captured)
    ok &= _ok("incidents/deauth_*.pcap exists",
              len(pcap_files) == 1, str(pcap_files))
    ok &= _ok("incidents/deauth_*.json exists",
              len(json_files) == 1, str(json_files))
    if json_files:
        meta = json.loads(json_files[0].read_text())
        ok &= _ok("metadata src_mac correct",
                  meta.get("src_mac") == "ca:fe:ca:fe:00:01",
                  f"got {meta.get('src_mac')}")
        ok &= _ok("metadata gps captured",
                  meta.get("gps") == "lock",
                  f"got {meta.get('gps')}")
        ok &= _ok("metadata round_idx == 1",
                  meta.get("round_idx") == 1)
    return ok


def main() -> int:
    cases = [case_idle, case_background, case_flood,
             case_probe_tracking, case_archive_pipeline]
    failures = 0
    for fn in cases:
        try:
            ok = fn()
        except Exception as exc:
            import traceback
            print(f"  [FAIL] {fn.__name__} raised: {exc}")
            traceback.print_exc()
            ok = False
        if not ok:
            failures += 1
        print()
    print("=" * 50)
    if failures == 0:
        print(f"OK - all {len(cases)} scenarios passed.")
        return 0
    print(f"FAIL - {failures}/{len(cases)} scenarios failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
