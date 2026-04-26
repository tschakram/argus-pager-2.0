# Changelog

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
