from homeassistant.components.number import NumberEntity
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

# ---------- Helper: Friendly Name-Key ----------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
# ------------------------------------------------

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    def create_numbers():
        nums = []
        if data.get("kessel", False):
            nums.extend([
                FroelingNumber(hass, config_entry, client, lock, translations, data, "kessel_solltemperatur", 40001, "°C", 2, 0, 70, 90, device_key="kessel"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "bei_welcher_rl_temperatur_an_der_zirkulationsleitung_soll_die_pumpe_ausschalten", 40601, "°C", 2, 0, 20, 120, device_key="boiler01"),
            ])
        if data.get("hk01", False):
            nums.extend([
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_vorlauf_temperatur_10c_aussentemperatur", 41032, "°C", 2, 0, 10, 110, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_vorlauf_temperatur_minus_10c_aussentemperatur", 41033, "°C", 2, 0, 10, 110, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_heizkreispumpe_ausschalten_wenn_vorlauf_soll_kleiner_ist_als", 41040, "°C", 2, 0, 10, 30, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_absenkung_der_vorlauftemperatur_im_absenkbetrieb", 41034, "°C", 2, 0, 0, 70, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_aussentemperatur_unter_der_die_heizkreispumpe_im_heizbetrieb_einschaltet", 41037, "°C", 2, 0, -20, 50, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_aussentemperatur_unter_der_die_heizkreispumpe_im_absenkbetrieb_einschaltet", 41038, "°C", 2, 0, -20, 50, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_frostschutztemperatur", 41039, "°C", 2, 0, 10, 20, device_key="hk01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk1_temp_am_puffer_oben_ab_der_der_ueberhitzungsschutz_aktiv_wird", 41048, "°C", 1, 0, 60, 120, device_key="hk01"),
            ])
        if data.get("hk02", False):
            nums.extend([
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_vorlauf_temperatur_10c_aussentemperatur", 41062, "°C", 2, 0, 10, 110, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_vorlauf_temperatur_minus_10c_aussentemperatur", 41063, "°C", 2, 0, 10, 110, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_heizkreispumpe_ausschalten_wenn_vorlauf_soll_kleiner_ist_als", 41070, "°C", 2, 0, 10, 30, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_absenkung_der_vorlauftemperatur_im_absenkbetrieb", 41064, "°C", 2, 0, 0, 70, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_aussentemperatur_unter_der_die_heizkreispumpe_im_heizbetrieb_einschaltet", 41067, "°C", 2, 0, -20, 50, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_aussentemperatur_unter_der_die_heizkreispumpe_im_absenkbetrieb_einschaltet", 41068, "°C", 2, 0, -20, 50, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_frostschutztemperatur", 41069, "°C", 2, 0, -10, 20, device_key="hk02"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "hk2_temp_am_puffer_oben_ab_der_der_ueberhitzungsschutz_aktiv_wird", 41079, "°C", 1, 0, 60, 120, device_key="hk02"),
            ])
        if data.get("boiler01", False):
            nums.extend([
                FroelingNumber(hass, config_entry, client, lock, translations, data, "boiler_1_gewuenschte_boilertemperatur", 41632, "°C", 2, 0, 10, 100, device_key="boiler01"),
                FroelingNumber(hass, config_entry, client, lock, translations, data, "boiler_1_nachladen_wenn_boilertemperatur_unter", 41633, "°C", 2, 0, 1, 90, device_key="boiler01"),
            ])
        if data.get("austragung", False):
            nums.append(FroelingNumber(hass, config_entry, client, lock, translations, data, "pelletlager_restbestand", 40320, "t", 10, 1, 0, 100, device_key="austragung"))
        return nums

    numbers = create_numbers()
    async_add_entities(numbers)
    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for n in numbers:
        async_track_time_interval(hass, n.async_update, update_interval)

class FroelingNumber(NumberEntity):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, register, unit,
                 scaling_factor, decimal_places=0, min_value=0, max_value=0, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id  # lowercase
        self._register = register
        self._unit = unit
        self._scaling_factor = scaling_factor
        self._decimal_places = decimal_places
        self._min_value = min_value
        self._max_value = max_value
        self._device_key = device_key
        self._value = None

        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.froeling_s3200_modbus.entity.number.{key}.name",
            self._entity_id.replace("_", " ")
        )

    @property
    def unique_id(self): return f"{self._device_name}_{self._entity_id}"

    @property
    def native_value(self): return self._value
    @property
    def native_unit_of_measurement(self): return self._unit
    @property
    def native_min_value(self): return self._min_value
    @property
    def native_max_value(self): return self._max_value

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    async def async_set_native_value(self, value):
        addr = self._register - 40001
        scaled = int(value * self._scaling_factor)
        async with self._lock:
            _, err = await self._hass.async_add_executor_job(_write_register_sync, self._client, self._unit_id, addr, scaled)
        if err:
            _LOGGER.error("write_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            return
        self._value = value

    async def async_update(self, _=None):
        addr = self._register - 40001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)
        if err:
            _LOGGER.error("read_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._value = None
            return
        raw = res.registers[0]
        self._value = round(raw / self._scaling_factor, self._decimal_places)
