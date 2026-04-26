"""Runtime screenshot instrumentation.

Activated by setting the env var ``ARGUS_SCREENSHOTS=1`` (and optionally
``ARGUS_SCREENSHOT_DIR=/path/to/dir``).

How it works:
- ``install(pager)`` monkey-patches ``pager.flip()`` so every frame the
  framebuffer is sampled. Reads ``/dev/fb0`` (RGB565), rotates back to
  landscape, writes a PNG with stdlib only.
- Rate-limit: at most one PNG per second within the same screen.
- ``mark_screen(name)`` sets a force-flag plus the screen name; the
  next ``flip`` after that always shoots regardless of rate-limit.
  ``main.py`` calls this before invoking each screen handler.

The result is a numbered PNG sequence under
``/root/loot/argus/screenshots/<sessionid>/`` showing every distinct
state the user sees. Pull them off with::

    tools/pull_screenshots.sh
"""
from __future__ import annotations

import os
import struct
import sys
import time
import zlib
from pathlib import Path

_FB = "/dev/fb0"
_DEFAULT_W = 222          # native portrait
_DEFAULT_H = 480
_ROTATE_DEG = 270         # back to landscape (matches set_rotation(270))

_state = {
    "enabled":     False,
    "dir":         None,
    "seq":         0,
    "last_ts":     0.0,
    "min_period":  1.0,    # seconds between auto-shots within a screen
    "force_next":  False,
    "screen":      "init",
    "fb_w":        _DEFAULT_W,
    "fb_h":        _DEFAULT_H,
}


def _log(msg: str) -> None:
    print(f"[screenshot] {msg}", file=sys.stderr, flush=True)


def is_enabled() -> bool:
    return bool(_state["enabled"])


def install(pager, *, base_dir: str | None = None) -> None:
    """Wire up screenshot capture if ARGUS_SCREENSHOTS is truthy."""
    if not os.environ.get("ARGUS_SCREENSHOTS"):
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

    _log(f"enabled, writing to {out} (fb {_state['fb_w']}x{_state['fb_h']})")

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
    _dump_fb(out)


def _dump_fb(path: Path) -> None:
    w = _state["fb_w"]
    h = _state["fb_h"]
    expected = w * h * 2
    with open(_FB, "rb") as f:
        raw = f.read(expected)
    rgb = _rgb565_to_rgb888(raw)
    rgb, w2, h2 = _rotate(rgb, w, h, _ROTATE_DEG)
    _write_png(str(path), w2, h2, rgb)


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
    idat = zlib.compress(bytes(raw), level=6)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))
