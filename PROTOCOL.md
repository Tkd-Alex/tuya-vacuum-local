# Protocol Reference

Complete reverse-engineering notes for the Tuya local protocol used by
Philips HomeRun Series 3000/3100 (XU3100) and compatible OEM vacuums.

Sources: tinytuya local sniffing, Tuya cloud debug logs, Tuya developer docs.

---

## Frame Format

All binary commands share the same AA-frame envelope:

```
AA  [len_hi]  [len_lo]  [cmd_byte]  [payload…]  [checksum]
```

- **Header**: `0xAA`
- **Length**: 2-byte big-endian — number of data bytes that follow (excluding checksum)
- **cmd_byte**: command identifier (first data byte, included in length count)
- **checksum**: `sum(cmd_byte + all_payload_bytes) & 0xFF`

Python builder:

```python
def aa_frame(cmd: int, payload: list) -> bytes:
    data = bytes([cmd] + list(payload))
    return bytes([0xAA, 0x00, len(data)]) + data + bytes([sum(data) & 0xFF])
```

Multiple AA-frames are often **concatenated into a single DP15 write** (a "bundle").

---

## Datapoints (DPs)

| DP  | Type | Name                  | Notes |
|-----|------|-----------------------|-------|
| 1   | bool | power_go              | Start / stop trigger |
| 2   | bool | pause                 | Pause cleaning |
| 3   | bool | switch_charge         | Return to dock |
| 4   | enum | mode                  | `smart` `zone` `pose` `part` `chargego` |
| 5   | enum | status                | `standby` `cleaning` `paused` `charging` `charge_done` `selectroom` `zone_clean` `goto_pos` `repositing` `fault` `emptying` |
| 6   | int  | clean_time_min        | Minutes elapsed in current session |
| 7   | int  | clean_area_m2         | m² cleaned in current session |
| 8   | int  | battery_pct           | Battery % |
| 9   | enum | suction               | `gentle` `normal` `strong` `strong_plus` (global) |
| 10  | enum | cistern               | `closed` `low` `middle` `high` (global mop level) |
| 11  | bool | locate                | Play locating sound |
| 14  | Raw  | path_data             | Map data — transmitted via Tuya P2P, **not** via local port 6668 |
| 15  | Raw  | command_trans         | **Main command channel** — all binary protocol commands |
| 28  | int  | fault                 | 0=ok, 128=0x80 generic fault, 67108864=0x4000000 stuck/lidar |
| 29  | int  | total_clean_area      | Cumulative m² |
| 30  | int  | total_clean_count     | Total sessions |
| 31  | int  | total_clean_time_min  | Cumulative minutes |
| 107 | int  | dp_107                | Increases slowly during and between sessions; likely lidar rotation counter |
| 132 | int  | dp_132 (sensor_life)  | 剩余充电时间 — Sensor remaining life in minutes (also used as remaining charge time) |

> **Note on DP14 / map data**: The robot transmits the floor map via Tuya's P2P
> cloud channel, not via the local TCP socket (port 6668). DP14 is defined in the
> device schema but is never observed carrying map data over the local connection.
> Use the Tuya Cloud Sweeper API to fetch stored maps after a cleaning session.

---

## Room Cleaning (`mode = selectroom`)

### Fixed preamble

Two DP15 writes required before any room command:

```
WAKE:  qgAGTQE7msoD8A==
       → AA 00 06 4D 01 3B 9A CA 03 F0   (cmd=0x4D)

SYNC:  qgACVwFYqgADVQEAVqoAAzkBADqqAAMTAQAUqgADUwEAVA==
       → bundle of cmd=0x57/0x55/0x39/0x13/0x53 short frames
```

### CMD 0x51 — room configuration

Each room occupies a 10-byte block. One or more rooms can be packed into a single frame.

```
AA [len_hi] [len_lo]  51  01  [num_rooms]
  [room_id] [05] [00] [b1] [b2] [passes] [suction] [water] [01] [00]
  (repeat per room)
  [checksum]
```

| Field   | Byte in block | Values |
|---------|---------------|--------|
| room_id | 0             | 0–4 (device-specific, discover with `test-room`) |
| 05, 00  | 1–2           | Fixed structural bytes |
| b1      | 3             | Per-room value from device memory (captured) |
| b2      | 4             | Per-room value from device memory (captured) |
| passes  | 5             | 1–5 (observed: 0 in multi-room app commands = use device default) |
| suction | 6             | 1=gentle 2=normal 3=strong 4=max — **0xFF = inherit global DP9** |
| water   | 7             | 0=off 1=low 2=middle 3=high — **0xFF = inherit global DP10** |
| 01, 00  | 8–9           | Fixed trailing bytes |

> **FF FF = "global settings"**: when suction and water are both 0xFF,
> the robot uses whatever DP9/DP10 are currently set to.
> This is the default when using preset-based cleaning.

> **b1 and b2 are device-specific** — they must be captured per room from your
> specific device using `vacuum_listener.py`. Do not guess or copy from another device.

**Single room example** (room_id=0, global settings):
```
AA 00 0D 51  01 01  00 05 00 00 02 01 FF FF 01 00  5A
             ↑  ↑   ←────── 10-byte room block ─────→
           ver num
```

**Multi-room example** (rooms 4,3,2 in one frame — captured from app):
```
AA 00 21 51  01 03
  04 05 00 00 02 00 FF FF 01 00
  03 05 00 00 02 00 FF FF 01 00
  02 05 00 00 02 00 FF FF 01 00
  70
```

### CMD 0x27 — cleaning order

```
AA  00  [4+N]  27  01  [num_rooms]  [room_id_0]  [room_id_1]  …  [checksum]
```

### CMD 0x4C — fault recovery *(newly discovered)*

Sent by the app when the robot stops due to a fault (stuck, lidar blocked).
Clears fault state and resumes cleaning.

```
AA 00 01 4C 4C     (cmd=0x4C, no payload, checksum=0x4C)
```

Observed in cloud logs at 18:19:32–18:20:17 after `DP28=67108864` (stuck fault).
After three sends: `DP28→0`, `DP5→standby`, then robot resumed.

### Motor trigger

```
DP1 = True
DP4 = "selectroom"
```

### Complete sequence

```
DP15 ← WAKE   (cmd=0x4D)
DP15 ← SYNC   (bundle)
DP15 ← CMD 0x51  (one frame per room, or all rooms in one frame)
DP15 ← CMD 0x27  (cleaning order)
DP1  ← True
DP4  ← "selectroom"
```

---

## Zone Cleaning (`mode = zone`)

Data in **CMD 0x55** inside a bundle.

### Bundle

```
DP15 ← AA frame 0x57  payload=[01]            (short — fixed)
       AA frame 0x55  payload=[zone_data]
       AA frame 0x39  payload=[01 00]
       AA frame 0x13  payload=[01 00]
       AA frame 0x53  payload=[01 00]
```

### CMD 0x55 payload — N zones

```
01  [num_zones]
  [num_corners]
  [X1_hi X1_lo]  [Y1_hi Y1_lo]
  [X2_hi X2_lo]  [Y2_hi Y2_lo]
  …
  05  00  00  00
  [passes]  [suction]  [water]
  FF  00  FF  [carpet: 0=off 1=on]
  (repeat for each zone)
```

### Coordinate system

```
Origin  : dock / charging station position
Units   : 200 units = 1 metre  (1 unit = 5 mm)
Type    : signed int16 big-endian (">h" in Python struct)
Range   : ±32 767 units = ±163 m
```

Verified across five independent measurements (max deviation < 1.5%):

| Real size | Units measured | Ratio       |
|-----------|----------------|-------------|
| 1.7 m     | 338            | 198.8 ≈ 200 |
| 3.8 m     | 759            | 199.7 ≈ 200 |
| 4.6 m     | 930            | 202.2 ≈ 200 |
| 2.4 m     | 477            | 198.8 ≈ 200 |
| 3.0 m     | 600            | 200.0 = 200 |

### Motor trigger

```
DP1 = True
DP4 = "zone"
```

---

## Spot Cleaning (`mode = pose`)

Data in **CMD 0x57** (roles of 0x57 and 0x55 are swapped vs zone).

### Bundle

```
DP15 ← AA frame 0x57  payload=[spot_data]
       AA frame 0x55  payload=[01 00]       (short — fixed)
       AA frame 0x39  payload=[01 00]
       AA frame 0x13  payload=[01 00]
       AA frame 0x53  payload=[01 00]
```

### CMD 0x57 payload

```
01
[X_hi X_lo]    ← signed int16, same coordinate system as zones
[Y_hi Y_lo]
05  00  00  00
[passes]  [suction]  [water]
FF  FF  FF  01
```

### Motor trigger

```
DP1 = True
DP4 = "pose"
```

---

## Map Data

The floor map is **not transmitted via local connection** (port 6668).
It is uploaded by the robot to Tuya's cloud via a separate P2P channel.

Use the Tuya Cloud Sweeper API to retrieve it:

| Endpoint | Description |
|----------|-------------|
| `GET /v1.0/users/sweepers/file/{device_id}/realtime-map` | Current/live map URLs (valid 1h). Returns layout (type 0), path (type 1), incremental path (type 2), planning (type 3). |
| `GET /v1.0/users/sweepers/file/{device_id}/list?file_type=pic&page_no=1&page_size=20` | List all stored map files with IDs and timestamps. |
| `GET /v1.0/users/sweepers/file/{device_id}/download?id={file_id}` | Download specific map by file ID. Returns `app_map` and `robot_map` URLs. |

Files are typically `.bin` or `.txt` binary format (Tuya proprietary, not yet decoded).

---

## Preset values (from Philips HomeRun / Tuya app)

| App preset name | Suction | Water | Passes |
|-----------------|---------|-------|--------|
| Wee & Dry       | 2       | 3     | 1      |
| Vacuum only     | 2       | 0     | 1      |
| Silent          | 1       | 1     | 1      |
| Intensive       | 4       | 3     | 5      |

---

## Fault codes (DP28)

| Value      | Hex          | Meaning |
|------------|--------------|---------|
| 0          | 0x00000000   | No fault |
| 128        | 0x00000080   | Generic fault (e.g. bin full, side brush stuck) |
| 67108864   | 0x04000000   | Robot stuck / lidar blocked |

**Recovery**: send CMD 0x4C (`AA 00 01 4C 4C`) to clear fault and resume.

---

## Other observed commands

| CMD  | Observed in | Payload | Meaning |
|------|-------------|---------|---------|
| 0x4D | app→device + device→cloud | `01 3B 9A CA 03` | Wake / session ping (required before room cleaning) |
| 0x4C | app→device | (none) | **Fault recovery / resume** |
| 0x5B | app→device | `01 [step]` | Volume control step |
| 0x33 | device→cloud | schedule bytes | Do Not Disturb schedule |
| 0x53 | device→app  | status bytes | Room settings status report (device→app direction) |

---

## Known unknowns

- **DP14 map format**: binary format of the `.bin`/`.txt` map files from cloud not yet decoded.
- **b1/b2 bytes** in CMD 0x51 (positions 3–4 in room block): per-room values stored in device firmware. Origin unclear. Must be captured per-device.
- **DP107**: increases steadily (~0.7 units/min) during and between sessions. Likely lidar rotation counter or internal diagnostics metric.
- **CMD 0x4D payload** (`01 3B 9A CA 03`): meaning of the 5-byte payload unknown. Fixed value observed across all sessions.

---

## Confirmed in production — session 2026-05-23

### CMD 0x53 — multi-room status report (device → app)

Captured every ~10 minutes during a 40-minute cleaning session.
Format confirmed: identical to CMD 0x51 multi-room, **sent by the device** as a
status broadcast (not a command).

```
AA  [len]  53  01  [num_rooms]
  [room_id]  05  00  [b1]  [b2]  [passes]  [suction]  [water]  FF  00  FF  01
  (× num_rooms)
  [checksum]
```

Observed during cleaning (suction=3=strong, water=3=high, passes=1):
```
room_id=3 (Cucina)      suction=3 water=3
room_id=4 (Bagno)       suction=3 water=3
room_id=2 (Camera)      suction=3 water=3
room_id=1 (Stanzetta)   suction=3 water=3
room_id=0 (Ingresso)    suction=3 water=3
```

Cleaning order reflected in the room block order: Cucina→Bagno→Camera→Stanzetta→Ingresso.

### Cleaning path — P2P only

The white cleaning path lines shown in the Tuya app are transmitted exclusively
via Tuya P2P protocol (not via local port 6668, not via REST API during cleaning).

- `DP14 (path_data)` is defined in the schema but **never observed** carrying data
  over the local TCP connection during actual cleaning.
- `GET /realtime-map` returns `[]` during cleaning — only populated after the session ends.
- After cleaning: the `robot_map` file from `GET /download` contains the full path.
- Real-time tracking during cleaning requires implementing the Tuya P2P SDK protocol
  (documented for Android at developer.tuya.com/en/docs/app-development/android-sweeper-p2p).

### Cloud files — confirmed structure

Downloaded map files use **LZ4 block compression** (not custom RLE):
- Header: 24 bytes (12 × big-endian uint16)
- Compressed data: `raw[24 : 24 + header.compressed_length]`
- Decompressed: first `width × height` bytes = room grid, remainder = room name section
- Room cell values: 0x00, 0x04, 0x08, 0x0C, 0x10 (room IDs 0-4, spacing of 4)
- Wall: 0xF9  |  Free space: 0xF4  |  Background: 0xFF

### Session stats (2026-05-23)

- Duration: ~40 min (16:03 → 16:43), interrupted by fault mid-session
- Battery: 97% → 56% (41% consumed)
- Area: ~35 m² across two sub-sessions
- Fault code: DP28 fired during first session, robot recovered automatically
