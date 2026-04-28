# argus-pager 2.0

**Counter-Surveillance auf dem WiFi Pineapple Pager.** Ein Tool das passiv und mobil
die Frage beantwortet: *„Wer überwacht mich gerade — und wie?"*

<p align="center">
  <img src="docs/screenshots/01_splash.png" alt="Splash + Sensor self-check" width="380">
  &nbsp;
  <img src="docs/screenshots/04_scan_live.png" alt="Live scan with round counter, ETA, live counters" width="380">
</p>

---

## Was kann das Ding

argus-pager 2.0 vereint drei Quellen auf einem Hardware-Stack
(Pineapple Pager + GL-E750 Mudi V2):

- **WiFi / Bluetooth** — wer pingt mich an, wer folgt mir
- **Cellular / GSM-Layer** — bin ich gerade an einem IMSI-Catcher
- **Aktive Funkangriffe** — werde ich gerade vom Netz geworfen

| Bedrohung | Detektor (Kürzel) | Quelle |
|---|---|---|
| Apple AirTag, Samsung SmartTag, Tile, Chipolo am Rucksack | BT-Tracker | BLE-Adv |
| Gerät verfolgt mich über mehrere Orte (Persistenz, Stalking) | Cross-Report | WiFi-Probe |
| WiFi Pineapple / KARMA in der Nähe | LAA + Probe-Storm (TODO) | WiFi-Probe |
| **Deauth-Flood-Angriff aktiv** | DEAUTH | 802.11 mgmt |
| IP-Kamera / NVR im Hotelzimmer | Hotel-Scan | WiFi-Beacon, BT |
| Aktive Spy-Cam (Bandbreiten-Spike) | Camera-Activity | PCAP |
| **IMSI-Catcher / Stingray** (RAT-Downgrade, TA-Anomalie, …) | IMSI-Monitor | AT+QENG |
| **Silent-SMS / Stille SMS** (Standortpeilung) | SMS-Watch | AT+CMGL |
| Cell-Tower Spoofing (Cell-ID-Mismatch) | OpenCelliD-Lookup | API |

Detail-Erklärungen aller Detektoren: **[docs/features.md](docs/features.md)**

---

## Wann benutze ich was

Drei Presets decken 90% der Situationen ab — `CUSTOM` für den Rest.

| Situation | Empfehlung | Dauer |
|---|---|---|
| Alltag, Café, U-Bahn | **`STANDARD`** | 6 min |
| Hotel-Check-in, längere stationäre Session | **`DEEPSCAN`** | 12 min |
| Auto-Fahrt, nur Cell-Layer | `CUSTOM` (nur `cell` + `gps_mudi`) | beliebig |
| Stealth, kein LED + kein Vibrate | `CUSTOM` mit `led_on_alert: false` | beliebig |
| Nur BT, passiv im Café | `CUSTOM` (nur `bt`) | beliebig |

Hintergrund-Watcher (**IMSI-Monitor** + **Silent-SMS**) laufen *immer* passiv mit,
sobald der Mudi erreichbar ist. Das sind keine Modus-Komponenten, sondern
systemweite Sensoren — du kriegst Alarme auch wenn gerade kein Scan läuft.

---

## IMEI-Changer (OPSEC/OPDEC)

Wenn ein Scan einen IMSI-Catcher oder eine andere starke Bedrohung findet, wird
dein Modem (also: deine **IMEI**) potenziell schon erfasst. Eine erfasste IMEI
gilt netzweit — der Operator kann dich über die Cell-Towers korrelieren, auch
wenn du SIM oder Standort wechselst.

argus bietet deshalb am Ende jeder Scan-Session eine **opt-in IMEI-Rotation**
über [Blue Merle](https://github.com/srlabs/blue-merle) auf dem Mudi V2:

1. **Radio off** (`AT+CFUN=4`) — verhindert dass die alte IMEI noch leakt
2. **Rotate** — Blue Merle generiert eine neue IMEI (deterministisch aus
   IMSI-Hash, optional pseudo-random)
3. **Radio on** (`AT+CFUN=1`) — neue IMEI ist live

Sichtbar als Schritt **4/4** im Post-Scan: `[A] Rotate` rotiert, `[B] Keep`
behält die aktuelle IMEI. Die Sequenz dauert je nach Modem 10–30 s.

**OPDEC-Hinweis:** IMEI-Wechsel allein hilft nicht gegen alle Korrelations-
Vektoren. Wer auch *operationale Sicherheit* (OPSEC) ernst nimmt, kombiniert
Rotation mit:

- **SIM-Swap im selben Schritt** (Modem ist schon im Radio-off-State)
- **Standortwechsel** zwischen alter und neuer IMEI (sonst kann ein passiver
  Beobachter die Übergabe am gleichen Cell-Tower mitloggen)
- **MAC-Randomisierung am Pager** (Linux native auf den WLAN-Interfaces)
- **Bluetooth-Adapter-Adresse** rotieren falls längerfristig in einem Raum

---

## Bedienanleitung

### Visueller Durchlauf

<table>
  <tr>
    <td align="center" width="33%"><img src="docs/screenshots/01_splash.png" width="240"><br><sub><b>1. Splash</b><br>Sensor-Self-Check</sub></td>
    <td align="center" width="33%"><img src="docs/screenshots/02_preset_menu.png" width="240"><br><sub><b>2. Preset-Menü</b><br>STANDARD / DEEPSCAN / CUSTOM</sub></td>
    <td align="center" width="33%"><img src="docs/screenshots/03_scan_config.png" width="240"><br><sub><b>3. Scan-Config</b><br>Toggle-Screen, ←→ schaltet</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshots/04_scan_live.png" width="240"><br><sub><b>4. Live-Scan</b><br>Round, ETA, Live-Counter</sub></td>
    <td align="center"><img src="docs/screenshots/05_report_card.png" width="240"><br><sub><b>5. Report-Card</b><br>Threat-Level + Top-Findings</sub></td>
    <td align="center"><sub><b>6. Report scroll</b><br>(Screenshot folgt sobald<br>der Full-Report-Test grün ist)</sub></td>
  </tr>
</table>

### Tastenbelegung

| Taste | Funktion |
|---|---|
| **D-Pad ↑ / ↓** | Auswahl bewegen / scrollen |
| **D-Pad ← / →** | Toggle umschalten / Wert ändern (Stepper) |
| **A** (grün) | Bestätigen / Weiter / Ja / Pause–Resume |
| **B** (rot) | Zurück / Nein / Skip / Stop |
| **Power / lang B** | Notbeenden (überall) |

A ist immer „die positive Aktion", B ist immer „die negative aber unschädliche
Aktion". Im Post-Scan kann man mit B durch die ganze Kette durchklicken ohne
etwas zu verändern.

### Ablauf

1. **Splash** — 2 s Logo + Sensor-Self-Check.
2. **Preset-Menü** — `STANDARD` / `DEEPSCAN` / `CUSTOM` wählen mit ↑↓, **A** = weiter, **B** = Pager runterfahren.
3. **Scan-Config** — Toggle-Screen mit allen Sensoren. ↑↓ Zeile, ←→ umschalten, **A** = Scan starten, **B** = zurück.
4. **Live-Scan** — Round-Counter, ETA, Progress-Bar, Live-Counter (WiFi / BT / GPS / IMSI / Deauth).
   - **A** = Pause / Resume (nur die laufende Runde — Background-Watcher laufen weiter).
   - **B** = Stop. Confirm-Dialog: **A = Continue** (weiter scannen), **B = Stop** (wirklich abbrechen).
5. **Post-Scan** — Sequenz aus 4 Schritten. **A** = Aktion ausführen, **B** = Skip + weiter.
   - **(1)** Silent-SMS-Check der letzten 2 h → **(2)** IMSI-Anomalien → **(3)** OpenCelliD-Upload → **(4)** IMEI-Rotation.
6. **Report-View** — Threat-Card mit Top-Findings.
   - **A** = vollständigen Markdown-Report scrollen (UP/DN, B = zurück).
   - **B** = Payload beenden, Pager-OS lädt wieder.

> **Tipp:** Wenn auf dem Display Zeichen als `?` erscheinen oder die Schrift schwammig wirkt,
> ist Steelfish (der OS-Default) gewählt worden statt DejaVu.
> `opkg install -d mmc font-ttf-dejavu` und Argus neu starten löst das.

---

## Installation

```bash
ssh pager
cd /root/payloads/user/reconnaissance/
git clone --recurse-submodules https://github.com/tschakram/argus-pager-2.0.git
cd argus-pager-2.0
git config core.hooksPath hooks                 # OPSEC-Pre-Commit aktivieren
cp config.example.json config.json              # dann Keys / GPS-Zonen eintragen

# Falls schon vorher geklont (ohne --recurse-submodules):
git submodule update --init --recursive

# Loot-Verzeichnisse:
mkdir -p /root/loot/argus/{pcap,reports,logs,ignore_lists,screenshots}

# Mudi vorbereiten (auf Mudi):
ssh mudi 'mkdir -p /root/loot/raypager/{cell_cache,upload_queue,reports}'
```

Starten über das Pager-Payload-Menü → `reconnaissance` → `argus-pager-2.0`.

### Voraussetzungen

| Komponente | Wert / Pfad |
|---|---|
| Pager | WiFi Pineapple Pager, OpenWrt 24.10.1, mipsel_24kc, Python 3.11 |
| `pagerctl` | `/mmc/root/lib/pagerctl/{libpagerctl.so,pagerctl.py}` (Loki/Pagergotchi installieren das) |
| Mudi V2 | GL-E750 + Quectel-Modem + u-blox M8130 USB-Dongle (`/dev/ttyACM0`) |
| Python-Deps | nur stdlib (keine pip-Installation) |

---

## Test + Debug

### Deauth-Detector offline testen

Validiert die Detection-Logik ohne dass ein einziges Frame durch die Luft fliegt:

```bash
python3 tools/deauth_test.py
# → OK - all 4 scenarios passed.
```

### Screenshot vom LCD machen

Während Argus läuft, zeigt der Pineapple-Web-Preview nichts mehr (pagerctl
hat den Framebuffer übernommen). Mit dem Helper kommt man trotzdem an
das Bild dran:

```bash
ssh pager 'python3 /root/payloads/user/reconnaissance/argus-pager-2.0/tools/screenshot.py /tmp/shot.png'
scp pager:/tmp/shot.png ./
```

Liest direkt aus `/dev/fb0`, dekodiert RGB565 und rotiert 270° zurück
in Landscape. Funktioniert während die UI läuft.

---

## Roadmap

### v2.0 ALPHA (jetzt)
- [x] UI-Skeleton (`pagerctl`-Screens) und Preset-Definitionen
- [x] Deauth-Flood-Detector + Offline-Test
- [x] ASCII-clean UI, Font-Auto-Discovery, scrollbare Quality-Lights
- [x] Synthetic Report Fallback wenn keine cyt/raypager .md vorliegt
- [x] Screenshot-Tool für die Doku
- [x] Submodule (`cyt`, `raypager`) eingehängt
- [ ] Erste Live-Tests auf dem Pager mit vollem Report

### v2.1+
Weitere Detektoren-Backlog mit Priorität sortiert:
**[docs/features.md](docs/features.md#geplant-für-v21)**.

---

## Lizenz / Verwendung

Privates Tooling, keine offizielle Lizenz. Verwendung auf eigene Verantwortung —
diese Software darf **ausschließlich auf eigener Hardware und gegen eigene Geräte**
eingesetzt werden. Counter-Surveillance ist legal — Surveillance gegen Dritte nicht.
