from homeassistant.components.sensor import SensorEntity
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

# --- HELPER: Modbus Calls (nur Input) ---
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

# --- ENDE HELPER ---

# ---------- Helper: Friendly Name-Key (defensiv) ----------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
# -------------------------------------------------------------------

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    def create_text_sensors():
        return [
            FroelingTextSensor(hass, config_entry, client, lock, translations, data,
                               "anlagenzustand", 34001, ANLAGENZUSTAND_MAPPING, device_key="controller"),
            FroelingTextSensor(hass, config_entry, client, lock, translations, data,
                               "kesselzustand", 34002, KESSELZUSTAND_MAPPING, device_key="kessel"),
        ]

    def create_sensors():
        sensors = [
            FroelingSensor(hass, config_entry, client, lock, translations, data,
                           "aussentemperatur", 31001, "°C", 2, 0, device_class="temperature", device_key="controller"),
        ]
        if data.get("kessel", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kesseltemperatur", 30001, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "abgastemperatur", 30002, "°C", 1, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "verbleibende_heizstunden_bis_zur_asche_entleeren_warnung", 30087, "h", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "saugzug_ansteuerung", 30013, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "saugzugdrehzahl", 30007, "Upm", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "sauerstoffregler", 30017, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "restsauerstoffgehalt", 30004, "%", 10, 1, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "ruecklauffuehler", 30010, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "primaerluft", 30012, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "sekundaerluft", 30014, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden", 30021, "h", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "stunden_seit_letzter_wartung", 30056, "h", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_in_der_feuererhaltung", 30025, "h", 1, 0, device_key="kessel"),
            ])
        if data.get("hk01", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk01_vorlauf_isttemperatur", 31031, "°C", 2, 0, device_class="temperature", device_key="hk01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk01_vorlauf_solltemperatur", 31032, "°C", 2, 0, device_class="temperature", device_key="hk01"),
            ])
        if data.get("hk02", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk02_vorlauf_isttemperatur", 31061, "°C", 2, 0, device_class="temperature", device_key="hk02"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk02_vorlauf_solltemperatur", 31062, "°C", 2, 0, device_class="temperature", device_key="hk02"),
            ])
        if data.get("puffer01", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_temperatur_oben", 32001, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_temperatur_mitte", 32002, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_temperatur_unten", 32003, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_pufferpumpen_ansteuerung", 32004, "%", 1, 0, device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_ladezustand", 32007, "%", 1, 0, device_key="puffer01"),
            ])
        if data.get("boiler01", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_temperatur_oben", 31631, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_pumpe_ansteuerung", 31633, "%", 1, 0, device_key="boiler01"),
            ])
        if data.get("austragung", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "fuellstand_im_pelletsbehaelter", 30022, "%", 207, 1, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "resetierbarer_kg_zaehler", 30082, "kg", 1, 0, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "resetierbarer_t_zaehler", 30083, "t", 1, 0, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "pelletverbrauch_gesamt", 30084, "t", 10, 0, device_key="austragung"),
            ])
        if data.get("zirkulationspumpe", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "ruecklauftemperatur_an_der_zirkulations_leitung", 30712, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "stoemungsschalter_an_der_brauchwasser_leitung", 30601, "", 2, 0, device_key="boiler01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "drehzahl_der_zirkulations_pumpe", 30711, "%", 1, 0, device_key="boiler01"),
            ])
        return sensors

    text_sensors = create_text_sensors()
    async_add_entities(text_sensors)
    sensors = create_sensors()
    async_add_entities(sensors)

    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for s in sensors:
        async_track_time_interval(hass, s.async_update, update_interval)
    for ts in text_sensors:
        async_track_time_interval(hass, ts.async_update_text_sensor, update_interval)

class FroelingSensor(SensorEntity):
    def __init__(self, hass, config_entry, client, lock, translations, data,
                 entity_id, register, unit, scaling_factor, decimal_places=0,
                 device_class=None, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id  # bereits lowercase
        self._register = register
        self._unit = unit
        self._scaling_factor = scaling_factor
        self._decimal_places = decimal_places
        self._device_class = device_class
        self._device_key = device_key
        self._state = None

        # Anzeigename aus Translations fix setzen
        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.froeling_s3200_modbus.entity.sensor.{key}.name",
            self._entity_id.replace("_", " ")
        )

    @property
    def unique_id(self): return f"{self._device_name}_{self._entity_id}"

    @property
    def state(self): return self._state
    @property
    def unit_of_measurement(self): return self._unit
    @property
    def device_class(self): return self._device_class

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    async def async_update(self, _=None):
        addr = self._register - 30001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_input_sync, self._client, self._unit_id, addr, 1)
        if err:
            _LOGGER.error("read_input addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._state = None
            return
        raw = res.registers[0]
        if raw > 32767:
            raw -= 65536
        val = raw / self._scaling_factor
        self._state = int(val) if self._decimal_places == 0 else round(val, self._decimal_places)

ANLAGENZUSTAND_MAPPING = {
    0:"Dauerlast",1:"Brauchwasser",2:"Automatik",3:"Scheitholzbetr",4:"Reinigen",5:"Ausgeschaltet",6:"Extraheizen",7:"Kaminkehrer",8:"Reinigen"
}

KESSELZUSTAND_MAPPING = {
    0:"STÖRUNG",1:"Kessel Aus",2:"Anheizen",3:"Heizen",4:"Feuererhaltung",5:"Feuer Aus",6:"Tür offen",7:"Vorbereitung",8:"Vorwärmen",9:"Zünden",
    10:"Abstellen Warten",11:"Abstellen Warten1",12:"Abstellen Einschub1",13:"Abstellen Warten2",14:"Abstellen Einschub2",15:"Abreinigen",
    16:"2h warten",17:"Saugen / Heizen",18:"Fehlzündung",19:"Betriebsbereit",20:"Rost schließen",21:"Stoker leeren",22:"Vorheizen",23:"Saugen",
    24:"RSE schließen",25:"RSE öffnen",26:"Rost kippen",27:"Vorwärmen-Zünden",28:"Resteinschub",29:"Stoker auffüllen",30:"Lambdasonde aufheizen",
    31:"Gebläsenachlauf I",32:"Gebläsenachlauf II",33:"Abgestellt",34:"Nachzünden",35:"Zünden Warten",36:"FB: RSE schließen",37:"FB: Kessel belüften",
    38:"FB: Zünden",39:"FB: min. Einschub",40:"RSE schließen",41:"STÖRUNG: STB/NA",42:"STÖRUNG: Kipprost",43:"STÖRUNG: FR-Überdr.",44:"STÖRUNG: Türkont.",
    45:"STÖRUNG: Saugzug",46:"STÖRUNG: Umfeld",47:"FEHLER: STB/NA",48:"FEHLER: Kipprost",49:"FEHLER: FR-Überdr.",50:"FEHLER: Türkont.",
    51:"FEHLER: Saugzug",52:"FEHLER: Umfeld",53:"FEHLER: Stoker",54:"STÖRUNG: Stoker",55:"FB: Stoker leeren",56:"Vorbelüften",57:"STÖRUNG: Hackgut",
    58:"FEHLER: Hackgut",59:"NB: Tür offen",60:"NB: Anheizen",61:"NB: Heizen",62:"FEHLER: STB/NA",63:"FEHLER: Allgemein",64:"NB: Feuer Aus",
    65:"Selbsttest aktiv",66:"Fehlerbeh. 20min",67:"FEHLER: Fallschacht",68:"STÖRUNG: Fallschacht",69:"Reinigen möglich",70:"Heizen - Reinigen",
    71:"SH Anheizen",72:"SH Heizen",73:"SH Heiz/Abstell",74:"STÖRUNG sicher",75:"AGR Nachlauf",76:"AGR reinigen",77:"Zündung AUS",78:"Filter reinigen",
    79:"Anheizassistent",80:"SH Zünden",81:"SH Störung",82:"Sensorcheck"
}

class FroelingTextSensor(SensorEntity):
    def __init__(self, hass, config_entry, client, lock, translations, data,
                 entity_id, register, mapping, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id  # lowercase
        self._register = register
        self._mapping = mapping
        self._device_key = device_key
        self._state = None

        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.froeling_s3200_modbus.entity.sensor.{key}.name",
            self._entity_id.replace("_", " ")
        )

    @property
    def unique_id(self): return f"{self._device_name}_{self._entity_id}"

    @property
    def state(self): return self._state

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    async def async_update_text_sensor(self, _=None):
        addr = self._register - 30001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(_read_input_sync, self._client, self._unit_id, addr, 1)
        if err:
            _LOGGER.error("read_input addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            self._state = None
            return
        raw = res.registers[0]
        self._state = self._mapping.get(raw, "Unknown")
