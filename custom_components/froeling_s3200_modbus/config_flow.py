import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN

# Erstanlage (UI-Flow) + Options-Flow (nachträgliche Konfiguration)

@config_entries.HANDLERS.register(DOMAIN)
class FroelingModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            # Alles als entry.data speichern
            return self.async_create_entry(title=user_input["name"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("name", default="Froeling"): str,
                vol.Required("host"): str,
                vol.Required("port", default=502): int,
                vol.Optional("unit_id", default=2): int,
                vol.Required("update_interval", default=60): int,
                vol.Optional("kessel", default=True): bool,
                vol.Optional("boiler01", default=True): bool,
                vol.Optional("hk01", default=True): bool,
                vol.Optional("hk02", default=True): bool,
                vol.Optional("austragung", default=True): bool,
                vol.Optional("puffer01", default=True): bool,
                vol.Optional("zirkulationspumpe", default=True): bool,
            })
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return FroelingOptionsFlow(config_entry)


class FroelingOptionsFlow(config_entries.OptionsFlow):
    """Options flow to reconfigure without removing the entry."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        # aktuelle Werte: options > data
        cfg = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            # nur als Optionen speichern (entry.options)
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema({
            vol.Optional("unit_id", default=cfg.get("unit_id", 2)): int,
            vol.Optional("update_interval", default=cfg.get("update_interval", 60)): int,
            vol.Optional("kessel", default=cfg.get("kessel", True)): bool,
            vol.Optional("boiler01", default=cfg.get("boiler01", True)): bool,
            vol.Optional("hk01", default=cfg.get("hk01", True)): bool,
            vol.Optional("hk02", default=cfg.get("hk02", True)): bool,
            vol.Optional("austragung", default=cfg.get("austragung", True)): bool,
            vol.Optional("puffer01", default=cfg.get("puffer01", True)): bool,
            vol.Optional("zirkulationspumpe", default=cfg.get("zirkulationspumpe", True)): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
