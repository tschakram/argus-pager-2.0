"""Network-Probe via nmap (STUB).

Geplant:
- nmap -sn auf wlan0cli-Subnet (Mudi 192.168.8.0/24): Live-Hosts
- pro Host: TCP-Banner-Grab (HTTP, SSH, Telnet, NetBIOS)
- mDNS via nmap --script broadcast-dns-service-discovery
- SSDP/UPnP via nmap --script broadcast-upnp-info

OPSEC:
- nmap-Scan ist im Netz sichtbar (Pakete kommen von wlan0cli mit Pager-MAC)
- Beim Mudi sieht der Operator den Scan als Traffic
- IDS/IPS auf vielen Routern flaggt nmap

Implementation: TODO. Aufruf-Schema waere wie bt_gatt.probe(): nimmt
Subnet (oder leer = aktuell assoziiertes), gibt dict zurueck mit
hosts/services/banner.
"""
from __future__ import annotations


def probe(*args, **kwargs) -> dict:
    return {
        "stub": True,
        "message": "Network-Probe noch nicht implementiert. Backlog v2.2.",
    }


def health_check() -> tuple[bool, str]:
    import shutil
    if not shutil.which("nmap"):
        return False, "nmap nicht installiert"
    return True, ""
