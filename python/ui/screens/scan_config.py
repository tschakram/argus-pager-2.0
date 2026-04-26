"""Scan-Config screen — slider toggles for sensors + rounds/duration steppers.

Body area is too small to fit all 10 rows simultaneously, so we scroll based
on the selected index. Power-button exits cleanly back to main.
"""
from __future__ import annotations

from .. import theme as T
from .. import widgets as W

try:
    from pagerctl import BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_A, BTN_B, BTN_POWER = 1, 2, 4, 8, 16, 32, 64


# Order matters - this is how the user navigates.
# Note: there is no "GPS Pager" toggle - the pager has no internal GPS,
# the only GPS source is the u-blox USB dongle on the Mudi.
TOGGLE_ROWS = [
    ("wifi",         "WiFi"),
    ("bt",           "Bluetooth"),
    ("gps_mudi",     "GPS (Mudi)"),
    ("cell",         "Cell / IMSI"),
    ("cross_report", "Cross-Report"),
    ("cameras",      "Cameras"),
    ("shodan",       "Shodan / WiGLE"),
]
STEPPER_ROWS = [
    ("rounds",     "Rounds",   1, 12, ""),
    ("duration_s", "Duration", 30, 300, "s"),
]
ROWS = TOGGLE_ROWS + [(k, label) for (k, label, *_rest) in STEPPER_ROWS]


def run(pager, state) -> str | None:
    preset = state["preset"]
    selected = 0

    while True:
        # Compute how many rows fit in body, with proper spacing for FONT_BODY
        body_h = T.FOOTER_Y - (T.BODY_Y + 4)
        row_h = max(28, T.FONT_BODY + 8)         # leave breathing room
        max_visible = max(3, body_h // row_h)

        # Auto-scroll so selected stays visible
        scroll = max(0, min(selected - max_visible // 2,
                            len(ROWS) - max_visible))
        scroll = max(0, scroll)

        pager.clear(T.BLACK)
        T.header(pager, f"Config: {state['preset_name']}")

        # ── Render visible rows ──────────────────────────────────────────
        for v in range(max_visible):
            i = scroll + v
            if i >= len(ROWS):
                break
            row_y = T.BODY_Y + 4 + v * row_h
            if i < len(TOGGLE_ROWS):
                key, label = TOGGLE_ROWS[i]
                W.toggle(pager, 28, row_y, label, bool(preset.get(key, False)),
                         selected=(i == selected))
            else:
                j = i - len(TOGGLE_ROWS)
                key, label, lo, hi, unit = STEPPER_ROWS[j]
                W.stepper(pager, 28, row_y, label, preset.get(key, lo), unit,
                          selected=(i == selected))

        # ── Scroll indicators ────────────────────────────────────────────
        if scroll > 0:
            _draw_arrow(pager, T.W - 16, T.BODY_Y + 4, up=True)
        if scroll + max_visible < len(ROWS):
            _draw_arrow(pager, T.W - 16, T.FOOTER_Y - 12, up=False)

        T.footer(pager, [("A", "Start"), ("B", "Back"), ("L/R", "Toggle")])
        pager.flip()

        btn = pager.wait_button()
        if btn == BTN_UP:
            selected = (selected - 1) % len(ROWS)
        elif btn == BTN_DOWN:
            selected = (selected + 1) % len(ROWS)
        elif btn in (BTN_LEFT, BTN_RIGHT):
            _adjust(preset, selected, delta=(-1 if btn == BTN_LEFT else +1))
        elif btn == BTN_A:
            return "scan_live"
        elif btn == BTN_B:
            return "preset_menu"
        elif btn == BTN_POWER:
            return None     # global quit


def _draw_arrow(pager, x: int, y: int, *, up: bool) -> None:
    """Tiny scroll indicator triangle."""
    if up:
        pager.fill_rect(x, y + 6, 12, 2, T.GREY)
        pager.fill_rect(x + 2, y + 4, 8, 2, T.GREY)
        pager.fill_rect(x + 4, y + 2, 4, 2, T.GREY)
    else:
        pager.fill_rect(x, y, 12, 2, T.GREY)
        pager.fill_rect(x + 2, y + 2, 8, 2, T.GREY)
        pager.fill_rect(x + 4, y + 4, 4, 2, T.GREY)


def _adjust(preset: dict, index: int, *, delta: int) -> None:
    if index < len(TOGGLE_ROWS):
        key = TOGGLE_ROWS[index][0]
        preset[key] = not bool(preset.get(key, False))
        return
    j = index - len(TOGGLE_ROWS)
    key, _label, lo, hi, _unit = STEPPER_ROWS[j]
    step = 1 if key == "rounds" else 10
    preset[key] = max(lo, min(hi, int(preset.get(key, lo)) + delta * step))
