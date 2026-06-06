"""Data coordinator for Tuya Vacuum Local."""
from __future__ import annotations

import base64, hashlib, hmac, io, json, logging, struct, time
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
    DP_CLEAN_TIME, DP_CLEAN_AREA, DP_REQUEST, DP_COMMAND_TRANS,
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
            # No update interval — we don't poll to avoid TCP conflicts
            update_interval=None,
        )
        self._config       = config
        self._map_image: bytes | None = None
        self._token_cache  = {"token": None, "expiry": 0.0}

    # ── Stateless connections ─────────────────────────────────────

    def _get_one_shot_device(self):
        """Create a device instance that closes the socket immediately."""
        d = tinytuya.Device(
            self._config[CONF_DEVICE_ID],
            self._config[CONF_DEVICE_IP],
            self._config[CONF_DEVICE_KEY],
            version=float(self._config.get(CONF_DEVICE_VERSION, 3.3)),
        )
        d.set_socketTimeout(5)
        d.set_socketPersistent(False)
        return d

    async def _async_update_data(self) -> dict[str, Any]:
        """Manual update or event-driven update for the map."""
        return {}

    # ── Vacuum commands (one-shot) ────────────────────────────────

    def send_dp(self, dp: int, value: Any) -> None:
        """Connect, send DP, and disconnect."""
        d = self._get_one_shot_device()
        d.set_value(dp, value)

    def send_multiple(self, values: dict) -> None:
        """Connect, send multiple DPs, and disconnect."""
        d = self._get_one_shot_device()
        d.set_multiple_values(values)

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
        sg  = hmac.new(cs.encode(), msg=msg.encode(),
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

    def fetch_and_render_map(self) -> bytes | None:
        """Download latest map from Tuya Cloud and render as PNG bytes."""
        import requests as req
        if not HAS_PIL:
            _LOGGER.warning("Pillow not installed — map rendering disabled")
            return None

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

    def _render_map(self, layout_raw: bytes, path_raw: bytes | None) -> bytes | None:
        """Decode LZ4 map and render PNG — returns PNG bytes."""
        try:
            from .map_decoder import decode_and_render
            return decode_and_render(layout_raw, path_raw)
        except Exception as e:
            _LOGGER.error("Map render error: %s", e)
            return None

    @property
    def map_image(self) -> bytes | None:
        return self._map_image

    def update_map(self) -> None:
        """Called after cleaning ends — fetch and cache the new map."""
        img = self.fetch_and_render_map()
        if img:
            self._map_image = img
            _LOGGER.info("Map updated (%d bytes)", len(img))
