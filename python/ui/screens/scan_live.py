"""Live scan screen: round counter, ETA, progress, live counters, pause/stop.

Layout is computed from the FONT_* / *_Y constants in theme so the screen
adapts when font sizes change.

Composition (top to bottom):
  - Round / ETA row          (FONT_BODY)
  - Progress bar             (12 px)
  - Stats line 1: WiFi+BT+GPS (FONT_SMALL)
  - Stats line 2: IMSI + Deauth (FONT_SMALL)
  - Footer (Pause / Stop hints)

We deliberately do NOT show the data-quality "lights" here anymore - on
the 480x222 LCD with FONT_BODY=28 there isn't enough vertical room to
fit them without overlapping the live-stats block, and the user gets
the same information cleanly in the Post-scan + Report screens after
the run.
"""
from __future__ import annotations

import time

from .. import theme as T
from .. import widgets as W
from core import scan_engine, scheduler

try:
    from pagerctl import BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_A, BTN_B, BTN_POWER = 16, 32, 64


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
    REDRAW_PERIOD = 0.5  # 2 fps is plenty for round/ETA - keeps CPU low
                         # so screenshot encoding never blocks the UI

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
            elif pressed & BTN_POWER:
                sched.stop()
                engine.stop()
                state["_global_exit"] = True
                break

            now = time.monotonic()
            if now - last_redraw >= REDRAW_PERIOD:
                _draw(pager, name, sched, engine, state)
                last_redraw = now

            time.sleep(0.05)
    finally:
        # ensure capture child processes are reaped before moving on
        result = engine.finish()
        state["scan_result"] = result

    # final OK frame so the user knows the scan ended cleanly
    _draw(pager, name, sched, engine, state, final=True)
    T.led_state(pager, "ok")
    time.sleep(0.5)
    if state.get("_global_exit"):
        return None
    return "post_scan"


# drawing

def _draw(pager, name, sched, engine, state, *, final: bool = False) -> None:
    """Render one live-scan frame. Layout is fixed (no scroll state) -
    we ditched the quality-light list so everything fits on the body
    without overlapping the live-stats block.
    """
    pager.clear(T.BLACK)
    label = "DONE" if final else ("PAUSE" if sched.is_paused() else "SCAN")
    T.header(pager, f"{label}: {name}")

    round_idx = sched.current_round
    elapsed   = sched.elapsed_total()
    total     = sched.total_seconds()
    remaining = max(0, total - elapsed)
    progress  = elapsed / total if total else 0.0

    if T.FONT_PATH:
        # Row 1: Round X/Y                        ETA mm:ss
        y1 = T.BODY_Y + 2
        pager.draw_ttf(14, y1, f"Round {round_idx}/{sched.rounds}",
                       T.WHITE, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_right(y1, f"ETA {_fmt(remaining)}",
                             T.ACCENT, T.FONT_PATH, T.FONT_BODY, 14)

        # Row 2: progress bar with Elapsed text inline (left of the bar)
        y2 = y1 + T.FONT_BODY + 8
        elapsed_label = f"{_fmt(elapsed)}"
        elapsed_w = pager.ttf_width(elapsed_label, T.FONT_PATH, T.FONT_SMALL)
        pager.draw_ttf(14, y2 - 2, elapsed_label, T.GREY,
                       T.FONT_PATH, T.FONT_SMALL)
        bar_x = 14 + elapsed_w + 8
        bar_w = T.W - bar_x - 14
        W.progress_bar(pager, bar_x, y2 + 2, bar_w, 12, progress)

        # Row 3: WiFi  BT  GPS                       (FONT_SMALL)
        # Row 4: IMSI  Deauth                        (FONT_SMALL, color-coded)
        stats = engine.live_stats()
        y3 = y2 + 18 + 6
        pager.draw_ttf(14, y3,
                       f"WiFi {stats.get('wifi_devices', 0):3d}    "
                       f"BT {stats.get('bt_devices', 0):3d}    "
                       f"GPS {stats.get('gps', '--')}",
                       T.WHITE, T.FONT_PATH, T.FONT_SMALL)

        y4 = y3 + T.FONT_SMALL + 6
        d_total  = int(stats.get("deauth",        0))
        d_rate   = float(stats.get("deauth_rate", 0.0))
        d_floods = int(stats.get("deauth_floods", 0))
        if d_floods > 0:
            d_color, d_label = T.RED, "DEAUTH FLOOD!"
            T.alert_high(pager)
        elif d_rate > 1.0:
            d_color, d_label = T.AMBER, f"deauth busy {d_total}"
        else:
            d_color, d_label = T.WHITE, f"deauth {d_total}"
        pager.draw_ttf(14, y4,
                       f"IMSI {stats.get('imsi', '--'):8s}    {d_label}",
                       d_color, T.FONT_PATH, T.FONT_SMALL)
    else:
        # bitmap-font fallback
        pager.draw_text(14, T.BODY_Y + 4,
                        f"Round {round_idx}/{sched.rounds}  ETA {_fmt(remaining)}",
                        T.WHITE, size=1)
        W.progress_bar(pager, 14, T.BODY_Y + 30, T.W - 28, 10, progress)

    # Footer hints
    if final:
        T.footer(pager, [("A", "Continue")])
    else:
        T.footer(pager, [("A", "Pause" if not sched.is_paused() else "Resume"),
                         ("B", "Stop")])
    pager.flip()


def _confirm_stop(pager) -> bool:
    """Tiny modal: A (green) = continue scanning, B (red) = stop.

    Convention: red B is the destructive answer everywhere in the UI,
    green A is the safe / continue answer. So in this stop-confirmation
    we make A the "no, keep going" button and B the "yes, really stop"
    button - matching the red-light/green-light intuition the user
    already has from outside the modal (B in scan_live opens this dialog
    in the first place because B == abort).
    """
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
                                "[A] Continue   [B] Stop",
                                T.GREY, T.FONT_PATH, T.FONT_SMALL)
    pager.flip()
    while True:
        btn = pager.wait_button()
        if btn == BTN_A:
            return False  # continue scanning
        if btn == BTN_B:
            return True   # confirm stop


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"
