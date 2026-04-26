"""Capture orchestrator — replaces v1.3 ``run_wifi_bt_scan()``.

Drives ``tcpdump`` (WiFi PCAP), ``btmon`` (BT capture), ``iw`` (channel hopping),
plus background SSH calls to the Mudi for GPS / cell. Each round writes its
artefacts under ``$LOOT_DIR/argus/{pcap,bt,gps_track.csv}`` and the engine
hands them to the cyt + raypager analysers when ``finish()`` is called.

Pause/Resume contract: ``pause()`` SIGSTOPs the active capture children so the
PCAP timeline pauses cleanly; ``resume()`` SIGCONTinues them and the scheduler
re-extends the round deadline. Background watchers (imsi_monitor / silent_sms
on the Mudi) keep running across pauses — they are out of scope here.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import mudi_client
from . import deauth_monitor


class ScanEngine:
    def __init__(self, config: dict, preset: dict):
        self.config = config
        self.preset = preset
        self.paths = config.get("paths") or {}
        self.base = Path(self.paths.get("base_dir", "/root/loot/argus"))
        self.pcap_dir = Path(self.paths.get("pcap_dir", str(self.base / "pcap")))
        self.report_dir = Path(self.paths.get("report_dir", str(self.base / "reports")))
        self.gps_track = Path(self.paths.get("gps_track", str(self.base / "gps_track.csv")))
        for d in (self.base, self.pcap_dir, self.report_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.pcap_files: list[Path] = []
        self.bt_files: list[Path] = []
        self._procs: list[subprocess.Popen] = []
        self._round_idx = 0
        self._stats = {
            "wifi_devices": 0,
            "bt_devices":   0,
            "imsi":         "--",
            "gps":          "--",
            "deauth":       0,
        }
        self._stats_lock = threading.Lock()
        self._mudi_thread: threading.Thread | None = None
        self._mudi_stop = threading.Event()
        self._deauth: deauth_monitor.DeauthMonitor | None = None
        self._deauth_summary: dict = {}

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        # Mudi background sampler (GPS + cell) - only if any cell/gps_mudi enabled
        if self.preset.get("cell") or self.preset.get("gps_mudi"):
            self._mudi_thread = threading.Thread(target=self._mudi_loop, daemon=True)
            self._mudi_thread.start()
        # Deauth monitor runs whenever WiFi is enabled (passive sniffer)
        if self.preset.get("wifi"):
            cfg = (self.config.get("deauth") or {})
            self._deauth = deauth_monitor.DeauthMonitor(
                iface=cfg.get("iface", "wlan1mon"),
                loot_dir=self.base,
                window_s=int(cfg.get("window_s", 10)),
                flood_threshold=int(cfg.get("flood_threshold", 5)),
            )
            self._deauth.start()
        self._round_idx = 0
        self._begin_round(1)

    def tick(self, sched) -> None:
        # Are we due for next round?
        if sched.advance_round() and sched.current_round != self._round_idx:
            self._end_round()
            self._begin_round(sched.current_round)

    def pause(self) -> None:
        for p in self._procs:
            try:
                os.kill(p.pid, signal.SIGSTOP)
            except Exception:
                pass

    def resume(self) -> None:
        for p in self._procs:
            try:
                os.kill(p.pid, signal.SIGCONT)
            except Exception:
                pass

    def stop(self) -> None:
        self._end_round()

    def finish(self) -> dict:
        """Cleanup + run analysers, return result dict for the report screen."""
        self._end_round()
        if self._mudi_thread is not None:
            self._mudi_stop.set()
            self._mudi_thread.join(timeout=4)
        if self._deauth is not None:
            self._deauth_summary = self._deauth.stop()

        from . import analyser  # local import to keep boot fast
        return analyser.run_all(self.config, self.preset,
                                pcaps=self.pcap_files,
                                bt_files=self.bt_files,
                                gps_track=self.gps_track,
                                report_dir=self.report_dir,
                                session_id=self.session_id,
                                deauth_summary=self._deauth_summary)

    # ── live stats for scan_live screen ──────────────────────────────

    def live_stats(self) -> dict:
        with self._stats_lock:
            stats = dict(self._stats)
        if self._deauth is not None:
            try:
                snap = self._deauth.snapshot()
                stats["deauth"] = snap.get("total", 0)
                stats["deauth_rate"] = snap.get("rate_per_s", 0.0)
                stats["deauth_floods"] = snap.get("flood_count", 0)
            except Exception:
                pass
        return stats

    # ── per-round capture ───────────────────────────────────────────

    def _begin_round(self, round_idx: int) -> None:
        self._round_idx = round_idx
        ts = time.strftime("%H%M%S")
        prefix = f"{self.session_id}_r{round_idx:02d}_{ts}"

        # WiFi PCAP — wlan1mon is already monitor mode on the pager
        if self.preset.get("wifi"):
            pcap = self.pcap_dir / f"{prefix}.pcap"
            self.pcap_files.append(pcap)
            self._procs.append(subprocess.Popen(
                ["tcpdump", "-i", "wlan1mon", "-w", str(pcap), "-U",
                 "-s", "256", "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
            # parallel channel hopper
            self._procs.append(subprocess.Popen(
                ["bash", "-c",
                 "while true; do for c in 1 6 11 36 40 44 48 149 153 157 161; "
                 "do iw dev wlan1mon set channel $c 2>/dev/null; sleep 0.5; done; done"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))

        # BT capture (btmon -w produces a parsable file for bt_scanner.py)
        if self.preset.get("bt"):
            btf = self.pcap_dir / f"{prefix}.btsnoop"
            self.bt_files.append(btf)
            self._procs.append(subprocess.Popen(
                ["btmon", "-w", str(btf)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))

    def _end_round(self) -> None:
        for p in list(self._procs):
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass
        # short grace period
        deadline = time.monotonic() + 2.0
        for p in self._procs:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                p.wait(timeout=remaining)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._procs.clear()

    # ── Mudi sampler (background) ────────────────────────────────────

    def _mudi_loop(self) -> None:
        sample_interval = 30
        while not self._mudi_stop.is_set():
            try:
                if self.preset.get("gps_mudi"):
                    pos = mudi_client.gps_get(self.config, timeout_s=8)
                    if pos:
                        with self._stats_lock:
                            self._stats["gps"] = "lock"
                        with self.gps_track.open("a", encoding="utf-8") as f:
                            f.write(f"{int(time.time())},{pos[0]:.6f},{pos[1]:.6f}\n")
                    else:
                        with self._stats_lock:
                            self._stats["gps"] = "no-fix"
                if self.preset.get("cell"):
                    info = mudi_client.cell_info(self.config)
                    if info:
                        threat = info.get("threat") or info.get("opencellid_threat") or "CLEAN"
                        with self._stats_lock:
                            self._stats["imsi"] = str(threat)[:10]
            except Exception:
                pass
            self._mudi_stop.wait(sample_interval)
