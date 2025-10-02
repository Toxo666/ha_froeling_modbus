from homeassistant.components.switch import SwitchEntity
from pymodbus.client import ModbusTcpClient
import logging
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ------------------- Geräte-Gruppierung -------------------
DEVICE_NAME = {
    "controller": "SP Dual Compact",
    "kessel": "Kessel",
    "boiler01": "Boiler 01",
    "hk01": "Heizkreis 01",
    "hk02": "Heizkreis 02",
    "puffer01": "Puffer 01",
    "austragung": "Austragung",
    "zirkulationspumpe": "Zirkulationspumpe",
}

def device_info_for(device_key: str, device_name_from_config: str, domain: str):
    dev_name = DEVICE_NAME.get(device_key, device_key)
    if device_key == "controller":
        return {
            "identifiers": {(domain, f"{device_name_from_config}:controller")},
            "name": "SP Dual Compact",
            "manufacturer": "Fröling",
            "model": "SP Dual Compact",
            "sw_version": "0.3.0",
        }
    return {
        "identifiers": {(domain, f"{device_name_from_config}:{device_key}")},
        "name": dev_name,
        "manufacturer": "Fröling",
        "model": dev_name,
        "via_device": (domain, f"{device_name_from_config}:controller"),
        "sw_version": "0.3.0",
    }
# ----------------------------------------------------------

# ---------- Helper: Key/Übersetzung ----------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
# --------------------------------------------

# --- HELPER: Modbus Calls (nur Holding: FC03 lesen / FC06 schreiben) ---
def _read_holding_sync(client, unit_id: int, addr: int, count: int):
    if not client.connect():
        return None, "connect"
    try:
        res = client.read_holding_registers(addr, count=count, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    try:
        res = client.read_holding_registers(addr, count=count, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

def _write_register_sync(client: ModbusTcpClient, unit_id: int, addr: int, value: int):
    """FC=06: Write Single Holding Register (4xxxx)."""
    if not client.connect():
        return None, "connect"
    # 1) bevorzugt: device_id
    try:
        res = client.write_register(addr, value, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    # 2) fallback: unit
    try:
        res = client.write_register(addr, value, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

# --- ENDE HELPER ---

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    def create_switches():
        sw: list[SwitchEntity] = []

        # --- Kessel ---
        if data.get("kessel", False):
            # 40136 Automatisch Zünden (R/W, 0/1)
            sw.append(FroelingHoldingSwitch(hass, config_entry, client, lock, translations, data, "automatisch_zuenden", 40136, device_key="kessel"))

        # --- Heizkreis 01 ---
        if data.get("hk01", False):
            # 48029 Freigabe Heizkreis 01 (R/W, 0/1)
            sw.append(FroelingHoldingSwitch(hass, config_entry, client, lock, translations, data, "hk1_freigabe", 48029, device_key="hk01"))

        # --- Heizkreis 02 ---
        if data.get("hk02", False):
            # 48030 Freigabe Heizkreis 02 (R/W, 0/1)
            sw.append(FroelingHoldingSwitch(hass, config_entry, client, lock, translations, data, "hk2_freigabe", 48030, device_key="hk02"))

        # --- Austragung ---
        if data.get("austragung", False):
            # 40265 Automatische Pelletsaustragung deaktivieren (R/W, 0/1)
            sw.append(FroelingHoldingSwitch(hass, config_entry, client, lock, translations, data, "pelletsaustragung_deaktivieren", 40265, device_key="austragung"))

        return sw

    switches = create_switches()
    async_add_entities(switches)

    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for s in switches:
        async_track_time_interval(hass, s.async_update, update_interval)

# ---------------- Basisklasse ----------------
class _BaseSwitch(SwitchEntity):
    _attr_should_poll = False
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id: str, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
        self._device_key = device_key
        self._is_on = None

        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.froeling_s3200_modbus.entity.switch.{key}.name",
            self._entity_id.replace("_", " ")
        )

    @property
    def unique_id(self):
        return f"{self._device_name}_{self._entity_id}"

    @property
    def is_on(self):
        return bool(self._is_on)

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    def _push_state(self):
        if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
            try:
                self.async_write_ha_state()
            except Exception:
                pass

# ---------------- Holding-Register (FC=03 lesen / FC=06 schreiben) ----------------
class FroelingHoldingSwitch(_BaseSwitch):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id: str, register: int, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._register = register  # echte 4xxxx-Nummer

    async def async_update(self, *_):
        addr = self._register - 40001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._is_on = None
            self._push_state()
            return
        try:
            self._is_on = bool(int(res.registers[0]))
        except Exception as e:
            _LOGGER.debug("parse error on switch %s: %s", self._entity_id, e)
            self._is_on = None
        self._push_state()

    async def async_turn_on(self, **kwargs):
        await self._async_write_state(True)

    async def async_turn_off(self, **kwargs):
        await self._async_write_state(False)

    async def _async_write_state(self, on: bool):
        addr = self._register - 40001
        value = 1 if on else 0
        async with self._lock:
            _, err = await self._hass.async_add_executor_job(_write_register_sync, self._client, self._unit_id, addr, value)
        if err:
            _LOGGER.error("write_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            return
        self._is_on = on
        self._push_state()
