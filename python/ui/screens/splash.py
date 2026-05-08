"""Splash screen: title + sensor self-check from core.sense.

ASCII-only - the display font has no umlauts. Detection logic lives in
``core/sense.py``; this screen just renders the report and stashes it on
``state['sensor_report']`` for downstream screens.
"""
from __future__ import annotations

import sys
import time

from .. import theme as T
from core import sense


def _log(msg: str) -> None:
    print(f"[splash] {msg}", file=sys.stderr, flush=True)


def run(pager, state) -> str:
    _log("start")

    _draw_title(pager)
    _draw_intro_line(pager, "checking sensors...")
    pager.flip()
    T.led_state(pager, "init")

    _log("sense.discover()")
    rep = sense.discover(state["config"])
    _log(f"sense.discover() -> {rep.as_dict()}")

    state["sensor_report"] = rep
    state["sensor_status"] = {
        "WiFi monitor":    rep.wifi_monitor,
        "Bluetooth":       rep.bluetooth,
        "Mudi (GPS+Cell)": rep.mudi,
    }
    state["preset"] = _auto_preset(rep)
    state["preset_name"] = "AUTO"

    _draw_title(pager)
    _draw_status_grid(pager, rep)
    pager.flip()
    T.led_state(pager, "ok")

    time.sleep(2.0)
    return "scan_live"


def _auto_preset(rep) -> dict:
    """Translate sensor discovery into a scan_engine preset dict."""
    return {
        "_name":        "AUTO",
        "rounds":       0,             # 0 = unbounded
        "duration_s":   120,            # 120s gives bt_scanner enough time
                                        # for GPS+OUI+BLE+SDP+JSON-write
        "wifi":         rep.wifi_monitor,
        "bt":           rep.bluetooth,
        "gps_mudi":     rep.gps_mudi,
        "cell":         rep.cell_mudi,
        "cross_report": rep.gps_mudi and rep.cell_mudi,
        "cameras":      False,
        "shodan":       True,           # external intel always-on; gated
        "fingerbank":   True,           # by API-key presence in config
        "imsi_watch":   rep.imsi_watch,
        "sms_watch":    rep.sms_watch,
    }


# ── render helpers ──────────────────────────────────────────────────────

def _draw_title(pager) -> None:
    pager.clear(T.BLACK)
    if T.FONT_PATH:
        pager.draw_ttf_centered(4, "ARGUS", T.ACCENT, T.FONT_PATH, T.FONT_TITLE)
        pager.draw_ttf_centered(46, "PAGER 2.0", T.WHITE, T.FONT_PATH, T.FONT_BODY)
    else:
        pager.draw_text_centered(8, "ARGUS", T.ACCENT, size=3)
        pager.draw_text_centered(48, "PAGER 2.0", T.WHITE, size=2)
    pager.hline(40, 84, T.W - 80, T.ACCENT)


def _draw_intro_line(pager, text: str) -> None:
    sz = T.FONT_SMALL - 4
    if T.FONT_PATH:
        pager.draw_ttf_centered(96, text, T.GREY, T.FONT_PATH, sz)
    else:
        pager.draw_text_centered(98, text, T.GREY, size=1)


def _draw_status_grid(pager, rep) -> None:
    rows_left = [
        ("WiFi mon",   rep.wifi_monitor),
        ("Bluetooth",  rep.bluetooth),
        ("Mudi",       rep.mudi),
        ("Time",       rep.time_synced),
    ]
    rows_right = [
        ("GPS  Mudi",  rep.gps_mudi),
        ("Cell Mudi",  rep.cell_mudi),
        ("IMSI watch", rep.imsi_watch),
        ("SMS  watch", rep.sms_watch),
    ]
    _draw_intro_line(pager, "Sensors detected")

    y0 = 116
    dy = 22
    sz = T.FONT_SMALL - 4
    col_l = 24
    col_r = 248

    def _draw_row(x: int, y: int, name: str, ok: bool) -> None:
        flag = "OK" if ok else "NA"
        flag_col = T.ACCENT if ok else T.GREY
        if T.FONT_PATH:
            pager.draw_ttf(x, y, name, T.WHITE, T.FONT_PATH, sz)
            pager.draw_ttf(x + 112, y, ":", T.GREY, T.FONT_PATH, sz)
            pager.draw_ttf(x + 124, y, flag, flag_col, T.FONT_PATH, sz)
        else:
            pager.draw_text(x, y, f"{name}:{flag}", flag_col, size=1)

    for i, (name, ok) in enumerate(rows_left):
        _draw_row(col_l, y0 + i * dy, name, ok)
    for i, (name, ok) in enumerate(rows_right):
        _draw_row(col_r, y0 + i * dy, name, ok)
