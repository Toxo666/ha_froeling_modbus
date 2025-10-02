from __future__ import annotations
import logging
from datetime import timedelta
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from pymodbus.client import ModbusTcpClient
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

# ------------------- Helpers -------------------
def _tr_key(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s)

# ---------------- Modbus Helpers (Holding lesen/schreiben) ----------------
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

# -------------------------------------------------------------------------

# ------------------------ Option-Definitionen (Codes → Keys) ----------------
# HK-Betriebsarten (Register 48047/48048)
HK_MODE_CODE_TO_KEY = {
    0: "off",
    1: "auto",
    2: "extra",
    3: "eco",
    4: "eco_permanent",
    5: "party",
}
HK_MODE_KEY_TO_CODE = {v: k for k, v in HK_MODE_CODE_TO_KEY.items()}

# Brennstoffauswahl (Register 40441)
FUEL_CODE_TO_KEY = {
    0: "softwood",
    1: "hardwood",
}
FUEL_KEY_TO_CODE = {v: k for k, v in FUEL_CODE_TO_KEY.items()}

# Fallback-Labels (falls Übersetzung fehlt)
DEFAULT_LABELS = {
    "hk_mode": {
        "off": "Aus",
        "auto": "Automatik",
        "extra": "Extraheizen",
        "eco": "Absenken",
        "eco_permanent": "Dauerabsenken",
        "party": "Partybetrieb",
    },
    "fuel": {
        "softwood": "weiches Holz",
        "hardwood": "hartes Holz",
    },
}

# ------------------------ Register (Holding) ------------------------
REG_HK1_BETRIEBSART = 48047     # Select HK1 - Betriebsart
REG_HK2_BETRIEBSART = 48048     # Select HK2 - Betriebsart
REG_BRENNSTOFFAUSWAHL = 40441   # Select Brennstoffauswahl

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]

    # Übersetzungen: sowohl "entity" als auch unser eigener Namespace "select_option"
    tr_entity = await async_get_translations(hass, hass.config.language, "entity")
    tr_opts   = await async_get_translations(hass, hass.config.language, "select_option")
    translations = {**tr_entity, **tr_opts}

    client: ModbusTcpClient = hass.data[DOMAIN][f"{config_entry.entry_id}_client"]
    lock = hass.data[DOMAIN][f"{config_entry.entry_id}_lock"]

    def create_selects():
        entities: list[SelectEntity] = []

        # 48047 – HK1 Betriebsart
        if data.get("hk01", False):
            entities.append(
                FroelingSelect(
                    hass=hass,
                    config_entry=config_entry,
                    client=client,
                    lock=lock,
                    translations=translations,
                    data=data,
                    entity_id="betriebsart_heizkreis_01",
                    register=REG_HK1_BETRIEBSART,
                    device_key="hk01",
                    group_key="hk_mode",
                    code_to_key=HK_MODE_CODE_TO_KEY,
                    key_to_code=HK_MODE_KEY_TO_CODE,
                    name_fallback="Betriebsart Heizkreis 01",
                )
            )

        # 48048 – HK2 Betriebsart
        if data.get("hk02", False):
            entities.append(
                FroelingSelect(
                    hass=hass,
                    config_entry=config_entry,
                    client=client,
                    lock=lock,
                    translations=translations,
                    data=data,
                    entity_id="betriebsart_heizkreis_02",
                    register=REG_HK2_BETRIEBSART,
                    device_key="hk02",
                    group_key="hk_mode",
                    code_to_key=HK_MODE_CODE_TO_KEY,
                    key_to_code=HK_MODE_KEY_TO_CODE,
                    name_fallback="Betriebsart Heizkreis 02",
                )
            )

        # 40441 – Brennstoffauswahl (Kessel)
        if data.get("kessel", False):
            entities.append(
                FroelingSelect(
                    hass=hass,
                    config_entry=config_entry,
                    client=client,
                    lock=lock,
                    translations=translations,
                    data=data,
                    entity_id="brennstoffauswahl",
                    register=REG_BRENNSTOFFAUSWAHL,
                    device_key="kessel",
                    group_key="fuel",
                    code_to_key=FUEL_CODE_TO_KEY,
                    key_to_code=FUEL_KEY_TO_CODE,
                    name_fallback="Brennstoffauswahl",
                )
            )

        return entities

    entities = create_selects()
    async_add_entities(entities)

    interval = timedelta(seconds=data.get("update_interval", 60))
    for e in entities:
        async_track_time_interval(hass, e.async_update, interval)

# --------------------------- Entity ---------------------------
class FroelingSelect(SelectEntity):
    _attr_should_poll = False

    def __init__(
        self,
        hass,
        config_entry,
        client,
        lock,
        translations,
        data,
        entity_id: str,
        register: int,
        device_key: str,
        group_key: str,                  # z.B. "hk_mode" oder "fuel"
        code_to_key: dict[int, str],     #  int -> option_key
        key_to_code: dict[str, int],     #  option_key -> int
        name_fallback: str,
    ):
        self._hass = hass
        self._client = client
        self._lock = lock
        self._translations = translations
        self._device_name = data["name"]
        self._unit_id = int(data.get("unit_id", 2))
        self._entity_id = entity_id
        self._register = register
        self._device_key = device_key

        self._group_key = group_key
        self._code_to_key = dict(code_to_key)
        self._key_to_code = dict(key_to_code)

        # Optionen: Liste der bekannten Option-Keys (Reihenfolge wie keys())
        self._option_keys = list(self._key_to_code.keys())

        self._current_key: str | None = None
        self._name_fallback = name_fallback

        key = _tr_key(self._entity_id)
        self._attr_name = self._translations.get(
            f"component.froeling_s3200_modbus.entity.select.{key}.name",
            self._name_fallback,
        )

    # ---------- Übersetzungs-Helfer ----------
    def _label_for_key(self, opt_key: str) -> str:
        tr_path = f"component.froeling_s3200_modbus.select_option.{self._group_key}.{opt_key}"
        # Fallback auf DEFAULT_LABELS, falls Übersetzung fehlt
        return self._translations.get(
            tr_path,
            DEFAULT_LABELS.get(self._group_key, {}).get(opt_key, opt_key),
        )

    # ---------- HA Properties ----------
    @property
    def unique_id(self) -> str:
        return f"{self._device_name}_{self._entity_id}"

    @property
    def options(self) -> list[str]:
        # Sichtbare Labels der bekannten Option-Keys
        return [self._label_for_key(k) for k in self._option_keys]

    @property
    def current_option(self) -> str | None:
        if self._current_key is None:
            return None
        return self._label_for_key(self._current_key)

    @property
    def device_info(self):
        return device_info_for(self._device_key, self._device_name, DOMAIN)

    # ---------- IO ----------
    async def async_update(self, *_):
        """Holding lesen und Option setzen."""
        addr = self._register - 40001
        async with self._lock:
            res, err = await self._hass.async_add_executor_job(
                _read_holding_sync, self._client, self._unit_id, addr, 1
            )
        if err or not res or not hasattr(res, "registers"):
            _LOGGER.debug("read_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            return
        try:
            raw = int(res.registers[0])
            key = self._code_to_key.get(raw)
            if key is None:
                # Unbekannter Code -> dynamische "Wert N" Darstellung
                self._current_key = None
                dyn_label = f"Wert {raw}"
                # In Optionen zeigen, ohne den festen Katalog zu verschmutzen
                if dyn_label not in self.options:
                    # nichts persistieren, HA zeigt current_option not in options → wir fügen dynamisch unten hinzu
                    pass
                # Setze sichtbare Option direkt über Label (current_key bleibt None)
                if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
                    self._attr_options = self.options + [dyn_label]
                    self._attr_current_option = dyn_label
                    self.async_write_ha_state()
                return
            else:
                self._current_key = key
                if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
                    # sicherstellen, dass HA die Optionen (Labels) hat
                    self._attr_options = self.options
                    self._attr_current_option = self.current_option
                    self.async_write_ha_state()
        except Exception as e:
            _LOGGER.debug("parse error on select %s: %s", self._entity_id, e)

    async def async_select_option(self, option: str):
        """Holding schreiben aus ausgewählter (übersetzter) Option."""
        # Mappe Label -> Key
        key = None
        for k in self._option_keys:
            if self._label_for_key(k) == option:
                key = k
                break

        if key is None:
            # Erlaube dynamisches "Wert N"
            if option.startswith("Wert "):
                try:
                    code = int(option.split(" ", 1)[1])
                except Exception:
                    _LOGGER.error("invalid dynamic option %s", option)
                    return
            else:
                _LOGGER.error("invalid option %s", option)
                return
        else:
            code = int(self._key_to_code[key])

        addr = self._register - 40001
        async with self._lock:
            _, err = await self._hass.async_add_executor_job(
                _write_register_sync, self._client, self._unit_id, addr, code
            )
        if err:
            _LOGGER.error("write_holding addr=%s unit=%s failed: %s", addr, self._unit_id, err)
            return

        # State lokal aktualisieren
        if key is None:
            # dynamischer Wert
            self._current_key = None
            if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
                self._attr_options = self.options + [option]
                self._attr_current_option = option
                self.async_write_ha_state()
        else:
            self._current_key = key
            if getattr(self, "hass", None) is not None and getattr(self, "entity_id", None):
                self._attr_options = self.options
                self._attr_current_option = self.current_option
                self.async_write_ha_state()
