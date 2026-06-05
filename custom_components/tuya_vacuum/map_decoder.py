"""LZ4 map decoder for Tuya Vacuum Local."""
from __future__ import annotations
import io, os, struct
import lz4.block as lz4b
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOM_CELLS  = [0x00, 0x04, 0x08, 0x0C, 0x10]
ROOM_COLORS = [
    (255, 210, 175), (200, 185, 240), (245, 185, 205),
    (210, 185, 245), (170, 195, 240),
]
CELL_TO_ROOM = {v: i for i, v in enumerate(ROOM_CELLS)}

def _colour(v):
    if v == 0xFF: return (245, 245, 245)
    if v == 0xF9: return (80,  80,  80)
    if v == 0xF4: return (215, 222, 230)
    if v in CELL_TO_ROOM: return ROOM_COLORS[CELL_TO_ROOM[v]]
    return (205, 200, 195)

def _shrink(v): return v - 65536 if v > 32767 else v

def _font(size):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def _room_names(data: bytes) -> dict:
    rooms, i = {}, 0
    while i < len(data):
        if 4 <= data[i] <= 30 and i + data[i] < len(data):
            n, nb = data[i], data[i+1:i+data[i]+1]
            if all(32 <= b < 127 for b in nb):
                rooms[len(rooms)] = nb.decode("ascii"); i += 1 + n; continue
        i += 1
    return rooms

def decode_and_render(layout_raw: bytes, path_raw: bytes | None = None,
                      scale: int = 4) -> bytes:
    """Decode LZ4 map binary and return PNG as bytes."""
    flds = [struct.unpack(">H", layout_raw[i:i+2])[0] for i in range(0, 24, 2)]
    W, H   = flds[2], flds[3]
    ox, oy = _shrink(flds[4]), _shrink(flds[5])
    res    = flds[6]
    total  = flds[10]
    clen   = flds[11]

    dec          = lz4b.decompress(layout_raw[24:24+clen], uncompressed_size=total)
    grid         = dec[:W*H]
    room_section = dec[W*H:]
    room_names   = _room_names(room_section)

    arr = np.zeros((H, W, 3), np.uint8)
    for r in range(H):
        for c in range(W):
            arr[r, c] = _colour(grid[r*W+c])

    img  = Image.fromarray(arr).resize((W*scale, H*scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    font = _font(18)
    fsm  = _font(13)

    # Room labels
    for idx, name in room_names.items():
        cv  = ROOM_CELLS[idx]
        pos = [(r,c) for r in range(H) for c in range(W) if grid[r*W+c]==cv]
        if not pos: continue
        rows=[p[0] for p in pos]; cols=[p[1] for p in pos]
        cr,cc = sum(rows)//len(rows), sum(cols)//len(cols)
        px,py = cc*scale+scale//2, cr*scale+scale//2
        bb = font.getbbox(name); tw,th,pad = bb[2]-bb[0],bb[3]-bb[1],8
        draw.rounded_rectangle(
            [px-tw//2-pad,py-th//2-pad,px+tw//2+pad,py+th//2+pad],
            radius=8, fill=(255,255,255), outline=(100,100,100), width=1)
        draw.text((px,py), name, fill=(40,40,40), font=font, anchor="mm")

    # Dock
    upc = res*2
    dc,dr = int(ox/upc), int(oy/upc)
    if 0<=dc<W and 0<=dr<H:
        dx,dy,R = dc*scale+scale//2, dr*scale+scale//2, 12
        draw.ellipse([dx-R,dy-R,dx+R,dy+R], fill=(50,200,80), outline=(20,140,40), width=2)
        draw.text((dx,dy), "⚡", fill=(255,255,255), font=fsm, anchor="mm")

    # Scale bar
    bar = (100//res)*scale
    bx,by = 20, H*scale-35
    draw.rectangle([bx,by,bx+bar,by+5], fill=(80,80,80))
    draw.text((bx+bar//2,by+14), "1 m", fill=(80,80,80), font=fsm, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
