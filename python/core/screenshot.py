"""Runtime screenshot instrumentation.

Activated by setting the env var ``ARGUS_SCREENSHOTS=1`` (and optionally
``ARGUS_SCREENSHOT_DIR=/path/to/dir``).

How it works:
- ``install(pager)`` monkey-patches ``pager.flip()`` so every frame the
  framebuffer can be sampled. The foreground call only reads
  ``/dev/fb0`` (~213 KB - fast) and hands the raw bytes to a daemon
  worker thread for RGB565->RGB888 conversion + rotate + PNG encode.
  This keeps the UI responsive on mipsel - the heavy work is offloaded
  and rate-limited; if the queue is full the new shot is just dropped.
- Rate-limit: at most one PNG per ``min_period`` seconds within the
  same screen (default 2s). Forced shots at screen boundaries bypass
  the rate-limit but still go through the queue (and may be dropped
  if the worker is backed up).
- ``mark_screen(name)`` sets a force-flag plus the screen name; the
  next ``flip`` after that always tries to shoot regardless of
  rate-limit. ``main.py`` calls this before invoking each handler.

The result is a numbered PNG sequence under
``/root/loot/argus/screenshots/<sessionid>/`` showing every distinct
state the user sees. Pull them off with::

    tools/pull_screenshots.sh
"""
from __future__ import annotations

import os
import queue
import struct
import sys
import threading
import time
import zlib
from pathlib import Path

_FB = "/dev/fb0"
_DEFAULT_W = 222          # native portrait
_DEFAULT_H = 480
_ROTATE_DEG = 270         # back to landscape (matches set_rotation(270))
_QUEUE_DEPTH = 3          # max pending PNGs - extra shots are dropped

_state = {
    "enabled":     False,
    "dir":         None,
    "seq":         0,
    "last_ts":     0.0,
    "min_period":  2.0,    # seconds between auto-shots within a screen
    "force_next":  False,
    "screen":      "init",
    "fb_w":        _DEFAULT_W,
    "fb_h":        _DEFAULT_H,
    "dropped":     0,
}

_jobs: "queue.Queue | None" = None
_worker: threading.Thread | None = None


def _log(msg: str) -> None:
    print(f"[screenshot] {msg}", file=sys.stderr, flush=True)


def is_enabled() -> bool:
    return bool(_state["enabled"])


def install(pager, *, base_dir: str | None = None) -> None:
    """Wire up screenshot capture if ARGUS_SCREENSHOTS is truthy.

    Note: a Python ``str`` is truthy unless empty, so ``"0"`` would
    enable screenshots if we used a plain bool check. Treat any of
    ``0``, empty, ``no``, ``off``, ``false`` (case-insensitive) as
    disabled.
    """
    global _jobs, _worker
    val = (os.environ.get("ARGUS_SCREENSHOTS") or "").strip().lower()
    if val in ("", "0", "no", "off", "false"):
        return
    out = Path(
        os.environ.get("ARGUS_SCREENSHOT_DIR")
        or base_dir
        or f"/root/loot/argus/screenshots/{time.strftime('%Y%m%d_%H%M%S')}"
    )
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _log(f"cannot create {out}: {exc}")
        return
    _state["enabled"] = True
    _state["dir"]     = out
    _state["seq"]     = 0
    _state["last_ts"] = 0.0

    # detect framebuffer geometry
    try:
        text = Path("/sys/class/graphics/fb0/virtual_size").read_text().strip()
        w, h = (int(x) for x in text.split(","))
        _state["fb_w"], _state["fb_h"] = w, h
    except Exception:
        pass

    # Background worker - flip() must return fast on mipsel, so encode happens here.
    _jobs = queue.Queue(maxsize=_QUEUE_DEPTH)
    _worker = threading.Thread(target=_worker_loop, daemon=True, name="argus-shot")
    _worker.start()

    _log(f"enabled, writing to {out} (fb {_state['fb_w']}x{_state['fb_h']}), "
         f"period={_state['min_period']}s, queue={_QUEUE_DEPTH}")

    # monkey-patch flip
    original_flip = pager.flip

    def flip_with_shot(*args, **kwargs):
        result = original_flip(*args, **kwargs)
        try:
            _maybe_shot()
        except Exception as exc:
            _log(f"shot failed: {exc}")
        return result

    pager.flip = flip_with_shot


def mark_screen(name: str) -> None:
    """Tell the instrumentation which screen we're entering. The next
    ``flip()`` will produce a forced screenshot regardless of rate-limit."""
    if not _state["enabled"]:
        return
    _state["screen"]     = name
    _state["force_next"] = True


def _maybe_shot() -> None:
    now = time.monotonic()
    if not _state["force_next"]:
        if now - _state["last_ts"] < _state["min_period"]:
            return
    _state["force_next"] = False
    _state["last_ts"]    = now
    _state["seq"]       += 1

    seq    = _state["seq"]
    screen = _state["screen"]
    out    = _state["dir"] / f"{seq:03d}_{screen}.png"

    # Foreground: just snapshot the framebuffer bytes. Cheap.
    w = _state["fb_w"]
    h = _state["fb_h"]
    try:
        with open(_FB, "rb") as f:
            raw = f.read(w * h * 2)
    except Exception as exc:
        _log(f"fb read failed: {exc}")
        return

    # Hand off to the writer thread. If the queue is full, drop this shot
    # so flip() never blocks.
    try:
        _jobs.put_nowait((str(out), raw, w, h))
    except queue.Full:
        _state["dropped"] += 1
        if _state["dropped"] % 10 == 1:
            _log(f"queue full - dropped {_state['dropped']} shot(s) so far")


def _worker_loop() -> None:
    """Encode PNGs off the UI thread."""
    while True:
        item = _jobs.get()
        if item is None:
            return
        path, raw, w, h = item
        try:
            rgb = _rgb565_to_rgb888(raw)
            rgb, w2, h2 = _rotate(rgb, w, h, _ROTATE_DEG)
            _write_png(path, w2, h2, rgb)
        except Exception as exc:
            _log(f"encode failed for {path}: {exc}")


# encoding helpers (kept inline so this module has zero deps beyond stdlib)

def _rgb565_to_rgb888(buf: bytes) -> bytes:
    out = bytearray(len(buf) // 2 * 3)
    o = 0
    for i in range(0, len(buf) - 1, 2):
        v = buf[i] | (buf[i + 1] << 8)
        r = ((v >> 11) & 0x1F) << 3
        g = ((v >> 5)  & 0x3F) << 2
        b = ( v        & 0x1F) << 3
        r |= r >> 5
        g |= g >> 6
        b |= b >> 5
        out[o]     = r
        out[o + 1] = g
        out[o + 2] = b
        o += 3
    return bytes(out)


def _rotate(rgb: bytes, w: int, h: int, deg: int) -> tuple[bytes, int, int]:
    deg = deg % 360
    if deg == 0:
        return rgb, w, h
    out = bytearray(len(rgb))
    if deg == 270:
        nw, nh = h, w
        for y in range(h):
            for x in range(w):
                src = (y * w + x) * 3
                dx, dy = y, w - 1 - x
                dst = (dy * nw + dx) * 3
                out[dst:dst + 3] = rgb[src:src + 3]
        return bytes(out), nw, nh
    # 90 / 180 not used here but easy to add
    return rgb, w, h


def _write_png(path: str, w: int, h: int, rgb888: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)
    sig  = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw  = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb888[y * stride:(y + 1) * stride]
    # zlib level 1 - we want speed, not minimal file size
    idat = zlib.compress(bytes(raw), level=1)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))
