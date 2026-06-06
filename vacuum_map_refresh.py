#!/usr/bin/env python3
"""
vacuum_map_refresh.py — Fetch latest map from Tuya Cloud + render PNG for Home Assistant
Part of the tuya-vacuum-local project.

Downloads both app_map (room layout) and robot_map (cleaning path),
renders them overlaid as a single PNG saved to /config/www/vacuum_map.png.

Usage:
  python vacuum_map_refresh.py
  python vacuum_map_refresh.py --output /config/www/vacuum_map.png --scale 4

Requirements:
  pip install lz4 pillow numpy requests
"""

import os, sys, json, time, hashlib, hmac, argparse, struct
import requests, lz4.block as lz4b
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
REGIONS     = {
    "eu": "https://openapi.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}

# ── Config & Auth ─────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: config.json not found at {CONFIG_PATH}")
        print("Copy config.example.json → config.json and fill in tuya_client_id/secret")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    for key in ("device_id", "tuya_client_id", "tuya_client_secret"):
        if not cfg.get(key) or "YOUR_" in str(cfg.get(key, "")):
            print(f"ERROR: '{key}' missing or placeholder in config.json")
            sys.exit(1)
    return cfg

_token_cache = {"token": None, "expiry": 0.0}

def get_token(cfg, base_url):
    if time.time() < _token_cache["expiry"] - 60 and _token_cache["token"]:
        return _token_cache["token"]
    path = "/v1.0/token?grant_type=1"
    r = requests.get(base_url + path, headers=_sign(cfg, "GET", path), timeout=10)
    if r.status_code != 200:
        print(f"ERROR: Token request failed: HTTP {r.status_code}")
        sys.exit(1)
    data = r.json()
    if not data.get("success"):
        print(f"ERROR: {data.get('msg', data)}")
        sys.exit(1)
    _token_cache["token"]  = data["result"]["access_token"]
    _token_cache["expiry"] = time.time() + data["result"]["expire_time"]
    return _token_cache["token"]

def _sign(cfg, method, path, token=""):
    ts  = str(int(time.time() * 1000))
    bh  = hashlib.sha256(b"").hexdigest()
    s2s = "\n".join([method, bh, "", path])
    msg = cfg["tuya_client_id"] + (token or "") + ts + s2s
    sg  = hmac.new(
        key=cfg["tuya_client_secret"].encode(),
        msg=msg.encode(), digestmod=hashlib.sha256
    ).hexdigest().upper()
    return {
        "client_id": cfg["tuya_client_id"], "sign": sg,
        "t": ts, "sign_method": "HMAC-SHA256", "access_token": token or "",
    }

def api_get(cfg, path):
    region = cfg.get("tuya_region", "eu")
    base   = REGIONS.get(region, REGIONS["eu"])
    token  = get_token(cfg, base)
    r = requests.get(base + path, headers=_sign(cfg, "GET", path, token), timeout=15)
    return r.json()

# ── Map download ──────────────────────────────────────────────────

def fetch_map_urls(cfg):
    """Returns (app_map_url, robot_map_url) from latest stored file."""
    did = cfg["device_id"]

    # 1. Try realtime first (works right after cleaning)
    result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/realtime-map")
    if result.get("success") and result.get("result"):
        maps = result["result"]
        app  = next((m["map_url"] for m in maps if m.get("map_type")==0), None)
        path = next((m["map_url"] for m in maps if m.get("map_type")==1), None)
        if app:
            print(f"Realtime map available (types: {[m.get('map_type') for m in maps]})")
            return app, path

    # 2. Fall back to latest stored file
    result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/list?file_type=pic&page_no=1&page_size=1")
    if not result.get("success") or not result.get("result", {}).get("datas"):
        print(f"No map files found. API response: {result}")
        return None, None

    file_id = result["result"]["datas"][0]["id"]
    fname   = result["result"]["datas"][0].get("file_name", "")
    print(f"Using stored file ID {file_id}: {fname}")

    result2 = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/download?id={file_id}")
    if not result2.get("success"):
        print(f"Download error: {result2}")
        return None, None

    r2     = result2.get("result", {})
    app    = r2.get("app_map")
    path   = r2.get("robot_map")
    return app, path

def download_bytes(url):
    if not url:
        return None
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content

# ── Room map decoder (LZ4) ────────────────────────────────────────

ROOM_CELLS  = [0x00, 0x04, 0x08, 0x0C, 0x10]
ROOM_COLORS = [
    (255, 210, 175), (200, 185, 240), (245, 185, 205),
    (210, 185, 245), (170, 195, 240),
]
CELL_TO_ROOM = {v: i for i, v in enumerate(ROOM_CELLS)}

def cell_colour(v):
    if v == 0xFF: return (245, 245, 245)
    if v == 0xF9: return (80,  80,  80)
    if v == 0xF4: return (215, 222, 230)
    if v in CELL_TO_ROOM: return ROOM_COLORS[CELL_TO_ROOM[v]]
    return (205, 200, 195)

def shrink(v): return v - 65536 if v > 32767 else v

def decode_app_map(raw):
    """Returns (width, height, resolution, origin_x, origin_y, grid_bytes, room_section)."""
    flds = [struct.unpack(">H", raw[i:i+2])[0] for i in range(0, 24, 2)]
    W, H   = flds[2], flds[3]
    ox, oy = shrink(flds[4]), shrink(flds[5])
    res    = flds[6]
    total  = flds[10]
    clen   = flds[11]
    dec    = lz4b.decompress(raw[24:24+clen], uncompressed_size=total)
    return W, H, res, ox, oy, dec[:W*H], dec[W*H:]

def parse_room_names(data):
    rooms, i = {}, 0
    while i < len(data):
        if 4 <= data[i] <= 30 and i+data[i] < len(data):
            n, nb = data[i], data[i+1:i+data[i]+1]
            if all(32 <= b < 127 for b in nb):
                rooms[len(rooms)] = nb.decode("ascii"); i += 1+n; continue
        i += 1
    return rooms

# ── Robot path decoder ────────────────────────────────────────────

def decode_robot_path(raw, ox, oy, res):
    """
    Decode robot_map file and return list of (col, row) grid positions.
    Tries multiple known Tuya path formats.
    """
    if not raw:
        return []

    units_per_cell = res * 2  # 5cm/cell × 2 units/cm = 10 units/cell

    # Format A: LZ4 compressed, same header as app_map
    try:
        flds = [struct.unpack(">H", raw[i:i+2])[0] for i in range(0, 24, 2)]
        clen = flds[11]; total = flds[10]
        if clen > 0 and clen < len(raw):
            dec = lz4b.decompress(raw[24:24+clen], uncompressed_size=total)
            # Path stored as int16 pairs
            coords = []
            for i in range(0, len(dec)-3, 4):
                x = struct.unpack(">h", dec[i:i+2])[0]
                y = struct.unpack(">h", dec[i+2:i+4])[0]
                c = int((x + ox) / units_per_cell)
                r = int((y + oy) / units_per_cell)
                coords.append((c, r))
            if len(coords) > 10:
                print(f"Path Format A: {len(coords)} points")
                return coords
    except Exception as e:
        pass

    # Format B: raw int16 pairs without header
    try:
        coords = []
        for i in range(0, len(raw)-3, 4):
            x = struct.unpack(">h", raw[i:i+2])[0]
            y = struct.unpack(">h", raw[i+2:i+4])[0]
            c = int((x + ox) / units_per_cell)
            r = int((y + oy) / units_per_cell)
            coords.append((c, r))
        if len(coords) > 10:
            print(f"Path Format B: {len(coords)} points")
            return coords
    except Exception as e:
        pass

    # Format C: text file with "x,y" lines
    try:
        text = raw.decode("utf-8", errors="ignore")
        coords = []
        for line in text.split("\n"):
            parts = line.strip().split(",")
            if len(parts) >= 2:
                try:
                    x, y = int(parts[0]), int(parts[1])
                    c = int((x + ox) / units_per_cell)
                    r = int((y + oy) / units_per_cell)
                    coords.append((c, r))
                except: pass
        if len(coords) > 10:
            print(f"Path Format C (text): {len(coords)} points")
            return coords
    except: pass

    print("Could not decode robot_map path (unknown format)")
    print(f"  First 32 bytes: {raw[:32].hex(' ')}")
    return []

# ── Renderer ──────────────────────────────────────────────────────

def _font(size):
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(fp):
            try:
                from PIL import ImageFont
                return ImageFont.truetype(fp, size)
            except: pass
    from PIL import ImageFont
    return ImageFont.load_default()

def render(W, H, res, ox, oy, grid, room_section, path_coords,
           scale=4, output_path="map.png"):
    room_names = parse_room_names(room_section)

    arr = np.zeros((H, W, 3), np.uint8)
    for r in range(H):
        for c in range(W):
            arr[r, c] = cell_colour(grid[r*W+c])

    img  = Image.fromarray(arr).resize((W*scale, H*scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)

    # Draw cleaning path
    if len(path_coords) > 1:
        valid = [(c*scale+scale//2, r*scale+scale//2)
                 for c,r in path_coords if 0<=c<W and 0<=r<H]
        if len(valid) > 1:
            draw.line(valid, fill=(255,255,255), width=max(1, scale//2))
            print(f"Drew path with {len(valid)} points")

    # Room labels
    font_lg = _font(18)
    font_sm = _font(13)
    for idx, name in room_names.items():
        cv  = ROOM_CELLS[idx]
        pos = [(r,c) for r in range(H) for c in range(W) if grid[r*W+c]==cv]
        if not pos: continue
        rows=[r for r,c in pos]; cols=[c for r,c in pos]
        cr,cc = sum(rows)//len(rows), sum(cols)//len(cols)
        px,py = cc*scale+scale//2, cr*scale+scale//2
        bb  = font_lg.getbbox(name)
        tw,th,pad = bb[2]-bb[0],bb[3]-bb[1],8
        draw.rounded_rectangle(
            [px-tw//2-pad, py-th//2-pad, px+tw//2+pad, py+th//2+pad],
            radius=8, fill=(255,255,255), outline=(100,100,100), width=1)
        draw.text((px,py), name, fill=(40,40,40), font=font_lg, anchor="mm")

    # Dock
    units_per_cell = res*2
    dc = int(ox/units_per_cell); dr = int(oy/units_per_cell)
    if 0<=dc<W and 0<=dr<H:
        dx,dy,R = dc*scale+scale//2, dr*scale+scale//2, 12
        draw.ellipse([dx-R,dy-R,dx+R,dy+R], fill=(50,200,80), outline=(20,140,40), width=2)
        draw.text((dx,dy), "⚡", fill=(255,255,255), font=font_sm, anchor="mm")

    # Scale bar
    bar = (100//res)*scale
    bx,by = 20, H*scale-35
    draw.rectangle([bx,by,bx+bar,by+5], fill=(80,80,80))
    draw.text((bx+bar//2,by+14), "1 m", fill=(80,80,80), font=font_sm, anchor="mm")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    img.save(output_path, optimize=True)
    print(f"Saved: {output_path}  ({W*scale}×{H*scale}px)")

# ── Main ──────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Fetch + render vacuum map for Home Assistant")
    p.add_argument("--output", default="/config/www/vacuum_map.png")
    p.add_argument("--scale",  type=int, default=4)
    args = p.parse_args()

    cfg = load_config()
    print("Fetching map from Tuya Cloud...")

    app_url, path_url = fetch_map_urls(cfg)
    if not app_url:
        print("ERROR: No map available"); sys.exit(1)

    print("Downloading app_map...")
    app_raw  = download_bytes(app_url)
    print(f"  {len(app_raw):,} bytes")

    path_raw = None
    if path_url:
        print("Downloading robot_map (cleaning path)...")
        path_raw = download_bytes(path_url)
        print(f"  {len(path_raw):,} bytes  | first 8 bytes: {path_raw[:8].hex()}")
    else:
        print("No robot_map available for this session")

    W, H, res, ox, oy, grid, room_section = decode_app_map(app_raw)
    print(f"Grid: {W}×{H}  res={res}cm  origin=({ox},{oy})")

    path_coords = decode_robot_path(path_raw, ox, oy, res) if path_raw else []

    render(W, H, res, ox, oy, grid, room_section, path_coords,
           scale=args.scale, output_path=args.output)

if __name__ == "__main__":
    main()
