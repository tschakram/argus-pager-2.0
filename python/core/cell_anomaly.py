"""Cellular Anomaly Detection - Heuristiken auf Serving Cell + Neighbours.

Counter-Surveillance gegen IMSI-Catcher. Anomalien werden als gewichtete
Liste von Findings zurueckgegeben, plus aggregierter Risk-Level (none/
medium/high). Threat-Bump wird vom analyser aufgerufen.

Heuristiken:
  H1  0 Neighbours trotz urbaner Region        - HIGH (isolierter Catcher)
  H2  Sehr wenig Neighbours (1-2) trotz Stadt  - MEDIUM
  H3  Neighbor RSRP > Serving RSRP (lock-in)   - MEDIUM
  H4  Serving RSRP-Sprung >20 dBm zwischen
      Polls (Power-Boost-Angriff)              - HIGH
  H5  Serving PCID/CID Wechsel bei stationärem
      GPS                                       - MEDIUM
  H6  Serving auf untypischem Band fuer Carrier - MEDIUM
  H7  Sehr viele unique Neighbour-PCIs in
      kurzer Zeit (Drift)                       - MEDIUM
  H8  Serving RSRP sehr stark (>-50 dBm) ohne
      passende Neighbour-Cluster                - MEDIUM
  H9  GSM/WCDMA-Downgrade (bereits in
      cell_info.is_suspicious abgedeckt)        - HIGH

Persistenter State (rat_history.json auf Mudi) erlaubt Trend-Detection
ueber mehrere Polls hinweg (RSRP-Sprung, PCID-Drift). Hier nur die
Single-Poll-Analyse - der historische Vergleich kommt vom analyser
der mehrere Snapshots aus dem _mudi_loop bekommt.
"""
from __future__ import annotations

# ── Risk constants ─────────────────────────────────────────────
RISK_NONE   = "none"
RISK_LOW    = "low"
RISK_MEDIUM = "medium"
RISK_HIGH   = "high"

_RANK = {RISK_NONE: 0, RISK_LOW: 1, RISK_MEDIUM: 2, RISK_HIGH: 3}


def _max(a, b):
    return a if _RANK[a] >= _RANK[b] else b


# ── Single-Poll Heuristiken ─────────────────────────────────────

def analyse_snapshot(cell: dict, neighbours: dict | None,
                     assume_urban: bool = True) -> dict:
    """Analysiert einen einzelnen Mudi-Poll (Serving + Neighbours).

    Args:
        cell:        Output von cell_info.get_cell_info() (oder cell_lookup).
        neighbours:  Output von cell_info.get_neighbor_cells() oder None.
        assume_urban: True default - wir sind ueblicherweise in der Stadt;
                      auf False fuer rurale Tests.

    Returns dict:
        {
          "risk":       "none"/"medium"/"high",
          "findings":   [(code, severity, message), ...],
          "neighbour_count": int,
          "neighbour_band_diversity": int,
        }
    """
    findings: list[tuple[str, str, str]] = []
    risk = RISK_NONE

    nb_count = (neighbours or {}).get("count", 0)
    nb_list  = (neighbours or {}).get("neighbours", [])

    serving_rsrp = cell.get("rsrp") if cell else None
    serving_pci  = cell.get("pcid", cell.get("pci")) if cell else None

    # Weak-Signal-Schwelle: Modem kann unterhalb von -100 dBm RSRP keine
    # Neighbours mehr decoden, selbst wenn welche da sind. H1/H2/H8 sind
    # in dem Fall nicht aussagekraeftig (false positive).
    weak_signal = (serving_rsrp is not None and serving_rsrp < -100)

    # H1: 0 Neighbours urban
    if nb_count == 0 and assume_urban and cell and cell.get("rat") == "LTE":
        if weak_signal:
            findings.append(("H1-weak", RISK_LOW,
                             f"0 Neighbour Cells, aber RSRP {serving_rsrp} dBm "
                             "sehr schwach - Modem kann Neighbours nicht decoden, "
                             "keine Catcher-Aussage moeglich"))
        else:
            findings.append(("H1", RISK_HIGH,
                             "0 Neighbour Cells trotz urbaner Region - "
                             "isolierter Tower (Catcher-Indikator)"))
            risk = _max(risk, RISK_HIGH)
    elif 0 < nb_count <= 2 and assume_urban and cell and cell.get("rat") == "LTE":
        if weak_signal:
            findings.append(("H2-weak", RISK_LOW,
                             f"Nur {nb_count} Neighbours bei schwachem "
                             f"RSRP {serving_rsrp} dBm - kein Catcher-Indikator"))
        else:
            findings.append(("H2", RISK_MEDIUM,
                             f"Nur {nb_count} Neighbour Cells - "
                             "ungewoehnlich wenig fuer urbane Region"))
            risk = _max(risk, RISK_MEDIUM)

    # H3: Neighbour RSRP staerker als Serving (lock-in)
    if serving_rsrp is not None and nb_list:
        stronger = [n for n in nb_list
                    if isinstance(n.get("rsrp"), int)
                    and n["rsrp"] > serving_rsrp + 3]
        if stronger:
            best = max(stronger, key=lambda n: n.get("rsrp", -999))
            findings.append(("H3", RISK_MEDIUM,
                             f"Neighbour PCI={best.get('pci')} RSRP="
                             f"{best.get('rsrp')} dBm > Serving "
                             f"{serving_rsrp} dBm (Lock-in?)"))
            risk = _max(risk, RISK_MEDIUM)

    # H7: Viele unique Neighbour-PCIs (Drift / arbitrary catcher beacons)
    unique_pcis = {n.get("pci") for n in nb_list
                   if isinstance(n.get("pci"), int)}
    if len(unique_pcis) > 15:
        findings.append(("H7", RISK_MEDIUM,
                         f"{len(unique_pcis)} unique Neighbour-PCIs - "
                         "extrem hohe Cell-Dichte"))
        risk = _max(risk, RISK_MEDIUM)

    # H8: Serving RSRP sehr stark + wenige Neighbours
    # (nicht relevant bei weak signal)
    if (serving_rsrp is not None and serving_rsrp > -60
            and nb_count < 3 and assume_urban and not weak_signal):
        findings.append(("H8", RISK_MEDIUM,
                         f"Serving RSRP {serving_rsrp} dBm sehr stark, "
                         f"aber nur {nb_count} Neighbours - "
                         "moeglicher Catcher in Naehe"))
        risk = _max(risk, RISK_MEDIUM)

    # Band diversity (LTE inter-frequency Neighbours auf verschiedenen EARFCNs)
    earfcns = {n.get("earfcn") for n in nb_list
               if isinstance(n.get("earfcn"), int)}
    band_diversity = len(earfcns)

    return {
        "risk":     risk,
        "findings": [{"code": c, "severity": s, "message": m}
                     for c, s, m in findings],
        "neighbour_count":          nb_count,
        "neighbour_band_diversity": band_diversity,
        "serving_rsrp":             serving_rsrp,
        "serving_pci":              serving_pci,
    }


# ── Multi-Poll Heuristiken (Trend-Detection ueber mehrere Snapshots) ─

def analyse_trend(snapshots: list[dict]) -> dict:
    """Trend-Analyse ueber mehrere Snapshots (z.B. waehrend einer Argus-Session).

    snapshots: liste von Snapshot-Dicts, jeder mit
        {"timestamp", "serving_rsrp", "serving_pci", "serving_cid",
         "neighbour_count", "gps_lat", "gps_lon"}

    Returns wie analyse_snapshot.
    """
    findings: list[tuple[str, str, str]] = []
    risk = RISK_NONE

    if len(snapshots) < 2:
        return {"risk": risk, "findings": [],
                "rsrp_jump_max": 0, "pci_changes": 0}

    # H4: RSRP-Sprung zwischen zwei aufeinanderfolgenden Polls
    #
    # GPS-aware: ein 30-dBm-Sprung beim Drive (alte Cell -> neue Cell) ist
    # normal, KEIN Catcher-Indikator. Wenn zwischen den zwei Polls > 100 m
    # zurueckgelegt wurden ODER die Serving-PCI gewechselt hat, dann ist
    # der Sprung durch Bewegung/Handover erklaert.
    # H4 triggert nur bei stationaerem GPS + gleicher PCI + grossem Sprung
    # (= echter Power-Boost auf derselben Cell).
    H4_DISTANCE_THRESHOLD_M = 100
    rsrp_jump_max = 0
    rsrp_jump_event = None
    rsrp_jump_stationary = False
    for i in range(1, len(snapshots)):
        a = snapshots[i - 1]
        b = snapshots[i]
        ra = a.get("serving_rsrp")
        rb = b.get("serving_rsrp")
        if ra is None or rb is None:
            continue
        delta = abs(rb - ra)
        if delta <= rsrp_jump_max:
            continue
        # GPS-Distanz zwischen den zwei Polls (grobe Naeherung)
        try:
            dlat = (b.get("gps_lat", 0) - a.get("gps_lat", 0)) * 111000
            dlon = (b.get("gps_lon", 0) - a.get("gps_lon", 0)) * 70000
            dist = (dlat * dlat + dlon * dlon) ** 0.5
        except Exception:
            dist = -1   # GPS unbekannt
        same_pci = (a.get("serving_pci") == b.get("serving_pci")
                    and a.get("serving_pci") is not None)
        # Bewegung erklaert den Sprung -> ignorieren
        if dist > H4_DISTANCE_THRESHOLD_M:
            continue
        # Cell-Wechsel erklaert den Sprung -> ignorieren
        if not same_pci:
            continue
        rsrp_jump_max = delta
        rsrp_jump_event = (a, b)
        rsrp_jump_stationary = True

    if rsrp_jump_stationary and rsrp_jump_max >= 20:
        a, b = rsrp_jump_event
        findings.append(("H4", RISK_HIGH,
                         f"Stationary RSRP-Sprung {a.get('serving_rsrp')} -> "
                         f"{b.get('serving_rsrp')} dBm (delta {rsrp_jump_max}, "
                         f"gleiche PCI) - Power-Boost-Indikator"))
        risk = _max(risk, RISK_HIGH)
    elif rsrp_jump_stationary and rsrp_jump_max >= 12:
        findings.append(("H4-low", RISK_MEDIUM,
                         f"Moderater Stationary-RSRP-Sprung delta "
                         f"{rsrp_jump_max} dBm"))
        risk = _max(risk, RISK_MEDIUM)

    # H5: PCID-Wechsel bei stationaerem GPS
    pci_changes = 0
    stationary_pci_change = False
    for i in range(1, len(snapshots)):
        a = snapshots[i - 1]
        b = snapshots[i]
        pa = a.get("serving_pci")
        pb = b.get("serving_pci")
        if pa is None or pb is None or pa == pb:
            continue
        pci_changes += 1
        # GPS-Distanz (grobe Naeherung in m)
        try:
            dlat = (b.get("gps_lat", 0) - a.get("gps_lat", 0)) * 111000
            dlon = (b.get("gps_lon", 0) - a.get("gps_lon", 0)) * 70000
            dist = (dlat * dlat + dlon * dlon) ** 0.5
        except Exception:
            dist = -1
        if 0 <= dist < 30:  # weniger als 30 m bewegt
            stationary_pci_change = True
    if stationary_pci_change:
        findings.append(("H5", RISK_MEDIUM,
                         f"PCID-Wechsel bei stationaerem GPS "
                         f"({pci_changes} Wechsel total) - erzwungener Handover?"))
        risk = _max(risk, RISK_MEDIUM)

    return {
        "risk":          risk,
        "findings":      [{"code": c, "severity": s, "message": m}
                          for c, s, m in findings],
        "rsrp_jump_max": rsrp_jump_max,
        "pci_changes":   pci_changes,
    }


def aggregate(snapshot_result: dict, trend_result: dict) -> dict:
    """Kombiniert Single-Poll + Trend-Analyse zu einem Gesamt-Befund."""
    findings = list(snapshot_result.get("findings", [])) + \
               list(trend_result.get("findings", []))
    risk = _max(snapshot_result.get("risk", RISK_NONE),
                trend_result.get("risk", RISK_NONE))
    return {
        "risk":     risk,
        "findings": findings,
        "snapshot": snapshot_result,
        "trend":    trend_result,
    }
