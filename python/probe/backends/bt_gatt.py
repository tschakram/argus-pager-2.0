"""BT-GATT Probe via gatttool.

Verbindet sich auf eine BLE-MAC und liest:
- Generic Access Service (0x1800):
    - 0x2A00 Device Name (oft im Advert leer, ueber GATT vorhanden!)
    - 0x2A01 Appearance (Tag/TV/Watch-Marker)
    - 0x2A04 Connection Parameters
- Device Information Service (0x180A):
    - 0x2A29 Manufacturer Name (z.B. "Samsung Electronics")
    - 0x2A24 Model Number (z.B. "QN65Q70AAFXZA" / "EI-T5300")
    - 0x2A25 Serial Number
    - 0x2A26 Firmware Revision
    - 0x2A27 Hardware Revision
    - 0x2A28 Software Revision
- Liste aller Primary Services (UUIDs)

Disconnects sofort - kein Bonding, keine persistente Verbindung.
"""
from __future__ import annotations

import re
import subprocess
import time

# Standard GAP/GATT Charakteristiken (BT SIG Assigned Numbers)
GATT_READS = [
    ("device_name",      "00002a00-0000-1000-8000-00805f9b34fb",
     "Device Name"),
    ("appearance",       "00002a01-0000-1000-8000-00805f9b34fb",
     "Appearance"),
    ("manufacturer",     "00002a29-0000-1000-8000-00805f9b34fb",
     "Manufacturer Name"),
    ("model_number",     "00002a24-0000-1000-8000-00805f9b34fb",
     "Model Number"),
    ("serial_number",    "00002a25-0000-1000-8000-00805f9b34fb",
     "Serial Number"),
    ("hardware_rev",     "00002a27-0000-1000-8000-00805f9b34fb",
     "Hardware Revision"),
    ("firmware_rev",     "00002a26-0000-1000-8000-00805f9b34fb",
     "Firmware Revision"),
    ("software_rev",     "00002a28-0000-1000-8000-00805f9b34fb",
     "Software Revision"),
    ("system_id",        "00002a23-0000-1000-8000-00805f9b34fb",
     "System ID"),
    ("pnp_id",           "00002a50-0000-1000-8000-00805f9b34fb",
     "PnP ID (Vendor/Product)"),
]

APPEARANCE_LABELS = {
    0x0000: "Generic", 0x0040: "Phone", 0x0080: "Computer",
    0x00C0: "Watch", 0x00C2: "Smartwatch",
    0x0140: "Display", 0x0180: "Remote",
    0x0200: "Tag/Tracker", 0x0240: "Keyring",
    0x0C40: "Mediaplayer", 0x0C49: "Television",
    0x07D4: "IP Camera", 0x07D6: "Audio Sensor",
}


def _decode_hex_bytes(hex_str: str) -> tuple[str, str]:
    """gatttool gibt 'value: 53 61 6d 73 75 6e 67' zurueck. Gibt
    (raw_hex, decoded_string) zurueck."""
    hex_clean = hex_str.replace(" ", "").strip()
    raw_hex = " ".join(hex_clean[i:i+2] for i in range(0, len(hex_clean), 2))
    try:
        b = bytes.fromhex(hex_clean)
        # ASCII-printable filtern (manche FW haben null-terminator)
        s = b.rstrip(b"\x00").decode("utf-8", errors="replace")
        if all(0x20 <= ord(c) < 0x7f or c in ("\t",) for c in s):
            return raw_hex, s
        return raw_hex, ""
    except Exception:
        return raw_hex, ""


def _gatt_read_uuid(mac: str, uuid: str, addr_type: str = "random",
                    timeout: float = 6.0) -> tuple[str, str] | None:
    """Liest eine Charakteristik via gatttool --char-read --uuid.
    addr_type: 'public' fuer feste OUI-MACs, 'random' fuer RPA/Static.
    Gibt (raw_hex, decoded_str) oder None zurueck.
    """
    try:
        proc = subprocess.run(
            ["gatttool", "-t", addr_type, "-b", mac.upper(),
             "--char-read", "--uuid", uuid],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # Zeilen wie:
        #   handle: 0x0003     value: 53 61 6d 73 75 6e 67
        for line in out.splitlines():
            m = re.search(r"value:\s+([0-9a-fA-F\s]+)", line)
            if m:
                return _decode_hex_bytes(m.group(1))
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def _gatt_primary_services(mac: str, addr_type: str = "random",
                           timeout: float = 8.0) -> list[str]:
    """Listet Primary Services. Gibt Liste von UUID-Strings zurueck."""
    try:
        proc = subprocess.run(
            ["gatttool", "-t", addr_type, "-b", mac.upper(), "--primary"],
            capture_output=True, text=True, timeout=timeout,
        )
        services = []
        out = (proc.stdout or "")
        # Zeilen: "attr handle: 0x0001, end grp handle: 0x0007 uuid: <UUID>"
        for line in out.splitlines():
            m = re.search(r"uuid:\s+([0-9a-fA-F-]+)", line)
            if m:
                u = m.group(1).lower()
                # Standard 16-bit UUIDs als kurz darstellen
                if u.startswith("0000") and u.endswith("-0000-1000-8000-00805f9b34fb"):
                    u = u[4:8]
                services.append(u)
        return services
    except Exception:
        return []


def probe(mac: str, addr_type: str = "random", per_read_timeout: float = 5.0,
          progress_cb=None) -> dict:
    """Voller GATT-Probe einer BT-MAC.

    addr_type: 'public' (Hausgeraete mit echtem Samsung/Apple OUI) oder
               'random' (RPA/Static, default).
    progress_cb: optional callable(step_label, current, total) fuer UI-Update.

    Returns dict:
      {
        'mac': str,
        'addr_type': 'public' / 'random',
        'reachable': bool,
        'data': {key: {raw_hex, decoded, label}, ...},
        'services': [uuid, ...],
        'errors': [str, ...],
      }
    """
    result = {
        "mac": mac.lower(),
        "addr_type": addr_type,
        "reachable": False,
        "data": {},
        "services": [],
        "errors": [],
    }

    total_steps = len(GATT_READS) + 1  # +1 fuer primary-services

    # Step 1: Primary Services (impliziter connect)
    if progress_cb:
        progress_cb("Primary Services...", 1, total_steps)
    services = _gatt_primary_services(mac, addr_type, timeout=8.0)
    if services:
        result["reachable"] = True
        result["services"] = services
    else:
        result["errors"].append("Keine primary services - Geraet nicht erreichbar oder Connectable=No")
        # Trotzdem Reads versuchen - manche Geraete antworten direkt auf char-read

    # Step 2..N: Standard-Reads
    for i, (key, uuid, label) in enumerate(GATT_READS, start=2):
        if progress_cb:
            progress_cb(label, i, total_steps)
        r = _gatt_read_uuid(mac, uuid, addr_type, timeout=per_read_timeout)
        if r is not None:
            raw_hex, decoded = r
            result["data"][key] = {
                "raw_hex": raw_hex,
                "decoded": decoded,
                "label": label,
            }
            result["reachable"] = True
            # Appearance speziell decodieren (2 Byte little-endian)
            if key == "appearance" and not decoded:
                try:
                    bytes_ = [int(b, 16) for b in raw_hex.split()]
                    if len(bytes_) >= 2:
                        code = bytes_[0] | (bytes_[1] << 8)
                        result["data"][key]["decoded"] = (
                            f"0x{code:04x} ({APPEARANCE_LABELS.get(code, 'Unbekannt')})"
                        )
                except Exception:
                    pass

    return result


def health_check() -> tuple[bool, str]:
    import shutil
    if not shutil.which("gatttool"):
        return False, "gatttool nicht installiert"
    if not shutil.which("hciconfig"):
        return False, "hciconfig nicht installiert"
    return True, ""
