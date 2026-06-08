# Tuya Vacuum Local (Advanced Companion)

<p align="center">
  <img src="https://raw.githubusercontent.com/Tkd-Alex/tuya-vacuum-local/main/custom_components/tuya_vacuum/brand/logo.svg" width="150" height="150" alt="Tuya Vacuum Local Logo">
</p>

**Advanced Map and Binary Control for Tuya-based Vacuums.**

This integration is designed as a **Companion** to the excellent [make-all/tuya-local](https://github.com/make-all/tuya-local) project.

## Why this exists?
While `tuya-local` is the gold standard for passive sensors (battery, brush life, etc.) and basic control, it does not support:
1. **Cloud Map Rendering**: Fetching and decoding the proprietary LZ4 map format.
2. **Advanced Binary Commands (DP15)**: Room-by-room cleaning with custom order, zone cleaning, and spot cleaning.

## How it works (The Companion Architecture)
To avoid the "One TCP connection" limitation of Tuya devices:
* **TuyaLocal** maintains the primary connection for sensors.
* **Tuya Vacuum Local** uses "stateless" one-shot connections: it connects, sends an advanced command (like "Clean Kitchen"), and disconnects immediately, allowing `tuya-local` to resume its monitoring without conflict.

---

## What you get

| Feature | Provider |
|---|---|
| Passive Sensors (Battery, Brushes, Filter) | **TuyaLocal** |
| Basic Controls (Start, Pause, Dock) | **TuyaLocal** |
| **Floor Map (Live & Static PNG)** | **This integration** |
| **Room Cleaning (Custom order/settings)** | **This integration** |
| **Zone & Spot Cleaning** | **This integration** |

---

## Installation & Setup

### Prerequisites
1. Install [TuyaLocal](https://github.com/make-all/tuya-local) and configure your vacuum (we recommend the `rowenta_xplorer75s_vacuum` profile for Philips XU3100 models).
2. Ensure the vacuum is working in Home Assistant.

### Option A — HACS (Recommended)
... (rest of HACS instructions) ...

## The white path lines — how it works

The Tuya app shows the robot's cleaning path as white lines on the map.
This data comes from **two sources**, depending on timing:

### During cleaning (real-time)
The robot streams position data via **Tuya P2P** — a direct UDP connection
between the app and the robot, encrypted with a session key from the cloud.
This is **not accessible** via the local tinytuya connection or the REST API.
Implementing P2P in Python is possible but complex (requires reverse-engineering
the Tuya P2P binary protocol — tracked as a future feature).

### After cleaning (static path)
Within ~1–2 minutes of the robot docking, Tuya Cloud publishes two files:
- `app_map` (type 0) — room layout (what we decode for the coloured map)
- `robot_map` (type 1) — the complete cleaning path as coordinate data

The `vacuum_map_refresh.py` script downloads **both** and overlays the path
on the room map automatically. The automation in `configuration.yaml` triggers
this 15 seconds after the robot docks.

**To get the path working now:**
```bash
# 1. After a cleaning session completes
python vacuum_map.py --list          # find the latest file ID

# 2. Download both files
python vacuum_map.py --download ID   # saves map_layout_ID.bin + map_path_ID.bin

# 3. Render with path overlay
python vacuum_map_decode.py map_layout_ID.bin --path map_path_ID.bin
```

> **Note:** If `robot_map` says "not available", the session was too short
> or the cloud hasn't processed it yet. Wait 2–3 minutes and try `--realtime`.

---

## Installation

### Option A — HACS (Recommended)
1. In HA: **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/Tkd-Alex/tuya-vacuum-local` as **Integration**
3. Install **Tuya Vacuum Local**
4. Restart HA
5. **Settings → Devices & Services → Add Integration → Tuya Vacuum Local**
6. Enter your device credentials (see Setup below)

## Dashboard & UI

This integration provides two out-of-the-box UI options to control your vacuum without writing any YAML:

### 🟢 Option 1 — Dedicated Panel (Zero Setup)
Upon configuration, a new "Vacuum" item will automatically appear in your Home Assistant sidebar.
This provides a full-screen, app-like experience where you can see the live map, select rooms, adjust suction/water, and start cleaning.

### 🔧 Option 2 — Lovelace Card (For your Dashboards)
If you want to embed the vacuum controls inside an existing Home Assistant Area or Dashboard (without the map):

1. Go to **Settings → Dashboards → 3 dots menu → Resources → Add Resource**
   - URL: `/tuya_vacuum_static/vacuum-card.js`
   - Resource type: `JavaScript Module`
2. Go to your Dashboard, Edit, and add a Custom Card:
   ```yaml
   type: custom:vacuum-card
   entity: vacuum.tuya_vacuum_xxx # Replace with your actual entity ID
   ```
   *Note: If you configured your rooms via the integration UI, they will automatically appear here.*


### Option B — Manual

```bash
cp -r custom_components/tuya_vacuum /config/custom_components/
```
Restart HA, then add the integration via Settings.

### Option C — CLI only (no HA)

```bash
pip install tinytuya lz4 pillow numpy requests
cp config.example.json config.json   # fill in your credentials
python vacuum_cmd.py status
```

---

## Setup

### Step 1 — Get device credentials (tinytuya wizard)

```bash
pip install tinytuya
python -m tinytuya wizard
```

Follow the prompts. You need a **Tuya developer account** at [platform.tuya.com](https://platform.tuya.com).
The wizard creates `snapshot.json` with your `device_id`, `device_ip`, and `local_key`.

### Step 2 — Capture room templates

Room templates encode per-room structural data stored in the robot's firmware.
They **must be captured from your specific device**.

```bash
# Terminal 1: start listener
python vacuum_listener.py

# Terminal 2: use Tuya app to start single-room clean for each room
# In listener output, look for cmd=0x51 lines and copy the hex strings
```

Add to `config.json`:
```json
"room_templates": {
  "0": "AA 00 0D 51 01 01 00 05 00 ...",
  "1": "AA 00 0D 51 01 01 01 05 00 ..."
}
```

### Step 3 — Discover room IDs

```bash
python vacuum_cmd.py test-room --id 0   # watch which room the robot goes to
python vacuum_cmd.py test-room --id 1
# ... repeat for 2, 3, 4
```

Update `config.json` with real names:
```json
"rooms": {
  "0": "Ingresso",
  "1": "Cucina",
  "2": "Camera",
  "3": "Bagno",
  "4": "Stanzetta"
}
```

### Step 4 — Cloud credentials (for map)

At [platform.tuya.com](https://platform.tuya.com) → Cloud → your project → Overview:

```json
"tuya_client_id":     "abc123...",
"tuya_client_secret": "xyz789...",
"tuya_region":        "eu"
```

---

## CLI usage

```bash
# Cleaning
python vacuum_cmd.py clean --rooms 0,2     --suction 3,2 --water 2,0
python vacuum_cmd.py preset --name intensiva --rooms 0,1,2
python vacuum_cmd.py zone --zone cucina     --suction 2  --water 1
python vacuum_cmd.py zone --coords -400,-200,200,-900
python vacuum_cmd.py spot --x -88 --y -660

# Control
python vacuum_cmd.py stop
python vacuum_cmd.py charge
python vacuum_cmd.py locate
python vacuum_cmd.py resume          # clear fault (robot stuck)
python vacuum_cmd.py status

# Map
python vacuum_cmd.py map-request     # request map via DP16 (local, no cloud)
python vacuum_map.py --list
python vacuum_map.py --download ID
python vacuum_map.py --render        # download + render in one shot
python vacuum_map_decode.py map_layout_*.bin --config   # print room ID mapping
python vacuum_map_decode.py map_layout_*.bin --info
```

---

## HA integration — send_command

The vacuum entity supports advanced commands via `vacuum.send_command`:

```yaml
# Clean specific rooms with per-room settings
service: vacuum.send_command
target:
  entity_id: vacuum.tuya_vacuum
data:
  command: clean_rooms
  params:
    rooms:   [0, 2, 3]
    suction: [3, 2, 2]
    water:   [2, 0, 0]

# Use a preset on specific rooms
service: vacuum.send_command
data:
  command: clean_preset
  params:
    preset: intensiva
    rooms:  [0, 1]

# Zone cleaning
service: vacuum.send_command
data:
  command: clean_zone
  params:
    corners: [[-437, -208], [84, -208], [84, -988], [-437, -988]]
    suction: 2
    water:   1

# Spot cleaning
service: vacuum.send_command
data:
  command: clean_spot
  params:
    x: -88
    y: -660

# Clear fault (robot stuck)
service: vacuum.send_command
data:
  command: resume
```

---

## Map coordinate system

All coordinates use the robot's internal system:

```
Origin (0, 0)  = dock / charging station
Units          = 200 per metre  (1 unit = 5 mm)
Type           = signed int16 big-endian
```

Conversion helpers:
```python
m_to_u = lambda metres: round(metres * 200)   # metres → units
u_to_m = lambda units:  units / 200.0          # units → metres
```

---

## Protocol summary

See [PROTOCOL.md](./PROTOCOL.md) for the complete binary protocol reference.

Key commands (all via DP15 `command_trans`):

| CMD | Direction | Purpose |
|-----|-----------|---------|
| 0x4D | app→robot | Wake / session ping (required before room cleaning) |
| 0x51 | app→robot | Configure room settings (suction, water, passes) |
| 0x27 | app→robot | Set cleaning order |
| 0x55 | app→robot | Zone coordinates + settings |
| 0x57 | app→robot | Spot position + settings |
| 0x4C | app→robot | Clear fault / resume |
| 0x53 | robot→app | Room settings status broadcast |
| 0x39 | robot→app | Map data frames (triggered by DP16=get_both) |

DP16 (`request`) = `"get_both"` triggers the robot to push the full floor map
via cmd=0x39 frames on DP15. This is the local alternative to the cloud API
and does not require internet access.

## Known limitations & Workarounds

### One TCP connection at a time
The robot (Tuya version 3.3) only supports **one active TCP connection** on port 6668. 
- If the Tuya app is open on your phone, `vacuum_cmd.py` or Home Assistant will fail to connect.
- If you use this integration alongside the official **Tuya** or **TuyaLocal** integration, they will compete for the socket.

**Workaround for Home Assistant:**
If you keep both integrations, use a script to reload the passive integration after this one sends a command.
1. Create an automation that triggers when the vacuum starts cleaning.
2. Wait 6-10 seconds.
3. Call `homeassistant.reload_config_entry` for the other Tuya integration.

### Real-time path during cleaning
Requires Tuya P2P protocol (not yet implemented). The path is currently updated ~2 minutes after the robot docks.

---

## License

MIT
