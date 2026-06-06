#!/usr/bin/env python3
"""
debug_map.py — Standalone tool to test Tuya Cloud map fetching and LZ4 decoding.
Run this locally to verify your credentials and the pure-python decoder.
"""
import json, os, sys
from custom_components.tuya_vacuum.map_decoder import decode_and_render

def test_map():
    if not os.path.exists("config.json"):
        print("Error: config.json not found in current directory.")
        return

    with open("config.json") as f:
        cfg = json.load(f)

    # Mocking the coordinator logic to fetch token and map
    import requests, time, hashlib, hmac

    did = cfg["device_id"]
    cid = cfg["tuya_client_id"]
    cs  = cfg["tuya_client_secret"]
    reg = cfg.get("tuya_region", "eu")
    
    bases = {
        "eu": "https://openapi.tuyaeu.com",
        "us": "https://openapi.tuyaus.com",
        "cn": "https://openapi.tuyacn.com",
        "in": "https://openapi.tuyain.com",
    }
    base = bases.get(reg, bases["eu"])

    def sign(method, path, token=""):
        ts = str(int(time.time() * 1000))
        bh = hashlib.sha256(b"").hexdigest()
        s2s = "\n".join([method, bh, "", path])
        msg = cid + token + ts + s2s
        sg = hmac.new(cs.encode(), msg=msg.encode(), digestmod=hashlib.sha256).hexdigest().upper()
        return {"client_id": cid, "sign": sg, "t": ts, "sign_method": "HMAC-SHA256", "access_token": token}

    print(f"--- Step 1: Getting Cloud Token ---")
    path = "/v1.0/token?grant_type=1"
    r = requests.get(base + path, headers=sign("GET", path)).json()
    if not r.get("success"):
        print(f"Token Error: {r}")
        return
    token = r["result"]["access_token"]
    print("Token obtained successfully.")

    print(f"\n--- Step 2: Fetching Realtime Map Info ---")
    path = f"/v1.0/users/sweepers/file/{did}/realtime-map"
    r = requests.get(base + path, headers=sign("GET", path, token)).json()
    
    layout_raw = None
    if r.get("success") and r.get("result"):
        print(f"Found {len(r['result'])} map entries in realtime API.")
        for m in r["result"]:
            if m.get("map_type") == 0:
                print(f"Downloading layout map: {m['map_url'][:50]}...")
                layout_raw = requests.get(m["map_url"]).content
                break
    
    if not layout_raw:
        print("Realtime map not available. Falling back to latest stored map...")
        path = f"/v1.0/users/sweepers/file/{did}/list?file_type=pic&page_no=1&page_size=1"
        r = requests.get(base + path, headers=sign("GET", path, token)).json()
        if r.get("success") and r.get("result", {}).get("datas"):
            fid = r["result"]["datas"][0]["id"]
            path = f"/v1.0/users/sweepers/file/{did}/download?id={fid}"
            r = requests.get(base + path, headers=sign("GET", path, token)).json()
            url = r.get("result", {}).get("app_map")
            if url:
                print(f"Downloading stored map: {url[:50]}...")
                layout_raw = requests.get(url).content

    if not layout_raw:
        print("Error: Could not find any map data on Tuya Cloud.")
        return

    print(f"\n--- Step 3: Decoding (Pure Python LZ4) ---")
    png_data = decode_and_render(layout_raw)
    
    if png_data.startswith(b"\x89PNG"):
        # Check if it's the error image (it's small and has reddish background)
        if len(png_data) < 5000:
             print("Warning: Decoder returned a small image. It might be the Error Image.")
        
        with open("debug_map.png", "wb") as f:
            f.write(png_data)
        print("Success! Result saved to debug_map.png")
    else:
        print("Error: Decoder did not return a valid PNG.")

if __name__ == "__main__":
    test_map()
