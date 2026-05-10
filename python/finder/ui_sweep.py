"""Sweep-Modus — Live-Liste aller MACs in Reichweite, sortiert nach RSSI.

Loest das BLE-Privacy-Address-Rotation-Problem: man sucht keine spezifische
MAC mehr, sondern nimmt einfach was gerade in der Luft ist und folgt dem
staerksten Signal. Wer beim Rumlaufen den dB-Wert nach oben treibt, ist
das Geraet das man sucht.

In-memory only - keine MAC-Listen werden persistent gespeichert (OPSEC).
"""
from __future__ import annotations

import time

from ui import theme as T

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_UP, BTN_DOWN, BTN_POWER = 16, 32, 4, 1, 2, 64

from . import ui_hunt   # gleiche Schwellen + LED/Vibrate-Logik wiederverwenden

REDRAW_PERIOD = 0.3
AGE_OUT_S     = 30.0   # MAC verschwindet aus Liste wenn 30s nichts neues kam
MAX_VISIBLE   = 6       # passt sauber ins Display
VIB_GAP_S     = 1.5
TOP_DEDUP     = 50      # max gleichzeitige MACs im Pool


def sweep_loop(pager, sampler, mode: str) -> None:
    """Endlos-Schleife: alle Samples einsammeln, Top-Liste rendern.

    Devices sind ein Dict ``mac_lower -> {rssi_last, rssi_max, last_seen, samples}``.
    """
    devices: dict[str, dict] = {}
    last_draw = 0.0
    last_vib = 0.0
    last_top_status = ""
    selected = 0   # gewaehlte Zeile (Highlight)
    scroll = 0

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
                if selected < scroll:
                    scroll = selected
                last_draw = 0
            elif pressed & BTN_DOWN:
                selected += 1
                last_draw = 0   # Limit kommt aus visible-Liste, redraw entscheidet
            elif pressed & BTN_LEFT:
                # zurueck nach oben
                selected = 0
                scroll = 0
                last_draw = 0

            now = time.monotonic()

            # Drain Samples
            for item in sampler.drain():
                if not isinstance(item, tuple):
                    continue
                mac, rssi = item
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

            # Aging-Out + Pool-Limit
            for mac in list(devices.keys()):
                if now - devices[mac]["last_seen"] > AGE_OUT_S:
                    del devices[mac]
            if len(devices) > TOP_DEDUP:
                # behalte nur die staerksten TOP_DEDUP (nach rssi_max)
                top = sorted(devices.items(),
                             key=lambda kv: -kv[1]["rssi_max"])[:TOP_DEDUP]
                devices = dict(top)

            # Sortierung: starkstes Signal zuerst
            ranked = sorted(devices.items(),
                            key=lambda kv: -kv[1]["rssi_last"])

            # Selection in gueltigen Bereich klemmen
            if not ranked:
                selected = 0
                scroll = 0
            else:
                selected = min(selected, len(ranked) - 1)
                if selected >= scroll + MAX_VISIBLE:
                    scroll = selected - MAX_VISIBLE + 1
                if scroll > max(0, len(ranked) - MAX_VISIBLE):
                    scroll = max(0, len(ranked) - MAX_VISIBLE)

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
                _draw(pager, mode, ranked, selected, scroll, now)
                last_draw = now

            time.sleep(0.05)
    finally:
        sampler.stop()
        try:
            T.led_state(pager, "off")
        except Exception:
            pass


def _draw(pager, mode: str, ranked: list, selected: int,
          scroll: int, now: float) -> None:
    pager.clear(T.BLACK)
    title = "SWEEP " + ("WIFI" if mode == "wifi" else "BT")
    T.header(pager, "FINDER " + title)

    body_y = T.BODY_Y
    if T.FONT_PATH:
        if not ranked:
            sub = "Lausche... bewege Pager"
        else:
            sub = f"Live ({len(ranked)} MACs, top sortiert)"
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
