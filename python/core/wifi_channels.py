"""Discover the WiFi *frequencies* the chip actually supports.

Returns frequencies in MHz, grouped by band, plus a flat sweep order. We use
frequencies (not channel numbers) because channel numbers overlap between
bands — channel 1 exists in 2.4 GHz AND 6 GHz, and 5/6 GHz overlap on
149-177. ``iw set channel N`` is ambiguous in that case; ``iw set freq <MHz>``
is not, so the hopper in scan_engine.py uses freqs end-to-end.

For 6 GHz we keep only the Preferred Scanning Channels (PSC) — 6E APs are
required to beacon on a PSC even if they operate on a non-PSC channel, so
sweeping 15 PSCs covers the whole band without spending 50% of the dwell
budget on 6 GHz alone.
"""
from __future__ import annotations

import re
import subprocess

# 6 GHz Preferred Scanning Channels (Wi-Fi 6E spec). 20 MHz primary frequencies.
# Generated from PSC channels 5, 21, 37, ..., 229: freq = 5950 + 5*ch.
_PSC_FREQS_6GHZ: set[int] = {
    5975, 6055, 6135, 6215, 6295, 6375, 6455, 6535,
    6615, 6695, 6775, 6855, 6935, 7015, 7095,
}

_FREQ_LINE = re.compile(r"\*\s+(\d+)\s+MHz\s+\[(\d+)\]")


def _phy_for_iface(iface: str) -> str | None:
    try:
        out = subprocess.run(
            ["iw", "dev", iface, "info"],
            capture_output=True, text=True, timeout=4, check=False,
        ).stdout
    except Exception:
        return None
    m = re.search(r"wiphy\s+(\d+)", out)
    return f"phy{m.group(1)}" if m else None


def _band_for_freq(freq_mhz: int) -> str:
    if 2400 <= freq_mhz < 2500:
        return "2.4"
    if 5000 <= freq_mhz < 5900:
        return "5"
    if 5900 <= freq_mhz < 7200:
        return "6"
    return "?"


def discover_channels(iface: str = "wlan1mon") -> dict:
    """Return frequencies grouped by band plus a flat sweep order.

    Output schema::

        {
          "2.4": [2412, 2417, ...],   # all enabled 20 MHz primaries
          "5":   [5180, 5200, ...],   # incl. usable DFS
          "6":   [5975, 6055, ...],   # Wi-Fi 6E PSC subset only
          "all": [...],               # 2.4 + 5 + 6 in sweep order
        }

    Skipped: channels marked ``(disabled)`` or DFS state ``unavailable``.
    Kept:    DFS state ``usable`` / ``available``  — both are fine for
             passive monitor capture.
    """
    phy = _phy_for_iface(iface) or "phy1"
    try:
        out = subprocess.run(
            ["iw", "phy", phy, "channels"],
            capture_output=True, text=True, timeout=4, check=False,
        ).stdout
    except Exception:
        return {"2.4": [], "5": [], "6": [], "all": []}

    bands: dict[str, list[int]] = {"2.4": [], "5": [], "6": []}
    cur_freq: int | None = None
    cur_band: str | None = None
    block: list[str] = []

    def _flush():
        if cur_freq is None or cur_band is None:
            return
        joined = " ".join(block).lower()
        if "(disabled)" in joined:
            return
        if "dfs state: unavailable" in joined:
            return
        if cur_band == "6" and cur_freq not in _PSC_FREQS_6GHZ:
            return  # 6 GHz: PSC subset only
        if cur_band in bands:
            bands[cur_band].append(cur_freq)

    for line in out.splitlines():
        m = _FREQ_LINE.search(line)
        if m:
            _flush()
            cur_freq = int(m.group(1))
            cur_band = _band_for_freq(cur_freq)
            block = [line]
        else:
            block.append(line)
    _flush()

    # Dedupe (chip lists each freq twice when bonded widths are listed).
    for k in bands:
        seen: set[int] = set()
        uniq: list[int] = []
        for f in bands[k]:
            if f in seen:
                continue
            seen.add(f)
            uniq.append(f)
        bands[k] = uniq

    flat: list[int] = bands["2.4"] + bands["5"] + bands["6"]
    return {**bands, "all": flat}


def freq_to_channel(freq_mhz: int) -> int:
    """Best-effort channel number for display only (analyser report)."""
    if 2412 <= freq_mhz <= 2484:
        return 1 + (freq_mhz - 2412) // 5 if freq_mhz != 2484 else 14
    if 5000 <= freq_mhz < 5900:
        return (freq_mhz - 5000) // 5
    if 5900 <= freq_mhz < 7200:
        return (freq_mhz - 5950) // 5
    return -1


if __name__ == "__main__":
    import json
    import sys
    iface = sys.argv[1] if len(sys.argv) > 1 else "wlan1mon"
    res = discover_channels(iface)
    print(json.dumps(res, indent=2))
    print(f"\nTotals: 2.4={len(res['2.4'])}  "
          f"5={len(res['5'])}  6={len(res['6'])}  "
          f"all={len(res['all'])}")
