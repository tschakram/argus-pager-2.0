"""WiFi management-frame watcher.

One ``tcpdump -i wlan1mon -l -n -e`` process listens for the management
frame subtypes we care about (probe-req, deauth, disassoc) and pushes
each line through ``_process_line``. From there:

- **Probe-Request** -> unique source-MAC tracking (live wifi_devices
  counter for the scan_live screen, plus first_ts / last_ts for the
  later WiFi<->BT pairing DB).
- **Deauth / Disassoc** -> per-second rate over a sliding window;
  flood detection above a threshold (typical Pineapple / mdk4 /
  aireplay signature is >>20/s, harmless legit deauth is <2/s).

Findings are written to ``$LOOT_DIR/argus/deauth.jsonl`` (one event
per detected flood) and a final summary to ``deauth_summary.json``.
The probe-request data is exposed via ``snapshot()`` only - it lives
in RAM during the run, the analyser pulls it out at finish-time.

Pre-rename note: this module replaces the older ``deauth_monitor``;
the public class is ``WifiWatcher`` now (was ``DeauthMonitor``).
"""
from __future__ import annotations

import json
import re
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional


# tcpdump -e prints link-layer addresses inline; we just pull out
# MAC-shaped tokens. The first two are usually (RA/DA, TA/SA) for
# the management subtypes we filter for.
_MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")


class WifiWatcher:
    """Background tcpdump watcher. Thread-safe stats via ``snapshot()``."""

    def __init__(
        self,
        *,
        iface: str = "wlan1mon",
        loot_dir: Path = Path("/root/loot/argus"),
        window_s: int = 10,
        flood_threshold: int = 5,
        on_flood=None,
    ):
        self.iface = iface
        self.loot_dir = Path(loot_dir)
        self.window_s = int(window_s)
        self.flood_threshold = int(flood_threshold)
        # Optional callback fired (in the reader thread) when a new flood
        # is detected. Used by scan_engine to archive the round PCAP for
        # forensic / police-evidence purposes.
        self.on_flood = on_flood

        self.loot_dir.mkdir(parents=True, exist_ok=True)
        self.events_path  = self.loot_dir / "deauth.jsonl"
        self.summary_path = self.loot_dir / "deauth_summary.json"

        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._lock = threading.Lock()
        # Deauth/Disassoc accounting
        self._deauth_timestamps: deque = deque(maxlen=2000)
        self._deauth_total = 0
        self._deauth_by_src: dict[str, int] = {}
        self._deauth_by_dst: dict[str, int] = {}
        self._floods: list[dict] = []
        self._last_flood_ts = 0.0
        # Probe-Request accounting (per source MAC)
        # value shape: {"count": int, "first_ts": float, "last_ts": float}
        self._probes_by_src: dict[str, dict] = {}
        self._probe_total = 0

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                ["tcpdump", "-i", self.iface, "-l", "-n", "-e",
                 "type mgt and (subtype deauth or subtype disassoc "
                 "or subtype probe-req)"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=1, text=True,
            )
        except Exception:
            self._proc = None
            return False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def stop(self) -> dict:
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.send_signal(signal.SIGTERM)
                try:
                    self._proc.wait(timeout=2.0)
                except Exception:
                    self._proc.kill()
            except Exception:
                pass
        if self._reader is not None:
            self._reader.join(timeout=2.0)
        summary = self.snapshot()
        try:
            self.summary_path.write_text(
                json.dumps(summary, indent=2), encoding="utf-8",
            )
        except Exception:
            pass
        return summary

    # ── reader thread ────────────────────────────────────────────────

    def _read_loop(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            self._process_line(line, ts=time.time())

    def _process_line(self, line: str, *, ts: float | None = None) -> None:
        """Parse a single tcpdump line. Public for tests so we can feed
        synthetic lines without spawning a real ``tcpdump`` process."""
        if ts is None:
            ts = time.time()
        macs = _MAC_RE.findall(line)
        if not macs:
            return

        # Heuristic: the textual frame label is enough to dispatch.
        # tcpdump -e prints 'Probe Request', 'Deauthentication',
        # 'Disassociation' for the subtypes we filter to.
        is_probe = "Probe Request" in line
        is_deauth = ("Deauth" in line) or ("Disassoc" in line)

        if is_probe:
            # In Probe-Req the second MAC is the transmitter (mobile client).
            src = macs[1] if len(macs) > 1 else macs[0]
            with self._lock:
                self._probe_total += 1
                rec = self._probes_by_src.get(src)
                if rec is None:
                    self._probes_by_src[src] = {
                        "count": 1, "first_ts": ts, "last_ts": ts,
                    }
                else:
                    rec["count"] += 1
                    rec["last_ts"] = ts
            return

        if is_deauth:
            dst = macs[0]
            src = macs[1] if len(macs) > 1 else "?"
            new_flood = None
            with self._lock:
                self._deauth_total += 1
                self._deauth_timestamps.append(ts)
                self._deauth_by_src[src] = self._deauth_by_src.get(src, 0) + 1
                self._deauth_by_dst[dst] = self._deauth_by_dst.get(dst, 0) + 1
                rate = self._rate_locked(ts)
                if rate >= self.flood_threshold and (ts - self._last_flood_ts) > 5:
                    self._last_flood_ts = ts
                    new_flood = {
                        "ts": ts, "rate_per_s": round(rate, 2),
                        "src": src, "dst": dst, "window_s": self.window_s,
                    }
                    self._floods.append(new_flood)
                    self._append_event(new_flood)
            # Run flood callback OUTSIDE the lock: it may do file I/O
            # (PCAP archive copy can take a moment on slow flash).
            if new_flood is not None and self.on_flood is not None:
                try:
                    self.on_flood(new_flood)
                except Exception:
                    pass

    def _append_event(self, evt: dict) -> None:
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt) + "\n")
        except Exception:
            pass

    def _rate_locked(self, now: float) -> float:
        cutoff = now - self.window_s
        n = sum(1 for ts in self._deauth_timestamps if ts >= cutoff)
        return n / max(1, self.window_s)

    # ── query ────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                # Deauth/Disassoc (legacy keys kept for analyser compat)
                "total":           self._deauth_total,
                "rate_per_s":      round(self._rate_locked(now), 2),
                "flood_count":     len(self._floods),
                "flood_threshold": self.flood_threshold,
                "top_sources":     sorted(
                    self._deauth_by_src.items(), key=lambda kv: -kv[1])[:5],
                "top_targets":     sorted(
                    self._deauth_by_dst.items(), key=lambda kv: -kv[1])[:5],
                "last_floods":     self._floods[-5:],
                # Probe-Request live counters
                "wifi_devices":    len(self._probes_by_src),
                "probe_total":     self._probe_total,
            }

    def probe_macs(self) -> dict[str, dict]:
        """Snapshot of unique probing MACs with first/last timestamps.

        Used by the WiFi<->BT pairing DB at scan finish-time. Returns a
        deep-copied dict so the caller can iterate without locking.
        """
        with self._lock:
            return {mac: dict(rec) for mac, rec in self._probes_by_src.items()}
