#!/usr/bin/env python3
"""
vacuum_listener.py — Real-time DP monitor for Tuya robot vacuums
Part of the tuya-vacuum-local project.

ALL output is saved to disk automatically (timestamped files):
  vacuum_log_YYYYMMDD_HHMMSS.txt    — human-readable log (mirrors terminal)
  vacuum_data_YYYYMMDD_HHMMSS.jsonl — structured DP events, one JSON per line
  map_chunks_YYYYMMDD_HHMMSS.jsonl  — DP14 map chunks only (if any)

Usage:
  python vacuum_listener.py                  # log everything
  python vacuum_listener.py --no-save        # terminal only, no files
  python vacuum_listener.py --device-id X --ip 192.168.1.X --key Y
"""

import tinytuya
import base64, json, os, sys, time, argparse, datetime

KNOWN_DPS = {
    1:  "power_go",         2:  "pause",
    3:  "switch_charge",    4:  "mode",
    5:  "status",           6:  "clean_time_min",
    7:  "clean_area_m2",    8:  "battery_pct",
    9:  "suction",          10: "cistern",
    11: "locate",           12: "direction_control",
    13: "reset_map",        14: "path_data_MAP",
    15: "command_trans",
    17: "edge_brush_life",  19: "roll_brush_life",
    21: "filter_life",      23: "dust_cloth_life",
    25: "do_not_disturb",   26: "volume_pct",
    27: "break_clean",      28: "fault",
    29: "total_clean_area", 30: "total_clean_count",
    31: "total_clean_time", 36: "language",
}
RAW_DPS = {14, 15}

C = {
    "r":"\033[0m","y":"\033[93m","c":"\033[96m",
    "g":"\033[92m","red":"\033[91m","b":"\033[1m"
}
def cc(k, t): return f"{C[k]}{t}{C['r']}"


class Tee:
    """Writes to both stdout and a log file simultaneously."""
    def __init__(self, filepath: str):
        self.file = open(filepath, "w", encoding="utf-8", buffering=1)
        self._stdout = sys.stdout

    def write(self, data: str):
        self._stdout.write(data)
        # Strip ANSI color codes for the file
        import re
        clean = re.sub(r'\033\[[0-9;]*m', '', data)
        self.file.write(clean)

    def flush(self):
        self._stdout.flush()
        self.file.flush()

    def close(self):
        self.file.close()

    # passthrough for anything else sys.stdout needs
    def __getattr__(self, name):
        return getattr(self._stdout, name)


def load_credentials(args):
    device_id = args.device_id
    ip = args.ip; key = args.key; ver = args.version
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for fname in ["config.json", "snapshot.json"]:
        path = os.path.join(script_dir, fname)
        if not os.path.exists(path): continue
        with open(path) as f: data = json.load(f)
        if fname == "config.json":
            device_id = device_id or data.get("device_id")
            ip  = ip  or data.get("device_ip")
            key = key or data.get("device_key")
            ver = ver or data.get("device_version")
        else:
            devices = data if isinstance(data, list) else data.get("devices", [])
            for d in devices:
                if not device_id or d.get("id") == device_id or d.get("gwId") == device_id:
                    device_id = device_id or d.get("id") or d.get("gwId")
                    ip  = ip  or d.get("ip")
                    key = key or d.get("key") or d.get("localKey")
                    ver = ver or d.get("ver") or d.get("version")
                    break
        if key: break
    if not all([device_id, ip, key]):
        print(cc("red", "ERROR: credentials not found. Check config.json."))
        sys.exit(1)
    return device_id, ip, key, float(str(ver)) if ver else 3.3


def decode_raw(value: str) -> str:
    try:
        raw = base64.b64decode(value)
        hex_str = raw.hex(" ").upper()
        frames = []
        i = 0
        while i < len(raw):
            if raw[i] == 0xAA and i + 2 < len(raw):
                length = (raw[i+1] << 8) | raw[i+2]
                end = i + 3 + length
                fb = raw[i:end]
                if len(fb) > 3:
                    cmd = fb[3]
                    payload = fb[4:-1] if len(fb) > 4 else b""
                    frames.append(
                        f"    cmd=0x{cmd:02X}({cmd:3d})"
                        f"  payload={payload.hex(' ').upper()}"
                    )
                i = end + 1
            else:
                i += 1
        result = f"\n  hex: {hex_str}"
        if frames:
            result += "\n  frames AA:\n" + "\n".join(frames)
        return result
    except Exception as e:
        return f"  (decode error: {e})"


def print_dp(dp_id: int, value):
    name = KNOWN_DPS.get(dp_id, f"dp_{dp_id}")
    if dp_id in RAW_DPS:
        print(cc("y", f"  DP{dp_id:3d}") + " " + cc("b", name))
        print(f"  base64: {cc('c', str(value))}{cc('g', decode_raw(str(value)))}")
    else:
        print(f"  {cc('c', f'DP{dp_id:3d}')}  {name}: {cc('g', str(value))}")


def main():
    p = argparse.ArgumentParser(
        description="Real-time DP monitor — saves ALL output to disk"
    )
    p.add_argument("--device-id")
    p.add_argument("--ip")
    p.add_argument("--key")
    p.add_argument("--version", type=float)
    p.add_argument("--no-save", action="store_true",
                   help="Don't write any files (terminal only)")
    args = p.parse_args()

    device_id, ip, key, ver = load_credentials(args)

    # ── Setup output files ────────────────────────────────────────
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))

    log_file     = None
    data_file    = None
    map_file     = None
    tee          = None

    if not args.no_save:
        log_path  = os.path.join(script_dir, f"vacuum_log_{ts}.txt")
        data_path = os.path.join(script_dir, f"vacuum_data_{ts}.jsonl")
        map_path  = os.path.join(script_dir, f"map_chunks_{ts}.jsonl")

        tee       = Tee(log_path)
        sys.stdout = tee

        data_file = open(data_path, "w", buffering=1)
        map_file  = open(map_path,  "w", buffering=1)

        print(f"Logging to:    {log_path}")
        print(f"Data file:     {data_path}")
        print(f"Map chunks:    {map_path}")
        print()

    # ── Connect ───────────────────────────────────────────────────
    print(cc("c", f"Connecting to {ip}  device={device_id}  v{ver}…"))

    d = tinytuya.Device(device_id, ip, key, version=ver)
    d.set_socketTimeout(5)

    def log_event(event_type: str, dp_id: int | None,
                  value, raw_b64: str | None = None):
        """Write a structured event to the JSONL data file."""
        if data_file is None:
            return
        record = {
            "ts":    datetime.datetime.now().isoformat(),
            "type":  event_type,
            "dp":    dp_id,
            "name":  KNOWN_DPS.get(dp_id, f"dp_{dp_id}") if dp_id else None,
            "value": value,
        }
        if raw_b64:
            record["b64"] = raw_b64
            try:
                record["hex"] = base64.b64decode(raw_b64).hex(" ").upper()
            except Exception:
                pass
        data_file.write(json.dumps(record) + "\n")

    # ── Initial state ─────────────────────────────────────────────
    try:
        status = d.status()
        if status and "dps" in status:
            print(cc("b", "\n══ Current state ══"))
            for k, v in sorted(status["dps"].items(), key=lambda x: int(x[0])):
                dp_id = int(k)
                print_dp(dp_id, v)
                log_event("initial", dp_id, v,
                          raw_b64=str(v) if dp_id in RAW_DPS else None)
            print()
    except Exception as e:
        print(cc("y", f"Could not read initial state: {e}"))

    d.set_socketPersistent(True)

    print(cc("b", "══ Listening… (Ctrl+C to exit) ══"))
    print(cc("y", "→ ALL DP updates are being saved to disk automatically"))
    print(cc("y", "→ Close the Tuya app before sending commands via script\n"))

    map_chunk_count = 0
    update_count    = 0

    while True:
        try:
            data = d.receive()

            if data and "dps" in data:
                update_count += 1
                ts_str = datetime.datetime.now().strftime("%H:%M:%S")
                print(cc("b", f"\n[{ts_str}] ── Update #{update_count} ──"))

                for k, v in sorted(data["dps"].items(),
                                   key=lambda x: int(x[0])):
                    dp_id = int(k)
                    print_dp(dp_id, v)

                    is_raw = dp_id in RAW_DPS
                    log_event("update", dp_id, v if not is_raw else None,
                              raw_b64=str(v) if is_raw else None)

                    # DP14 = map data
                    if dp_id == 14 and map_file:
                        map_chunk_count += 1
                        map_file.write(json.dumps({
                            "ts":  ts_str,
                            "seq": map_chunk_count,
                            "b64": str(v),
                        }) + "\n")
                        map_file.flush()
                        print(cc("g",
                            f"  → MAP CHUNK #{map_chunk_count} saved!"))

            elif data and data.get("Err"):
                err_msg = f"Error: {data}"
                print(cc("red", err_msg))
                if data_file:
                    data_file.write(json.dumps({
                        "ts":   datetime.datetime.now().isoformat(),
                        "type": "error",
                        "data": data,
                    }) + "\n")

        except KeyboardInterrupt:
            print(cc("c", "\n\n── Session ended ──"))
            print(f"Total updates:  {update_count}")
            print(f"Map chunks:     {map_chunk_count}")
            if not args.no_save:
                print(f"\nFiles saved:")
                print(f"  {log_path}")
                print(f"  {data_path}")
                if map_chunk_count > 0:
                    print(f"  {map_path}  ({map_chunk_count} chunks)")
            break

        except Exception as e:
            print(cc("red", f"Exception: {e}"))
            time.sleep(2)

    # ── Cleanup ───────────────────────────────────────────────────
    if data_file:  data_file.close()
    if map_file:   map_file.close()
    if tee:
        sys.stdout = tee._stdout
        tee.close()


if __name__ == "__main__":
    main()
