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

# ---------- Verbindungs-Helfer ----------
def _ensure_connected(client: ModbusTcpClient):
    try:
        if not getattr(client, "connected", False):
            client.connect()
    except Exception:
        pass

# --- HELPER: Modbus Calls (FC04/FC03/FC01/FC02) ---
def _read_input_sync(client, unit_id: int, addr: int, count: int):
    if not client.connect():
        return None, "connect"
    # 1) Bevorzugt: device_id
    try:
        res = client.read_input_registers(addr, count=count, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    # 2) Fallback: unit
    try:
        res = client.read_input_registers(addr, count=count, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

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

def _read_coils_sync(client, unit_id: int, addr: int, count: int):
    """FC=01: Coils. addr wird so verwendet, wie übergeben (kein Offset-Abzug!)."""
    if not client.connect():
        return None, "connect"
    # 1) bevorzugt: device_id
    try:
        res = client.read_coils(addr, count=count, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    # 2) fallback: unit
    try:
        res = client.read_coils(addr, count=count, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
        return res, None
    except Exception as e:
        return None, f"exc:{e}"

def _read_discrete_sync(client, unit_id: int, addr: int, count: int):
    """FC=02: Discrete Inputs (1xxxx). addr ist 0-basiert (10001 -> 0)."""
    if not client.connect():
        return None, "connect"
    # 1) bevorzugt: device_id
    try:
        res = client.read_discrete_inputs(addr, count=count, device_id=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(device_id)"
        return res, None
    except TypeError:
        pass
    # 2) fallback: unit
    try:
        res = client.read_discrete_inputs(addr, count=count, unit=unit_id)
        if hasattr(res, "isError") and res.isError():
            return None, "error(unit)"
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
        bs: list[BinarySensorEntity] = []

        # ----- DISCRETE INPUTS (FC=02, 1xxxx) -----
        bs.append(FroelingBinaryDI(hass, config_entry, client, lock, translations, data, "tuerkontaktschalter", 10001, device_key="controller"))
        bs.append(FroelingBinaryDI(hass, config_entry, client, lock, translations, data, "stb_eingang", 10002, device_key="controller"))
        bs.append(FroelingBinaryDI(hass, config_entry, client, lock, translations, data, "not_aus_eingang", 10003, device_key="controller"))
        bs.append(FroelingBinaryDI(hass, config_entry, client, lock, translations, data, "kesselfreigabe_eingang", 10004, device_key="controller"))
        
        if data.get("hk01", False):
            # ----- COILS (FC=01) -----
            bs.append(FroelingBinaryCoil(hass, config_entry, client, lock, translations, data, "hk1_pumpe_an_aus", 1030, device_key="hk01"))
            # ----- HOLDING REGISTER (FC=03, 4xxxx) -----
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "hk1_boilervorrang_heizen_erlaubt", 41044, device_key="hk01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "hk1_hochtemperatur_anforderung_boilerladung", 41046, device_key="hk01"))

        if data.get("hk02", False):
            # ----- COILS (FC=01) -----
            bs.append(FroelingBinaryCoil(hass, config_entry, client, lock, translations, data, "hk2_pumpe_an_aus", 1060, device_key="hk02"))
            # ----- HOLDING REGISTER (FC=03, 4xxxx) -----
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "hk2_boilervorrang_heizen_erlaubt", 41074, device_key="hk02"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "hk2_hochtemperatur_anforderung_boilerladung", 41076, device_key="hk02"))

        if data.get("kessel", False):
            # ----- INPUT REGISTER (FC=04, 3xxxx) -----
            bs.append(FroelingBinaryInput(hass, config_entry, client, lock, translations, data, "kesselanforderung_steht_an", 30057, device_key="kessel"))
            # ----- HOLDING REGISTER (FC=03, 4xxxx) -----
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "lambda_auto_kalibrierung_aktiv", 43020, device_key="kessel"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "nachlegeberechnung_aktiv", 42031, device_key="puffer01"))

        if data.get("boiler01", False):
            # ----- HOLDING REGISTER (FC=03, 4xxxx) -----
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "boiler1_restwaermenutzung", 41635, device_key="boiler01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "boiler1_nur_einmal_pro_tag_aufladen", 41636, device_key="boiler01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "boiler1_legionellen_aufheizung_aktiv", 41637, device_key="boiler01"))

        if data.get("puffer01", False):
            # ----- HOLDING REGISTER (FC=03, 4xxxx) -----
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "puffer1_restwaermenutzung", 42002, device_key="puffer01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "puffer1_puffermitte_regelung_aktiv", 42014, device_key="puffer01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "puffer1_sp_dual_nach_puffermitte_beenden", 42015, device_key="puffer01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "pufferanforderung_nach_systemumfeld", 42025, device_key="puffer01"))
            bs.append(FroelingBinaryHolding(hass, config_entry, client, lock, translations, data, "puffer1_hygienespeicher_verwendet", 42030, device_key="puffer01"))

        return bs

    sensors = create_binary_sensors()
    async_add_entities(sensors)

    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for s in sensors:
        async_track_time_interval(hass, s.async_update, update_interval)

# ---------------- Basisklasse ----------------
class _BaseBin(BinarySensorEntity):
    _attr_should_poll = False
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
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

    def _push_state(self):
        if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
            try:
                self.async_write_ha_state()
            except Exception:
                pass

# ---------------- Coils (FC=01) ----------------
class FroelingBinaryCoil(_BaseBin):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, coil_address, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._coil_address = coil_address

    async def async_update(self, _=None):
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_coils_sync, self._client, self._unit_id, self._coil_address, 1)
        if err or not res or not hasattr(res, "bits"):
            _LOGGER.debug("read_coils addr=%s unit=%s failed: %s", self._coil_address, self._unit_id, err)
            self._state = None
            self._push_state()
            return
        self._state = bool(res.bits[0])
        self._push_state()

# ---------------- Input-Register (FC=04) ----------------
class FroelingBinaryInput(_BaseBin):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, register, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._register = register  # echte 3xxxx-Nummer

    async def async_update(self, _=None):
        addr = self._register - 30001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_input_sync, self._client, self._unit_id, addr, 1)
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_input addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._state = None
            self._push_state()
            return
        raw = int(res.registers[0])
        if raw > 32767:
            raw -= 65536
        self._state = (raw != 0)
        self._push_state()

# ---------------- Holding-Register (FC=03) ----------------
class FroelingBinaryHolding(_BaseBin):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, register, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._register = register  # echte 4xxxx-Nummer

    async def async_update(self, _=None):
        addr = self._register - 40001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._state = None
            self._push_state()
            return
        self._state = (int(res.registers[0]) != 0)
        self._push_state()

# ---------------- Discrete Inputs (FC=02) ----------------
class FroelingBinaryDI(_BaseBin):
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, register, device_key="controller"):
        super().__init__(hass, config_entry, client, lock, translations, data, entity_id, device_key=device_key)
        self._register = register  # echte 1xxxx-Nummer

    async def async_update(self, _=None):
        addr = self._register - 10001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_discrete_sync, self._client, self._unit_id, addr, 1)
        if err or not res or not hasattr(res, "bits"):
            _LOGGER.debug("read_discrete addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._state = None
            self._push_state()
            return
        self._state = bool(res.bits[0])
        self._push_state()
