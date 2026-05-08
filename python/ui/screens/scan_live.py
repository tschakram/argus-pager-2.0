"""Live scan screen: 3-button action panel + endless-rounds display.

States:
  IDLE     - waiting for the user to press SCAN LOS (BTN_LEFT)
  RUNNING  - capture is live, BTN_A = pause, BTN_B = stop
  PAUSED   - BTN_LEFT = resume, BTN_B = stop

When ``preset['rounds'] == 0`` the scheduler runs unbounded; the only way
out is BTN_B (stop), which jumps to the post-scan flow.
"""
from __future__ import annotations

import sys
import time

from .. import theme as T
from .. import widgets as W
from core import scan_engine, scheduler, mudi_client

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_A, BTN_B, BTN_LEFT, BTN_POWER = 16, 32, 4, 64

REDRAW_PERIOD = 0.5

# IMEI-rotate confirm modal: how long to wait for a button before
# defaulting to "no" and going straight to the report.
IMEI_CONFIRM_TIMEOUT_S = 10


def _log(msg: str) -> None:
    print(f"[scan_live] {msg}", file=sys.stderr, flush=True)


def run(pager, state) -> str:
    preset = state["preset"]
    name = state.get("preset_name") or preset.get("_name") or "AUTO"
    rounds = int(preset.get("rounds", 0))
    duration = int(preset.get("duration_s", 90))

    sched = scheduler.Scheduler(rounds=rounds, duration_s=duration)
    engine = scan_engine.ScanEngine(state["config"], preset)
    state["scan_result"] = None

    started = False
    last_redraw = 0.0
    T.led_state(pager, "init")

    try:
        while True:
            try:
                _curr, pressed, _rel = pager.poll_input()
            except Exception:
                pressed = 0

            if not started:
                if pressed & BTN_LEFT:
                    _log("SCAN LOS")
                    sched.start()
                    engine.start()
                    started = True
                    T.led_state(pager, "scan")
                elif pressed & BTN_POWER:
                    state["_global_exit"] = True
                    break
            else:
                engine.tick(sched)
                if sched.is_done():
                    break

                if pressed & BTN_LEFT and sched.is_paused():
                    _log("RESUME")
                    sched.resume()
                    engine.resume()
                    T.led_state(pager, "scan")
                elif pressed & BTN_A and sched.is_running():
                    _log("PAUSE")
                    sched.pause()
                    engine.pause()
                    T.led_state(pager, "pause")
                elif pressed & BTN_B:
                    if _confirm_stop(pager):
                        _log("STOP")
                        sched.stop()
                        engine.stop()
                        _draw_saving(pager, name)
                        break
                elif pressed & BTN_POWER:
                    sched.stop()
                    engine.stop()
                    state["_global_exit"] = True
                    break

            now = time.monotonic()
            if now - last_redraw >= REDRAW_PERIOD:
                _draw(pager, name, sched, engine, started)
                last_redraw = now
            time.sleep(0.05)
    finally:
        if started:
            # Run engine.finish() in a worker thread so we can keep the
            # "Saving report..." frame alive with a spinner + elapsed
            # counter. Without this the screen looks frozen for the 30-
            # 120s the analyser takes (cyt + cell_lookup + external_intel).
            import threading
            result_holder: dict = {}
            err_holder: dict = {}

            def _runner() -> None:
                try:
                    result_holder["r"] = engine.finish()
                except Exception as e:
                    err_holder["e"] = e

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            spinner = "|/-\\"
            tick = 0
            start_save = time.monotonic()
            while t.is_alive():
                elapsed = int(time.monotonic() - start_save)
                _draw_saving(pager, name,
                             spin=spinner[tick % 4],
                             elapsed_s=elapsed)
                tick += 1
                t.join(timeout=0.3)
            t.join()
            if err_holder:
                _log(f"engine.finish raised: {err_holder['e']}")
                state["scan_result"] = {
                    "threat_level": "low",
                    "findings":     [f"finish failed: {err_holder['e']}"],
                    "report_path":  None,
                }
            else:
                state["scan_result"] = result_holder.get("r")

    if not started:
        if state.get("_global_exit"):
            return None
        return None

    _draw(pager, name, sched, engine, started, final=True)
    T.led_state(pager, "ok")
    time.sleep(0.5)
    if state.get("_global_exit"):
        return None

    # Optional IMEI rotation before showing the report. Auto-default NO
    # after IMEI_CONFIRM_TIMEOUT_S so the user can put the pager down
    # without blocking on a confirmation. Only shown if Mudi is reachable.
    if mudi_client.is_reachable(state.get("config") or {}):
        if _imei_confirm_modal(pager):
            _imei_rotate(pager, state)
    return "report"


def _imei_confirm_modal(pager) -> bool:
    """Render a Yes/No card asking whether to rotate the Mudi IMEI.

    Returns True only on explicit BTN_LEFT (Yes). BTN_B / BTN_POWER /
    no-press-within-timeout all return False (so the run quietly
    continues to the report).
    """
    try:
        from pagerctl import BTN_UP, BTN_DOWN
    except ImportError:
        BTN_UP, BTN_DOWN = 1, 2

    pager.clear(T.BLACK)
    T.header(pager, "Rotate IMEI?")
    body_y = T.BODY_Y + 18
    msg = ["Rotate Mudi IMEI now?",
           "(needs ~30s reboot)",
           "",
           "no input = NO"]
    for ln in msg:
        if T.FONT_PATH:
            pager.draw_ttf_centered(body_y, ln, T.WHITE, T.FONT_PATH, T.FONT_BODY)
        else:
            pager.draw_text_centered(body_y, ln, T.WHITE, size=2)
        body_y += T.FONT_BODY + 4
    T.footer(pager, [("LEFT", "YES"), ("B", "NO")])
    pager.flip()

    deadline = time.monotonic() + IMEI_CONFIRM_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            _cur, pressed, _rel = pager.poll_input()
        except Exception:
            return False
        if pressed:
            if pressed & BTN_LEFT:
                return True
            if pressed & (BTN_B | BTN_POWER | BTN_A | BTN_UP | BTN_DOWN):
                return False
        time.sleep(0.1)
    _log(f"IMEI confirm timed out after {IMEI_CONFIRM_TIMEOUT_S}s -> NO")
    return False


def _imei_rotate(pager, state) -> None:
    """Show a 'rotating' frame while blue_merle does its thing on Mudi.

    The Mudi reboots after rotating, so the SSH call returns within a
    few seconds but Mudi-Internet is dead for ~30-60s afterwards. We
    don't wait for the reboot; the next scan's sense.discover() will
    notice it back.
    """
    pager.clear(T.BLACK)
    T.header(pager, "IMEI rotation")
    if T.FONT_PATH:
        pager.draw_ttf_centered(T.BODY_Y + 30, "Rotating Mudi IMEI...",
                                T.ACCENT, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_centered(T.BODY_Y + 60, "(Mudi rebooting)",
                                T.WHITE, T.FONT_PATH, T.FONT_SMALL)
    else:
        pager.draw_text_centered(T.BODY_Y + 30, "Rotating Mudi IMEI...",
                                 T.ACCENT, size=2)
    T.footer(pager, [("", "")])
    pager.flip()
    try:
        result = mudi_client.imei_rotate(state.get("config") or {})
        _log(f"imei_rotate result: {result}")
        # Stash for diagnostics; report.py doesn't surface this today.
        state.setdefault("post_scan_result", {})["imei_rotate"] = result or {}
    except Exception as exc:
        _log(f"imei_rotate failed: {exc}")
        state.setdefault("post_scan_result", {})["imei_rotate"] = {
            "error": str(exc),
        }


# ── drawing ─────────────────────────────────────────────────────────────

def _draw(pager, name, sched, engine, started, *, final: bool = False) -> None:
    pager.clear(T.BLACK)
    if not started:
        label = "READY"
    elif final:
        label = "DONE"
    elif sched.is_paused():
        label = "PAUSED"
    else:
        label = "SCAN"
    T.header(pager, f"{label}: {name}")

    if not started:
        _draw_idle_body(pager)
    else:
        _draw_active_body(pager, sched, engine)

    _draw_action_panel(pager, sched, started, final)
    pager.flip()


def _draw_idle_body(pager) -> None:
    if T.FONT_PATH:
        pager.draw_ttf_centered(T.BODY_Y + 18, "Press LEFT to start",
                                T.WHITE, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_centered(T.BODY_Y + 18 + T.FONT_BODY + 12,
                                "Auto-detected sensors will run.",
                                T.GREY, T.FONT_PATH, T.FONT_SMALL)
    else:
        pager.draw_text_centered(T.BODY_Y + 20, "Press LEFT to start", T.WHITE, size=2)


def _draw_active_body(pager, sched, engine) -> None:
    round_idx = sched.current_round
    round_elapsed = sched.round_elapsed()
    duration = max(1, sched.duration_s)
    round_progress = min(1.0, round_elapsed / duration)
    total_elapsed = sched.elapsed_total()

    if T.FONT_PATH:
        y1 = T.BODY_Y + 2
        if sched.is_unbounded():
            head_left = f"Round {round_idx}"
        else:
            head_left = f"Round {round_idx}/{sched.rounds}"
        pager.draw_ttf(14, y1, head_left, T.WHITE, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_right(y1, f"Total {_fmt(total_elapsed)}",
                             T.ACCENT, T.FONT_PATH, T.FONT_BODY, 14)

        y2 = y1 + T.FONT_BODY + 8
        elapsed_label = f"{_fmt(round_elapsed)}/{_fmt(duration)}"
        elapsed_w = pager.ttf_width(elapsed_label, T.FONT_PATH, T.FONT_SMALL)
        pager.draw_ttf(14, y2 - 2, elapsed_label, T.GREY,
                       T.FONT_PATH, T.FONT_SMALL)
        bar_x = 14 + elapsed_w + 8
        bar_w = T.W - bar_x - 14
        W.progress_bar(pager, bar_x, y2 + 2, bar_w, 12, round_progress)

        stats = engine.live_stats()
        y3 = y2 + 18 + 6
        wifi_dev    = int(stats.get("wifi_devices", 0))
        wifi_probes = int(stats.get("probe_total", 0))
        pager.draw_ttf(14, y3,
                       f"WiFi {wifi_dev}/{wifi_probes}   "
                       f"BT {stats.get('bt_devices', 0):3d}   "
                       f"GPS {stats.get('gps', '--')}",
                       T.WHITE, T.FONT_PATH, T.FONT_SMALL)

        y4 = y3 + T.FONT_SMALL + 6
        d_total = int(stats.get("deauth", 0))
        d_rate = float(stats.get("deauth_rate", 0.0))
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
        head = f"Round {round_idx}" + (f"/{sched.rounds}" if not sched.is_unbounded() else "")
        pager.draw_text(14, T.BODY_Y + 4, head, T.WHITE, size=1)
        W.progress_bar(pager, 14, T.BODY_Y + 30, T.W - 28, 10, round_progress)


def _draw_action_panel(pager, sched, started: bool, final: bool) -> None:
    """3-button strip: SCAN LOS / PAUSE / STOP. Active = accent, inactive = grey."""
    pager.fill_rect(0, T.FOOTER_Y - 1, T.W, T.FOOTER_H + 1, T.BLACK)
    pager.hline(0, T.FOOTER_Y - 1, T.W, T.GREY)

    if final:
        active = (False, False, False)
    elif not started:
        active = (True, False, False)         # only SCAN LOS
    elif sched.is_paused():
        active = (True, False, True)          # RESUME + STOP
    else:
        active = (False, True, True)          # PAUSE + STOP

    left_label = "RESUME" if started and sched.is_paused() else "SCAN LOS"
    btns = [
        ("L", left_label, active[0]),
        ("A", "PAUSE",    active[1]),
        ("B", "STOP",     active[2]),
    ]

    slot_w = T.W // 3
    pad = 8
    pill_w = 28
    if T.FONT_PATH:
        ty = T.FOOTER_Y + 6
        for i, (key, label, on) in enumerate(btns):
            x = i * slot_w + pad
            pill_bg = T.ACCENT if on else T.GREY
            pager.fill_rect(x, ty - 2, pill_w, T.FONT_SMALL + 4, pill_bg)
            pager.draw_ttf(x + 7, ty, key, T.BLACK, T.FONT_PATH, T.FONT_SMALL)
            label_col = T.WHITE if on else T.GREY
            pager.draw_ttf(x + pill_w + 6, ty, label,
                           label_col, T.FONT_PATH, T.FONT_SMALL)
    else:
        x = 8
        y = T.FOOTER_Y + 6
        for key, label, on in btns:
            col = T.WHITE if on else T.GREY
            pager.draw_text(x, y, f"[{key}]{label}", col, size=1)
            x += slot_w


def _draw_saving(pager, name: str, *,
                 spin: str = " ", elapsed_s: int = 0) -> None:
    """Shown while engine.finish() runs cyt + external intel + cellular
    lookup + report rendering. With a 30-PCAP session the analyser
    typically takes 60-120s, so we redraw with a spinner and elapsed
    counter to make clear the device is alive."""
    pager.clear(T.BLACK)
    T.header(pager, f"DONE: {name}")
    head = f"Saving report {spin}"
    sub  = f"{elapsed_s:3d}s"
    if T.FONT_PATH:
        pager.draw_ttf_centered(T.BODY_Y + 18, head,
                                T.WHITE, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_centered(T.BODY_Y + 18 + T.FONT_BODY + 12,
                                sub, T.ACCENT, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_centered(T.BODY_Y + 18 + (T.FONT_BODY + 12) * 2,
                                "do not switch off",
                                T.GREY, T.FONT_PATH, T.FONT_SMALL)
    else:
        pager.draw_text_centered(T.BODY_Y + 20, head, T.WHITE, size=2)
        pager.draw_text_centered(T.BODY_Y + 50, sub, T.ACCENT, size=2)
    T.led_state(pager, "init")
    pager.flip()


def _confirm_stop(pager) -> bool:
    """Modal: A = continue scanning, B = confirm stop. Red B is destructive."""
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
            return False
        if btn == BTN_B:
            return True


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"
