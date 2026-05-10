"""Hunt-Screen — RSSI-Live-Anzeige + Bar + Sparkline + LED/Vibrate.

Endlos-Loop bis BTN_B oder Auto-Idle-Exit (5 min ohne Sample). poll_input
wird in jedem 50ms-Tick abgefragt — Stop greift sofort.
"""
from __future__ import annotations

import collections
import time

from ui import theme as T

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_POWER = 16, 32, 4, 64

# RSSI-Schwellen (dBm)
T_RED    = -55   # IM RAUM (gleicher Tisch / unter 3m)
T_YELLOW = -70   # NAEHER (durch Wand, Nachbarraum)
T_BLUE   = -80   # NEBENAN (mehrere Waende)
                # darunter = WEIT

SIGNAL_TIMEOUT_S = 4.0     # nach 4s ohne neues Sample: "kein Signal"
IDLE_EXIT_S      = 300.0   # nach 5 Min ohne Signal: auto-exit
REDRAW_PERIOD    = 0.2     # 5 Hz reicht fuer 480x222
HISTORY_LEN      = 60      # 60 Samples Sparkline (~30s bei 2Hz)
VIB_GAP_S        = 1.0     # Vibration max alle 1s, nicht durchgaengig


def hunt_loop(pager, target: dict, sampler, mode: str) -> None:
    history: collections.deque[int] = collections.deque(maxlen=HISTORY_LEN)
    last_rssi: int | None = None
    rssi_max: int | None = None
    last_signal_t = time.monotonic()
    last_vib_t = 0.0
    last_draw_t = 0.0
    last_status = ""

    sampler.start()
    try:
        while True:
            try:
                _curr, pressed, _rel = pager.poll_input()
            except Exception:
                pressed = 0

            if pressed & BTN_B or pressed & BTN_POWER:
                break

            # Drain neue Samples
            new = sampler.drain()
            if new:
                for v in new:
                    history.append(v)
                    if rssi_max is None or v > rssi_max:
                        rssi_max = v
                last_rssi = new[-1]
                last_signal_t = time.monotonic()

            now = time.monotonic()
            since_signal = now - last_signal_t

            # "Kein Signal" wenn lange nichts kam
            if since_signal > SIGNAL_TIMEOUT_S:
                effective = None
            else:
                effective = last_rssi

            # Status / LED / Vibrate
            status = _classify(effective)
            if status != last_status:
                _apply_led(pager, status)
                last_status = status
            if status in ("red", "yellow", "blue") and (now - last_vib_t) > VIB_GAP_S:
                _vibrate(pager, status)
                last_vib_t = now

            # Auto-Exit wenn lange kein Signal
            if since_signal > IDLE_EXIT_S:
                break

            if now - last_draw_t >= REDRAW_PERIOD:
                _draw(pager, target, mode, effective, rssi_max, history,
                      status, since_signal)
                last_draw_t = now

            time.sleep(0.05)
    finally:
        sampler.stop()
        try:
            T.led_state(pager, "off")
        except Exception:
            pass


# ── Helpers ──────────────────────────────────────────────────────

def _classify(rssi: int | None) -> str:
    if rssi is None:
        return "none"
    if rssi >= T_RED:
        return "red"
    if rssi >= T_YELLOW:
        return "yellow"
    if rssi >= T_BLUE:
        return "blue"
    return "green"


def _apply_led(pager, status: str) -> None:
    name = {
        "red":    "alert",
        "yellow": "pause",
        "blue":   "scan",
        "green":  "ok",
        "none":   "off",
    }.get(status, "off")
    try:
        T.led_state(pager, name)
    except Exception:
        pass


def _vibrate(pager, status: str) -> None:
    try:
        if status == "red":
            pager.vibrate_pattern("180,80,180")
        elif status == "yellow":
            pager.vibrate(150)
        else:
            pager.vibrate(60)
    except Exception:
        pass


# ── Drawing ──────────────────────────────────────────────────────

_STATUS_PALETTE = {
    "red":    (T.RED,    "IM RAUM"),
    "yellow": (T.AMBER,  "NAEHER"),
    "blue":   (T.CYAN,   "NEBENAN"),
    "green":  (T.ACCENT, "WEIT WEG"),
    "none":   (T.GREY,   "kein Signal"),
}


def _draw(pager, target: dict, mode: str, rssi: int | None,
          rssi_max: int | None, history, status: str,
          since_signal: float) -> None:
    pager.clear(T.BLACK)
    color, status_text = _STATUS_PALETTE.get(status, (T.GREY, "?"))

    # Header
    sub = ("WiFi" if mode == "wifi" else "BT") + " - " + target["mac"][-8:]
    T.header(pager, "FINDER " + sub, accent=color)

    # Body Layout
    body_top = T.BODY_Y
    # Grosse RSSI-Zahl (FONT_TITLE) auf der linken Haelfte
    if T.FONT_PATH:
        big = f"{rssi} dBm" if rssi is not None else "--- dBm"
        pager.draw_ttf(10, body_top, big, color, T.FONT_PATH, T.FONT_TITLE)
        # Status rechts neben der Zahl, einzeilig
        pager.draw_ttf_right(body_top + 4, status_text, color,
                             T.FONT_PATH, T.FONT_BODY, 12)
        # Zweite Zeile: max + samples + age
        line2_y = body_top + T.FONT_TITLE + 6
        max_text = f"max {rssi_max} dBm" if rssi_max is not None else "max --"
        age = f"{since_signal:.0f}s" if since_signal < 999 else "--"
        info = f"{max_text}   age {age}"
        pager.draw_ttf(10, line2_y, info, T.GREY, T.FONT_PATH, T.FONT_SMALL)

    # Bar -100..0 dBm
    bar_y = body_top + T.FONT_TITLE + T.FONT_SMALL + 14
    bar_x = 10
    bar_w = T.W - 20
    bar_h = 18
    pager.fill_rect(bar_x, bar_y, bar_w, bar_h, T.DARK)
    pager.rect(bar_x, bar_y, bar_w, bar_h, T.GREY)
    # Threshold-marker bei -55, -70, -80 (dBm) auf der bar
    for thr, c in ((T_RED, T.RED), (T_YELLOW, T.AMBER), (T_BLUE, T.CYAN)):
        x = bar_x + int((thr + 100) / 100.0 * bar_w)
        pager.fill_rect(x, bar_y - 3, 2, bar_h + 6, c)
    if rssi is not None:
        pos = max(0, min(bar_w - 4, int((rssi + 100) / 100.0 * bar_w)))
        pager.fill_rect(bar_x + pos - 3, bar_y - 4, 7, bar_h + 8, color)

    # Sparkline darunter
    spark_y = bar_y + bar_h + 10
    spark_h = 36
    pager.fill_rect(bar_x, spark_y, bar_w, spark_h, T.DARK)
    pager.rect(bar_x, spark_y, bar_w, spark_h, T.GREY)
    if history:
        n = len(history)
        # x-step abh. von n
        step = max(1, bar_w // max(1, HISTORY_LEN))
        for i, v in enumerate(history):
            # map -100..-30 auf 0..spark_h-2
            y_norm = max(0, min(1.0, (v + 100) / 70.0))
            py = spark_y + spark_h - 2 - int(y_norm * (spark_h - 4))
            px = bar_x + 2 + i * step
            if px < bar_x + bar_w - 1:
                pager.fill_rect(px, py, max(1, step - 1), 2, color)

    # Footer
    T.footer(pager, [("B", "Stop"), ("A", "(reserved)")])
    pager.flip()
