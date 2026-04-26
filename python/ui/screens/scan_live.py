"""Live scan screen — round counter, ETA, data-quality lights, pause/stop."""
from __future__ import annotations

import time

from .. import theme as T
from .. import widgets as W
from core import scan_engine, data_quality, scheduler

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
    REDRAW_PERIOD = 0.3

    try:
        while not sched.is_done():
            # 1) advance scheduler — let it tick capture rounds
            engine.tick(sched)

            # 2) handle non-blocking input — poll_input returns
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
                # Global quit — stop the scan and bubble up to main loop
                sched.stop()
                engine.stop()
                state["_global_exit"] = True
                break

            # 3) periodic redraw
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


# ── drawing ─────────────────────────────────────────────────────────────

def _draw(pager, name, sched, engine, state, *, final: bool = False) -> None:
    pager.clear(T.BLACK)
    label = "DONE" if final else ("PAUSE" if sched.is_paused() else "SCAN")
    T.header(pager, f"{label}: {name}")

    # round + elapsed/eta
    round_idx = sched.current_round
    elapsed = sched.elapsed_total()
    total = sched.total_seconds()
    remaining = max(0, total - elapsed)
    progress = elapsed / total if total else 0.0

    if T.FONT_PATH:
        pager.draw_ttf(14, 36, f"Round {round_idx}/{sched.rounds}", T.WHITE,
                       T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_right(36, f"ETA {_fmt(remaining)}",
                             T.ACCENT, T.FONT_PATH, T.FONT_BODY, 14)
        pager.draw_ttf(14, 56, f"Elapsed {_fmt(elapsed)}", T.GREY,
                       T.FONT_PATH, T.FONT_SMALL)
    else:
        pager.draw_text(14, 38, f"Round {round_idx}/{sched.rounds}  ETA {_fmt(remaining)}",
                        T.WHITE, size=1)

    # progress bar
    W.progress_bar(pager, 14, 76, T.W - 28, 8, progress)

    # ── Data quality lights (computed once per draw) ─────────────────
    dq = data_quality.evaluate(state["config"], state["preset"], sched)
    y = 96
    for label_, status, detail in dq:
        W.quality_light(pager, 14, y, label_, status, detail)
        y += 22

    # Live counters from engine
    stats = engine.live_stats()
    if T.FONT_PATH:
        pager.draw_ttf(14, T.FOOTER_Y - 44,
                       f"WiFi {stats.get('wifi_devices', 0):3d}  "
                       f"BT {stats.get('bt_devices', 0):3d}  "
                       f"IMSI {stats.get('imsi', '--')}  "
                       f"GPS {stats.get('gps', '--')}",
                       T.WHITE, T.FONT_PATH, T.FONT_SMALL)
        # Deauth row - red if a flood was already seen, amber on elevated rate
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
        pager.draw_ttf(14, T.FOOTER_Y - 22,
                       f"{d_label} {d_total} frames"
                       f" ({d_rate:.1f}/s, floods {d_floods})",
                       d_color, T.FONT_PATH, T.FONT_SMALL)

    # footer hints
    if final:
        T.footer(pager, [("A", "Continue")])
    else:
        T.footer(pager, [("A", "Pause" if not sched.is_paused() else "Resume"),
                         ("B", "Stop")])
    pager.flip()


def _confirm_stop(pager) -> bool:
    """Tiny modal — A=stop, B=keep going."""
    pager.fill_rect(80, 60, T.W - 160, 100, T.DARK)
    pager.rect(80, 60, T.W - 160, 100, T.RED)
    if T.FONT_PATH:
        pager.draw_ttf_centered(78, "Stop scan?", T.RED, T.FONT_PATH, 22)
        pager.draw_ttf_centered(112, "Partial reports will still be saved.",
                                T.WHITE, T.FONT_PATH, T.FONT_SMALL)
        pager.draw_ttf_centered(140, "[A] Stop   [B] Continue",
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
