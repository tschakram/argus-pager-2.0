"""Post-scan helpers used by the post_scan screen.

Pure thin wrappers around mudi_client.* — the screen owns the UX, this module
owns the labels and string-formatting so the screen stays presentation-only.
"""
from __future__ import annotations

from . import mudi_client


def silent_sms_check(cfg: dict) -> str:
    rows = mudi_client.silent_sms_recent(cfg, hours=2)
    if not rows:
        return "clean (0 events 2h)"
    types = sorted({(r.get("type") or "?") for r in rows})
    return f"{len(rows)} events: {','.join(types)}"


def imsi_summary(cfg: dict) -> str:
    rows = mudi_client.imsi_alerts_recent(cfg, hours=2)
    if not rows:
        return "clean (0 alerts 2h)"
    high = sum(1 for r in rows if (r.get("severity") or "").upper() == "HIGH")
    med  = sum(1 for r in rows if (r.get("severity") or "").upper() == "MEDIUM")
    return f"{len(rows)} alerts: HIGH={high} MED={med}"


def upload_queue_count(cfg: dict) -> int:
    return mudi_client.upload_queue_count(cfg)


def opencellid_upload(cfg: dict) -> tuple[int, int]:
    return mudi_client.opencellid_upload(cfg)


def imei_rotate(cfg: dict) -> str:
    # Radio-off first to avoid leaking new IMEI on the active connection.
    mudi_client.radio(cfg, on=False)
    res = mudi_client.imei_rotate(cfg, deterministic=True)
    mudi_client.radio(cfg, on=True)
    if not res:
        return "Mudi unreachable"
    if res.get("success"):
        new = (res.get("imei_after") or "")[-6:]
        return f"rotated: ...{new}"
    return f"failed: {res.get('error', 'unknown')[:30]}"
