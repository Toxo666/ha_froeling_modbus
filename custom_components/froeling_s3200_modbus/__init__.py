from __future__ import annotations

import asyncio
import logging
import pymodbus
from pymodbus.client import ModbusTcpClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr, entity_registry as er

DOMAIN = "froeling_s3200_modbus"
_LOGGER = logging.getLogger(__name__)

# Optional: YAML-Schema
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required("name", default="Froeling"): cv.string,
                vol.Required("host"): cv.string,
                vol.Required("port", default=502): cv.port,
                vol.Optional("unit_id", default=2): cv.positive_int,
                vol.Required("update_interval", default=60): cv.positive_int,
                vol.Optional("kessel", default=True): cv.boolean,
                vol.Optional("boiler01", default=True): cv.boolean,
                vol.Optional("hk01", default=True): cv.boolean,
                vol.Optional("hk02", default=True): cv.boolean,
                vol.Optional("austragung", default=True): cv.boolean,
                vol.Optional("puffer01", default=True): cv.boolean,
                vol.Optional("zirkulationspumpe", default=True): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.SELECT]


async def async_setup(hass: HomeAssistant, config: dict):
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up the integration from a config entry."""
    # entry.data ist immutable → kopieren und Optionen überlagern
    data = dict(entry.data)
    if entry.options:
        data.update(entry.options)
    data.setdefault("unit_id", 2)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = data

    # Gemeinsamer Modbus-Client + Lock für diese Entry-ID (einmalig verbinden)
    client = ModbusTcpClient(
        data["host"],
        port=data.get("port", 502),
        timeout=3,
        retries=2,
    )
    try:
        client.connect()
    except Exception:
        pass

    lock = asyncio.Lock()
    hass.data[DOMAIN][f"{entry.entry_id}_client"] = client
    hass.data[DOMAIN][f"{entry.entry_id}_lock"] = lock

    _LOGGER.warning(
        "Froeling Modbus initialisiert (pymodbus=%s, host=%s, port=%s, unit_id=%s)",
        pymodbus.__version__,
        data["host"],
        data.get("port", 502),
        data["unit_id"],
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ---- Options-Update: deaktivierte Gruppen aufräumen und reloaden ----
    async def _cleanup_disabled_groups_and_reload(
        hass: HomeAssistant, updated_entry: ConfigEntry
    ):
        old_cfg = hass.data[DOMAIN].get(updated_entry.entry_id, {})
        new_cfg = {**updated_entry.data, **updated_entry.options}

        name = new_cfg.get("name", old_cfg.get("name", "Froeling"))
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        groups = [
            "kessel",
            "boiler01",
            "hk01",
            "hk02",
            "austragung",
            "puffer01",
            "zirkulationspumpe",
        ]

        to_remove = [g for g in groups if old_cfg.get(g, False) and not new_cfg.get(g, False)]

        for g in to_remove:
            ident = (DOMAIN, f"{name}:{g}")
            device = dev_reg.async_get_device({ident})
            if not device:
                continue

            for ent in list(ent_reg.entities.values()):
                if ent.config_entry_id == updated_entry.entry_id and ent.device_id == device.id:
                    ent_reg.async_remove(ent.entity_id)

            try:
                dev_reg.async_remove_device(device.id)
            except Exception:
                _LOGGER.debug("Device %s konnte nicht entfernt werden", device.id)

        await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_cleanup_disabled_groups_and_reload))
    # --------------------------------------------------------------------

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload the config entry and close the client."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    client: ModbusTcpClient | None = hass.data[DOMAIN].pop(
        f"{entry.entry_id}_client", None
    )
    if client:
        try:
            client.close()
        except Exception:
            pass

    hass.data[DOMAIN].pop(f"{entry.entry_id}_lock", None)
    hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
