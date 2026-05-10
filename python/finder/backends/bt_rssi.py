"""BT RSSI Sampler — btmon live-stream mit Filter auf Target-MAC.

btmon -t gibt einen kontinuierlichen Stream aller HCI-Events. Wir filtern
auf 'Address: <target>' und nehmen die zugehoerige 'RSSI: -<n> dBm'-Zeile.

Nutzung:
    s = BtSampler("AA:BB:CC:DD:EE:FF")
    s.start()
    while True:
        for rssi in s.drain():
            ...
    s.stop()
"""
from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading

ADDR_RE = re.compile(r'\s+Address:\s+([0-9A-Fa-f:]{17})')
RSSI_RE = re.compile(r'\s+RSSI:\s+(-?\d+)\s+dBm')


class BtSampler:
    """Liefert RSSI-Samples aus btmon-Live-Stream.

    target_mac == None oder "" -> Sweep-Modus: alle BLE-Adverts; queued
    ``(mac_lower, rssi)``.
    target_mac gesetzt -> Target-Modus: nur diese MAC; queued ``int rssi``.
    """

    def __init__(self, target_mac: str | None):
        self.target = target_mac.lower() if target_mac else None
        # Target: int RSSI. Sweep: (mac_lower, int) tuples.
        self._q: "queue.Queue" = queue.Queue(maxsize=2048)
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._scanner: subprocess.Popen | None = None

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        if self._proc is not None:
            return
        self._stop_evt.clear()

        # bluetoothctl im Hintergrund triggern damit BLE-Scan dauerhaft laeuft
        # (sonst sieht btmon nur sporadisch was). Nicht-fatal wenn fehlend.
        try:
            self._scanner = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            if self._scanner.stdin:
                self._scanner.stdin.write("scan on\n")
                self._scanner.stdin.flush()
        except FileNotFoundError:
            self._scanner = None

        try:
            self._proc = subprocess.Popen(
                ["btmon", "-t"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            self._proc = None
            return

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def stop(self) -> None:
        self._stop_evt.set()
        for p in (self._proc, self._scanner):
            if p is None:
                continue
            try:
                p.terminate()
                try:
                    p.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    p.kill()
            except Exception:
                pass
        self._proc = None
        self._scanner = None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── data ─────────────────────────────────────────────────────

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
        if self._proc is None or self._proc.stdout is None:
            return
        current = None
        try:
            for line in self._proc.stdout:
                if self._stop_evt.is_set():
                    break
                line = line.rstrip()

                m = ADDR_RE.match(line)
                if m:
                    current = m.group(1).lower()
                    continue

                # Target-Mode: filtert auf einzelne MAC
                if self.target and current != self.target:
                    continue
                if current is None:
                    continue

                m = RSSI_RE.match(line)
                if not m:
                    continue
                try:
                    rssi = int(m.group(1))
                except ValueError:
                    continue

                item = rssi if self.target else (current, rssi)
                try:
                    self._q.put_nowait(item)
                except queue.Full:
                    try:
                        self._q.get_nowait()
                        self._q.put_nowait(item)
                    except queue.Empty:
                        pass
        except Exception:
            pass


def health_check() -> tuple[bool, str]:
    """True wenn btmon + bluetoothctl verfuegbar."""
    if shutil.which("btmon") is None:
        return False, "btmon nicht installiert"
    return True, ""
