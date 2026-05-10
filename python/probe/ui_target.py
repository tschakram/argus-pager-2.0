"""Target-Auswahl fuer den Probe.

Quellen:
1. Letzter Argus-Run BT-Targets (last_only) - bevorzugt
2. Manuelle MAC-Eingabe ueber Pager-Tastenfeld waere v2.2 - aktuell
   nicht praktisch ohne Tastatur am Pager.
"""
from __future__ import annotations

import time

from ui import theme as T
from ui import widgets as W
from finder import target_loader

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER = 16, 32, 4, 1, 2, 64

REDRAW_PERIOD = 0.15
MAX_VISIBLE = 4


def select_bt_target(pager, loot_dir: str = "/root/loot/argus") -> dict | None:
    """Liest BT-Targets aus letztem Argus-Run, zeigt scrollbare Liste.
    Returns gewaehltes target (dict mit mac, vendor etc.) oder None bei Cancel.
    """
    targets = target_loader.load_bt_targets(loot_dir, last_only=True)
    if not targets:
        # Fallback: alle bt-Files
        targets = target_loader.load_bt_targets(loot_dir, last_only=False,
                                                max_files=20)
    if not targets:
        from .ui_results import show_message
        show_message(pager, "Keine BT-Targets",
                     "Erst Argus-Scan oder Sweep, dann erneut.")
        return None

    selected = 0
    scroll = 0
    last_redraw = 0.0
    items = [_format_target(t) for t in targets]

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
        elif pressed & (BTN_LEFT | BTN_A):
            return targets[selected]
        elif pressed & (BTN_B | BTN_POWER):
            return None

        now = time.monotonic()
        if now - last_redraw >= REDRAW_PERIOD:
            _draw(pager, items, selected, scroll, len(targets))
            last_redraw = now
        time.sleep(0.04)


def _format_target(t: dict) -> str:
    last4 = t["mac"].replace(":", "")[-6:]
    name = (t.get("name") or t.get("vendor") or "?")[:14]
    risk = t.get("risk", "")
    return f"{last4} {name} {risk}"


def _draw(pager, items: list[str], selected: int, scroll: int,
          total: int) -> None:
    pager.clear(T.BLACK)
    T.header(pager, "PROBE BT-Target")

    body_y = T.BODY_Y
    if T.FONT_PATH:
        pager.draw_ttf(8, body_y, f"Target ({selected+1}/{total}):",
                       T.GREY, T.FONT_PATH, T.FONT_SMALL)
    list_y = body_y + T.FONT_SMALL + 8
    W.list_menu(pager, 8, list_y, items, selected,
                scroll=scroll, max_visible=MAX_VISIBLE,
                row_h=T.FONT_BODY + 8)
    T.footer(pager, [("UP/DN", "Scroll"), ("LEFT", "OK"), ("B", "Cancel")])
    pager.flip()
