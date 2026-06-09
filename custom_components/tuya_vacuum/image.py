"""Map image entity for Tuya Vacuum Local."""
from __future__ import annotations
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .coordinator import TuyaVacuumCoordinator

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TuyaVacuumMapImage(coordinator, entry)])

class TuyaVacuumMapImage(ImageEntity):
    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_content_type = "image/png"

    def __init__(self, coordinator: TuyaVacuumCoordinator, entry: ConfigEntry):
        super().__init__(coordinator.hass)
        self._coordinator  = coordinator
        self._attr_unique_id = f"{entry.entry_id}_map"
        self._image_last_updated = dt_util.utcnow()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title or "Tuya Vacuum",
            "manufacturer": "Tuya",
        }

    @property
    def extra_state_attributes(self) -> dict:
        """Return map calibration and room coordinates for UI extensions."""
        return self._coordinator.map_data or {}

    async def async_image(self) -> bytes | None:
        return self._coordinator.map_image

    async def async_update_map(self) -> None:
        """Fetch and render latest map (called by automation after cleaning)."""
        await self.hass.async_add_executor_job(self._coordinator.update_map)
        self._image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()
