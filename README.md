# Froeling S3200 Modbus

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Eine **Home Assistant Custom Integration** für die Anbindung einer **Fröling Lambdatronic S3200** Steuerung über **Modbus TCP**.  
Damit lassen sich Zustände und Messwerte der Heizanlage (Kessel, Heizkreise, Puffer, Austragung etc.) direkt in Home Assistant einbinden.

---

## ✨ Funktionen

- Verbindung zur **Fröling S3200** über Modbus TCP  
- Auslesen von Sensorwerten (z. B. Temperaturen, Betriebszustände)  
- Steuerung von Schaltern (z. B. Pumpen, Heizkreise)  
- Unterstützung mehrerer Gerätebereiche:
  - Kessel
  - Heizkreis(e)
  - Puffer
  - Austragung
  - Warmwasser (DHW)
  - Zirkulationspumpe  

---

## 📦 Installation

### Variante 1: Über HACS (empfohlen)
1. Stelle sicher, dass [HACS](https://hacs.xyz/) installiert ist.  
2. Füge dieses Repository als **Custom Repository** hinzu:
   - HACS → Integrationen → Repositories → „+“ →  
     URL: `https://github.com/Toxo666/ha_froeling_modbus`  
     Kategorie: `Integration`  
3. Danach taucht die Integration in HACS auf und kann installiert werden.  

### Variante 2: Manuell
1. Lade die Dateien aus `custom_components/froeling_s3200_modbus` herunter.  
2. Kopiere den Ordner `froeling_s3200_modbus` nach:  
   ```
   config/custom_components/froeling_s3200_modbus
   ```
3. Home Assistant neu starten.  

---

## ⚙️ Konfiguration

1. Gehe in Home Assistant auf:  
   **Einstellungen → Geräte & Dienste → Integration hinzufügen**  
2. Wähle **Froeling S3200 Modbus**.  
3. Gib die Verbindungseinstellungen ein:
   - Hostname / IP-Adresse der S3200
   - Port (Standard: 502)
   - Update-Intervall (Standard: 60 s)  

---

## 🖼️ Screenshots
<img width="2010" height="1344" alt="2025-10-03_14-57-08" src="https://github.com/user-attachments/assets/ebbb796a-b0e1-4b06-b8c6-bd18caea4a31" />
---

## 🤝 Mitwirken

Pull Requests, Issues und Verbesserungsvorschläge sind jederzeit willkommen!  

---
