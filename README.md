# argus-pager 2.0

**Counter-Surveillance & IMSI-Catcher Detection für den WiFi Pineapple Pager — komplett neu mit nativer `pagerctl`-UI.**

argus-pager 2.0 ersetzt das DuckyScript/Bash-Frontend von v1.3 durch eine schlanke
Python-Anwendung mit direktem Framebuffer-Zugriff über
[`pagerctl`](https://github.com/pineapple-pager-projects/pineapple_pager_pagerctl).
Die Bedienung folgt dem Look-and-Feel des Pineapple Pager OS (schwarz / grüner Akzent),
nutzt das D-Pad und vermeidet die Limitierungen von `NUMBER_PICKER` / `SHOW_REPORT`.

> **Status:** Skeleton — UI- und Engine-Module sind angelegt, Submodule
> `cyt` (Chasing-Your-Tail-NG) und `raypager` (IMSI-Catcher / Mudi-Backend)
> werden im ersten Lauf eingehängt.

---

## Was ist neu gegenüber v1.3?

| | v1.3 | **2.0** |
|---|---|---|
| Frontend | 1488 Zeilen Bash + DuckyScript-Builtins | Python + `pagerctl` (480×222 Framebuffer) |
| Modi | 7 überlappende Modi (0–6) | **3 Presets**: `STANDARD`, `DEEPSCAN`, `CUSTOM` |
| Pre-Scan-Config | nacheinander durch NUMBER_PICKER abgefragt | **Toggle-Screen** mit Schiebereglern, alles auf einen Blick |
| Pause/Resume | nicht möglich | **Pause** stoppt nur die laufende Runde, Watcher laufen weiter |
| Live-Feedback | reine LED + LOG-Zeilen | **Live-Screen** mit Restzeit, Datenqualitäts-Ampel, Devices-Counter |
| Daten-Qualität | implizit | **explizit**: „CYT ✓ ausreichend / Hotel-Scan ⚠ noch 1 Runde" |
| IMSI / Silent-SMS | optionaler Daemon | **immer passiv im Hintergrund**, sobald Mudi erreichbar |
| OPSEC | gitignore + Hook | gitignore + Hook + verschärfte MAC/Coord-Regex |

---

## Hardware & Voraussetzungen

| Komponente | Modell / Pfad |
|---|---|
| Pager | WiFi Pineapple Pager (OpenWrt 24.10.1, mipsel_24kc, Python 3.11) |
| WiFi | `wlan1mon` (Monitor-Mode), `wlan0mon` reserviert |
| BT | BlueZ 5.72, `btmon` |
| Pager-GPS | (intern) |
| Mudi V2 | GL-E750 mit Quectel-Modem + u-blox M8130 USB-Dongle (`/dev/ttyACM0`, 4800 Baud) |
| `pagerctl` | `/mmc/root/lib/pagerctl/{libpagerctl.so,pagerctl.py}` (vorausgesetzt) |
| Python-Deps | nur stdlib — keine pip-Installation nötig |

Pre-flight Check (aus `payload.sh`): existiert `/mmc/root/lib/pagerctl/pagerctl.py`?
Wenn nein → `LOG red "pagerctl missing — install Loki/Pagergotchi first"` + exit.

---

## Presets

Drei Profile, dazu der freie `CUSTOM`-Modus.
Hintergrund-Watcher (`imsi_monitor`, `silent_sms`) laufen **immer passiv**, solange Mudi erreichbar ist —
sie sind **keine** Modus-Komponente, sondern systemweite Sensoren.

### STANDARD — Alltag (Default)

`4 × 90 s = 6 min Scan`

| Sensor | aktiv |
|---|:-:|
| WiFi (Probe-Analyse) | ✓ |
| Bluetooth (BT/BLE-Scan) | ✓ |
| GPS Pager (intern) | ✓ |
| GPS Mudi (u-blox) | ✓ |
| Cell / IMSI-Lookup | ✓ |
| Cross-Report (Multi-Round-Persistenz) | ✓ |
| Cameras (Hotel-Scan) | ✗ |
| Shodan / WiGLE-Lookups | ✗ |

Ergebnis: WiFi-Stalker, BT-Tracker (AirTag/SmartTag/Tile), Cell-Anomalien, Geräte
die über mehrere Scans hinweg an verschiedenen Orten persistieren.

### DEEPSCAN — Stationär, lange Session

`6 × 120 s = 12 min Scan`

Alles aus STANDARD plus:

| Sensor | aktiv |
|---|:-:|
| Cameras (Hotel-Scan + Camera-Activity) | ✓ |
| Shodan / WiGLE-Lookups | ✓ |

Empfohlen wenn der Pager > 10 min liegen bleiben kann.
Aktiviert die teuren API-Lookups und die Bandbreiten-Analyse für aktive Spy-Cams.

### CUSTOM — Manuell

Default `3 × 60 s`, alle 8 Toggles frei einstellbar im **Scan-Config-Screen**.
Empfohlen für Sondersituationen: nur BT (passiv im Café), nur Cell (Auto-Fahrt),
„Stealth" ohne Vibration und LED.

---

## Bedienanleitung (Quick Start)

### Tastenbelegung am Pager

| Taste | Funktion |
|---|---|
| **D-Pad ↑ / ↓** | Auswahl bewegen / scrollen |
| **D-Pad ← / →** | Toggle umschalten / Wert ändern (Stepper) |
| **A** (grün) | Bestätigen / Weiter / Ja / Pause-Resume |
| **B** (rot) | Zurück / Nein / Skip / Stop (im Scan) |
| **Power / lang B** | Notbeenden (überall) |

A ist immer „die positive Aktion", B ist immer „die negative aber unschädliche Aktion".
Im Post-Scan kann man mit B durch die ganze Kette durchklicken ohne etwas zu verändern.

### Ablauf eines Scans

1. **Splash** — 2 s Logo + Sensor-Self-Check (WiFi, BT, GPS, Mudi).
2. **Preset-Menü** — `STANDARD` (4×90s), `DEEPSCAN` (6×120s), `CUSTOM` (frei).
   - ↑/↓ wählen, **A** = weiter, **B** = Pager runterfahren.
3. **Scan-Config** — Toggle-Screen mit allen Sensoren.
   - ↑/↓ Zeile, ←/→ umschalten oder Wert verändern (Rounds 1–12, Duration 30–300 s).
   - **A** = Scan starten, **B** = zurück zum Preset-Menü.
4. **Live-Scan** — Round-Counter, ETA, Datenqualitäts-Ampel, Live-Counter
   (WiFi/BT/IMSI/GPS/Deauth).
   - **A** = Pause / Resume (nur die laufende Runde — Background-Watcher laufen weiter).
   - **B** = Stop (Confirm-Dialog: A = wirklich stoppen, B = doch weiter).
5. **Post-Scan** — Sequenz aus 4 Schritten. **A** = Aktion ausführen, **B** = Skip + weiter.
   - **(1)** Silent-SMS-Check der letzten 2 h.
   - **(2)** IMSI-Anomalie-Zusammenfassung.
   - **(3)** OpenCelliD-Upload (nur falls Queue > 0).
   - **(4)** IMEI-Rotation (Radio off → Blue Merle → Radio on).
6. **Report-View** — Threat-Card mit Top-Findings.
   - **A** = vollständigen Markdown-Report scrollen (UP/DN, B = zurück).
   - **B** = Payload beenden, Pager-OS lädt wieder.

### Tipps für den Alltag

- Wenn nichts passiert nach **A** in „View Report": cyt + raypager Submodule sind noch nicht
  gemountet. Argus zeigt dann eine **In-Memory-Zusammenfassung** statt eines fehlenden
  Markdown-Reports — Inhalt also trotzdem sichtbar.
- Wenn auf dem Display Zeichen als `?` erscheinen: DejaVu-Font installieren —
  `opkg install -d mmc font-ttf-dejavu` — Argus nutzt ihn dann automatisch beim
  nächsten Start. Steelfish (der Standard-Font des Pineapple OS) hat keine Glyphen
  für viele Sonderzeichen.
- Notabbruch jederzeit mit der Power-Taste — `payload.sh` setzt einen `kill_script`
  in `/root/loot/argus/logs/last_kill.sh`, den man via SSH auch von Hand triggern kann
  falls Python hängt.

---

## Workflow / UI-Flow

```
┌────────┐   ┌────────────┐   ┌──────────────┐   ┌───────────┐   ┌────────────┐   ┌──────┐
│ SPLASH │ → │ Preset-Menü│ → │ Scan-Config  │ → │ Scan-Live │ → │ Post-Scan  │ → │Report│
│        │   │ (STANDARD/ │   │ (Schiebe-    │   │ (Round X/Y│   │ SMS / IMEI │   │ View │
│        │   │ DEEPSCAN/  │   │  regler,     │   │  Restzeit │   │ / Upload   │   │      │
│        │   │ CUSTOM)    │   │  Rounds×Dur) │   │  Quality) │   │            │   │      │
└────────┘   └────────────┘   └──────────────┘   └───────────┘   └────────────┘   └──────┘
                                                       │
                                                  Pause [A]
                                                  Stop  [B]
```

### 1. Splash (2 s)
Logo + Version. LED `cyan blink`. Sensor-Self-Check (WiFi mon, Mudi reachable, GPS dongle).

### 2. Preset-Menü
D-Pad ↑/↓ zum Scrollen, **A** = wählen, **B** = Pager runterfahren.

### 3. Scan-Config (Schieberegler)
Toggles links, Werte rechts. **L/R** schaltet ein Toggle, **↑/↓** wechselt Zeile,
**A** startet, **B** zurück.
Bei `STANDARD`/`DEEPSCAN` sind die Toggles vor-gesetzt aber editierbar.

### 4. Scan-Live
Während der Aufnahme:

* Round-Counter `2 / 4`, Restzeit `01:23`, Gesamt-Progress-Bar
* **Datenqualitäts-Ampel** (rechnet aus `data_quality.py`):
  * `CYT` → grün ab 180 s gesamt
  * `Cross-Report` → grün ab Runde 3
  * `Hotel-Scan` → grün ab 240 s
  * `Shodan` → grün ab Runde 2
* Live-Counter: WiFi-Devices, BT-Devices, IMSI-Status, GPS-Lock
* **A** pausiert (nur aktuelle Runde, Watcher laufen weiter)
* **B** stoppt komplett (Confirm-Dialog)

### 5. Post-Scan-Sequenz
Sequenz, kein Menü:

1. **Silent-SMS-Check** — letzte 2 h auswerten, Treffer rot anzeigen
2. **IMSI-Alerts** — `imsi_alerts.jsonl` der letzten 2 h zusammenfassen
3. **OpenCelliD-Upload** — Queue-Counter + `[A] Upload` / `[B] Skip`
4. **IMEI-Rotation** — `[A] Rotate` (radio off → blue_merle → on) / `[B] Keep`

### 6. Report-View
Kompakte Threat-Card: Ampel + Top-Findings. **A** öffnet Markdown-Report im pagerctl-Scroll-View, **B** beendet.

---

## Feature-Katalog (vollständig)

### WiFi-Counter-Surveillance (cyt)
- Probe-Request-Persistenz mit konfigurierbarem Threshold (default `0.6`)
- LAA-Bit-Erkennung (Locally Administered = Spoofed-MAC-Indikator)
- IEEE-OUI-Lookup (offline cache, wöchentlich aktualisiert)
- WiGLE-Lookup für SSID/MAC (optional, API-Key)
- Time-Window-Bucketing: recent / medium / old / oldest

### Deauth-Flood Detection (neu in 2.0)
Passiver `tcpdump`-Watcher (`core/deauth_monitor.py`), läuft parallel zum WiFi-Capture
solange der WiFi-Toggle aktiv ist:

- Filter: `type mgt and (subtype deauth or subtype disassoc)` auf `wlan1mon`
- Ring-Buffer der letzten N Sekunden (config: `deauth.window_s`, default 10s)
- Ab `flood_threshold` Frames/s (default 5) wird ein **Flood-Event** geloggt
- Pro-Source/Destination-MAC-Counters um Angreifer vs. Ziel zu trennen
- Live-Anzeige im Scan-Screen (rot bei Flood, gelb bei elevated rate)
- Einträge gehen nach `loot/argus/deauth.jsonl`, Summary nach `deauth_summary.json`
- Threat-Level **HIGH** bei jedem Flood, **MEDIUM** ab 30 frames, sonst nur Notiz

### BT/BLE-Counter-Surveillance (cyt)
- BLE-Advertisement via `btmon` (Service-UUIDs, Appearance, Name, RSSI)
- Tracker-Erkennung: AirTag (Apple), SmartTag (Samsung), Tile, Chipolo, Eddystone
- Risk-Scoring: `RISK_NONE` / `LOW` / `MEDIUM` / `HIGH`
- BT-Classic SDP-Probing (optional)

### IMSI-Catcher-Detection (raypager / Mudi)
5-Layer-Erkennung über `AT+QENG="servingcell"`:
1. **RAT-Downgrade** — LTE → WCDMA / GSM
2. **Ciphering-Plaintext** — `A5/0` (GSM) / `EEA0` (LTE)
3. **Timing-Advance-Anomalie** — `TA = 0` + RSRP < −100 dBm
4. **Neighbor-Cell-Collapse** — plötzlicher Verlust aller Nachbarn
5. **TAC-Change auf gleicher Cell-ID** — Cell-Cloning-Indikator

### Silent-SMS-Watcher (raypager / Mudi)
- TP-PID `0x40` → Silent-SMS (Type 0)
- TP-PID `0x7F` / `0x3E` / `0x3F` → OTA-Provisioning (SIM/ME)
- TP-DCS `Class 0` → Flash-SMS
- TP-DCS 8-bit → Binary-SMS
- Logged nach `silent_sms.jsonl`, Dedup-Cache, optional `--purge-binary`

### Hotel-Scan / Spy-Cam-Detection (cyt)
- WiFi-Beacon: 64 OUI-Prefixe (Hikvision, Dahua, Reolink, Wyze, Arlo, Ring, …)
- 51 SSID-Pattern (`ipcam`, `cctv`, `nvr`, `esp32cam`, …)
- BLE: Service-UUIDs `ffe0`/`ffe1` (Camera Control / Stream)
- **Camera-Activity**: Bandbreiten-Spikes aus Data-Frames (>200 KB/s)

### Cell-Tower-Verification (raypager / Mudi)
- OpenCelliD-Lookup mit 24 h-Cache
- Threat-Level: `CLEAN` / `UNKNOWN` / `MISMATCH` / `GHOST` / `NOSERVICE`
- Upload-Queue für eigene Messungen (gzip-CSV, multipart-Upload)

### Cross-Report (cyt)
- Persistenz von MACs/Devices über mehrere Scans hinweg
- Gewichtung nach GPS-Distanz zwischen Sichtungen
- Trigger ab 3 Runden (`cross_report_min_rounds`)

### IMEI-Rotation (raypager / Mudi)
- `blue_merle.py rotate [-r|-d] [--poweroff]`
- Sequenz: `AT+CFUN=4` (Radio off) → IMEI-Generator → Verify
- `random` oder `IMSI-deterministic`

### Watch-List (cyt)
- **Static** — Gerät nur in bekannter Zone OK (Geofencing, Haversine)
- **Dynamic** — Gerät folgt dem Träger (Tracking-Erkennung)
- Hinzufügen über `Report-View` → `Add to Watch-List`

---

## Repo-Struktur

```
argus-pager-2.0/
├── README.md                 (dieses File)
├── CHANGELOG.md              (1.3 → 2.0 Migration)
├── .gitignore                OPSEC
├── hooks/pre-commit          OPSEC-Guard (GPS / MAC / API-Keys)
├── config.example.json       Platzhalter — niemals echte Coords/Keys
├── payload.sh                minimaler Launcher
├── python/
│   ├── main.py               Haupt-Entry: Screen-Stack-Loop
│   ├── ui/
│   │   ├── theme.py          Farben, Fonts, LED-/Vibrate-Helper
│   │   ├── widgets.py        Toggle, Slider, List, ProgressBar, AlertCard
│   │   └── screens/
│   │       ├── splash.py
│   │       ├── preset_menu.py
│   │       ├── scan_config.py
│   │       ├── scan_live.py
│   │       ├── post_scan.py
│   │       └── report_view.py
│   ├── core/
│   │   ├── presets.py        STANDARD / DEEPSCAN / CUSTOM Defs
│   │   ├── scan_engine.py    Capture-Orchestrator (tcpdump / btmon / iw)
│   │   ├── scheduler.py      Pause / Resume / Stop State-Machine
│   │   ├── data_quality.py   „genug Daten für Mode X?"
│   │   ├── mudi_client.py    SSH-Client → gps / cell / imsi / sms / blue_merle
│   │   └── post_scan.py      SMS → IMSI-Summary → Upload → IMEI
│   ├── assets/
│   │   ├── fonts/DejaVuSansMono.ttf
│   │   └── images/argus_logo.png
│   └── lib/                  (gitignored — system pagerctl wird verwendet)
├── cyt/                      submodule → chasing-your-tail-pager (main)
└── raypager/                 submodule → raypager (master)
```

---

## Installation auf dem Pager

```bash
# Auf dem Pager (via SSH):
cd /root/payloads/user/reconnaissance/
git clone --recurse-submodules git@github.com:tschakram/argus-pager-2.0.git
cd argus-pager-2.0
git config core.hooksPath hooks
cp config.example.json config.json     # dann Keys / GPS-Zonen eintragen

# pagerctl prüfen (sollte schon da sein wenn Loki/Pagergotchi installiert):
ls /mmc/root/lib/pagerctl/libpagerctl.so

# Loot-Verzeichnisse anlegen:
mkdir -p /root/loot/argus/{pcap,reports,logs,ignore_lists}

# Mudi vorbereiten (auf Mudi):
ssh mudi 'mkdir -p /root/loot/raypager/{cell_cache,upload_queue,reports}'
```

Starten über das normale Pager-Payload-Menü → `reconnaissance` → `argus-pager-2.0`.

---

## Roadmap

### v2.0 ALPHA (jetzt)
* [x] UI-Skeleton (`pagerctl`-Screens)
* [x] Preset-Definitionen + scan_engine + mudi_client + post_scan
* [x] Deauth-Flood-Detector (`core/deauth_monitor.py`)
* [x] ASCII-clean UI (DejaVu wenn vorhanden, Steelfish fallback)
* [x] Synthetic Report Fallback wenn keine cyt/raypager .md vorliegt
* [ ] Erste Live-Tests auf dem Pager
* [ ] Submodule (`cyt`, `raypager`) per `git submodule add` einhängen
* [ ] Migration-Guide v1.3 → 2.0

### v2.1+ — Geplante Detektoren

Weitere Angriffsvektoren, die in 2.x hinzukommen sollen. Reihenfolge nach
Aufwand × Nutzen geordnet — die erste Hälfte ist passiv und billig zu implementieren,
weiter unten wird's invasiver.

| # | Vektor | Erkennung | Status |
|---|---|---|---|
| 1 | **Beacon-Flood / Pineapple Mode** | >X random SSIDs von wenigen MACs in kurzer Zeit | TODO |
| 2 | **Evil Twin / SSID-Klon** | Gleiche SSID, mehrere BSSIDs gleichzeitig sichtbar (eines davon stärker als das echte) | TODO |
| 3 | **CSA-Spoofing (Channel Switch Announcement)** | CSA-IE mit Sprung in fremden Channel ohne legit Reason | TODO |
| 4 | **KARMA / PineAP** | AP antwortet auf jeden Probe-Request mit eigenem ACK (jedes SSID „existiert") | TODO |
| 5 | **WPS PIN-Brute-Signs** | Wiederholte WPS-Auth-Versuche zur gleichen BSSID | TODO |
| 6 | **PMKID-Exfil** | EAPOL Frame 1/4 ohne Frame 2/4 (hashcat-22000-Pattern) | TODO |
| 7 | **Probe-Storm** | Eine Source-MAC die >Y Probe-Requests/s sendet (Mapping-Verhalten) | TODO |
| 8 | **AWDL / Apple Continuity-Probes** | mDNS/Bonjour aus unbekannter Quelle (Sniff-Indikator) | TODO |
| 9 | **MFP-/802.11w-Status der Umgebung** | RSN-IE prüfen — ungeschützte APs sind deauth-anfällig | TODO |
| 10 | **Hidden-SSID-Probes von Watch-List MACs** | Probe an `len 0` SSID kombiniert mit MAC der schon im Tracker steckt | TODO |
| 11 | **BLE GATT-Probing** | GATT-Read-Anfragen von unbekannten Centrals an unsere Devices | TODO |
| 12 | **NFC/UWB/AirDrop Recon** | UWB-CIR-Patterns aus iPhone Find-My-Tracker-Mode | RESEARCH |
| 13 | **Rogue mDNS / LLMNR / NBT-NS** | Vergiftete Name-Lookups im LAN (nur wenn assoziert) | TODO |
| 14 | **Cellular Jamming-Indikatoren** | RSSI > X aber kein Service / NOSERVICE Threat-Level | teils da (raypager) |
| 15 | **Bluetooth Spam-Frames** | BLE-Adv-Stürme mit zufälligen Namen (Apple/Samsung Pairing-Spam) | TODO |

Vorgehen ab v2.1: 1–4 zuerst (alles aus dem laufenden tcpdump zu extrahieren, kein
zusätzlicher Capture nötig), 5–7 dann (separate Filter), 8–15 nach Bedarf.

---

## Lizenz / Verwendung

Wie v1.3: privates Tooling, keine offizielle Lizenz. Verwendung auf eigene Verantwortung —
diese Software darf **ausschließlich auf eigener Hardware und gegen eigene Geräte** eingesetzt werden.
Counter-Surveillance ist legal — Surveillance gegen Dritte nicht.
