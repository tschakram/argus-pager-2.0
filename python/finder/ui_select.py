"""Target-Auswahl-Screen — scrollbare Liste, BTN_UP/DN + BTN_LEFT.

Nutzt das gleiche poll_input-Pattern wie scan_live.py. Kein Auto-Advance.
"""
from __future__ import annotations

import time

from ui import theme as T
from ui import widgets as W

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER
except ImportError:  # SSH-Shell fallback
    BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER = 16, 32, 4, 1, 2, 64

from . import target_loader

REDRAW_PERIOD = 0.15
MAX_VISIBLE = 4


def select_target(pager, targets: list[dict], mode: str,
                  session_label: str = "") -> dict | None:
    """Zeigt scrollbare Liste, gibt gewaehltes target zurueck oder None bei Abbruch.

    ``session_label`` wird im Header-Body gezeigt damit der User sieht
    aus welchem Argus-Run die Targets stammen.
    """
    if not targets:
        return None

    selected = 0
    scroll = 0
    last_redraw = 0.0
    items = [target_loader.short_label(t, mode) for t in targets]

    while True:
        try:
            _curr, pressed, _rel = pager.poll_input()
        except Exception:
            pressed = 0

        if pressed & BTN_UP:
            selected = max(0, selected - 1)
            if selected < scroll:
                scroll = selected
            last_redraw = 0
        elif pressed & BTN_DOWN:
            selected = min(len(items) - 1, selected + 1)
            if selected >= scroll + MAX_VISIBLE:
                scroll = selected - MAX_VISIBLE + 1
            last_redraw = 0
        elif pressed & BTN_LEFT or pressed & BTN_A:
            return targets[selected]
        elif pressed & BTN_B or pressed & BTN_POWER:
            return None

        now = time.monotonic()
        if now - last_redraw >= REDRAW_PERIOD:
            _draw(pager, mode, items, selected, scroll, len(targets), session_label)
            last_redraw = now
        time.sleep(0.04)


def _draw(pager, mode: str, items: list[str], selected: int,
          scroll: int, total: int, session_label: str = "") -> None:
    pager.clear(T.BLACK)
    title = "FINDER · " + ("WIFI" if mode == "wifi" else "BT")
    T.header(pager, title)

    body_y = T.BODY_Y
    if T.FONT_PATH:
        sub = f"Target ({selected+1}/{total})"
        if session_label:
            sub += "  -  " + session_label
        pager.draw_ttf(8, body_y, sub, T.GREY, T.FONT_PATH, T.FONT_SMALL)
    list_y = body_y + T.FONT_SMALL + 8
    W.list_menu(pager, 8, list_y, items, selected,
                scroll=scroll, max_visible=MAX_VISIBLE,
                row_h=T.FONT_BODY + 8)

    T.footer(pager, [("UP/DN", "Scroll"),
                     ("LEFT", "OK"),
                     ("B", "Cancel")])
    pager.flip()


def show_message(pager, title: str, body: str) -> None:
    """Einfache Info-Card, wartet auf einen Buttonclick."""
    T.error_card(pager, T.ascii_safe(title), T.ascii_safe(body))
    # poll fuer einen Klick (BTN_B/A/LEFT) — nicht blockieren
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            _, pressed, _ = pager.poll_input()
        except Exception:
            pressed = 0
        if pressed & (BTN_A | BTN_B | BTN_LEFT | BTN_POWER):
            return
        time.sleep(0.05)
