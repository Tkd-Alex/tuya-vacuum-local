#!/usr/bin/env python3
"""
vacuum_cmd.py — Local control CLI for Tuya-based robot vacuums
Part of the tuya-vacuum-local project.

Tested on: Philips HomeRun Series 3000 / 3100 (XU3100)
May work with other Tuya-protocol vacuums sharing the same firmware.

Protocol summary (fully reverse-engineered — see PROTOCOL.md):
  ROOM  : 0x4D wake + sync + CMD 0x51 × N + CMD 0x27 + DP1=True + DP4=selectroom
  ZONE  : sync + bundle(0x57[01] + 0x55[zone_data] + …)  + DP1=True + DP4=zone
  SPOT  : sync + bundle(0x57[spot_data] + 0x55[01,00] + …) + DP1=True + DP4=pose

Map coordinate system: 200 units = 1 metre  (origin = dock position)

Usage:
  python vacuum_cmd.py clean  --rooms 0,2    --suction 3,2  --water 2,0
  python vacuum_cmd.py preset --name turbo   --rooms 0,1,2
  python vacuum_cmd.py zone   --zone kitchen --suction 2    --water 1
  python vacuum_cmd.py zone   --coords -400,-200,200,-900
  python vacuum_cmd.py spot   --spot center
  python vacuum_cmd.py spot   --x -88 --y -660
  python vacuum_cmd.py decode-zone <base64>
  python vacuum_cmd.py test-room --id 0
  python vacuum_cmd.py stop | charge | locate | status | resume | map-request
  python vacuum_cmd.py rooms | presets | zones
"""

import sys, os, json, base64, argparse, time, struct
import tinytuya

# ── Configuration loader ──────────────────────────────────────────

def load_config() -> dict:
    """
    Loads config.json from the script directory.
    Falls back to snapshot.json (tinytuya wizard output) for device credentials.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")

    if not os.path.exists(config_path):
        print("ERROR: config.json not found.", file=sys.stderr)
        print("  Copy config.example.json to config.json and fill in your values.", file=sys.stderr)
        print("  See README.md for instructions.", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        cfg = json.load(f)

    # Resolve device credentials: config.json takes priority, then snapshot.json
    if not cfg.get("device_ip") or not cfg.get("device_key"):
        snap_path = os.path.join(script_dir, "snapshot.json")
        if os.path.exists(snap_path):
            with open(snap_path) as f:
                snap = json.load(f)
            devices = snap if isinstance(snap, list) else snap.get("devices", [])
            for d in devices:
                if d.get("id") == cfg.get("device_id") or d.get("gwId") == cfg.get("device_id"):
                    cfg.setdefault("device_ip",      d.get("ip"))
                    cfg.setdefault("device_key",     d.get("key") or d.get("localKey"))
                    cfg.setdefault("device_version", d.get("ver") or d.get("version"))
                    break

    for field in ("device_id", "device_ip", "device_key"):
        if not cfg.get(field):
            print(f"ERROR: '{field}' missing from config.json", file=sys.stderr)
            sys.exit(1)

    cfg["device_version"] = float(str(cfg.get("device_version", 3.3)))
    return cfg


CFG = None  # loaded lazily on first use

def cfg() -> dict:
    global CFG
    if CFG is None:
        CFG = load_config()
    return CFG

def get_device():
    c = cfg()
    d = tinytuya.Device(c["device_id"], c["device_ip"], c["device_key"],
                        version=c["device_version"])
    d.set_socketTimeout(6)
    return d

# ── Fixed protocol constants (do not change) ─────────────────────

# Captured from app traffic — these are protocol-level handshake frames
_PREAMBLE_WAKE = "qgAGTQE7msoD8A=="
_PREAMBLE_SYNC = "qgACVwFYqgADVQEAVqoAAzkBADqqAAMTAQAUqgADUwEAVA=="

# ── Coordinate helpers ────────────────────────────────────────────

def m_to_u(metres: float) -> int:
    """Convert metres to map units (200 units = 1 metre)."""
    return round(metres * 200)

def u_to_m(units: int) -> float:
    """Convert map units to metres."""
    return units / 200.0

def rect_from_centre(cx: int, cy: int, w: int, h: int):
    """Return 4 corners [(x,y)…] of a rectangle given centre and size (map units)."""
    hw, hh = w // 2, h // 2
    return [(cx-hw, cy+hh), (cx+hw, cy+hh), (cx+hw, cy-hh), (cx-hw, cy-hh)]

# ── Low-level frame construction ──────────────────────────────────

def _checksum(data: bytes) -> int:
    return sum(data) & 0xFF

def _aa_frame(cmd: int, payload) -> bytes:
    data = bytes([cmd] + list(payload))
    return bytes([0xAA, 0x00, len(data)]) + data + bytes([_checksum(data)])

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()

# ── CMD 0x51 — room configuration frame ──────────────────────────

def _build_room_frame(room_id: int, suction=None, water=None, passes=1) -> bytes:
    """
    Builds a CMD 0x51 frame for one room.
    FF FF bytes mean "use current global settings" — replaced when suction/water specified.
    Template bytes preserve per-room structural data captured from the device.
    """
    templates = cfg().get("room_templates", {})
    tpl_hex = templates.get(str(room_id))
    if not tpl_hex:
        raise ValueError(
            f"No template for room {room_id}. "
            "Capture it with vacuum_listener.py while using the app. See PROTOCOL.md."
        )
    frame = bytearray(bytes.fromhex(tpl_hex.replace(" ", "")))
    # byte[11]=passes  byte[12]=suction  byte[13]=water
    if passes  != 1:         frame[11] = passes
    if suction is not None:  frame[12] = suction
    if water   is not None:  frame[13] = water
    frame[-1] = _checksum(frame[3:-1])
    return bytes(frame)

def _build_start_frame(room_ids: list) -> bytes:
    """CMD 0x27 — defines cleaning order."""
    return _aa_frame(0x27, [0x01, len(room_ids)] + list(room_ids))

# ── CMD 0x55 — zone configuration ────────────────────────────────

def _zone_payload(zones: list) -> list:
    """
    Encodes N zones into CMD 0x55 payload.
    Each zone: {"corners": [(x,y),…], "suction": int, "water": int,
                "passes": int, "carpet": int}
    """
    payload = [0x01, len(zones)]
    for z in zones:
        corners = z["corners"]
        payload.append(len(corners))
        for x, y in corners:
            payload += list(struct.pack(">hh", int(x), int(y)))
        payload += [
            0x05, 0x00, 0x00, 0x00,
            z.get("passes",  1),
            z.get("suction", 2),
            z.get("water",   0),
            0xFF, 0x00, 0xFF,
            z.get("carpet",  0),
        ]
    return payload

def _build_zone_bundle(zones: list) -> bytes:
    bundle  = _aa_frame(0x57, [0x01])
    bundle += _aa_frame(0x55, _zone_payload(zones))
    bundle += _aa_frame(0x39, [0x01, 0x00])
    bundle += _aa_frame(0x13, [0x01, 0x00])
    bundle += _aa_frame(0x53, [0x01, 0x00])
    return bundle

# ── CMD 0x57 — spot configuration ────────────────────────────────

def _build_spot_bundle(x: int, y: int, suction: int, water: int, passes: int = 1) -> bytes:
    payload = [0x01] + list(struct.pack(">hh", x, y)) + [
        0x05, 0x00, 0x00, 0x00, passes, suction, water, 0xFF, 0xFF, 0xFF, 0x01
    ]
    bundle  = _aa_frame(0x57, payload)
    bundle += _aa_frame(0x55, [0x01, 0x00])
    bundle += _aa_frame(0x39, [0x01, 0x00])
    bundle += _aa_frame(0x13, [0x01, 0x00])
    bundle += _aa_frame(0x53, [0x01, 0x00])
    return bundle

# ── Cleaning sequences ────────────────────────────────────────────

def _parse_list(arg, length: int, default):
    if arg is None:
        return [default] * length
    v = [int(x) for x in str(arg).split(",")]
    return v * length if len(v) == 1 else v

def run_room_clean(room_ids: list, suctions: list, waters: list, passes_list: list):
    d = get_device()
    print("→ Wake (0x4D)…")
    d.set_value(15, _PREAMBLE_WAKE);   time.sleep(0.4)
    print("→ Session sync…")
    d.set_value(15, _PREAMBLE_SYNC);   time.sleep(0.4)
    for i, rid in enumerate(room_ids):
        frame = _build_room_frame(rid, suctions[i], waters[i], passes_list[i])
        d.set_value(15, _b64(frame))
        print(f"→ Configure room {rid}")
        time.sleep(0.4)
    d.set_value(15, _b64(_build_start_frame(room_ids)))
    print(f"→ Start order {room_ids}")
    time.sleep(0.4)
    print("→ Trigger motors (DP1=True, DP4=selectroom)…")
    print(d.set_multiple_values({1: True, 4: "selectroom"}))

def run_zone_clean(zones_config: list):
    d = get_device()
    print("→ Session sync…")
    d.set_value(15, _PREAMBLE_SYNC);   time.sleep(0.4)
    d.set_value(15, _b64(_build_zone_bundle(zones_config)))
    print(f"→ Zone bundle sent ({len(zones_config)} zone(s))")
    time.sleep(0.4)
    print("→ Trigger motors (DP1=True, DP4=zone)…")
    print(d.set_multiple_values({1: True, 4: "zone"}))

def run_spot_clean(x: int, y: int, suction: int, water: int, passes: int = 1):
    d = get_device()
    print("→ Session sync…")
    d.set_value(15, _PREAMBLE_SYNC);   time.sleep(0.4)
    d.set_value(15, _b64(_build_spot_bundle(x, y, suction, water, passes)))
    print(f"→ Spot bundle sent ({x}, {y})")
    time.sleep(0.4)
    print("→ Trigger motors (DP1=True, DP4=pose)…")
    print(d.set_multiple_values({1: True, 4: "pose"}))

# ── Decoder: extract zone data from captured base64 ───────────────

def decode_zone_b64(b64_str: str):
    """
    Parses a raw DP15 base64 string captured from the app,
    finds CMD 0x55 frames and prints zone corners + settings.
    Output can be pasted directly into config.json zones section.
    """
    raw = base64.b64decode(b64_str)
    i = 0
    found = False
    while i < len(raw):
        if raw[i] == 0xAA and i + 2 < len(raw):
            length = (raw[i+1] << 8) | raw[i+2]
            end = i + 3 + length
            data = raw[i+3:end]
            if data and data[0] == 0x55 and len(data) > 3:
                found = True
                payload = list(data[1:])
                if payload[1] == 0x00:
                    i = end + 1; continue  # short/empty 0x55 frame
                print("\n[CMD 0x55] Zone payload decoded:")
                num_zones = payload[1]
                print(f"  Zones: {num_zones}")
                pos = 2
                for z in range(num_zones):
                    nc = payload[pos]; pos += 1
                    corners = []
                    for _ in range(nc):
                        x, y = struct.unpack(">hh", bytes(payload[pos:pos+4]))
                        corners.append([x, y])
                        pos += 4
                    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
                    w_u = max(xs) - min(xs); h_u = max(ys) - min(ys)
                    pos += 4  # skip 05 00 00 00
                    passes  = payload[pos]; pos += 1
                    suction = payload[pos]; pos += 1
                    water   = payload[pos]; pos += 1
                    pos += 3  # FF 00 FF
                    carpet  = payload[pos]; pos += 1
                    print(f"\n  Zone {z+1}:")
                    print(f"    Size:    {u_to_m(w_u):.2f} m × {u_to_m(h_u):.2f} m")
                    print(f"    Corners: {corners}")
                    print(f"    suction={suction}  water={water}  passes={passes}  carpet={carpet}")
                    print(f"\n  → Paste into config.json:")
                    print(f'    "my-zone-{z+1}": {{')
                    print(f'      "corners": {corners},')
                    print(f'      "label": "My Zone {z+1}"')
                    print(f'    }}')
            i = end + 1
        else:
            i += 1
    if not found:
        print("No CMD 0x55 zone data found in this base64 string.")

# ── CLI commands ──────────────────────────────────────────────────

def cmd_clean(args):
    rooms    = [int(r) for r in str(args.rooms).split(",")]
    suctions = _parse_list(args.suction, len(rooms), None)
    waters   = _parse_list(args.water,   len(rooms), None)
    passes   = _parse_list(args.passes,  len(rooms), 1)
    run_room_clean(rooms, suctions, waters, passes)

def cmd_preset(args):
    presets = cfg().get("presets", {})
    p = presets.get(args.name.lower())
    if not p:
        print(f"Unknown preset. Available: {', '.join(presets) or 'none (add to config.json)'}")
        sys.exit(1)
    print(f"Preset: {p.get('label', args.name)}")
    rooms    = [int(r) for r in str(args.rooms).split(",")] if args.rooms else list(cfg().get("rooms", {}).keys())
    rooms    = [int(r) for r in rooms]
    run_room_clean(rooms, [p["suction"]]*len(rooms), [p["water"]]*len(rooms), [p["passes"]]*len(rooms))

def cmd_zone(args):
    suction = int(args.suction) if args.suction else 2
    water   = int(args.water)   if args.water   else 0
    passes  = int(args.passes)  if args.passes  else 1
    carpet  = int(args.carpet)  if args.carpet  else 0

    if args.zone:
        zones_cfg = cfg().get("zones", {})
        z = zones_cfg.get(args.zone)
        if not z:
            print(f"Unknown zone '{args.zone}'. Available: {', '.join(zones_cfg) or 'none'}")
            print("Add zones to config.json or use: python vacuum_cmd.py decode-zone <base64>")
            sys.exit(1)
        zones = [{"corners": z["corners"], "suction": suction, "water": water,
                  "passes": passes, "carpet": carpet}]
    elif args.coords:
        try:
            x1,y1,x2,y2 = [int(v) for v in args.coords.split(",")]
        except Exception:
            print("--coords expects x1,y1,x2,y2 (map units, 200=1m)"); sys.exit(1)
        zones = [{"corners": [(x1,y1),(x2,y1),(x2,y2),(x1,y2)],
                  "suction": suction, "water": water, "passes": passes, "carpet": carpet}]
    else:
        print("Provide --zone <name> or --coords x1,y1,x2,y2"); sys.exit(1)

    run_zone_clean(zones)

def cmd_spot(args):
    x = int(args.x) if args.x else 0
    y = int(args.y) if args.y else 0
    if args.spot:
        sp = cfg().get("spots", {}).get(args.spot)
        if sp:
            x, y = sp["x"], sp["y"]
    suction = int(args.suction) if args.suction else 2
    water   = int(args.water)   if args.water   else 0
    passes  = int(args.passes)  if args.passes  else 1
    run_spot_clean(x, y, suction, water, passes)

def cmd_test_room(args):
    """Send robot to a single room with default settings — use this to map ID → physical room."""
    rid = int(args.id)
    print(f"Sending robot to room ID {rid} with suction=2, water=0…")
    run_room_clean([rid], [None], [None], [1])

def cmd_decode_zone(args):
    decode_zone_b64(args.b64)

def cmd_stop(args):   print(get_device().set_value(2, True))
def cmd_charge(args): print(get_device().set_value(3, True))
def cmd_locate(args): print(get_device().set_value(11, True))

def cmd_fault_resume(args):
    """Send CMD 0x4C to clear fault state and resume cleaning."""
    d = get_device()
    frame = _aa_frame(0x4C, [])
    print(f"→ Fault recovery (0x4C): {_b64(frame)}")
    print(d.set_value(15, _b64(frame)))

def cmd_status(args):
    st = get_device().status()
    if st and "dps" in st:
        dps = st["dps"]
        out = {
            "status":  dps.get("5",  "?"),
            "battery": dps.get("8",  "?"),
            "mode":    dps.get("4",  "?"),
            "suction": dps.get("9",  "?"),
            "water":   dps.get("10", "?"),
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"Error: {st}", file=sys.stderr)

def cmd_list_rooms(args):
    rooms = cfg().get("rooms", {})
    if not rooms:
        print("No rooms configured. Add them to config.json."); return
    print("Configured rooms:")
    for rid, name in rooms.items():
        print(f"  ID {rid}: {name}")

def cmd_list_presets(args):
    presets = cfg().get("presets", {})
    if not presets:
        print("No presets configured. Add them to config.json."); return
    print("Configured presets:")
    for k, v in presets.items():
        print(f"  {k:15s}  suction={v['suction']}  water={v['water']}  "
              f"passes={v['passes']}  carpet={v.get('carpet',0)}  ({v.get('label',k)})")

def cmd_list_zones(args):
    zones = cfg().get("zones", {})
    if not zones:
        print("No zones configured. Use 'decode-zone' to extract from app captures."); return
    print("Configured zones:")
    for k, v in zones.items():
        xs = [c[0] for c in v["corners"]]; ys = [c[1] for c in v["corners"]]
        w = u_to_m(max(xs)-min(xs)); h = u_to_m(max(ys)-min(ys))
        print(f"  {k:20s}  {w:.1f}m × {h:.1f}m  ({v.get('label', k)})")


def cmd_request_map(args):
    """
    Send DP16='get_both' to trigger the robot to push the full map
    via command_trans (DP15) locally — no cloud needed.
    The robot responds with cmd=0x39 frames containing map data.
    Saves raw frames to map_local_TIMESTAMP.bin for analysis.
    """
    import base64, time
    from pathlib import Path

    d = get_device()
    d.set_socketPersistent(True)

    print("Sending DP16=get_both (map request)...")
    d.set_value(16, "get_both")
    time.sleep(0.3)

    ts       = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"map_local_{ts}.bin")
    frames   = []

    print(f"Listening for map frames (30s)...  Ctrl+C to stop early.")
    deadline = time.time() + 30
    try:
        while time.time() < deadline:
            data = d.receive()
            if not data or "dps" not in data:
                continue
            for k, v in data["dps"].items():
                if int(k) == 15 and v:   # command_trans
                    raw = base64.b64decode(str(v))
                    # Parse AA frames
                    i = 0
                    while i < len(raw):
                        if raw[i] == 0xAA and i+2 < len(raw):
                            ln  = (raw[i+1]<<8)|raw[i+2]
                            end = i+3+ln
                            fb  = raw[i:end]
                            if len(fb) > 3:
                                cmd = fb[3]
                                if cmd == 0x39:   # map data frame
                                    frames.append(bytes(fb))
                                    pld = fb[4:-1] if len(fb)>4 else b""
                                    print(f"  Map frame cmd=0x39 "
                                          f"({len(pld)} bytes) "
                                          f"preview={pld[:12].hex(' ')}")
                            i = end+1
                        else:
                            i += 1
    except KeyboardInterrupt:
        pass

    if frames:
        # Save concatenated raw frames
        with open(out_path, "wb") as f:
            for fr in frames:
                f.write(fr)
        print(f"\nSaved {len(frames)} map frames → {out_path}")
        print("Share this file to decode the local map format.")
    else:
        print("\nNo 0x39 map frames received.")
        print("Try while the robot is cleaning, or check DP16 value for your device.")


# ── Main ──────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Local control CLI for Tuya robot vacuums",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vacuum_cmd.py clean --rooms 0,2 --suction 3,2 --water 2,0
  python vacuum_cmd.py preset --name turbo --rooms 0,1
  python vacuum_cmd.py zone --zone kitchen --suction 2 --water 1
  python vacuum_cmd.py spot --x -88 --y -660
  python vacuum_cmd.py decode-zone "qgACVwFY..."
  python vacuum_cmd.py test-room --id 0
        """
    )
    sub = p.add_subparsers(dest="command")

    # clean
    cl = sub.add_parser("clean", help="Clean specific rooms in order")
    cl.add_argument("--rooms",   required=True, help="Comma-separated room IDs, e.g. 0,2,4")
    cl.add_argument("--suction", help="Suction per room: 1=gentle 2=normal 3=strong 4=max (default: global)")
    cl.add_argument("--water",   help="Water per room: 0=off 1=low 2=middle 3=high (default: global)")
    cl.add_argument("--passes",  help="Passes per room: 1-5 (default: 1)")

    # preset
    pr = sub.add_parser("preset", help="Clean using a named preset from config.json")
    pr.add_argument("--name",  required=True, help="Preset name as defined in config.json")
    pr.add_argument("--rooms", help="Room IDs to clean (default: all configured rooms)")

    # zone
    zo = sub.add_parser("zone", help="Clean a rectangular zone")
    zog = zo.add_mutually_exclusive_group(required=True)
    zog.add_argument("--zone",   help="Named zone from config.json")
    zog.add_argument("--coords", help="Explicit corners: x1,y1,x2,y2 in map units (200=1m)")
    zo.add_argument("--suction"); zo.add_argument("--water")
    zo.add_argument("--passes");  zo.add_argument("--carpet")

    # spot
    sp = sub.add_parser("spot", help="Clean a specific point on the map")
    sp.add_argument("--spot",  help="Named spot from config.json")
    sp.add_argument("--x",    help="X coordinate (map units)")
    sp.add_argument("--y",    help="Y coordinate (map units)")
    sp.add_argument("--suction"); sp.add_argument("--water"); sp.add_argument("--passes")

    # decode-zone
    dz = sub.add_parser("decode-zone", help="Decode a DP15 base64 captured from the app")
    dz.add_argument("b64", help="Base64 string from vacuum_listener.py output")

    # test-room
    tr = sub.add_parser("test-room", help="Send robot to a single room (for ID discovery)")
    tr.add_argument("--id", required=True, help="Room ID to test (0-4)")

    # info commands
    sub.add_parser("rooms",   help="List configured rooms")
    sub.add_parser("presets", help="List configured presets")
    sub.add_parser("zones",   help="List configured zones")

    # control
    sub.add_parser("stop",   help="Pause cleaning")
    sub.add_parser("charge", help="Return to dock")
    sub.add_parser("locate", help="Play locating sound")
    sub.add_parser("status", help="Print current device status (JSON)")

    # raw
    rw = sub.add_parser("raw", help="Send a raw base64 string directly to DP15")
    rw.add_argument("b64")

    args = p.parse_args()
    handlers = {
        "clean":       cmd_clean,
        "preset":      cmd_preset,
        "zone":        cmd_zone,
        "spot":        cmd_spot,
        "decode-zone": cmd_decode_zone,
        "test-room":   cmd_test_room,
        "rooms":       cmd_list_rooms,
        "presets":     cmd_list_presets,
        "zones":       cmd_list_zones,
        "stop":        cmd_stop,
        "charge":      cmd_charge,
        "locate":      cmd_locate,
        "resume":      cmd_fault_resume,
        "map-request": cmd_request_map,
        "status":      cmd_status,
        "raw":         lambda a: print(get_device().set_value(15, a.b64)),
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
