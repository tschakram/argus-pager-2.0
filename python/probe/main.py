#!/usr/bin/env python3
"""Argus Probe - Entry-Point.

Vom payload.sh als
    python3 -u probe/main.py
gestartet. PYTHONPATH zeigt auf .../python/ und .../pagerctl/.

Flow:
  pager-init -> mode_select -> target_select -> warning -> [optional MAC-spoof]
  -> probe-execute -> show_results -> [restore MAC] -> back to mode_select
  oder exit.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# pagerctl-Setup wie main.py
sys.path.insert(0, "/mmc/root/lib/pagerctl")
try:
    import pagerctl
    from pagerctl import Pager
except ImportError as exc:
    print(f"FATAL: pagerctl nicht importierbar: {exc}", file=sys.stderr, flush=True)
    sys.exit(1)

for _name in ("BTN_A", "BTN_B", "BTN_UP", "BTN_DOWN", "BTN_LEFT",
              "BTN_RIGHT", "BTN_POWER"):
    if not hasattr(pagerctl, _name) and hasattr(Pager, _name):
        setattr(pagerctl, _name, getattr(Pager, _name))

from ui import theme as T
from probe import opsec, ui_mode_select, ui_target, ui_results
from probe.backends import bt_gatt, network_nmap, mdns_ssdp


def _log(msg: str) -> None:
    print(f"[probe] {msg}", file=sys.stderr, flush=True)


def _load_config(payload_dir: Path) -> dict:
    p = payload_dir / "config.json"
    if p.exists():
        try:
            with p.open() as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _run_bt_gatt(pager, loot_dir: str) -> None:
    """BT-GATT Probe Flow: Target waehlen -> Warn -> Probe -> Results."""
    target = ui_target.select_bt_target(pager, loot_dir)
    if target is None:
        return
    target_mac = target["mac"].lower()
    short = opsec.short_mac(target_mac)
    addr_type = (target.get("addr_type") or "random").lower()
    if addr_type not in ("public", "random"):
        addr_type = "random"
    _log(f"target chosen: {short} addr_type={addr_type}")

    if not opsec.warning_active_probe(pager, short, "BT-GATT"):
        _log("user cancelled at warning")
        return

    # Optional MAC-Spoof
    orig_bd = opsec.get_current_bd_addr("hci0")
    spoofed = False
    new_bd = opsec.random_laa_mac()
    _log("attempting bdaddr spoof...")
    if opsec.spoof_bd_addr(new_bd, "hci0"):
        spoofed = True
        _log(f"bdaddr spoofed: ...{new_bd[-5:]}")
    else:
        _log("bdaddr spoof FAILED - continuing with original BD-Address")

    try:
        # Probe ausfuehren - mit progress callback
        def _progress(step, current, total):
            ui_results.show_progress(pager, short, step, current, total)

        result = bt_gatt.probe(target_mac, addr_type=addr_type,
                               progress_cb=_progress)
        _log(f"probe done: reachable={result.get('reachable')} "
             f"data_keys={list(result.get('data', {}).keys())}")
        ui_results.show_results(pager, result)
    finally:
        if spoofed and orig_bd:
            _log("restoring original bdaddr...")
            opsec.restore_bd_addr(orig_bd, "hci0")


def _run_stub(pager, mode_label: str, msg: str) -> None:
    ui_results.show_message(pager, mode_label, msg)


def main() -> int:
    payload_dir = Path(os.environ.get(
        "ARGUS_PAYLOAD_DIR",
        Path(__file__).resolve().parents[2],
    ))
    config = _load_config(payload_dir)
    loot_dir = config.get("paths", {}).get("loot_dir", "/root/loot/argus")

    _log("Pager()")
    pager = Pager()
    rc = pager.init()
    if rc != 0:
        print(f"FATAL: pager.init() rc={rc}", file=sys.stderr, flush=True)
        return 3
    pager.set_rotation(270)
    pager.set_brightness(config.get("ui", {}).get("brightness", 80))
    pager.screen_on()
    T.init(pager, config)

    try:
        # Health checks
        ok, err = bt_gatt.health_check()
        if not ok:
            ui_results.show_message(pager, "Probe Fehler", err)
            return 1

        # Loop: mode-select -> probe -> back to mode-select
        while True:
            mode = ui_mode_select.select_mode(pager)
            if mode is None:
                break
            _log(f"mode chosen: {mode}")
            if mode == "bt_gatt":
                _run_bt_gatt(pager, loot_dir)
            elif mode == "network":
                _run_stub(pager, "Network nmap",
                          "Stub - in v2.2 implementiert.")
            elif mode == "mdns":
                _run_stub(pager, "mDNS / SSDP",
                          "Stub - in v2.2 implementiert.")

    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        try:
            T.error_card(pager, "Fatal error", traceback.format_exc(limit=4))
            pager.wait_button()
        except Exception:
            pass
        return 2
    finally:
        try:
            T.shutdown(pager)
        except Exception:
            pass
        try:
            pager.cleanup()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
