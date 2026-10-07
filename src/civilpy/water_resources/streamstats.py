#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""USGS StreamStats: delineate a basin, compute its characteristics, and the
regional regression peak flows - the five-call workflow USGS documents
(*StreamStats Flow Statistics Workflow*, ss-delineate v1.2 / ss-hydro / NSS):

1. ``ss-delineate`` - basin polygon at the pour point;
2. NSS ``regressionregions/bylocation`` - regression regions under it;
3. NSS ``scenarios`` - the peak-flow equations (statistic group 2) and the
   basin characteristics they need;
4. ``ss-hydro`` - those characteristics for this basin;
5. NSS ``scenarios/estimate`` - the flows (in Ohio: Koltun 2019,
   SIR 2019-5018, PK50AEP .. PK0_2AEP = Q2 .. Q500).

USGS asks for no more than four simultaneous requests.

The pour point is used as given.  StreamStats snaps it to its own stream
grid; pre-snapping a bridge to NHDPlus flowlines is NOT done because NHD
omits most small channels and moves a culvert onto the nearest mapped river
(a 10 ft span jumping from 0.2 to 1,000 mi^2 in testing).  Use
:func:`plausibility` to catch a point that landed on the wrong stream.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from statistics import NormalDist

BASE = "https://streamstats.usgs.gov"
DELINEATE = BASE + "/ss-delineate/v1/delineate/sshydro/{region}"
BASIN_CHARS = BASE + "/ss-hydro/v1/basin-characteristics/calculate"
NSS_REGIONS = BASE + "/nssservices/regressionregions/bylocation"
NSS_SCENARIOS = BASE + "/nssservices/scenarios"
NSS_ESTIMATE = BASE + "/nssservices/scenarios/estimate"
PEAK_FLOW_GROUP = 2

M2_PER_SQ_MI = 2_589_988.110336
#: Smaller than this (about 3 acres) is the one-cell polygon of a failed snap.
MIN_BASIN_SQ_MI = 0.005


class StreamStatsError(RuntimeError):
    pass


@dataclass
class Basin:
    """One delineated basin with its peak-flow regression results."""
    lat: float                        # pour point as requested
    lon: float
    outlet: tuple | None = None       # (lat, lon) the service reports for the pour point
    geometry: dict | None = None      # GeoJSON Polygon / MultiPolygon, lon/lat
    polygon_area_sq_mi: float | None = None
    drainage_area_sq_mi: float | None = None    # DRNAREA (the regression input)
    characteristics: dict = field(default_factory=dict)    # code -> {"value", "unit", "name"}
    peak_flows: dict = field(default_factory=dict)          # AEP percent (float) -> cfs
    regression: list = field(default_factory=list)          # [{"code","name","percent"}]
    warnings: list = field(default_factory=list)
    huc: str = ""
    timings_s: dict = field(default_factory=dict)

    @property
    def delineated(self) -> bool:
        """A real basin came back (not the one-cell polygon StreamStats
        returns for a point it could not snap to its stream grid)."""
        return (self.geometry is not None and (self.polygon_area_sq_mi or 0) > MIN_BASIN_SQ_MI
                and not any("not snappable" in w.lower() for w in self.warnings))

    def q(self, aep_pct: float) -> float | None:
        """Peak flow (cfs) at an annual exceedance probability, interpolated."""
        return flow_at_aep(self.peak_flows, aep_pct)

    def as_dict(self):
        return {"lat": self.lat, "lon": self.lon, "outlet": self.outlet,
                "polygon_area_sq_mi": self.polygon_area_sq_mi,
                "drainage_area_sq_mi": self.drainage_area_sq_mi, "characteristics": self.characteristics,
                "peak_flows": {str(k): v for k, v in self.peak_flows.items()},
                "regression": self.regression, "warnings": self.warnings, "huc": self.huc}


# ── parsing (pure) ────────────────────────────────────────────────────────

def aep_of_code(code: str) -> float | None:
    """NSS peak-flow statistic code -> AEP percent: PK50AEP -> 50, PK0_2AEP -> 0.2."""
    m = re.fullmatch(r"PK(\d+)(?:_(\d+))?AEP", code or "")
    if not m:
        return None
    return float(f"{m.group(1)}.{m.group(2)}" if m.group(2) else m.group(1))


def parse_delineation(resp: dict) -> dict:
    """Pour point, basin polygon (GlobalWshd), its area and warnings from an
    ss-delineate response.  ``Shape_Area`` is square metres."""
    out = {"outlet": None, "geometry": None, "polygon_area_sq_mi": None, "warnings": [], "huc": ""}
    try:
        collections = resp["bcrequest"]["wsresp"]["featurecollection"][0]
    except (KeyError, IndexError, TypeError):
        raise StreamStatsError("delineation response has no feature collection") from None
    for item in collections:
        for f in item.get("feature", {}).get("features", []):
            p = f.get("properties") or {}
            w = (p.get("WarningMsg") or "").strip(" ,")
            if w and w not in out["warnings"]:
                out["warnings"].append(w)
            if item.get("name") == "globalwatershedpoint":
                lon, lat = f["geometry"]["coordinates"][:2]
                out["outlet"] = (lat, lon)
                out["huc"] = str(p.get("HUCID") or "")
            elif item.get("name") == "globalwatershed" and p.get("GlobalWshd") == 1:
                out["geometry"] = f["geometry"]
                if p.get("Shape_Area") is not None:
                    out["polygon_area_sq_mi"] = float(p["Shape_Area"]) / M2_PER_SQ_MI
    return out


def peak_flow_scenario(scenarios: list) -> dict:
    """The peak-flow scenario from an NSS scenarios response (statistic group 2)."""
    for s in scenarios or []:
        if s.get("statisticGroupID") in (PEAK_FLOW_GROUP, None) and s.get("regressionRegions"):
            return s
    raise StreamStatsError("no peak-flow scenario for this basin's regression regions")


def fill_scenario(scenario: dict, characteristics: list) -> dict:
    """Write computed basin characteristics into every regression region's
    parameters (case-insensitive code match); returns the scenario."""
    vals = {c["code"].lower(): c.get("value") for c in characteristics}
    for reg in scenario.get("regressionRegions", []):
        for p in reg.get("parameters", []):
            if p["code"].lower() in vals:
                p["value"] = vals[p["code"].lower()]
    return scenario


def parse_estimate(estimate: list) -> tuple[dict, list]:
    """Peak flows {AEP %: cfs} and the regression regions used.  When the
    basin spans several regions NSS adds an area-weighted region; it wins."""
    regions = (estimate or [{}])[0].get("regressionRegions", [])
    used = [{"code": r.get("code"), "name": r.get("name"), "percent": r.get("percentWeight")} for r in regions]
    pick = next((r for r in regions if "weight" in (r.get("name") or "").lower()
                 or "averaged" in (r.get("name") or "").lower()), None)
    pick = pick or next((r for r in regions if r.get("results")), None)
    flows = {}
    for res in (pick or {}).get("results", []):
        aep = aep_of_code(res.get("code", ""))
        if aep is not None and res.get("value") is not None and float(res["value"]) > 0:
            flows[aep] = float(res["value"])      # NSS reports -99999 when an input is missing
    return dict(sorted(flows.items(), reverse=True)), used


def flow_at_aep(peak_flows: dict, aep_pct: float) -> float | None:
    """Interpolate log(Q) against the standard normal variate of the AEP
    (log-normal probability paper); clamps to the tabulated range."""
    pts = sorted(((float(k), float(v)) for k, v in (peak_flows or {}).items() if v and float(v) > 0),
                 reverse=True)
    if not pts:
        return None
    z = lambda p: NormalDist().inv_cdf(1.0 - p / 100.0)       # noqa: E731
    target = z(min(max(aep_pct, pts[-1][0]), pts[0][0]))
    zs = [z(p) for p, _ in pts]
    lq = [math.log(q) for _, q in pts]
    for i in range(len(zs) - 1):
        if zs[i] <= target <= zs[i + 1]:
            t = 0.0 if zs[i + 1] == zs[i] else (target - zs[i]) / (zs[i + 1] - zs[i])
            return math.exp(lq[i] + t * (lq[i + 1] - lq[i]))
    return math.exp(lq[0] if target <= zs[0] else lq[-1])


def aep_of_flow(peak_flows: dict, q_cfs: float) -> float | None:
    """Inverse of :func:`flow_at_aep`: AEP percent of a discharge (clamped)."""
    pts = sorted(((float(k), float(v)) for k, v in (peak_flows or {}).items() if v and float(v) > 0),
                 reverse=True)
    if not pts or q_cfs is None or q_cfs <= 0:
        return None
    if q_cfs <= pts[0][1]:
        return pts[0][0]
    if q_cfs >= pts[-1][1]:
        return pts[-1][0]
    z = lambda p: NormalDist().inv_cdf(1.0 - p / 100.0)       # noqa: E731
    lq = math.log(q_cfs)
    for (p0, q0), (p1, q1) in zip(pts, pts[1:]):
        if q0 <= q_cfs <= q1:
            t = (lq - math.log(q0)) / (math.log(q1) - math.log(q0))
            return 100.0 * (1.0 - NormalDist().cdf(z(p0) + t * (z(p1) - z(p0))))
    return None


def plausibility(drainage_area_sq_mi: float | None, max_span_ft: float | None,
                 total_length_ft: float | None = None) -> list:
    """Flags for a basin that does not fit the opening it drains through.
    Screening bounds, deliberately loose: a 10-20 ft culvert does not drain
    hundreds of square miles, and a 200 ft multi-span river crossing does not
    sit on a basin of a few acres."""
    flags = []
    if drainage_area_sq_mi is None:
        return ["no drainage area"]
    if drainage_area_sq_mi <= MIN_BASIN_SQ_MI:
        flags.append("basin under 3 acres - pour point probably missed the channel")
    span = max(max_span_ft or 0.0, 0.0)
    length = max(total_length_ft or 0.0, span)
    if span and span <= 20 and drainage_area_sq_mi > 50:
        flags.append(f"{drainage_area_sq_mi:.0f} mi^2 through a {span:.0f} ft span - snapped to a larger stream?")
    if length >= 150 and drainage_area_sq_mi < 0.5:
        flags.append(f"{drainage_area_sq_mi:.2f} mi^2 under a {length:.0f} ft bridge - snapped to a side ditch?")
    return flags


# ── service calls ─────────────────────────────────────────────────────────

def _call(method, url, *, session, attempts=3, timeout=180, **kw):
    import requests

    s = session or requests
    last = None
    for k in range(attempts):
        try:
            r = s.request(method, url, timeout=timeout, **kw)
            if r.status_code in (502, 503, 504, 429):
                raise StreamStatsError(f"{r.status_code} from {url}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:                                   # noqa: BLE001
            last = exc
            if k < attempts - 1:
                time.sleep(5 * (k + 1))
    raise StreamStatsError(f"{url}: {last}")


def delineate_basin(lat: float, lon: float, *, region: str = "OH", session=None,
                    with_flows: bool = True) -> Basin:
    """Run the StreamStats workflow at a pour point (WGS84)."""
    b = Basin(lat, lon)
    t = time.time()
    resp = _call("GET", DELINEATE.format(region=region), session=session, params={"lat": lat, "lon": lon})
    d = parse_delineation(resp)
    b.outlet, b.geometry, b.polygon_area_sq_mi = d["outlet"], d["geometry"], d["polygon_area_sq_mi"]
    b.warnings, b.huc = d["warnings"], d["huc"]
    b.timings_s["delineate"] = round(time.time() - t, 1)
    if not b.delineated or not with_flows:
        return b

    t = time.time()
    regions = _call("POST", NSS_REGIONS, session=session, json=b.geometry)
    codes = [r["code"] for r in regions or [] if r.get("code")]
    scenarios = _call("GET", NSS_SCENARIOS, session=session,
                      params={"regions": region, "statisticgroups": PEAK_FLOW_GROUP,
                              "regressionregions": ",".join(codes)})
    scenario = peak_flow_scenario(scenarios)
    params = sorted({p["code"] for r in scenario["regressionRegions"] for p in r.get("parameters", [])}
                    | {"DRNAREA"})
    resp["bcrequest"]["bcLabels"] = ";".join(params)
    chars = _call("POST", BASIN_CHARS, session=session, json=resp, timeout=300)
    # ss-hydro reports -999 for a characteristic it could not compute
    b.characteristics = {c["code"]: {"value": c.get("value") if (c.get("value") or 0) > -999 else None,
                                     "unit": c.get("unit"), "name": c.get("name")}
                         for c in chars or []}
    da = b.characteristics.get("DRNAREA", {}).get("value")
    b.drainage_area_sq_mi = float(da) if da is not None and float(da) > 0 else None
    b.timings_s["characteristics"] = round(time.time() - t, 1)

    t = time.time()
    estimate = _call("POST", NSS_ESTIMATE, session=session, params={"regions": region},
                     json=[fill_scenario(scenario, chars)])
    b.peak_flows, b.regression = parse_estimate(estimate)
    b.timings_s["flows"] = round(time.time() - t, 1)
    return b
