"""Data coordinator for Tuya Vacuum Local."""
from __future__ import annotations

import base64, hashlib, hmac, io, json, logging, struct, time
import requests as req
from datetime import timedelta
from typing import Any

import tinytuya

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID, CONF_DEVICE_IP, CONF_DEVICE_KEY, CONF_DEVICE_VERSION,
    CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION,
    DOMAIN, REGIONS, UPDATE_INTERVAL,
    DP_BATTERY, DP_STATUS, DP_MODE, DP_SUCTION, DP_WATER,
    DP_CLEAN_TIME, DP_CLEAN_AREA, DP_REQUEST, DP_COMMAND_TRANS, DP_FAULT,
    DP_TOTAL_AREA, DP_TOTAL_COUNT, DP_TOTAL_TIME,
    DP_EDGE_BRUSH, DP_ROLL_BRUSH, DP_FILTER, DP_DUST_CLOTH,
)

_LOGGER = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class TuyaVacuumCoordinator(DataUpdateCoordinator):
    """Manages communication with the vacuum robot."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self._config       = config
        self._map_image: bytes | None = None
        self._token_cache  = {"token": None, "expiry": 0.0}
        self._last_map_refresh = 0.0
        self._last_status      = "unknown"


    # ── Cloud-based polling ───────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Manual update or event-driven update for the map. Status polling is disabled in Companion mode."""
        await self._async_check_cloud_templates()
        return {}

    # ── Stateless & Persistent connections ────────────────────────

    def _get_device(self, persistent: bool = False):
        """Create a device instance."""
        d = tinytuya.Device(
            self._config[CONF_DEVICE_ID],
            self._config[CONF_DEVICE_IP],
            self._config[CONF_DEVICE_KEY],
            version=float(self._config.get(CONF_DEVICE_VERSION, 3.3)),
        )
        d.set_socketTimeout(5)
        d.set_socketPersistent(persistent)
        return d

    def send_dp(self, dp: int, value: Any) -> None:
        """Connect, send DP, and disconnect."""
        d = self._get_device(persistent=False)
        result = d.set_value(dp, value)
        if result and result.get("Error"):
            _LOGGER.warning("send_dp %s=%s error: %s", dp, value, result)

    def send_multiple(self, values: dict) -> None:
        """Connect, send multiple DPs, and disconnect."""
        d = self._get_device(persistent=False)
        result = d.set_multiple_values(values)
        if result and result.get("Error"):
            _LOGGER.warning("send_multiple %s error: %s", values, result)

    def send_sequence(self, sequence: list) -> None:
        """Execute a sequence of DP commands over a single persistent connection."""
        # Request TuyaLocal to temporarily release the socket
        tuya_local_entity = self._config.get("tuya_local_entity")
        if tuya_local_entity:
            from homeassistant.helpers import entity_registry as er
            import asyncio
            registry = er.async_get(self.hass)
            entry = registry.async_get(tuya_local_entity)
            if entry and entry.config_entry_id:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.hass.config_entries.async_reload(entry.config_entry_id),
                        self.hass.loop
                    ).result(timeout=3)
                    time.sleep(1.0)  # wait for TuyaLocal to release the socket
                except Exception as e:
                    _LOGGER.debug("Failed to reload TuyaLocal: %s", e)

        d = self._get_device(persistent=True)
        try:
            for item in sequence:
                for attempt in range(3):
                    if isinstance(item, dict):
                        result = d.set_multiple_values(item)
                    else:
                        dp, val = item
                        result = d.set_value(dp, val)
                    
                    if not result or not result.get("Error"):
                        break
                        
                    if attempt == 2:
                        _LOGGER.warning("send_sequence step %s error after 3 attempts: %s", item, result)
                    else:
                        time.sleep(0.1)
                time.sleep(0.08)
        except Exception as exc:
            _LOGGER.error("send_sequence failed: %s", exc)
            raise
        finally:
            d.close()
            _LOGGER.debug("send_sequence completed, connection released")

    def send_dp15(self, b64: str) -> None:
        """Connect, send raw DP15, and disconnect."""
        self.send_dp(DP_COMMAND_TRANS, b64)

    # ── Map fetching ──────────────────────────────────────────────

    def _cloud_sign(self, method: str, path: str, token: str = "") -> dict:
        cfg = self._config
        cid = cfg[CONF_CLIENT_ID]
        cs  = cfg[CONF_CLIENT_SECRET]
        ts  = str(int(time.time() * 1000))
        bh  = hashlib.sha256(b"").hexdigest()
        s2s = "\n".join([method, bh, "", path])
        msg = cid + (token or "") + ts + s2s
        sg  = hmac.new(key=cs.encode(), msg=msg.encode(),
                       digestmod=hashlib.sha256).hexdigest().upper()
        return {"client_id": cid, "sign": sg, "t": ts,
                "sign_method": "HMAC-SHA256", "access_token": token or ""}

    def _get_cloud_token(self) -> str:
        import requests
        if time.time() < self._token_cache["expiry"] - 60 and self._token_cache["token"]:
            return self._token_cache["token"]
        region = self._config.get(CONF_REGION, "eu")
        base   = REGIONS.get(region, REGIONS["eu"])
        path   = "/v1.0/token?grant_type=1"
        r = requests.get(base + path, headers=self._cloud_sign("GET", path),
                         timeout=10).json()
        if not r.get("success"):
            raise RuntimeError(f"Cloud token error: {r}")
        self._token_cache["token"]  = r["result"]["access_token"]
        self._token_cache["expiry"] = time.time() + r["result"]["expire_time"]
        return self._token_cache["token"]

    def fetch_and_render_map(self) -> tuple[bytes | None, dict | None]:
        """Download latest map from Tuya Cloud and render as PNG bytes."""
        import requests as req
        if not HAS_PIL:
            _LOGGER.warning("Pillow not installed — map rendering disabled")
            return None, None

        cfg    = self._config
        did    = cfg[CONF_DEVICE_ID]
        region = cfg.get(CONF_REGION, "eu")
        base   = REGIONS.get(region, REGIONS["eu"])
        token  = self._get_cloud_token()

        def api_get(path):
            return req.get(base + path,
                           headers=self._cloud_sign("GET", path, token),
                           timeout=15).json()

        # Try realtime first, then latest stored
        result = api_get(f"/v1.0/users/sweepers/file/{did}/realtime-map")
        layout_raw = path_raw = None

        if result.get("success") and result.get("result"):
            maps = result["result"]
            for m in maps:
                url = m.get("map_url", "")
                if not url: continue
                data = req.get(url, timeout=30).content
                if m.get("map_type") == 0: layout_raw = data
                elif m.get("map_type") == 1: path_raw = data
        else:
            # Fall back to stored file
            r2 = api_get(f"/v1.0/users/sweepers/file/{did}/list?file_type=pic&page_no=1&page_size=1")
            if r2.get("success") and r2.get("result", {}).get("datas"):
                fid = r2["result"]["datas"][0]["id"]
                r3  = api_get(f"/v1.0/users/sweepers/file/{did}/download?id={fid}")
                res = r3.get("result", {})
                for key, attr in [("app_map", "layout_raw"), ("robot_map", "path_raw")]:
                    url = res.get(key)
                    if url:
                        data = req.get(url, timeout=30).content
                        if attr == "layout_raw": layout_raw = data
                        else: path_raw = data

        if not layout_raw:
            _LOGGER.warning("No layout map available from Tuya Cloud")
            return None

        return self._render_map(layout_raw, path_raw)

    def _render_map(self, layout_raw: bytes, path_raw: bytes | None) -> tuple[bytes | None, dict | None]:
        """Decode LZ4 map and render PNG — returns (PNG bytes, map_data dict)."""
        try:
            from .map_decoder import decode_and_render
            configured_rooms = self._config.get("rooms", {})
            return decode_and_render(layout_raw, path_raw, configured_rooms=configured_rooms)
        except Exception as e:
            _LOGGER.error("Map render error: %s", e)
            return None, None

    @property
    def map_image(self) -> bytes | None:
        return self._map_image

    @property
    def map_data(self) -> dict | None:
        """Return map calibration and room data."""
        return getattr(self, "_map_data", {})

    def update_map(self) -> None:
        """Called after cleaning ends — fetch and cache the new map."""
        img, map_data = self.fetch_and_render_map() or (None, None)
        if img:
            self._map_image = img
            self._map_data = map_data
            _LOGGER.info("Map updated (%d bytes)", len(img))

    def _extract_templates_from_dps(self, raw: bytes) -> dict[str, str]:
        """Extract room templates from CMD 0x51 or CMD 0x53 frames."""
        templates = {}
        i = 0
        while i < len(raw):
            if raw[i] != 0xAA or i + 3 >= len(raw):
                i += 1
                continue
            length = (raw[i+1] << 8) | raw[i+2]
            end = i + 3 + length
            if end > len(raw):
                i += 1
                continue
            frame = raw[i:end]
            cmd = frame[3]

            # Parse CMD 0x51 (Room configuration command)
            if cmd == 0x51 and len(frame) >= 6:
                num_rooms = frame[5]
                for r in range(num_rooms):
                    bs = 6 + r * 10
                    be = bs + 10
                    if be > len(frame):
                        break
                    block = frame[bs:be]
                    room_id = block[0]
                    if block[1] != 0x05 or block[2] != 0x00:
                        continue
                    # Reconstruct a single-room CMD 0x51 frame
                    payload = bytes([0x51, 0x01, 0x01]) + bytes(block)
                    cs = sum(payload) & 0xFF
                    single_frame = bytes([0xAA, 0x00, len(payload)]) + payload + bytes([cs])
                    templates[str(room_id)] = single_frame.hex()
                    _LOGGER.debug("Extracted room template from 0x51: room_id=%d", room_id)

            # Parse CMD 0x53 (Room status report)
            elif cmd == 0x53 and len(frame) >= 6:
                num_rooms = frame[5]
                # CMD 0x53 has 12-byte blocks: [room_id] 05 00 [b1] [b2] [passes] [suction] [water] FF 00 FF 01
                for r in range(num_rooms):
                    bs = 6 + r * 12
                    be = bs + 12
                    if be > len(frame):
                        break
                    block = frame[bs:be]
                    room_id = block[0]
                    if block[1] != 0x05 or block[2] != 0x00:
                        continue
                    # Reconstruct a 10-byte block for CMD 0x51: first 8 bytes from block + 01 00
                    block_51 = block[0:8] + bytes([0x01, 0x00])
                    payload = bytes([0x51, 0x01, 0x01]) + block_51
                    cs = sum(payload) & 0xFF
                    single_frame = bytes([0xAA, 0x00, len(payload)]) + payload + bytes([cs])
                    templates[str(room_id)] = single_frame.hex()
                    _LOGGER.debug("Extracted room template from 0x53: room_id=%d b1=0x%02X b2=0x%02X",
                                  room_id, block[3], block[4])
            i = end

        return templates

    def _cloud_fetch_and_extract_templates(self) -> dict[str, str]:
        """Fetch recent DP15 logs from Tuya Cloud and extract room templates."""
        did = self._config[CONF_DEVICE_ID]
        region = self._config.get(CONF_REGION, "eu")
        base = REGIONS.get(region, REGIONS["eu"])
        try:
            token = self._get_cloud_token()
        except Exception as e:
            _LOGGER.error("Failed to get cloud token: %s", e)
            return {}

        now_ms = int(time.time() * 1000)
        # Query logs from the last 2 hours (enough to capture any active clean session)
        start_ms = now_ms - (2 * 3600 * 1000)
        
        # Sort keys alphabetically for the signature
        params = {
            "codes": "command_trans",
            "end_time": now_ms,
            "size": 50,
            "start_time": start_ms,
            "type": 7
        }
        sorted_keys = sorted(params.keys())
        query_str = "&".join(f"{k}={params[k]}" for k in sorted_keys)
        path = f"/v1.0/devices/{did}/logs?{query_str}"

        try:
            r = req.get(
                base + path,
                headers=self._cloud_sign("GET", path, token),
                timeout=15
            ).json()
            if not r.get("success"):
                _LOGGER.error("Failed to fetch logs from Tuya Cloud: %s", r)
                return {}
            logs = r.get("result", {}).get("logs", [])
            
            templates = {}
            for log in logs:
                if log.get("code") == "command_trans" and log.get("value"):
                    try:
                        raw = base64.b64decode(log["value"])
                        extracted = self._extract_templates_from_dps(raw)
                        if extracted:
                            templates.update(extracted)
                    except Exception as ex:
                        _LOGGER.debug("Failed to parse log entry: %s", ex)
            return templates
        except Exception as e:
            _LOGGER.error("Error fetching DP15 logs from Tuya Cloud: %s", e)
            return {}

    async def _async_check_cloud_templates(self) -> None:
        """Query Tuya Cloud DP15 logs and extract templates if missing."""
        if not self._config.get(CONF_CLIENT_ID) or not self._config.get(CONF_CLIENT_SECRET):
            return

        # Find our config entry
        entry = None
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.data.get(CONF_DEVICE_ID) == self._config.get(CONF_DEVICE_ID):
                entry = e
                break
        if not entry:
            return

        rooms = entry.options.get("rooms", entry.data.get("rooms", {}))
        room_templates = entry.options.get("room_templates", entry.data.get("room_templates", {}))
        missing = [rid for rid in rooms if str(rid) not in room_templates]
        
        if not missing:
            return

        # Check if the vacuum is cleaning
        tuya_local_id = entry.options.get("tuya_local_entity")
        is_cleaning = False
        if tuya_local_id:
            state = self.hass.states.get(tuya_local_id)
            if state:
                is_cleaning = state.state in ["cleaning", "returning", "error", "selectroom", "zone_clean", "goto_pos"]

        if not is_cleaning:
            return

        _LOGGER.debug("Vacuum is cleaning and missing room template(s) %s. Querying cloud logs...", missing)

        # Call executor to fetch logs and parse templates
        templates = await self.hass.async_add_executor_job(self._cloud_fetch_and_extract_templates)
        if templates:
            # Filter templates to only include new ones
            new_templates = {k: v for k, v in templates.items() if k not in room_templates}
            if new_templates:
                _LOGGER.info("Found new room templates in cloud logs: %s", list(new_templates.keys()))
                existing = dict(room_templates)
                existing.update(new_templates)
                new_options = dict(entry.options)
                new_options["room_templates"] = existing
                
                # Update config entry options. This will trigger entry reload.
                self.hass.config_entries.async_update_entry(entry, options=new_options)


