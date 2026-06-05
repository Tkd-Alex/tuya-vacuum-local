#!/usr/bin/env python3
"""
vacuum_map_decode.py — Decode and render Tuya vacuum map binary files
Part of the tuya-vacuum-local project.

Format (reverse-engineered + confirmed via tuya-vacuum package):
  - Header: 24 bytes (12 × big-endian uint16)
  - Grid: LZ4-compressed, width×height bytes
    0xFF = background (outside apartment)
    0xF9 = wall / obstacle
    0xF4 = free explored space
    0x00,0x04,0x08,0x0C,0x10 = room IDs 0-4
  - Room section: room names + polygon vertices

Requirements:
  pip install lz4 pillow numpy

Usage:
  python vacuum_map_decode.py map_app_map_*.bin
  python vacuum_map_decode.py map_app_map_*.bin --output /config/www/vacuum_map.png
  python vacuum_map_decode.py map_app_map_*.bin --info
  python vacuum_map_decode.py map_app_map_*.bin --config
"""

import struct, sys, os, argparse
from pathlib import Path

try:
    import lz4.block as lz4b
except ImportError:
    print("ERROR: pip install lz4"); sys.exit(1)

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: pip install pillow numpy"); sys.exit(1)


# ── Colour palette (matches Tuya app) ────────────────────────────

BACKGROUND = (245, 245, 245)
WALL       = (80,  80,  80)
FREE       = (215, 222, 230)
UNKNOWN    = (200, 195, 190)

ROOM_CELLS  = [0x00, 0x04, 0x08, 0x0C, 0x10]
ROOM_COLORS = [
    (255, 210, 175),   # room 0 — peach     (Ingresso)
    (200, 185, 240),   # room 1 — lavender  (Stanzetta)
    (245, 185, 205),   # room 2 — pink      (Camera)
    (210, 185, 245),   # room 3 — violet    (Cucina)
    (170, 195, 240),   # room 4 — sky blue  (Bagno)
]
CELL_TO_ROOM = {v: i for i, v in enumerate(ROOM_CELLS)}

def cell_colour(v: int) -> tuple:
    if v == 0xFF: return BACKGROUND
    if v == 0xF9: return WALL
    if v == 0xF4: return FREE
    if v in CELL_TO_ROOM: return ROOM_COLORS[CELL_TO_ROOM[v]]
    return UNKNOWN


# ── Header parsing ────────────────────────────────────────────────

def shrink(v: int) -> int:
    """Convert unsigned to signed int16."""
    return v - 65536 if v > 32767 else v

def parse_header(raw: bytes) -> dict:
    """
    Header: 24 bytes = 12 × big-endian uint16
    Fields: _, _, width, height, origin_x, origin_y,
            resolution, pile_x, pile_y, _, total_count, length_compressed
    """
    fields = [struct.unpack(">H", raw[i:i+2])[0] for i in range(0, 24, 2)]
    return {
        "version":     raw[0],
        "width":       fields[2],
        "height":      fields[3],
        "origin_x":    shrink(fields[4]),
        "origin_y":    shrink(fields[5]),
        "resolution":  fields[6],   # cm per grid cell (= 5)
        "pile_x":      shrink(fields[7]),
        "pile_y":      shrink(fields[8]),
        "total_count": fields[10],
        "compressed_length": fields[11],
    }


# ── Decompression ─────────────────────────────────────────────────

def decompress_map(raw: bytes, header: dict) -> tuple[bytes, bytes]:
    """
    Returns (grid_bytes, room_section_bytes).
    Compressed data starts at byte 24 and has length = header.compressed_length.
    """
    area = header["width"] * header["height"]
    clen = header["compressed_length"]

    # total_count is the decompressed size
    total = header["total_count"]

    decoded = lz4b.decompress(raw[24:24 + clen], uncompressed_size=total)
    return decoded[:area], decoded[area:]


# ── Room name extraction ──────────────────────────────────────────

def parse_room_names(data: bytes) -> dict:
    """
    Scans for length-prefixed ASCII strings in the room section.
    Returns {room_index: name}.
    """
    rooms = {}
    i = 0
    while i < len(data):
        if 4 <= data[i] <= 30 and i + data[i] < len(data):
            n = data[i]
            nb = data[i+1:i+1+n]
            if all(32 <= b < 127 for b in nb):
                rooms[len(rooms)] = nb.decode("ascii")
                i += 1 + n
                continue
        i += 1
    return rooms


# ── Rendering ─────────────────────────────────────────────────────

def _find_font(size: int):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_map(
    grid: bytes,
    room_section: bytes,
    header: dict,
    scale: int = 5,
    output_path: str = "map.png",
):
    W = header["width"]
    H = header["height"]
    room_names = parse_room_names(room_section)

    # Build pixel array
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for r in range(H):
        for c in range(W):
            arr[r, c] = cell_colour(grid[r * W + c])

    img  = Image.fromarray(arr).resize((W * scale, H * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)

    font_label = _find_font(18)
    font_small = _find_font(13)

    # Room labels — white badge, dark text
    for room_idx, name in room_names.items():
        cv  = ROOM_CELLS[room_idx]
        pos = [(r, c) for r in range(H) for c in range(W)
               if grid[r * W + c] == cv]
        if not pos:
            continue
        rows = [r for r, c in pos]
        cols = [c for r, c in pos]
        cr   = sum(rows) // len(rows)
        cc   = sum(cols) // len(cols)
        px   = cc * scale + scale // 2
        py   = cr * scale + scale // 2

        bb  = font_label.getbbox(name)
        tw  = bb[2] - bb[0]
        th  = bb[3] - bb[1]
        pad = 8
        draw.rounded_rectangle(
            [px - tw//2 - pad, py - th//2 - pad,
             px + tw//2 + pad, py + th//2 + pad],
            radius=8, fill=(255, 255, 255), outline=(100, 100, 100), width=1
        )
        draw.text((px, py), name, fill=(40, 40, 40),
                  font=font_label, anchor="mm")

    # Dock marker — robot starts at coordinate (0,0) → grid origin
    # origin_x / resolution gives the grid column of coordinate x=0
    res = header["resolution"]   # = 5 cm per cell
    # In robot units: 200 units = 1 m → resolution cells/m = 100/res
    units_per_cell = res * 2     # cm/cell × 2 units/cm = 10 units/cell
    ox  = header["origin_x"]
    oy  = header["origin_y"]

    # Dock is at robot coord (0,0); convert to grid
    dock_c = int(ox / units_per_cell)
    dock_r = int(oy / units_per_cell)

    if 0 <= dock_c < W and 0 <= dock_r < H:
        dx = dock_c * scale + scale // 2
        dy = dock_r * scale + scale // 2
        r  = 12
        draw.ellipse([dx-r, dy-r, dx+r, dy+r],
                     fill=(50, 200, 80), outline=(20, 140, 40), width=2)
        draw.text((dx, dy), "⚡", fill=(255, 255, 255),
                  font=font_small, anchor="mm")

    # Scale bar: 1 m = (100/res) cells × scale px
    cells_per_m = 100 // res
    bar_len = cells_per_m * scale
    bx, by = 20, H * scale - 35
    draw.rectangle([bx, by, bx + bar_len, by + 5], fill=(80, 80, 80))
    draw.text((bx + bar_len // 2, by + 14), "1 m",
              fill=(80, 80, 80), font=font_small, anchor="mm")

    img.save(output_path, optimize=True)
    return img


# ── Info / config output ──────────────────────────────────────────

def print_info(header: dict, grid: bytes, room_section: bytes):
    W, H = header["width"], header["height"]
    res  = header["resolution"]
    from collections import Counter
    cnt = Counter(grid)

    print(f"Map dimensions : {W} × {H} cells  ({W*res/100:.1f} m × {H*res/100:.1f} m)")
    print(f"Cell size      : {res} cm")
    print(f"Origin         : ({header['origin_x']}, {header['origin_y']}) robot units")
    print(f"Dock (approx)  : grid col {header['origin_x']//10}, row {header['origin_y']//10}")

    rooms = parse_room_names(room_section)
    if rooms:
        print(f"\nRooms ({len(rooms)}):")
        for idx, name in rooms.items():
            cv = ROOM_CELLS[idx]
            n  = cnt.get(cv, 0)
            print(f"  [{idx}] 0x{cv:02X}  {name:<22}  {n} cells = {n*res*res/10000:.1f} m²")


def print_config(room_section: bytes):
    rooms = parse_room_names(room_section)
    if not rooms:
        print("No rooms found."); return
    print('  "rooms": {')
    for i, (idx, name) in enumerate(rooms.items()):
        comma = "," if i < len(rooms) - 1 else ""
        print(f'    "{idx}": "{name}"{comma}')
    print("  },")


# ── CLI ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Decode and render Tuya vacuum map binary files"
    )
    p.add_argument("file",   help=".bin map file from vacuum_map.py --download")
    p.add_argument("--output", "-o", default=None,
                   help="Output PNG path (default: <file>.png)")
    p.add_argument("--scale",  type=int, default=5,
                   help="Pixels per grid cell (default: 5)")
    p.add_argument("--info",   action="store_true",
                   help="Print map info and exit (no image)")
    p.add_argument("--config", action="store_true",
                   help="Print rooms snippet for config.json")
    args = p.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}"); sys.exit(1)

    with open(args.file, "rb") as f:
        raw = f.read()

    header = parse_header(raw)
    grid, room_section = decompress_map(raw, header)

    print_info(header, grid, room_section)

    if args.config:
        print()
        print_config(room_section)

    if args.info:
        return

    out = args.output or str(Path(args.file).with_suffix(".png"))
    render_map(grid, room_section, header, scale=args.scale, output_path=out)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
