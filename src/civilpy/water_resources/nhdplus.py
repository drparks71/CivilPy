#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NHDPlus HR flowlines near a point, as an independent check on a
StreamStats basin.

StreamStats snaps a pour point to its own stream grid, and at a confluence a
bridge can land on the side stream: SR 555 over the West Branch Little
Hocking (SFN 8404615) delineated Burnett Run, 2.0 mi^2 against the 18.9 mi^2
the branch drains.  NHDPlus HR carries each flowline's GNIS name, upstream
drainage area at its downstream end and its own incremental catchment
(``AreaSqKm``), so a bridge's waterway name picks the flowline it crosses and
the two areas bracket the drainage at the bridge.  The drainage used is
``DivDASqKm`` (flow split at divergences), not ``TotDASqKm``: in flat
north-west Ohio the ditch network makes TotDA count every basin a divergence
touches (Ottawa River at Toledo: TotDA 764 mi^2, DivDA 143 mi^2, StreamStats
155 mi^2).

Only a name match is trusted.  Snapping to the nearest NHD flowline regardless
of name moves a culvert onto the nearest mapped river (see
:mod:`civilpy.water_resources.streamstats`), and SNBI names an unnamed
tributary as "TRIB OF X" / "T X CR" / "BRANCH OF X" - those never match X.

    fls = flowlines_near(39.341011, -81.762461)
    fl = matching_flowline(fls, "WEST BRANCH OF THE LITTLE HOCKING RIVER")
    area_agrees(2.0, fl)           # False -> re-delineate at fl.nearest
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

#: National Map NHDPlus HR, NetworkNHDFlowline layer.
HR_FLOWLINES = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3/query"
SQ_KM_PER_SQ_MI = 2.589988110336
EARTH_RADIUS_M = 6_371_008.8

#: A StreamStats area within this factor of the NHDPlus bracket agrees.
DEFAULT_TOLERANCE = 2.0

# words that name the kind of stream, not which one
GENERIC = {"river", "creek", "run", "brook", "ditch", "stream", "drain", "the", "of", "at", "and", "near"}
# words that make it a different stream when one name has them and the other does not
QUALIFIERS = {"west", "east", "north", "south", "middle", "branch", "fork", "little", "big", "upper", "lower"}
ABBREVIATIONS = {
    "r": "river", "riv": "river", "cr": "creek", "ck": "creek", "crk": "creek", "rn": "run",
    "br": "branch", "bra": "branch", "brn": "branch", "fk": "fork", "frk": "fork",
    "w": "west", "e": "east", "n": "north", "s": "south", "m": "middle", "mid": "middle",
    "lit": "little", "ltl": "little", "lt": "little", "trib": "tributary", "tribs": "tributary",
    "dit": "ditch", "dt": "ditch", "st": "saint", "mt": "mount",
}


class NHDPlusError(RuntimeError):
    pass


@dataclass
class Flowline:
    """One NHDPlus HR flowline near the point asked about."""
    nhdplus_id: int | None
    name: str                         # GNIS name, '' when unnamed
    stream_order: int | None
    total_da_sq_mi: float | None      # DivDASqKm (else TotDASqKm): drainage at its downstream end
    local_da_sq_mi: float | None      # AreaSqKm: its own catchment
    distance_m: float                 # point to the flowline
    nearest: tuple                    # (lat, lon) on the flowline closest to the point

    @property
    def da_range_sq_mi(self) -> tuple | None:
        """(low, high) drainage area somewhere along this flowline: its
        upstream end has the total less its own catchment."""
        if self.total_da_sq_mi is None:
            return None
        low = self.total_da_sq_mi - (self.local_da_sq_mi or 0.0)
        return max(low, 0.0), self.total_da_sq_mi

    def as_dict(self):
        return {"nhdplus_id": self.nhdplus_id, "name": self.name, "stream_order": self.stream_order,
                "total_da_sq_mi": self.total_da_sq_mi, "local_da_sq_mi": self.local_da_sq_mi,
                "distance_m": round(self.distance_m, 1), "nearest": list(self.nearest)}


# ── names (pure) ──────────────────────────────────────────────────────────

def name_tokens(name: str) -> list:
    """Lower-case words with abbreviations expanded; road notes in
    parentheses and after '-' / '@' dropped ("MILLERS RN-BACK RN(STREA")."""
    s = re.split(r"[(\-@#]", str(name or ""), maxsplit=1)[0].lower().replace("&", " and ")
    words = re.findall(r"[a-z0-9']+", s.replace(".", " "))
    return [ABBREVIATIONS.get(w.replace("'", ""), w.replace("'", "")) for w in words]


def is_tributary_name(name: str) -> bool:
    """SNBI's names for an unnamed tributary or branch of a named stream:
    "TRIB OF SUNDAY CK", "T WALNUT CR", "BRANCH OF TODDS FORK", "TRIBUTARY TO ..."."""
    toks = name_tokens(name)
    if not toks:
        return False
    if "tributary" in toks or (toks[0] == "t" and len(toks) > 1):
        return True
    return toks[0] == "branch" and len(toks) > 1 and toks[1] in ("of", "to")


def _core(tokens) -> set:
    return {t for t in tokens if t not in GENERIC}


def names_match(waterway: str, gnis_name: str) -> bool:
    """True when an SNBI waterway name names this GNIS stream: every word
    of the GNIS name that says which stream it is appears in the SNBI name,
    and the SNBI name adds no qualifier (West / Branch / Little ...) the GNIS
    name lacks.  A tributary-style SNBI name never matches."""
    if not waterway or not gnis_name or is_tributary_name(waterway):
        return False
    snbi, gnis = _core(name_tokens(waterway)), _core(name_tokens(gnis_name))
    if not gnis or not gnis <= snbi:
        return False
    return not ((snbi - gnis) & QUALIFIERS)


def matching_flowline(flowlines, waterway: str) -> Flowline | None:
    """The nearest flowline whose GNIS name the waterway name matches."""
    hits = [f for f in flowlines or [] if names_match(waterway, f.name)]
    return min(hits, key=lambda f: f.distance_m) if hits else None


def area_agrees(area_sq_mi: float | None, flowline: Flowline | None,
                tolerance: float = DEFAULT_TOLERANCE) -> bool | None:
    """Does a basin area fit the flowline's drainage bracket within a factor
    of ``tolerance``?  None when there is nothing to compare."""
    rng = flowline.da_range_sq_mi if flowline else None
    if area_sq_mi is None or rng is None or rng[1] <= 0:
        return None
    low, high = rng
    return low / tolerance <= area_sq_mi <= high * tolerance


def disagreement(area_sq_mi: float | None, flowline: Flowline | None) -> float | None:
    """How far outside the bracket an area is, as a factor (1.0 = inside)."""
    rng = flowline.da_range_sq_mi if flowline else None
    if not area_sq_mi or rng is None or rng[1] <= 0:
        return None
    low, high = rng
    if area_sq_mi > high:
        return area_sq_mi / high
    if low > 0 and area_sq_mi < low:
        return low / area_sq_mi
    return 1.0


# ── geometry (pure) ───────────────────────────────────────────────────────

def _local_xy(lat0, lon0):
    """Equirectangular metres about (lat0, lon0) - exact enough within a few km."""
    kx = math.radians(1.0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    ky = math.radians(1.0) * EARTH_RADIUS_M
    to_xy = lambda lat, lon: ((lon - lon0) * kx, (lat - lat0) * ky)          # noqa: E731
    to_ll = lambda x, y: (lat0 + y / ky, lon0 + x / kx)                       # noqa: E731
    return to_xy, to_ll


def nearest_on_paths(lat: float, lon: float, paths) -> tuple:
    """(distance m, (lat, lon)) of the closest point on polylines given as
    lists of [lon, lat, ...] vertices."""
    to_xy, to_ll = _local_xy(lat, lon)
    best = (math.inf, None)
    for path in paths or []:
        pts = [to_xy(v[1], v[0]) for v in path]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] or pts):
            dx, dy = x2 - x1, y2 - y1
            seg = dx * dx + dy * dy
            t = 0.0 if seg == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg))
            px, py = x1 + t * dx, y1 + t * dy
            d = math.hypot(px, py)
            if d < best[0]:
                best = (d, to_ll(px, py))
    return best


def parse_flowlines(resp: dict, lat: float, lon: float) -> list:
    """Flowlines from an ArcGIS query response (outSR 4326), nearest first."""
    if not isinstance(resp, dict) or "error" in resp:
        raise NHDPlusError(f"NHDPlus HR query failed: {(resp or {}).get('error')}")
    out = []
    for f in resp.get("features", []):
        a = {k.lower(): v for k, v in (f.get("attributes") or {}).items()}
        dist, near = nearest_on_paths(lat, lon, (f.get("geometry") or {}).get("paths"))
        if near is None:
            continue
        tot = a.get("divdasqkm") if a.get("divdasqkm") not in (None, 0) else a.get("totdasqkm")
        loc = a.get("areasqkm")
        out.append(Flowline(
            nhdplus_id=int(a["nhdplusid"]) if a.get("nhdplusid") is not None else None,
            name=(a.get("gnis_name") or "").strip(),
            stream_order=a.get("streamorde"),
            total_da_sq_mi=tot / SQ_KM_PER_SQ_MI if tot is not None and tot > 0 else None,
            local_da_sq_mi=loc / SQ_KM_PER_SQ_MI if loc is not None and loc >= 0 else None,
            distance_m=dist, nearest=near))
    return sorted(out, key=lambda f: f.distance_m)


# ── service ───────────────────────────────────────────────────────────────

def flowlines_near(lat: float, lon: float, *, radius_m: float = 150.0, session=None,
                   timeout: float = 60) -> list:
    """NHDPlus HR network flowlines within ``radius_m`` of a point (WGS84)."""
    import requests

    s = session or requests
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326, "outSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "distance": radius_m, "units": "esriSRUnit_Meter",
              "outFields": "nhdplusid,gnis_name,streamorde,totdasqkm,divdasqkm,areasqkm", "returnGeometry": "true",
              "f": "json"}
    last = None
    for _ in range(3):
        try:
            r = s.request("GET", HR_FLOWLINES, params=params, timeout=timeout)
            r.raise_for_status()
            return parse_flowlines(r.json(), lat, lon)
        except NHDPlusError:
            raise
        except Exception as exc:                                   # noqa: BLE001
            last = exc
    raise NHDPlusError(f"NHDPlus HR: {last}")
