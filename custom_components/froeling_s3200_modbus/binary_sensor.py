from homeassistant.components.binary_sensor import BinarySensorEntity
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
}

def device_info_for(device_key: str, device_name_from_config: str, domain: str):
    dev_name = DEVICE_NAME.get(device_key, device_key)

    if device_key == "controller":
        return {
            "identifiers": {(domain, f"{device_name_from_config}:controller")},
            "name": "SP Dual Compact",
            "manufacturer": "Fröling",
            "model": "SP Dual Compact",
            "sw_version": "1.0",
        }

    return {
        "identifiers": {(domain, f"{device_name_from_config}:{device_key}")},
        "name": dev_name,
        "manufacturer": "Fröling",
        "model": dev_name,
        "via_device": (domain, f"{device_name_from_config}:controller"),
        "sw_version": "1.0",
    }
# ----------------------------------------------------------

# ---------- Verbindungs-Helfer ----------
def _ensure_connected(client: ModbusTcpClient):
    try:
        if not getattr(client, "connected", False):
            client.connect()
    except Exception:
        pass
# ---------------------------------------

# --- HELPER: Modbus Calls (Input + Coils) ---
def _read_input_sync(client, unit_id: int, addr: int, count: int):
    if not client.connect():
        return None, "connect"
    try:
        res = client.read_input_registers(addr, count=count, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    try:
        res = client.read_input_registers(addr, count=count, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except TypeError:
        pass
    try:
        client.unit_id = unit_id
        res = client.read_input_registers(addr, count=count)
        if hasattr(res, "isError") and res.isError():
            return None, "error(client.unit_id)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

def _read_coils_sync(client, unit_id: int, addr: int, count: int):
    if not client.connect():
        return None, "connect"
    try:
        res = client.read_coils(addr, count=count, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    try:
        res = client.read_coils(addr, count=count, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except TypeError:
        pass
    try:
        client.unit_id = unit_id
        res = client.read_coils(addr, count=count)
        if hasattr(res, "isError") and res.isError():
            return None, "error(client.unit_id)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

# --- ENDE HELPER ---

# ---------- Helper: Friendly Name-Key ----------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
# -----------------------------------------------

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    def create_binary_sensors():
        bs = []
        if data.get("hk01", False):
            bs.append(FroelingBinaryCoil(hass, config_entry, client, lock, translations, data, "hk1_pumpe_an_aus", 1030, device_key="hk01"))
        if data.get("hk02", False):
            bs.append(FroelingBinaryCoil(hass, config_entry, client, lock, translations, data, "hk2_pumpe_an_aus", 1060, device_key="hk02"))
        if data.get("puffer01", False):
            bs.append(FroelingBinaryInput(hass, config_entry, client, lock, translations, data, "puffer_1_pufferpumpe_an_aus", 32004, device_key="puffer01"))
        if data.get("zirkulationspumpe", False):
            bs.append(FroelingBinaryInput(hass, config_entry, client, lock, translations, data, "zirkulationspumpe_an_aus", 30711, device_key="boiler01"))
        if data.get("boiler01", False):
            bs.append(FroelingBinaryInput(hass, config_entry, client, lock, translations, data, "boiler_1_pumpe_an_aus", 31633, device_key="boiler01"))
        return bs

    sensors = create_binary_sensors()
    async_add_entities(sensors)
    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for s in sensors:
        async_track_time_interval(hass, s.async_update, update_interval)

class _BaseBin(BinarySensorEntity):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id  # lowercase
        self._device_key = device_key
        self._state = None

        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.froeling_s3200_modbus.entity.binary_sensor.{key}.name",
            self._entity_id.replace("_", " ")
        )

    @property
    def unique_id(self): return f"{self._device_name}_{self._entity_id}"
    @property
    def is_on(self): return self._state

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

class FroelingBinaryCoil(_BaseBin):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, coil_address, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._coil_address = coil_address

    async def async_update(self, _=None):
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_coils_sync, self._client, self._unit_id, self._coil_address, 1)
        if err:
            _LOGGER.error("read_coils addr=%s unit=%s failed: %s", self._coil_address, self._unit_id, err)
            self._state = None
            return
        self._state = bool(res.bits[0])

class FroelingBinaryInput(_BaseBin):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, register, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._register = register

    async def async_update(self, _=None):
        addr = self._register - 30001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_input_sync, self._client, self._unit_id, addr, 1)
        if err:
            _LOGGER.error("read_input addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._state = None
            return
        self._state = res.registers[0] > 0
