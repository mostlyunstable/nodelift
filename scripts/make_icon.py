#!/usr/bin/env python3
"""Draw the Nodecraft app icon (three connected nodes) as a 1024px PNG using only the standard library.

    python3 scripts/make_icon.py OUT.png
Then:  cd apps/web && pnpm tauri icon OUT.png
"""

from __future__ import annotations

import math
import struct
import sys
import zlib

SIZE = 1024


def smooth(edge0: float, edge1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def sd_round_rect(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    qx, qy = abs(px - cx) - (hw - r), abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def sd_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    pax, pay, bax, bay = px - ax, py - ay, bx - ax, by - ay
    h = min(1.0, max(0.0, (pax * bax + pay * bay) / (bax * bax + bay * bay)))
    return math.hypot(pax - bax * h, pay - bay * h)


def mix(a: tuple[float, ...], b: tuple[float, ...], t: float) -> tuple[float, ...]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def hexcolor(h: str) -> tuple[float, float, float]:
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


NODES = [((270, 330), hexcolor("#58a6ff")), ((512, 700), hexcolor("#3fb950")), ((754, 330), hexcolor("#d29922"))]
EDGES = [(0, 1), (1, 2), (0, 2)]


def pixel(x: int, y: int) -> tuple[int, int, int, int]:
    px, py = x + 0.5, y + 0.5
    # tile: rounded square with a vertical gradient
    d = sd_round_rect(px, py, 512, 512, 480, 480, 215)
    alpha = 1 - smooth(-1.5, 1.5, d)
    if alpha <= 0:
        return (0, 0, 0, 0)
    base = mix(hexcolor("#1c2535"), hexcolor("#0b0f14"), py / SIZE)
    # soft inner border
    base = mix(base, hexcolor("#2d3a4f"), smooth(-10, -2, d) * 0.9)
    color = base
    # edges
    for a, b in EDGES:
        (ax, ay), (bx, by) = NODES[a][0], NODES[b][0]
        e = sd_segment(px, py, ax, ay, bx, by)
        color = mix(color, hexcolor("#7d8590"), 1 - smooth(14, 17, e))
    # nodes: coloured ring around a dark core
    for (cx, cy), col in NODES:
        r = math.hypot(px - cx, py - cy)
        color = mix(color, col, 1 - smooth(98, 101, r))
        color = mix(color, hexcolor("#0d1117"), 1 - smooth(60, 63, r))
        color = mix(color, col, 1 - smooth(26, 29, r))
    return (int(color[0]), int(color[1]), int(color[2]), int(alpha * 255))


def main(out: str) -> None:
    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        for x in range(SIZE):
            raw.extend(pixel(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(out, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
