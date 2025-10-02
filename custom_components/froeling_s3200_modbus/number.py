from homeassistant.components.number import NumberEntity
from pymodbus.client import ModbusTcpClient
import logging
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from .const import DOMAIN
from datetime import datetime, timezone, timedelta

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
# ---------------------------------------

# --- HELPER: Modbus Calls (Input/Holding + Write) ---
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

def _write_register_sync(client, unit_id: int, addr: int, value: int):
    """FC=06: Single Holding Register schreiben (4xxxx). addr ist 0-basiert (40001 -> 0)."""
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
        nums: list[NumberEntity] = []

        # --- Kessel ---
        if data.get("kessel", False):
            nums.extend([
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "kessel_solltemperatur", 40001, "°C", 2, 0, 70, 90, device_key="kessel"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "bei_welcher_rl_temperatur_an_der_zirkulationsleitung_soll_die_pumpe_ausschalten", 40601, "°C", 2, 0, 20, 120, device_key="boiler01"),
            ])

        # --- Heizkreis 01 ---
        if data.get("hk01", False):
            nums.extend([
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_vorlauf_temperatur_10c_aussentemperatur", 41032, "°C", 2, 0, 10, 110, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_vorlauf_temperatur_minus_10c_aussentemperatur", 41033, "°C", 2, 0, 10, 110, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_heizkreispumpe_ausschalten_wenn_vorlauf_soll_kleiner_ist_als", 41040, "°C", 2, 0, 10, 30, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_absenkung_der_vorlauftemperatur_im_absenkbetrieb", 41034, "°C", 2, 0, 0, 70, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_aussentemperatur_unter_der_die_heizkreispumpe_im_heizbetrieb_einschaltet", 41037, "°C", 2, 0, -20, 50, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_aussentemperatur_unter_der_die_heizkreispumpe_im_absenkbetrieb_einschaltet", 41038, "°C", 2, 0, -20, 50, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_frostschutztemperatur", 41039, "°C", 2, 0, -30, 20, device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_temp_am_puffer_oben_ab_der_der_ueberhitzungsschutz_aktiv_wird", 41048, "°C", 1, 0, 60, 120, device_class="temperature", device_key="hk01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk1_vorlauf_soll_modbus", 48001, "°C", 2, 0, 0, 75, device_key="hk01"),
            ])

        # --- Heizkreis 02 ---
        if data.get("hk02", False):
            nums.extend([
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_vorlauf_temperatur_10c_aussentemperatur", 41062, "°C", 2, 0, 10, 110, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_vorlauf_temperatur_minus_10c_aussentemperatur", 41063, "°C", 2, 0, 10, 110, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_heizkreispumpe_ausschalten_wenn_vorlauf_soll_kleiner_ist_als", 41070, "°C", 2, 0, 10, 30, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_absenkung_der_vorlauftemperatur_im_absenkbetrieb", 41064, "°C", 2, 0, 0, 70, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_aussentemperatur_unter_der_die_heizkreispumpe_im_heizbetrieb_einschaltet", 41067, "°C", 2, 0, -20, 50, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_aussentemperatur_unter_der_die_heizkreispumpe_im_absenkbetrieb_einschaltet", 41068, "°C", 2, 0, -20, 50, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_frostschutztemperatur", 41069, "°C", 2, 0, -10, 20, device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_temp_am_puffer_oben_ab_der_der_ueberhitzungsschutz_aktiv_wird", 41079, "°C", 1, 0, 60, 120, device_class="temperature", device_key="hk02"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "hk2_vorlauf_soll_modbus", 48002, "°C", 2, 0, 0, 75, device_key="hk02"),
            ])

        # --- Boiler 01 ---
        if data.get("boiler01", False):
            nums.extend([
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "boiler_1_gewuenschte_boilertemperatur", 41632, "°C", 2, 0, 10, 100, device_key="boiler01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "boiler_1_nachladen_wenn_boilertemperatur_unter", 41633, "°C", 2, 0, 1, 90, device_key="boiler01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "boiler_1_solltemperatur_modbus", 48019, "°C", 2, 0, 0, 65, device_key="boiler01"),
            ])

        # --- Puffer 01 ---
        if data.get("puffer01", False):
            nums.extend([
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "puffer_1_delta_t_kessel_vs_grenzschicht", 42003, "°C", 2, 0, 0, 120, device_key="puffer01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "puffer_1_start_pufferladung_ab_ladezustand", 42022, "%", 1, 0, 0, 100, device_key="puffer01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "puffer_1_100_prozent_kesselleistung_bis_ladezustand", 42027, "%", 1, 0, 0, 100, device_key="puffer01"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "puffer_1_0_prozent_kesselleistung_ab_ladezustand", 42028, "%", 1, 0, 0, 100, device_key="puffer01"),
            ])

        # --- Austragung ---
        if data.get("austragung", False):
            nums.extend([
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "gefoerderte_pellets_100_prozent_einschub", 40319, "g", 1, 0, 0, 10000, device_key="austragung"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "pelletlager_restbestand", 40320, "t", 10, 1, 0, 100, device_key="austragung"),
                FroelingNumberHolding(hass, config_entry, client, lock, translations, data, "pelletlager_mindestbestand", 40336, "t", 10, 1, 0, 100, device_key="austragung"),
            ])

        return nums

    numbers = create_numbers()
    async_add_entities(numbers)

    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for n in numbers:
        async_track_time_interval(hass, n.async_update, update_interval)

# ---------------- Basisklassen ----------------
class _BaseNumber(NumberEntity):
    _attr_should_poll = False
    """Gemeinsame Basis – Name/IDs/Übersetzungen/Meta."""
    def __init__(self, hass, config_entry, client, lock, translations, data, entity_id, register, unit,
                 scaling_factor, decimal_places=0, min_value=0, max_value=0, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
        self._register = register
        self._unit = unit
        self._scaling_factor = scaling_factor
        self._decimal_places = decimal_places
        self._min_value = float(min_value)
        self._max_value = float(max_value)
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
    def native_step(self):
        # Schrittweite aus Skalierung ableiten, z. B. SKAL=2 -> 0.5
        try:
            step = 1.0 / float(self._scaling_factor)
            return int(step) if step.is_integer() else round(step, max(0, self._decimal_places))
        except Exception:
            return None

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

# ---------------- Input-Register (FC=04, 3xxxx, read-only) ----------------
class FroelingNumberInput(_BaseNumber):
    async def async_set_native_value(self, value):
        # read-only: bewusst kein Setzen
        _LOGGER.debug("Attempt to write to Input-Register %s ignored", self._register)

    async def async_update(self, _=None):
        addr = self._register - 30001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_input_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_input addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._value = None
            return
        raw = int(res.registers[0])
        self._value = round(raw / float(self._scaling_factor), self._decimal_places)
        self.async_write_ha_state()
        
# ---------------- Holding-Register (FC=03, 4xxxx, read/write) ----------------
class FroelingNumberHolding(_BaseNumber):
    """4xxxx Number, writeable (FC=06) mit 2.6-Logik:
       - -1 Antworten -> unknown
       - Anzeige: Override aktiv (2-min Fenster ab letztem Write)
       - Warnung bei Writes < 10 min Mindestschaltdauer
    """

    # Optional: eigene Defaults pro Entity anpassbar, falls nötig
    _override_timeout = timedelta(minutes=2)   # 2.6: Fernsteuerung deaktiviert nach 2 min ohne Write
    _min_switch_interval = timedelta(minutes=10)  # 2.6: Mindestschaltdauer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_write_utc: datetime | None = None

    @property
    def extra_state_attributes(self):
        now = datetime.now(timezone.utc)
        override_active = (
            self._last_write_utc is not None
            and now - self._last_write_utc <= self._override_timeout
        )
        return {
            "register": self._register,
            "last_write_utc": self._last_write_utc.isoformat() if self._last_write_utc else None,
            "modbus_override_active": override_active,
            "min_switch_interval_min": int(self._min_switch_interval.total_seconds() // 60),
            "override_timeout_min": int(self._override_timeout.total_seconds() // 60),
        }

    async def async_set_native_value(self, value):
        # Begrenzen & quantisieren
        v = float(min(max(value, self._min_value), self._max_value))
        raw = int(round(v * float(self._scaling_factor)))
        v_quant = raw / float(self._scaling_factor)

        # 10-Minuten-Fenster nur als Hinweis loggen (Regel ignoriert sonst selbst und sendet -1)
        now = datetime.now(timezone.utc)
        if self._last_write_utc and (now - self._last_write_utc) < self._min_switch_interval:
            _LOGGER.warning(
                "Write to %s (reg %s) innerhalb der 10-Minuten-Mindestschaltdauer (2.6). "
                "Regelung kann den Wert ignorieren und -1 zurückmelden.",
                self._entity_id, self._register
            )

        addr = self._register - 40001
        async with self._lock:
            _, err = await self._hass.async_add_executor_job(
                _write_register_sync, self._client, self._unit_id, addr, raw
            )
        if err:
            _LOGGER.error("write_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            return

        # Erfolgreicher Write: Zeitstempel setzen & lokalen Wert übernehmen
        self._last_write_utc = now
        self._value = round(v_quant, self._decimal_places)
        self.async_write_ha_state()

    async def async_update(self, _=None):
        addr = self._register - 40001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_holding_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._value = None
            return

        raw = int(res.registers[0])

        # signiertes 16-bit: -1 -> 65535
        if raw > 32767:
            raw -= 65536

        # 2.6: -1 bedeutet "Wert ignoriert / Mindestschaltdauer" -> unknown
        if raw == -1:
            self._value = None
            return

        self._value = round(raw / float(self._scaling_factor), self._decimal_places)
        self.async_write_ha_state()