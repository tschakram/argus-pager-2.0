"""Mode-Wahl beim Finder-Start: Target oder Sweep.

Target = aus letztem Argus-Run eine spezifische MAC waehlen + tracken.
Sweep  = alle MACs in Reichweite live, ohne festes Ziel - umgeht
         BLE-Privacy-Adress-Rotation (jede 15min neue Adresse).
"""
from __future__ import annotations

import time

from ui import theme as T

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_POWER = 16, 32, 4, 64

REDRAW_PERIOD = 0.2


def select_mode(pager, mode_label: str) -> str | None:
    """Returns 'target', 'sweep' oder None (Cancel)."""
    last_draw = 0.0
    while True:
        try:
            _curr, pressed, _rel = pager.poll_input()
        except Exception:
            pressed = 0
        if pressed & BTN_LEFT:
            return "target"
        if pressed & BTN_A:
            return "sweep"
        if pressed & (BTN_B | BTN_POWER):
            return None
        now = time.monotonic()
        if now - last_draw >= REDRAW_PERIOD:
            _draw(pager, mode_label)
            last_draw = now
        time.sleep(0.04)


def _draw(pager, mode_label: str) -> None:
    pager.clear(T.BLACK)
    T.header(pager, f"FINDER {mode_label}")

    body_y = T.BODY_Y
    if not T.FONT_PATH:
        T.footer(pager, [("L", "Target"), ("A", "Sweep"), ("B", "Cancel")])
        pager.flip()
        return

    pager.draw_ttf(10, body_y, "Wie suchen?", T.WHITE, T.FONT_PATH, T.FONT_BODY)

    # Zwei Cards: Target (LEFT) + Sweep (A)
    card_y = body_y + T.FONT_BODY + 14
    card_h = 70
    card_w = (T.W - 30) // 2

    # Target card
    pager.fill_rect(10, card_y, card_w, card_h, T.DARK)
    pager.rect(10, card_y, card_w, card_h, T.ACCENT)
    pager.fill_rect(10, card_y, 4, card_h, T.ACCENT)
    pager.draw_ttf(20, card_y + 6, "LEFT  Target",
                   T.ACCENT, T.FONT_PATH, T.FONT_BODY)
    pager.draw_ttf(20, card_y + 6 + T.FONT_BODY + 4,
                   "aus letztem", T.WHITE, T.FONT_PATH, T.FONT_SMALL)
    pager.draw_ttf(20, card_y + 6 + T.FONT_BODY + 4 + T.FONT_SMALL,
                   "Argus-Run",  T.WHITE, T.FONT_PATH, T.FONT_SMALL)

    # Sweep card
    sw_x = 20 + card_w
    pager.fill_rect(sw_x, card_y, card_w, card_h, T.DARK)
    pager.rect(sw_x, card_y, card_w, card_h, T.AMBER)
    pager.fill_rect(sw_x, card_y, 4, card_h, T.AMBER)
    pager.draw_ttf(sw_x + 10, card_y + 6, "A     Sweep",
                   T.AMBER, T.FONT_PATH, T.FONT_BODY)
    pager.draw_ttf(sw_x + 10, card_y + 6 + T.FONT_BODY + 4,
                   "alle live", T.WHITE, T.FONT_PATH, T.FONT_SMALL)
    pager.draw_ttf(sw_x + 10, card_y + 6 + T.FONT_BODY + 4 + T.FONT_SMALL,
                   "(privacy-safe)", T.WHITE, T.FONT_PATH, T.FONT_SMALL)

    T.footer(pager, [("LEFT", "Target"), ("A", "Sweep"), ("B", "Cancel")])
    pager.flip()
