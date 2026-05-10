"""mDNS/SSDP Discovery (STUB).

Geplant:
- mDNS via nmap --script broadcast-dns-service-discovery
  Findet Apple TV, AirPlay, Cast, Sonos, Drucker, NAS - oft mit
  echtem Hostname ('Marcus iPhone', 'Wohnzimmer Apple TV').
- SSDP/UPnP via nmap --script broadcast-upnp-info
  Findet Smart-TVs, IP-Kameras, IoT-Gateways.

OPSEC:
- Multicast-Broadcasts sind im lokalen Netz sichtbar
- Pager-MAC erscheint als source - Mudi-Operator sieht das
"""
from __future__ import annotations


def probe(*args, **kwargs) -> dict:
    return {
        "stub": True,
        "message": "mDNS/SSDP Discovery noch nicht implementiert.",
    }


def health_check() -> tuple[bool, str]:
    import shutil
    if not shutil.which("nmap"):
        return False, "nmap nicht installiert"
    return True, ""
