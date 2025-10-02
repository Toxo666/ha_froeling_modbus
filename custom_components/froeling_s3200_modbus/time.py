from __future__ import annotations
from datetime import time, timedelta
import logging
from pymodbus.client import ModbusTcpClient
from homeassistant.util import dt as dt_util
from homeassistant.components.time import TimeEntity
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

# ------------------- Helpers -------------------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)

# --- Modbus Helpers (Holding) ---
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

# --------------------------------

# ---- Zeitzonen/DST nur für echte Tageszeiten (40062/40095) ----
ASSUME_DEVICE_USES_UTC = True  # typischerweise lokale Uhrzeit im Gerät

def _now_offset_minutes(hass) -> int:
    tz = dt_util.get_time_zone(hass.config.time_zone) if hass.config.time_zone else dt_util.DEFAULT_TIME_ZONE
    return int(dt_util.now(tz).utcoffset().total_seconds() // 60)

def _hhmm_to_minutes(raw: int) -> int:
    if raw == 2400:
        return 0
    h = max(0, min(23, raw // 100))
    m = max(0, min(59, raw % 100))
    return h * 60 + m

def _minutes_to_hhmm(mins: int) -> int:
    mins %= 1440
    h = mins // 60
    m = mins % 60
    return h * 100 + m

def _device_to_local_minutes(hass, device_mins: int) -> int:
    if not ASSUME_DEVICE_USES_UTC:
        return device_mins
    return (device_mins + _now_offset_minutes(hass)) % 1440

def _local_to_device_minutes(hass, local_mins: int) -> int:
    if not ASSUME_DEVICE_USES_UTC:
        return local_mins
    return (local_mins - _now_offset_minutes(hass)) % 1440

# ---- Register ----
REGISTER_START_PELLETSBEFUELLUNG_1 = 40062  # R/W Uhrzeit (HHMM 0..2400)
REGISTER_START_PELLETSBEFUELLUNG_2 = 40095  # R   Uhrzeit (HHMM 0..2400)
REGISTER_VERZOEGERUNG_NACH_SCHEITHOLZ = 40252  # R/W Dauer in 0,1 h (0..24, skaliert)

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    if not data.get("austragung", False):
        return

    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN].get(f"{config_entry.entry_id}_lock")

    entities = [
        # 40062 – Start 1. Pelletsbefüllung (R/W, echte Tageszeit)
        FroelingAustragungTimeHHMM(
            hass=hass, client=client, lock=lock, translations=translations, data=data,
            entity_id="pelletsbefuellung_1_startzeit", register=REGISTER_START_PELLETSBEFUELLUNG_1,
            device_key="austragung",
        ),
        # 40095 – Start 2. Pelletsbefüllung (R, echte Tageszeit)
        FroelingAustragungTimeHHMMReadOnly(
            hass=hass, client=client, lock=lock, translations=translations, data=data,
            entity_id="pelletsbefuellung_2_startzeit", register=REGISTER_START_PELLETSBEFUELLUNG_2,
            device_key="austragung",
        ),
        # 40252 – Verzögerung als HH:MM anzeigen, intern 0,1 h schreiben/lesen
        FroelingAustragungDelayAsTime(
            hass=hass, client=client, lock=lock, translations=translations, data=data,
            entity_id="verzoegerung_pufferladung_nach_scheitholzbetrieb",
            register=REGISTER_VERZOEGERUNG_NACH_SCHEITHOLZ,
            device_key="austragung",
        ),
    ]

    async_add_entities(entities)
    interval = timedelta(seconds=data.get("update_interval", 60))
    for e in entities:
        async_track_time_interval(hass, e.async_update, interval)

# ---------------- Basisklasse: echte HHMM-Tageszeit ----------------
class _BaseTimeHHMM(TimeEntity):
    _attr_should_poll = False

    def __init__(self, hass, client, lock, translations, data, entity_id: str, register: int, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
        self._register = register
        self._device_key = device_key
        self._value: time | None = None

    @property
    def unique_id(self) -> str:
        return f"{self._device_name}_{self._entity_id}"

    @property
    def name(self) -> str:
        key = _tr_key(self._entity_id)
        default_name = self._entity_id.replace("_", " ")
        return self._translations.get(f"component.{DOMAIN}.entity.time.{key}.name", default_name)

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    @property
    def native_value(self) -> time | None:
        return self._value

    def _push_state(self):
        if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
            try:
                self.async_write_ha_state()
            except Exception:
                pass

    async def _read_holding_1(self):
        addr = self._register - 40001
        if self._lock is not None:
            async with self._lock:
                return await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)
        return await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)

# --- Konkrete HHMM-Entities (Tageszeit mit optionaler UTC-Umrechnung) ---
class FroelingAustragungTimeHHMM(_BaseTimeHHMM):
    """R/W HHMM-Zeit (40062)."""
    async def async_update(self, *_):
        res, err = await self._read_holding_1()
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding err @%s: %s", self._register, err)
            return
        try:
            raw = int(res.registers[0])
            dev_mins = _hhmm_to_minutes(raw)
            loc_mins = _device_to_local_minutes(self._hass, dev_mins)
            self._value = time(hour=(loc_mins // 60) % 24, minute=loc_mins % 60)
            self._push_state()
        except Exception as e:
            _LOGGER.debug("parse HHMM failed (%s): %s", self._entity_id, e)

    async def async_set_value(self, value: time) -> None:
        loc_mins = value.hour * 60 + value.minute
        dev_mins = _local_to_device_minutes(self._hass, loc_mins)
        write_val = _minutes_to_hhmm(dev_mins)
        addr = self._register - 40001
        if self._lock is not None:
            async with self._lock:
                _, err = await self._hass.async_add_executor_job(_write_register_sync, self._client, self._unit_id, addr, write_val)
        else:
            _, err = await self._hass.async_add_executor_job(_write_register_sync, self._client, self._unit_id, addr, write_val)
        if err:
            _LOGGER.error("write_holding err @%s: %s", self._register, err)
            return
        self._value = value
        self._push_state()

class FroelingAustragungTimeHHMMReadOnly(_BaseTimeHHMM):
    """R/O HHMM-Zeit (40095)."""
    async def async_update(self, *_):
        res, err = await self._read_holding_1()
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding err @%s: %s", self._register, err)
            return
        try:
            raw = int(res.registers[0])
            dev_mins = _hhmm_to_minutes(raw)
            loc_mins = _device_to_local_minutes(self._hass, dev_mins)
            self._value = time(hour=(loc_mins // 60) % 24, minute=loc_mins % 60)
            self._push_state()
        except Exception as e:
            _LOGGER.debug("parse HHMM failed (%s): %s", self._entity_id, e)

# --- Speziell: 40252 als „Zeit-Feld“, intern 0,1 h (Dauer) ---
class FroelingAustragungDelayAsTime(TimeEntity):
    """Stellt die *Dauer* 40252 (0..24 h in 0,1 h) als HH:MM dar."""
    _attr_should_poll = False
    def __init__(self, hass, client, lock, translations, data, entity_id: str, register: int, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
        self._register = register
        self._device_key = device_key
        self._value: time | None = None

        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.{DOMAIN}.entity.time.{key}.name",
            "Nach Scheitholzbetrieb: Pufferladung mit Pellets verzögern um",
        )

    @property
    def unique_id(self) -> str:
        return f"{self._device_name}_{self._entity_id}"

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    @property
    def native_value(self) -> time | None:
        return self._value

    def _push_state(self):
        if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
            try:
                self.async_write_ha_state()
            except Exception:
                pass

    async def async_update(self, *_):
        """raw (0..240, =0..24,0 h) -> Minuten (= raw*6) -> HH:MM."""
        addr = self._register - 40001
        if self._lock is not None:
            async with self._lock:
                res, err = await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)
        else:
            res, err = await self._hass.async_add_executor_job(_read_holding_sync, self._client, self._unit_id, addr, 1)
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding err @%s: %s", self._register, err)
            return
        try:
            raw = int(res.registers[0])  # 0..240 (Zehntelstunden)
            raw = max(0, min(240, raw))
            minutes = raw * 6  # 0,1 h = 6 min
            # 1440 (=24:00) als 00:00 anzeigen (HA kennt 24:00 nicht)
            minutes %= 1440
            self._value = time(hour=(minutes // 60) % 24, minute=minutes % 60)
            self._push_state()
        except Exception as e:
            _LOGGER.debug("parse delay failed (%s): %s", self._entity_id, e)

    async def async_set_value(self, value: time) -> None:
        """HH:MM -> Minuten -> raw=round(min/6), clamp 0..240."""
        minutes = value.hour * 60 + value.minute
        raw = int(round(minutes / 6.0))
        raw = max(0, min(240, raw))
        addr = self._register - 40001
        if self._lock is not None:
            async with self._lock:
                _, err = await self._hass.async_add_executor_job(_write_register_sync, self._client, self._unit_id, addr, raw)
        else:
            _, err = await self._hass.async_add_executor_job(_write_register_sync, self._client, self._unit_id, addr, raw)
        if err:
            _LOGGER.error("write_holding err @%s: %s", self._register, err)
            return
        # zurücksetzen auf gerasterten Wert (auf 6-min Snap)
        minutes = (raw * 6) % 1440
        self._value = time(hour=(minutes // 60) % 24, minute=minutes % 60)
        self._push_state()
