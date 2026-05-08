"""External intel enrichment - InternetDB / Shodan / Fingerbank.

Called by analyser.run_all() after the CYT pipeline completes. Returns a
findings list + a markdown block to append to the report.

All HTTP calls go directly from the pager via Mudi -> LTE.
Network errors never raise; missing data is treated as "no result".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PAYLOAD_DIR = Path(os.environ.get("ARGUS_PAYLOAD_DIR",
                                  Path(__file__).resolve().parents[2]))
CYT_PY      = PAYLOAD_DIR / "cyt" / "python"

# Vendor cyt's shodan_lookup module (stdlib-only, drop-in).
if str(CYT_PY) not in sys.path:
    sys.path.insert(0, str(CYT_PY))
try:
    import shodan_lookup as sl  # type: ignore
    _OK = True
except Exception as e:
    print(f"[external_intel] cyt.shodan_lookup unavailable: {e}",
          file=sys.stderr, flush=True)
    _OK = False


# ── PCAP -> IP extraction ───────────────────────────────────────────────

_PUBLIC_IP_CACHE: set[str] = set()


def _extract_ips(pcap: Path) -> set[str]:
    """Pull unique src/dst IPv4s from a pcap via tcpdump.

    -n  no DNS, -nn no port-name, -r read file, -t no time.
    Output lines like 'IP 1.2.3.4.443 > 5.6.7.8.51234: Flags ...'
    """
    import re
    import subprocess
    ip_re = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
    ips: set[str] = set()
    try:
        p = subprocess.run(
            ["tcpdump", "-nn", "-t", "-r", str(pcap), "ip"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        for line in (p.stdout or "").splitlines():
            for m in ip_re.findall(line):
                ips.add(m)
    except Exception as exc:
        print(f"[external_intel] tcpdump {pcap.name}: {exc}",
              file=sys.stderr, flush=True)
    return ips


def _collect_public_ips(pcaps: list[Path]) -> list[str]:
    seen: set[str] = set()
    for p in pcaps:
        if not p.exists():
            continue
        for ip in _extract_ips(p):
            if not sl.is_private_ip(ip):
                seen.add(ip)
    return sorted(seen)


# ── BT/WiFi MAC collection ──────────────────────────────────────────────

def _collect_bt_macs(bt_files: list[Path]) -> list[str]:
    """Pull BT MACs from per-round bt_scanner JSON files.

    Real schema (cyt/bt_scanner.py):
        {"timestamp": ..., "gps": {...},
         "bt_devices": {"aa:bb:..": {vendor, rssi, ...}, ...}}
    Tolerated legacy shapes:
        {"devices": [{addr|mac|bdaddr: ...}, ...]}
        [{addr: ...}, ...]
    """
    macs: set[str] = set()
    for f in bt_files:
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        # primary: dict-form bt_devices keyed by MAC
        if isinstance(data, dict):
            bt = data.get("bt_devices")
            if isinstance(bt, dict):
                for mac in bt.keys():
                    if isinstance(mac, str):
                        macs.add(mac.lower())
                continue
            # legacy list-form
            rows = data.get("devices") or []
        else:
            rows = data if isinstance(data, list) else []
        for row in rows:
            if isinstance(row, dict):
                m = row.get("addr") or row.get("mac") or row.get("bdaddr")
                if m:
                    macs.add(m.lower())
    return sorted(macs)


def _collect_wifi_macs(pairings_path: Path | None,
                       session_id: str | None) -> list[str]:
    """Pick WiFi probe-MACs that appeared in this session from pairings.json."""
    if not pairings_path or not pairings_path.exists() or not session_id:
        return []
    try:
        db = json.loads(pairings_path.read_text())
    except Exception:
        return []
    macs: set[str] = set()
    # pairings.json shape: {"<bt_mac>": {"sessions": {sid: {wifi_macs:[...]}}}}
    # We tolerate variations.
    for _bt, entry in (db.items() if isinstance(db, dict) else []):
        if not isinstance(entry, dict):
            continue
        sessions = entry.get("sessions") or {}
        sess = sessions.get(session_id) if isinstance(sessions, dict) else None
        if isinstance(sess, dict):
            for w in sess.get("wifi_macs") or []:
                if isinstance(w, str):
                    macs.add(w.lower())
    return sorted(macs)


# ── Lookups ─────────────────────────────────────────────────────────────

# Hard caps so a single drive-by session with 800+ BT devices doesn't
# saturate the Fingerbank free-tier (30 req/min) or the InternetDB rate.
# Below these limits the analyser stays under 60s for the lookup phase.
_MAX_IP_LOOKUPS  = 50
_MAX_MAC_LOOKUPS = 50


def _lookup_ips(ips: list[str], shodan_key: str | None) -> list[dict]:
    out: list[dict] = []
    for ip in ips[:_MAX_IP_LOOKUPS]:
        info = sl.enrich_ip(ip, api_key=shodan_key, timeout=5)
        if info:
            out.append({"ip": ip, **info})
    return out


def _lookup_macs(macs: list[str], fb_key: str) -> list[dict]:
    out: list[dict] = []
    for mac in macs[:_MAX_MAC_LOOKUPS]:
        r = sl.fingerbank_lookup(mac, fb_key, timeout=5)
        if r:
            out.append({"mac": mac, **r})
    return out


# ── Public entry ────────────────────────────────────────────────────────

def run(*, config: dict,
        pcaps: list[Path],
        bt_files: list[Path],
        pairings_path: Path | None,
        session_id: str | None) -> dict:
    """Returns:

        {
          "findings": ["short bullet", ...],
          "threat_bump": "low" | "medium" | "high" | None,
          "report_block": "markdown ..." | "",
          "ip_results":  [...],
          "mac_results": [...],
        }
    """
    if not _OK:
        return {"findings": [], "threat_bump": None, "report_block": "",
                "ip_results": [], "mac_results": []}

    shodan_key = config.get("shodan_api_key") or None
    fb_key     = config.get("fingerbank_api_key") or ""

    ips       = _collect_public_ips(pcaps)
    # Fingerbank is primarily a WiFi/DHCP-fingerprint database; bulk-
    # querying every BT MAC from a drive-by run (often 500+) hammers the
    # free-tier rate-limit and almost always returns score < 30 anyway.
    # We keep BT MACs for diagnostics in the report header but only ship
    # WiFi probe MACs (from pairings.json, this session) to Fingerbank.
    bt_macs   = _collect_bt_macs(bt_files)
    wifi_macs = _collect_wifi_macs(pairings_path, session_id)
    macs_to_query = sorted(set(wifi_macs))

    ip_results: list[dict] = _lookup_ips(ips, shodan_key) if ips else []
    mac_results: list[dict] = (_lookup_macs(macs_to_query, fb_key)
                               if (fb_key and macs_to_query) else [])

    findings: list[str] = []
    bump: str | None = None

    # IP severity: any vulns -> high; tagged 'cdn'/'cloud' alone -> low.
    risky_ips = [r for r in ip_results if r.get("vulns") or r.get("ports")]
    if risky_ips:
        with_vulns = [r for r in risky_ips if r.get("vulns")]
        if with_vulns:
            findings.append(
                f"InternetDB: {len(with_vulns)} IP(s) with known CVEs")
            bump = "high"
        else:
            findings.append(
                f"InternetDB: {len(risky_ips)} IP(s) with open ports")
            bump = bump or "low"

    # Fingerbank: high-risk = camera/NVR; medium = IoT/embedded.
    high  = [r for r in mac_results if r.get("risk") == "high"]
    med   = [r for r in mac_results if r.get("risk") == "medium"]
    if high:
        findings.append(f"Fingerbank: {len(high)} camera/NVR-class device(s)")
        bump = "high"
    elif med:
        findings.append(f"Fingerbank: {len(med)} IoT/embedded device(s)")
        bump = bump or "medium"

    block = _render_block(ips=ips, ip_results=ip_results,
                          macs=macs_to_query,
                          mac_results=mac_results,
                          bt_macs_total=len(bt_macs),
                          shodan_key=shodan_key, fb_key=fb_key)

    return {"findings": findings, "threat_bump": bump,
            "report_block": block,
            "ip_results": ip_results, "mac_results": mac_results}


# ── Markdown report block ───────────────────────────────────────────────

def _render_block(*, ips: list[str], ip_results: list[dict],
                  macs: list[str], mac_results: list[dict],
                  bt_macs_total: int = 0,
                  shodan_key: str | None, fb_key: str) -> str:
    lines: list[str] = []
    lines.append("## External Intel")
    lines.append("")

    src_bits = []
    src_bits.append("InternetDB" + (" + Shodan" if shodan_key else ""))
    if fb_key:
        src_bits.append("Fingerbank")
    lines.append(f"Sources: {', '.join(src_bits)}.")
    lines.append("")

    # IPs
    lines.append(f"### Public IPs ({len(ip_results)} hit / {len(ips)} seen)")
    if not ips:
        lines.append("_No public IPv4 traffic in capture._")
    elif not ip_results:
        lines.append("_None of the observed IPs returned data._")
    else:
        lines.append("| IP | Org | Ports | Tags | CVEs |")
        lines.append("|---|---|---|---|---|")
        for r in ip_results[:30]:
            ports = ",".join(str(p) for p in (r.get("ports") or [])[:6])
            tags  = ",".join((r.get("tags") or [])[:4])
            vulns = len(r.get("vulns") or [])
            org   = (r.get("org") or "-")[:24]
            lines.append(f"| `{r['ip']}` | {org} | {ports} | {tags} | {vulns} |")
        if len(ip_results) > 30:
            lines.append(f"| ... | ({len(ip_results)-30} more) | | | |")
    lines.append("")

    # MACs
    if fb_key:
        suffix = (f" [{bt_macs_total} BT MACs seen but not queried "
                  f"(low Fingerbank coverage)]" if bt_macs_total else "")
        lines.append(
            f"### Devices ({len(mac_results)} identified / "
            f"{len(macs)} WiFi MACs queried){suffix}")
        if not macs:
            lines.append("_No WiFi MACs collected this session._")
        elif not mac_results:
            lines.append("_Fingerbank returned no high-confidence matches._")
        else:
            lines.append("| MAC | Device | Category | Score | Risk |")
            lines.append("|---|---|---|---|---|")
            for r in mac_results[:50]:
                lines.append(
                    f"| `{r['mac']}` | {r.get('device_name','?')[:24]} "
                    f"| {r.get('category','?')[:20]} "
                    f"| {r.get('score',0)} | {r.get('risk','-')} |")
            if len(mac_results) > 50:
                lines.append(f"| ... | ({len(mac_results)-50} more) | | | |")
        lines.append("")
    else:
        lines.append("_Fingerbank disabled (no `fingerbank_api_key` in config)._")
        lines.append("")

    return "\n".join(lines)
