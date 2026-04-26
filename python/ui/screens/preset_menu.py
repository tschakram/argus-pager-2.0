"""Preset selection screen — STANDARD / DEEPSCAN / CUSTOM."""
from __future__ import annotations

from .. import theme as T
from .. import widgets as W
from core import presets

try:
    from pagerctl import BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER = 1, 2, 16, 32, 64


PRESETS_ORDER = ["STANDARD", "DEEPSCAN", "CUSTOM"]
DESCRIPTIONS = {
    "STANDARD": "Daily counter-surveillance: 4x90s WiFi+BT+GPS+Cell+Cross",
    "DEEPSCAN": "Stationary deep scan: 6x120s adds Cameras+Shodan",
    "CUSTOM":   "All toggles editable, 3x60s default",
}


def run(pager, state) -> str | None:
    selected = PRESETS_ORDER.index(state.get("preset_name", "STANDARD"))

    while True:
        pager.clear(T.BLACK)
        T.header(pager, "Preset", accent=T.ACCENT)

        W.list_menu(pager, x=10, y=T.BODY_Y + 4,
                    items=PRESETS_ORDER, selected=selected,
                    row_h=T.FONT_BODY + 14)

        # Description for highlighted preset (just above the footer)
        desc = DESCRIPTIONS[PRESETS_ORDER[selected]]
        desc_y = T.FOOTER_Y - T.FONT_SMALL - 4
        if T.FONT_PATH:
            pager.draw_ttf(12, desc_y, desc, T.GREY, T.FONT_PATH, T.FONT_SMALL)
        else:
            pager.draw_text(12, desc_y, desc[:60], T.GREY, size=1)

        T.footer(pager, [("A", "Continue"), ("B", "Shutdown")])
        pager.flip()

        btn = pager.wait_button()
        if btn == BTN_UP:
            selected = (selected - 1) % len(PRESETS_ORDER)
        elif btn == BTN_DOWN:
            selected = (selected + 1) % len(PRESETS_ORDER)
        elif btn == BTN_A:
            name = PRESETS_ORDER[selected]
            state["preset_name"] = name
            state["preset"] = presets.from_config(state["config"], name)
            return "scan_config"
        elif btn == BTN_B:
            return None
        elif btn == BTN_POWER:
            return None     # global quit
