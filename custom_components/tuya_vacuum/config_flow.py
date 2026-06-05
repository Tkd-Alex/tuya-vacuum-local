"""Config flow for Tuya Vacuum Local."""
from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
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
            return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema({
            vol.Optional(CONF_CLIENT_ID,
                default=self._entry.data.get(CONF_CLIENT_ID, "")): str,
            vol.Optional(CONF_CLIENT_SECRET,
                default=self._entry.data.get(CONF_CLIENT_SECRET, "")): str,
            vol.Optional(CONF_REGION,
                default=self._entry.data.get(CONF_REGION, "eu")):
                vol.In(["eu", "us", "cn", "in"]),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
