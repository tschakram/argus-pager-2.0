"""WiFi RSSI Sampler — tcpdump live-stream + Radiotap-Parser.

Spawnt tcpdump auf wlan1mon mit BPF-Filter auf addr2 == target_mac.
Schreibt PCAP nach stdout, Reader-Thread parst Radiotap-Header und
schiebt jeden RSSI-Wert in eine thread-safe Queue. Optional rotiert
ein Channel-Hopper-Thread durch 2.4-GHz-Channels (1/6/11).

Nutzung:
    s = WifiSampler("AA:BB:CC:DD:EE:FF", iface="wlan1mon", sweep=True)
    s.start()
    while True:
        for rssi in s.drain():   # Liste neuer Samples seit letztem drain
            ...
        s.stop()
"""
from __future__ import annotations

import os
import queue
import struct
import subprocess
import threading
import time

DEFAULT_IFACE  = "wlan1mon"
SWEEP_CHANNELS = (1, 6, 11)
SWEEP_DWELL_S  = 0.6


def _parse_radiotap_rssi(data: bytes) -> int | None:
    """Bit 5 = dBm Antenna Signal (1 Byte signed) im Radiotap-Header."""
    if len(data) < 8:
        return None
    try:
        present = struct.unpack('<I', data[4:8])[0]
        pos = 8
        cur = present
        while cur & (1 << 31):
            if pos + 4 > len(data):
                return None
            cur  = struct.unpack('<I', data[pos:pos+4])[0]
            pos += 4
        if present & (1 << 0):
            pos = (pos + 7) & ~7
            pos += 8
        if present & (1 << 1):
            pos += 1
        if present & (1 << 2):
            pos += 1
        if present & (1 << 3):
            pos = (pos + 1) & ~1
            pos += 4
        if present & (1 << 4):
            pos = (pos + 1) & ~1
            pos += 2
        if present & (1 << 5) and pos < len(data):
            return struct.unpack('b', data[pos:pos+1])[0]
    except Exception:
        pass
    return None


class WifiSampler:
    """Liefert RSSI-Samples fuer eine Ziel-MAC aus tcpdump-Live-Stream."""

    def __init__(self, target_mac: str, iface: str = DEFAULT_IFACE,
                 sweep: bool = True):
        self.target = target_mac.lower()
        self.iface  = iface
        self.sweep  = sweep
        self._q: "queue.Queue[int]" = queue.Queue(maxsize=512)
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._hopper: threading.Thread | None = None
        self._stop_evt = threading.Event()

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        if self._proc is not None:
            return
        self._stop_evt.clear()
        # tcpdump: -U = packet-buffered, -l = line-buffered isn't enough for
        # binary pcap, -U flushes per-packet. -w - = pcap to stdout.
        cmd = [
            "tcpdump", "-i", self.iface, "-y", "IEEE802_11_RADIO",
            "-s", "256", "-U", "-w", "-",
            f"wlan addr2 {self.target}",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except FileNotFoundError:
            self._proc = None
            return

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if self.sweep:
            self._hopper = threading.Thread(target=self._hop_loop, daemon=True)
            self._hopper.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            except Exception:
                pass
            self._proc = None
        # threads are daemon; let them exit on next iteration

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── data access ──────────────────────────────────────────────

    def drain(self, max_items: int = 256) -> list[int]:
        out: list[int] = []
        try:
            while len(out) < max_items:
                out.append(self._q.get_nowait())
        except queue.Empty:
            pass
        return out

    # ── internals ────────────────────────────────────────────────

    def _read_loop(self) -> None:
        """Liest pcap-stream von tcpdump, parst Radiotap-Header, queued RSSI."""
        if self._proc is None or self._proc.stdout is None:
            return
        f = self._proc.stdout
        # Global header (24 Bytes)
        magic = f.read(4)
        if magic == b'\xd4\xc3\xb2\xa1':
            endian = '<'
        elif magic == b'\xa1\xb2\xc3\xd4':
            endian = '>'
        else:
            return
        try:
            f.read(20)
        except Exception:
            return

        while not self._stop_evt.is_set():
            try:
                hdr = f.read(16)
            except Exception:
                break
            if len(hdr) < 16:
                break
            try:
                _, _, incl_len, _ = struct.unpack(endian + 'IIII', hdr)
            except struct.error:
                break
            if incl_len <= 0 or incl_len > 0x40000:
                break
            try:
                data = f.read(incl_len)
            except Exception:
                break
            if len(data) < incl_len or len(data) < 4:
                break
            try:
                rt_len = struct.unpack('<H', data[2:4])[0]
            except struct.error:
                continue
            if rt_len > len(data):
                continue
            rssi = _parse_radiotap_rssi(data[:rt_len])
            if rssi is not None:
                try:
                    self._q.put_nowait(rssi)
                except queue.Full:
                    # drop oldest
                    try:
                        self._q.get_nowait()
                        self._q.put_nowait(rssi)
                    except queue.Empty:
                        pass

    def _hop_loop(self) -> None:
        """Rotiert wlan1mon durch 2.4-GHz-Channels — fokus auf wo ESP32 probt."""
        i = 0
        while not self._stop_evt.is_set():
            ch = SWEEP_CHANNELS[i % len(SWEEP_CHANNELS)]
            try:
                subprocess.run(
                    ["iw", "dev", self.iface, "set", "channel", str(ch)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                )
            except Exception:
                pass
            i += 1
            self._stop_evt.wait(SWEEP_DWELL_S)


def health_check(iface: str = DEFAULT_IFACE) -> tuple[bool, str]:
    """True + leerstring wenn iface da; sonst False + Fehlertext."""
    if not os.path.exists(f"/sys/class/net/{iface}"):
        return False, f"{iface} nicht da. Erst Argus-Scan starten."
    return True, ""
