#!/usr/bin/env python3
"""OpenCelliD CSV-zu-SQLite Importer.

Konvertiert eine OpenCelliD-Country-CSV (z.B. 246.csv.gz fuer Litauen) in
eine kompakte SQLite-DB die opencellid.py als Offline-Cache nutzen kann.

CSV-Format (OpenCelliD):
    radio,mcc,mnc,area,cell,unit,lon,lat,range,samples,changeable,
    created,updated,averageSignal

Output-Schema:
    CREATE TABLE cells (
        radio TEXT,        -- 'GSM' / 'UMTS' / 'LTE' / 'NR'
        mcc   INTEGER,
        mnc   INTEGER,
        area  INTEGER,     -- LAC fuer GSM/UMTS, TAC fuer LTE
        cell  INTEGER,
        lat   REAL,
        lon   REAL,
        range INTEGER,     -- meters
        samples INTEGER,
        updated INTEGER,
        PRIMARY KEY (mcc, mnc, area, cell)
    );
    CREATE INDEX idx_cells ON cells (mcc, mnc, area, cell);

Nutzung:
    python3 tools/opencellid_import.py 246.csv.gz cells_246.sqlite
    python3 tools/opencellid_import.py --append 262.csv.gz cells.sqlite
    python3 tools/opencellid_import.py --info cells.sqlite

Im argus-Workflow:
    1. Lokal: tools/opencellid_import.py 246.csv.gz cells_lt.sqlite
    2. Upload: scp cells_lt.sqlite mudi:/root/loot/raypager/cell_db/cells.sqlite
    3. opencellid.py erkennt automatisch lokale DB und benutzt sie zuerst
       (API-Lookup nur noch als Fallback)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import os
import sqlite3
import sys
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS cells (
    radio   TEXT NOT NULL,
    mcc     INTEGER NOT NULL,
    mnc     INTEGER NOT NULL,
    area    INTEGER NOT NULL,
    cell    INTEGER NOT NULL,
    lat     REAL NOT NULL,
    lon     REAL NOT NULL,
    range_m INTEGER,
    samples INTEGER,
    updated INTEGER,
    PRIMARY KEY (mcc, mnc, area, cell)
);
CREATE INDEX IF NOT EXISTS idx_cells_lookup ON cells (mcc, mnc, area, cell);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def open_csv(path: str):
    """Open .csv or .csv.gz transparently."""
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def import_csv(csv_path: str, db_path: str, *, append: bool = False) -> dict:
    """Read OpenCelliD CSV and write to SQLite. Returns stats dict."""
    if not append and os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    inserted = 0
    skipped  = 0
    by_radio: dict[str, int] = {}
    by_mnc:   dict[int, int] = {}
    t0 = time.time()

    with open_csv(csv_path) as f:
        rd = csv.reader(f)
        rows = []
        for line in rd:
            if len(line) < 13:
                skipped += 1
                continue
            try:
                radio = line[0]
                mcc   = int(line[1])
                mnc   = int(line[2])
                area  = int(line[3])
                cell  = int(line[4])
                lon   = float(line[6])
                lat   = float(line[7])
                rng   = int(line[8]) if line[8] else 0
                samp  = int(line[9]) if line[9] else 0
                upd   = int(line[12]) if len(line) > 12 and line[12] else 0
            except (ValueError, IndexError):
                skipped += 1
                continue
            rows.append((radio, mcc, mnc, area, cell, lat, lon, rng, samp, upd))
            by_radio[radio] = by_radio.get(radio, 0) + 1
            by_mnc[mnc]     = by_mnc.get(mnc, 0)   + 1
            if len(rows) >= 5000:
                cur.executemany(
                    "INSERT OR REPLACE INTO cells "
                    "(radio,mcc,mnc,area,cell,lat,lon,range_m,samples,updated) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                inserted += len(rows)
                rows.clear()
        if rows:
            cur.executemany(
                "INSERT OR REPLACE INTO cells "
                "(radio,mcc,mnc,area,cell,lat,lon,range_m,samples,updated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            inserted += len(rows)

    # Metadaten
    cur.execute("INSERT OR REPLACE INTO meta (key,value) VALUES (?,?)",
                ("imported_at", str(int(time.time()))))
    cur.execute("INSERT OR REPLACE INTO meta (key,value) VALUES (?,?)",
                ("imported_from", os.path.basename(csv_path)))
    conn.commit()
    conn.close()

    return {
        "inserted":  inserted,
        "skipped":   skipped,
        "duration":  round(time.time() - t0, 2),
        "by_radio":  by_radio,
        "by_mnc":    by_mnc,
        "db_size":   os.path.getsize(db_path),
    }


def show_info(db_path: str) -> None:
    """Print DB statistics."""
    if not os.path.exists(db_path):
        print(f"DB nicht gefunden: {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print(f"DB: {db_path}  ({os.path.getsize(db_path):,} bytes)")
    print()

    # Total
    cur.execute("SELECT COUNT(*) FROM cells")
    total = cur.fetchone()[0]
    print(f"Total cells: {total:,}")

    # By radio
    print("\nBy RAT:")
    for radio, n in cur.execute(
            "SELECT radio, COUNT(*) FROM cells GROUP BY radio ORDER BY 2 DESC"):
        print(f"  {radio:6}  {n:,}")

    # By MCC
    print("\nBy MCC:")
    for mcc, n in cur.execute(
            "SELECT mcc, COUNT(*) FROM cells GROUP BY mcc ORDER BY 2 DESC"):
        print(f"  {mcc}     {n:,}")

    # By MNC (top 10)
    print("\nBy MCC/MNC (top 10):")
    for mcc, mnc, n in cur.execute(
            "SELECT mcc,mnc,COUNT(*) FROM cells GROUP BY mcc,mnc "
            "ORDER BY 3 DESC LIMIT 10"):
        print(f"  {mcc}/{mnc:<3}  {n:,}")

    # Meta
    print("\nMeta:")
    for k, v in cur.execute("SELECT key,value FROM meta"):
        if k == "imported_at":
            v = time.strftime("%Y-%m-%d %H:%M",
                              time.localtime(int(v))) + f" ({v})"
        print(f"  {k}: {v}")

    conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", help="Pfad zur CSV oder CSV.gz (oder DB bei --info)")
    p.add_argument("output", nargs="?", help="Ziel-SQLite-Datei")
    p.add_argument("--append", action="store_true",
                   help="An existierende DB anhaengen statt ueberschreiben")
    p.add_argument("--info", action="store_true",
                   help="DB-Statistiken anzeigen statt importieren")
    args = p.parse_args()

    if args.info:
        show_info(args.input)
        return

    if not args.output:
        p.error("output ist erforderlich (oder --info)")

    print(f"Importing {args.input} -> {args.output}...")
    stats = import_csv(args.input, args.output, append=args.append)
    print(f"\nDone in {stats['duration']}s:")
    print(f"  inserted: {stats['inserted']:,}")
    print(f"  skipped:  {stats['skipped']:,}")
    print(f"  db size:  {stats['db_size']:,} bytes")
    print(f"  by RAT:   {stats['by_radio']}")
    print(f"  by MNC:   {stats['by_mnc']}")


if __name__ == "__main__":
    main()
