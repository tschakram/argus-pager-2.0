"""OPSEC-Helpers fuer aktive Probes:
- BT MAC-Spoof (bdaddr-Tool, restore in finally-Block)
- Warning-Screen vor jedem aktiven Probe (Confirm-Modal)
- Log-Redaction (kein full-MAC im Logfile)

Zweck: Aktive Probes hinterlassen Spuren beim Zielgeraet - das ist die
ganze Sache. Aber wir koennen kontrollieren WELCHE Spuren:
- Statt unserer echten Pager-BD-Address eine LAA-randomisierte;
  Zielgeraet sieht eine random-MAC, kann aber nicht zurueckverfolgen.
- Big-Warning-Screen sorgt dafuer dass kein Probe versehentlich
  ausgeloest wird.
"""
from __future__ import annotations

import os
import random
import subprocess
import time

from ui import theme as T

try:
    from pagerctl import BTN_A, BTN_B, BTN_LEFT, BTN_POWER
except ImportError:
    BTN_A, BTN_B, BTN_LEFT, BTN_POWER = 16, 32, 4, 64


# ── BT MAC-Spoof ────────────────────────────────────────────────

def get_current_bd_addr(iface: str = "hci0") -> str | None:
    """Liest aktuelle BD-Address aus hciconfig."""
    try:
        out = subprocess.check_output(
            ["hciconfig", iface], text=True, timeout=2,
            stderr=subprocess.DEVNULL,
        )
        # Format: "BD Address: AA:BB:CC:DD:EE:FF  ACL MTU: ..."
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("BD Address:"):
                return line.split()[2].lower()
    except Exception:
        pass
    return None


def random_laa_mac() -> str:
    """Random MAC mit gesetztem Locally-Administered-Bit (Bit 1 von Byte 0)
    und gecleartem Multicast-Bit (Bit 0). Kollidiert nie mit IEEE-OUI."""
    first = (random.randint(0, 255) & 0xfe) | 0x02
    rest = [random.randint(0, 255) for _ in range(5)]
    return "{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}".format(first, *rest)


def spoof_bd_addr(new_mac: str, iface: str = "hci0") -> bool:
    """Setzt neue BD-Address auf hci0. Erfordert hciconfig down/up.
    Returns True wenn erfolgreich. ACHTUNG: nicht jeder BT-Chipset
    erlaubt bdaddr-write - falls bdaddr fehlschlaegt, wird die echte
    Adresse weiter benutzt.
    """
    try:
        subprocess.run(["hciconfig", iface, "down"],
                       check=False, timeout=3,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rc = subprocess.run(["bdaddr", "-i", iface, new_mac],
                            timeout=5,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        # USB-BT-Chips brauchen Reset nach bdaddr-Write
        subprocess.run(["hciconfig", iface, "reset"],
                       check=False, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["hciconfig", iface, "up"],
                       check=False, timeout=3,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        # Verify
        actual = get_current_bd_addr(iface)
        return rc == 0 and actual == new_mac.lower()
    except Exception:
        return False


def restore_bd_addr(orig_mac: str, iface: str = "hci0") -> bool:
    """Stellt die originale BD-Address wieder her."""
    return spoof_bd_addr(orig_mac, iface)


# ── Warning-Screens ─────────────────────────────────────────────

def warning_active_probe(pager, target_short: str, mode: str) -> bool:
    """Big-Warning vor aktivem Probe. LEFT = bestaetigen, B = abbrechen.
    Returns True wenn User explicit bestaetigt hat."""
    last_draw = 0.0
    while True:
        try:
            _curr, pressed, _rel = pager.poll_input()
        except Exception:
            pressed = 0
        if pressed & BTN_LEFT:
            return True
        if pressed & (BTN_B | BTN_POWER | BTN_A):
            return False

        now = time.monotonic()
        if now - last_draw >= 0.3:
            _draw_warning(pager, target_short, mode)
            last_draw = now
        time.sleep(0.05)


def _draw_warning(pager, target_short: str, mode: str) -> None:
    pager.clear(T.BLACK)
    # Roter Header zur Warnung
    pager.fill_rect(0, 0, T.W, T.HEADER_H, T.RED)
    if T.FONT_PATH:
        pager.draw_ttf(8, 4, "AKTIVER PROBE", T.WHITE,
                       T.FONT_PATH, T.FONT_TITLE)
    pager.hline(0, T.HEADER_H - 1, T.W, T.WHITE)

    body_y = T.BODY_Y
    if T.FONT_PATH:
        lines = [
            f"Mode:   {mode}",
            f"Target: {target_short}",
            "",
            "Pager wird vom Ziel gesehen.",
            "Connection erscheint im",
            "Geraete-Log des Ziels.",
            "",
            "MAC ist randomisiert,",
            "aber Probe ist sichtbar.",
        ]
        y = body_y
        for ln in lines:
            pager.draw_ttf(8, y, ln, T.WHITE, T.FONT_PATH, T.FONT_SMALL)
            y += T.FONT_SMALL + 2

    T.footer(pager, [("LEFT", "OK Probe"), ("B", "Cancel")])
    pager.flip()


def short_mac(mac: str) -> str:
    """Redaktiert MAC fuer Logs/Display: nur letzte 5 Hex."""
    if not mac:
        return "?"
    return "..." + mac.replace(":", "")[-5:]
