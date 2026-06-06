"""Pure-python LZ4 block decompressor and map renderer for Tuya Vacuum Local."""
from __future__ import annotations
import io, os, struct
from PIL import Image, ImageDraw, ImageFont

# ── Pure Python LZ4 Decompressor ──────────────────────────────────

def lz4_decompress(source: bytes, uncompressed_size: int) -> bytes:
    """
    Decompress LZ4 block data. 
    Simplified version for Tuya vacuum maps.
    """
    src = io.BytesIO(source)
    dst = bytearray()
    
    while True:
        token_byte = src.read(1)
        if not token_byte: break
        token = token_byte[0]
        
        # Literal length
        lit_len = token >> 4
        if lit_len == 0xF:
            while True:
                b = src.read(1)[0]
                lit_len += b
                if b != 0xFF: break
        
        # Copy literals
        dst.extend(src.read(lit_len))
        
        if len(dst) >= uncompressed_size: break
        
        # Match offset
        offset_bytes = src.read(2)
        if not offset_bytes: break
        offset = struct.unpack("<H", offset_bytes)[0]
        if offset == 0: break
        
        # Match length
        match_len = (token & 0xF) + 4
        if match_len == 0xF + 4:
            while True:
                b = src.read(1)[0]
                match_len += b
                if b != 0xFF: break
        
        # Copy match
        pos = len(dst) - offset
        for _ in range(match_len):
            dst.append(dst[pos])
            pos += 1
            
    return bytes(dst[:uncompressed_size])

# ── Renderer ──────────────────────────────────────────────────────

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

def _error_img(msg: str, W: int = 512, H: int = 512) -> bytes:
    """Return a PNG with error message."""
    img = Image.new("RGB", (W, H), (240, 200, 200))
    draw = ImageDraw.Draw(img)
    draw.text((W//2, H//2), f"Map Error:\n{msg}", fill=(150, 0, 0), anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def decode_and_render(layout_raw: bytes, path_raw: bytes | None = None,
                      scale: int = 4) -> bytes:
    """Decode LZ4 map binary and return PNG as bytes."""
    try:
        if not layout_raw or len(layout_raw) < 24:
            return _error_img("Invalid map data (too short)")

        flds = [struct.unpack(">H", layout_raw[i:i+2])[0] for i in range(0, 24, 2)]
        W, H   = flds[2], flds[3]
        ox, oy = _shrink(flds[4]), _shrink(flds[5])
        res    = flds[6]
        total  = flds[10]
        clen   = flds[11]

        if W == 0 or H == 0 or clen == 0:
            return _error_img(f"Invalid dimensions: {W}x{H}")

        # Decompress
        try:
            dec = lz4_decompress(layout_raw[24:24+clen], uncompressed_size=total)
        except Exception as e:
            return _error_img(f"Decompression failed: {e}")

        grid         = dec[:W*H]
        room_section = dec[W*H:]
        room_names   = _room_names(room_section)

        # Create image
        img = Image.new("RGB", (W, H))
        pixels = [_colour(v) for v in grid]
        img.putdata(pixels)
        
        # Resize and draw
        img  = img.resize((W*scale, H*scale), Image.NEAREST)
        draw = ImageDraw.Draw(img)
        font = _font(18)
        fsm  = _font(13)

        # Room labels
        for idx, name in room_names.items():
            try:
                cv  = ROOM_CELLS[idx] if idx < len(ROOM_CELLS) else None
                if cv is None: continue
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
            except Exception: continue

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

    except Exception as e:
        import traceback
        return _error_img(f"Render error: {e}\n{traceback.format_exc()[:100]}")
