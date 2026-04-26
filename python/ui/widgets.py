"""Re-usable widgets for argus-pager 2.0 screens.

Everything draws to a Pager instance from pagerctl. Widgets are dumb — state
lives in the screen, the widget only renders.
"""
from __future__ import annotations

from . import theme as T


# ── Toggle (slider style ON/OFF) ─────────────────────────────────────────

def toggle(pager, x: int, y: int, label: str, value: bool, *,
           selected: bool = False, width: int = 360) -> None:
    """Renders ``label  [■■■■■■■■] ON`` / ``[────────] OFF``."""
    label_color = T.WHITE if selected else 0xC618  # light grey
    if T.FONT_PATH:
        pager.draw_ttf(x, y, label, label_color, T.FONT_PATH, T.FONT_BODY)
    else:
        pager.draw_text(x, y, label, label_color, size=1)

    # Bar position: keep enough room for ~14-char label at FONT_BODY size.
    bar_x = x + 200
    bar_w = 150
    bar_h = max(16, T.FONT_BODY - 4)
    bar_y = y + 4

    # bar background
    pager.fill_rect(bar_x, bar_y, bar_w, bar_h, T.DARK)
    pager.rect(bar_x, bar_y, bar_w, bar_h, T.GREY)

    if value:
        pager.fill_rect(bar_x + 2, bar_y + 2, bar_w - 4, bar_h - 4, T.ACCENT)
        text, color = "ON", T.ACCENT
    else:
        text, color = "OFF", T.GREY

    if T.FONT_PATH:
        pager.draw_ttf(bar_x + bar_w + 10, y, text, color, T.FONT_PATH, T.FONT_BODY)
    else:
        pager.draw_text(bar_x + bar_w + 10, y, text, color, size=1)

    # selection caret
    if selected:
        pager.fill_rect(x - 14, y + 4, 6, T.FONT_BODY - 4, T.ACCENT)


# ── Number stepper (rounds / duration_s) ─────────────────────────────────

def stepper(pager, x: int, y: int, label: str, value, unit: str = "",
            *, selected: bool = False) -> None:
    label_color = T.WHITE if selected else 0xC618
    if T.FONT_PATH:
        pager.draw_ttf(x, y, label, label_color, T.FONT_PATH, T.FONT_BODY)
        val_text = f"<  {value}{unit}  >" if selected else f"{value}{unit}"
        pager.draw_ttf(x + 200, y, val_text, T.ACCENT if selected else T.WHITE,
                       T.FONT_PATH, T.FONT_BODY)
    else:
        pager.draw_text(x, y, f"{label} {value}{unit}", label_color, size=1)
    if selected:
        pager.fill_rect(x - 14, y + 4, 6, T.FONT_BODY - 4, T.ACCENT)


# ── Scrollable list (preset menu, report list) ───────────────────────────

def list_menu(pager, x: int, y: int, items: list[str], selected: int,
              *, scroll: int = 0, max_visible: int = 5,
              row_h: int = 26, width: int = 460) -> None:
    for i in range(max_visible):
        idx = scroll + i
        if idx >= len(items):
            break
        row_y = y + i * row_h
        if idx == selected:
            pager.fill_rect(x, row_y - 2, width, row_h, T.DARK)
            pager.fill_rect(x, row_y - 2, 4, row_h, T.ACCENT)
            color = T.ACCENT
        else:
            color = T.WHITE
        if T.FONT_PATH:
            pager.draw_ttf(x + 14, row_y + 2, items[idx], color, T.FONT_PATH, T.FONT_BODY)
        else:
            pager.draw_text(x + 14, row_y + 2, items[idx], color, size=1)


# ── Progress bar ────────────────────────────────────────────────────────

def progress_bar(pager, x: int, y: int, w: int, h: int, fraction: float,
                 *, color=None) -> None:
    fraction = max(0.0, min(1.0, fraction))
    color = color or T.ACCENT
    pager.fill_rect(x, y, w, h, T.DARK)
    pager.rect(x, y, w, h, T.GREY)
    if fraction > 0:
        pager.fill_rect(x + 1, y + 1, int((w - 2) * fraction), h - 2, color)


# ── Quality light (✓ / ⚠ / ✗) ───────────────────────────────────────────

def quality_light(pager, x: int, y: int, label: str, status: str,
                  detail: str = "") -> None:
    """``status`` ∈ {"ok", "wait", "off"}."""
    color = {"ok": T.ACCENT, "wait": T.AMBER, "off": T.GREY}.get(status, T.GREY)
    glyph = {"ok": "OK", "wait": "..", "off": "--"}.get(status, "--")

    pager.fill_circle(x + 6, y + 8, 5, color)

    if T.FONT_PATH:
        pager.draw_ttf(x + 18, y, label, T.WHITE, T.FONT_PATH, T.FONT_BODY)
        if detail:
            pager.draw_ttf(x + 200, y, detail, color, T.FONT_PATH, T.FONT_SMALL)
    else:
        pager.draw_text(x + 18, y, f"{label} {glyph} {detail}", color, size=1)


# ── Threat card (post-scan / report-view) ───────────────────────────────

def threat_card(pager, x: int, y: int, w: int, h: int, level: str,
                lines: list[str]) -> None:
    """``level`` ∈ {"clean", "low", "medium", "high"}."""
    palette = {
        "clean":  T.ACCENT,
        "low":    T.ACCENT,
        "medium": T.AMBER,
        "high":   T.RED,
    }
    color = palette.get(level, T.GREY)
    pager.fill_rect(x, y, w, h, T.DARK)
    pager.rect(x, y, w, h, color)
    pager.fill_rect(x, y, 6, h, color)

    if T.FONT_PATH:
        pager.draw_ttf(x + 12, y + 6, f"THREAT: {level.upper()}", color,
                       T.FONT_PATH, T.FONT_TITLE)
        ly = y + T.FONT_TITLE + 8
        line_h = T.FONT_SMALL + 4
        max_lines = max(1, (h - (T.FONT_TITLE + 12)) // line_h)
        for ln in lines[:max_lines]:
            pager.draw_ttf(x + 12, ly, ln, T.WHITE, T.FONT_PATH, T.FONT_SMALL)
            ly += line_h
    else:
        pager.draw_text(x + 12, y + 8, f"THREAT: {level.upper()}", color, size=1)
