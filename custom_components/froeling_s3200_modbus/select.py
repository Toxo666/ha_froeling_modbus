from homeassistant.components.select import SelectEntity
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

# --- HELPER: Modbus Calls (Holding + Write) ---
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
    except TypeError:
        pass
    try:
        client.unit_id = unit_id
        res = client.read_holding_registers(addr, count=count)
        if hasattr(res, "isError") and res.isError():
            return None, "error(client.unit_id)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

def _write_register_sync(client, unit_id: int, addr: int, value: int):
    if not client.connect():
        return None, "connect"
    try:
        res = client.write_register(addr, value, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    try:
        res = client.write_register(addr, value, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except TypeError:
        pass
    try:
        client.unit_id = unit_id
        res = client.write_register(addr, value)
        if hasattr(res, "isError") and res.isError():
            return None, "error(client.unit_id)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

# --- ENDE HELPER ---

# ---------- Helper: translation key ----------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
# --------------------------------------------

# ---------- Options (0..5) ----------
HK_MODE_LABELS = [
    "Aus",
    "Automatik",
    "Extraheizen",
    "Absenken",
    "Dauerabsenken",
    "Partybetrieb",
]
MODE_TO_INT = {name: i for i, name in enumerate(HK_MODE_LABELS)}
# -------------------------------------

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    selects = []

    # PDF 3.5: Betriebsart Heizkreis 1-18 -> 48047..48064
    if data.get("hk01", False):
        selects.append(
            FroelingSelect(
                hass, config_entry, client, lock, translations, data,
                "hk01_betriebsart", 48047, HK_MODE_LABELS, device_key="hk01"
            )
        )
    if data.get("hk02", False):
        selects.append(
            FroelingSelect(
                hass, config_entry, client, lock, translations, data,
                "hk02_betriebsart", 48048, HK_MODE_LABELS, device_key="hk02"
            )
        )

    if selects:
        async_add_entities(selects)
        interval = timedelta(seconds=data.get("update_interval", 60))
        for s in selects:
            async_track_time_interval(hass, s.async_update, interval)

class FroelingSelect(SelectEntity):
    def __init__(
        self, hass, config_entry, client, lock, translations, data,
        entity_id: str, register: int, options: list[str], device_key="controller"
    ):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
        self._register = register
        self._options = options
        self._device_key = device_key
        self._current_option = None

    @property
    def unique_id(self):
        return f"{self._device_name}_{self._entity_id}"

    @property
    def name(self):
        key = _tr_key(self._entity_id)
        return self._translations.get(
            f"component.froeling_s3200_modbus.entity.select.{key}.name",
            self._entity_id,
        )

    @property
    def options(self):
        return self._options

    @property
    def current_option(self):
        return self._current_option

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    async def async_update(self, _=None):
        addr = self._register - 40001  # Holding-Register-Offset
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_holding_sync, self._client, self._unit_id, addr, 1
            )
        if err:
            _LOGGER.error("read_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._current_option = None
            return
        raw = res.registers[0]
        if 0 <= raw < len(self._options):
            self._current_option = self._options[raw]
        else:
            self._current_option = None

    async def async_select_option(self, option: str):
        if option not in MODE_TO_INT:
            _LOGGER.error("invalid option %s", option)
            return
        value = MODE_TO_INT[option]
        addr = self._register - 40001
        async with self._lock:
            _, err = await self._hass.async_add_executor_job(
                _write_register_sync, self._client, self._unit_id, addr, int(value)
            )
        if err:
            _LOGGER.error("write_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            return
        self._current_option = option
