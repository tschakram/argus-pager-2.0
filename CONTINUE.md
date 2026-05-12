# CONTINUE.md — Argus Pager 2.0

Diese Datei bringt einen frischen Chat in Sekunden auf Stand.
**Zuerst lesen, bevor du Code anfasst.**

---

## Projekt

Counter-Surveillance auf dem **WiFi Pineapple Pager**. Erkennt verdächtige
WiFi-/BT-Geräte, IMSI-Catcher und Silent-SMS während man sich bewegt.

---

## Aktueller Stand (10.05.2026)

- Repo: `github.com/tschakram/argus-pager-2.0`
- **Letzter Commit (LOKAL auf Pager): `f6bfef7` —
  `v2.1.0-alpha3: simplified UX, sensor pipeline, external intel, OPSEC`**
- GitHub `origin/main`: weiterhin auf `005a6df` (alpha9) — **NICHT gepusht**.
- Geplanter naechster Commit (in Vorbereitung):
  `v2.1.0-alpha4: argus finder + probe-request RSSI`

### Stand 10.05. — Argus Finder + Probe-RSSI + Heim-Run

**Probe-Request-RSSI Patch** (cyt-Submodule):
- `cyt/python/pcap_engine.py` — `read_pcap_probes` extrahiert jetzt
  Radiotap-RSSI fuer Probe-Frames; `analyze_persistence` aggregiert
  max + last je MAC.
- `cyt/python/analyze_pcap.py` — neue RSSI-Spalte in WARNING-Tabelle
  und "Alle Geraete" (Format `max/last dBm`).
- Re-analyse 08.05. Heim-Run zeigte **Espressif `<redacted-mac-espressif>` mit
  -18 / -64 dBm** — Stalker war zwischenzeitlich quasi am Pager.

**Heim-Run 10.05. 09:26:** sauber durchgelaufen (rc=0). Espressif diesmal
mit -48 / -53 dBm — bestaetigt: Geraet ist physisch in der Wohnung.
Pager-"Freeze" am Ende war kein Crash — Pineapple-Framework ging in
"User Idle, memory maintain" (Eco-Mode) nachdem Argus rc=0 zurueckkam.
Loesung: Pineapple-Daemons disablen wenn nicht gebraucht (siehe Backlog).

**Espressif** zur ignore_list ("nicht meiner aber ignorieren") -
49 entries in `/root/loot/argus/ignore_lists/mac_list.json`.

**Argus Finder (NEU) - Walking-Mode RSSI-Tracker:**
- `python/finder/main.py` - Pager-Init, Splash, --mode {wifi,bt}
- `python/finder/target_loader.py` - liest letzten Argus-Report +
  bt-Files (Default `last_only=True` -> nur letzte Session, weil
  BLE-Privacy-Adressen rotieren ~alle 15 Min).
- `python/finder/ui_select.py` - scrollbare Target-Liste, Header zeigt
  `Run TT.MM HH:MM (Xmin alt)` damit der User sieht wie frisch.
- `python/finder/ui_hunt.py` - Live-RSSI-Anzeige mit Bar -100..0 dBm,
  30s-Sparkline, Schwellen-Marker, LED + Vibration.
  Schwellen: ROT >= -55, GELB >= -70, BLAU >= -80, GRUEN < -80.
  poll_input alle 50ms -> BTN_B = sofort raus. Auto-Exit 5min ohne Signal.
- `python/finder/backends/wifi_rssi.py` - tcpdump live-stream
  (`-U -w -`) + Radiotap-Parser-Thread + 2.4GHz-Channel-Hopper-Thread
  (1/6/11, 0.6s dwell).
- `python/finder/backends/bt_rssi.py` - btmon live-stream + bluetoothctl
  scan-on Background.
- `argus-finder/payload.sh` + `argus-finder-wifi/payload.sh` - 80-Zeiler
  Wrapper, suspendieren Pineapple-UI mit kill -STOP, restore via trap.
  Liegen im Repo unter `argus-pager-2.0/`, am Pager als Symlinks ins
  Reconnaissance-Menue:
  ```sh
  ln -s /root/payloads/user/reconnaissance/argus-pager-2.0/argus-finder \
        /root/payloads/user/reconnaissance/argus-finder
  ln -s /root/payloads/user/reconnaissance/argus-pager-2.0/argus-finder-wifi \
        /root/payloads/user/reconnaissance/argus-finder-wifi
  ```

**Architektur-Wechsel zum alten DuckyScript-Finder:**
- Kein NUMBER_PICKER/CONFIRMATION_DIALOG mehr (zu unzuverlaessig)
- Direktes Framebuffer-Drawing via pagerctl, gleicher Stack wie main.py
- Live-Stream-Sampler statt Burst-Scan (kontinuierlich, nicht alle 4s)

**BT-Finder Test 10.05.: nichts gefunden.** Wahrscheinliche Ursachen:
1. SmartTag-Beacon-Intervall langsam (2-15s, manchmal Minuten)
2. BLE-Privacy-Adresse zwischen Argus-Scan und Finder-Start rotiert
3. hci0-Konflikt mit pineapd (auch wenn pineapple-UI suspended).

**alpha9: Offline OpenCelliD + Heim-Zelle + weak-signal Anomaly-Fix**
(12.05. nach 1. Test-Run der alpha8)

Heutiger Test-Run zeigte Anomaly-Score=HIGH wegen [H1] 0 Neighbours -
aber RSRP war -104 dBm (am Empfangs-Limit). Modem kann dort keine
Neighbours mehr decoden -> false positive in H1. Fix: weak-signal-
Schwelle bei RSRP < -100 suspendiert H1/H2/H8 zu LOW-Severity-Hinweisen.

User hat das OpenCelliD-Country-CSV fuer Litauen (246.csv.gz) lokal
heruntergeladen. Wir bauen daraus eine offline SQLite-DB:
- tools/opencellid_import.py liest .csv(.gz), schreibt SQLite mit
  PRIMARY KEY (mcc,mnc,area,cell). 8646 cells in 0.1s.
- Hochgeladen auf Mudi: /root/loot/raypager/cell_db/cells.sqlite (868 KB)
- Heim-Zellen (CID 1056780 + 1056790, TAC 142 BITE LT) manuell
  eingetragen mit Approximation-GPS (54.844, 25.461) - waren beide
  NICHT im OpenCelliD-Dump.
- raypager/python/opencellid.py: _offline_lookup() neu, lookup() jetzt
  offline-first. Nur bei Miss + api_fallback=true API-Call. Distance-
  Check auch fuer offline-hits. Source-Marker im result-dict.
- Mudi-config.json bekommt cellular.{offline_db_path, api_fallback, urban}

Smoke-Test (echte Mudi-Calls):
  T1 Heim 1056790:      CLEAN  offline  18.7 ms  (vorher UNKNOWN)
  T2 echte BITE-Cell:   MISMATCH offline 14.1 ms  (21.9 km weg)
  T3 bogus cell:        UNKNOWN  api     866 ms   (fallback aktiv)
Offline-Lookup ca. 50x schneller als API.

**alpha8: Cellular Anomaly Detection mit Neighbour Cells**
- `raypager/python/cell_info.py` — `get_neighbor_cells()` parst
  AT+QENG="neighbourcell" (LTE intra/inter, WCDMA, GSM formats).
  CLI: `cell_info.py --neighbours --json`.
- `python/core/mudi_client.py` — neue `cell_neighbors(cfg)` Methode,
  laeuft parallel zu cell_info im ThreadPool (max_workers=4).
- `python/core/cell_anomaly.py` — NEU. 8 Heuristiken H1-H8:
  - H1: 0 Neighbours urban -> high (isolated tower)
  - H2: <=2 Neighbours urban -> medium
  - H3: Neighbour RSRP > Serving RSRP -> medium (lock-in)
  - H4: Serving-RSRP-Sprung >20 dBm zwischen Polls -> high (Power-Boost)
  - H4-low: Sprung 12-20 dBm -> medium
  - H5: PCID-Wechsel bei stationaerem GPS (<30m) -> medium
  - H7: >15 unique PCIs in Session -> medium (drift)
  - H8: Serving >-60 dBm + <3 Neighbours -> medium
  Plus `analyse_trend(snapshots)` fuer Multi-Poll-Detection.
- `python/core/scan_engine.py` — _mudi_loop sammelt jetzt `cell_snapshots`
  (ts/rsrp/pci/cid/rat/nb_count/neighbours/gps) bei jedem cell-tick.
  Wird an analyser.run_all uebergeben.
- `python/core/analyser.py` — Cellular & Catcher Block erweitert:
  - Tower-Zeile zeigt jetzt auch PCI + Band + RSRP
  - Neighbour Cells Tabelle (kind/rat/freq/pci/power/quality/sinr)
  - Anomaly Score Block mit H-Code-Findings
  - Session-Stat (rsrp min/max/avg ueber alle Polls)
  - Threat-Bump: high -> threat=high, medium -> medium
- Config-Toggle `cellular.urban` (default true) - rurale Tests
  koennen H1/H2/H8 abschalten.
- README: ausfuehrliches Vergleichskapitel argus-pager 1.x vs 2.0
  (26 Zeilen Feature-Tabelle), neue "Cellular Anomaly Detection"-Section.

**alpha7: argus-probe (BT-GATT)**
- `argus-probe/payload.sh` als drittes Tool im Reconnaissance-Menue
  (Symlink im pager wie argus-finder/-wifi). Neben Sweep+Target-Mode
  ist Probe das aktive Identifikations-Tool.
- `python/probe/main.py` Mode-Loop: bt_gatt (ready), network (stub),
  mdns (stub). Mode-Auswahl scrollbar.
- `python/probe/backends/bt_gatt.py` macht gatttool-Reads von
  Generic-Access (0x1800) + Device-Information (0x180A) Services:
  Device-Name, Appearance, Manufacturer, Model-Number, FW/HW/SW-Rev,
  Serial, PnP-ID, System-ID. Plus Liste aller Primary-Services.
- `python/probe/opsec.py` macht bdaddr-Spoof vor Probe (LAA-random),
  restore im finally. Big-Warning-Screen vor jedem Probe (Confirm).
  Log-MACs redaktiert auf letzte 5 Hex.
- README ausfuehrlich: Workflow, OPSEC-Massnahmen, Beispiel-Output.
- Stubs fuer Network-nmap + mDNS/SSDP angelegt damit Architektur klar
  ist; Implementation ist v2.2-Backlog.

**alpha6 nachgezogen: BLE Address-Type-Erkennung + harter Tracker-Marker**
(cyt-Submodule). Fixt das Samsung-TV-False-Positive-Problem:
- `bt_scanner.py` parst jetzt `Address type: Public|Random` aus btmon-Output,
  klassifiziert Random-Subtype (resolvable/non_resolvable/static) aus Bits 7..6
- `bt_fingerprint.py` Logik umsortiert: Appearance 0x0200/0x0240 ist HARTER
  Tracker-Marker (vor Company-ID-Check). Company-ID + Public-Address =
  Hausgeraet (TV/Soundbar). Company-ID + RPA = Tracker. Company-ID +
  unknown addr_type = Medium (konservativ). Bestaetigt: Samsung TVs
  haben CompanyID 117 + Public-OUI -> kein Tracker-Flag mehr.
- Aufrufer (`bt_scanner._apply_fingerprinting`, `analyze_pcap.save_report`)
  reichen addr_type + addr_subtype durch.

**Loesung: Sweep-Mode (alpha5 nachgezogen)** - Beim Finder-Start fragt
das UI jetzt:
- LEFT = Target-Mode (wie alpha4: feste MAC aus Argus-Run)
- A    = Sweep-Mode (alle Adverts in Reichweite, Live-Top-Liste)

Sweep umgeht Privacy-Rotation komplett: egal wie oft der SmartTag seine
Adresse wechselt, der naechste Beacon erscheint sofort wieder in der
Liste. User laeuft durch die Wohnung und beobachtet welche MAC im
RSSI-Wert nach oben zieht.

OPSEC im Sweep-Mode: keine MAC-Listen persistent, alles in-memory;
Logs gitignored; full-MAC im Wrapper-Log redaktiert auf letzte 5 Hex.

### Stand 08.05. — alpha3 Commit + Heim-Auswertung + Pineapple-Diagnose

**alpha3 committed (`f6bfef7`):**
- 40 files: 19 mod, 10 del, 11 new
- +3592 / -1106 LOC
- Author: `tschakram <tschakram@users.noreply.github.com>` via GIT_*-ENV-vars
  (kein persistent git config update)
- pre-commit OPSEC-Hook: passed (1 warn fuer long-hex SHA = harmless)
- pre-commit MAC-Whitelist erweitert auf Patterns:
  `aa:bb:cc:dd:ee:??`, `aa:00:00:00:00:??`, `ca:fe:ca:fe:??:??`,
  `bc:bc:bc:bc:bc:bc`, `01:02:03:04:05:06`, `de:ad:be:ef:??:??`
- CONTINUE.md anonymisiert — JBL-MAC nicht mehr im Klartext
  (alle Erwaehnungen `<redacted-mac>`)

**Erster Heim-Run nach allen Fixes (08.05. 15:14):**
- Session 20260508_151433, 5 PCAPs, 9 min
- Threat: MEDIUM
- **Save-Zeit ~50s** (vorher 30 Min) — alle Performance-Fixes wirken
- **Log-Groesse 3961 Bytes** (vorher 12527 mit screenshots) — Faktor 3,
  KEIN dropped-shot-Spam mehr -> screenshot truthy-bug-Fix wirkt
- IMEI-Modal triggerte (kein Log-Output -> User druckte B/NO oder Timeout)
- Run sauber STOP -> report -> exit, rc=0

**Auswertung Heim-Report - Kernbefund:**
- 🔴 **Espressif-Stalker `<redacted-mac-espressif>`**: score 1.00, in 5/5
  Round-Windows, **17 historische Sessions** (seit 30.04.). Auch beim
  Drive-back am 03.05. mit 53 Appearances dabei. Vermutlich eigenes
  Smart-Home-IoT (ESP32-Familie) oder Nachbar-IoT.
- 🔴 **3 Samsung-Tracker (Company ID 117 = SmartTag)**:
  - `<redacted-mac-samsung-tv>` (9 sessions) — schon erklaert: "Samsung TV
    Vermieter (BLE)" in ignore_list
  - `<redacted-mac-samsung-tag-rot>` (8 sessions) — `:74:04` ist in ignore als
    "Samsung BLE", `:74:05` ist Adress-Rotation desselben Geraets;
    BLE-Privacy-Pattern-Whitelist sinnvoll
  - `<redacted-mac-samsung-tag-unknown>` (8 sessions) — UNBEKANNT, identifizieren
    via Samsung Find-My-App
- 🟡 **Cell-tower `CID=1056790 TAC=142` UNKNOWN** — BITE Lietuva
  Heim-Zelle, nicht in OpenCelliD-DB. Konsistent UNKNOWN ueber mehrere
  Tage; kein Catcher-Signal sondern Daten-Luecke. Whitelist-Feature
  fuer "Known-UNKNOWN towers" auf v2.2-Backlog.

**Pager-Performance-Diagnose (warum manchmal traege):**
```
load avg 2.34   (1 CPU, also 234%-Last)
RAM      228/250 MB used, 23 MB free, kein Swap
PID 2667 /pineapple/pineapple   217% CPU
PID 4021 pineapd --recon=true   im Hintergrund
PID 4727 _pineap MONITOR <redacted-mac-mudi> rate=200 timeout=3600
```
Der `_pineap MONITOR` aktiv-trackt eine MAC die laut ignore_list der
**Mudi-Router (GL-MT1300 randomized)** ist — sinnlose Ressourcen-Last.
Pineapple-Daemon plus Recon-Mode fressen >1 CPU dauerhaft. Argus-payload
suspendiert das waehrend Capture (`kill -STOP 2667`), daher fuehlt sich
der Scan selbst nicht so traege an. Aber nach STOP + im idle wird's
spuerbar.

**Quick-fix dauerhaft:**
```sh
ssh pager '
killall _pineap 2>/dev/null
/etc/init.d/pineapd disable
/etc/init.d/pineapplepager disable
'
```
Argus + cyt + bt_scanner laufen ohne Pineapple-Daemon — die Pineapple-
Web-UI ist dann zwar weg, aber bei pure-counter-surveillance-Use
nicht gebraucht.

**ignore_list Audit:**
- Pager WiFi-AP `<redacted-mac-pager-wifi>` ist drin
- Pager BT-HCI-Self `<redacted-mac-pager-bt>` ist NICHT drin -> sollte rein
- 48 Eintraege total, gut gepflegt, mit deutschen comments

**User-Frage zu BT `<redacted-mac-bt-rot>` + `:9d:c4:93`** —
beide nicht in argus-Daten. Adressen aus selbem OUI mit 12 Hex
auseinander -> klassisches BLE-Privacy-Address-Rotations-Pattern.
OUI b0:d5:fb -> typischerweise Sercomm/Hon Hai (Router/STB).
Falls Watch-Target gewuenscht: `watch_list.json` Eintrag.

**Verfuegbare Tools fuer Espressif-Lokalisierung:**
- `device_hunter` (RocketGod) in `/root/payloads/user/reconnaissance/` —
  hot/cold-Tracker mit LED + Vibration + Klick-Sound. **Genau das
  richtige Tool fuer WiFi-MAC `<redacted-mac-espressif>`**
- `argus-finder` — eigenes BT-RSSI-Tool, aber nur fuer BT-Tracker.
  WiFi-Variante nicht gebaut.
- FritzBox 7583 WebUI -> Heimnetz -> MAC-Suche
- `tcpdump -enttiI wlan1mon -y IEEE802_11_RADIO 'wlan addr2 == ...'`
  + RSSI-Trend manuell

### Stand 05.-07.05. — Live-Tests + Performance + IMEI-Modal

**3x 1h Live-Tests am 05.05. (Drive 1 / Work / Drive back):**
- Drive 1 (02:46-03:20, 18 PCAPs): MEDIUM, 179 BT
- Work    (03:45-04:39, 28 PCAPs): MEDIUM, 318 BT — **Akku weg im idle
  Report-Screen** (Pager wartete auf Button-press, kein Auto-Exit).
  Daten alle erhalten, Report 52 KB sauber geschrieben vor Akku-Kill.
- Drive back (14:11-15:11, 31 PCAPs): CLEAN, **801 BT** (Stadt-Drive
  sammelt jeden BT am Strassenrand). Pairing-DB: 23 Records in 2 von 3
  heutigen Sessions, 0 in allen 3 (verschiedene Orte). Korrekt.

**Performance-Probleme entdeckt + gefixt (06.-07.05.):**
- **Save-Latenz 30 Min**: bei 31 PCAPs lief external_intel.fingerbank
  ueber 800 BT-MACs - rate-limit 30/min = 27 Min. **Fix:**
  - BT-MACs gar nicht mehr an Fingerbank (score < 30 sowieso, low
    coverage). Nur WiFi-MACs aus pairings.json this-session.
  - Hard caps `_MAX_IP_LOOKUPS=50`, `_MAX_MAC_LOOKUPS=50`.
  - Mudi-Calls (cell_lookup, imsi_alerts, silent_sms) parallelisiert
    via ThreadPoolExecutor max_workers=3.
  - **Ergebnis: 30 Min -> 46 Sek fuer 31-PCAP-Session (39x).**
- **UI-Latenz**: `ARGUS_SCREENSHOTS=1` wurde durchgereicht (vermutlich
  vom Pineapple-Framework). Pro flip(): 213 KB FB-read + queue.put,
  Worker (Python-loop ueber 106k Pixel) kommt nicht hinterher, 1500+
  dropped Shots pro 1h-Run. **Fix:** payload.sh hard-default auf 0,
  opt-in nur via `ARGUS_SCREENSHOTS_DEBUG=1`.
- **Akku-Idle**: Report-Screen wartete blockierend auf Button. Bei
  Akku weg waehrend man im Report scrollt -> tot. **Fix:**
  `_wait_button_with_timeout(IDLE_TIMEOUT_S=60)` via `poll_input()`
  Schleife. Auto-Exit nach 60s zur Splash.

**IMEI-Rotate UI (Variante A) — wieder eingebaut (07.05.):**
- post_scan-Screen-Removal (Block A) hatte den IMEI-Rotate-Step
  versehentlich mit weggenommen. Jetzt: Confirm-Modal direkt in
  `scan_live` nach `engine.finish()`, vor return "report".
- "Rotate IMEI? LEFT=YES, B=NO" mit `IMEI_CONFIRM_TIMEOUT_S=10`
  Auto-default-NO. Modal nur wenn `mudi_client.is_reachable(cfg)`.
- Bei YES: "Rotating Mudi IMEI..." Frame, `mudi_client.imei_rotate()`,
  Mudi rebootet (~30-60s), Pager geht weiter zum Report.

**Regression + Fix (07.05.):**
- 2 Test-Runs am 06.05. starben nach 30 Min mit SIGKILL rc=137.
  Ursache: payload.sh-SCP von Windows am 04.05. ueberschrieb den
  03.05.-direkt-am-Pager `timeout 1800 -> 14400`-Patch (Windows-Klon
  hatte 1800 noch). Lokal jetzt auch auf 14400 + erneut deployed.
  Reports beider Sessions via `tools/rerun_analyser.py` recovered:
  - 20260506_025504: MEDIUM, 193 BT, 13 stable pairings
  - 20260506_035031: MEDIUM, 158 BT, CYT suspects found

### Stand 03./04.05. — Architektur-Block A + OPSEC-Haertung

**Architektur (gegen aelteren Plan):**
- **OpenCelliD-Upload entfernt** — `mudi_client.upload_queue_count` +
  `opencellid_upload` weg. Lookup-only bleibt drin.
- **`post_scan`-Screen komplett entfernt** — Code (`ui/screens/post_scan.py` +
  `core/post_scan.py`) geloescht, `main.py SCREENS` cleanup, scan_live-
  Comment entfernt. AUTO-Flow ist jetzt nur noch splash -> scan_live -> report.
- **`core/external_intel.py` neu** — InternetDB / Shodan / Fingerbank-
  Wrapper. Nutzt `cyt/python/shodan_lookup.py` direkt via `sys.path`.
  Wird vom Analyser nach CYT/incidents aufgerufen, generiert eigenen
  "External Intel"-Block + Findings + Threat-Bump.
- **`mudi_client.cell_lookup()` neu** — kombiniert `cell_info.py` (Mudi)
  + `opencellid.py --json` und merged auf Pager-Seite (RSSI aus cell_info,
  threat aus opencellid). **rc-Wert von opencellid.py spiegelt threat-
  level (0=CLEAN, 1=UNKNOWN, 2=MISMATCH, 3=GHOST), kein Error**.
- **"Cellular & Catcher"-Block im Report** — Tower MCC/MNC/CID/TAC/RAT/
  RSSI + OpenCelliD-Verdict + IMSI-Alerts (2h) + silent-SMS-Hits (24h).
  Threat-Bump bei MISMATCH/GHOST -> high, UNKNOWN -> medium, IMSI-alert
  -> medium, silent-SMS -> high.
- **AUTO-Preset:** `shodan=True` und `fingerbank=True`. Beide
  Always-On gated nur durch API-Key-Praesenz in `config.json`. Kein
  separater UI-Toggle.

**Code-Reife (Block A, alle 4):**
- **A1 `pairing.prune()`** — TTL 90d (default), 365d (established
  >=3 Sessions). Laeuft auto bei jedem `pairing.update()`.
- **A2 `_roll_gps_track()`** — TTL 30d, laeuft bei `engine.start()`.
  Mischt Legacy- und Unix-Timestamp-Format korrekt.
- **A3 `BT_SCANNER_NO_LOCAL_GPS=1`** — env-Schalter; bt_scanner.py
  skippt GPS_GET-Fallback wenn gesetzt; scan_engine setzt env beim
  bt_scanner-Spawn. Spart 3-5s pro Round = ca. 2 Min/h.
- **A4** — siehe oben (cell_lookup + Cellular & Catcher block).

**Ops/Walk-Fixes (03.05.):**
- `payload.sh timeout` von 1800s -> 14400s (4h). Vorher: SIGKILL bei
  30 Min, gerade waehrend langer Walks. Jetzt 4x Reserve fuer 1h-Tests.
- `_mudi_loop` sample_interval 30s -> 10s; cell_info nur jeden
  6. Tick (=60s). GPS-Track ist damit ~3-4x dichter (200-300 Pkt./h
  statt 90). 1h-Walk auf 03.05. ergab 44 Punkte fuer 28.9 min @ Faktor
  1.6x Polygonkuerzung; nach Fix erwartet ~250 Punkte.

**OPSEC-Haertung (03.05.):**
- `.gitignore` erweitert: `pairings.json`, `incidents/`, `deauth_*`,
  `external_intel_cache.json`, `walk_*`, `gps_track_*`.
- `hooks/pre-commit` erweitert:
  - FORBIDDEN-Liste: + `pairings.json`, `external_intel_cache.json`
  - Path-Patterns: + `incidents/*`, `deauth_*`, `walk_*`, `gps_track_*`
  - **GPS-Pattern Bug gefixt** — `grep -q | grep -v` Pipeline ate
    output, dadurch waren echte Koordinaten nie geblockt. Jetzt sauber.
  - **IMEI/IMSI-Pattern neu** — 14-16 stellige Zahlen mit `imei`/`imsi`-
    Keyword block, plus warning fuer naheliegende Zahlen.
- **CYT-Repo OPSEC-Purge** durchgefuehrt — JBL Flip 5 MAC
  `<redacted-mac>` war in 4 commits von chasing-your-tail-pager.
  `git filter-repo --replace-text` mit `aa:bb:cc:dd:ee:01` als
  Placeholder, `git push --mirror --force` auf GitHub. Beide lokalen
  Klone sind clean (Windows + Pager-Submodule), local patches
  (`bt_scanner.py` GPS-aus-argus_track, `oui_lookup.py` TTL 365d)
  erhalten via stash/pop. argus-pager-2.0 cyt-Submodule-Pointer ist
  auf neue HEAD `2dcc3fd...` (uncommitted im argus-Index).
- argus-pager-2.0 / raypager / mvt-pager Repos: alle clean, kein
  History-Leak.

**API-Keys auf Pager** (config.json, gitignored):
- `shodan_api_key` SET (32ch)
- `fingerbank_api_key` SET (40ch)
- `opencellid_key` SET (35ch) — fuer Lookup, nicht Upload
- **TODO User: Keys rotieren (waren im Chat exposed)**

### Stand 02.05. — was alles seit alpha9 deployed ist

(Detail-Liste der einzelnen Files steht unter "Datei-Layout" weiter
unten; hier nur thematisch.)

Phase 1 (Bedienung) — Auto-Detect splash, 3-Button scan_live, endless rounds,
Pause/Resume durch alle Sensoren, ASCII-Sanitizer fuer Display-Font,
"Saving report..." Frame, TZ permanent UTC + per-run Mudi-Sync.

Phase 2 (Sensoren) — `wifi_watcher.py` (probe-req unique-MAC + deauth flood
+ `on_flood`-Callback), `bt_scanner.py`-Pipeline (separate `_bt_procs`-Liste,
SDP-aware 25s grace, Round-dur 120s, OUI-Cache TTL 365d, GPS aus
`gps_track.csv`), Mudi-Watcher als procd Services (raypager-imsi /
raypager-sms, autostart), `sense.py` heartbeat-aware (state-files +
.jsonl).

Phase 5 (Report) — Threat-Summary oben, Metrics-Tabelle (PCAPs/BT/Incidents/
Pairing), Findings-Liste, "Forensic Incidents (Deauth Floods)"-Block,
Ignorierte-Liste in `<details>` collapsed, `report_view` filtert
`<details>` zur Single-Line auf Pager-Display, `cyt rc=2` korrekt als
"suspects found" gelabelt.

Korrelation — `pairing.py` persistente WiFi/BT-Pairing-DB
(`pairings.json`), **time-aware**: Probe-MAC-Window muss Round-BT-Window
ueberlappen (kein `alle x alle pro Session` mehr), ESTABLISHED ≥3 Sessions.

UX-Bug-Fix (02.05.) — `scan_live` returnt direkt `"report"` statt
`"post_scan"`, weil post_scan `wait_button` blockiert und User STOP nicht
als "Continue zu post_scan-Steps" interpretiert. Vorher: 30min-Timeout
und SIGKILL.

Polish (02./03.05.) — `tools/deauth_test.py` auf `wifi_watcher` umgestellt
und um Case 5 erweitert: end-to-end Pipeline-Test (synthetic flood ->
on_flood -> scan_engine._on_flood -> incidents/deauth_*.{pcap,json}).
**5/5 Cases PASS auf Pager** — Forensik-Pipeline verifiziert, das letzte
fehlende Stueck ist nur noch ein echter Pineapple-Angriff in Reichweite.

System-Config (kein Repo-Code, einmalig):
- Pager: `/etc/TZ` `UTC+2` → `UTC0`, uci dito, `hwclock -w -u`
- Mudi: `/etc/TZ` `CET-1CEST,…` → `UTC0`, uci dito
- Mudi: `pyserial 3.5` in `/usr/lib/python3.10/site-packages/serial/`
  (Blue Merle's `imei_generate.py` braucht das fuer IMEI-Rotation)
- Mudi: `/etc/init.d/raypager-imsi` + `/etc/init.d/raypager-sms` aktiv
- Pager: OUI-Cache via Mudi-LTE neu geladen (39342 entries, frisch)

### Test-Status (Stand 07.05.)

**Live verifiziert mit den 3 Sessions vom 05.05. + 2 vom 06.05.:**
- 18-31 PCAPs pro Session, BT-counts 158-801 (Drives sammeln viel)
- Pairing-DB ueber alle Tests: 1613 records, 30 in >=2 sessions,
  3 established (alte SmartTags aus 01.-03.05.)
- Cellular & Catcher Block: BITE Lietuva LTE, mehrere CIDs gesehen,
  alle "UNKNOWN" oder "CLEAN" - eine konstant unknown CID (1056820)
  in Vilnius, andere kommen+gehen
- Save-Latenz Vorher: 30+ Min (Fingerbank rate-limit), Nachher: 46s

**Performance-Fixes verifiziert nur per rerun_analyser, nicht in echtem
Live-Run:**
- 60s Idle-Auto-Exit im report_view (poll_input-Loop)
- ARGUS_SCREENSHOTS=0 hard-default
- IMEI-Confirm-Modal Display-Test auf dem Pager

### Test-Status (Stand 04.05.)

**Live verifiziert nach Block A (04.05., 4-Round-Smoke + Walk-rerun):**
- `gps_track Rolling`: 66 alte Rows gedroppt, 57 gekept (TTL 30d)
- `External Intel`: 4 BT-MACs an Fingerbank queried (vorher 0 — Bug
  in `_collect_bt_macs` durch Schema-Check fixiert)
- `Cellular & Catcher`: BITE Lietuva LTE, OpenCelliD-Verdict
  funktional. Erste live Anomalie: CID=1056820 (Band 28) UNKNOWN.
- `cell_lookup` rc-Bug gefixt (rc=1 = UNKNOWN, kein Error)
- Threat-Bump-Logik bei UNKNOWN -> MEDIUM verifiziert
- Findings: 3 Punkte korrekt aufgefuehrt (CYT suspects, Pairing
  stable, Cell tower not in OpenCelliD)
- 30-min-Walk-Run (03.05. vormittags) lief 30 Min in payload.sh
  timeout = SIGKILL rc=137; Daten alle erhalten (15 PCAPs + 14 BT-
  JSONs + 44 GPS-Pkt.); rerun_analyser.py-Tool dazu gebaut.

**Live verifiziert (Stand 02.05., gruene Reports):**
- Splash 8-Sensor-Discovery, alle OK
- AUTO-Preset, scan_live IDLE/RUNNING/PAUSED 3-Button-Flow
- 5+ vollstaendige Runden Hintereinander, jede mit BT-JSON
- Pause/Resume + STOP + Confirm-Modal
- WiFi probe-req Counter live (`WiFi 1/15` etc.)
- Live BT-Counter ab Round 2
- bt_scanner schreibt JSON sauber, GPS aus argus_track
- pairings.json wuchs ueber 5 Sessions auf 3 etablierte SmartTags
- Threat-Summary inkl. Metrics + rc=2-Relabel
- Ignorierte-Liste collapsed in `<details>`
- TZ permanent UTC + sync_time pro Run
- Mudi-Watcher heartbeats sense.py erkennt sie als OK
- IMEI-Rotation via Blue Merle (Mudi reboot)
- Argus-Report Pairing-Block "Stabil ≥3 Sessions"

**Code committed/deployed aber nie unter Realbedingung getriggert:**
- Deauth-Flood-Detection: kein echter Pineapple-Angriff erlebt → 
  `_on_flood`-Callback nur Unit-Tested. Incidents-Verzeichnis leer.
- Silent-SMS-Detection: `silent_sms.jsonl` leer (keine echte Silent-SMS
  empfangen). Daemon laeuft, aber Real-Detection-Code-Pfad ungetestet.
- IMSI-Catcher-Detection: 20+ samples gesammelt, alle "clean BITE LT".
  Anomalie-Code-Pfad ungetestet (kein Catcher in Vilnius).
- Movement-GPS-Track: nur statische Tests im aktuellen Setup;
  02.04.2026-Daten zeigen Bewegung im historischen Track.
- 6 GHz / 5 GHz DFS Frequenzen: im Hopper drin, aber Vilnius hat dort
  keine APs → leer im PCAP. Coverage-Beweis fehlt.
- BTN_POWER (global exit) im scan_live nie getestet.
- report_view scroll-mode (BTN_UP/DOWN) wenig genutzt.
- time-aware pairing live (smoke nur, real-disjoint Probes selten).

**Unreachable im aktuellen AUTO-Flow (Code da, kein UI-Pfad):**
- `hotel_scan.py` (cyt) / `camera_activity.py` (cyt): AUTO `cameras=False`
  - Mit Fingerbank-API-Key wuerde hotel_scan IP-Kameras erkennen koennen
    (Backlog: `cameras=True` wenn fingerbank_api_key gesetzt).

**Block-A-Erledigungen (04.05.) — vorher als offen gelistet:**
- ~~pairings.json waechst nur, kein Cleanup~~ → **DONE** (`pairing.prune`)
- ~~gps_track.csv waechst forever~~ → **DONE** (`_roll_gps_track`)
- ~~`BT_SCANNER_NO_LOCAL_GPS=1` env~~ → **DONE** (cyt local patch + scan_engine)
- ~~OpenCelliD-Lookup im Report~~ → **DONE** (`cell_lookup` + Cellular block)

**Bekannte offene Punkte / Workarounds:**
- screenshots queue overflow (`dropped 201 shots`) bei niedriger CPU —
  funktional OK, optisch unsauber im Log.
- BT-MACs durch Fingerbank: score < 30, daher 0 identified im
  Test-Run. Fingerbank ist primaer fuer WiFi+DHCP gedacht; BT-MAC-
  Coverage in Free-Tier limitiert. Alternative: WiFi-MACs aus Pairings
  schicken (passiert in `_collect_wifi_macs`).
- DHCP-Fingerprint-Extraktion aus PCAPs nicht impl — bewusst weggelassen,
  da probe-only-Capture keine DHCP-Frames hat. Bei Hotel-WiFi-Test
  (assoziiert) waere das nachruestbar.

### Gelöscht
**Phase-1-Cleanup:**
- `python/ui/screens/preset_menu.py`
- `python/ui/screens/scan_config.py`
- `python/core/presets.py`

**Block-A/Architektur-Cleanup (03.05.):**
- `python/ui/screens/post_scan.py` (war unreachable im AUTO-Flow)
- `python/core/post_scan.py`
- `python/core/deauth_monitor.py` (ersetzt durch `wifi_watcher.py`)

### Neu seit alpha9
- `python/core/sense.py` (8-Sensor-Discovery + sync_time)
- `python/core/wifi_watcher.py` (probe-req + deauth flood)
- `python/core/wifi_channels.py` (chip-caps -> Frequenzliste)
- `python/core/pairing.py` (time-aware WiFi/BT-DB + prune)
- `python/core/external_intel.py` (InternetDB/Shodan/Fingerbank)
- `tools/rerun_analyser.py` (recovery wenn payload.sh SIGKILLed wird)

### Geplanter Commit (nach 2x 1h-Tests am 05.05.)
`v2.1.0-alpha3: simplified UX, sensor pipeline, pairing DB, threat
summary, external intel, cellular block, OPSEC hardening`

---

## Re-Design: drastische Vereinfachung

### Was bisher schief lief
Bisheriger Flow: `splash → preset_menu (STANDARD/DEEPSCAN/CUSTOM) → scan_config (7 Toggles + 2 Stepper) → scan_live → post_scan → report`.
Zu viel Bedienung für ein Gerät, das verdeckt und einhändig genutzt wird.

### Neuer Flow

1. **App startet** → Splash zeigt **Sensor-Discovery-Ergebnisse**
   (WiFi-Monitor, BT, Mudi-GPS, Mudi-Cell, IMSI-Watcher, SMS-Watcher)
2. **EINE Action-Tafel mit drei Buttons**: `SCAN LOS` · `PAUSE` · `STOP`
3. Programm entscheidet **selbst**, welche Sensoren laufen, welche Channels
   gehoppt werden — basierend auf der Discovery
4. Runden laufen **endlos** bis `PAUSE` oder `STOP`
5. `STOP` → direkt in den Report

### Status der Arbeit

- **Phase 1** Bedienung — ✅ codeseitig + live verifiziert
- **Phase 2** Sensoren — ✅ codeseitig + live verifiziert (siehe Test-Status oben)
- **Phase 3** Filter (Ignore/Watch/Suspects/Hopper) — bestehend von cyt
  uebernommen; Watch-List konfiguriert mit Platzhalter-Koords (echte
  Home/Office-Zonen sind in `config.json` auf dem Pager, gitignored)
- **Phase 4** Scan-Engine (Rotation/Pause/Stop unter Last) — durch
  Phase 1+2 weitgehend abgedeckt
- **Phase 5** Report — ✅ codeseitig + live verifiziert

---

## Hardware + SSH

| Gerät | Adresse | SSH-Alias | Key |
|---|---|---|---|
| Pager (WiFi Pineapple) | 172.16.52.1 (USB-C) | `pager` | `~/.ssh/pager_key` |
| Mudi V2 (LTE-Router) | 192.168.8.1 (WiFi) | `mudi` | `~/.ssh/mudi_key` |

- GPS-Quelle: u-blox M8130 USB-Dongle am Mudi → `/dev/ttyACM0` @ 4800 baud
- Pager → Mudi: WiFi (`wlan0cli`)
- Mudi → Internet: LTE (BITE Lietuva)

---

## Pfade

### Pager (`ssh pager`)
- Repo: `/root/payloads/user/reconnaissance/argus-pager-2.0/`
- Loot: `/root/loot/argus/`
  - PCAPs: `/root/loot/argus/pcap/`
  - Reports: `/root/loot/argus/reports/`
  - Logs: `/root/loot/argus/logs/` — `last.log` zeigt aktuellen Run
  - GPS-Track: `/root/loot/argus/gps_track.csv`
- Hopper-Log (transient): `/tmp/argus_hopper.log`

### Mudi (`ssh mudi`)
- Scripts: `/root/raypager/python/`
- Loot: `/root/loot/raypager/`

---

## Pager-Eigenheiten — unbedingt beachten

### 1. Python braucht PATH + LD_LIBRARY_PATH
Sonst kein `python3`, kein `libpython3.11.so`:
```sh
export PATH="/mmc/usr/bin:/mmc/usr/sbin:/mmc/bin:/mmc/sbin:$PATH"
export LD_LIBRARY_PATH="/mmc/usr/lib:/mmc/lib:$LD_LIBRARY_PATH"
```
`payload.sh` setzt das automatisch. Nur für manuelle SSH-Sessions wichtig.

### 2. CRLF nach SCP von Windows
Nach **jedem** SCP:
```sh
ssh pager 'sed -i "s/\r$//" /pfad/zu/datei'
```

### 3. Display-Font hat KEINE Umlaute
Alle UI-Strings (LOG, draw_text, Screen-Labels) müssen **ASCII** sein —
sonst leerer Kasten auf dem Display. Im Code `ae/oe/ue/ss` schreiben.
.md-Reports sind davon nicht betroffen.

### 4. Git-Commits nur vom Pager
Lokale `git config` fehlt auf dem Windows-Rechner. Commits also:
```sh
ssh pager 'cd /root/payloads/user/reconnaissance/argus-pager-2.0 && git add -A && git commit -m "..."'
```

### 5. Submodules
- `cyt/` → `github.com/tschakram/chasing-your-tail-pager`
- `raypager/` → `github.com/tschakram/raypager`

Vor jedem Submodule-Commit `git checkout main` (sonst detached HEAD).

### 6. Zeitzone — beide Geraete laufen UTC
Pager und Mudi haben permanent `TZ=UTC0` in `/etc/TZ` und uci. Pager
hat zusaetzlich `hwclock -w -u`, ueberlebt also Reboots. `core/sense.py`
ruft beim Start `sync_time(cfg)` auf, holt UTC vom Mudi (LTE-NTP-Quelle)
und setzt sie via `date -u -s` auf dem Pager — fuer den Run-Drift.
Filenames (`argus_report_<ts>.md`) und cross_report-cutoff stimmen
seitdem ueberein. Wenn die "Time"-Zeile im Splash auf NA geht: Mudi ist
nicht erreichbar oder Mudi-Uhr ist selber gedriftet (`ssh mudi 'ntpd -q'`).

### 7. Mudi-pyserial Abhaengigkeit
Blue Merle's `/lib/blue-merle/imei_generate.py` importiert `serial`.
Auf dem Mudi ist pyserial 3.5 unter
`/usr/lib/python3.10/site-packages/serial/` installiert. Bei Mudi-Reset
ohne Backup: erneut von PyPI-Wheel ziehen.

---

## Datei-Layout (heute, post 07.05.-Performance-Block)

```
argus-pager-2.0/
├── payload.sh                 ← MOD: timeout 1800s -> 14400s (4h),
│                                  ARGUS_SCREENSHOTS hard-default 0
├── python/
│   ├── main.py                ← MOD: SCREENS = {splash, scan_live, report}
│   │                              (post_scan-Eintrag entfernt)
│   └── core/
│       ├── analyser.py        ← MOD: + external_intel + Cellular & Catcher
│       │                              block, Mudi-Calls parallel
│       │                              (ThreadPoolExecutor max_workers=3)
│       ├── data_quality.py
│       ├── external_intel.py  ← NEU/MOD: InternetDB/Shodan/Fingerbank
│       │                              + Caps 50 IPs/50 MACs, BT-MACs
│       │                              werden NICHT mehr gequeryed
│       ├── mudi_client.py     ← MOD: cell_lookup() neu, opencellid_upload+
│       │                              upload_queue_count entfernt
│       ├── pairing.py         ← MOD: prune() + auto-call in update()
│       ├── scan_engine.py     ← MOD: _roll_gps_track() bei start(),
│       │                              BT_SCANNER_NO_LOCAL_GPS env-flag,
│       │                              GPS sample 30s -> 10s, cell every 60s
│       ├── scheduler.py       ← MOD: rounds=0 = endlos
│       ├── screenshot.py
│       ├── sense.py           ← NEU: 8-Sensor-Discovery + sync_time
│       ├── wifi_channels.py   ← chip-caps → Frequenzliste (Multi-Band)
│       └── wifi_watcher.py    ← NEU: probe-req + deauth-flood watcher
│   └── ui/
│       ├── theme.py           ← MOD: ascii_safe() Sanitizer
│       ├── widgets.py
│       └── screens/
│           ├── splash.py        ← REWRITE: 8-Sensor-Liste, AUTO-Preset
│           │                      MOD: shodan=True, fingerbank=True
│           ├── scan_live.py     ← REWRITE: 3-Button, direct "report"
│           │                      MOD: IMEI-Confirm-Modal nach finish()
│           │                      mit 10s Timeout-default-NO
│           └── report_view.py   ← MOD: ascii_safe + <details>-collapse,
│                                  + Auto-Exit nach 60s Idle (poll_input)
├── cyt/        (submodule, neuer HEAD nach OPSEC-purge: 2dcc3fd...)
│   └── python/
│       ├── bt_scanner.py      ← LOCAL PATCHES: GPS aus argus_track,
│       │                              + BT_SCANNER_NO_LOCAL_GPS env-skip
│       └── oui_lookup.py      ← LOCAL PATCH: UPDATE_DAYS 7→365,
│                                      urlopen timeout 15→5
├── raypager/   (submodule)
├── tools/
│   ├── deauth_test.py
│   └── rerun_analyser.py      ← NEU: recovery wenn payload SIGKILLed
├── hooks/
│   └── pre-commit             ← MOD: + IMEI/IMSI, + pairings/incidents/walk_,
│                                      GPS-Pattern bug fix (grep -q ate output)
├── .gitignore                 ← MOD: + pairings.json, incidents/,
│                                      external_intel_cache.json, walk_*
├── config.example.json
├── README.md
└── CONTINUE.md  ← diese Datei
```

**Geloescht in Block A:**
- `python/ui/screens/post_scan.py`
- `python/core/post_scan.py`

---

## Naechste Schritte / Backlog

### Geplanter Workflow (10.-11.05.2026)

User-Plan:
1. **Heute kurzer Test-Lauf** (~5-10 Min daheim) mit alpha8 — pruefen ob
   Neighbour-Cells im Report auftauchen und Anomaly-Score sauber rechnet.
2. **Morgen** waehrend Fahrt (1h Drive) + im Hotel (~1h association). Drive
   liefert PCID-Changes + RSRP-Drift, Hotel liefert assoziierte WiFi-Captures
   + InternetDB-Lookups + ggf. fremde IoT-Devices.
3. **Wenn alles sauber laeuft** -> Daten-Cleanup:
   - alte Argus-Reports/PCAPs/BT-JSONs vor 10.05. loeschen
   - andere Reconnaissance-Payloads die wir nicht nutzen vom Pager loeschen
     (argus-pager 1.x, alte argus-finder versions, etc.)
   - argus-pager-2.0.before-alpha3 backup-dir loeschen
   - Pager-OPSEC clean machen: SSH-keys auditen, Loot-Dirs leer, nur die
     aktiven Tools im Menue
4. **Dann der eigentliche Counter-Surveillance-Modus:** Daten-Persistenz
   ueber Sessions:
   - pairings.json (existiert, wird erweitert)
   - suspects_db.json (existiert)
   - **NEU: Attack-Surface-DB (SQLite auf Mudi)** — tables: sessions,
     bt_devices, wifi_macs, pairings, incidents, gps_track, cell_history,
     cellular_anomalies. argus-pager schreibt pro Run rein, Auswertung
     spaeter via Jupyter/Web-UI/Maltego.
   - Trend-Analysen ueber Wochen statt nur einzelne Sessions.

### Was noch in der CONTINUE fehlt (User-Audit-Antwort)

Vor dem Cleanup sollten folgende offene Punkte explizit dokumentiert sein:
- [ ] API-Keys rotieren (shodan, fingerbank, opencellid - waren im
      Chat-Verlauf exposed)
- [ ] cyt-Submodule-Patches als formelle Upstream-PRs einreichen
      (Probe-RSSI in pcap_engine, Address-Type-aware fingerprint, OUI-TTL)
- [ ] Mudi-Setup wieder zuverlaessig: heute mehrfach offline
      ("Name does not resolve") - braucht Sanity-Check der ~/.ssh/config
- [ ] BLE-Privacy-Pattern-Whitelist (`70:b1:3d:ab:74:??` als ein Eintrag)
- [ ] Pre-Cleanup-Snapshot: `tar` der aktuellen /root/loot/argus/ und
      /root/payloads/user/reconnaissance/argus-* als Cold-Storage
- [ ] Attack-Surface-DB-Schema festlegen (welche Tabellen, welche Felder
      sind Required vs Optional, Index-Strategie)
- [ ] Cleanup-Script schreiben: `tools/cleanup.sh` listet alle aktiven
      Tools + erlaubt Auswahl was geloescht werden soll (interaktiv,
      nicht destruktiv ohne Confirm)

### Verifikations-Tests fuer Release v2.1.0 (User)
- [x] Heim-Run 08.05.: Save 50s, kein screenshot-spam, sauber rc=0
- [ ] 1-2 weitere alltaegliche Runs (Walk / Cafe / Buero), idealerweise
      mit echtem assoziiertem WiFi um endlich Public-IPs zu sehen
      (External-Intel-Block bisher nur leer-getestet)
- [ ] Falls alle gruen -> `git tag v2.1.0 && git push origin main && git push origin v2.1.0`

### Open vom 08.05.
- [ ] **Espressif `<redacted-mac-espressif>` identifizieren** via device_hunter
      (RSSI-Tracking) oder FritzBox-WebUI. Falls eigen -> ignore_list
      mit Kommentar; falls fremd Nachbar-IoT -> ignore_list mit "Nachbar
      IoT seit 30.04.".
- [ ] **`<redacted-mac-samsung-tag-unknown>`** (Samsung SmartTag, 8 Sessions) identifizieren
      via Samsung Find-My-App. Falls eigen -> ignore. Falls fremd -> physisch
      suchen (Tasche/Mantel/Auto), Find-My im Ortungs-Modus piepen lassen.
- [ ] **Pager BT-HCI-self `<redacted-mac-pager-bt>`** in ignore_list eintragen
      (Pager WiFi-AP ist schon drin als `<redacted-mac-pager-wifi>`).
- [ ] **Pineapple-Daemons stoppen** wenn Pineapple-Web-UI nicht gebraucht:
      `/etc/init.d/pineapd disable && /etc/init.d/pineapplepager disable`.
      Spart ~217% CPU + RAM.
- [ ] Optional: `argus-finder-wifi` als Variante des bestehenden
      argus-finder fuer WiFi-MACs (RSSI + LED + Vibration). Wuerde
      Espressif-Lokalisierung im argus-Workflow integrieren.

### v2.2 Backlog (mittelfristig)
- "Known-UNKNOWN towers" Whitelist in config.json: bekannte UNKNOWN-CIDs
  (BITE Lietuva Heim-Zellen) nicht mehr threat-bumpen
- BLE-Privacy-Pattern-Whitelist in mac_list: `70:b1:3d:ab:74:??` matchen
  als ein Geraet statt 256 verschiedene
- DHCP-Fingerprint-Extraction aus assoziierten WiFi-Captures (Hotel-Test)
- Maltego-Anbindung der pairings.json
- Battery-Level read aus /sys/class/power_supply/

### Frueher fuer 05.05. geplant, gemacht:
- [x] **2x 1h Live-Test** mit Pager + Mudi outdoor:
      - **Test 1 (1h Walk):** GPS-Sampling 10s → erwartet ~250-300
        Punkte (vorher 90/h). Pairing-DB sollte fremde Probe-MACs
        aus wechselnder Umgebung sammeln. Zeigt ob Polygon-Strecke
        nahe an realer Strecke kommt (heute Faktor 1.6x bei 40s sampling).
      - **Test 2 (1h Hotel/Cafe-WiFi):** Pager im Beobachtungs-Modus
        nahe oeffentliches WiFi → Probe-Requests + evtl. assoziierte
        Frames. **Erstmal Live-Beweis fuer InternetDB-Lookup mit
        echten Public IPs.**

### Block B/C — sobald die 1h-Tests sauber sind
- [ ] **Deauth-Flood-Live-Test**: `mdk4 wlan1mon d` von Test-Laptop
      → muesste `incidents/deauth_<ts>.{pcap,json}` produzieren und
      Report-Bump auf `high`.
- [ ] **Silent-SMS-Test**: SMS Type 0 ans Mudi → `silent_sms.jsonl`
      Eintrag → analyser-Block "Cellular & Catcher" listet ihn auf.
- [ ] **IMSI-Catcher-Anomalie**: schwer zu provozieren; alternative:
      kuenstliche cell_info-Eingabe um Anomalie-Code-Pfad zu testen.
- [ ] **Movement-GPS-Track**: durch Test 1 abgedeckt.

### Block D — Vor `v2.1.0-alpha3` Commit
- [ ] CONTINUE.md aktualisieren — **DONE 04.05.**
- [ ] README.md kurz pruefen (Feature-Liste / Sensoren-Tabelle)
- [ ] OPSEC-Audit: `git status` final clean, `pre-commit` greift,
      Submodule-Pointer auf neue HEADs, keine ungewollten Files staged
- [ ] Commit `v2.1.0-alpha3: simplified UX, sensor pipeline, pairing
      DB, external intel, cellular block, OPSEC hardening` — vom Pager
- [ ] cyt-Submodule-Patches (`oui_lookup.py`, `bt_scanner.py` mit
      `BT_SCANNER_NO_LOCAL_GPS` env, GPS-aus-argus_track) als
      formelle Pull Requests upstream einreichen.

### Release-Kandidaten (mehrere alpha3-Tests dann v2.1.0)
- Mehrere 1h-Tests an verschiedenen Orten clean
- Reale Deauth-Detection mind. 1x triggered + sauber gespeichert
- Mind. 1 Hotel/Cafe-Test mit IPs → InternetDB-Block validiert

### Auswertung / Datenarchivierung
- [ ] **Maltego CE Anbindung** zur Visualisierung der pairings.json /
      suspects_db.json / gps_track.csv? Maltego erwartet TDS-/CSV-/JSON-
      Imports. Wir muessten:
      - Custom-Transform "argus -> Maltego" schreiben, der unsere
        BT/WiFi-Pairings als Entities (Person, MacAddress, Location)
        ausgibt
      - Persistente Datenhaltung in einem Format, das Maltego
        einlesen kann (Graphml oder Server-DB)
      Aktuelle Datenlage ist klein genug fuer JSON-Files — sobald wir
      mehrere hundert Sessions sammeln, wird eine SQLite-DB sinnvoll.
- [ ] **Attack-Surface-DB** (mittelfristig): SQLite auf Mudi mit
      Tabellen `sessions`, `bt_devices`, `wifi_macs`, `pairings`,
      `incidents`, `gps_track`, `cell_history`. argus-pager schreibt
      pro Run rein, eine Web-UI / lokales Notebook kann ueber alle
      Sessions hinweg auswerten. Vorteil ueber Maltego: keine externe
      Abhaengigkeit, alles auf eigener Hardware.

### Phase 3 (Filter) — bestehend, evtl. erweitern
- [ ] Watch-List Trigger-Logik: was passiert wenn Pager "Home"-Zone
      betritt/verlaesst? Aktuell config-Eintraege ohne Code-Konsequenz.
- [ ] Suspects-DB cleanup-Routine.

### Phase 6 — externe Anreicherung (NEU geplant)
- [ ] `core/shodan_lookup.py` — pro Scan: lookup von BT/WiFi-MACs
      und ggf. IPs gegen shodan.io. Cache, retry, threat-bewertet.
      In Argus-Report eigene Sektion "## External Intel (Shodan)".
- [ ] `core/fingerbank_lookup.py` — pro Scan: DHCP-Fingerprint aus
      PCAP extrahieren, gegen Fingerbank Free-API senden, in
      `bt_devices`/wifi_devices `device_type`-Feld anreichern.
      Idealerweise als Cache, da Fingerprints stabil sind.
- [ ] **Camera/Hotel-Scan auf Toggle stellen**: aktuell `cameras=False`
      in AUTO. Bei aktiviertem Fingerbank koennten IP-Kameras
      automatisch erkannt werden — dann ist `hotel_scan.py`
      moeglicherweise auch als Default-On sinnvoll.

---

## Offene Punkte / Bekanntes

### 08.05.2026 (alpha3-Commit + Pineapple-Diagnose)
- **alpha3 committed lokal `f6bfef7`** — 40 files, +3592/-1106. Author
  via GIT_*-ENV (kein persistent config update). pre-commit MAC-
  Whitelist erweitert auf Patterns (statt fixe Werte).
- **CONTINUE.md JBL-MAC anonymisiert** — pre-commit blockte sonst.
  Alle Erwaehnungen `<redacted-mac>`.
- **Heim-Scan zeigt Espressif-Stalker mit 17 Sessions Persistenz** —
  vermutlich eigenes IoT, aber identifizieren-Pflicht.
- **Pineapple-Framework frisst >1 CPU-Core dauerhaft** + halbleeres
  RAM (23 MB free). Quick-fix: pineapd + pineapplepager init-Scripts
  disable. Argus selbst funktioniert ohne Pineapple.

### 07.05.2026 (Performance + Regression)
- **30-Min-Save-Latenz** durch external_intel BT-MAC-Bulk-Fingerbank.
  Fix: BT-MACs raus aus Lookup, Cap 50, Mudi parallel. **30 Min -> 46s.**
- **ARGUS_SCREENSHOTS=1 vom Framework durchgereicht** -> 1500+ dropped
  shots/h, 213 KB FB-read pro flip(). Fix: hard-default 0, opt-in via
  `ARGUS_SCREENSHOTS_DEBUG=1`.
- **Akku-Idle Report-Screen** ohne Auto-Exit. Fix: poll_input-Schleife
  mit 60s Timeout in report_view.
- **Regression payload.sh timeout**: 04.05. SCP von Windows ueberschrieb
  03.05.-direkt-am-Pager 14400-Patch. 06.05. 2 Runs SIGKILLed nach 30
  Min. Fix: Windows-Klon synchronisiert, neu deployed. Reports der
  beiden Runs via `tools/rerun_analyser.py` recovered.
- **IMEI-Rotate UI** war seit Block A weg, jetzt als Confirm-Modal
  Variante A in scan_live.

### 04.05.2026 (Block-A-Bugfixes)
- **`_collect_bt_macs` Schema-Bug** — bt_scanner schreibt
  `{"bt_devices": {"<mac>": {...}}}` (Dict, MAC ist Key). External-
  intel suchte aber `data["devices"]` als List. Fix: erst
  `bt_devices`-dict, dann legacy-list-fallback. Vorher: 0 MACs an
  Fingerbank, jetzt 4/4 BT-MACs aus Test-Run.
- **`cell_lookup` rc-Bug** — `opencellid.py` exit code mirrorring
  threat (0=CLEAN, 1=UNKNOWN, 2=MISMATCH, 3=GHOST). Mein Code
  verwarf die Antwort bei rc != 0. Fix: nur auf leere Output
  pruefen. Live-getriggert mit CID=1056820 in Vilnius (UNKNOWN).
- **`hooks/pre-commit` GPS-Pattern Bug** — `grep -q | grep -v` ate
  pipe output, dadurch waren echte Koordinaten nie geblockt.
  Fix: einmalige Aggregation in `gps_hits=$(...)`, danach Test mit
  echten + placeholder-Koords beide korrekt.

### 03.05.2026 (Walk-Test + Architektur)
- **30-Min-SIGKILL beim Walk** — payload.sh hatte hardcoded
  `timeout 1800`. Walk lief durch (15 PCAPs + 14 BT-JSONs + 44 GPS-
  Pkt. erhalten), aber kein Final-Report. Fix: timeout auf 14400s
  (4h). Plus: `tools/rerun_analyser.py` als Recovery wenn das nochmal
  passiert (alte Daten reanalysieren).
- **GPS-Track 6km vs 3.78km Polygon** — Sampling alle ~40s in der
  Stadt schneidet Kurven, real-vs-Polygon-Faktor 1.6x. Fix: sample
  10s, cell decimiert auf 60s.
- **CYT JBL-MAC Leak** — `<redacted-mac>` in 4 commits von
  chasing-your-tail-pager (auch in Anonymisierungs-Diffs). Fix via
  `git filter-repo --replace-text` + `git push --mirror --force`,
  beide lokalen Klone neu synchronisiert. argus-pager-2.0 /
  raypager / mvt-pager Repos clean.

### 01.05.2026 (Bug-Hunt-Round)
- **Cross-Report-Stub auf Display gefixt** — analyser pickte vorher die mtime-letzte
  `.md` aus dem report_dir, das war aber `cross_report_<sid>.md` (geschrieben NACH
  argus_report). Mit nur 1 Argus-Report im 4h-Fenster sagte der ein Stub:
  "Mindestens 2 Reports nötig". Filter auf `argus_report_*.md` zeigt jetzt den
  echten Report.
- **BT-Crash gefixt (vorerst)** — cyt's `analyze_pcap.py --bt-scans` erwartet
  JSON (von `bt_scanner.py` produziert), wir lieferten raw .btsnoop von btmon
  → `UnicodeDecodeError`. Quick-Fix: AUTO-Preset hat `bt: False`. BT-Detection
  bleibt informativ. Phase 2: scan_engine ruft `bt_scanner.py --output …json`
  parallel zum WiFi-Capture statt btmon.
- **Time-Drift gefixt** — Pager hatte `/etc/TZ=UTC+2`, also liefen
  `time.strftime` (lokal) und `datetime.utcnow` 2h auseinander.
  cross_report cutoff (UTC) und argus_report-Filename (lokal) hatten
  inkonsistente Anker → "0 Reports im 4h-Fenster" obwohl der Report da war.
  Beide Geraete jetzt UTC + per-run Sync via Mudi.
- **IMEI-Rotate** — pyserial fehlte auf dem Mudi (Pure-Python-Wheel
  installiert), Blue Merle funktioniert jetzt. Mudi rebootet nach jedem
  Rotate, Internet ist daher kurz weg.

### 30.04.2026 (Phase-1-Test)
- **Stop-Hänger gefixt** — nach Stop-Confirm zeigte das Display ~5s den
  alten Scan-Frame, weil `engine.finish()` (cyt + raypager-Analyser, MD-Report)
  blockiert. Neuer "Saving report..." Frame zeigt sofort, dass etwas passiert.
- **Umlaut-Boxes im Report gefixt** — der cyt-Analyser schreibt deutsche
  Strings ("Geraete", "Verdaechtig") in den .md-Report, der Display-Font
  hat aber keine Umlaut-Glyphs. `theme.ascii_safe()` ersetzt sie beim Rendern;
  die .md auf Disk bleibt unangetastet.
- **IMSI/SMS-Watch zeigen NA** auf dem Splash — `imsi_alerts.jsonl` und
  `silent_sms.jsonl` existieren auf dem Mudi nicht, weil die Watcher-Daemons
  dort noch nie gelaufen sind. Detection ist semantisch korrekt
  ("noch keine Daten") — Phase 2 entscheidet, ob wir die Daemons starten oder
  die Probe lockern (Existenz des Watcher-Scripts statt Output-Datei).

### 29.04.2026 (Multi-Band)
- **Multi-Band funktioniert technisch** (54 Frequenzen, kein Hopper-Error).
  In Vilnius bleiben 6 GHz und 5 GHz DFS leer — keine APs dort.
- **Geraete-Anzahl pro Scan niedrig (3-4)** — das ist Probe-Request-Frequenz
  von Mobilgeraeten, kein Capture-Bug. Die meisten Probes kommen auf 2,4 GHz
  Ch.1/6/11; Multi-Band hilft hier wenig.
- **Sensors-Header bug gefixt** — `analyser.py` separiert UI-Sensoren von
  Mudi-Background-Daemons.
- **Regdomain ist `US/DFS-FCC`** — Pineapple-Default. 2,4 GHz Ch.12/13 sind
  disabled. Bringt fuer Detection nichts.

---

## Wenn du dieses Dokument liest und neu beginnst

1. Lies diese Datei komplett.
2. Schauen ob seit der letzten Session committed wurde:
   ```sh
   ssh pager 'cd /root/payloads/user/reconnaissance/argus-pager-2.0 && \
     git status --short && git log --oneline -5'
   ```
3. Letzten Run-Status checken:
   ```sh
   ssh pager 'tail -50 /root/loot/argus/logs/last.log'
   ```
4. Falls letzter Run mit `rc=137` endete (SIGKILL durch payload-timeout)
   und Daten erhalten sind: `python3 tools/rerun_analyser.py <session_id>`
   um den Report nachtraeglich zu erzeugen.
5. Mit dem User abstimmen, wo es weitergeht. Naechster grosser Punkt
   sind die 1h-Live-Tests am 05.05. — danach `v2.1.0-alpha3` Commit.

Memory-Eintrag im Claude-Setup: `~/.claude/projects/.../memory/MEMORY.md`.
Wichtigste Einträge: `feedback_pager_umlauts.md`, `reference_pagerctl_display.md`.
Die `project_argus_pager.md`-Memory ist v1.x-Stand — älter als 2.0, mit Vorsicht.
