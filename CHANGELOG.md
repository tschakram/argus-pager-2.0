# Changelog

## 2.0.0-alpha5 — UI was slow, preset menu fix, IMEI section (2026-04-26)

### Performance
- **Screenshot mode no longer blocks the UI thread.** flip() now only
  reads /dev/fb0 (cheap) and hands the bytes to a daemon worker thread
  for RGB conversion + rotate + PNG encode. If the worker is busy, the
  next shot is dropped (logged as "queue full"). Rate-limit raised
  from 1s to 2s. zlib level lowered from 6 to 1. The user reported
  multi-second lag per click in alpha4 - that's gone.
- Queue depth is 3, so a burst of fast screen changes still gets all
  three shots; only sustained spam drops frames.

### UI
- **Preset menu: description no longer overlaps CUSTOM.** alpha4
  pinned the description in a fixed slot above the footer; with the
  larger FONT_BODY of 28 the third list item collided with the
  description text. Now the description is rendered *inside* the
  highlighted row as a smaller indented sub-line, so non-selected rows
  stay short and there is never any overlap.

### Docs
- README has a new IMEI-Changer section explaining the rotate flow
  (radio off -> Blue Merle rotate -> radio on) and the OPSEC/OPDEC
  caveats around IMEI rotation alone (SIM swap, location change,
  MAC/BT-addr randomization).

## 2.0.0-alpha4 — Auto-screenshot mode + remove fake Pager-GPS (2026-04-26)

### New
- **Auto-screenshot mode** - set `ARGUS_SCREENSHOTS=1` (env var or in
  `payload.sh`) and every distinct UI state is dumped to
  `/root/loot/argus/screenshots/<sessionid>/<seq>_<screen>.png`.
  Implemented as a monkey-patch over `pager.flip()` with a 1s rate-limit
  inside the same screen and a force-flag at every screen boundary.
  `post_scan` is instrumented per sub-step so each step gets a named PNG.
- `tools/screenshot.sh` - shell wrapper that sets `PATH` /
  `LD_LIBRARY_PATH` so `python3` finds `libpython3.11.so` over SSH.
  Replaces the unreliable inline `ssh pager 'python3 ...'` call.
- `tools/pull_screenshots.sh` - pulls the most recent screenshot
  session off the pager via `scp -r`.

### Bugfix
- **Pager has no internal GPS** - removed the fake `Pager GPS` self-check
  in `splash` (was checking for `/dev/ttyACM0` on the pager, which never
  exists; the GPS dongle sits on the Mudi). Splash now reports
  `Mudi (GPS+Cell)` as one combined check.
- `gps_pager` removed from all presets and from the scan-config toggle
  list. The remaining `GPS (Mudi)` toggle is the only GPS source.

## 2.0.0-alpha3 — Layout buffer, screenshot tool, README rewrite (2026-04-26)

### Bugfixes
- **Post-scan layout** — Silent-SMS / IMSI / Upload / IMEI step labels and
  yes/no questions are now placed at `BODY_Y + FONT_TITLE + 4` so display
  fonts (Steelfish ascender) can no longer poke up into the screen header.
  Was the cause of the half-overlapped Silent-SMS title in alpha2 testing.
- **Body breathing room** — `theme.BODY_Y = HEADER_H + 12` (was +6) gives
  enough vertical buffer between the divider and any centered title.
- **Header internals** — ARGUS / title / version baselines pushed down 2px
  each so display-font ascenders don't clip past the top edge.

### New
- **`tools/screenshot.py`** - reads `/dev/fb0` directly, decodes RGB565,
  rotates 270deg back to landscape, writes a PNG with stdlib only.
  Works while `pagerctl` owns the framebuffer (the Pineapple "Virtual
  Pager" web preview goes blank during a session - this is the way to
  capture screens for the README / docs).
- **Font auto-discovery** - any `*.ttf` dropped into
  `python/assets/fonts/` is now picked up automatically. Liberation
  fonts also added to the system search path.

### Docs
- **README rewrite** - hero block with use-cases up top, "wann benutze
  ich was" preset table, condensed Bedienanleitung, install snippet,
  test/debug section. Detail moved out.
- **`docs/features.md`** - all detectors explained in detail, one
  section per detector with threat model, detection logic, report
  output, and config knobs. v2.1 backlog moved here too.

## 2.0.0-alpha2 — Readability + testability pass (2026-04-26)

### UX
- **Schrift größer + scrollbar wo nötig.** FONT_TITLE 32 -> 36, FONT_BODY 24 -> 28,
  FONT_SMALL 18 -> 22. Header- und Footerhöhe entsprechend angehoben.
- **scan_live:** komplett auf FONT_*-relative Y-Werte umgestellt; Datenqualitäts-
  Ampel ist jetzt scrollbar (UP/DOWN), wenn mehr Sensoren aktiv sind als auf
  den Bildschirm passen. Footer zeigt `[UP/DN] Scroll` nur wenn nötig.
- **post_scan, splash, report_view, preset_menu** alle auf den neuen Layout-
  Standard gezogen (Card-Höhe, Listen-Row-Height, Centered-Title-Y leiten sich
  jetzt aus FONT_BODY/FONT_TITLE ab statt hardgecodet).
- Quality-Light-Bullet ist jetzt **vertikal mittig** zur Schrift, Detail-Text
  rechtsbündig.

### Testbarkeit
- `core.deauth_monitor` refactored: `_process_line()` ist jetzt eine eigene
  Methode und kann ohne tcpdump-Subprocess gefüttert werden.
- **`tools/deauth_test.py`**: Offline-Smoke-Test mit 4 Szenarien (idle,
  background trickle, active flood, multi-source). Läuft vom Pager aus,
  ohne dass irgendein Frame durch die Luft fliegt.
- README: neuer Abschnitt **„Deauth-Detector testen"** mit 3 Pfaden
  (Mock / PCAP-Replay / Lab on-device).

## 2.0.0-alpha — First Pager Test (2026-04-25)

### Bugfixes vs Skeleton
- **Glyph rendering** — alle User-facing Strings auf reines ASCII gebracht
  (`·`, `…`, `×` durch `:`, `...`, `x` ersetzt). Behebt `?`-Platzhalter
  auf dem Pager-Display, weil das default `Steelfish.ttf` keine Unicode-Glyphen
  jenseits des Basis-ASCII bietet.
- **Font-Reihenfolge** — DejaVu wird jetzt bevorzugt, Steelfish nur als Fallback.
- **Report-View** — `[A] View Report` zeigt jetzt einen In-Memory-Report
  wenn keine `.md` auf der Disk liegt (z.B. wenn cyt/raypager noch nicht
  gemountet sind).
- **Post-Scan** — `[B]` (rot) ist jetzt überall „Skip + weiter", nicht „nichts
  passiert". Result-Screens akzeptieren A oder B zum Weitergehen.

### Neue Features
- **Deauth-Flood-Detector** (`core/deauth_monitor.py`) — passive `tcpdump`-Watcher,
  läuft automatisch wenn WiFi-Toggle aktiv ist. Live-Anzeige im Scan-Screen,
  Threat-Level HIGH bei Floods. Logs in `/root/loot/argus/deauth.jsonl`.
- **Bedienanleitung** in der README.
- **Roadmap v2.1+** — 15 weitere geplante Detektoren als Tabelle.

## 2.0.0 — Skeleton (WIP)

Komplett neu aufgesetztes Frontend für argus-pager.

### Breaking changes vs 1.3
- Frontend ist jetzt **Python + pagerctl** statt Bash + DuckyScript-Builtins.
- Die 7 Modi (`0`–`6`) wurden zusammengelegt zu **3 Presets**: `STANDARD`, `DEEPSCAN`, `CUSTOM`.
  - Cross-Report ist jetzt Teil von `STANDARD` (vorher nur in `5` / `6`).
  - Hotel-Scan + Camera-Activity laufen unter `DEEPSCAN` (Cameras-Toggle), oder im `CUSTOM`-Modus.
  - „WiFi only", „WiFi+GPS", „WiFi+BT", „WiFi+BT+GPS" gibt es nicht mehr — `CUSTOM` mit den entsprechenden Toggles ersetzt sie.
- `payload.sh` ist von 1488 → ~40 Zeilen geschrumpft (nur Launcher).
- Pre-Scan-Settings sind ein einziger Toggle-Screen statt 5 hintereinander geschalteter NUMBER_PICKER.
- IMSI-Monitor + Silent-SMS-Watcher laufen jetzt **immer passiv** im Hintergrund (sobald der Mudi erreichbar ist) — sie sind keine Modus-Komponente mehr.

### New
- Live-Scan-Screen mit Round-Counter, Restzeit, Datenqualitäts-Ampel und Live-Counter (WiFi/BT/IMSI/GPS).
- Pause / Resume — pausiert nur die laufende Capture-Runde, Hintergrund-Watcher laufen weiter.
- Threat-Card-Report mit Ampel-Farbe (clean/low/medium/high).
- Scrollbare Markdown-Report-Anzeige direkt am Pager.
- OPSEC-Hook erweitert: blockiert jetzt auch generische API-Key-Pattern und SSH-Private-Keys.

### Migration
- `config.json` von 1.3 funktioniert weiter. Neue Keys: `ui`, `presets`, `data_quality`. Defaults greifen wenn die Keys fehlen.
- `cyt`- und `raypager`-Submodule werden eingehängt wie in 1.3.
- Loot-Layout unverändert: `/root/loot/argus/{pcap,reports,logs,gps_track.csv}`.
- IMEI-Rotation, OpenCelliD-Upload und Watchlist-Add funktionieren wie vorher, aber der Dialog läuft jetzt über die `pagerctl`-Screens.

### Known TODO
- `python/assets/fonts/DejaVuSansMono.ttf` muss noch hinzugefügt werden (oder System-Font wird verwendet).
- Submodule (`cyt`, `raypager`) müssen via `git submodule add` hinzugefügt werden, sobald das Remote existiert.
- Erste Live-Tests am Pager stehen aus.
