# Detektoren — Detailbeschreibung

Diese Seite erklärt jeden Detektor einzeln: **was wird erkannt, wie funktioniert
das technisch, welche Daten gehen in den Report, und wann meldet er Alarm.**

Reihenfolge nach Stack-Schicht: WiFi → Bluetooth → Cellular → SMS → Spy-Cam.

---

## WiFi-Layer

### Probe-Request-Persistenz (CYT)

**Bedrohungsmodell:** Ein Stalker bewegt sich mit dir. Sein Handy / Wearable
sendet zyklisch Probe-Requests an seine Heim-SSIDs. Diese Probe-Requests
identifizieren das Gerät über die MAC-Adresse, auch wenn die SSID-Liste
einmalig ist.

**Detection:**
- `tcpdump` auf `wlan1mon` zeichnet alle Probe-Request-Frames auf
- Pro Source-MAC wird ein **Persistence-Score** (0.0–1.0) berechnet:
  *Anteil der Time-Buckets in denen die MAC mindestens 1 mal aufgetaucht ist*
- Threshold ist konfigurierbar (`config.surveillance.persistence_threshold`,
  default `0.6` = in mind. 60% der Buckets gesehen)
- LAA-Bit (`Locally Administered`) wird separat geflaggt — das ist ein
  starker Indikator für Spoofed-MAC (iOS/Android randomisieren so)
- IEEE-OUI-Lookup gegen offline cache → Hersteller-Name wenn nicht LAA

**Im Report:** `cyt analysis OK: <N> pcap(s)` plus eine Tabelle der MACs mit
Persistence ≥ Threshold.

---

### Cross-Report (CYT)

**Bedrohungsmodell:** Ein Gerät wurde an mehreren weit auseinanderliegenden
Orten gesehen. Das ist „Tracking-Verhalten" und nicht erklärbar mit einer
festen Installation in einem Café.

**Detection:**
- Persistente MACs aus mehreren Scan-Sessions werden in einer SuspectsDB
  vorgehalten (`/root/loot/argus/suspects.db`)
- Zwischen Sichtungen wird der **Haversine-Abstand** berechnet (GPS-Lock
  vorausgesetzt)
- Ein Gerät, das mit **min. 3 Reports** in **>200 m Abstand** voneinander
  gesehen wurde, wird als „Cross-Report-Hit" geflaggt

**Im Report:** `cross-report flagged persistent devices`. Threat-Level
`MEDIUM`.

**Konfiguration:** `data_quality.cross_report_min_rounds` (default 3).

---

### Deauth-Flood-Detector (NEU in 2.0)

**Bedrohungsmodell:** Ein Angreifer schickt 802.11 Deauthentication- oder
Disassociation-Frames mit gespoofter Source-MAC. Ziel: dein Handy aus dem
WLAN werfen → es muss neu assoziieren → EAPOL-Handshake fängt der Angreifer
für hashcat ab. Oder einfach DOS gegen dich.

Das ist der mit Abstand häufigste **aktive** WLAN-Angriff (Pineapple,
mdk4, aireplay-ng, MITM-Frameworks).

**Detection:**
- Eigener `tcpdump`-Subprocess parallel zum normalen WiFi-Capture
- Filter: `type mgt and (subtype deauth or subtype disassoc)` auf `wlan1mon`
- Ring-Buffer der letzten N Sekunden Timestamps (`config.deauth.window_s`,
  default `10`)
- **Flood-Threshold** (`config.deauth.flood_threshold`, default `5/s`):
  ab dieser Rate wird ein Flood-Event geloggt
- Per-Source/Destination-MAC-Counters trennen Angreifer von Ziel
- Live-Anzeige im Scan-Screen: rote Zeile bei Flood, gelb bei elevated

**Im Report:**
- `DEAUTH FLOOD: <N> bursts, <M> frames` → Threat **HIGH**, LED + Vibrate
- `deauth: elevated <M> frames` → Threat **MEDIUM** (>30 Frames gesamt)
- `deauth: <M> frames (background)` → kein Threat (Hintergrund-Verkehr)

**Logfiles:** `/root/loot/argus/deauth.jsonl` (jedes Flood-Event eine Zeile)
plus `deauth_summary.json` am Sessionende.

**Test:** `python3 tools/deauth_test.py` — 4 Offline-Szenarien, kein Funkverkehr.

---

### Hotel-Scan (CYT)

**Bedrohungsmodell:** Versteckte Kamera oder NVR im Hotelzimmer / Airbnb.

**Detection (multi-source):**
- WiFi-Beacons → 64 OUI-Prefixes von Kamera-Herstellern (Hikvision, Dahua,
  Reolink, Wyze, Arlo, Ring, EZVIZ, Axis, Tuya, …)
- 51 SSID-Patterns (`ipcam`, `cctv`, `nvr`, `esp32cam`, …)
- BLE-Service-UUIDs `ffe0`/`ffe1` (Camera Control / Stream)
- Optional: Shodan-Lookup für Cameras-Vulnerabilities (CVEDB)

**Im Report:** `hotel_scan: suspicious cameras found` + Liste mit
MAC, Hersteller, Signal-Stärke. Threat **HIGH**.

---

### Camera-Activity (CYT)

**Bedrohungsmodell:** Eine Kamera die zwar still aussieht, aber gerade
Bandbreite über das WLAN fährt → wird also gerade aktiv genutzt.

**Detection:**
- PCAP wird nach Data-Frames mit hohem Bytes/Sekunde-Spike durchsucht
- Threshold default 200 KB/s — typisch für eine 720p-RTSP-Kamera
- Spikes müssen >2 s anhalten (kein Fluke)

**Im Report:** `camera activity spikes detected`. Threat **MEDIUM**.

---

## Bluetooth-Layer

### BT-Tracker-Erkennung (CYT)

**Bedrohungsmodell:** Apple AirTag / Samsung SmartTag / Tile / Chipolo
am Rucksack, in der Jacke, am Auto.

**Detection:**
- `btmon` capture wird gegen die TRACKER_COMPANY_IDs gematcht:
  - Apple Find My (76)
  - Samsung SmartTags (117)
  - Microsoft / Surface (224)
  - Tile (155)
- Service-UUIDs als Backup: `FEED`, `FEEA`, `FE9A`, `FD44`, `FABE`
- `has_tracker` Flag im fingerprint_device Return

**Im Report:** Liste der erkannten Tracker mit RSSI-Verlauf.
**False-Positive-Filter:** ein- und ausgeschaltet wird ein Tracker nicht
geflaggt — er muss in **min. 2 aufeinanderfolgenden Scans** sichtbar sein.

---

### BT-Risk-Scoring

**Bedrohungsmodell:** Unbekannte BLE-Geräte in Reichweite die kein Tracker
sind aber dennoch verdächtig (z.B. ein Spy-Cam-Modul, ein BLE-Beacon-Logger).

**Score:**
- `RISK_NONE` — bekannte konsumer Hardware (JBL Speaker, Garmin Watch)
- `RISK_LOW` — generisches BLE-Gerät, neutral
- `RISK_MEDIUM` — unbekannter Hersteller, kein OUI-Match
- `RISK_HIGH` — Hersteller im IoT/Spy-Cam OUI-Set + verdächtige
  Service-UUIDs

---

## Cellular-Layer (Mudi V2)

Alle Detektoren in dieser Sektion laufen über `AT+QENG="servingcell"` und
verwandte AT-Kommandos auf dem Quectel-Modem im Mudi V2.

### IMSI-Catcher-Monitor (5-Layer-Erkennung)

**Bedrohungsmodell:** Stingray, Rayhunter-Class Catcher, oder eine
Behörde mit IMSI-Catcher-Equipment in der Nähe. Der Catcher zwingt
dein Telefon in eine schwächere Verschlüsselung um den Funkverkehr
mitlesen zu können.

**Detection in 5 Schichten:**

| # | Anomalie | Indikator |
|---|---|---|
| 1 | **RAT-Downgrade** | Plötzlich LTE → WCDMA / GSM |
| 2 | **Cipher-Plaintext** | A5/0 (GSM) / EEA0 (LTE) — keine Verschlüsselung |
| 3 | **TA-Anomalie** | Timing-Advance = 0 bei RSRP < −100 dBm (unmöglich fern) |
| 4 | **Neighbor-Cell-Collapse** | Plötzlicher Verlust aller Nachbar-Cells → Force-Lock auf Fake-BTS |
| 5 | **TAC-Change auf gleicher Cell-ID** | Cell-Cloning-Indikator |

State-Files: `imsi_alerts.jsonl`, `rat_history.json` auf dem Mudi.
**Im Report:** `IMSI: <N> alerts: HIGH=<x> MED=<y>`.

---

### Cell-Tower-Verifikation (OpenCelliD + WiGLE + UnwiredLabs)

**Bedrohungsmodell:** Du bist an einem Cell-Tower angemeldet, der
nicht in den großen Datenbanken auftaucht — entweder ein neuer legit
Tower (Upload-Queue → wir senden's hin) oder ein Spoof.

**Threat-Level:**
- `CLEAN` — Tower ist in der DB, GPS-Position passt
- `UNKNOWN` — Tower nicht in der DB → Upload-Queue
- `MISMATCH` — Tower in der DB, aber GPS-Position weicht > 5 km ab
- `GHOST` — Tower in keiner der 3 Quellen → starker Spoof-Indikator
- `NOSERVICE` — kein Service trotz vorheriger Connection (Jamming?)

**API-Quellen:**
- OpenCelliD (primär, free, 100 lookups/day)
- WiGLE (sekundär, free)
- UnwiredLabs (tertiär, free, 100 lookups/day)

Der Threat-Level kombiniert alle 3.

---

### IMEI-Rotation (Blue Merle, opt-in)

**Bedrohungsmodell:** Du wurdest bereits identifiziert — IMEI ist im
SS7-Netz oder via lokalem Catcher geleakt. IMEI-Wechsel + ggf.
SIM-Wechsel hilft dabei die Spur zu kappen.

**Workflow (auf Knopfdruck im Post-Scan):**
1. `AT+CFUN=4` — Radio aus (verhindert dass die alte IMEI noch leakt)
2. `blue_merle.py rotate --deterministic` — IMEI generiert aus IMSI-Hash
3. `AT+CFUN=1` — Radio wieder an

**Im Report:** `IMEI: rotated: ...<last 6 digits>` oder `IMEI: kept`.

---

## SMS-Layer

### Silent-SMS-Watcher

**Bedrohungsmodell:** Eine Behörde / ein Carrier-Insider sendet dir eine
„Stille SMS" — sie kommt nie im Posteingang an, der Provider sieht aber
deine aktuelle Cell-ID und triangulert dich.

**Detection:**
- Daemon auf dem Mudi (`silent_sms.py`) pollt alle 60 s `AT+CMGL=4` (PDU)
- TP-PID + TP-DCS werden dekodiert

| Pattern | Bedeutung |
|---|---|
| TP-PID `0x40` | **Silent SMS (Type 0)** — Ping-SMS, taucht nirgends auf |
| TP-PID `0x7F` | **SIM Data Download** — OTA-Kommando direkt zur SIM |
| TP-PID `0x3E/0x3F` | **ME Data Download** — OTA-Kommando ans Gerät |
| TP-DCS class 0 | **Flash SMS** — Display-only, kein Storage |
| TP-DCS 8-bit | **Binary SMS** — Nicht-Text-Payload |

**Logfile:** `/root/loot/raypager/silent_sms.jsonl`.
**Im Report:** `SMS: <N> events: SILENT_SMS,FLASH_SMS,...`.

Abschalten via `config.silent_sms.watch_on_start = false`.

---

### Self-SMS-Loopback (opt-in, im Menü)

**Bedrohungsmodell:** Wir wollen wissen ob unsere SMS *abgefangen*
werden. Lösung: wir schicken eine SMS an uns selbst mit einem Token
und messen Latenz / ob sie ankommt.

**Default: OFF.** Wird vor Payload-Exit als Frage abgeprüft.

- **Latency > 30 s** → Warnung (typisch für Carrier-MITM)
- **Token kommt nie an** → Silent Interception bestätigt

Test-Number nur in `config.json` auf dem Mudi (gitignored), nie im Repo.

---

## Datenqualität — wann „reicht" ein Scan

Argus zeigt im Live-Screen eine **Datenqualitäts-Ampel** pro Detektor.
Defaults aus `config.example.json`:

| Detektor | Schwelle | Bedeutung |
|---|---|---|
| CYT analysis | 180 s gesamt | unter 3 min ist Probe-Persistenz nicht aussagekräftig |
| Cross-Report | min. 3 Runden | Persistenz braucht mehrere Sichtungen |
| Hotel-Scan | 240 s gesamt | Spy-Cams beaconen langsamer als Phones |
| Shodan / WiGLE | min. 2 Runden | API-Lookups erst sinnvoll wenn Targets sich gefestigt haben |
| Camera-Activity | 120 s gesamt | Bandbreiten-Spike braucht Beobachtungsfenster |

Ampel: 🟢 grün = bereit, 🟡 gelb = noch X Sekunden / Runden, ⚫ aus = Detektor inaktiv.

---

## Geplant für v2.1

Reihenfolge nach Aufwand × Nutzen:

| # | Vektor | Erkennung | Status |
|---|---|---|---|
| 1 | **Beacon-Flood / Pineapple Mode** | >X random SSIDs von wenigen MACs in kurzer Zeit | TODO |
| 2 | **Evil Twin / SSID-Klon** | Gleiche SSID, mehrere BSSIDs gleichzeitig sichtbar | TODO |
| 3 | **CSA-Spoofing (Channel Switch Announcement)** | CSA-IE mit Sprung in fremden Channel ohne legit Reason | TODO |
| 4 | **KARMA / PineAP** | AP antwortet auf jeden Probe-Request mit eigenem ACK | TODO |
| 5 | **WPS PIN-Brute-Signs** | Wiederholte WPS-Auth-Versuche zur gleichen BSSID | TODO |
| 6 | **PMKID-Exfil** | EAPOL Frame 1/4 ohne Frame 2/4 (hashcat-22000-Pattern) | TODO |
| 7 | **Probe-Storm** | Eine Source-MAC die >Y Probe-Requests/s sendet | TODO |
| 8 | **AWDL / Apple Continuity-Probes** | mDNS/Bonjour aus unbekannter Quelle | TODO |
| 9 | **MFP / 802.11w-Status der Umgebung** | RSN-IE prüfen — ungeschützte APs sind deauth-anfällig | TODO |
| 10 | **Hidden-SSID-Probes von Watch-List MACs** | Probe an `len 0` SSID + bekannte MAC | TODO |
| 11 | **BLE GATT-Probing** | GATT-Read-Anfragen von unbekannten Centrals | TODO |
| 12 | **AWDL / UWB Recon** | UWB-CIR-Patterns aus iPhone Find-My-Mode | RESEARCH |
| 13 | **Rogue mDNS / LLMNR / NBT-NS** | Vergiftete Name-Lookups im LAN | TODO |
| 14 | **Cellular Jamming-Indikatoren** | RSSI hoch aber NOSERVICE | teils da |
| 15 | **Bluetooth Spam-Frames** | BLE-Adv-Stürme mit zufälligen Namen (Apple/Samsung Pairing-Spam) | TODO |

Vorgehen ab v2.1: 1–4 zuerst (alles aus dem laufenden tcpdump zu extrahieren,
kein zusätzlicher Capture nötig), 5–7 dann (separate Filter), 8–15 nach Bedarf.
