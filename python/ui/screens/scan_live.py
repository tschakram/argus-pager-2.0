"""Live scan screen: round counter, ETA, data-quality lights, pause/stop.

Layout is computed from the FONT_* / *_Y constants in theme so the screen
adapts when font sizes change. When more quality-light rows than fit on
screen exist, UP/DOWN scrolls them; the footer shows that hint.
"""
from __future__ import annotations

import time

from .. import theme as T
from .. import widgets as W
from core import scan_engine, data_quality, scheduler

try:
    from pagerctl import BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER = 1, 2, 16, 32, 64


def run(pager, state) -> str:
    preset = state["preset"]
    name = state["preset_name"]
    rounds = int(preset["rounds"])
    duration = int(preset["duration_s"])

    sched = scheduler.Scheduler(rounds=rounds, duration_s=duration)
    engine = scan_engine.ScanEngine(state["config"], preset)

    state["scan_result"] = None
    sched.start()
    engine.start()
    T.led_state(pager, "scan")

    last_redraw = 0.0
    REDRAW_PERIOD = 0.3
    quality_scroll = 0

    try:
        while not sched.is_done():
            engine.tick(sched)

            # Non-blocking input - poll_input returns
            # (current, pressed, released) bitmasks, NOT a single button id.
            try:
                _curr, pressed, _rel = pager.poll_input()
            except Exception:
                pressed = 0
            if pressed & BTN_A:
                if sched.is_paused():
                    sched.resume()
                    engine.resume()
                    T.led_state(pager, "scan")
                else:
                    sched.pause()
                    engine.pause()
                    T.led_state(pager, "pause")
            elif pressed & BTN_B:
                if _confirm_stop(pager):
                    sched.stop()
                    engine.stop()
                    break
            elif pressed & BTN_UP:
                quality_scroll = max(0, quality_scroll - 1)
                last_redraw = 0  # force redraw
            elif pressed & BTN_DOWN:
                quality_scroll += 1
                last_redraw = 0
            elif pressed & BTN_POWER:
                sched.stop()
                engine.stop()
                state["_global_exit"] = True
                break

            now = time.monotonic()
            if now - last_redraw >= REDRAW_PERIOD:
                quality_scroll = _draw(
                    pager, name, sched, engine, state,
                    quality_scroll=quality_scroll,
                )
                last_redraw = now

            time.sleep(0.05)
    finally:
        # ensure capture child processes are reaped before moving on
        result = engine.finish()
        state["scan_result"] = result

    # final OK frame so the user knows the scan ended cleanly
    _draw(pager, name, sched, engine, state,
          quality_scroll=quality_scroll, final=True)
    T.led_state(pager, "ok")
    time.sleep(0.5)
    if state.get("_global_exit"):
        return None
    return "post_scan"


# drawing

def _draw(pager, name, sched, engine, state, *,
          quality_scroll: int = 0, final: bool = False) -> int:
    """Render one live-scan frame. Returns the (possibly clamped) scroll
    offset so the caller can keep it in sync."""
    pager.clear(T.BLACK)
    label = "DONE" if final else ("PAUSE" if sched.is_paused() else "SCAN")
    T.header(pager, f"{label}: {name}")

    round_idx = sched.current_round
    elapsed = sched.elapsed_total()
    total = sched.total_seconds()
    remaining = max(0, total - elapsed)
    progress = elapsed / total if total else 0.0

    # Top block: Round + ETA + Elapsed + progress-bar
    y = T.BODY_Y + 2
    if T.FONT_PATH:
        pager.draw_ttf(14, y, f"Round {round_idx}/{sched.rounds}", T.WHITE,
                       T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_right(y, f"ETA {_fmt(remaining)}",
                             T.ACCENT, T.FONT_PATH, T.FONT_BODY, 14)
        y += T.FONT_BODY + 4
        pager.draw_ttf(14, y, f"Elapsed {_fmt(elapsed)}", T.GREY,
                       T.FONT_PATH, T.FONT_SMALL)
        y += T.FONT_SMALL + 6
    else:
        pager.draw_text(14, y, f"Round {round_idx}/{sched.rounds}  ETA {_fmt(remaining)}",
                        T.WHITE, size=1)
        y += 18

    # Progress bar
    bar_y = y
    W.progress_bar(pager, 14, bar_y, T.W - 28, 10, progress)
    y = bar_y + 14

    # Live-stats footer (live counters + deauth row) - drawn fixed near
    # the bottom so the quality-light list above can scroll freely.
    stats = engine.live_stats()
    stats_block_h = (T.FONT_SMALL + 4) * 2 + 4
    stats_top = T.FOOTER_Y - stats_block_h - 2

    # Quality-light list - everything between `y` and `stats_top` is the
    # scrollable area.
    dq = data_quality.evaluate(state["config"], state["preset"], sched)
    line_h = T.FONT_BODY + 6
    list_h = max(line_h, stats_top - y - 2)
    visible = max(1, list_h // line_h)
    max_offset = max(0, len(dq) - visible)
    quality_scroll = max(0, min(quality_scroll, max_offset))

    row_y = y
    for i in range(visible):
        idx = quality_scroll + i
        if idx >= len(dq):
            break
        label_, status, detail = dq[idx]
        W.quality_light(pager, 14, row_y, label_, status, detail)
        row_y += line_h
    # scroll caret on the right side of the list
    if max_offset > 0:
        track_x = T.W - 6
        pager.fill_rect(track_x, y, 2, list_h, T.GREY)
        ind_h = max(8, int(list_h * visible / max(1, len(dq))))
        ind_y = y + int((list_h - ind_h) * quality_scroll / max(1, max_offset))
        pager.fill_rect(track_x - 2, ind_y, 6, ind_h, T.ACCENT)

    # Stats block - WiFi/BT/IMSI/GPS row + deauth row, both FONT_SMALL
    if T.FONT_PATH:
        sy = stats_top
        pager.draw_ttf(14, sy,
                       f"WiFi {stats.get('wifi_devices', 0):3d}  "
                       f"BT {stats.get('bt_devices', 0):3d}  "
                       f"IMSI {stats.get('imsi', '--')}  "
                       f"GPS {stats.get('gps', '--')}",
                       T.WHITE, T.FONT_PATH, T.FONT_SMALL)
        sy += T.FONT_SMALL + 4
        d_total  = int(stats.get("deauth", 0))
        d_rate   = float(stats.get("deauth_rate", 0.0))
        d_floods = int(stats.get("deauth_floods", 0))
        if d_floods > 0:
            d_color, d_label = T.RED,  "DEAUTH FLOOD"
            T.alert_high(pager)
        elif d_rate > 1.0:
            d_color, d_label = T.AMBER, "deauth busy"
        else:
            d_color, d_label = T.GREY,  "deauth"
        pager.draw_ttf(14, sy,
                       f"{d_label} {d_total} frames"
                       f" ({d_rate:.1f}/s, floods {d_floods})",
                       d_color, T.FONT_PATH, T.FONT_SMALL)

    # Footer hints - include scroll hint only if there is something to scroll
    hints = []
    if final:
        hints.append(("A", "Continue"))
    else:
        hints.append(("A", "Pause" if not sched.is_paused() else "Resume"))
        hints.append(("B", "Stop"))
    if max_offset > 0:
        hints.append(("UP/DN", "Scroll"))
    T.footer(pager, hints)
    pager.flip()
    return quality_scroll


def _confirm_stop(pager) -> bool:
    """Tiny modal: A=stop, B=keep going."""
    box_w = T.W - 120
    box_h = 110
    box_x = (T.W - box_w) // 2
    box_y = (T.H - box_h) // 2
    pager.fill_rect(box_x, box_y, box_w, box_h, T.DARK)
    pager.rect(box_x, box_y, box_w, box_h, T.RED)
    if T.FONT_PATH:
        pager.draw_ttf_centered(box_y + 8, "Stop scan?",
                                T.RED, T.FONT_PATH, T.FONT_TITLE)
        pager.draw_ttf_centered(box_y + 8 + T.FONT_TITLE + 6,
                                "Partial reports will be saved.",
                                T.WHITE, T.FONT_PATH, T.FONT_SMALL)
        pager.draw_ttf_centered(box_y + box_h - T.FONT_SMALL - 6,
                                "[A] Stop   [B] Continue",
                                T.GREY, T.FONT_PATH, T.FONT_SMALL)
    pager.flip()
    while True:
        btn = pager.wait_button()
        if btn == BTN_A:
            return True
        if btn == BTN_B:
            return False


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"
