"""Vacuum entity for Tuya Vacuum Local."""
from __future__ import annotations
import base64, struct, time
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity, VacuumEntityFeature, VacuumActivity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, DP_POWER, DP_PAUSE, DP_CHARGE, DP_MODE, DP_LOCATE,
    DP_COMMAND_TRANS, SUCTION_LEVELS,
    MODE_ROOM, MODE_SMART, MODE_CHARGE,
)
from .coordinator import TuyaVacuumCoordinator

# Fixed protocol frames (from reverse engineering)
_WAKE  = "qgAGTQE7msoD8A=="
_SYNC  = "qgACVwFYqgADVQEAVqoAAzkBADqqAAMTAQAUqgADUwEAVA=="
_ROOM_CELL = [0x00, 0x04, 0x08, 0x0C, 0x10]

STATUS_MAP = {
    "standby":     VacuumActivity.IDLE,
    "charging":    VacuumActivity.DOCKED,
    "charge_done": VacuumActivity.DOCKED,
    "cleaning":    VacuumActivity.CLEANING,
    "smart":       VacuumActivity.CLEANING,
    "selectroom":  VacuumActivity.CLEANING,
    "zone_clean":  VacuumActivity.CLEANING,
    "goto_pos":    VacuumActivity.CLEANING,
    "paused":      VacuumActivity.PAUSED,
    "pause":       VacuumActivity.PAUSED,
    "goto_charge": VacuumActivity.RETURNING,
    "repositing":  VacuumActivity.RETURNING,
    "fault":       VacuumActivity.ERROR,
}

FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.STATUS
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.SEND_COMMAND
    | VacuumEntityFeature.STATE
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TuyaVacuumCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TuyaVacuumEntity(coordinator, entry)])


class TuyaVacuumEntity(CoordinatorEntity, StateVacuumEntity):
    """Vacuum entity that acts as a proxy for advanced commands."""
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = FEATURES
    _attr_fan_speed_list = SUCTION_LEVELS

    def __init__(self, coordinator: TuyaVacuumCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_vacuum"
        self._entry = entry

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title or "Tuya Vacuum",
            "manufacturer": "Tuya",
        }

    @property
    def available(self) -> bool:
        """Return True if the target TuyaLocal entity is available, otherwise assume True."""
        tuya_local_id = self._entry.options.get("tuya_local_entity")
        if tuya_local_id:
            state = self.hass.states.get(tuya_local_id)
            if state:
                return state.state != "unavailable"
        return True

    # ── State ──────────────────────────────────────────────────

    def _get_target_state(self):
        """Helper to get the state of the associated TuyaLocal entity."""
        tuya_local_id = self._entry.options.get("tuya_local_entity")
        if tuya_local_id:
            return self.hass.states.get(tuya_local_id)
        return None

    @property
    def activity(self) -> VacuumActivity:
        """Return the current activity, primarily from the TuyaLocal entity."""
        target_state = self._get_target_state()
        if target_state:
            # Try to map TuyaLocal string state to VacuumActivity
            st = target_state.state
            if st in ["cleaning", "returning", "docked", "idle", "paused", "error"]:
                # If TuyaLocal uses modern string states
                try: return VacuumActivity(st)
                except ValueError: pass

            # Fallback to our internal map just in case
            return STATUS_MAP.get(st, VacuumActivity.IDLE)

        # Fallback to cloud data if no TuyaLocal entity is configured
        st = (self.coordinator.data or {}).get("status", "unknown")
        return STATUS_MAP.get(st, VacuumActivity.IDLE)

    @property
    def battery_level(self) -> int | None:
        """Return the battery level from TuyaLocal (if available) or cloud status."""
        target_state = self._get_target_state()
        if target_state and "battery_level" in target_state.attributes:
            return target_state.attributes["battery_level"]
        return (self.coordinator.data or {}).get("battery")


    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes from cloud status."""
        d = self.coordinator.data or {}
        rooms = self._entry.options.get("rooms", self._entry.data.get("rooms", {}))
        return {
            "mode":       d.get("mode"),
            "water":      d.get("water"),
            "clean_time": d.get("clean_time"),
            "clean_area": d.get("clean_area"),
            "current_room": d.get("current_room"),
            "fault_code": d.get("fault"),
            "rooms":      rooms,
            "integration": "Companion for TuyaLocal",
        }

    # ── Basic services ─────────────────────────────────────────

    async def async_start(self) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.send_multiple, {DP_POWER: True, DP_MODE: MODE_SMART}
        )

    async def async_pause(self) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.send_dp, DP_PAUSE, True
        )

    async def async_stop(self, **kwargs) -> None:
        await self.async_pause()

    async def async_return_to_base(self, **kwargs) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.send_dp, DP_CHARGE, True
        )

    async def async_locate(self, **kwargs) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.send_dp, 11, True
        )

    async def async_set_fan_speed(self, fan_speed: str, **kwargs) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.send_dp, 9, fan_speed
        )

    # ── send_command — advanced room/zone/spot control ─────────

    async def async_send_command(self, command: str, params: dict | None = None) -> None:
        """
        Supported commands:

        clean_rooms   params: {rooms: [0,1,2], suction: [3,2,1], water: [2,0,1], passes: [1,2,1]}
        clean_preset  params: {preset: "intensiva", rooms: [0,1,2]}
        clean_zone    params: {corners: [[x1,y1,x2,y2,...]], suction: 2, water: 1, passes: 1}
        clean_spot    params: {x: -88, y: -660, suction: 2, water: 1}
        resume        (clear fault)
        """
        params = params or {}
        
        # Handle carpet boost DP if provided
        if "carpet_boost" in params:
            # Placeholder DP for carpet boost - needs verification for specific model
            # For now we just log it as we don't have the confirmed DP ID
            _LOGGER.debug("Carpet boost requested: %s", params["carpet_boost"])
        if command == "clean_rooms":
            await self.hass.async_add_executor_job(
                self._do_clean_rooms, params
            )
        elif command == "clean_preset":
            await self.hass.async_add_executor_job(
                self._do_preset, params
            )
        elif command == "clean_zone":
            await self.hass.async_add_executor_job(
                self._do_zone, params
            )
        elif command == "clean_spot":
            await self.hass.async_add_executor_job(
                self._do_spot, params
            )
        elif command == "resume":
            frame = _aa(0x4C, [])
            await self.hass.async_add_executor_job(
                self.coordinator.send_dp15, _b64(frame)
            )

    # ── Internal command builders ──────────────────────────────

    def _do_clean_rooms(self, params: dict) -> None:
        c  = self.coordinator
        rooms    = [int(x) for x in params.get("rooms", [0,1,2,3,4])]
        suctions = [_parse_int_or_none(x) for x in _pad(params.get("suction"), len(rooms), None)]
        waters   = [_parse_int_or_none(x) for x in _pad(params.get("water"),   len(rooms), None)]
        passes   = [_parse_int_or_none(x) or 1 for x in _pad(params.get("passes"),  len(rooms), 1)]

        room_templates = self._entry.data.get("room_templates", {})
        
        # Build the sequence for a single persistent connection
        sequence = [
            (DP_COMMAND_TRANS, _WAKE),
            (DP_COMMAND_TRANS, _SYNC),
        ]
        
        for i, rid in enumerate(rooms):
            frame = _build_room(rid, suctions[i], waters[i], passes[i], room_templates)
            sequence.append((DP_COMMAND_TRANS, _b64(frame)))

        sequence.append((DP_COMMAND_TRANS, _b64(_aa(0x27, [0x01, len(rooms)] + list(rooms)))))
        sequence.append({DP_POWER: True, DP_MODE: MODE_ROOM})

        c.send_sequence(sequence)

    def _do_preset(self, params: dict) -> None:
        presets = {
            "wee-dry":     (2, 3, 1),
            "aspirazione": (2, 0, 1),
            "silenziosa":  (1, 1, 1),
            "intensiva":   (4, 3, 5),
        }
        name = params.get("preset", "aspirazione").lower()
        suc, wat, pas = presets.get(name, (2, 0, 1))
        rooms = params.get("rooms", [0,1,2,3,4])
        self._do_clean_rooms({
            "rooms": rooms,
            "suction": [suc]*len(rooms),
            "water":   [wat]*len(rooms),
            "passes":  [pas]*len(rooms),
        })

    def _do_zone(self, params: dict) -> None:
        raw_corners = params.get("corners", [])
        if not raw_corners:
            return
            
        suc  = params.get("suction", 2)
        wat  = params.get("water",   0)
        pas  = params.get("passes",  1)
        car  = params.get("carpet",  0)
        
        zones_config = []
        
        # Handle both our internal format [[(x,y), ...]] and Xiaomi Map Card format [[x1,y1,x2,y2], ...]
        for z in raw_corners:
            if len(z) == 4 and not isinstance(z[0], (list, tuple)):
                # Xiaomi format: bounding box [x1, y1, x2, y2]
                x1, y1, x2, y2 = z
                corners = [(x1,y1), (x2,y1), (x2,y2), (x1,y2)]
            else:
                # Fallback / internal format
                corners = [tuple(c) for c in z]
                
            zones_config.append({
                "corners": corners, "suction": suc, "water": wat,
                "passes": pas, "carpet": car
            })

        if not zones_config:
            return

        c = self.coordinator
        sequence = [
            (DP_COMMAND_TRANS, _SYNC),
            (DP_COMMAND_TRANS, _b64(_zone_bundle(zones_config))),
            {DP_POWER: True, DP_MODE: "zone"}
        ]
        c.send_sequence(sequence)

    def _do_spot(self, params: dict) -> None:
        x   = int(params.get("x", 0))
        y   = int(params.get("y", 0))
        suc = params.get("suction", 2)
        wat = params.get("water",   0)
        
        c = self.coordinator
        sequence = [
            (DP_COMMAND_TRANS, _SYNC),
            (DP_COMMAND_TRANS, _b64(_spot_bundle(x, y, suc, wat))),
            {DP_POWER: True, DP_MODE: "pose"}
        ]
        c.send_sequence(sequence)


# ── Frame helpers ─────────────────────────────────────────────────

def _checksum(d: bytes) -> int: return sum(d) & 0xFF
def _aa(cmd: int, payload) -> bytes:
    data = bytes([cmd]+list(payload))
    return bytes([0xAA, 0x00, len(data)]) + data + bytes([_checksum(data)])
def _b64(b: bytes) -> str: return base64.b64encode(b).decode()
def _parse_int_or_none(v):
    try: return int(v)
    except (ValueError, TypeError): return None
def _pad(val, n, default):
    if val is None: return [default]*n
    if isinstance(val, (int, str)): return [val]*n
    v = list(val)
    return (v*n)[:n] if len(v)==1 else v

def _build_room(room_id, suction, water, passes, templates) -> bytes:
    tpl = templates.get(str(room_id))
    if tpl:
        frame = bytearray(bytes.fromhex(tpl.replace(" ","")))
        # Search for structural marker [0x05, 0x00] to find settings offset
        # Block is typically: [room_id] [05] [00] [b1] [b2] [passes] [suction] [water] [01] [00]
        try:
            idx = frame.index(b"\x05\x00", 3) # start search after header
            if passes and passes != 1: frame[idx+4] = passes
            if suction is not None:    frame[idx+5] = suction
            if water   is not None:    frame[idx+6] = water
        except (ValueError, IndexError):
            # Fallback to hardcoded offsets if marker not found
            if passes and passes != 1: frame[11] = passes
            if suction is not None:    frame[12] = suction
            if water   is not None:    frame[13] = water
        
        frame[-1] = _checksum(frame[3:-1])
        return bytes(frame)
    # Fallback generic frame
    payload = [0x01, 0x01, room_id, 0x05, 0x00, 0x00, 0x02,
               passes or 1,
               suction if suction is not None else 0xFF,
               water   if water   is not None else 0xFF,
               0x01, 0x00]
    return _aa(0x51, payload)

def _zone_bundle(zones) -> bytes:
    payload = [0x01, len(zones)]
    for z in zones:
        corners = z["corners"]
        payload.append(len(corners))
        for x, y in corners:
            payload += list(struct.pack(">hh", int(x), int(y)))
        payload += [0x05, 0x00, 0x00, 0x00,
                    z.get("passes",1), z.get("suction",2), z.get("water",0),
                    0xFF, 0x00, 0xFF, z.get("carpet",0)]
    b  = _aa(0x57, [0x01])
    b += _aa(0x55, payload)
    b += _aa(0x39, [0x01, 0x00])
    b += _aa(0x13, [0x01, 0x00])
    b += _aa(0x53, [0x01, 0x00])
    return b

def _spot_bundle(x, y, suc, wat) -> bytes:
    payload = [0x01] + list(struct.pack(">hh", x, y)) + [
        0x05,0x00,0x00,0x00, 1, suc, wat, 0xFF,0xFF,0xFF,0x01]
    b  = _aa(0x57, payload)
    b += _aa(0x55, [0x01, 0x00])
    b += _aa(0x39, [0x01, 0x00])
    b += _aa(0x13, [0x01, 0x00])
    b += _aa(0x53, [0x01, 0x00])
    return b
