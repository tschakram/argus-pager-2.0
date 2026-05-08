#!/usr/bin/env python3
"""Take a PNG screenshot of the Pager LCD by reading /dev/fb0.

Useful for the README / docs because the Pineapple "Virtual Pager"
web preview goes blank as soon as we SIGSTOP the framework UI -
``pagerctl`` then owns the framebuffer exclusively. This tool reads
the same framebuffer the LCD is showing, decodes the RGB565 layout,
optionally rotates 270deg back to landscape, and writes a PNG with
no Python dependencies (stdlib zlib + struct only).

Usage on the pager:
    python3 tools/screenshot.py /tmp/shot.png
    # or with explicit geometry:
    python3 tools/screenshot.py /tmp/shot.png --w 480 --h 222 --rotate 0

Defaults assume the framebuffer device is 222x480 portrait (the
Pineapple Pager's native orientation) and rotates back 270deg so
the image matches what the user sees on the LCD in landscape.

Pull the file off the pager:
    scp pager:/tmp/shot.png ./
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib
from pathlib import Path


def rgb565_to_rgb888(buf: bytes) -> bytes:
    """Convert a little-endian RGB565 buffer to packed RGB888."""
    out = bytearray(len(buf) // 2 * 3)
    o = 0
    for i in range(0, len(buf) - 1, 2):
        v = buf[i] | (buf[i + 1] << 8)
        r = ((v >> 11) & 0x1F) << 3
        g = ((v >> 5)  & 0x3F) << 2
        b = ( v        & 0x1F) << 3
        # replicate the top bits into the low ones so 0xFF stays 0xFF
        r |= r >> 5
        g |= g >> 6
        b |= b >> 5
        out[o]     = r
        out[o + 1] = g
        out[o + 2] = b
        o += 3
    return bytes(out)


def rotate(rgb: bytes, w: int, h: int, deg: int) -> tuple[bytes, int, int]:
    """Rotate an RGB888 image by 0/90/180/270 degrees clockwise."""
    deg = deg % 360
    if deg == 0:
        return rgb, w, h
    out = bytearray(len(rgb))
    if deg == 90:
        nw, nh = h, w
        for y in range(h):
            for x in range(w):
                src = (y * w + x) * 3
                dx, dy = h - 1 - y, x
                dst = (dy * nw + dx) * 3
                out[dst:dst + 3] = rgb[src:src + 3]
        return bytes(out), nw, nh
    if deg == 180:
        for y in range(h):
            for x in range(w):
                src = (y * w + x) * 3
                dy, dx = h - 1 - y, w - 1 - x
                dst = (dy * w + dx) * 3
                out[dst:dst + 3] = rgb[src:src + 3]
        return bytes(out), w, h
    if deg == 270:
        nw, nh = h, w
        for y in range(h):
            for x in range(w):
                src = (y * w + x) * 3
                dx, dy = y, w - 1 - x
                dst = (dy * nw + dx) * 3
                out[dst:dst + 3] = rgb[src:src + 3]
        return bytes(out), nw, nh
    raise ValueError(f"rotation must be 0/90/180/270, got {deg}")


def write_png(path: str, w: int, h: int, rgb888: bytes) -> None:
    """Write a minimal truecolor PNG (no alpha, no interlace)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig  = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit truecolor
    # filter byte 0 (None) per scanline
    raw = bytearray()
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


def autodetect_geometry(fb: str) -> tuple[int, int]:
    """Try /sys/class/graphics/.../virtual_size; fall back to 222x480."""
    name = Path(fb).name  # "fb0"
    sysfs = Path("/sys/class/graphics") / name / "virtual_size"
    try:
        text = sysfs.read_text().strip()
        w, h = (int(x) for x in text.split(","))
        return w, h
    except Exception:
        return 222, 480  # Pineapple Pager native portrait


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("output", nargs="?", default="/tmp/argus-shot.png",
                   help="output PNG path (default: /tmp/argus-shot.png)")
    p.add_argument("--fb", default="/dev/fb0", help="framebuffer device")
    p.add_argument("--w", type=int, default=None, help="framebuffer width")
    p.add_argument("--h", type=int, default=None, help="framebuffer height")
    p.add_argument("--rotate", type=int, default=270,
                   help="rotate the captured image (0/90/180/270, default 270)")
    p.add_argument("--quiet", action="store_true", help="no stdout on success")
    args = p.parse_args()

    if args.w is None or args.h is None:
        det_w, det_h = autodetect_geometry(args.fb)
        if args.w is None:
            args.w = det_w
        if args.h is None:
            args.h = det_h

    expected = args.w * args.h * 2
    try:
        with open(args.fb, "rb") as f:
            raw = f.read(expected)
    except FileNotFoundError:
        print(f"error: framebuffer {args.fb} not found", file=sys.stderr)
        return 2
    except PermissionError:
        print(f"error: cannot read {args.fb} (need root)", file=sys.stderr)
        return 3
    if len(raw) < expected:
        print(f"warn: short read {len(raw)}/{expected} bytes", file=sys.stderr)

    rgb888 = rgb565_to_rgb888(raw)
    rgb888, w, h = rotate(rgb888, args.w, args.h, args.rotate)
    write_png(args.output, w, h, rgb888)

    if not args.quiet:
        print(f"saved {args.output}: {w}x{h}, {os.path.getsize(args.output)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
