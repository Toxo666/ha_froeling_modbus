from homeassistant.components.sensor import SensorEntity
from pymodbus.client import ModbusTcpClient
import logging
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers import entity_registry as er
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
# ---------------------------------------

# --- HELPER: Modbus Calls ---
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
# ---------------------------------------

# ---------- Helper: Friendly Name-Key (defensiv) ----------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
# -------------------------------------------------------------------

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    translations = await async_get_translations(hass, hass.config.language, "entity")
    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    ent_reg = er.async_get(hass)
    dev_name = data["name"]
    to_remove = []
    if not data.get("kessel", False):
        to_remove.append(f"{dev_name}_kesselzustand")
    if not data.get("boiler01", False):
        to_remove.append(f"{dev_name}_legionellentag")
    if not data.get("hk01", False):
        to_remove.append(f"{dev_name}_hk_01_pufferversorgung")
    if not data.get("hk02", False):
        to_remove.append(f"{dev_name}_hk_02_pufferversorgung")
    for e in list(ent_reg.entities.values()):
        if e.platform == DOMAIN and e.unique_id in to_remove:
            ent_reg.async_remove(e.entity_id)

    # ---------- TEXT-SENSOREN ----------
    def create_text_sensors():
        items = []
        items.append(FroelingTextSensor(hass, config_entry, client, lock, translations, data, "anlagenzustand", 34001, ANLAGENZUSTAND_MAPPING, device_key="controller"))
        if data.get("kessel", False):
            items.append(
                FroelingTextSensor(hass, config_entry, client, lock, translations, data, "kesselzustand", 34002, KESSELZUSTAND_MAPPING, device_key="kessel")
                )
        if data.get("boiler01", False):
            items.append(
                FroelingTextHoldingSensor(hass, config_entry, client, lock, translations, data, "legionellentag", 41638, LEGIONELLENTAG_MAPPING, device_key="boiler01")
                )
        if data.get("hk01", False):
            items.append(
                FroelingTextHoldingSensor(hass, config_entry, client, lock, translations, data, "hk_01_pufferversorgung", 41045, HK01PUFFERVERSORGUNG_MAPPING, device_key="hk01")
                )
        if data.get("hk02", False):
            items.append(
                FroelingTextHoldingSensor(hass, config_entry, client, lock, translations, data, "hk_02_pufferversorgung", 41075, HK02PUFFERVERSORGUNG_MAPPING, device_key="hk02")
                )
        return items
    # ---------- CONTROLLER-SENSOREN ----------
    def create_controller_sensors():
        return [
            FroelingSensor(hass, config_entry, client, lock, translations, data, "boardtemperatur", 30003, "°C", 2, 0, device_class="temperature", device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "boardtemperatur_pelletsmodul", 30018, "°C", 2, 0, device_class="temperature", device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden", 30021, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "anzahl_der_brennerstarts", 30023, "", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_in_der_feuererhaltung", 30025, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_stokerschnecke", 30040, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_foerderschnecke", 30041, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_ruettler", 30043, "min", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_wos", 30045, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_ascheschnecke", 30046, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_zuendung", 30047, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_lambdasonde", 30048, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_saugturbinen", 30049, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_austragsschnecke", 30050, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "lambdasondenspannung_gemessen", 30055, "mV", 100, 2, device_class="voltage", device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "stunden_seit_letzter_wartung", 30056, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "stunden_im_pelletsbetrieb", 30063, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "stunden_im_heizen", 30064, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "stunden_in_teillastbetrieb", 30075, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "stunden_im_scheitholzbetrieb", 30077, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "tagesertrag", 30085, "kWh", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "gesamtertrag", 30086, "kWh", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_saugturbine", 30098, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "anzahl_der_reinigungen", 30102, "", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "zeit_bis_zur_naechsten_reinigung", 30103, "min", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "betriebsstunden_e_filter", 30104, "h", 1, 0, device_key="controller"),
            FroelingSensor(hass, config_entry, client, lock, translations, data, "aussentemperatur", 31001, "°C", 2, 0, device_class="temperature", device_key="controller"),
        ]

    # ---------- KOMPLETTER SENSOR-AUFBAU ----------
    def create_sensors():
        sensors: list[SensorEntity] = []
        # Controller zuerst
        sensors.extend(create_controller_sensors())

        # KESSEL
        if data.get("kessel", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_kesseltemperatur", 30001, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_abgastemperatur", 30002, "°C", 1, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_restsauerstoffgehalt", 30004, "%", 10, 1, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_position_primaerluftklappe", 30005, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_saugzugdrehzahl", 30007, "Upm", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_fuehler_1", 30008, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_abgastemperatur_nach_brennwertwaermetauscher", 30009, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_ruecklauffuehler", 30010, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_luftgeschwindigkeit_ansaug", 30011, "m/s", 100, 2, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_primaerluft", 30012, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_saugzug_ansteuerung", 30013, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_sekundaerluft", 30014, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_kesselstellgroesse", 30015, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_abgas_solltemperatur", 30016, "°C", 1, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_sauerstoffregler", 30017, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_ansauglufttemperatur", 30019, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_errechnete_kesselsolltemperatur", 30028, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_ruecklaufpumpen_ansteuerung", 30037, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_drehzahl_kesselladepumpe", 30068, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_verbleibende_heizstunden_bis_asche_entleeren", 30087, "h", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_feuerraumtemperatur", 30089, "°C", 1, 0, device_class="temperature", device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_saugzug_ansteuerung_alt", 30105, "%", 1, 0, device_key="kessel"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "kessel_waermemenge_vom_kessel", 30171, "MWh", 10, 1, device_key="kessel"),

                # Holding 4xxxx -> eigene Klasse
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_abschalten_wenn_kesseltemperatur_ueber_soll", 40002, "°C", 2, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_maximale_anheizzeit", 40003, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_kesseltemperatur_ab_pumpen_freigabe", 40008, "°C", 2, 0, device_class="temperature", device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_immer_abschalten_ueber_kesselsoll_plus", 40009, "°C", 2, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_sollwert_restsauerstoff", 40027, "%", 10, 1, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_restsauerstoff_fuer_feuer_aus", 40028, "%", 10, 1, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_restsauerstoff_ohne_verbrennung", 40029, "%", 10, 1, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_dauer_vorwaermen", 40043, "s", 1, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_maximale_zuenddauer", 40045, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_abstellen_warten_1", 40046, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_mind_dauer_geblaesenachlauf1", 40047, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_mind_dauer_abstellen", 40048, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_abstellen_warten_2", 40049, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_mind_dauer_geblaesenachlauf2", 40050, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_sicherheitszeit", 40051, "min", 60, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_wos_laufzeit", 40061, "s", 1, 0, device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_abgastemperatur_feuer_aus", 40073, "°C", 1, 0, device_class="temperature", device_key="kessel"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "kessel_nach_wie_viel_mal_abstellen_abreinigen", 40085, "", 1, 0, device_key="kessel"),
            ])

        # HEIZKREIS 01
        if data.get("hk01", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk01_vorlauf_isttemperatur", 31031, "°C", 2, 0, device_class="temperature", device_key="hk01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk01_vorlauf_solltemperatur", 31032, "°C", 2, 0, device_class="temperature", device_key="hk01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "hk01_maximale_vorlauftemperatur", 41035, "°C", 2, 0, device_class="temperature", device_key="hk01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "hk01_laufzeit_mischer", 41043, "s", 1, 0, device_key="hk01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "hk01_maximale_boiler_vorlauftemperatur", 41047, "°C", 2, 0, device_class="temperature", device_key="hk01"),
            ])

        # HEIZKREIS 02
        if data.get("hk02", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk02_vorlauf_isttemperatur", 31061, "°C", 2, 0, device_class="temperature", device_key="hk02"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "hk02_vorlauf_solltemperatur", 31062, "°C", 2, 0, device_class="temperature", device_key="hk02"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "hk02_maximale_vorlauftemperatur", 41065, "°C", 2, 0, device_class="temperature", device_key="hk02"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "hk02_laufzeit_mischer", 41073, "s", 1, 0, device_key="hk02"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "hk02_maximale_boiler_vorlauftemperatur", 41078, "°C", 2, 0, device_class="temperature", device_key="hk02"),
            ])

        # PUFFER 01
        if data.get("puffer01", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_temperatur_oben", 32001, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_temperatur_mitte", 32002, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_temperatur_unten", 32003, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_pufferpumpen_ansteuerung", 32004, "%", 1, 0, device_key="puffer01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_ladezustand", 32007, "%", 1, 0, device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_heizkreisfreigabe_ab_puffertemperatur", 42001, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_minimale_drehzahl_pufferpumpe", 42004, "%", 1, 0, device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_kesselstart_diff_kesselsoll_oben", 42005, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_durchgeladen_diff_kesselsoll_unten", 42006, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_maximale_drehzahl_pufferpumpe", 42012, "%", 1, 0, device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_puffer_puffer_diff", 42018, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_ladezustand_100_prozent_beikesselsoll", 42020, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_ladezustand_0_prozent_ab_temp", 42021, "°C", 2, 0, device_class="temperature", device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_systemumfeld_ausschaltverzoegerung", 42026, "min", 60, 0, device_key="puffer01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "puffer_1_volumen", 42029, "l", 1, 0, device_key="puffer01"),
            ])

        # BOILER 01
        if data.get("boiler01", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_temperatur_oben", 31631, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_pumpe_ansteuerung", 31633, "%", 1, 0, device_key="boiler01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_laden_bei_puffer_und_boiler_tempdiff_von", 41634, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_laden_bei_kessel_und_boiler_tempdiff_von", 41639, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_soll_diff_kessel_boiler", 41640, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_min_drehzahl_boilerpumpe", 41641, "%", 1, 0, device_key="boiler01"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "boiler_1_max_drehzahl_boilerpumpe", 41646, "%", 1, 0, device_key="boiler01"),
            ])

        # AUSTRAGUNG
        if data.get("austragung", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "stromaufnahme_der_austragsschnecke", 30020, "A", 1000, 2, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "fuellstand_im_pelletsbehaelter", 30022, "%", 207, 1, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "resetierbarer_kg_zaehler", 30082, "kg", 1, 0, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "resetierbarer_t_zaehler", 30083, "t", 1, 0, device_key="austragung"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "pelletverbrauch_gesamt", 30084, "t", 10, 1, device_key="austragung"),
                FroelingHoldingSensor(hass, config_entry, client, lock, translations, data, "dauer_des_ruettelns", 40125, "s", 1, 0, device_key="austragung"),  # Holding
            ])

        # ZIRKULATIONSPUMPE (unter Boiler 01 gruppiert)
        if data.get("zirkulationspumpe", False):
            sensors.extend([
                FroelingSensor(hass, config_entry, client, lock, translations, data, "ruecklauftemperatur_an_der_zirkulations_leitung", 30712, "°C", 2, 0, device_class="temperature", device_key="boiler01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "stoemungsschalter_an_der_brauchwasser_leitung", 30601, "", 2, 0, device_key="boiler01"),
                FroelingSensor(hass, config_entry, client, lock, translations, data, "drehzahl_der_zirkulations_pumpe", 30711, "%", 1, 0, device_key="boiler01"),
            ])

        return sensors

    # ——— Setup Entities & Polling ———
    text_sensors = create_text_sensors()
    async_add_entities(text_sensors)

    sensors = create_sensors()
    async_add_entities(sensors)

    update_interval = timedelta(seconds=data.get("update_interval", 60))
    for s in sensors:
        async_track_time_interval(hass, s.async_update, update_interval)
    for ts in text_sensors:
        async_track_time_interval(hass, ts.async_update_text_sensor, update_interval)

# --------------------- Basisklassen ---------------------
class FroelingSensor(SensorEntity):
    _attr_should_poll = False
    """Input (3xxxx) – FC=04"""
    def __init__(self, hass, config_entry, client, lock, translations, data,
                 entity_id, register, unit, scaling_factor, decimal_places=0,
                 device_class=None, device_key="controller"):
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
        self._device_class = device_class
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
    def unit_of_measurement(self): return self._unit
    @property
    def device_class(self): return self._device_class

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    async def async_update(self, _=None):
        addr = self._register - 30001  # 0-basiert
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_input_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_input failed reg=%s (addr=%s) unit=%s err=%s", self._register, addr, self._unit_id, err)
            self._state = None
            return
        raw = int(res.registers[0])
        if raw > 32767:
            raw -= 65536
        val = raw / (self._scaling_factor if self._scaling_factor else 1)
        self._state = int(round(val)) if self._decimal_places == 0 else round(val, self._decimal_places)
        self.async_write_ha_state()
        
class FroelingHoldingSensor(SensorEntity):
    _attr_should_poll = False
    """Holding (4xxxx) – FC=03"""
    def __init__(self, hass, config_entry, client, lock, translations, data,
                 entity_id, register, unit, scaling_factor, decimal_places=0,
                 device_class=None, device_key="controller"):
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
        self._device_class = device_class
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
    def unit_of_measurement(self): return self._unit
    @property
    def device_class(self): return self._device_class

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    async def async_update(self, _=None):
        addr = self._register - 40001  # 0-basiert
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_holding_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding failed reg=%s (addr=%s) unit=%s err=%s", self._register, addr, self._unit_id, err)
            self._state = None
            return
        raw = int(res.registers[0])
        if raw > 32767:
            raw -= 65536
        val = raw / (self._scaling_factor if self._scaling_factor else 1)
        self._state = int(round(val)) if self._decimal_places == 0 else round(val, self._decimal_places)
        self.async_write_ha_state()

class FroelingTextSensor(SensorEntity):
    _attr_should_poll = False
    """Text-Mapping über Input (3xxxx) – FC=04"""
    def __init__(self, hass, config_entry, client, lock, translations, data,
                 entity_id, register, mapping, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
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
        addr = self._register - 30001  # 0-basiert (Input)
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_input_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_input TEXT failed reg=%s (addr=%s) unit=%s err=%s", self._register, addr, self._unit_id, err)
            self._state = None
            return
        raw = int(res.registers[0])
        self._state = self._mapping.get(raw, f"Unknown ({raw})")
        self.async_write_ha_state()

class FroelingTextHoldingSensor(SensorEntity):
    _attr_should_poll = False
    """Text-Mapping über Holding (4xxxx) – FC=03"""
    def __init__(self, hass, config_entry, client, lock, translations, data,
                 entity_id, register, mapping, device_key="controller"):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = data.get("unit_id", 2)
        self._entity_id = entity_id
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
        addr = self._register - 40001  # 0-basiert (Holding)
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_holding_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding TEXT failed reg=%s (addr=%s) unit=%s err=%s", self._register, addr, self._unit_id, err)
            self._state = None
            return
        raw = int(res.registers[0])
        self._state = self._mapping.get(raw, f"Unknown ({raw})")
        self.async_write_ha_state()

# --------------------- Text-Mappings ---------------------
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

LEGIONELLENTAG_MAPPING = {
    1:"Montag",2:"Dienstag",3:"Mittwoch",4:"Donnerstag",5:"Freitag",6:"Samstag",7:"Sonntag"
}
HK01PUFFERVERSORGUNG_MAPPING = {
    0:"Kessel",1:"Puffer01",2:"Puffer02",3:"Puffer03",4:"Puffer04"
}
HK02PUFFERVERSORGUNG_MAPPING = {
    0:"Kessel",1:"Puffer01",2:"Puffer02",3:"Puffer03",4:"Puffer04"
}
