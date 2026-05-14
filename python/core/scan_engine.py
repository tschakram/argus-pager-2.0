"""Capture orchestrator — replaces v1.3 ``run_wifi_bt_scan()``.

Drives ``tcpdump`` (WiFi PCAP), ``cyt/bt_scanner.py`` (BT JSON capture),
``iw`` (channel hopping), plus background SSH calls to the Mudi for
GPS / cell. Each round writes its artefacts under
``$LOOT_DIR/argus/{pcap,bt,gps_track.csv}`` and the engine hands them
to the cyt + raypager analysers when ``finish()`` is called.

Pause/Resume contract: ``pause()`` SIGSTOPs the active capture children so the
PCAP timeline pauses cleanly; ``resume()`` SIGCONTinues them and the scheduler
re-extends the round deadline. Background watchers (imsi_monitor / silent_sms
on the Mudi) keep running across pauses — they are out of scope here.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import mudi_client
from . import wifi_watcher
from . import wifi_channels

PAYLOAD_DIR = Path(os.environ.get("ARGUS_PAYLOAD_DIR",
                                  Path(__file__).resolve().parents[2]))
BT_SCANNER  = PAYLOAD_DIR / "cyt" / "python" / "bt_scanner.py"


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
        self._procs: list[subprocess.Popen] = []      # SIGTERM at round-end
        self._bt_procs: list[subprocess.Popen] = []   # natural-exit, brief wait
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
        self._mudi_pause = threading.Event()
        # Cellular snapshots fuer Trend-Analyse - jeder Mudi-cell-Poll
        # legt ein dict ab (ts, rsrp, pci, cid, rat, nb_count, neighbours,
        # gps_lat, gps_lon). Wird vom analyser via engine.cell_snapshots
        # gelesen und an cell_anomaly weitergegeben.
        self.cell_snapshots: list[dict] = []
        self._cell_snapshots_lock = threading.Lock()
        self._last_gps: tuple[float, float] | None = None
        # Sticky-Mode: GPS-Status springt nicht sofort auf "no-fix" bei
        # einer einzelnen failed gps_get(). Erst nach GPS_LOCK_STALE_S
        # ohne erfolgreichen Fix wird "stale" oder "no-fix" angezeigt.
        # Endurance-Test 14.05. zeigte: einzelne Mudi-Timeouts triggern
        # sonst "no-fix" obwohl GPS in der Sekunde davor noch lieferte.
        self._last_gps_ts: float = 0.0
        self._wifi: wifi_watcher.WifiWatcher | None = None
        self._deauth_summary: dict = {}
        self.iface = (config.get("deauth") or {}).get("iface", "wlan1mon")
        self.channels: dict = {"2.4": [], "5": [], "6": [], "all": []}
        self.hopper_log = Path("/tmp/argus_hopper.log")

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        # Roll the GPS track: keep only the last GPS_TRACK_KEEP_DAYS days.
        self._roll_gps_track()
        # Discover frequencies the chip actually supports — once per session.
        if self.preset.get("wifi"):
            self.channels = wifi_channels.discover_channels(self.iface)
            n24 = len(self.channels["2.4"])
            n5  = len(self.channels["5"])
            n6  = len(self.channels["6"])
            print(f"[scan_engine] freqs {self.iface}: "
                  f"2.4GHz={n24} 5GHz={n5} 6GHz={n6} (PSC) "
                  f"total={n24 + n5 + n6}",
                  file=__import__("sys").stderr, flush=True)
            try:
                self.hopper_log.write_text("")  # truncate
            except Exception:
                pass
        # Mudi background sampler (GPS + cell) - only if any cell/gps_mudi enabled
        if self.preset.get("cell") or self.preset.get("gps_mudi"):
            self._mudi_thread = threading.Thread(target=self._mudi_loop, daemon=True)
            self._mudi_thread.start()
        # WiFi watcher runs whenever WiFi is enabled (passive mgmt-frame
        # sniffer). Tracks probe-req source MACs (live wifi_devices) and
        # flags deauth/disassoc floods (deauth_summary for the analyser).
        # on_flood persists the active round PCAP for forensic use.
        if self.preset.get("wifi"):
            cfg = (self.config.get("deauth") or {})
            self._wifi = wifi_watcher.WifiWatcher(
                iface=cfg.get("iface", "wlan1mon"),
                loot_dir=self.base,
                window_s=int(cfg.get("window_s", 10)),
                flood_threshold=int(cfg.get("flood_threshold", 5)),
                on_flood=self._on_flood,
            )
            self._wifi.start()
        self._round_idx = 0
        self._begin_round(1)

    def tick(self, sched) -> None:
        # Are we due for next round?
        if sched.advance_round() and sched.current_round != self._round_idx:
            self._end_round()
            self._begin_round(sched.current_round)

    def pause(self) -> None:
        for p in (*self._procs, *self._bt_procs):
            try:
                os.kill(p.pid, signal.SIGSTOP)
            except Exception:
                pass
        self._mudi_pause.set()

    def resume(self) -> None:
        for p in (*self._procs, *self._bt_procs):
            try:
                os.kill(p.pid, signal.SIGCONT)
            except Exception:
                pass
        self._mudi_pause.clear()

    def stop(self) -> None:
        self._end_round()

    def finish(self) -> dict:
        """Cleanup + run analysers, return result dict for the report screen."""
        self._end_round()
        if self._mudi_thread is not None:
            self._mudi_stop.set()
            self._mudi_thread.join(timeout=4)
        wifi_probes: dict = {}
        if self._wifi is not None:
            # Snapshot probe MACs BEFORE stop() so the dict is still
            # populated; stop() joins the reader thread and writes the
            # deauth summary, after which probe_macs() still works
            # (it's lock-protected) but might race-clear in the future.
            wifi_probes = self._wifi.probe_macs()
            self._deauth_summary = self._wifi.stop()

        from . import analyser  # local import to keep boot fast
        # Hopper failures (if any) - read once, attach to settings.
        hopper_errs = ""
        try:
            if self.hopper_log.exists():
                hopper_errs = self.hopper_log.read_text()[-1500:]
        except Exception:
            pass
        scan_settings = {
            "preset_name": self.preset.get("_name", "?"),
            "preset":      dict(self.preset),
            "iface":       self.iface,
            "channels":    self.channels,
            "session_id":  self.session_id,
            "hopper_errors": hopper_errs,
        }
        # Drop bt_files that never got written (mid-round STOP before
        # bt_scanner finished). The analyser would skip them anyway, but
        # filtering here keeps the report header's BT-files count honest.
        bt_files_present = [f for f in self.bt_files if f.exists()]
        with self._cell_snapshots_lock:
            cell_snaps_copy = list(self.cell_snapshots)
        return analyser.run_all(self.config, self.preset,
                                pcaps=self.pcap_files,
                                bt_files=bt_files_present,
                                gps_track=self.gps_track,
                                report_dir=self.report_dir,
                                session_id=self.session_id,
                                deauth_summary=self._deauth_summary,
                                scan_settings=scan_settings,
                                wifi_probes=wifi_probes,
                                cell_snapshots=cell_snaps_copy)

    # ── live stats for scan_live screen ──────────────────────────────

    def live_stats(self) -> dict:
        with self._stats_lock:
            stats = dict(self._stats)
        if self._wifi is not None:
            try:
                snap = self._wifi.snapshot()
                stats["wifi_devices"]  = snap.get("wifi_devices", 0)
                stats["probe_total"]   = snap.get("probe_total", 0)
                stats["deauth"]        = snap.get("total", 0)
                stats["deauth_rate"]   = snap.get("rate_per_s", 0.0)
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
                ["tcpdump", "-i", self.iface, "-w", str(pcap), "-U",
                 "-s", "256", "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
            # parallel channel hopper — dynamic frequency list from chip caps.
            # Frequencies (MHz), not channel numbers, because channels overlap
            # across bands (ch.1 = 2412 MHz AND 5955 MHz). Dwell scales with
            # list length so a full sweep stays roughly 8-12s.
            freqs = self.channels.get("all") or [
                2412, 2437, 2462, 5180, 5200, 5220, 5240,
                5745, 5765, 5785, 5805,
            ]
            n = max(1, len(freqs))
            dwell = max(0.15, min(0.5, 10.0 / n))
            freq_str = " ".join(str(f) for f in freqs)
            # stderr from `iw set freq` is appended to hopper_log so we can
            # see afterwards which freqs the driver rejected (DFS lockout,
            # regdom block, etc.).
            hopper_cmd = (
                f"while true; do for f in {freq_str}; do "
                f"iw dev {self.iface} set freq $f "
                f"|| echo \"$(date +%H:%M:%S) freq=$f FAIL\" >> {self.hopper_log}; "
                f"sleep {dwell:.2f}; done; done"
            )
            with open(self.hopper_log, "ab") as logf:
                self._procs.append(subprocess.Popen(
                    ["bash", "-c", hopper_cmd],
                    stdout=subprocess.DEVNULL, stderr=logf,
                ))

        # BT capture: cyt/bt_scanner.py writes a JSON the analyser can read.
        # bt_scanner has no signal handler, so SIGTERM during natural-exit
        # JSON-write would lose the file. We track it in a separate list
        # (_bt_procs) and let _end_round() wait briefly for natural exit
        # before falling back to SIGTERM. Duration is slightly shorter than
        # the round so the natural exit lands inside the round window.
        # Stderr is captured to a per-round log so silent failures (OUI
        # download hang, btmon permissions, etc.) become diagnosable.
        if self.preset.get("bt") and BT_SCANNER.exists():
            btf = self.pcap_dir / f"{prefix}.bt.json"
            bt_log = self.base / "logs" / f"bt_{prefix}.log"
            bt_log.parent.mkdir(parents=True, exist_ok=True)
            self.bt_files.append(btf)
            round_dur = int(self.preset.get("duration_s", 120))
            # bt_scanner overhead on top of --duration:
            #   ~14s GPS-fix probe (no GPS on pager -> times out)
            #   ~9s OUI-DB load
            #   ~5s initial BT-classic inquiry
            #   ~10s SDP query per Classic device (default timeout)
            #   ~1s JSON write
            # Reserve 25s of headroom so natural-exit lands inside the
            # round window even with one Classic device requiring SDP.
            bt_dur = max(15, round_dur - 25)
            # No USB GPS dongle on the pager — Mudi already feeds gps_track.csv
            # via the _mudi_loop. Tell bt_scanner to skip the GPS_GET fallback
            # so each round doesn't waste 3-5s on a guaranteed-no-fix probe.
            bt_env = dict(os.environ)
            bt_env["BT_SCANNER_NO_LOCAL_GPS"] = "1"
            self._bt_procs.append(subprocess.Popen(
                [sys.executable, str(BT_SCANNER),
                 "--duration", str(bt_dur),
                 "--output",   str(btf)],
                stdout=subprocess.DEVNULL,
                stderr=bt_log.open("ab"),
                env=bt_env,
            ))

    def _end_round(self) -> None:
        # Phase 1: wait briefly for self-terminating procs (bt_scanner) to
        # finish their natural exit + JSON write. They were started with
        # --duration < round_dur so they should already be finishing.
        if self._bt_procs:
            # 25s grace covers the worst case of one Classic device requiring
            # SDP (~10s) plus JSON serialisation, even if bt_scanner only
            # finishes its BLE scan right as _end_round triggers.
            grace = time.monotonic() + 25.0
            while time.monotonic() < grace:
                if all(p.poll() is not None for p in self._bt_procs):
                    break
                time.sleep(0.2)
            for p in self._bt_procs:
                rc = p.poll()
                if rc is None:
                    print(f"[scan_engine] bt_scanner pid={p.pid} still "
                          f"running after grace; SIGTERM",
                          file=sys.stderr, flush=True)
                    try: p.send_signal(signal.SIGTERM)
                    except Exception: pass
                    try: p.wait(timeout=1.0)
                    except Exception:
                        try: p.kill()
                        except Exception: pass
                else:
                    print(f"[scan_engine] bt_scanner pid={p.pid} exited rc={rc}",
                          file=sys.stderr, flush=True)
            self._bt_procs.clear()

            # After bt_scanner finished its round, surface the BT-device
            # count to the live scan_live screen (until then it shows 0).
            if self.bt_files:
                last_btf = self.bt_files[-1]
                if last_btf.exists():
                    try:
                        data = json.loads(last_btf.read_text(encoding="utf-8"))
                        n = len(data.get("bt_devices") or {})
                        with self._stats_lock:
                            self._stats["bt_devices"] = n
                    except Exception:
                        pass

        # Phase 2: long-running procs (tcpdump, channel hopper) get SIGTERM
        # immediately - they don't self-terminate.
        for p in list(self._procs):
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass
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

    # ── Forensic incident archive ────────────────────────────────────

    def _on_flood(self, flood: dict) -> None:
        """Persist forensic evidence when wifi_watcher flags a deauth flood.

        Snapshots the active round's PCAP (still being written by tcpdump,
        but PCAP frames are atomic so we get a valid prefix) and writes a
        sidecar JSON with the metadata a police report would need:
        UTC timestamp, GPS, source / target MACs, rate, window. Files
        land in ``<base>/incidents/`` which is never overwritten by
        subsequent scans.
        """
        try:
            incidents_dir = self.base / "incidents"
            incidents_dir.mkdir(parents=True, exist_ok=True)
            ts_iso = time.strftime("%Y%m%d_%H%M%S",
                                   time.gmtime(float(flood.get("ts") or time.time())))
            base_name = f"deauth_{ts_iso}"
            if self.pcap_files:
                src_pcap = self.pcap_files[-1]
                dst_pcap = incidents_dir / f"{base_name}.pcap"
                try:
                    shutil.copy2(src_pcap, dst_pcap)
                except Exception:
                    pass
            with self._stats_lock:
                gps = self._stats.get("gps", "--")
            frame_total = 0
            if self._wifi is not None:
                try:
                    frame_total = int(self._wifi.snapshot().get("total", 0))
                except Exception:
                    pass
            meta = {
                "ts_utc":      ts_iso,
                "session_id":  self.session_id,
                "round_idx":   self._round_idx,
                "rate_per_s":  flood.get("rate_per_s"),
                "src_mac":     flood.get("src"),
                "target_mac":  flood.get("dst"),
                "window_s":    flood.get("window_s"),
                "frame_total": frame_total,
                "iface":       self.iface,
                "gps":         gps,
                "preset":      dict(self.preset),
            }
            (incidents_dir / f"{base_name}.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8",
            )
            print(f"[scan_engine] FLOOD archived: {base_name} "
                  f"src={meta['src_mac']} rate={meta['rate_per_s']}/s",
                  file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[scan_engine] _on_flood failed: {exc}",
                  file=sys.stderr, flush=True)

    # ── Mudi sampler (background) ────────────────────────────────────

    GPS_LOCK_STALE_S = 30   # nach 30s ohne Fix -> "stale"
    GPS_LOCK_LOST_S  = 90   # nach 90s ohne Fix -> "no-fix"

    def _mudi_loop(self) -> None:
        sample_interval = 10
        cell_every_n    = 6   # cell-info every 60s
        tick = 0
        while not self._mudi_stop.is_set():
            if not self._mudi_pause.is_set():
                try:
                    if self.preset.get("gps_mudi"):
                        pos = mudi_client.gps_get(self.config, timeout_s=8)
                        now = time.time()
                        if pos:
                            self._last_gps = pos
                            self._last_gps_ts = now
                            with self._stats_lock:
                                self._stats["gps"] = "lock"
                            with self.gps_track.open("a", encoding="utf-8") as f:
                                f.write(f"{int(now)},{pos[0]:.6f},{pos[1]:.6f}\n")
                        else:
                            # Sticky-Mode: einzelne fails clobbern nicht
                            # sofort den UI-Status. Erst nach STALE_S "stale",
                            # nach LOST_S endgueltig "no-fix".
                            age = now - self._last_gps_ts if self._last_gps_ts else 999
                            if age < self.GPS_LOCK_STALE_S:
                                # noch frischer Fix vorhanden - kein UI-Wechsel
                                pass
                            elif age < self.GPS_LOCK_LOST_S:
                                with self._stats_lock:
                                    self._stats["gps"] = "stale"
                            else:
                                with self._stats_lock:
                                    self._stats["gps"] = "no-fix"
                    if self.preset.get("cell") and (tick % cell_every_n) == 0:
                        info = mudi_client.cell_info(self.config)
                        nbs  = mudi_client.cell_neighbors(self.config)
                        if info:
                            threat = info.get("threat") or info.get("opencellid_threat") or "CLEAN"
                            with self._stats_lock:
                                self._stats["imsi"] = str(threat)[:10]
                            # Snapshot fuer Trend-Analyse (cell_anomaly)
                            snap = {
                                "ts":               int(time.time()),
                                "serving_rsrp":     info.get("rsrp"),
                                "serving_pci":      info.get("pcid", info.get("pci")),
                                "serving_cid":      info.get("cell_id"),
                                "serving_tac":      info.get("tac", info.get("lac")),
                                "rat":              info.get("rat"),
                                "neighbour_count":  (nbs or {}).get("count", 0),
                                "neighbours":       (nbs or {}).get("neighbours", []),
                            }
                            if self._last_gps:
                                snap["gps_lat"] = self._last_gps[0]
                                snap["gps_lon"] = self._last_gps[1]
                            with self._cell_snapshots_lock:
                                self.cell_snapshots.append(snap)
                except Exception:
                    pass
            tick += 1
            self._mudi_stop.wait(sample_interval)

    # ── GPS track retention ──────────────────────────────────────────

    GPS_TRACK_KEEP_DAYS = 30

    def _roll_gps_track(self) -> None:
        """Trim gps_track.csv to the last GPS_TRACK_KEEP_DAYS days.

        File mixes legacy ``YYYYMMDD_HHMMSS,lat,lon`` rows with current
        ``unix_epoch,lat,lon`` rows; we keep both formats and drop only
        rows whose timestamp is interpretable AND older than the cutoff.
        Unparseable rows are kept (no destructive guesswork).
        """
        if not self.gps_track.exists():
            return
        try:
            cutoff = time.time() - self.GPS_TRACK_KEEP_DAYS * 86400
            kept: list[str] = []
            dropped = 0
            with self.gps_track.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    parts = s.split(",")
                    if len(parts) < 3:
                        kept.append(line.rstrip("\n"))
                        continue
                    ts = parts[0]
                    when: float | None = None
                    if ts.isdigit():
                        try:
                            when = float(ts)
                        except Exception:
                            when = None
                    elif "_" in ts and len(ts) == 15:
                        try:
                            when = time.mktime(time.strptime(ts, "%Y%m%d_%H%M%S"))
                        except Exception:
                            when = None
                    if when is not None and when < cutoff:
                        dropped += 1
                        continue
                    kept.append(line.rstrip("\n"))
            if dropped == 0:
                return
            tmp = self.gps_track.with_suffix(self.gps_track.suffix + ".tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""),
                           encoding="utf-8")
            tmp.replace(self.gps_track)
            print(f"[scan_engine] gps_track rolled: dropped {dropped} "
                  f"row(s) older than {self.GPS_TRACK_KEEP_DAYS}d, "
                  f"kept {len(kept)}",
                  file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[scan_engine] _roll_gps_track failed: {exc}",
                  file=sys.stderr, flush=True)
