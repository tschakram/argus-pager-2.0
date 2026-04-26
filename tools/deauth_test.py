#!/usr/bin/env python3
"""Offline test for core.deauth_monitor - no radio traffic required.

Three scenarios are simulated by feeding synthetic tcpdump-style lines
directly into ``DeauthMonitor._process_line()``. The detector decides
purely from those calls (timestamp + line text), so we can validate the
flood-detection logic in seconds without running tcpdump or sending a
single 802.11 frame.

Run on the pager (or anywhere):

    python3 tools/deauth_test.py

Exit code is non-zero if any scenario produced an unexpected result.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# Resolve PYTHONPATH so this works regardless of cwd
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "python"))

from core.deauth_monitor import DeauthMonitor


# Synthetic tcpdump line format - we only need the MAC tokens to be present.
LINE_TPL = (
    "{ts:.6f} 200000000us tsft 1.0 Mb 2412 MHz 11b -39dB signal "
    "DA:{dst} SA:{src} BSSID:{bss} Deauthentication ({src}): "
    "Reason 7 - Class 3 frame received from non-associated STA"
)


def _line(ts: float, src: str, dst: str = "ff:ff:ff:ff:ff:ff", bss: str | None = None) -> str:
    return LINE_TPL.format(ts=ts, src=src, dst=dst, bss=bss or src)


def _new_monitor(name: str, threshold: int = 5, window_s: int = 10) -> DeauthMonitor:
    loot = Path(tempfile.mkdtemp(prefix=f"deauth-test-{name}-"))
    return DeauthMonitor(loot_dir=loot, window_s=window_s, flood_threshold=threshold)


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
    return cond


def case_idle() -> bool:
    """No traffic at all -> snapshot must be empty, no floods."""
    print("[case 1/4] idle (zero frames)")
    mon = _new_monitor("idle")
    snap = mon.snapshot()
    return all([
        _ok("total == 0", snap["total"] == 0),
        _ok("floods == 0", snap["flood_count"] == 0),
        _ok("rate == 0",   snap["rate_per_s"] == 0),
    ])


def case_background() -> bool:
    """Slow trickle (1 frame every 2s for 8s) - below threshold of 5/s."""
    print("[case 2/4] background trickle (sub-threshold)")
    mon = _new_monitor("trickle", threshold=5, window_s=10)
    base = time.time()
    for i in range(4):
        mon._process_line(
            _line(base + i * 2.0, src="aa:bb:cc:dd:ee:ff"),
            ts=base + i * 2.0,
        )
    snap = mon.snapshot()
    return all([
        _ok("total == 4", snap["total"] == 4),
        _ok("flood_count == 0", snap["flood_count"] == 0,
            f"rate {snap['rate_per_s']}/s, threshold 5/s"),
    ])


def case_flood() -> bool:
    """Real flood: 30 frames/s for 2s -> rate 6/s, MUST flag."""
    print("[case 3/4] active deauth flood")
    mon = _new_monitor("flood", threshold=5, window_s=10)
    base = time.time()
    for i in range(60):
        ts = base + i * (1.0 / 30.0)  # 30 fps
        mon._process_line(
            _line(ts, src="11:22:33:44:55:66", dst="aa:bb:cc:dd:ee:ff"),
            ts=ts,
        )
    snap = mon.snapshot()
    return all([
        _ok("total == 60", snap["total"] == 60),
        _ok("flood_count >= 1", snap["flood_count"] >= 1,
            f"floods={snap['flood_count']}, rate={snap['rate_per_s']}/s"),
        _ok("top source identified",
            bool(snap["top_sources"]) and snap["top_sources"][0][0] == "11:22:33:44:55:66"),
    ])


def case_multi_source() -> bool:
    """Two sources, one floods, one trickles - top_sources[0] is the flooder."""
    print("[case 4/4] multi-source (one flood, one background)")
    mon = _new_monitor("multi", threshold=5, window_s=10)
    base = time.time()
    # flooder: 50 frames in 1s
    for i in range(50):
        ts = base + i * 0.02
        mon._process_line(_line(ts, src="aa:bb:cc:dd:ee:ff"), ts=ts)
    # background: 3 frames over 6s
    for i in range(3):
        ts = base + 1.0 + i * 2.0
        mon._process_line(_line(ts, src="11:22:33:44:55:66"), ts=ts)
    snap = mon.snapshot()
    return all([
        _ok("flood_count >= 1", snap["flood_count"] >= 1),
        _ok("flooder is top source",
            snap["top_sources"][0][0] == "aa:bb:cc:dd:ee:ff",
            f"top_sources={snap['top_sources']}"),
    ])


def main() -> int:
    cases = [case_idle, case_background, case_flood, case_multi_source]
    failures = 0
    for fn in cases:
        try:
            ok = fn()
        except Exception as exc:
            print(f"  [FAIL] {fn.__name__} raised: {exc}")
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
