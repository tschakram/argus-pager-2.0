"""Preset definitions — STANDARD / DEEPSCAN / CUSTOM.

Defaults are duplicated in ``config.example.json`` so the user can override them
without touching code. ``from_config(cfg, name)`` returns a fresh dict for the
selected preset, falling back to the constants below if the config omits it.
"""
from __future__ import annotations

# Sensors marked True become enabled toggles in the scan-config screen.
# 'imsi_watch' / 'sms_watch' are background daemons — always-on if Mudi reachable.

STANDARD: dict = {
    "rounds": 4, "duration_s": 90,
    "wifi": True,  "bt": True,
    "gps_mudi": True,
    "cell": True, "cross_report": True,
    "cameras": False, "shodan": False,
    "imsi_watch": True, "sms_watch": True,
}

DEEPSCAN: dict = {
    "rounds": 6, "duration_s": 120,
    "wifi": True, "bt": True,
    "gps_mudi": True,
    "cell": True, "cross_report": True,
    "cameras": True, "shodan": True,
    "imsi_watch": True, "sms_watch": True,
}

CUSTOM: dict = {
    "rounds": 3, "duration_s": 60,
    "wifi": True, "bt": True,
    "gps_mudi": False,
    "cell": False, "cross_report": False,
    "cameras": False, "shodan": False,
    "imsi_watch": True, "sms_watch": True,
}

DEFAULTS = {"STANDARD": STANDARD, "DEEPSCAN": DEEPSCAN, "CUSTOM": CUSTOM}


def from_config(config: dict, name: str) -> dict:
    """Merge defaults with user overrides from config['presets'][name]."""
    base = DEFAULTS.get(name, CUSTOM).copy()
    user = (config.get("presets") or {}).get(name) or {}
    base.update({k: v for k, v in user.items() if not k.startswith("_")})
    return base
