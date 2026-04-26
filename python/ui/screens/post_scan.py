"""Post-scan sequence: Silent-SMS check, IMSI summary, OpenCelliD upload, IMEI rotate.

Convention used by the screens in this module:
- A button = primary / "yes" / continue
- B button = secondary / "no" / skip BUT also continues to the next step
  (not "back" - there is no going back during post-scan)
- POWER = abort the whole post-scan sequence and exit to the main loop
"""
from __future__ import annotations

import time

from .. import theme as T
from .. import widgets as W
from core import post_scan as core_post

try:
    from pagerctl import BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_A, BTN_B, BTN_POWER = 16, 32, 64


STEPS = ["Silent-SMS check", "IMSI alerts (2h)", "OpenCelliD upload", "IMEI rotation"]


def run(pager, state) -> str | None:
    cfg = state["config"]
    results: dict[str, str] = {}

    # Step 1 — Silent-SMS
    _step_header(pager, 1, "Silent-SMS check")
    sms = core_post.silent_sms_check(cfg)
    results["sms"] = sms
    _step_result(pager, "Silent-SMS", sms)
    if _wait_a(pager) == "exit":
        return None

    # Step 2 — IMSI summary
    _step_header(pager, 2, "IMSI alerts (last 2h)")
    imsi = core_post.imsi_summary(cfg)
    results["imsi"] = imsi
    _step_result(pager, "IMSI", imsi)
    if _wait_a(pager) == "exit":
        return None

    # Step 3 — OpenCelliD upload
    _step_header(pager, 3, "OpenCelliD upload")
    queued = core_post.upload_queue_count(cfg)
    if queued > 0:
        if _ask_yes_no(pager, f"{queued} measurements queued",
                       "[A] Upload   [B] Skip"):
            up_ok, up_fail = core_post.opencellid_upload(cfg)
            results["upload"] = f"ok={up_ok} fail={up_fail}"
        else:
            results["upload"] = "skipped"
    else:
        results["upload"] = "queue empty"
    _step_result(pager, "Upload", results["upload"])
    if _wait_a(pager) == "exit":
        return None

    # Step 4 — IMEI rotation
    _step_header(pager, 4, "IMEI rotation")
    if _ask_yes_no(pager, "Rotate IMEI before next scan?",
                   "[A] Rotate   [B] Keep"):
        rot = core_post.imei_rotate(cfg)
        results["imei"] = rot
    else:
        results["imei"] = "kept"
    _step_result(pager, "IMEI", results["imei"])
    if _wait_a(pager) == "exit":
        return None

    state["post_scan_result"] = results
    return "report"


# ── helpers ─────────────────────────────────────────────────────────────

def _step_header(pager, n: int, label: str) -> None:
    pager.clear(T.BLACK)
    T.header(pager, f"Post-scan: {n}/4")
    if T.FONT_PATH:
        pager.draw_ttf_centered(80, label, T.ACCENT, T.FONT_PATH, T.FONT_TITLE)
        pager.draw_ttf_centered(118, "running...", T.GREY, T.FONT_PATH, T.FONT_SMALL)
    pager.flip()


def _step_result(pager, label: str, body: str) -> None:
    if T.FONT_PATH:
        pager.fill_rect(0, 100, T.W, 80, T.BLACK)
        color = T.ACCENT
        low = body.lower()
        if "alert" in low or "fail" in low or "high" in low:
            color = T.RED
        elif "warn" in low or "queue" in low or "rotated" in low:
            color = T.AMBER
        pager.draw_ttf_centered(118, body[:48], color, T.FONT_PATH, T.FONT_BODY)
    T.footer(pager, [("A", "Continue"), ("B", "Continue")])
    pager.flip()


def _wait_continue(pager) -> str | None:
    """Wait for A or B (both continue). POWER aborts the sequence."""
    while True:
        btn = pager.wait_button()
        if btn in (BTN_A, BTN_B):
            return None
        if btn == BTN_POWER:
            return "exit"


# Backwards-compat alias for any callers still using _wait_a()
_wait_a = _wait_continue


def _ask_yes_no(pager, question: str, hint: str) -> bool:
    """A = yes, B = no. Both advance the sequence (no 'back' here).
    POWER also resolves to no, like B."""
    if T.FONT_PATH:
        pager.fill_rect(0, 80, T.W, 80, T.BLACK)
        pager.draw_ttf_centered(96, question, T.WHITE, T.FONT_PATH, T.FONT_BODY)
        pager.draw_ttf_centered(130, hint, T.GREY, T.FONT_PATH, T.FONT_SMALL)
    pager.flip()
    while True:
        btn = pager.wait_button()
        if btn == BTN_A:
            return True
        if btn in (BTN_B, BTN_POWER):
            return False
