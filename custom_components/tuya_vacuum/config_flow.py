"""Config flow for Tuya Vacuum Local."""
from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import (
    DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_IP, CONF_DEVICE_KEY,
    CONF_DEVICE_VERSION, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION,
)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID):                   str,
    vol.Required(CONF_DEVICE_IP):                   str,
    vol.Required(CONF_DEVICE_KEY):                  str,
    vol.Optional(CONF_DEVICE_VERSION, default=3.3): vol.Coerce(float),
    vol.Optional(CONF_CLIENT_ID,      default=""):  str,
    vol.Optional(CONF_CLIENT_SECRET,  default=""):  str,
    vol.Optional(CONF_REGION,         default="eu"):
        vol.In(["eu", "us", "cn", "in"]),
})

class TuyaVacuumConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Basic validation: try connecting
            try:
                import tinytuya
                d = tinytuya.Device(
                    user_input[CONF_DEVICE_ID],
                    user_input[CONF_DEVICE_IP],
                    user_input[CONF_DEVICE_KEY],
                    version=user_input[CONF_DEVICE_VERSION],
                )
                d.set_socketTimeout(5)
                st = await self.hass.async_add_executor_job(d.status)
                if not st or "dps" not in st:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Vacuum {user_input[CONF_DEVICE_IP]}",
                        data=user_input,
                    )
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "docs_url": "https://github.com/Tkd-Alex/tuya-vacuum-local"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TuyaVacuumOptionsFlow(config_entry)

class TuyaVacuumOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # Reconstruct the rooms dictionary
            rooms = {
                "0": user_input.pop("room_0_name"),
                "1": user_input.pop("room_1_name"),
                "2": user_input.pop("room_2_name"),
                "3": user_input.pop("room_3_name"),
                "4": user_input.pop("room_4_name"),
            }
            # Add rooms back to user_input
            user_input["rooms"] = rooms
            return self.async_create_entry(title="", data=user_input)
        
        # Get existing rooms or defaults
        rooms = self._entry.data.get("rooms", {})
        
        schema = vol.Schema({
            vol.Optional("tuya_local_entity", default=self._entry.options.get("tuya_local_entity", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="vacuum", integration="tuya_local")
            ),
            vol.Optional(CONF_CLIENT_ID,
                default=self._entry.data.get(CONF_CLIENT_ID, "")): str,
            vol.Optional(CONF_CLIENT_SECRET,
                default=self._entry.data.get(CONF_CLIENT_SECRET, "")): str,
            vol.Optional(CONF_REGION,
                default=self._entry.data.get(CONF_REGION, "eu")):
                vol.In(["eu", "us", "cn", "in"]),
            
            # Room name mapping (ID 0-4)
            vol.Optional("room_0_name", default=rooms.get("0", "Living Room")): str,
            vol.Optional("room_1_name", default=rooms.get("1", "Kitchen")): str,
            vol.Optional("room_2_name", default=rooms.get("2", "Bedroom")): str,
            vol.Optional("room_3_name", default=rooms.get("3", "Bathroom")): str,
            vol.Optional("room_4_name", default=rooms.get("4", "Hallway")): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
