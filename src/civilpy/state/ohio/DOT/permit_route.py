"""Permit route screening — which bridges a permit load meets between two
points on Ohio roads, and whether each one is a load, vertical-clearance or
width problem.

The road route comes from an OSRM instance (the public demo server by
default): the passenger-car route, so permit-routing restrictions are NOT
applied — the point is to score the bridges on the road the hauler would
drive, not to find a legal path.

Bridges come from a :class:`BridgeSource`. The public ODOT TIMS Bridge
Inventory layer (:class:`TIMSBridgeSource`) works anywhere with internet;
an agency running its own SNBI mirror supplies a richer source (per-vehicle
rating factors, every feature's clearance). Each bridge near the route is
tied to the road the route is on at that point three ways, in order of
trust:

1. **LRS conflation** — the ODOT road inventory (public TIMS layer) is asked
   for the segments around the bridge; the one the route is riding gives an
   NLF_ID (``SFRAIR00071**C`` = state, Franklin, IR 71, cardinal) which is
   compared with the NLF_IDs the inventory records for the roadway carried
   and the roadway under.
2. **Route tokens** — the router's ``ref`` (``"US 36; SR 37"``) against the
   inventory's B.RT route type + number.
3. **Names** — ``"Wilson Road"`` against the feature names.

Every check is a capacity / demand ratio so a map can colour them on one
scale: < 1 red, 1 → 2 yellow → green.

* **load** — the vehicle's rating factor when the source has it; else the
  design-load operating RF when the vehicle *is* the design load; else an
  estimate from the rated vehicles by the simple-span M+ ratio at the
  maximum span (the cheap end of the ORIL 2026 live-load-effect-ratio
  method, ``civilpy.structural.rating_ratios``), taking the lowest implied
  value and labelled ``estimated``.
* **vertical** — minimum vertical clearance of the roadway the route is on:
  under the bridge, or the carried roadway for a through structure
  (99.9 = unrestricted).
* **width** — usable surface width of that roadway (curb-to-curb fallback).

Example::

    from civilpy.state.ohio.DOT.permit_route import screen_route, TIMSBridgeSource
    out = screen_route((39.9612, -82.9988), (40.30, -82.85), "SU6",
                       height_ft=13.5, width_ft=8.5, source=TIMSBridgeSource())
    for b in out["bridges"]:
        print(b["station_mi"], b["sfn"], b["relation"], b["min_ratio"], b["status"])
"""
from __future__ import annotations

import datetime
import logging
import math
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

import requests

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

logger = logging.getLogger(__name__)

OSRM_BASE_URL = "https://router.project-osrm.org"
TIMS_BRIDGES_URL = ("https://tims.dot.state.oh.us/ags/rest/services/Assets/"
                    "Bridge_Inventory/MapServer/0/query")
TIMS_ROADS_URL = ("https://tims.dot.state.oh.us/ags/rest/services/Roadway_Information/"
                  "Road_Inventory/MapServer/0/query")

ODOT_PERMITS_URL = "https://www.transportation.ohio.gov/working/permits/special-hauling-permits"
OHPS_URL = "https://haulingpermits.transportation.ohio.gov/"
DISCLAIMER = (
    "DISCLAIMER — Permit route screen. This tool is not endorsed by, affiliated with, or "
    "approved by the State of Ohio or the Ohio Department of Transportation. It does not "
    "replace the need to apply for and receive an actual Special Hauling Permit through "
    f"ODOT's Ohio Hauling Permit System ({OHPS_URL}; program information at {ODOT_PERMITS_URL}), "
    "nor the permits of any county, township, municipality or the Ohio Turnpike whose roads the "
    "load will use. Results are computed from public inventory data and a passenger-car road "
    "route; the data may be incomplete, out of date or wrong, rating factors marked 'estimated' "
    "are approximations, and permit routing restrictions are not applied. The tool is provided "
    "AS IS, without warranty of any kind, for informational purposes only; use it at your own "
    "risk and verify every clearance, rating and posting with the responsible agency before "
    "moving a load."
)
#: Set False (or call ``configure(print_disclaimer=False)``) to stop the
#: disclaimer being written to stderr on every screen — for a host that
#: shows it in its own UI. It is always included in the result.
PRINT_DISCLAIMER = True

BUFFER_M = 30.0            # how far off the road centreline a bridge point may sit
ROAD_LOOKUP_M = 60.0       # envelope half-width for the road-inventory conflation
LEGAL_HEIGHT_FT = 13.5     # ORC 5577.05
LEGAL_WIDTH_FT = 8.5
UNRESTRICTED_FT = 99.0     # SNBI / NBI 99.9 = no vertical restriction
ROUTE_CACHE_S = 60 * 60 * 24 * 7
ROAD_CACHE_S = 60 * 60 * 24 * 30
HTTP_TIMEOUT = 30

# ── vehicles ────────────────────────────────────────────────────────────────
VEHICLE_GROUPS = (
    ("AASHTO design", ("HL-93", "HS20")),
    ("AASHTO legal", ("Type 3", "Type 3S2", "Type 3-3")),
    ("Specialized hauling (SHV)", ("SU4", "SU5", "SU6", "SU7")),
    ("Emergency (FAST Act)", ("EV2", "EV3")),
    ("Ohio legal", ("2F1", "3F1", "4F1", "5C1")),
    ("Ohio permit", ("S-PL60T", "S-PL65T")),
)
VEHICLES = tuple(n for _g, names in VEHICLE_GROUPS for n in names)
DESIGN_LOAD_ALIASES = {"HS20": "HS20", "HS20M": "HS20", "HS-20": "HS20", "HS20+MOD": "HS20",
                       "HL93": "HL-93", "HL-93": "HL-93"}


def list_vehicles() -> list[dict]:
    from civilpy.structural.aashto.vehicles import RATING_VEHICLES
    out = []
    for group, names in VEHICLE_GROUPS:
        for n in names:
            v = RATING_VEHICLES[n]
            out.append({"name": n, "group": group, "gvw_tons": round(v.gvw_tons, 2),
                        "axles": len(v.axle_loads_kip),
                        "wheelbase_ft": round(v.wheelbase_ft, 1),
                        "reference": v.reference})
    return out


# ── cache (duck-typed: Django's cache works, so does the dict below) ───────
class _MemoryCache:
    def __init__(self):
        self._d: dict = {}

    def get(self, key, default=None):
        hit = self._d.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        self._d.pop(key, None)
        return default

    def set(self, key, value, timeout=None):
        self._d[key] = (time.time() + (timeout or 3600), value)


cache = _MemoryCache()


def configure(*, cache_backend=None, osrm_base_url: str | None = None,
              print_disclaimer: bool | None = None) -> None:
    """Point the module at a shared cache (anything with ``get``/``set``),
    a self-hosted OSRM, and/or silence the stderr disclaimer."""
    global cache, OSRM_BASE_URL, PRINT_DISCLAIMER
    if cache_backend is not None:
        cache = cache_backend
    if osrm_base_url:
        OSRM_BASE_URL = osrm_base_url.rstrip("/")
    if print_disclaimer is not None:
        PRINT_DISCLAIMER = bool(print_disclaimer)


# ── records a source hands back ─────────────────────────────────────────────
@dataclass
class FeatureRecord:
    """One roadway / waterway / railway the bridge carries or crosses."""
    kind: str                              # H highway, W waterway, R rail, P pedestrian, …
    location: str                          # C carried on the bridge, B under it
    name: str = ""
    lrs_id: str = ""                       # ODOT NLF_ID / SNBI B.H.06, "" unknown
    min_vert_clearance_ft: Optional[float] = None
    usable_width_ft: Optional[float] = None
    routes: list[tuple[str, str]] = field(default_factory=list)   # (B.RT.04 type, number)

    @property
    def is_highway(self) -> bool:
        return (self.kind or "").upper().startswith("H")

    @property
    def carried(self) -> bool:
        return (self.location or "").upper() in ("C", "T", "L", "A")

    @property
    def under(self) -> bool:
        return (self.location or "").upper() == "B"


@dataclass
class BridgeRecord:
    sfn: str
    lat: float
    lon: float
    name: str = ""
    max_span_ft: Optional[float] = None
    curb_width_ft: Optional[float] = None
    design_load: str = ""                  # B.LR.01 / NBI 31 text ("HS20M", "HL93")
    design_opr_rf: Optional[float] = None  # B.LR.06
    continuous: bool = False
    features: list[FeatureRecord] = field(default_factory=list)
    known_rfs: dict[str, tuple[float, str]] = field(default_factory=dict)   # vehicle → (RF, source)
    posting_code: str = ""
    posting_since: Optional[str] = None
    year_built: Optional[int] = None


class BridgeSource(Protocol):
    def bridges_in(self, bbox: tuple[float, float, float, float]) -> list[BridgeRecord]:
        """Bridges inside ``(min_lat, min_lon, max_lat, max_lon)``. May be
        shells (location + geometry only) when the source also defines
        ``hydrate``."""
        ...

    def by_sfn(self, sfn: str) -> Optional[BridgeRecord]:
        ...

    # optional: fill features / rating factors / posting for the few bridges
    # that land on the route, so a long route does not pull every bridge in
    # its bounding box in full
    # def hydrate(self, bridge: BridgeRecord) -> BridgeRecord: ...


# ── routing ─────────────────────────────────────────────────────────────────
class RoutingError(RuntimeError):
    pass


def osrm_route(start: tuple[float, float], end: tuple[float, float]) -> dict:
    """Driving route start→end: ``{"coords": [[lat, lon], …], "distance_m",
    "duration_s", "steps": [{"name", "ref", "distance_m", "d0", "d1"}]}``.
    ``d0``/``d1`` are each step's cumulative station range so a bridge can
    be attributed to the road it sits on. Cached a week per rounded pair."""
    key = "permit-route:%.5f,%.5f:%.5f,%.5f" % (*start, *end)
    hit = cache.get(key)
    if hit is not None:
        return hit
    url = (f"{OSRM_BASE_URL}/route/v1/driving/{start[1]:.6f},{start[0]:.6f};"
           f"{end[1]:.6f},{end[0]:.6f}")
    try:
        r = requests.get(url, params={"overview": "full", "geometries": "geojson",
                                      "steps": "true"}, timeout=HTTP_TIMEOUT)
        data = r.json()
    except Exception as exc:
        raise RoutingError(f"routing service unreachable ({exc})") from exc
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(data.get("message") or f"routing failed ({data.get('code')})")
    route = data["routes"][0]
    coords = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
    steps, d = [], 0.0
    for leg in route["legs"]:
        for s in leg["steps"]:
            seg = polyline_length_m([[c[1], c[0]] for c in s["geometry"]["coordinates"]])
            steps.append({"name": s.get("name") or "", "ref": s.get("ref") or "",
                          "distance_m": round(seg, 1), "d0": d, "d1": d + seg})
            d += seg
    out = {"coords": coords, "distance_m": route["distance"], "duration_s": route["duration"],
           "steps": steps, "source": OSRM_BASE_URL}
    cache.set(key, out, ROUTE_CACHE_S)
    return out


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def polyline_length_m(coords) -> float:
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:]))


# ── flat-earth geometry (metres, good to ~0.1 % across a state) ─────────────
class LocalFrame:
    """Equirectangular projection about a reference latitude."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = 110_574.0

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky


class Polyline:
    """A projected polyline with cumulative stations; nearest-point queries."""

    def __init__(self, xy: list[tuple[float, float]]):
        self.pts = xy
        self.cum = [0.0]
        for a, b in zip(xy, xy[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))

    @property
    def length(self) -> float:
        return self.cum[-1]

    def nearest(self, x: float, y: float) -> tuple[float, float, float]:
        """(distance, station, heading_rad) of the closest point on the line."""
        best = (float("inf"), 0.0, 0.0)
        for i, (a, b) in enumerate(zip(self.pts, self.pts[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
            px, py = a[0] + t * dx, a[1] + t * dy
            d = math.hypot(x - px, y - py)
            if d < best[0]:
                best = (d, self.cum[i] + t * math.sqrt(L2), math.atan2(dy, dx))
        return best

    def heading_at(self, station: float) -> float:
        for i in range(1, len(self.cum)):
            if station <= self.cum[i] or i == len(self.cum) - 1:
                a, b = self.pts[i - 1], self.pts[i]
                return math.atan2(b[1] - a[1], b[0] - a[0])
        return 0.0


def heading_diff(a: float, b: float) -> float:
    """Smallest angle between two undirected headings (rad, 0..π/2)."""
    d = abs((a - b + math.pi) % math.pi)
    return min(d, math.pi - d)


# ── road-name / LRS matching ────────────────────────────────────────────────
_REF_TYPES = {"I": "1", "IR": "1", "US": "2", "SR": "3", "OH": "3", "ST": "3",
              "CR": "4", "TR": "5"}
_REF_RE = re.compile(r"\b(I|IR|US|SR|OH|CR|TR)[\s-]*(\d{1,4})\b", re.I)
_NAME_RE = re.compile(
    r"\b(interstate|state route|state rte|us route|u\.?s\.? highway|county road|"
    r"township road)\s+(\d{1,4})\b", re.I)
_NAME_TYPES = {"interstate": "1", "us route": "2", "us highway": "2",
               "state route": "3", "state rte": "3", "county road": "4", "township road": "5"}
# NLF_ID: jurisdiction, county, route type, number, suffix, cardinality
_NLF_RE = re.compile(r"^([SCTMU])([A-Z]{3})([A-Z]{2})(\d{3,5})([A-Z0-9*]{0,2})([CN]?)$")
_NLF_TYPES = {"IR": "1", "US": "2", "SR": "3", "CR": "4", "TR": "5"}


def route_tokens(ref: str, name: str) -> set[str]:
    """``"US 36; SR 37"`` / ``"State Route 61"`` → ``{"2:36", "3:37", "3:61"}``."""
    toks = set()
    for m in _REF_RE.finditer(ref or ""):
        toks.add(f"{_REF_TYPES[m.group(1).upper()]}:{int(m.group(2))}")
    for m in _NAME_RE.finditer(name or ""):
        kind = re.sub(r"[.]", "", m.group(1).lower())
        code = _NAME_TYPES.get(kind)
        if code:
            toks.add(f"{code}:{int(m.group(2))}")
    return toks


def bridge_route_tokens(routes) -> set[str]:
    toks = set()
    for rtype, rnum in routes:
        num = str(rnum or "").strip().lstrip("0")
        if num.isdigit() and str(rtype or "").strip():
            toks.add(f"{str(rtype).strip()}:{int(num)}")
    return toks


def parse_nlf(nlf: str) -> Optional[dict]:
    """``"SFRAIR00071**C"`` → jurisdiction S, county FRA, type IR, number 71,
    cardinal C; ``None`` for anything that is not an NLF_ID."""
    m = _NLF_RE.match((nlf or "").strip().upper())
    if not m:
        return None
    j, county, rtype, num, suffix, card = m.groups()
    return {"jurisdiction": j, "county": county, "type": rtype, "number": int(num),
            "suffix": suffix, "cardinal": card, "base": f"{j}{county}{rtype}{num}{suffix}"}


def nlf_token(nlf: str) -> Optional[str]:
    p = parse_nlf(nlf)
    if p and p["type"] in _NLF_TYPES:
        return f"{_NLF_TYPES[p['type']]}:{p['number']}"
    return None


def nlf_base(nlf: str) -> str:
    p = parse_nlf(nlf)
    return p["base"] if p else ""


def _norm_name(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"\b(EB|WB|NB|SB|EAST|WEST|NORTH|SOUTH)\b", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(ROAD|RD)\b", "RD", s)
    s = re.sub(r"\b(STREET|ST)\b", "ST", s)
    s = re.sub(r"\b(AVENUE|AVE)\b", "AVE", s)
    s = re.sub(r"\b(PIKE|PK)\b", "PIKE", s)
    return " ".join(s.split())


def names_match(a: str, b: str) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    return na == nb or (len(na) > 4 and na in nb) or (len(nb) > 4 and nb in na)


# ── road-inventory conflation (public TIMS) ─────────────────────────────────
def roads_near(lat: float, lon: float, half_m: float = ROAD_LOOKUP_M) -> list[dict]:
    """ODOT road-inventory segments in a box about a point:
    ``[{"nlf_id", "street", "route_type", "route_nbr", "divided", "truck_route",
    "paths": [[[lat, lon], …], …]}, …]``. Cached 30 days per rounded point."""
    key = "permit-roads:%.4f,%.4f" % (lat, lon)
    hit = cache.get(key)
    if hit is not None:
        return hit
    dlat = half_m / 110_574.0
    dlon = half_m / (111_320.0 * math.cos(math.radians(lat)))
    env = {"xmin": lon - dlon, "ymin": lat - dlat, "xmax": lon + dlon, "ymax": lat + dlat,
           "spatialReference": {"wkid": 4326}}
    import json as _json
    try:
        r = requests.post(TIMS_ROADS_URL, data={
            "geometry": _json.dumps(env), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outFields": "NLF_ID,STREET_NAME,ROUTE_TYPE,ROUTE_NBR,DIVIDED_HWY_IND,TRUCK_ROUTE_IND",
            "f": "json"}, timeout=HTTP_TIMEOUT)
        data = r.json()
    except Exception as exc:
        logger.warning("TIMS road inventory lookup failed at %s,%s: %s", lat, lon, exc)
        return []
    out = []
    for f in data.get("features", []):
        a = f.get("attributes", {})
        paths = [[[p[1], p[0]] for p in path] for path in f.get("geometry", {}).get("paths", [])]
        out.append({"nlf_id": a.get("NLF_ID") or "", "street": a.get("STREET_NAME") or "",
                    "route_type": a.get("ROUTE_TYPE") or "", "route_nbr": a.get("ROUTE_NBR") or "",
                    "divided": a.get("DIVIDED_HWY_IND") == "Y",
                    "truck_route": a.get("TRUCK_ROUTE_IND") == "Y", "paths": paths})
    cache.set(key, out, ROAD_CACHE_S)
    return out


def road_under_route(lat: float, lon: float, frame: LocalFrame, route: Polyline,
                     station: float, max_offset_m: float = 12.0,
                     max_skew_rad: float = math.radians(25)) -> Optional[dict]:
    """The road-inventory segment the route is riding at ``station``: the one
    closest to the route's point there and heading the same way. ``None``
    when the inventory has nothing that lines up (a ramp the inventory
    codes differently, or a service outage)."""
    heading = route.heading_at(station)
    best, best_d = None, max_offset_m
    for seg in roads_near(lat, lon):
        for path in seg["paths"]:
            pl = Polyline([frame.xy(p[0], p[1]) for p in path])
            if len(pl.pts) < 2:
                continue
            # distance from the route point to this segment + its heading there
            rx, ry = _route_point(route, station)
            d, _s, h = pl.nearest(rx, ry)
            if d < best_d and heading_diff(h, heading) <= max_skew_rad:
                best, best_d = {**seg, "offset_m": round(d, 1)}, d
    if best:
        best = {k: v for k, v in best.items() if k != "paths"}
    return best


def _route_point(route: Polyline, station: float) -> tuple[float, float]:
    for i in range(1, len(route.cum)):
        if station <= route.cum[i] or i == len(route.cum) - 1:
            a, b = route.pts[i - 1], route.pts[i]
            seg = route.cum[i] - route.cum[i - 1]
            t = 0.0 if seg == 0 else (station - route.cum[i - 1]) / seg
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
    return route.pts[0]


# ── per-bridge assessment ───────────────────────────────────────────────────
@dataclass
class Check:
    kind: str                 # load | vertical | width
    ratio: Optional[float]    # capacity / demand; None = no data
    capacity: Optional[float]
    demand: float
    unit: str
    source: str
    note: str = ""
    estimated: bool = False

    def as_dict(self) -> dict:
        return {"kind": self.kind, "ratio": None if self.ratio is None else round(self.ratio, 3),
                "capacity": self.capacity, "demand": self.demand, "unit": self.unit,
                "source": self.source, "note": self.note, "estimated": self.estimated}


@dataclass
class RouteBridge:
    sfn: str
    name: str
    lat: float
    lon: float
    station_m: float
    offset_m: float
    relation: str             # over | under | unknown
    road: str                 # what the router calls the road here
    matched_by: str = ""      # lrs | route | name | assumed | none
    road_lrs: str = ""        # NLF_ID of the road the route rides here (conflation)
    checks: list[Check] = field(default_factory=list)
    posting: Optional[dict] = None
    notes: list[str] = field(default_factory=list)
    max_span_ft: Optional[float] = None
    year_built: Optional[int] = None
    routes_carried: str = ""
    feature_under: str = ""

    @property
    def min_ratio(self) -> Optional[float]:
        vals = [c.ratio for c in self.checks if c.ratio is not None]
        return min(vals) if vals else None

    def as_dict(self) -> dict:
        r = self.min_ratio
        return {"sfn": self.sfn, "name": self.name, "lat": self.lat, "lon": self.lon,
                "station_mi": round(self.station_m / 1609.344, 2),
                "offset_ft": round(self.offset_m * 3.28084, 1),
                "relation": self.relation, "road": self.road, "matched_by": self.matched_by,
                "road_lrs": self.road_lrs,
                "min_ratio": None if r is None else round(r, 3),
                "status": status_for(r),
                "checks": [c.as_dict() for c in self.checks],
                "posting": self.posting, "notes": self.notes,
                "max_span_ft": self.max_span_ft, "year_built": self.year_built,
                "routes_carried": self.routes_carried, "feature_under": self.feature_under}


def status_for(ratio: Optional[float]) -> str:
    if ratio is None:
        return "unknown"
    return "fail" if ratio < 1.0 else "marginal" if ratio < 1.1 else "pass"


def posting_label(code: str) -> tuple[str, bool]:
    """SNBI B.PS.01 as ODOT codes it (first letter P/T/S, second the state:
    O open, P posted, R restricted, A advisory; C closed; N n/a) — or the
    NBI item 70 digit TIMS publishes (5 = at or above legal loads). Returns
    (label, worth flagging)."""
    c = (code or "").split("-")[0].strip().upper()
    if c in ("", "N"):
        return "not applicable", False
    if c == "C":
        return "closed", True
    if c.isdigit():
        n = int(c)
        return ("open (at or above legal loads)", False) if n >= 5 else \
               (f"posted (NBI 70 code {n}: below legal loads)", True)
    state = {"O": "open (not posted)", "P": "posted", "R": "restricted", "A": "advisory posting"}
    if len(c) == 2 and c[1] in state:
        return state[c[1]], c[1] != "O"
    return f"status {c}", True


def rating_factor(vehicle: str, known: dict[str, tuple[float, str]],
                  design_load: str | None, design_rf: float | None,
                  max_span_ft: float | None, continuous: bool) -> Check:
    """The vehicle's RF for one bridge from ``known`` = {vehicle: (rf, source)},
    else the design-load RF when the vehicle is the design load, else an
    estimate scaled from what IS rated."""
    if vehicle in known:
        rf, src = known[vehicle]
        return Check("load", rf, rf, 1.0, "RF", src)
    alias = DESIGN_LOAD_ALIASES.get((design_load or "").strip().upper())
    if alias and alias == DESIGN_LOAD_ALIASES.get(vehicle.upper()) and design_rf:
        return Check("load", design_rf, design_rf, 1.0, "RF",
                     f"operating RF of the design load (B.LR.06) — B.LR.01 {design_load}")
    if alias and design_rf and alias not in known:
        known = {**known, alias: (float(design_rf), f"design-load operating RF ({design_load})")}
    if not known or not max_span_ft or not (20.0 <= max_span_ft <= 200.0):
        why = ("no rated vehicle to scale from" if not known
               else "span outside the 20–200 ft estimation range" if max_span_ft
               else "maximum span length unknown")
        return Check("load", None, None, 1.0, "RF", "none", f"not rated for {vehicle}; {why}")
    try:
        from civilpy.structural.rating_ratios import simple_span_demands
        basis = simple_span_demands(float(max_span_ft), tuple(sorted(set(known) | {vehicle})))
        m_target = float(basis.effects("positive_moment", [vehicle])[0])
        ests = []
        for k, (rf, _src) in known.items():
            m_k = float(basis.effects("positive_moment", [k])[0])
            if m_k > 0 and m_target > 0:
                ests.append(rf * m_k / m_target)
        if not ests:
            raise ValueError("no usable demand")
        # conservative: the lowest RF any rated vehicle implies (they agree when
        # M+ governs; the median says how far the knowns are from that)
        est = min(ests)
        med = statistics.median(ests)
        note = (f"estimated from {len(ests)} rated vehicle(s) by simple-span M+ ratio at "
                f"{max_span_ft:g} ft (lowest implied; median {med:.2f})")
        if continuous:
            note += "; continuous structure — simple-span ratio is approximate"
        return Check("load", est, round(est, 2), 1.0, "RF", "estimate", note, estimated=True)
    except Exception as exc:  # never fatal
        logger.warning("RF estimate failed: %s", exc)
        return Check("load", None, None, 1.0, "RF", "none",
                     f"not rated for {vehicle}; estimate unavailable ({exc})")


def vertical_check(clearance, height_ft: float, source: str) -> Optional[Check]:
    if clearance is None:
        return Check("vertical", None, None, height_ft, "ft", source, "clearance not recorded")
    c = float(clearance)
    if c <= 0:
        return Check("vertical", None, None, height_ft, "ft", source, "clearance not recorded")
    if c >= UNRESTRICTED_FT:
        return None                     # 99.9 — no overhead restriction
    margin_in = (c - height_ft) * 12.0
    return Check("vertical", c / height_ft if height_ft > 0 else None, round(c, 2), height_ft,
                 "ft", source, f"margin {margin_in:+.0f} in")


def _is_sentinel(v: float) -> bool:
    """SNBI / NBI "not applicable" fillers: 99.9, 99.99, 999."""
    return abs(v - 99.9) < 0.05 or abs(v - 99.99) < 0.005 or v >= 999


def width_check(width, width_ft: float, source: str) -> Check:
    if width is None or float(width) <= 0 or _is_sentinel(float(width)):
        return Check("width", None, None, width_ft, "ft", source, "width not recorded")
    w = float(width)
    return Check("width", w / width_ft if width_ft > 0 else None, round(w, 2), width_ft,
                 "ft", source, f"margin {(w - width_ft):+.1f} ft")


_PREFIX = {"1": "IR", "2": "US", "3": "SR", "4": "CR", "5": "TR"}


def _step_at(steps, station_m) -> Optional[dict]:
    for s in steps:
        if s["d0"] <= station_m < s["d1"] or (s is steps[-1] and station_m >= s["d0"]):
            return s
    return None


_NAME_ROUTE_RE = re.compile(r"^[A-Z]{3}-(\d{5})-")   # ODOT bridge name CCC-RRRRR-LLLL


def assess(b: BridgeRecord, station_m: float, offset_m: float, step: dict, vehicle: str,
           height_ft: float, width_ft: float, road: Optional[dict] = None,
           extra_tokens: Optional[set] = None) -> RouteBridge:
    """Score one bridge. ``road`` is the road-inventory segment the route is
    riding here (from :func:`road_under_route`), when known; ``extra_tokens``
    are route tokens of the neighbouring router steps (a ramp merging onto
    the mainline lands on the mainline's bridge before the step changes)."""
    rb = RouteBridge(sfn=b.sfn, name=b.name, lat=b.lat, lon=b.lon, station_m=station_m,
                     offset_m=offset_m, relation="unknown",
                     road=step.get("ref") or step.get("name") or (road or {}).get("street") or "(unnamed road)",
                     max_span_ft=b.max_span_ft, year_built=b.year_built,
                     road_lrs=(road or {}).get("nlf_id", ""))
    road_toks = route_tokens(step.get("ref", ""), step.get("name", "")) | set(extra_tokens or ())
    if road:
        # the inventory's street text names ramps by their ends ("RAMP FROM RA
        # 25609 TO IR 71"): a merge lands on the mainline's bridge
        road_toks |= route_tokens(road.get("street", ""), "")
    if road and road.get("route_type") in _NLF_TYPES and str(road.get("route_nbr", "")).strip("0"):
        road_toks.add(f"{_NLF_TYPES[road['route_type']]}:{int(road['route_nbr'])}")
    road_name = step.get("name", "")
    road_base = nlf_base((road or {}).get("nlf_id", ""))

    carried = [f for f in b.features if f.is_highway and f.carried]
    under_hwy = [f for f in b.features if f.is_highway and f.under]
    labels = {f"{_PREFIX.get(str(t).strip(), 'RT')} {int(str(n).strip().lstrip('0') or 0)}"
              for f in carried for t, n in f.routes if str(n or '').strip().lstrip('0').isdigit()}
    labels |= {t for t in (_nlf_display(f.lrs_id) for f in carried) if t}
    rb.routes_carried = "; ".join(sorted(labels))
    rb.feature_under = "; ".join(f.name or f.kind for f in b.features if f.under and (f.name or f.kind))

    def match(f: FeatureRecord) -> str:
        if road_base and nlf_base(f.lrs_id) == road_base:
            return "lrs"
        toks = bridge_route_tokens(f.routes)
        t = nlf_token(f.lrs_id)
        if t:
            toks.add(t)
        if toks & road_toks:
            return "route"
        if names_match(f.name, road_name) or names_match(f.name, step.get("ref", "")) \
                or (road and names_match(f.name, road.get("street", ""))):
            return "name"
        return ""

    on_feat = under_feat = None
    for f in carried:
        how = match(f)
        if how:
            on_feat, rb.relation, rb.matched_by = f, "over", how
            break
    if on_feat is None:
        for f in under_hwy:
            how = match(f)
            if how:
                under_feat, rb.relation, rb.matched_by = f, "under", how
                break
    if on_feat is None and under_feat is None and not carried:
        # the mirror has no carried-roadway row: ODOT names bridges
        # CCC-RRRRR-LLLL, and RRRRR is the inventory route's number
        m = _NAME_ROUTE_RE.match((b.name or "").upper())
        road_nums = {int(t.split(":")[1]) for t in road_toks} | \
            ({parse_nlf(road["nlf_id"])["number"]} if road and parse_nlf(road.get("nlf_id", "")) else set())
        if m and int(m.group(1)) in road_nums:
            rb.relation, rb.matched_by = "over", "name"
            rb.notes.append("no carried-roadway feature on record; route number taken from the "
                            "bridge name")
    if on_feat is None and under_feat is None and rb.relation == "unknown":
        hwy_lrs = [f for f in carried + under_hwy if nlf_base(f.lrs_id)]
        if road_base and road.get("route_type") != "RA" and hwy_lrs \
                and len(hwy_lrs) == len(carried + under_hwy) \
                and all(nlf_base(f.lrs_id) != road_base for f in hwy_lrs):
            # every roadway on and under this bridge has an LRS id, and the
            # road the route rides is none of them: a neighbour, not a crossing
            rb.relation, rb.matched_by = "adjacent", "lrs"
            rb.notes.append(f"the route rides {road.get('street') or road['nlf_id']} "
                            f"({road['nlf_id']}), which this bridge neither carries nor crosses")
            return rb
        if not under_hwy:
            rb.relation, rb.matched_by = "over", "assumed"
            on_feat = carried[0] if carried else None
            rb.notes.append("carried roadway not matched to the route by LRS, route number or "
                            "name; assumed the route rides the bridge (no highway underneath)")
        else:
            rb.matched_by = "none"
            under_feat = min(under_hwy, key=lambda f: f.min_vert_clearance_ft or 999)
            on_feat = carried[0] if carried else None
            rb.notes.append("could not tell whether the route is on or under this bridge — "
                            "both checked; verify in the field")

    # ── load (only if the vehicle rides the bridge) ──
    if rb.relation in ("over", "unknown"):
        rb.checks.append(rating_factor(vehicle, dict(b.known_rfs), b.design_load,
                                       b.design_opr_rf, b.max_span_ft, b.continuous))
        if on_feat is not None:
            v = vertical_check(on_feat.min_vert_clearance_ft, height_ft,
                               "min vertical clearance over the bridge roadway (B.H.13)")
            if v is not None and v.ratio is not None:
                rb.checks.append(v)
            w = on_feat.usable_width_ft or b.curb_width_ft
            src = ("max usable surface width (B.H.16)" if on_feat.usable_width_ft
                   else "curb-to-curb width (B.G.06)")
            rb.checks.append(width_check(w, width_ft, src))
        else:
            rb.checks.append(width_check(b.curb_width_ft, width_ft, "curb-to-curb width (B.G.06)"))
        if b.posting_code:
            label, flag = posting_label(b.posting_code)
            rb.posting = {"code": b.posting_code, "since": b.posting_since, "label": label,
                          "flag": flag}

    # ── under: the bridge is overhead ──
    if rb.relation in ("under", "unknown") and under_feat is not None:
        v = vertical_check(under_feat.min_vert_clearance_ft, height_ft,
                           f"min vertical underclearance (B.H.13, {under_feat.name or 'road under'})")
        if v is not None:
            rb.checks.append(v)
        rb.checks.append(width_check(under_feat.usable_width_ft, width_ft,
                                     "max usable surface width of the road under (B.H.16)"))
    return rb


def _nlf_display(nlf: str) -> str:
    p = parse_nlf(nlf)
    return f"{p['type']} {p['number']}" if p else ""


# ── the screen ──────────────────────────────────────────────────────────────
def screen_route(start: tuple[float, float], end: tuple[float, float], vehicle: str,
                 height_ft: float = LEGAL_HEIGHT_FT, width_ft: float = LEGAL_WIDTH_FT, *,
                 source: BridgeSource, buffer_m: float = BUFFER_M, conflate: bool = True,
                 router: Callable[[tuple, tuple], dict] = None, workers: int = 8) -> dict:
    """Route ``start``→``end`` (``(lat, lon)``) and score every bridge within
    ``buffer_m`` of the road for ``vehicle`` at ``height_ft`` × ``width_ft``.
    ``conflate`` asks the public road inventory which road the route rides
    at each bridge (LRS match); off, matching falls back to route numbers
    and names only."""
    from civilpy.structural.aashto.vehicles import RATING_VEHICLES
    if vehicle not in VEHICLES or vehicle not in RATING_VEHICLES:
        raise ValueError(f"unknown vehicle {vehicle!r}; one of {VEHICLES}")
    if PRINT_DISCLAIMER:
        print(DISCLAIMER, file=sys.stderr, flush=True)
    route = (router or osrm_route)(start, end)
    coords = route["coords"]
    frame = LocalFrame(sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords))
    line = Polyline([frame.xy(c[0], c[1]) for c in coords])
    pad = buffer_m / 111_000 * 1.5
    bbox = (min(c[0] for c in coords) - pad, min(c[1] for c in coords) - pad,
            max(c[0] for c in coords) + pad, max(c[1] for c in coords) + pad)
    hits = []
    hydrate = getattr(source, "hydrate", None)
    for b in source.bridges_in(bbox):
        d, s, _h = line.nearest(*frame.xy(b.lat, b.lon))
        if d <= buffer_m:
            hits.append((hydrate(b) if hydrate else b, s, d))

    roads: dict[str, Optional[dict]] = {}
    if conflate and hits:
        def look(item):
            b, s, _d = item
            try:
                return b.sfn, road_under_route(b.lat, b.lon, frame, line, s)
            except Exception as exc:  # pragma: no cover - network
                logger.warning("conflation failed for %s: %s", b.sfn, exc)
                return b.sfn, None
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            roads = dict(pool.map(look, hits))

    results = []
    steps = route["steps"]
    for b, s, d in hits:
        step = _step_at(steps, s) or {}
        extra = set()
        for other in steps:                       # steps that start or end within 150 m
            if other is not step and (abs(other["d0"] - s) <= 150 or abs(other["d1"] - s) <= 150):
                extra |= route_tokens(other.get("ref", ""), other.get("name", ""))
        results.append(assess(b, s, d, step, vehicle, height_ft, width_ft, roads.get(b.sfn), extra))
    results.sort(key=lambda r: r.station_m)
    counts = {"pass": 0, "marginal": 0, "fail": 0, "unknown": 0}
    for r in results:
        if r.relation != "adjacent":
            counts[status_for(r.min_ratio)] += 1
    v = RATING_VEHICLES[vehicle]
    worst = min((r for r in results if r.min_ratio is not None),
                key=lambda r: r.min_ratio, default=None)
    return {
        "vehicle": {"name": vehicle, "gvw_tons": round(v.gvw_tons, 2),
                    "axles": len(v.axle_loads_kip), "reference": v.reference,
                    "height_ft": height_ft, "width_ft": width_ft},
        "route": {"coords": coords, "distance_mi": round(route["distance_m"] / 1609.344, 1),
                  "duration_min": round(route["duration_s"] / 60),
                  "source": route.get("source", ""), "start": list(start), "end": list(end),
                  "note": "passenger-car route; permit routing restrictions are not applied"},
        "matching": {"lrs_conflation": bool(conflate),
                     "by": {k: sum(1 for r in results if r.matched_by == k)
                            for k in ("lrs", "route", "name", "assumed", "none")},
                     "adjacent": sum(1 for r in results if r.relation == "adjacent")},
        "counts": counts, "bridge_count": len(results),
        "worst": worst.as_dict() if worst else None,
        "bridges": [r.as_dict() for r in results],
        "disclaimer": DISCLAIMER,
        "permit_links": {"odot_special_hauling_permits": ODOT_PERMITS_URL, "ohps": OHPS_URL},
    }


# ── public TIMS source ──────────────────────────────────────────────────────
# NBI item 31 design load codes as TIMS publishes them
_TIMS_DESIGN_LOAD = {"1": "H10", "2": "H15", "3": "HS15", "4": "H20", "5": "HS20",
                     "6": "HS20M", "7": "PEDESTRIAN", "8": "RAILROAD", "9": "HL93"}
_TIMS_FIELDS = ("SFN,STR_LOC_CARRIED,INVENT_FEAT,NLFID,INVENT_ON_UND_CD,LATITUDE_DD,LONGITUDE_DD,"
                "DESIGN_LOAD_CD,RAT_OPR_LOAD_FACT,BRG_POSTING,MAX_SPAN_LEN,BRG_RDW_WD,"
                "MIN_HORIZ_CLR_C,MINVRT_UNDCLR_C,ROUTE_TYPE,ROUTE_NBR,YR_BUILT,MAIN_STR_TYPE_CD,"
                "TYPE_SERV1_CD,TYPE_SERV2_CD,GEN_OPR_STATUS")


class TIMSBridgeSource:
    """Bridges from the public ODOT TIMS Bridge Inventory layer. It carries
    one LRS id (the inventory route, on or under the bridge), the design-
    load operating RF (no per-vehicle legal RFs — those are estimated), the
    minimum vertical underclearance and the curb-to-curb width."""

    def __init__(self, url: str = TIMS_BRIDGES_URL, timeout: int = HTTP_TIMEOUT):
        self.url, self.timeout = url, timeout

    def _query(self, **params) -> list[dict]:
        base = {"outFields": _TIMS_FIELDS, "f": "json", "returnGeometry": "false",
                "resultRecordCount": 5000}
        base.update(params)
        r = requests.post(self.url, data=base, timeout=self.timeout)
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"TIMS: {data['error']}")
        return [f["attributes"] for f in data.get("features", [])]

    def bridges_in(self, bbox):
        import json as _json
        min_lat, min_lon, max_lat, max_lon = bbox
        env = {"xmin": min_lon, "ymin": min_lat, "xmax": max_lon, "ymax": max_lat,
               "spatialReference": {"wkid": 4326}}
        rows = self._query(geometry=_json.dumps(env), geometryType="esriGeometryEnvelope",
                           inSR=4326, spatialRel="esriSpatialRelIntersects",
                           where="LATITUDE_DD IS NOT NULL")
        return [r for r in (self.to_record(a) for a in rows) if r is not None]

    def by_sfn(self, sfn: str):
        rows = self._query(where=f"SFN = '{str(sfn).strip()}'")
        return self.to_record(rows[0]) if rows else None

    @staticmethod
    def to_record(a: dict) -> Optional[BridgeRecord]:
        lat, lon = a.get("LATITUDE_DD"), a.get("LONGITUDE_DD")
        if lat is None or lon is None:
            return None

        def num(v, scale=1.0):
            try:
                x = float(v)
            except (TypeError, ValueError):
                return None
            return None if x in (0.0, 9999.0, 99.99) else x * scale

        on_under = str(a.get("INVENT_ON_UND_CD") or "").strip()
        nlf = (a.get("NLFID") or "").strip()
        rtype, rnbr = (a.get("ROUTE_TYPE") or "").strip(), (a.get("ROUTE_NBR") or "").strip()
        routes = [(_NLF_TYPES[rtype], rnbr)] if rtype in _NLF_TYPES and rnbr.strip("0") else []
        carried = FeatureRecord("H", "C", name=(a.get("STR_LOC_CARRIED") or "").strip(),
                                lrs_id=nlf if on_under == "1" else "",
                                usable_width_ft=num(a.get("BRG_RDW_WD")),
                                routes=routes if on_under == "1" else [])
        under_kind = "H" if str(a.get("TYPE_SERV2_CD") or "") in ("1", "2", "4", "6", "7", "8") \
            else {"5": "W", "3": "R", "9": "R"}.get(str(a.get("TYPE_SERV2_CD") or ""), "X")
        under = FeatureRecord(under_kind, "B", name=(a.get("INVENT_FEAT") or "").strip(),
                              lrs_id=nlf if on_under == "2" else "",
                              min_vert_clearance_ft=num(a.get("MINVRT_UNDCLR_C")),
                              usable_width_ft=num(a.get("MIN_HORIZ_CLR_C")) if on_under == "2" else None,
                              routes=routes if on_under == "2" else [])
        yr = a.get("YR_BUILT")
        year = None
        if isinstance(yr, (int, float)) and yr:
            # epoch milliseconds; arithmetic rather than gmtime because Windows'
            # gmtime rejects dates before 1970 (most of the inventory)
            year = (_EPOCH + datetime.timedelta(milliseconds=yr)).year
        return BridgeRecord(
            sfn=str(a.get("SFN") or "").strip(), lat=float(lat), lon=float(lon),
            name=(a.get("STR_LOC_CARRIED") or "").strip(),
            max_span_ft=num(a.get("MAX_SPAN_LEN")), curb_width_ft=num(a.get("BRG_RDW_WD")),
            design_load=_TIMS_DESIGN_LOAD.get(str(a.get("DESIGN_LOAD_CD") or "").strip(), ""),
            design_opr_rf=num(a.get("RAT_OPR_LOAD_FACT"), 0.001),
            continuous=False, features=[carried, under],
            posting_code=str(a.get("BRG_POSTING") or "").strip(), year_built=year)
