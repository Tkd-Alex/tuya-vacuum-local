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
        # Find room ID by name
        rooms = entry.data.get("rooms", {})
        room_id = next((rid for rid, name in rooms.items() if name == room_name), None)
        if room_id is not None:
            # Get the vacuum entity for this entry
            # (Simplification: assuming one vacuum per entry)
            for entity_id in hass.states.async_entity_ids("vacuum"):
                state = hass.states.get(entity_id)
                if state and state.attributes.get("unique_id") == f"{entry.entry_id}_vacuum":
                    await hass.services.async_call("vacuum", "send_command", {
                        "entity_id": entity_id,
                        "command": "clean_rooms",
                        "params": {"rooms": [int(room_id)]}
                    })
                    break

    hass.services.async_register(DOMAIN, "clean_room_by_name", handle_clean_room)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok
