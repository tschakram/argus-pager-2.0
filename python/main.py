#!/usr/bin/env python3
"""argus-pager 2.0 — main entry.

Owns the framebuffer for the whole session via pagerctl. Drives a stack-based
screen machine: each screen returns a (next_screen, payload) tuple. The loop
keeps running until a screen returns ``None``.

Run from payload.sh — that script sets PYTHONPATH so ``pagerctl`` and the
``ui`` / ``core`` packages are importable.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# Aggressive boot tracing — every step prints to stderr (which payload.sh
# redirects to /tmp/argus.log). If main.py hangs we still know exactly where.
def _log(msg: str) -> None:
    print(f"[main] {msg}", file=sys.stderr, flush=True)

_log("import: pagerctl")
sys.path.insert(0, "/mmc/root/lib/pagerctl")

try:
    import pagerctl  # noqa: F401
    from pagerctl import Pager
except ImportError as exc:  # pragma: no cover
    print(f"FATAL: pagerctl not importable: {exc}", file=sys.stderr, flush=True)
    sys.exit(1)

# pagerctl exposes button constants on the Pager class, NOT at module level.
# Re-export at module level so `from pagerctl import BTN_A` works in screens.
for _name in ("BTN_A", "BTN_B", "BTN_UP", "BTN_DOWN", "BTN_LEFT", "BTN_RIGHT", "BTN_POWER"):
    if not hasattr(pagerctl, _name) and hasattr(Pager, _name):
        setattr(pagerctl, _name, getattr(Pager, _name))

_log("import: ui + core")
from ui import theme
from ui.screens import splash, preset_menu, scan_config, scan_live, post_scan, report_view
from core import presets, screenshot

PAYLOAD_DIR = Path(os.environ.get("ARGUS_PAYLOAD_DIR", Path(__file__).resolve().parent.parent))
CONFIG_PATH = PAYLOAD_DIR / "config.json"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


SCREENS = {
    "splash":      splash.run,
    "preset_menu": preset_menu.run,
    "scan_config": scan_config.run,
    "scan_live":   scan_live.run,
    "post_scan":   post_scan.run,
    "report":      report_view.run,
}


def main() -> int:
    _log(f"load_config: {CONFIG_PATH}")
    config = load_config()
    _log("Pager()")
    pager = Pager()
    _log("pager.init() — initialize LCD hardware")
    rc = pager.init()
    if rc != 0:
        print(f"FATAL: pager.init() returned {rc}", file=sys.stderr, flush=True)
        return 3
    # LCD native is portrait (222x480). 270° = landscape (480x222), which is
    # what all our screen layouts assume.
    _log("set_rotation(270) — landscape")
    pager.set_rotation(270)
    _log(f"logical screen: {pager.width}x{pager.height}")
    _log(f"set_brightness({config.get('ui', {}).get('brightness', 80)})")
    pager.set_brightness(config.get("ui", {}).get("brightness", 80))
    pager.screen_on()
    _log("theme.init")
    theme.init(pager, config)
    # Optional auto-screenshot (env: ARGUS_SCREENSHOTS=1). Hooks pager.flip().
    screenshot.install(pager)
    if screenshot.is_enabled():
        _log("screenshot mode ENABLED")

    state: dict = {
        "config":  config,
        "preset":  presets.STANDARD.copy(),
        "preset_name": "STANDARD",
        "scan_result": None,
        "post_scan_result": None,
    }

    next_screen = "splash"
    try:
        while next_screen is not None:
            handler = SCREENS.get(next_screen)
            if handler is None:
                print(f"unknown screen: {next_screen!r}", file=sys.stderr, flush=True)
                break
            _log(f"-> enter screen: {next_screen}")
            screenshot.mark_screen(next_screen)
            next_screen = handler(pager, state)
            _log(f"<- exit screen, next={next_screen!r}")
    except KeyboardInterrupt:
        pass
    except Exception:  # pragma: no cover
        traceback.print_exc()
        # Show a final error card so the user sees something
        try:
            theme.error_card(pager, "Fatal error", traceback.format_exc(limit=4))
            pager.wait_button()
        except Exception:
            pass
        return 2
    finally:
        try:
            theme.shutdown(pager)
        except Exception:
            pass
        try:
            pager.cleanup()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
