"""Deauthentication / disassociation flood detector.

Runs alongside the WiFi capture: a parallel tcpdump filtered to
802.11 management frames of subtype Deauthentication (12) or
Disassociation (10), parsed line-by-line so we can flag floods
in near real-time without waiting for the post-scan analyser.

Detection logic
---------------
- Per-second event rate over the last ``window_s`` seconds is
  computed from a ring buffer of timestamps.
- Above ``flood_threshold`` events/sec the monitor classifies the
  burst as a likely *deauth flood attack* (typical Pineapple /
  mdk4 / aireplay-ng signature is >>20/s, harmless legit deauth
  is <2/s even on a busy AP).
- Per-source-MAC counters surface which BSSID is being targeted
  vs. who is doing the spraying.

Findings are written to ``$LOOT_DIR/argus/deauth.jsonl`` (one event
per line) and a final summary to ``deauth_summary.json`` so the
analyser can include them in the report.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional


# tcpdump output line format we rely on (timestamp, then radiotap/802.11
# fields incl. DA / SA / BSSID). We don't need a full 802.11 parser; we
# just pull MAC-shaped tokens in order and trust the first two as a
# (target, source) pair for rate-stat grouping. Forensic attribution is
# not the goal here - the goal is "is the air storming with deauth?".
_MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")


class DeauthMonitor:
    """Background tcpdump watcher. Thread-safe stats via ``snapshot()``."""

    def __init__(
        self,
        *,
        iface: str = "wlan1mon",
        loot_dir: Path = Path("/root/loot/argus"),
        window_s: int = 10,
        flood_threshold: int = 5,
    ):
        self.iface = iface
        self.loot_dir = Path(loot_dir)
        self.window_s = int(window_s)
        self.flood_threshold = int(flood_threshold)

        self.loot_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.loot_dir / "deauth.jsonl"
        self.summary_path = self.loot_dir / "deauth_summary.json"

        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._lock = threading.Lock()
        self._timestamps: deque = deque(maxlen=2000)
        self._by_src: dict[str, int] = {}
        self._by_dst: dict[str, int] = {}
        self._floods: list[dict] = []
        self._total = 0
        self._last_flood_ts = 0.0

    # lifecycle

    def start(self) -> bool:
        try:
            # Filter: management subtype 10 (disassoc) or 12 (deauth).
            # -e prepends link-layer addresses so we can grep MACs.
            self._proc = subprocess.Popen(
                ["tcpdump", "-i", self.iface, "-l", "-n", "-e",
                 "type mgt and (subtype deauth or subtype disassoc)"],
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

    # reader thread

    def _read_loop(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            self._process_line(line, ts=time.time())

    def _process_line(self, line: str, *, ts: float | None = None) -> None:
        """Parse a single tcpdump line and update counters / flood state.

        Public for tests so we can feed synthetic lines without spawning
        a real ``tcpdump`` process.
        """
        macs = _MAC_RE.findall(line)
        if not macs:
            return
        if ts is None:
            ts = time.time()
        # In radiotap+802.11 the order is usually DA, SA, BSSID
        # but tcpdump's -e prints RA, TA, ... depending on type.
        # We just take the first two MACs as dst/src guesses for
        # rate stats; they're for grouping only, not forensic.
        dst = macs[0]
        src = macs[1] if len(macs) > 1 else "?"
        with self._lock:
            self._total += 1
            self._timestamps.append(ts)
            self._by_src[src] = self._by_src.get(src, 0) + 1
            self._by_dst[dst] = self._by_dst.get(dst, 0) + 1
            rate = self._rate_locked(ts)
            if rate >= self.flood_threshold and (ts - self._last_flood_ts) > 5:
                self._last_flood_ts = ts
                flood = {
                    "ts": ts, "rate_per_s": round(rate, 2),
                    "src": src, "dst": dst, "window_s": self.window_s,
                }
                self._floods.append(flood)
                self._append_event(flood)

    def _append_event(self, evt: dict) -> None:
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt) + "\n")
        except Exception:
            pass

    def _rate_locked(self, now: float) -> float:
        cutoff = now - self.window_s
        n = sum(1 for ts in self._timestamps if ts >= cutoff)
        return n / max(1, self.window_s)

    # query

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                "total":          self._total,
                "rate_per_s":     round(self._rate_locked(now), 2),
                "flood_count":    len(self._floods),
                "flood_threshold": self.flood_threshold,
                "top_sources":    sorted(
                    self._by_src.items(), key=lambda kv: -kv[1])[:5],
                "top_targets":    sorted(
                    self._by_dst.items(), key=lambda kv: -kv[1])[:5],
                "last_floods":    self._floods[-5:],
            }
