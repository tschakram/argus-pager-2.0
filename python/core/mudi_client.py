"""Thin SSH client that talks to the Mudi V2 (raypager backend).

We use the system ``ssh`` binary with ControlMaster multiplexing so repeated
calls during a scan stay fast. All scripts on the Mudi live in
``/root/raypager/python``; their CLIs are documented in raypager's own README.

Every callable here is a NO-OP returning ``None`` if Mudi is unreachable, so
that Pager-only scans (CUSTOM with no cell/gps_mudi) keep working offline.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

_CONTROL_PATH = "/tmp/argus-mudi-%C"
_CACHE = {"reachable_at": 0.0, "reachable": False}


# ── basic plumbing ──────────────────────────────────────────────────────

def _ssh_args(cfg: dict) -> list[str]:
    m = cfg.get("mudi") or {}
    host = m.get("host", "192.168.8.1")
    user = m.get("user", "root")
    key  = m.get("key",  "/root/.ssh/mudi_key")
    return [
        "ssh",
        "-i", key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=4",
        "-o", "ServerAliveInterval=10",
        "-o", "BatchMode=yes",
        "-o", f"ControlPath={_CONTROL_PATH}",
        "-o", "ControlMaster=auto",
        "-o", "ControlPersist=300",
        f"{user}@{host}",
    ]


def _run(cfg: dict, remote_cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    cmd = _ssh_args(cfg) + [remote_cmd]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            check=False, env={**os.environ, "TERM": "dumb"},
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 255, "", str(e)


def is_reachable(cfg: dict) -> bool:
    """Cached connectivity probe (~30 s TTL)."""
    now = time.monotonic()
    if now - _CACHE["reachable_at"] < 30:
        return _CACHE["reachable"]
    rc, _, _ = _run(cfg, "true", timeout=4)
    _CACHE["reachable"] = (rc == 0)
    _CACHE["reachable_at"] = now
    return _CACHE["reachable"]


def _py_path(cfg: dict, script: str) -> str:
    base = (cfg.get("mudi") or {}).get("python_dir", "/root/raypager/python")
    return f"python3 {base}/{script}"


# ── high-level helpers ──────────────────────────────────────────────────

def gps_get(cfg: dict, *, timeout_s: int = 10) -> tuple[float, float] | None:
    if not is_reachable(cfg):
        return None
    rc, out, _ = _run(cfg, _py_path(cfg, f"gps.py --timeout {timeout_s}"), timeout=timeout_s + 5)
    if rc != 0 or not out.strip():
        return None
    try:
        lat, lon, *_ = out.strip().split()
        return float(lat), float(lon)
    except Exception:
        return None


def cell_info(cfg: dict) -> dict | None:
    if not is_reachable(cfg):
        return None
    rc, out, _ = _run(cfg, _py_path(cfg, "cell_info.py --json"), timeout=15)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def cell_lookup(cfg: dict) -> dict | None:
    """Cell tower + OpenCelliD lookup (cached on Mudi), merged with the
    full cell_info radio metadata (RSSI/RSRP/operator/etc.).

    Slower than cell_info() because of the extra API call; intended for
    analyser-time usage, not the live _mudi_loop. The returned dict has
    everything cell_info() returns plus the OpenCelliD fields:
    ``threat`` / ``threat_label`` / ``in_db`` / ``db_lat`` / ``db_lon``.
    """
    if not is_reachable(cfg):
        return None
    base = cell_info(cfg) or {}
    # opencellid.py uses the exit code to mirror the threat level:
    # rc=0 CLEAN, rc=1 UNKNOWN, rc=2 MISMATCH, rc=3 GHOST. JSON is always
    # written to stdout regardless. We must not gate on rc != 0.
    rc, out, _ = _run(cfg, _py_path(cfg, "opencellid.py"), timeout=20)
    if not out.strip():
        return base or None
    idx = out.find("{")
    if idx < 0:
        return base or None
    try:
        ocid = json.loads(out[idx:])
    except Exception:
        return base or None
    base.update(ocid)
    return base


def imsi_alerts_recent(cfg: dict, *, hours: int = 2) -> list[dict]:
    if not is_reachable(cfg):
        return []
    loot = (cfg.get("mudi") or {}).get("loot_dir", "/root/loot/raypager")
    cmd = (
        f"awk -v cutoff=$(($(date +%s) - {hours * 3600})) "
        f"-F'\"' '/\"ts\":/ {{ if ($4+0 >= cutoff) print $0 }}' "
        f"{loot}/imsi_alerts.jsonl 2>/dev/null"
    )
    rc, out, _ = _run(cfg, cmd, timeout=10)
    if rc != 0:
        return []
    rows: list[dict] = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def silent_sms_recent(cfg: dict, *, hours: int = 2) -> list[dict]:
    if not is_reachable(cfg):
        return []
    loot = (cfg.get("mudi") or {}).get("loot_dir", "/root/loot/raypager")
    rc, out, _ = _run(
        cfg,
        f"tail -n 200 {loot}/silent_sms.jsonl 2>/dev/null",
        timeout=8,
    )
    rows: list[dict] = []
    cutoff = time.time() - hours * 3600
    for line in out.splitlines():
        try:
            evt = json.loads(line)
            if float(evt.get("ts", 0)) >= cutoff:
                rows.append(evt)
        except Exception:
            continue
    return rows




def imei_rotate(cfg: dict, *, deterministic: bool = True) -> dict | None:
    if not is_reachable(cfg):
        return None
    flag = "deterministic" if deterministic else ""
    rc, out, err = _run(cfg, _py_path(cfg, f"blue_merle.py rotate {flag}"), timeout=60)
    if rc != 0:
        return {"success": False, "error": err.strip()}
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:
        return {"success": rc == 0, "raw": out.strip()[:120]}


def radio(cfg: dict, on: bool) -> bool:
    if not is_reachable(cfg):
        return False
    state = "on" if on else "off"
    rc, _, _ = _run(cfg, _py_path(cfg, f"blue_merle.py radio {state}"), timeout=20)
    return rc == 0
