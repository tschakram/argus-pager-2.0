#!/usr/bin/env python3
"""Argus Finder — Entry-Point.

Wird vom payload.sh-Wrapper als
    python3 -u finder/main.py --mode {bt,wifi}
gestartet. PYTHONPATH zeigt auf .../python/ und .../pagerctl/.

Flow: pager-init -> splash (1s) -> target-load -> select-screen -> hunt-loop.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
from finder import target_loader, ui_select, ui_hunt, ui_sweep, ui_mode_select
from finder.backends import wifi_rssi, bt_rssi


def _log(msg: str) -> None:
    print(f"[finder] {msg}", file=sys.stderr, flush=True)


def _splash(pager, mode: str) -> None:
    pager.clear(T.BLACK)
    T.header(pager, "FINDER " + ("WIFI" if mode == "wifi" else "BT"))
    if T.FONT_PATH:
        pager.draw_ttf(10, T.BODY_Y, "Lade Targets...", T.WHITE,
                       T.FONT_PATH, T.FONT_BODY)
    pager.flip()
    T.led_state(pager, "init")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("wifi", "bt"), required=True)
    p.add_argument("--loot", default="/root/loot/argus")
    p.add_argument("--iface", default="wlan1mon")
    p.add_argument("--config", default=None)
    args = p.parse_args()

    payload_dir = Path(os.environ.get(
        "ARGUS_PAYLOAD_DIR",
        Path(__file__).resolve().parents[2],
    ))
    config_path = Path(args.config) if args.config else payload_dir / "config.json"
    config: dict = {}
    if config_path.exists():
        try:
            with config_path.open() as f:
                config = json.load(f)
        except Exception:
            pass

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
        _splash(pager, args.mode)

        # Backend-Health
        if args.mode == "wifi":
            ok, err = wifi_rssi.health_check(args.iface)
        else:
            ok, err = bt_rssi.health_check()
        if not ok:
            _log(f"backend not ready: {err}")
            ui_select.show_message(pager, "Finder Fehler", err)
            return 1

        # Mode-Wahl: Target (Argus-Run-MAC) oder Sweep (alle live)
        mode_label = "WIFI" if args.mode == "wifi" else "BT"
        which = ui_mode_select.select_mode(pager, mode_label)
        if which is None:
            _log("user cancelled at mode-select")
            return 0
        _log(f"mode chosen: {which}")

        if which == "sweep":
            # Sweep-Mode: kein Target, Sampler ohne MAC-Filter
            if args.mode == "wifi":
                sampler = wifi_rssi.WifiSampler(None, iface=args.iface, sweep=True)
            else:
                sampler = bt_rssi.BtSampler(None)
            ui_sweep.sweep_loop(pager, sampler, args.mode)
            return 0

        # Target-Mode: aus dem letzten Argus-Run laden (BLE-Privacy-Adressen
        # rotieren ~alle 15 Min, alte Adressen waeren nutzlos).
        if args.mode == "wifi":
            targets = target_loader.load_wifi_targets(args.loot, last_only=True)
        else:
            targets = target_loader.load_bt_targets(args.loot, last_only=True)
        _log(f"targets loaded: {len(targets)}")

        # Session-Label fuer UI: zeigt aus welchem Run die Liste stammt
        meta = target_loader.latest_session_meta(args.loot)
        session_label = ""
        if meta.get("session_id"):
            sid = meta["session_id"]   # z.B. 20260510_092619
            session_label = f"Run {sid[6:8]}.{sid[4:6]} {sid[9:11]}:{sid[11:13]}"
            if meta.get("mtime"):
                age_min = max(0, int((time.time() - meta["mtime"]) / 60))
                session_label += f" ({age_min}min alt)"

        if not targets:
            ui_select.show_message(
                pager, "Keine Targets",
                "Erst Argus-Scan laufen lassen oder Sweep-Mode nutzen.\n"
                + (session_label or ""),
            )
            return 1

        # Auswahl
        target = ui_select.select_target(pager, targets, args.mode, session_label)
        if target is None:
            _log("user cancelled at target-select")
            return 0
        # Log redaktiert nur die letzten 4 Hex-Stellen (OPSEC: full MAC
        # waere im /root/loot/argus/logs/ persistent, gitignored aber
        # vermeidbar)
        _log(f"selected: ...{target['mac'][-5:]}")

        # Sampler aufsetzen
        if args.mode == "wifi":
            sampler = wifi_rssi.WifiSampler(target["mac"], iface=args.iface,
                                            sweep=True)
        else:
            sampler = bt_rssi.BtSampler(target["mac"])

        # Hunt-Loop
        ui_hunt.hunt_loop(pager, target, sampler, args.mode)

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
