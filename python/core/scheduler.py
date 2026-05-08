"""Scan scheduler — round counter + pause/resume bookkeeping.

The scheduler does NOT perform any I/O; it just exposes monotonic timestamps
the scan_engine and scan_live screen consume. ``ScanEngine.tick(scheduler)``
is what actually advances rounds.
"""
from __future__ import annotations

import time
from enum import Enum


class State(Enum):
    IDLE    = "idle"
    RUNNING = "running"
    PAUSED  = "paused"
    DONE    = "done"
    STOPPED = "stopped"


class Scheduler:
    def __init__(self, *, rounds: int, duration_s: int):
        self.rounds = int(rounds)         # 0 = unbounded (run until stop())
        self.duration_s = int(duration_s)
        self.state = State.IDLE
        self.current_round = 0          # 0 before start, then 1..rounds
        self._round_started: float = 0.0
        self._round_elapsed_at_pause: float = 0.0
        self._total_started: float = 0.0
        self._total_paused_offset: float = 0.0  # accumulated pause time
        self._pause_started: float = 0.0

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        if self.state != State.IDLE:
            return
        self.state = State.RUNNING
        self.current_round = 1
        now = time.monotonic()
        self._total_started = now
        self._round_started = now
        self._round_elapsed_at_pause = 0.0

    def pause(self) -> None:
        if self.state != State.RUNNING:
            return
        self.state = State.PAUSED
        now = time.monotonic()
        self._round_elapsed_at_pause = now - self._round_started
        self._pause_started = now

    def resume(self) -> None:
        if self.state != State.PAUSED:
            return
        now = time.monotonic()
        paused_for = now - self._pause_started
        self._total_paused_offset += paused_for
        # restart the current round so scan_engine doesn't lose accumulated time
        self._round_started = now - self._round_elapsed_at_pause
        self.state = State.RUNNING

    def stop(self) -> None:
        self.state = State.STOPPED

    def advance_round(self) -> bool:
        """Move to next round if the current one is complete. Returns True if advanced."""
        if self.state != State.RUNNING:
            return False
        if self.round_elapsed() < self.duration_s:
            return False
        if self.rounds > 0 and self.current_round >= self.rounds:
            self.state = State.DONE
            return False
        self.current_round += 1
        self._round_started = time.monotonic()
        return True

    def is_unbounded(self) -> bool:
        return self.rounds == 0

    # ── queries ──────────────────────────────────────────────────────

    def is_paused(self) -> bool:
        return self.state == State.PAUSED

    def is_running(self) -> bool:
        return self.state == State.RUNNING

    def is_done(self) -> bool:
        return self.state in (State.DONE, State.STOPPED)

    def round_elapsed(self) -> float:
        if self.state == State.PAUSED:
            return self._round_elapsed_at_pause
        if self.state in (State.DONE, State.STOPPED):
            return float(self.duration_s)
        if self.state == State.IDLE:
            return 0.0
        return time.monotonic() - self._round_started

    def elapsed_total(self) -> float:
        if self.state == State.IDLE:
            return 0.0
        if self.state == State.PAUSED:
            now = self._pause_started
        else:
            now = time.monotonic()
        return max(0.0, now - self._total_started - self._total_paused_offset)

    def total_seconds(self) -> int:
        """Bounded total. Returns 0 when unbounded (caller should not show ETA)."""
        return self.rounds * self.duration_s
