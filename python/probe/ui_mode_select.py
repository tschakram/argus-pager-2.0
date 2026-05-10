"""Mode-Wahl beim Probe-Start: BT-GATT, Network (TBD), mDNS (TBD)."""
from __future__ import annotations

import time

from ui import theme as T

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER = 16, 32, 4, 1, 2, 64

REDRAW_PERIOD = 0.2

MODES = [
    ("bt_gatt",  "BT-GATT Probe",   "gatttool, Service+Char-Read",      "ready"),
    ("network",  "Network nmap",    "TCP-Scan + Banner auf wlan0cli",   "stub"),
    ("mdns",     "mDNS / SSDP",     "Apple TV / Cast / Sonos / NAS",    "stub"),
]


def select_mode(pager) -> str | None:
    """Returns 'bt_gatt' / 'network' / 'mdns' / None."""
    selected = 0
    last_draw = 0.0
    while True:
        try:
            _curr, pressed, _rel = pager.poll_input()
        except Exception:
            pressed = 0

        if pressed & BTN_UP:
            selected = max(0, selected - 1)
            last_draw = 0
        elif pressed & BTN_DOWN:
            selected = min(len(MODES) - 1, selected + 1)
            last_draw = 0
        elif pressed & (BTN_LEFT | BTN_A):
            return MODES[selected][0]
        elif pressed & (BTN_B | BTN_POWER):
            return None

        now = time.monotonic()
        if now - last_draw >= REDRAW_PERIOD:
            _draw(pager, selected)
            last_draw = now
        time.sleep(0.04)


def _draw(pager, selected: int) -> None:
    pager.clear(T.BLACK)
    T.header(pager, "PROBE Mode")

    body_y = T.BODY_Y
    if T.FONT_PATH:
        pager.draw_ttf(8, body_y, "Welcher Probe?",
                       T.GREY, T.FONT_PATH, T.FONT_SMALL)

    list_y = body_y + T.FONT_SMALL + 8
    row_h = T.FONT_BODY + 18
    for i, (key, label, descr, status) in enumerate(MODES):
        row_y = list_y + i * row_h
        is_sel = (i == selected)
        ready = (status == "ready")
        bg = T.DARK if is_sel else T.BLACK
        accent = T.ACCENT if ready else T.GREY
        pager.fill_rect(8, row_y - 2, T.W - 16, row_h, bg)
        if is_sel:
            pager.fill_rect(8, row_y - 2, 4, row_h, accent)
        if T.FONT_PATH:
            tag = "" if ready else "  (TODO)"
            pager.draw_ttf(20, row_y + 2, label + tag, accent,
                           T.FONT_PATH, T.FONT_BODY)
            pager.draw_ttf(20, row_y + 2 + T.FONT_BODY,
                           descr, T.WHITE, T.FONT_PATH, T.FONT_SMALL)

    T.footer(pager, [("UP/DN", "Scroll"), ("LEFT", "OK"), ("B", "Cancel")])
    pager.flip()
