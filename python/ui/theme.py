"""Pineapple-Pager visual theme + LED/vibrate helpers.

All colors are RGB565 — converted via ``pager.rgb()`` once at init time.
Layout constants (480x222 LCD) live here so screens stay declarative.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Resolution ───────────────────────────────────────────────────────────
W = 480
H = 222

# Layout slots (filled from screens). Sizes follow the FONT_* constants
# below - if you bump those, recompute HEADER_H / FOOTER_H so the chrome
# still fits without clipping descenders.
#
# Note: pagerctl's draw_ttf y-coordinate behavior differs slightly between
# draw_ttf() (top-of-glyph) and draw_ttf_centered() (also top-of-glyph but
# can drift a few pixels with display fonts). We give the body a generous
# top buffer so headers can never end up overlapping the body title.
HEADER_Y   = 0
HEADER_H   = 44          # fits FONT_TITLE=36 with top + bottom padding
DIVIDER_Y  = HEADER_H + 1
BODY_Y     = HEADER_H + 12   # 12px breathing room below the divider
FOOTER_H   = 38          # fits FONT_SMALL=22 with padding
FOOTER_Y   = H - FOOTER_H

# ── Colors (will be re-bound to pager.rgb in init) ───────────────────────
BLACK = 0x0000
WHITE = 0xFFFF
GREEN = 0x07E0   # 0x00FF00
LIME  = 0x07E0
RED   = 0xF800
AMBER = 0xFD20
CYAN  = 0x07FF
GREY  = 0x4208
DARK  = 0x10A2   # ~ #111815 — Pineapple Pager dashboard tint
ACCENT = GREEN   # primary accent — green like the Pineapple Pager dashboard

# Fonts.
# Sizes were bumped one notch in the alpha to favor legibility over density;
# screens that ran out of space now scroll instead of cramming. If you raise
# these further, also raise HEADER_H / FOOTER_H above accordingly.
FONT_PATH: str | None = None         # filled in init()
FONT_TITLE = 36          # 480x222 LCD - readable at arm's length
FONT_BODY  = 28          # main rows + value steppers
FONT_SMALL = 22          # footer hints, descriptions, scroll body

# ── State ────────────────────────────────────────────────────────────────
_pager = None
_config: dict = {}


def init(pager, config: dict) -> None:
    """Call once after Pager() construction."""
    global _pager, _config, FONT_PATH
    _pager = pager
    _config = config

    # locate TTF font - explicit `ui.font` from config wins, then any
    # *.ttf the user dropped into python/assets/fonts/, then the system
    # paths in priority order (DejaVu first because Steelfish's glyph
    # coverage is narrow and its italic-display style looks blurry on
    # the 480x222 LCD).
    payload_dir = Path(os.environ.get(
        "ARGUS_PAYLOAD_DIR",
        Path(__file__).resolve().parents[2],
    ))
    user_font = config.get("ui", {}).get("font")
    candidates = []
    if user_font:
        candidates += [
            payload_dir / "python" / "assets" / "fonts" / user_font,
            Path(user_font) if user_font.startswith("/") else None,
        ]
    # Auto-discover any TTF the user dropped into assets/fonts/.
    asset_fonts_dir = payload_dir / "python" / "assets" / "fonts"
    if asset_fonts_dir.is_dir():
        candidates += sorted(asset_fonts_dir.glob("*.ttf"))
    # System paths - DejaVu is preferred (sharp on 480x222, full Unicode);
    # Steelfish is the last-resort fallback (italic display font, fuzzy).
    candidates += [
        Path("/usr/share/fonts/ttf-dejavu/DejaVuSansMono.ttf"),
        Path("/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/ttf-liberation/LiberationMono-Regular.ttf"),
        Path("/usr/share/fonts/ttf-liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
        Path("/mmc/root/lib/pagerctl/DejaVuSansMono.ttf"),
        Path("/mmc/usr/share/fonts/ttf-dejavu/DejaVuSansMono.ttf"),
        Path("/pineapple/ui/Steelfish.ttf"),  # last-resort fallback
    ]
    candidates = [c for c in candidates if c is not None]
    for c in candidates:
        if c.exists():
            FONT_PATH = str(c)
            break

    pager.clear(BLACK)
    pager.flip()


def shutdown(pager) -> None:
    """Final teardown: blank screen, all LEDs off."""
    try:
        pager.led_all_off()
    except Exception:
        pass
    pager.clear(BLACK)
    pager.flip()


def _set_all_leds(pager, r: int, g: int, b: int) -> None:
    """pagerctl exposes per-direction RGB LEDs — wrap them all to one color."""
    try:
        for d in ("up", "down", "left", "right"):
            pager.led_rgb(d, r, g, b)
    except Exception:
        pass


# ── Generic chrome helpers ───────────────────────────────────────────────

def header(pager, title: str, *, accent=None) -> None:
    accent = accent or ACCENT
    pager.fill_rect(0, HEADER_Y, W, HEADER_H, BLACK)
    if FONT_PATH:
        # Title-row baselines: ARGUS at the title size, the screen name
        # one notch smaller right next to it, version glyph far right.
        # All offsets give the ascenders enough room above so display
        # fonts don't bleed past the top edge.
        pager.draw_ttf(8, HEADER_Y + 4, "ARGUS", accent, FONT_PATH, FONT_TITLE)
        title_x = 8 + pager.ttf_width("ARGUS  ", FONT_PATH, FONT_TITLE)
        pager.draw_ttf(title_x, HEADER_Y + 8, title, WHITE, FONT_PATH, FONT_BODY)
        pager.draw_ttf_right(HEADER_Y + 10, "v2.0", GREY, FONT_PATH, FONT_SMALL, 8)
    else:
        pager.draw_text(8, HEADER_Y + 6, "ARGUS  " + title, accent, size=2)
    pager.hline(0, HEADER_Y + HEADER_H - 1, W, accent)


def footer(pager, hints: list[tuple[str, str]]) -> None:
    """Bottom hint bar. ``hints`` is ``[("A", "Continue"), ("B", "Back"), ...]``."""
    pager.fill_rect(0, FOOTER_Y - 1, W, FOOTER_H + 1, BLACK)
    pager.hline(0, FOOTER_Y - 1, W, GREY)
    x = 8
    y = FOOTER_Y + 6  # baseline padding for the larger FONT_SMALL
    for key, label in hints:
        # button pill
        if FONT_PATH:
            kw = pager.ttf_width(f" {key} ", FONT_PATH, FONT_SMALL) + 4
            pager.fill_rect(x, y - 2, kw, FONT_SMALL + 4, ACCENT)
            pager.draw_ttf(x + 3, y, key, BLACK, FONT_PATH, FONT_SMALL)
            x += kw + 6
            pager.draw_ttf(x, y, label, WHITE, FONT_PATH, FONT_SMALL)
            x += pager.ttf_width(label + "   ", FONT_PATH, FONT_SMALL)
        else:
            pager.draw_text(x, y, f"[{key}]{label}", WHITE, size=1)
            x += 80


def error_card(pager, title: str, body: str) -> None:
    pager.clear(BLACK)
    pager.fill_rect(0, 0, W, 30, RED)
    if FONT_PATH:
        pager.draw_ttf(10, 4, title, WHITE, FONT_PATH, FONT_TITLE)
    else:
        pager.draw_text(10, 8, title, WHITE, size=2)
    y = 40
    for line in body.splitlines()[:8]:
        if FONT_PATH:
            pager.draw_ttf(10, y, line[:60], WHITE, FONT_PATH, FONT_SMALL)
        else:
            pager.draw_text(10, y, line[:60], WHITE, size=1)
        y += 18
    pager.flip()


# ── Alert helpers (LED + vibrate gates) ──────────────────────────────────

def alert_low(pager) -> None:
    if _config.get("ui", {}).get("led_on_alert", True):
        _set_all_leds(pager, 0, 80, 0)


def alert_med(pager) -> None:
    if _config.get("ui", {}).get("led_on_alert", True):
        _set_all_leds(pager, 120, 80, 0)
    if _config.get("ui", {}).get("vibrate_on_alert", True):
        pager.vibrate(120)


def alert_high(pager) -> None:
    if _config.get("ui", {}).get("led_on_alert", True):
        _set_all_leds(pager, 160, 0, 0)
    if _config.get("ui", {}).get("vibrate_on_alert", True):
        try:
            # pagerctl wants a comma-string: "on_ms,off_ms,on_ms,..."
            pager.vibrate_pattern("180,80,180")
        except Exception:
            pass


def led_state(pager, name: str) -> None:
    """Named LED states matching v1.3 semantics."""
    table = {
        "init":   (0,   80, 80),    # cyan-ish blink (caller does blink)
        "scan":   (0,   40, 160),   # blue
        "pause":  (90,  60, 0),     # amber
        "ok":     (0,   120, 0),    # green
        "alert":  (160, 0,   0),    # red
        "off":    (0,   0,   0),
    }
    r, g, b = table.get(name, (0, 0, 0))
    if name == "off":
        try:
            pager.led_all_off()
        except Exception:
            pass
        return
    _set_all_leds(pager, r, g, b)
