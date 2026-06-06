#!/usr/bin/env python3
"""
vacuum_map.py — Fetch vacuum map from Tuya Cloud API
Part of the tuya-vacuum-local project.

Usage:
  python vacuum_map.py                    # download latest map (layout + path)
  python vacuum_map.py --list             # list all stored map files
  python vacuum_map.py --download ID      # download specific file by ID
  python vacuum_map.py --realtime         # fetch realtime map (during/after cleaning)
  python vacuum_map.py --watch            # poll every 30s and download new maps
  python vacuum_map.py --render           # download + render to PNG in one shot
"""

import os, sys, json, time, argparse, hashlib, hmac
from datetime import datetime
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("Missing: pip install requests"); sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Config ────────────────────────────────────────────────────────

def load_config():
    path = os.path.join(SCRIPT_DIR, "config.json")
    if not os.path.exists(path):
        print("ERROR: config.json not found"); sys.exit(1)
    with open(path) as f:
        return json.load(f)

# ── Tuya Cloud API ────────────────────────────────────────────────

REGIONS = {
    "eu": "https://openapi.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}
_token_cache = {"token": None, "expiry": 0.0}

def _sign(client_id, client_secret, method, path, token=""):
    ts  = str(int(time.time() * 1000))
    bh  = hashlib.sha256(b"").hexdigest()
    s2s = "\n".join([method, bh, "", path])
    msg = client_id + (token or "") + ts + s2s
    sg  = hmac.new(key=client_secret.encode(), msg=msg.encode(),
                   digestmod=hashlib.sha256).hexdigest().upper()
    return {"client_id": client_id, "sign": sg, "t": ts,
            "sign_method": "HMAC-SHA256", "access_token": token or ""}

def get_token(cfg, base_url):
    if time.time() < _token_cache["expiry"] - 60 and _token_cache["token"]:
        return _token_cache["token"]
    p = "/v1.0/token?grant_type=1"
    r = requests.get(base_url + p,
                     headers=_sign(cfg["tuya_client_id"],
                                   cfg["tuya_client_secret"], "GET", p),
                     timeout=10).json()
    if not r.get("success"):
        print(f"ERROR token: {r}"); sys.exit(1)
    _token_cache["token"]  = r["result"]["access_token"]
    _token_cache["expiry"] = time.time() + r["result"]["expire_time"]
    return _token_cache["token"]

def api_get(cfg, path):
    region = cfg.get("tuya_region", "eu")
    base   = REGIONS.get(region, REGIONS["eu"])
    token  = get_token(cfg, base)
    return requests.get(base + path,
                        headers=_sign(cfg["tuya_client_id"],
                                      cfg["tuya_client_secret"],
                                      "GET", path, token),
                        timeout=15).json()

# ── Download helpers ──────────────────────────────────────────────

MAP_TYPE_LABELS = {0: "layout", 1: "path", 2: "incremental", 3: "planning"}

def download_and_save(url: str, filename: str) -> int:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    with open(filename, "wb") as f:
        f.write(r.content)
    return len(r.content)

# ── CLI commands ──────────────────────────────────────────────────

def cmd_realtime(cfg):
    """Download realtime map (type 0=layout, type 1=path)."""
    did    = cfg["device_id"]
    result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/realtime-map")
    if not result.get("success"):
        print(f"Error: {result}"); return

    maps = result.get("result", [])
    if not maps:
        print("No realtime map available (robot may be idle or map not updated yet).")
        print("Try calling this immediately after cleaning finishes.")
        return

    saved = []
    for m in maps:
        mtype = m.get("map_type", "?")
        url   = m.get("map_url", "")
        if not url:
            continue
        label = MAP_TYPE_LABELS.get(mtype, f"type{mtype}")
        ext   = url.split("?")[0].split(".")[-1] or "bin"
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"map_{label}_{ts}.{ext}"
        n     = download_and_save(url, fname)
        print(f"Saved {label} map: {fname} ({n:,} bytes)")
        saved.append((label, fname))

    if saved:
        print(f"\nDownloaded {len(saved)} map file(s).")
        print("Render with: python vacuum_map_decode.py <layout_file>")

def cmd_list(cfg, file_type="pic"):
    """List stored map files."""
    did    = cfg["device_id"]
    params = urlencode({"file_type": file_type, "page_no": 1, "page_size": 20})
    result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/list?{params}")
    if not result.get("success"):
        print(f"Error: {result}"); return

    datas = result.get("result", {}).get("datas", [])
    total = result.get("result", {}).get("total_count", 0)
    if not datas:
        print("No map files found."); return

    print(f"Total: {total} file(s)\n")
    print(f"{'ID':<14} {'Date':<22} {'Filename'}")
    print("-" * 65)
    for d in datas:
        ts   = datetime.fromtimestamp(d.get("time", 0)).strftime("%Y-%m-%d %H:%M:%S")
        fid  = d.get("id", "?")
        fn   = d.get("file_name") or d.get("extend", "?")
        print(f"{fid:<14} {ts:<22} {fn}")
    print(f"\nDownload with: python vacuum_map.py --download <ID>")

def cmd_download(cfg, file_id: int):
    """Download a specific map file (saves BOTH app_map and robot_map)."""
    did    = cfg["device_id"]
    result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/download?id={file_id}")
    if not result.get("success"):
        print(f"Error: {result}"); return

    res = result.get("result", {})
    saved = []
    for key, label in [("app_map", "layout"), ("robot_map", "path")]:
        url = res.get(key)
        if not url:
            print(f"  {label}: not available for this session")
            continue
        ext   = url.split("?")[0].split(".")[-1] or "bin"
        fname = f"map_{label}_{file_id}.{ext}"
        n     = download_and_save(url, fname)
        print(f"  Saved {label}: {fname} ({n:,} bytes)")
        saved.append(fname)

    if saved:
        layout = next((f for f in saved if "layout" in f), None)
        path   = next((f for f in saved if "path" in f), None)
        print()
        if layout:
            print(f"Render room map:  python vacuum_map_decode.py {layout}")
        if layout and path:
            print(f"Render with path: python vacuum_map_decode.py {layout} --path {path}")

def cmd_watch(cfg, interval=30):
    """Poll realtime-map every N seconds and download when URL changes."""
    print(f"Watching for map updates every {interval}s… (Ctrl+C to stop)")
    print("Start a full house clean, then call this.\n")
    seen = set()
    while True:
        try:
            did    = cfg["device_id"]
            result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/realtime-map")
            maps   = result.get("result", [])
            ts     = datetime.now().strftime("%H:%M:%S")
            if not maps:
                print(f"[{ts}] No map yet (result=[])  — keep waiting...")
            else:
                for m in maps:
                    url = m.get("map_url", "")
                    if url and url not in seen:
                        seen.add(url)
                        mtype = m.get("map_type", "?")
                        label = MAP_TYPE_LABELS.get(mtype, f"type{mtype}")
                        ext   = url.split("?")[0].split(".")[-1] or "bin"
                        fname = f"map_{label}_{ts.replace(':','')}.{ext}"
                        n     = download_and_save(url, fname)
                        print(f"[{ts}] New {label} map → {fname} ({n:,} bytes)")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped."); break

def cmd_render(cfg):
    """Download latest map and render it immediately."""
    # Download
    did    = cfg["device_id"]
    result = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/list?file_type=pic&page_no=1&page_size=1")
    if not result.get("success") or not result.get("result", {}).get("datas"):
        print("No files found."); return

    fid    = result["result"]["datas"][0]["id"]
    result2 = api_get(cfg, f"/v1.0/users/sweepers/file/{did}/download?id={fid}")
    res    = result2.get("result", {})

    layout_raw = path_raw = None
    for key, label in [("app_map","layout"),("robot_map","path")]:
        url = res.get(key)
        if url:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            if label == "layout": layout_raw = r.content
            else:                 path_raw   = r.content
            print(f"Downloaded {label}: {len(r.content):,} bytes")

    if not layout_raw:
        print("No layout map available."); return

    # Render
    try:
        from vacuum_map_decode import parse_header, decompress_map, render_map
        header = parse_header(layout_raw)
        grid, room_section = decompress_map(layout_raw, header)
        out = f"map_render_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        render_map(grid, room_section, header, scale=5, output_path=out)
        print(f"Rendered: {out}")
    except ImportError:
        print("vacuum_map_decode.py not found — saving raw files instead")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"map_layout_{ts}.bin","wb") as f: f.write(layout_raw)
        if path_raw:
            with open(f"map_path_{ts}.bin","wb") as f: f.write(path_raw)

# ── Main ──────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Tuya vacuum cloud map tool")
    p.add_argument("--list",      action="store_true", help="List stored map files")
    p.add_argument("--file-type", default="pic", choices=["pic","collect_recode"])
    p.add_argument("--download",  type=int, metavar="FILE_ID",
                   help="Download app_map + robot_map for a specific file ID")
    p.add_argument("--realtime",  action="store_true",
                   help="Download realtime map (best called right after cleaning)")
    p.add_argument("--watch",     action="store_true",
                   help="Poll for new maps every 30s")
    p.add_argument("--interval",  type=int, default=30)
    p.add_argument("--render",    action="store_true",
                   help="Download latest map and render PNG immediately")
    args = p.parse_args()

    cfg = load_config()
    if not cfg.get("tuya_client_id") or "YOUR_" in str(cfg.get("tuya_client_id","")):
        print("ERROR: add tuya_client_id + tuya_client_secret to config.json"); sys.exit(1)

    if   args.list:     cmd_list(cfg, args.file_type)
    elif args.download: cmd_download(cfg, args.download)
    elif args.realtime: cmd_realtime(cfg)
    elif args.watch:    cmd_watch(cfg, args.interval)
    elif args.render:   cmd_render(cfg)
    else:               cmd_realtime(cfg)   # default = realtime

if __name__ == "__main__":
    main()
