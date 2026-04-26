"""Report-view screen: threat-card summary, optional full Markdown scroll."""
from __future__ import annotations

import time
from pathlib import Path

from .. import theme as T
from .. import widgets as W

try:
    from pagerctl import BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER
except ImportError:  # pragma: no cover
    BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_POWER = 1, 2, 16, 32, 64


def run(pager, state) -> str | None:
    result = state.get("scan_result") or {}
    post = state.get("post_scan_result") or {}

    level = result.get("threat_level", "low")
    findings = result.get("findings", [])

    # Card overview
    pager.clear(T.BLACK)
    T.header(pager, "Report")

    summary_lines = []
    summary_lines += findings[:4]
    if post.get("imsi"):
        summary_lines.append(f"IMSI: {post['imsi']}")
    if post.get("sms"):
        summary_lines.append(f"SMS:  {post['sms']}")
    if not summary_lines:
        summary_lines = ["no findings"]

    W.threat_card(pager, x=14, y=T.BODY_Y + 10, w=T.W - 28, h=130,
                  level=level, lines=summary_lines)

    T.footer(pager, [("A", "View Report"), ("B", "Exit")])
    pager.flip()

    while True:
        btn = pager.wait_button()
        if btn == BTN_A:
            _scroll_report(pager, result, post, state.get("preset_name", "?"))
        elif btn in (BTN_B, BTN_POWER):
            return None


# helpers

def _scroll_report(pager, result: dict, post: dict, preset_name: str) -> None:
    """Scroll either the analyser markdown report, or a synthetic fallback
    built from the in-memory result dict (used when the cyt/raypager submodules
    didn't produce a .md file, e.g. before they're installed)."""
    text = _load_or_synthesize(result, post, preset_name)
    lines = [ln.rstrip()[:60] for ln in text.splitlines()]
    if not lines:
        lines = ["(empty report)"]

    line_h = T.FONT_SMALL + 4
    visible = (T.FOOTER_Y - T.BODY_Y - 10) // line_h
    offset = 0
    max_offset = max(0, len(lines) - visible)

    while True:
        pager.clear(T.BLACK)
        T.header(pager, "Report: scroll")
        y = T.BODY_Y + 6
        for ln in lines[offset:offset + visible]:
            if T.FONT_PATH:
                pager.draw_ttf(8, y, ln, T.WHITE, T.FONT_PATH, T.FONT_SMALL)
            else:
                pager.draw_text(8, y, ln, T.WHITE, size=1)
            y += line_h
        # scroll indicator on right edge
        if max_offset > 0:
            ind_y = T.BODY_Y + int((T.FOOTER_Y - T.BODY_Y - 10) * offset / max_offset)
            pager.fill_rect(T.W - 4, T.BODY_Y, 2, T.FOOTER_Y - T.BODY_Y - 4, T.GREY)
            pager.fill_rect(T.W - 6, ind_y, 6, 18, T.ACCENT)

        T.footer(pager, [("UP/DN", "Scroll"), ("B", "Back")])
        pager.flip()

        btn = pager.wait_button()
        if btn == BTN_UP:
            offset = max(0, offset - visible // 2)
        elif btn == BTN_DOWN:
            offset = min(max_offset, offset + visible // 2)
        elif btn in (BTN_A, BTN_B, BTN_POWER):
            return


def _load_or_synthesize(result: dict, post: dict, preset_name: str) -> str:
    path = result.get("report_path")
    if path and Path(path).exists():
        try:
            return Path(path).read_text("utf-8", errors="replace")
        except Exception:
            pass

    out: list[str] = []
    out.append(f"# Argus Pager 2.0 - {preset_name}")
    out.append(f"# {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("")
    out.append(f"Threat level: {result.get('threat_level', 'unknown').upper()}")
    out.append("")
    out.append("## Findings")
    for f in result.get("findings") or ["(none)"]:
        out.append(f"- {f}")
    out.append("")
    if post:
        out.append("## Post-scan")
        for k in ("sms", "imsi", "upload", "imei"):
            v = post.get(k)
            if v:
                out.append(f"- {k:7s}: {v}")
        out.append("")
    if not result.get("report_path"):
        out.append("(No analyser report on disk - showing in-memory summary.")
        out.append("Install cyt + raypager submodules to enable full reports.)")
    return "\n".join(out)
