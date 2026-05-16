"""Sweep-Modus — Live-Liste aller MACs in Reichweite, sortiert nach RSSI.

Loest das BLE-Privacy-Address-Rotation-Problem: man sucht keine spezifische
MAC mehr, sondern nimmt einfach was gerade in der Luft ist und folgt dem
staerksten Signal. Wer beim Rumlaufen den dB-Wert nach oben treibt, ist
das Geraet das man sucht.

In-memory only - keine MAC-Listen werden persistent gespeichert (OPSEC).
"""
from __future__ import annotations

import json
import os
import sys
import time

from ui import theme as T

# Bootstrap cyt/python to sys.path for mac_ignore import
_CYT_PY = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "cyt", "python"))
if _CYT_PY not in sys.path:
    sys.path.insert(0, _CYT_PY)
from mac_ignore import MacIgnoreSet

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER = 16, 32, 4, 1, 2, 64

from . import ui_hunt   # gleiche Schwellen + LED/Vibrate-Logik wiederverwenden

REDRAW_PERIOD = 0.3
# Aging-Schwellen unterscheiden sich je nach Funkprotokoll:
#   BLE-Adverts:   2-15s Intervall -> 30s reicht
#   WiFi-Probes:   1-3 MIN Intervall -> 120s noetig damit der Eintrag
#                  nicht verschwindet bevor User ihn sieht
AGE_OUT_BT_S   = 30.0
AGE_OUT_WIFI_S = 120.0
MAX_VISIBLE    = 6
VIB_GAP_S      = 1.5
TOP_DEDUP      = 50

# Pfade zur ignore-Liste - gleicher Mechanismus wie target_loader
_IGNORE_PATHS = (
    "/root/loot/argus/ignore_lists/mac_list.json",
    "/root/loot/chasing_your_tail/ignore_lists/mac_list.json",
)


def _load_ignore_macs() -> MacIgnoreSet:
    """Liest ignore_macs aus mac_list.json - inkl. Wildcard-Patterns
    (siehe cyt/python/mac_ignore.py). Wildcards "aa:bb:cc:dd:ee:??"
    erfassen BLE-Privacy-Rotation in der Sweep-Liste.
    """
    out = MacIgnoreSet()
    for p in _IGNORE_PATHS:
        if not os.path.exists(p):
            continue
        try:
            with open(p) as fh:
                data = json.load(fh)
            out.update(data.get("ignore_macs", []))
        except Exception:
            pass
    return out


def sweep_loop(pager, sampler, mode: str) -> None:
    """Endlos-Schleife: alle Samples einsammeln, Top-Liste rendern.

    Devices sind ein Dict ``mac_lower -> {rssi_last, rssi_max, last_seen, samples}``.
    Ignore-listed MACs werden direkt beim Drain gefiltert.
    """
    devices: dict[str, dict] = {}
    last_draw = 0.0
    last_vib = 0.0
    last_top_status = ""
    selected = 0
    scroll = 0
    ignore_macs = _load_ignore_macs()
    age_out = AGE_OUT_WIFI_S if mode == "wifi" else AGE_OUT_BT_S
    # Stats fuer UI-Transparenz
    stats = {"ignored_hits": 0, "total_samples": 0}

    sampler.start()
    try:
        while True:
            try:
                _curr, pressed, _rel = pager.poll_input()
            except Exception:
                pressed = 0

            if pressed & (BTN_B | BTN_POWER):
                break
            if pressed & BTN_UP:
                selected = max(0, selected - 1)
                last_draw = 0
            elif pressed & BTN_DOWN:
                # Bound-check direkt: selected darf nicht ueber len-1
                # (Liste-Length kommt vom letzten Render-Cycle, deshalb
                #  separate Variable). Falls Liste leer = selected bleibt 0.
                # Voraktualisierung: wenn devices nicht leer ist, max ist
                # current count - 1, sonst 0.
                if devices:
                    selected = min(selected + 1, len(devices) - 1)
                last_draw = 0
            elif pressed & BTN_LEFT:
                selected = 0
                scroll = 0
                last_draw = 0

            now = time.monotonic()

            # Drain Samples + Ignore-List-Filter
            for item in sampler.drain():
                if not isinstance(item, tuple):
                    continue
                mac, rssi = item
                stats["total_samples"] += 1
                if mac in ignore_macs:
                    stats["ignored_hits"] += 1
                    continue   # Ignore-listed -> nicht in die Live-Liste
                d = devices.setdefault(mac, {
                    "rssi_last": rssi,
                    "rssi_max": rssi,
                    "last_seen": now,
                    "samples": 0,
                })
                d["rssi_last"] = rssi
                if rssi > d["rssi_max"]:
                    d["rssi_max"] = rssi
                d["last_seen"] = now
                d["samples"] += 1

            # Aging-Out + Pool-Limit (mode-abhaengiger TTL)
            for mac in list(devices.keys()):
                if now - devices[mac]["last_seen"] > age_out:
                    del devices[mac]
            if len(devices) > TOP_DEDUP:
                # behalte nur die staerksten TOP_DEDUP (nach rssi_max)
                top = sorted(devices.items(),
                             key=lambda kv: -kv[1]["rssi_max"])[:TOP_DEDUP]
                devices = dict(top)

            # Sortierung: starkstes Signal zuerst
            ranked = sorted(devices.items(),
                            key=lambda kv: -kv[1]["rssi_last"])

            # Selection + Scroll in gueltigen Bereich klemmen
            if not ranked:
                selected = 0
                scroll = 0
            else:
                # selected darf nicht ueber max-idx
                selected = max(0, min(selected, len(ranked) - 1))
                # scroll so anpassen dass selected immer sichtbar ist
                if selected < scroll:
                    scroll = selected
                elif selected >= scroll + MAX_VISIBLE:
                    scroll = selected - MAX_VISIBLE + 1
                # scroll an die Liste-Length anpassen (nie ueber max)
                max_scroll = max(0, len(ranked) - MAX_VISIBLE)
                scroll = max(0, min(scroll, max_scroll))

            # LED + Vibration nach staerkstem Geraet (wenn vorhanden)
            top_rssi = ranked[0][1]["rssi_last"] if ranked else None
            top_status = ui_hunt._classify(top_rssi)
            if top_status != last_top_status:
                ui_hunt._apply_led(pager, top_status)
                last_top_status = top_status
            if top_status in ("red", "yellow") and (now - last_vib) > VIB_GAP_S:
                ui_hunt._vibrate(pager, top_status)
                last_vib = now

            if now - last_draw >= REDRAW_PERIOD:
                _draw(pager, mode, ranked, selected, scroll, now, stats)
                last_draw = now

            time.sleep(0.05)
    finally:
        sampler.stop()
        try:
            T.led_state(pager, "off")
        except Exception:
            pass


def _draw(pager, mode: str, ranked: list, selected: int,
          scroll: int, now: float, stats: dict | None = None) -> None:
    pager.clear(T.BLACK)
    title = "SWEEP " + ("WIFI" if mode == "wifi" else "BT")
    T.header(pager, "FINDER " + title)

    body_y = T.BODY_Y
    if T.FONT_PATH:
        ign = stats.get("ignored_hits", 0) if stats else 0
        if not ranked:
            sub = f"Lausche... (ignored:{ign})"
        else:
            # zeigt visible-Position + total + ignored count
            shown_end = min(scroll + MAX_VISIBLE, len(ranked))
            sub = (f"{scroll+1}-{shown_end}/{len(ranked)}  "
                   f"ign:{ign}  sel:{selected+1}")
        pager.draw_ttf(8, body_y, sub, T.GREY, T.FONT_PATH, T.FONT_SMALL)

    list_y = body_y + T.FONT_SMALL + 6
    row_h  = T.FONT_SMALL + 8

    if not ranked:
        T.footer(pager, [("B", "Stop")])
        pager.flip()
        return

    for i in range(MAX_VISIBLE):
        idx = scroll + i
        if idx >= len(ranked):
            break
        mac, d = ranked[idx]
        rssi = d["rssi_last"]
        age  = now - d["last_seen"]
        samples = d["samples"]
        status = ui_hunt._classify(rssi)
        color, _ = ui_hunt._STATUS_PALETTE.get(status, (T.WHITE, "?"))

        row_y = list_y + i * row_h
        if idx == selected:
            pager.fill_rect(8, row_y - 2, T.W - 16, row_h, T.DARK)
            pager.fill_rect(8, row_y - 2, 4, row_h, T.ACCENT)
            label_color = T.ACCENT
        else:
            label_color = T.WHITE

        if T.FONT_PATH:
            # Linksseite: kompakte MAC + dBm
            short = mac.replace(":", "")[-6:]   # nur letzten 3 Bytes
            line  = f"{short}  {rssi:4d}dBm  n{samples}"
            pager.draw_ttf(20, row_y + 2, line, label_color,
                           T.FONT_PATH, T.FONT_SMALL)
            # rechts: alter (in Sekunden)
            age_s = f"{age:.0f}s"
            pager.draw_ttf_right(row_y + 2, age_s, color,
                                 T.FONT_PATH, T.FONT_SMALL, 12)

    T.footer(pager, [("UP/DN", "Scroll"), ("LEFT", "Top"), ("B", "Stop")])
    pager.flip()
