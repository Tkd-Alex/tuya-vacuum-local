"""Tuya Vacuum Local — Home Assistant integration."""
from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .coordinator import TuyaVacuumCoordinator

PLATFORMS = ["vacuum", "image", "sensor", "select"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TuyaVacuumCoordinator(hass, dict(entry.data))
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register custom services
    async def handle_clean_room(call):
        room_name = call.data.get("room_name")
        suction   = call.data.get("suction")
        water     = call.data.get("water")
        
        # Find room ID by name
        rooms = entry.data.get("rooms", {})
        room_id = next((rid for rid, name in rooms.items() if name == room_name), None)
        
        if room_id is not None:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(hass)
            # Find the vacuum entity belonging to this config entry
            entities = er.async_entries_for_config_entry(registry, entry.entry_id)
            vacuum_entity = next((e for e in entities if e.domain == "vacuum"), None)

            if vacuum_entity:
                params = {"rooms": [int(room_id)]}
                if suction: params["suction"] = [suction]
                if water:   params["water"]   = [water]

                await hass.services.async_call("vacuum", "send_command", {
                    "entity_id": vacuum_entity.entity_id,
                    "command": "clean_rooms",
                    "params": params
                })
            else:
                _LOGGER.error("Could not find vacuum entity for entry %s", entry.entry_id)

    async def handle_refresh_map(call):
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await hass.async_add_executor_job(coordinator.update_map)

    hass.services.async_register(DOMAIN, "clean_room_by_name", handle_clean_room)
    hass.services.async_register(DOMAIN, "refresh_map", handle_refresh_map)

    # Initial map fetch to avoid 500 error on startup
    hass.async_add_executor_job(coordinator.update_map)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok
