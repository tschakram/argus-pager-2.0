"""Splash screen — logo, version, sensor self-check (~2s)."""
from __future__ import annotations

import sys
import time

from .. import theme as T
from core import mudi_client


def _log(msg: str) -> None:
    print(f"[splash] {msg}", file=sys.stderr, flush=True)


def run(pager, state) -> str:
    _log("start")
    pager.clear(T.BLACK)

    # Centered ARGUS title
    if T.FONT_PATH:
        pager.draw_ttf_centered(40, "ARGUS", T.ACCENT, T.FONT_PATH, 64)
        pager.draw_ttf_centered(108, "PAGER 2.0", T.WHITE, T.FONT_PATH, T.FONT_BODY)
    else:
        pager.draw_text_centered(58, "ARGUS", T.ACCENT, size=2)
        pager.draw_text_centered(118, "PAGER 2.0", T.WHITE, size=2)

    # divider
    pager.hline(80, 144, T.W - 160, T.ACCENT)

    # init line - readable size, not the tiniest
    if T.FONT_PATH:
        pager.draw_ttf_centered(154, "initializing sensors...",
                                T.GREY, T.FONT_PATH, T.FONT_SMALL)
    else:
        pager.draw_text_centered(160, "initializing sensors", T.GREY, size=1)

    _log("flip splash frame")
    pager.flip()
    T.led_state(pager, "init")

    # ── Sensor self-check ────────────────────────────────────────────
    _log("sensor check: WiFi monitor")
    checks = []
    checks.append(("WiFi monitor",   _check_wlan_mon()))
    _log("sensor check: Bluetooth")
    checks.append(("Bluetooth",      _check_btmon()))
    _log("sensor check: Pager GPS")
    checks.append(("Pager GPS",      _check_pager_gps()))
    _log("sensor check: Mudi backend (this can hang on SSH)")
    try:
        mudi_ok = mudi_client.is_reachable(state["config"])
    except Exception as exc:
        _log(f"mudi check failed: {exc}")
        mudi_ok = False
    checks.append(("Mudi backend",   mudi_ok))
    _log(f"sensor checks done: {checks}")

    state["sensor_status"] = dict(checks)

    # render result line under "initializing"
    line = "  ".join(f"{k}:{'OK' if v else 'NA'}" for k, v in checks)
    if T.FONT_PATH:
        pager.draw_ttf_centered(186, line, T.WHITE, T.FONT_PATH, T.FONT_SMALL - 4)
    else:
        pager.draw_text_centered(184, line[:50], T.WHITE, size=1)
    pager.flip()

    time.sleep(1.5)
    return "preset_menu"


# ── helpers ─────────────────────────────────────────────────────────────

def _check_wlan_mon() -> bool:
    try:
        with open("/proc/net/dev", "r") as f:
            return "wlan1mon:" in f.read() or "wlan0mon:" in f.read()
    except Exception:
        return False


def _check_btmon() -> bool:
    import shutil
    return bool(shutil.which("btmon"))


def _check_pager_gps() -> bool:
    # placeholder — pager has internal GPS, we verify via gpsd or /dev path
    import os
    for p in ("/dev/ttyACM0", "/dev/ttyACM1", "/var/run/gpsd.sock"):
        if os.path.exists(p):
            return True
    return False
