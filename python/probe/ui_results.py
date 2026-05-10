"""Ergebnis-Anzeige fuer GATT-Probe.

Scrollbare Key/Value-Liste mit allen ausgelesenen Charakteristiken.
BTN_UP/DN scrollt, BTN_B beendet.
"""
from __future__ import annotations

import time

from ui import theme as T
from . import opsec

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER = 16, 32, 4, 1, 2, 64

REDRAW_PERIOD = 0.2


def _build_lines(result: dict) -> list[tuple[str, str]]:
    """Konvertiert probe-result-dict in (label, value)-Liste."""
    lines: list[tuple[str, str]] = []
    lines.append(("MAC", opsec.short_mac(result.get("mac", ""))))
    lines.append(("Address Type", result.get("addr_type", "?")))
    if not result.get("reachable"):
        lines.append(("Status", "NICHT erreichbar"))
        for err in result.get("errors", [])[:3]:
            lines.append(("Fehler", err[:38]))
        return lines

    lines.append(("Status", "OK"))
    data = result.get("data", {})
    # Wichtigste zuerst
    priority_keys = ["device_name", "manufacturer", "model_number",
                     "appearance", "firmware_rev", "hardware_rev",
                     "software_rev", "serial_number"]
    for key in priority_keys:
        if key in data:
            d = data[key]
            label = d.get("label", key)
            val = d.get("decoded") or d.get("raw_hex") or "?"
            if val:
                lines.append((label, str(val)[:38]))

    # PnP-ID + System-ID falls vorhanden
    for key in ("pnp_id", "system_id"):
        if key in data:
            d = data[key]
            val = d.get("decoded") or d.get("raw_hex") or ""
            if val:
                lines.append((d.get("label", key), str(val)[:38]))

    # Service-Liste
    services = result.get("services", [])
    if services:
        lines.append(("---", "---"))
        lines.append(("Services", f"{len(services)} found"))
        for s in services[:8]:
            lines.append(("  uuid", s[:38]))

    return lines


def show_results(pager, result: dict) -> None:
    """Zeigt Ergebnis scrollbar bis BTN_B."""
    lines = _build_lines(result)
    scroll = 0
    last_redraw = 0.0
    visible = 8

    while True:
        try:
            _curr, pressed, _rel = pager.poll_input()
        except Exception:
            pressed = 0
        if pressed & BTN_UP:
            scroll = max(0, scroll - 1)
            last_redraw = 0
        elif pressed & BTN_DOWN:
            scroll = min(max(0, len(lines) - visible), scroll + 1)
            last_redraw = 0
        elif pressed & (BTN_B | BTN_POWER | BTN_LEFT | BTN_A):
            break

        now = time.monotonic()
        if now - last_redraw >= REDRAW_PERIOD:
            _draw_results(pager, lines, scroll, visible)
            last_redraw = now
        time.sleep(0.05)


def _draw_results(pager, lines: list, scroll: int, visible: int) -> None:
    pager.clear(T.BLACK)
    T.header(pager, "PROBE Result")

    y = T.BODY_Y
    row_h = T.FONT_SMALL + 4
    for i in range(visible):
        idx = scroll + i
        if idx >= len(lines):
            break
        label, val = lines[idx]
        if T.FONT_PATH:
            pager.draw_ttf(8, y, label[:18], T.GREY,
                           T.FONT_PATH, T.FONT_SMALL)
            pager.draw_ttf(170, y, str(val)[:32], T.WHITE,
                           T.FONT_PATH, T.FONT_SMALL)
        y += row_h

    if scroll + visible < len(lines):
        if T.FONT_PATH:
            pager.draw_ttf_right(T.FOOTER_Y - T.FONT_SMALL - 4, "v scroll v",
                                 T.GREY, T.FONT_PATH, T.FONT_SMALL, 8)

    T.footer(pager, [("UP/DN", "Scroll"), ("B", "Done")])
    pager.flip()


def show_message(pager, title: str, body: str) -> None:
    """Einfache Info-Card mit Buttonwait."""
    T.error_card(pager, T.ascii_safe(title), T.ascii_safe(body))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            _, pressed, _ = pager.poll_input()
        except Exception:
            pressed = 0
        if pressed & (BTN_A | BTN_B | BTN_LEFT | BTN_POWER):
            return
        time.sleep(0.05)


def show_progress(pager, target_short: str, step: str,
                  current: int, total: int) -> None:
    """Spinner-Frame waehrend des Probe."""
    pager.clear(T.BLACK)
    T.header(pager, "PROBE laeuft...")
    if T.FONT_PATH:
        pager.draw_ttf(8, T.BODY_Y, f"Target: {target_short}",
                       T.WHITE, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf(8, T.BODY_Y + T.FONT_BODY + 10,
                       f"Read: {step}", T.ACCENT, T.FONT_PATH, T.FONT_SMALL)
        # Progress bar
        bar_y = T.BODY_Y + T.FONT_BODY + T.FONT_SMALL + 30
        bar_w = T.W - 20
        pager.fill_rect(10, bar_y, bar_w, 14, T.DARK)
        pager.rect(10, bar_y, bar_w, 14, T.GREY)
        if total > 0:
            fill = int((bar_w - 2) * current / total)
            pager.fill_rect(11, bar_y + 1, fill, 12, T.ACCENT)
        pager.draw_ttf(10, bar_y + 22, f"{current}/{total}",
                       T.GREY, T.FONT_PATH, T.FONT_SMALL)
    pager.flip()
