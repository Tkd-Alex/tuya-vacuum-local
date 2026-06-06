"""Select platform for Tuya Vacuum Local."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUCTION_LEVELS, WATER_LEVELS
from .coordinator import TuyaVacuumCoordinator

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TuyaVacuumCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        TuyaVacuumPresetSelect(coordinator, entry),
    ]
    
    async_add_entities(entities)

class TuyaVacuumPresetSelect(CoordinatorEntity, SelectEntity):
    """Select entity for cleaning presets."""
    _attr_has_entity_name = True
    _attr_name = "Cleaning Preset"
    _attr_icon = "mdi:robot-vacuum"
    
    _PRESETS = {
        "Eco":     {"suction": "gentle", "water": "low"},
        "Normal":  {"suction": "normal", "water": "middle"},
        "Intensive":{"suction": "strong_plus", "water": "high"},
        "Dry":     {"suction": "normal", "water": "closed"},
    }

    def __init__(self, coordinator: TuyaVacuumCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_preset_select"
        self._attr_options = list(self._PRESETS.keys())
        self._attr_current_option = "Normal"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        
        # When a preset is selected, we could optionally update the robot immediately
        # or just leave it for the next 'start' command. 
        # For now, let's just log it.
        settings = self._PRESETS.get(option)
        if settings:
            # Optionally send global DPs for suction/water
            pass
