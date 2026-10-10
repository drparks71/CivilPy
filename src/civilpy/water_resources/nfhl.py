#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""FEMA National Flood Hazard Layer (NFHL) at a crossing: the flood zone and
regulatory floodway, the base flood elevations and the flood-study cross
sections nearby, the FIRM panels and any LOMRs - what decides which
floodplain rule a bridge or culvert project has to meet.

Data: FEMA's public NFHL map service (``hazards.fema.gov``, the effective
FIRM database; layer ids below).  Elevations are as published (``V_DATUM``:
NAVD88 on modernised studies, NGVD29 on some older ones).

:func:`regulatory` names the NFIP minimum standard (44 CFR 60.3) the mapped
condition triggers.  Communities and states may adopt stricter rules, and
the effective FIRM / Flood Insurance Study (with any LOMR) is the record -
this is a screen to point at the right requirement, not a determination.

    h = flood_hazard(39.138161, -82.900469, radius_ft=250)
    h.in_floodway, h.zone, h.wsel_1pct_ft, regulatory(h)["key"]   # True, 'AE', 581.x, 'floodway'
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from civilpy.water_resources.nhdplus import nearest_on_paths

NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
LAYER = {"availability": 0, "lomr": 1, "panel": 3, "cross_section": 14, "bfe": 16, "zone": 28}
M_PER_FT = 0.3048
NODATA = -9999.0
#: ZONE_SUBTY values that mark the regulatory floodway.
FLOODWAY_SUBTYPES = ("FLOODWAY", "FLOODWAY CONTAINED IN CHANNEL", "COLORADO RIVER FLOODWAY",
                     "COMMUNITY ENCROACHMENT AREA", "STATE ENCROACHMENT AREA", "RIVERINE FLOODWAY SHOWN IN COASTAL ZONE",
                     "ADMINISTRATIVE FLOODWAY")
SFHA_ZONES = ("A", "AE", "AH", "AO", "AR", "A99", "V", "VE")
#: Zones published with base flood elevations (or depths).
DETAILED_ZONES = ("AE", "AH", "AO", "VE")


class NFHLError(RuntimeError):
    pass


@dataclass
class Zone:
    zone: str                       # FLD_ZONE: A, AE, AH, AO, X, D ...
    subtype: str = ""               # ZONE_SUBTY: FLOODWAY, 0.2 PCT ANNUAL CHANCE FLOOD HAZARD ...
    sfha: bool = False              # SFHA_TF: in the 1%-annual-chance special flood hazard area
    static_bfe_ft: float | None = None
    dfirm_id: str = ""
    study_type: str = ""

    @property
    def floodway(self) -> bool:
        return (self.subtype or "").upper() in FLOODWAY_SUBTYPES or "FLOODWAY" in (self.subtype or "").upper()

    @property
    def shaded_x(self) -> bool:
        return self.zone == "X" and "0.2 PCT" in (self.subtype or "").upper()


@dataclass
class Elevation:
    """A BFE line or a cross section, with its distance from the crossing."""
    elev_ft: float
    distance_ft: float
    datum: str = ""
    kind: str = "bfe"               # bfe | cross_section
    stream: str = ""
    station: float | None = None
    letter: str = ""


@dataclass
class Panel:
    panel: str
    effective: str = ""             # ISO date
    panel_type: str = ""


@dataclass
class LOMR:
    case: str
    effective: str = ""
    status: str = ""


@dataclass
class FloodHazard:
    lat: float
    lon: float
    radius_ft: float
    zone_at_point: Zone | None = None
    zones_nearby: list = field(default_factory=list)       # distinct zones within radius_ft
    bfes: list = field(default_factory=list)               # Elevation, nearest first
    cross_sections: list = field(default_factory=list)     # Elevation, nearest first
    panels: list = field(default_factory=list)
    lomrs: list = field(default_factory=list)

    @property
    def mapped(self) -> bool:
        return self.zone_at_point is not None or bool(self.zones_nearby) or bool(self.panels)

    @property
    def zone(self) -> str:
        return self.zone_at_point.zone if self.zone_at_point else ""

    @property
    def in_floodway(self) -> bool:
        """The crossing touches the regulatory floodway (at the point or within the radius)."""
        return any(z.floodway for z in ([self.zone_at_point] if self.zone_at_point else []) + self.zones_nearby)

    @property
    def in_sfha(self) -> bool:
        return any(z.sfha for z in ([self.zone_at_point] if self.zone_at_point else []) + self.zones_nearby)

    @property
    def wsel_1pct_ft(self) -> float | None:
        """Approximate 1%-annual-chance water surface at the crossing: the two
        nearest flood-study cross sections (else BFE lines) weighted by inverse
        distance; a static BFE where the zone carries one."""
        for pts in (self.cross_sections, self.bfes):
            near = [p for p in pts if p.elev_ft is not None][:2]
            if len(near) == 2 and near[0].elev_ft != near[1].elev_ft:
                d1, d2 = max(near[0].distance_ft, 1e-6), max(near[1].distance_ft, 1e-6)
                return (near[0].elev_ft * d2 + near[1].elev_ft * d1) / (d1 + d2)
            if near:
                return near[0].elev_ft
        if self.zone_at_point and self.zone_at_point.static_bfe_ft is not None:
            return self.zone_at_point.static_bfe_ft
        return None

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(mapped=self.mapped, zone=self.zone, in_floodway=self.in_floodway, in_sfha=self.in_sfha,
                 wsel_1pct_ft=self.wsel_1pct_ft)
        return d


# ── parsing (pure) ────────────────────────────────────────────────────────

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= NODATA + 1 or math.isnan(f) else f


def _date(ms) -> str:
    if ms in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return str(ms)


def _attrs(f) -> dict:
    return {k.upper(): v for k, v in (f.get("attributes") or {}).items()}


def _features(resp) -> list:
    if not isinstance(resp, dict) or "error" in resp:
        raise NFHLError(f"NFHL query failed: {(resp or {}).get('error')}")
    return resp.get("features", [])


def parse_zones(resp) -> list:
    out = []
    for f in _features(resp):
        a = _attrs(f)
        out.append(Zone(zone=(a.get("FLD_ZONE") or "").strip(), subtype=(a.get("ZONE_SUBTY") or "").strip(),
                        sfha=str(a.get("SFHA_TF") or "").upper() == "T", static_bfe_ft=_num(a.get("STATIC_BFE")),
                        dfirm_id=a.get("DFIRM_ID") or "", study_type=a.get("STUDY_TYP") or ""))
    return out


def distinct_zones(zones) -> list:
    seen, out = set(), []
    for z in zones:
        key = (z.zone, z.subtype, z.static_bfe_ft)
        if key not in seen:
            seen.add(key)
            out.append(z)
    return out


def _distance_ft(f, lat, lon) -> float:
    d, _ = nearest_on_paths(lat, lon, (f.get("geometry") or {}).get("paths"))
    return d / M_PER_FT if math.isfinite(d) else math.inf


def parse_elevations(resp, lat, lon, kind: str) -> list:
    """BFE lines (``ELEV``) or cross sections (``WSEL_REG``), nearest first."""
    out = []
    for f in _features(resp):
        a = _attrs(f)
        elev = _num(a.get("ELEV") if kind == "bfe" else a.get("WSEL_REG"))
        if elev is None:
            continue
        unit = (a.get("LEN_UNIT") or "Feet").lower()
        if unit.startswith("met"):
            elev /= M_PER_FT
        out.append(Elevation(elev_ft=elev, distance_ft=_distance_ft(f, lat, lon), datum=a.get("V_DATUM") or "",
                             kind=kind, stream=a.get("WTR_NM") or "", station=_num(a.get("STREAM_STN")),
                             letter=a.get("XS_LTR") or ""))
    return sorted(out, key=lambda e: e.distance_ft)


def parse_panels(resp) -> list:
    out = {}
    for f in _features(resp):
        a = _attrs(f)
        p = a.get("FIRM_PAN") or ""
        if p:
            out[p] = Panel(panel=p, effective=_date(a.get("EFF_DATE")), panel_type=a.get("PANEL_TYP") or "")
    return sorted(out.values(), key=lambda p: p.panel)


def parse_lomrs(resp) -> list:
    out = {}
    for f in _features(resp):
        a = _attrs(f)
        c = a.get("CASE_NO") or ""
        if c:
            out[c] = LOMR(case=c, effective=_date(a.get("EFF_DATE")), status=a.get("STATUS") or "")
    return sorted(out.values(), key=lambda x: x.effective, reverse=True)


# ── the rule it points at (pure) ──────────────────────────────────────────

def regulatory(h: FloodHazard) -> dict:
    """The NFIP minimum standard the mapped condition triggers:
    ``{"key", "title", "requirement", "cite", "notes"}``."""
    notes = []
    if h.lomrs:
        notes.append(f"{len(h.lomrs)} LOMR(s) revise the effective map here - read them with the FIRM "
                     f"({', '.join(x.case for x in h.lomrs[:3])}).")
    datums = {e.datum for e in h.cross_sections + h.bfes if e.datum}
    if datums - {"NAVD88"}:
        notes.append(f"elevations on {', '.join(sorted(datums))} - convert before comparing with NAVD88 LiDAR")
    if not h.mapped:
        return {"key": "unmapped", "title": "No effective NFHL data here",
                "requirement": "No digital FIRM: check the community's paper FIRM / FIS and NFHL availability.",
                "cite": "", "notes": notes}
    if h.in_floodway:
        return {"key": "floodway", "title": "Regulatory floodway",
                "requirement": "Encroachments in the floodway need an engineering analysis showing no increase "
                               "in the base flood elevation (a no-rise certification), or a CLOMR/LOMR.",
                "cite": "44 CFR 60.3(d)(3)", "notes": notes}
    touched = ([h.zone_at_point] if h.zone_at_point else []) + h.zones_nearby
    sfha = [z for z in touched if z.sfha]
    zone = next((z.zone for z in sfha if z.zone in DETAILED_ZONES), sfha[0].zone if sfha else h.zone)
    # BFEs apply when a zone the crossing touches is a detailed (BFE) zone, not
    # because a BFE line of some other stream is within the search radius
    if any(z.zone in DETAILED_ZONES or z.static_bfe_ft is not None for z in sfha):
        return {"key": "ae_no_floodway", "title": f"Zone {zone or 'AE'} with base flood elevations, no floodway",
                "requirement": "Until a floodway is designated, new development (with all other existing and "
                               "anticipated development) may not raise the base flood elevation more than 1.0 ft.",
                "cite": "44 CFR 60.3(c)(10)", "notes": notes}
    if h.in_sfha:
        return {"key": "approximate_a", "title": f"Approximate Zone {zone or 'A'} (no BFE published)",
                "requirement": "No base flood elevation or floodway on the map: obtain, review and reasonably use "
                               "any available BFE / floodway data, or develop the BFE for the project.",
                "cite": "44 CFR 60.3(b)(4)", "notes": notes}
    shaded = (h.zone_at_point and h.zone_at_point.shaded_x) or any(z.shaded_x for z in h.zones_nearby)
    return {"key": "shaded_x" if shaded else "outside",
            "title": "Zone X (0.2%-annual-chance floodplain)" if shaded else f"Zone {h.zone or 'X'} (outside the SFHA)",
            "requirement": "Outside the 1%-annual-chance special flood hazard area: no NFIP floodplain "
                           "development standard applies.", "cite": "", "notes": notes}


# ── service ───────────────────────────────────────────────────────────────

def query(layer: str, lat: float, lon: float, *, radius_ft: float = 0.0, geometry: bool = False,
          session=None, timeout: float = 60) -> dict:
    """One NFHL layer query at a point (``radius_ft`` > 0 searches around it)."""
    import requests

    s = session or requests
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
              "returnGeometry": "true" if geometry else "false", "f": "json"}
    if geometry:
        params["outSR"] = 4326
    if radius_ft > 0:                       # distance=0 makes the service return nothing
        params.update(distance=radius_ft, units="esriSRUnit_Foot")
    last = None
    for _ in range(3):
        try:
            r = s.request("GET", f"{NFHL}/{LAYER[layer]}/query", params=params, timeout=timeout)
            r.raise_for_status()
            d = r.json()
            if isinstance(d, dict) and "error" in d:
                raise NFHLError(f"NFHL {layer}: {d['error']}")
            return d
        except Exception as exc:                                   # noqa: BLE001
            last = exc
    raise NFHLError(f"NFHL {layer}: {last}")


def flood_hazard(lat: float, lon: float, *, radius_ft: float = 250.0, elevation_radius_ft: float = 1500.0,
                 session=None) -> FloodHazard:
    """Zones at and within ``radius_ft`` of the crossing, BFE lines and cross
    sections within ``elevation_radius_ft``, FIRM panels and LOMRs."""
    h = FloodHazard(lat, lon, radius_ft)
    at = parse_zones(query("zone", lat, lon, session=session))
    h.zone_at_point = next((z for z in at if z.sfha), at[0] if at else None)
    h.zones_nearby = distinct_zones(parse_zones(query("zone", lat, lon, radius_ft=radius_ft, session=session)))
    h.bfes = parse_elevations(query("bfe", lat, lon, radius_ft=elevation_radius_ft, geometry=True, session=session),
                              lat, lon, "bfe")
    h.cross_sections = parse_elevations(
        query("cross_section", lat, lon, radius_ft=elevation_radius_ft, geometry=True, session=session),
        lat, lon, "cross_section")
    h.panels = parse_panels(query("panel", lat, lon, session=session))
    h.lomrs = parse_lomrs(query("lomr", lat, lon, radius_ft=radius_ft, session=session))
    return h
