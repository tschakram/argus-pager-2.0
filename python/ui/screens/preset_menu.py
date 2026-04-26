"""Preset selection screen: STANDARD / DEEPSCAN / CUSTOM.

Layout note: the description for the highlighted preset is rendered
*inside* the highlighted row (indented one notch under the name), not
in a fixed slot above the footer. The fixed-slot version (alpha2/3/4)
collided with the third list item on the 480x222 LCD because there
just isn't enough vertical room for "header + 3 items + description +
footer" at the new font sizes. By making only the selected row taller
we get the description shown without any overlap with neighbouring
rows.
"""
from __future__ import annotations

from .. import theme as T
from core import presets

try:
    from pagerctl import BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER = 1, 2, 16, 32, 64


PRESETS_ORDER = ["STANDARD", "DEEPSCAN", "CUSTOM"]
DESCRIPTIONS = {
    "STANDARD": "Daily counter-surveillance, 4x90s",
    "DEEPSCAN": "Stationary deep scan, 6x120s, +cameras",
    "CUSTOM":   "All toggles editable, 3x60s",
}


def run(pager, state) -> str | None:
    selected = PRESETS_ORDER.index(state.get("preset_name", "STANDARD"))

    # Compact layout. Math: 3 base rows + selected-row's description = body height.
    # base 32 * 3 = 96; selected-extra 24 -> total 120, fits in body 128.
    row_h      = T.FONT_BODY  + 4    # base row height per preset
    desc_extra = T.FONT_SMALL + 2    # extra height for the selected row's desc
    list_x = 10
    list_w = T.W - list_x * 2

    while True:
        pager.clear(T.BLACK)
        T.header(pager, "Preset", accent=T.ACCENT)

        y = T.BODY_Y + 4
        for i, name in enumerate(PRESETS_ORDER):
            is_sel = (i == selected)
            row_total = row_h + (desc_extra if is_sel else 0)
            if is_sel:
                # highlight body + accent strip on the left
                pager.fill_rect(list_x, y - 2, list_w, row_total, T.DARK)
                pager.fill_rect(list_x, y - 2, 4,       row_total, T.ACCENT)
                color = T.ACCENT
            else:
                color = T.WHITE

            if T.FONT_PATH:
                pager.draw_ttf(list_x + 14, y + 2, name, color,
                               T.FONT_PATH, T.FONT_BODY)
                if is_sel:
                    desc = DESCRIPTIONS.get(name, "")
                    desc_y = y + 2 + T.FONT_BODY + 4
                    pager.draw_ttf(list_x + 14, desc_y, desc, T.GREY,
                                   T.FONT_PATH, T.FONT_SMALL)
            else:
                pager.draw_text(list_x + 14, y + 2, name, color, size=1)

            y += row_total

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
            return None
