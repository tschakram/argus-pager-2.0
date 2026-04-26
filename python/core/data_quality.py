"""Data-quality evaluator: returns a list of (label, status, detail) tuples
the live-scan screen renders as quality lights.

status ∈ {"ok", "wait", "off"}.

Thresholds come from config['data_quality']; defaults match the values in
config.example.json (CYT 180s, Cross-Report 3 rounds, Hotel 240s, …).
"""
from __future__ import annotations


_DEFAULTS = {
    "cyt_min_seconds":         180,
    "cross_report_min_rounds": 3,
    "hotel_min_seconds":       240,
    "shodan_min_rounds":       2,
    "camera_min_seconds":      120,
}


def _t(cfg: dict, key: str) -> int:
    return int((cfg.get("data_quality") or {}).get(key, _DEFAULTS[key]))


def evaluate(config: dict, preset: dict, sched) -> list[tuple[str, str, str]]:
    elapsed = int(sched.elapsed_total())
    round_idx = sched.current_round

    out: list[tuple[str, str, str]] = []

    # ── CYT analysis ────────────────────────────────────────────────
    cyt_target = _t(config, "cyt_min_seconds")
    if preset.get("wifi") or preset.get("bt"):
        if elapsed >= cyt_target:
            out.append(("CYT analysis", "ok", "ready"))
        else:
            out.append(("CYT analysis", "wait", f"{cyt_target - elapsed}s"))
    else:
        out.append(("CYT analysis", "off", "WiFi/BT off"))

    # ── Cross-Report ────────────────────────────────────────────────
    cr_target = _t(config, "cross_report_min_rounds")
    if preset.get("cross_report"):
        if round_idx >= cr_target:
            out.append(("Cross-Report", "ok", f"r{round_idx}"))
        else:
            out.append(("Cross-Report", "wait", f"need r{cr_target}"))
    else:
        out.append(("Cross-Report", "off", "disabled"))

    # ── Hotel-Scan ──────────────────────────────────────────────────
    if preset.get("cameras"):
        h_target = _t(config, "hotel_min_seconds")
        if elapsed >= h_target:
            out.append(("Hotel-Scan", "ok", "ready"))
        else:
            out.append(("Hotel-Scan", "wait", f"{h_target - elapsed}s"))

    # ── Shodan/WiGLE ────────────────────────────────────────────────
    if preset.get("shodan"):
        s_target = _t(config, "shodan_min_rounds")
        if round_idx >= s_target:
            out.append(("Shodan/WiGLE", "ok", f"r{round_idx}"))
        else:
            out.append(("Shodan/WiGLE", "wait", f"need r{s_target}"))

    return out
