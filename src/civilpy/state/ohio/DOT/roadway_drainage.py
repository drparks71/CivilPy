#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT roadway drainage - ditches, pavement drainage and storm sewers -
L&D Vol 2 sections 1102, 1103 and 1104 (July 2026), the calculations ODOT's
CDSS "Ditch Analysis", "Inlet Spacing" and "Storm Sewer" modules make.

Every function cites its section.  Rainfall comes from :mod:`.idf`
(Figure 1101-2; Atlas 14 is not allowed for the rational method).

Ditches (1102.3)
    design storms by ADT (:func:`ditch_design_aeps`), Manning's normal depth
    in a trapezoidal / V ditch (:func:`normal_depth`), shear ``62.4 D S``
    against Table 1102-1 and the permanent linings (:func:`shear_stress`,
    :func:`select_lining`), the 1 ft-below-pavement depth limit and lining
    widths (:func:`ditch_check`), the CB-2-2-A window weir, depressed median
    catch basin spacing (1102.3.6).

Pavement (1103)
    design storms and allowable spread by facility (Table 1103-1), the gutter
    equation ``Q = 0.56 Z S^1/2 Y^8/3 / n`` straight and composite (1103.4),
    grate / curb-opening interception on grade with the July 2026 corrected
    equations (1103.5.2), sag grates (1103.6), scupper efficiency
    ``1 - (1 - W/T)^2.67`` and bridge-end treatment (1103.8), slotted drains
    (1103.9), the Figure 1103-1 local depressions, and an inlet-spacing
    walk along a continuous grade (:func:`space_inlets`).

Storm sewers (1104)
    just-full (0.938 D) sizing at 10 % AEP working downstream with the
    rational method (:func:`design_storm_sewer`), n 0.015 / 0.013, minimum
    12 / 15 in, 3 fps cleansing and 10 fps / 4:1 limits, cover and access
    spacing, and the 4 % AEP hydraulic grade line worked upstream from the
    outlet starting at the higher of tailwater and ``(dc + D) / 2``
    (:func:`hydraulic_grade_line`), checked against 12 in below the
    pavement edge (ditch sections) or the grate elevation (curbed).

Standard-drawing dimensions (grate lengths, window lengths, open areas of
CB-3 / CB-6 / I-2 ...) are inputs here - take them from the Hydraulic SCDs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import idf

G = 32.2
GAMMA = 62.4
MANNING_K = 1.486                     # US customary Manning's constant

# ── ditches (1102.3) ──────────────────────────────────────────────────────

#: Table 1102-2 Manning's n by lining.
LINING_N = {
    "bare earth": 0.02, "seeded": 0.03, "sod": 0.04, "turf reinforcing mat": 0.04, "item 670": 0.04,
    "concrete": 0.02, "bituminous": 0.02, "grouted riprap": 0.02, "tied concrete block": 0.03,
    "rock channel protection (ditch)": 0.06, "rock channel protection (large channel)": 0.04,
}

#: Table 1102-1 and 1102.3.2 A-E allowable shear (lb/sq ft), by allowable shear; rock channel protection
#: ahead of a turf mat of the same value (it is only offered outside the clear zone or behind barrier).
ALLOWABLE_SHEAR = {
    "seed (659)": 0.40,
    "sodding (660)": 1.0,
    "item 670 type B": 1.50, "item 670 type G": 1.75, "item 670 type C": 2.0,
    "rock channel protection type D": 2.0,
    "item 670 type E": 2.25,
    "turf reinforcing mat type 1 (SS836)": 3.0,
    "rock channel protection type C": 4.0, "turf reinforcing mat type 2 (SS836)": 4.0,
    "turf reinforcing mat type 3 (SS836)": 5.0,
    "rock channel protection type B": 6.0, "turf reinforcing mat type 4 (SS836)": 6.0,
    "tied concrete block mat (601)": 12.0,
    "articulating concrete block type 1 (601)": 17.0, "articulating concrete block type 2 (601)": 20.0,
    "articulating concrete block type 3 (601)": 23.0,
}
TEMPORARY_LININGS = {"item 670 type B", "item 670 type G", "item 670 type C", "item 670 type E"}
TEMPORARY_LINING_MONTHS = 6          # 1102.3.2: temporary values for 6 months or less; 1.0 once vegetated
LINING_MIN_WIDTH_FT = 4.0            # 1102.3.1
LINING_WIDTH_STEP_FT = 3.5
DITCH_FREEBOARD_BELOW_PAVEMENT_FT = 1.0   # 1102.3.1: flow 1 ft below the edge of pavement
MIN_DITCH_VELOCITY_NOTE = "none; shear governs (1102.3.2)"


def ditch_design_aeps(adt: float | None) -> dict:
    """1102.3.1: depth of flow and shear stress design storms by ADT.
    Unknown ADT is treated as 3,000 or more (the conservative pair)."""
    if adt is not None and float(adt) < 3000:
        return {"depth_aep_pct": 20.0, "shear_aep_pct": 50.0, "adt_class": "under 3,000 ADT", "basis": "1102.3.1"}
    return {"depth_aep_pct": 10.0, "shear_aep_pct": 20.0,
            "adt_class": "3,000 ADT or more" if adt is not None else "ADT unknown (treated as 3,000 or more)",
            "basis": "1102.3.1"}


@dataclass(frozen=True)
class Trapezoid:
    """Ditch section: bottom width (0 for a V ditch) and side slopes as
    horizontal : 1 (z_left, z_right)."""
    bottom_ft: float
    z_left: float
    z_right: float

    def area(self, y):
        return self.bottom_ft * y + 0.5 * (self.z_left + self.z_right) * y * y

    def top_width(self, y):
        return self.bottom_ft + (self.z_left + self.z_right) * y

    def wetted_perimeter(self, y):
        return self.bottom_ft + y * (math.sqrt(1 + self.z_left ** 2) + math.sqrt(1 + self.z_right ** 2))

    def hydraulic_radius(self, y):
        p = self.wetted_perimeter(y)
        return self.area(y) / p if p > 0 else 0.0


def manning_q(area_sqft: float, hydraulic_radius_ft: float, n: float, slope: float) -> float:
    """Q = 1.486 / n A R^(2/3) S^(1/2)."""
    return MANNING_K / n * area_sqft * hydraulic_radius_ft ** (2.0 / 3.0) * math.sqrt(max(slope, 0.0))


def normal_depth(q_cfs: float, section: Trapezoid, n: float, slope: float, *, y_max_ft: float = 20.0) -> float:
    """Depth at which the section carries ``q_cfs`` (bisection on Manning's)."""
    if q_cfs <= 0:
        return 0.0
    if slope <= 0:
        raise ValueError("a ditch needs a positive slope for normal depth")
    lo, hi = 0.0, y_max_ft
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if manning_q(section.area(mid), section.hydraulic_radius(mid), n, slope) < q_cfs:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def shear_stress(depth_ft: float, slope: float) -> float:
    """tau = 62.4 D S (lb/sq ft), 1102.3.2."""
    return GAMMA * depth_ft * slope


def lining_width(top_width_ft: float) -> float:
    """1102.3.1: 4 ft minimum, then 3.5 ft increments, centred on the flow line."""
    w = LINING_MIN_WIDTH_FT
    while w < top_width_ft - 1e-9:
        w += LINING_WIDTH_STEP_FT
    return w


def select_lining(shear_lb_sqft: float, *, slope: float, outside_clear_zone: bool = False, behind_barrier: bool = False,
                  q_20pct_cfs: float | None = None, side_slope_z: float | None = None, temporary: bool = False) -> dict:
    """The least lining whose allowable shear (Table 1102-1, 1102.3.2 A-E)
    covers the actual shear, within each lining's limits: TRM on grades of
    10 % or less; rock channel protection only outside the clear zone or
    behind barrier, grades under 10 %, 20 % AEP flow under 50 cfs (10-25 %
    grades: HEC-15 with a 1.5 safety factor, contact OHE); tied block and
    ACB with side slopes 2:1 or flatter; concrete only as a last resort
    (contact OHE)."""
    tau = float(shear_lb_sqft)
    rejected = []
    for name, allow in ALLOWABLE_SHEAR.items():
        if allow < tau:
            continue
        if name in TEMPORARY_LININGS and not temporary:
            rejected.append((name, "temporary lining (6 months or less; 1.0 lb/sq ft once vegetated)"))
            continue
        if "turf reinforcing" in name and slope > 0.10:
            rejected.append((name, "TRM only on grades of 10 % or less"))
            continue
        if "rock channel" in name:
            if not (outside_clear_zone or behind_barrier):
                rejected.append((name, "RCP lining only outside the clear zone or behind guardrail / barrier"))
                continue
            if slope >= 0.10:
                rejected.append((name, "10-25 % grades: HEC-15 with SF 1.5 (Type B / C), contact OHE"))
                continue
            if q_20pct_cfs is not None and q_20pct_cfs >= 50.0:
                rejected.append((name, "shear equation valid under 50 cfs; contact OHE"))
                continue
        if ("tied concrete" in name or "articulating" in name) and side_slope_z is not None and side_slope_z < 2.0:
            rejected.append((name, "side slopes 2:1 or flatter"))
            continue
        if "tied concrete" in name and slope > 0.25:
            rejected.append((name, "profile grades 25 % or less"))
            continue
        return {"lining": name, "allowable_lb_sqft": allow, "actual_lb_sqft": round(tau, 3), "rejected": rejected,
                "basis": "Table 1102-1 / 1102.3.2"}
    return {"lining": "concrete (last resort - contact OHE)", "allowable_lb_sqft": None, "actual_lb_sqft": round(tau, 3),
            "rejected": rejected, "basis": "1102.3.2 F"}


def ditch_check(q_depth_cfs: float, q_shear_cfs: float, section: Trapezoid, slope: float, *, lining: str = "seeded",
                pavement_edge_above_flowline_ft: float | None = None, bank_height_ft: float | None = None,
                **lining_kw) -> dict:
    """1102.3.1 / 1102.3.2 at one ditch checkpoint: normal depth at the depth
    storm against 1 ft below the pavement edge (and the bank in toe-of-slope
    ditches), shear at the shear storm against the lining, the lining that
    would pass and its width.  ``lining`` names a Table 1102-2 entry for n."""
    n = LINING_N[lining]
    y = normal_depth(q_depth_cfs, section, n, slope)
    y_s = normal_depth(q_shear_cfs, section, n, slope)
    tau = shear_stress(y_s, slope)
    v = q_depth_cfs / section.area(y) if y > 0 else 0.0
    out = {"depth_ft": round(y, 3), "velocity_fps": round(v, 2), "top_width_ft": round(section.top_width(y), 2),
           "shear_depth_ft": round(y_s, 3), "shear_lb_sqft": round(tau, 3), "n": n, "basis": "1102.3.1 / 1102.3.2",
           "flags": []}
    if pavement_edge_above_flowline_ft is not None:
        limit = pavement_edge_above_flowline_ft - DITCH_FREEBOARD_BELOW_PAVEMENT_FT
        out["depth_limit_ft"] = round(limit, 3)
        if y > limit:
            out["flags"].append(f"depth {y:.2f} ft exceeds {limit:.2f} ft (1 ft below the pavement edge) - catch basin or deeper ditch")
    if bank_height_ft is not None and y > bank_height_ft:
        out["flags"].append(f"depth {y:.2f} ft overtops the {bank_height_ft:.2f} ft ditch bank (1102.3.1)")
    seed = ALLOWABLE_SHEAR["seed (659)"]
    out["seed_ok"] = tau <= seed
    pick = select_lining(tau, slope=slope, **lining_kw)
    out["lining_required"] = pick
    if not out["seed_ok"]:
        out["lining_width_ft"] = lining_width(section.top_width(y_s))
        out["flags"].append(f"shear {tau:.2f} lb/sq ft exceeds seed ({seed}) - {pick['lining']}"
                            + (f", {out['lining_width_ft']:.1f} ft wide" if pick["allowable_lb_sqft"] else ""))
    return out


def cb_window_capacity(length_ft: float, head_ft: float, *, c: float = 3.0) -> float:
    """CB-2-2-A side window, unsubmerged: Q = C L H^1.5 (1102.3.4 D; the
    grate is access only on continuous grades)."""
    return c * length_ft * max(head_ft, 0.0) ** 1.5


#: 1102.3.6 depressed-median catch basin spacing in fill sections (median width ft -> desirable, maximum).
MEDIAN_CB_SPACING_FT = {84: (1250, 1500), 60: (1000, 1250), 40: (800, 1000)}
UNDERDRAIN_CB_SPACING_FT = 1000


def median_cb_spacing(median_width_ft: float, *, underdrains: bool = False) -> dict:
    """Desirable / maximum spacing for the nearest listed width at or below
    the median width; 1,000 ft maximum wherever underdrains need an outlet."""
    widths = sorted(MEDIAN_CB_SPACING_FT)
    w = max([x for x in widths if x <= median_width_ft] or [widths[0]])
    d, m = MEDIAN_CB_SPACING_FT[w]
    if underdrains:
        d, m = min(d, UNDERDRAIN_CB_SPACING_FT), min(m, UNDERDRAIN_CB_SPACING_FT)
    return {"desirable_ft": d, "maximum_ft": m, "table_width_ft": w, "basis": "1102.3.6",
            "note": "catch basins at every sag low point; omit the earth dike in a sag"}


# ── pavement drainage (1103) ──────────────────────────────────────────────

GUTTER_N = 0.015                      # ODOT's Spread and Scupper Bypass spreadsheet (1103.8.1); Table 1102-2 lists 0.02 for concrete
PAVEMENT_C = 0.9                      # Table 1101-2 pavement
MIN_DECK_GRADE = 0.003                # 1103.8.1 with concrete parapets; 1103.4 sag drainage 0.3 % at 50 ft from the bottom
SAG_K_MAX = 167                       # 1103.4 drainage maximum K for curbed sag vertical curves
FLANKING_INLET_RISE_FT = 0.20         # 1103.6 on freeways
SAG_WEIR_DEPTH_LIMIT_FT = 0.4         # 1103.6
SAG_WEIR_C = 3.0                      # HEC-22 Cw for grates in sags (LD2 gives the 0.4 ft switch, not the coefficients)
SAG_ORIFICE_C = 0.67                  # HEC-22 Co
SCUPPER_EXPONENT = 2.67               # 1103.8.1
BRIDGE_END_FLUME_MAX_CFS = 0.75       # 1103.8.2 A / B
BRIDGE_END_BYPASS_FLUME_CFS = 0.5     # 1103.8.2 B
ROUNDABOUT_CURB_CUT_MAX_CFS = 0.75    # 1103.2
MIN_INLET_SPACING_CONTACT_OHE_FT = 100.0   # 1103.3

#: Figure 1103-1 (January 2026) local depressions, inches: A at the grate
#: edge nearest the centerline, B at the curb window, for a normal pavement
#: slope and for a depressed pavement / gutter.  Starred values are the ones
#: CDSS uses; the I-3 grate's 0.75 in is for sags only.
LOCAL_DEPRESSION_IN = {
    "CB-3/3A": {"grate_slope": 0.1074, "normal": {"A": 0.5, "B": 2.0}, "depressed": {"A": 0.0, "B": 0.5}},
    "CB-6": {"grate_slope": 0.0, "normal": {"A": 1.25, "B": 0.5}, "depressed": {"A": 1.625, "B": 0.0}},
    "CB-9": {"grate_slope": None, "normal": {"A": 0.0, "B": None}, "depressed": {"A": None, "B": None}},
    "I-2/2A": {"grate_slope": None, "normal": {"A": None, "B": 2.0}, "depressed": {"A": None, "B": 2.0}},
    "I-3B/3C/3D grate": {"grate_slope": 0.0833, "normal": {"A": 0.75, "B": 2.0}, "depressed": {"A": None, "B": None},
                         "note": "A for CDSS in a sag only"},
    "I-3B/3C/I-4 window": {"grate_slope": None, "normal": {"A": None, "B": 2.0}, "depressed": {"A": None, "B": None}},
}


def pavement_design_aep(*, freeway: bool, aadt: float | None) -> dict:
    """1103.2: 10 % on interstates / freeways / expressways, 20 % over 6,000
    ADT, 50 % otherwise (unknown ADT -> 20 %, conservative)."""
    if freeway:
        return {"aep_pct": 10.0, "facility": "interstate / freeway / expressway", "basis": "1103.2"}
    if aadt is None or float(aadt) > 6000:
        return {"aep_pct": 20.0, "facility": "high volume highway (over 6,000 ADT)" if aadt is not None
                else "ADT unknown (treated as high volume)", "basis": "1103.2"}
    return {"aep_pct": 50.0, "facility": "all other highways", "basis": "1103.2"}


def sag_check_aep(*, freeway: bool, aadt: float | None, lanes: int | None) -> float | None:
    """1103.2 / 1104.3.2 ponding check for sags that drain only through the
    sewer: 2 % on freeways and high-volume highways, 4 % on other multilane
    roads, none on 2-lane (water overtops the curb; contact OHE)."""
    if freeway or (aadt is not None and float(aadt) > 6000):
        return 2.0
    if lanes is not None and lanes >= 3:
        return 4.0
    return None


def allowable_spread(*, freeway: bool, aadt: float | None, lanes: int | None, design_speed_mph: float | None = None,
                     lane_width_ft: float = 12.0) -> dict:
    """Table 1103-1 allowable spread into the through lane (12 ft lanes;
    narrower lanes lose the difference).  Unknown speed on a high-volume road
    is treated as 45 mph or more (4 ft)."""
    if freeway:
        t, row = 0.0, "interstates, freeways & expressways"
    elif aadt is None or float(aadt) > 6000:
        if design_speed_mph is None or design_speed_mph >= 45:
            t, row = 4.0, "high volume, 45 mph or more" + (" (speed unknown)" if design_speed_mph is None else "")
        else:
            t, row = (8.0, "high volume, under 45 mph, 4 lanes") if (lanes or 2) >= 4 else (6.0, "high volume, under 45 mph, 2 lanes")
    else:
        t, row = (8.0, "all other highways, 4 or more lanes") if (lanes or 2) >= 4 else (6.0, "all other highways, 2 lanes")
    t = max(t - max(12.0 - lane_width_ft, 0.0), 0.0)
    return {"spread_ft": t, "row": row, "basis": "Table 1103-1", "lane_width_ft": lane_width_ft,
            "note": "through lane only; a 10 ft dry lane minimum; roundabouts may be increased proportionally"}


def gutter_flow(y_ft: float, sx: float, s: float, n: float = GUTTER_N) -> float:
    """Q = 0.56 Z S^1/2 Y^8/3 / n, Z = 1 / Sx (1103.4), a triangular section at a curb."""
    if y_ft <= 0:
        return 0.0
    return 0.56 / sx * math.sqrt(s) * y_ft ** (8.0 / 3.0) / n


def gutter_depth(q_cfs: float, sx: float, s: float, n: float = GUTTER_N) -> float:
    """Depth at the curb carrying Q (1103.4 inverted)."""
    if q_cfs <= 0:
        return 0.0
    return (q_cfs * n * sx / (0.56 * math.sqrt(s))) ** (3.0 / 8.0)


def spread_from_q(q_cfs: float, sx: float, s: float, n: float = GUTTER_N) -> float:
    """Spread T = Y / Sx for a straight cross slope - the OHE spreadsheet's
    ``T = (Q n / (0.56 Sx^5/3 S^1/2))^3/8``."""
    return gutter_depth(q_cfs, sx, s, n) / sx


def composite_gutter_flow(y_ft: float, *, gutter_width_ft: float, sw: float, sx: float, s: float,
                          n_gutter: float = GUTTER_N, n_pavement: float = GUTTER_N) -> dict:
    """1103.4 composite section: Q1 (whole triangle at the gutter slope, depth
    Y) - Q2 (the part beyond the gutter at the gutter slope, depth Y1) + Q3
    (that part at the pavement slope); Y1 = Y - W Sw."""
    y1 = max(y_ft - gutter_width_ft * sw, 0.0)
    q1 = gutter_flow(y_ft, sw, s, n_gutter)
    q2 = gutter_flow(y1, sw, s, n_gutter)
    q3 = gutter_flow(y1, sx, s, n_pavement)
    t = gutter_width_ft + y1 / sx if y1 > 0 else y_ft / sw
    return {"q_cfs": q1 - q2 + q3, "q1": q1, "q2": q2, "q3": q3, "y1_ft": y1, "spread_ft": t, "basis": "1103.4"}


def composite_gutter_depth(q_cfs: float, **kw) -> dict:
    """Depth at the curb for Q in a composite section (bisection)."""
    lo, hi = 0.0, 5.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if composite_gutter_flow(mid, **kw)["q_cfs"] < q_cfs:
            lo = mid
        else:
            hi = mid
    y = 0.5 * (lo + hi)
    out = composite_gutter_flow(y, **kw)
    out["y_ft"] = y
    return out


def _side_capture_ratio(a_ft: float, y2_ft: float, l_ft: float, la_ft: float) -> float:
    """1103.5.2 (July 2026): the fraction of the flow beside the grate / window
    intercepted by an opening of length L when La is the length for 100 %."""
    if y2_ft <= 0 or la_ft <= 0:
        return 0.0
    r = l_ft / la_ft
    if r >= 1.0:
        return 1.0
    k = a_ft / y2_ft
    num = (k + 1.0) ** 2.5 - (k + 1.0 - r) ** 2.5
    den = (k + 1.0) ** 2.5 - k ** 2.5
    return min(max(num / den, 0.0), 1.0) if den > 0 else 0.0


def opening_capture_length(q_side_cfs: float, a_ft: float, y_ft: float) -> float:
    """La: Qa / La = 0.7 (A + Y)^1.5 (1 - (1 - Y / (A + Y))^2.5) (1103.5.2)."""
    if y_ft <= 0 or q_side_cfs <= 0:
        return 0.0
    per_ft = 0.7 * (a_ft + y_ft) ** 1.5 * (1.0 - (1.0 - y_ft / (a_ft + y_ft)) ** 2.5)
    return q_side_cfs / per_ft if per_ft > 0 else math.inf


def grate_interception(q_cfs: float, *, sx: float, s: float, grate_width_ft: float, grate_length_ft: float,
                       depression_a_ft: float = 0.0, n: float = GUTTER_N, gutter_width_ft: float | None = None,
                       sw: float | None = None) -> dict:
    """Grate or combination catch basin on a continuous grade (1103.5.2):
    everything over the grate width is captured; the flow beside the grate
    (Qa, the triangle beyond the grate edge at depth Y2, no depression) is
    intercepted as a window of depth Y2 and the grate's length, with local
    depression A (Figure 1103-1).  The curb opening of a combination basin is
    not counted.  Returns Qi, the bypass Qb and the efficiency."""
    if q_cfs <= 0:
        return {"q_cfs": 0.0, "intercepted_cfs": 0.0, "bypass_cfs": 0.0, "efficiency_pct": 100.0, "basis": "1103.5.2"}
    if gutter_width_ft and sw:
        g = composite_gutter_depth(q_cfs, gutter_width_ft=gutter_width_ft, sw=sw, sx=sx, s=s, n_gutter=n, n_pavement=n)
        y, t = g["y_ft"], g["spread_ft"]
        if grate_width_ft <= gutter_width_ft:
            y2 = y - grate_width_ft * sw
        else:
            y2 = y - gutter_width_ft * sw - (grate_width_ft - gutter_width_ft) * sx
    else:
        y = gutter_depth(q_cfs, sx, s, n)
        t = y / sx
        y2 = y - grate_width_ft * sx
    y2 = max(y2, 0.0)
    qa = gutter_flow(y2, sx, s, n) if y2 > 0 else 0.0           # beside the grate
    q_over = q_cfs - qa
    la = opening_capture_length(qa, depression_a_ft, y2)
    qi_side = qa * _side_capture_ratio(depression_a_ft, y2, grate_length_ft, la)
    qi = q_over + qi_side
    return {"q_cfs": q_cfs, "depth_ft": round(y, 4), "spread_ft": round(t, 3), "y2_ft": round(y2, 4),
            "q_over_grate_cfs": round(q_over, 4), "q_beside_cfs": round(qa, 4), "la_ft": round(la, 3) if la != math.inf else None,
            "intercepted_cfs": round(qi, 4), "bypass_cfs": round(q_cfs - qi, 4), "efficiency_pct": round(100.0 * qi / q_cfs, 2),
            "basis": "1103.5.2"}


def curb_opening_interception(q_cfs: float, *, sx: float, s: float, window_length_ft: float, depression_b_ft: float = 0.0,
                              n: float = GUTTER_N) -> dict:
    """Curb / barrier opening inlet on grade: the same equations with the
    depth at the curb face Y and the window's local depression B
    (1103.5.2, 1103.5.1 - the grate on a barrier inlet is a safety factor)."""
    if q_cfs <= 0:
        return {"q_cfs": 0.0, "intercepted_cfs": 0.0, "bypass_cfs": 0.0, "efficiency_pct": 100.0, "basis": "1103.5.2"}
    y = gutter_depth(q_cfs, sx, s, n)
    la = opening_capture_length(q_cfs, depression_b_ft, y)
    qi = q_cfs * _side_capture_ratio(depression_b_ft, y, window_length_ft, la)
    return {"q_cfs": q_cfs, "depth_ft": round(y, 4), "spread_ft": round(y / sx, 3), "la_ft": round(la, 3),
            "intercepted_cfs": round(qi, 4), "bypass_cfs": round(q_cfs - qi, 4), "efficiency_pct": round(100.0 * qi / q_cfs, 2),
            "basis": "1103.5.2"}


def window_length_for_bypass(q_cfs: float, *, sx: float, s: float, depression_b_ft: float = 0.0, bypass_fraction: float = 0.10,
                             n: float = GUTTER_N) -> float:
    """1103.5: size an inlet window to bypass 10-15 % of the design flow -
    the length L for which the captured fraction is 1 - bypass."""
    target = 1.0 - bypass_fraction
    y = gutter_depth(q_cfs, sx, s, n)
    la = opening_capture_length(q_cfs, depression_b_ft, y)
    lo, hi = 0.0, la
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _side_capture_ratio(depression_b_ft, y, mid, la) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def sag_grate_capacity(depth_ft: float, *, perimeter_ft: float, open_area_sqft: float) -> dict:
    """1103.6: weir flow over the grate edge to 0.4 ft (Cw 3.0, HEC-22),
    orifice through the full open area above that (Co 0.67), no clogging
    deduction.  The depth is the ponding at the grate edge."""
    d = max(depth_ft, 0.0)
    if d <= SAG_WEIR_DEPTH_LIMIT_FT:
        q, regime = SAG_WEIR_C * perimeter_ft * d ** 1.5, "weir"
    else:
        q, regime = SAG_ORIFICE_C * open_area_sqft * math.sqrt(2 * G * d), "orifice"
    return {"q_cfs": q, "regime": regime, "depth_ft": d, "basis": "1103.6 (coefficients HEC-22)"}


def sag_spread(q_total_cfs: float, *, sx: float, perimeter_ft: float, open_area_sqft: float, depression_ft: float = 0.0) -> dict:
    """Ponding depth at the grate edge that passes the total flow reaching the
    sag from both sides, and the spread it makes ((d - local depression) / Sx)."""
    lo, hi = 0.0, 3.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if sag_grate_capacity(mid, perimeter_ft=perimeter_ft, open_area_sqft=open_area_sqft)["q_cfs"] < q_total_cfs:
            lo = mid
        else:
            hi = mid
    d = 0.5 * (lo + hi)
    cap = sag_grate_capacity(d, perimeter_ft=perimeter_ft, open_area_sqft=open_area_sqft)
    return {"depth_ft": round(d, 4), "spread_ft": round(max(d - depression_ft, 0.0) / sx, 3), "regime": cap["regime"], "basis": "1103.6"}


def scupper_efficiency(scupper_width_ft: float, spread_ft: float) -> float:
    """E = 1 - (1 - W / T)^2.67 (1103.8.1; side capture and splash-over neglected)."""
    if spread_ft <= 0:
        return 0.0
    return 1.0 - (1.0 - min(scupper_width_ft / spread_ft, 1.0)) ** SCUPPER_EXPONENT


def scupper_bypass(q_cfs: float, scupper_width_ft: float, spread_ft: float) -> dict:
    e = scupper_efficiency(scupper_width_ft, spread_ft)
    return {"efficiency": round(e, 4), "intercepted_cfs": round(q_cfs * e, 4), "bypass_cfs": round(q_cfs * (1 - e), 4),
            "basis": "1103.8.1"}


def bridge_end_treatment(q_end_cfs: float, *, mse_wall: bool = False, bypass_cfs: float | None = None) -> dict:
    """1103.8.2: what collects the deck flow leaving the parapet end."""
    if mse_wall:
        return {"treatment": "barrier with a standard barrier inlet at the approach slab, outside the MSE reinforcement and the "
                             "barrier transition", "items": ["barrier inlet"], "basis": "1103.8.2 C"}
    if q_end_cfs < BRIDGE_END_FLUME_MAX_CFS:
        return {"treatment": "flume (SCD DM-4.1) beyond the bridge terminal assembly", "items": ["flume DM-4.1"], "basis": "1103.8.2 A"}
    items = ["CB-3A off the approach slab, outside the curb taper and the bridge terminal assembly",
             "Type F broken-back conduit down the embankment (Figure 1104-1), armoured outlet"]
    if bypass_cfs is not None and bypass_cfs > BRIDGE_END_BYPASS_FLUME_CFS:
        items.append("flume DM-4.1 downstream of the basin at the end of the curb (bypass over 0.5 cfs)")
    return {"treatment": "CB-3A catch basin with a Type F outlet", "items": items, "basis": "1103.8.2 B"}


def slotted_drain_length(q_cfs: float, *, s: float, sx: float, n: float = GUTTER_N, kt: float = 0.6) -> float:
    """HEC-22 4-22a on grade: LT = KT Q^0.42 SL^0.3 (1 / (n Sx))^0.6 (1103.9)."""
    return kt * q_cfs ** 0.42 * s ** 0.3 * (1.0 / (n * sx)) ** 0.6


def slotted_drain_length_sag(q_cfs: float, *, depth_ft: float, width_ft: float, clogging_factor: float = 2.0) -> dict:
    """HEC-22 4-32 / 4-33 in a sag: weir to 0.2 ft, orifice above; LD2
    recommends twice the length for 50 % clogging (1103.9)."""
    if depth_ft < 0.2:
        lt, regime = q_cfs / (2.48 * depth_ft ** 1.5), "weir"
    else:
        lt, regime = q_cfs / (0.8 * width_ft * math.sqrt(2 * G * depth_ft)), "orifice"
    return {"length_ft": lt, "length_with_clogging_ft": lt * clogging_factor, "regime": regime, "basis": "1103.9 (HEC-22 4-32 / 4-33)"}


SLOTTED_DRAIN_CB6_INTERVAL_FT = 100
TRENCH_DRAIN_CB6_INTERVAL_FT = 200


def space_inlets(*, zone: str, aep_pct: float, sx: float, s: float, drainage_width_ft: float, allowable_spread_ft: float,
                 start_station_ft: float = 0.0, end_station_ft: float, grate_width_ft: float, grate_length_ft: float,
                 depression_a_ft: float = 0.0, c: float = PAVEMENT_C, tc_min: float = idf.MIN_TC_PAVEMENT_MIN,
                 n: float = GUTTER_N, step_ft: float = 5.0, max_inlets: int = 200) -> dict:
    """Inlet spacing along a continuous grade (1103.3-1103.5): walk
    downstream, the gutter flow is C i A (A = contributing width x distance,
    i at the 10-minute minimum tc) plus the bypass of the inlet above, and an
    inlet goes where the spread would exceed the allowable.  Spacings of
    100 ft or less mean contacting OHE (1103.3).  Grate dimensions come from
    the SCD of the basin chosen."""
    i = idf.intensity(tc_min, aep_pct, zone)
    q_allow = gutter_flow(allowable_spread_ft * sx, sx, s, n)
    per_ft = c * i * drainage_width_ft / 43560.0                   # cfs per foot of gutter
    inlets, bypass, sta_prev, sta = [], 0.0, start_station_ft, start_station_ft
    while sta < end_station_ft and len(inlets) < max_inlets:
        sta = min(sta + step_ft, end_station_ft)
        q = bypass + per_ft * (sta - sta_prev)
        if q >= q_allow or sta >= end_station_ft:
            cap = grate_interception(q, sx=sx, s=s, grate_width_ft=grate_width_ft, grate_length_ft=grate_length_ft,
                                     depression_a_ft=depression_a_ft, n=n)
            inlets.append({"station_ft": round(sta, 1), "spacing_ft": round(sta - sta_prev, 1), "q_cfs": round(q, 3),
                           "spread_ft": cap["spread_ft"], "intercepted_cfs": cap["intercepted_cfs"], "bypass_cfs": cap["bypass_cfs"],
                           "efficiency_pct": cap["efficiency_pct"]})
            bypass, sta_prev = cap["bypass_cfs"], sta
    flags = []
    if any(x["spacing_ft"] <= MIN_INLET_SPACING_CONTACT_OHE_FT for x in inlets[1:]):
        flags.append("spacing of 100 ft or less - contact OHE; consider a rolling gutter profile or I-2 inlets (1103.3, 1103.5)")
    return {"intensity_in_hr": round(i, 3), "allowable_q_cfs": round(q_allow, 3), "q_per_ft": per_ft, "inlets": inlets,
            "flags": flags, "basis": "1103.3-1103.5"}


# ── storm sewers (1104) ───────────────────────────────────────────────────

PIPE_SIZES_IN = (12, 15, 18, 21, 24, 27, 30, 33, 36, 42, 48, 54, 60, 66, 72, 78, 84, 90, 96, 102, 108, 120)
JUST_FULL_RATIO = 0.938               # 1104.3.1 just-full depth for circular conduits
SEWER_DESIGN_AEP = 10.0               # 1104.3.1
SEWER_HGL_AEP = 4.0                   # 1104.3.2
MIN_CLEANSING_VELOCITY_FPS = 3.0      # 1104.2.1 G
MAX_SEWER_VELOCITY_FPS = 10.0         # 1104.3.7
MAX_SEWER_SLOPE = 0.25                # 1104.3.7, 4:1
OUTLET_PROTECTION_VELOCITY_FPS = 5.0  # 1104.3.8
HGL_BELOW_PAVEMENT_EDGE_FT = 1.0      # 1104.3.2 A, ditch sections
BROKEN_BACK_SLOPE = 1.0 / 3.0         # 1104.3.7: embankments steeper than 3:1 -> Type F


def sewer_n(d_in: float) -> float:
    """1104.3.5: 0.015 to 60 in, 0.013 above (minor losses folded in)."""
    return 0.015 if d_in <= 60 else 0.013


def min_pipe_in(*, freeway: bool) -> int:
    """1104.3.6: 15 in on interstates / freeways / expressways and ramps, 12 in elsewhere."""
    return 15 if freeway else 12


def min_cover_in(*, rigid: bool, under_pavement: bool, high_strength: bool = False) -> dict:
    """1104.2.1 A-C height of cover."""
    if high_strength:
        return {"to_surface_in": 10 if under_pavement else 4, "to_subgrade_in": 4 if under_pavement else None,
                "basis": "1104.2.1 C (D-load from OHE)"}
    if rigid:
        return {"to_surface_in": 15 if under_pavement else 18, "to_subgrade_in": 9 if under_pavement else None, "basis": "1104.2.1 A"}
    return {"to_surface_in": 24, "to_subgrade_in": 12 if under_pavement else None, "basis": "1104.2.1 B"}


def access_spacing_ft(d_in: float) -> tuple:
    """1104.2.3 maximum manhole / access spacing: (desirable, maximum)."""
    if d_in < 36:
        return (300, 300)
    if d_in <= 60:
        return (500, 500)
    return (750, 1000)


def circle_section(d_ft: float, y_ft: float) -> dict:
    """Area, wetted perimeter, top width and hydraulic radius of a circle flowing at depth y."""
    y = min(max(y_ft, 0.0), d_ft)
    if y <= 0:
        return {"area": 0.0, "perimeter": 0.0, "top_width": 0.0, "rh": 0.0}
    theta = 2.0 * math.acos(1.0 - 2.0 * y / d_ft)
    a = d_ft * d_ft / 8.0 * (theta - math.sin(theta))
    p = d_ft * theta / 2.0
    t = d_ft * math.sin(theta / 2.0) if y < d_ft else 0.0
    return {"area": a, "perimeter": p, "top_width": t, "rh": a / p if p > 0 else 0.0}


def circular_q(d_in: float, y_ft: float, slope: float, n: float | None = None) -> float:
    g = circle_section(d_in / 12.0, y_ft)
    return manning_q(g["area"], g["rh"], n or sewer_n(d_in), slope)


def full_flow_q(d_in: float, slope: float, n: float | None = None) -> float:
    return circular_q(d_in, d_in / 12.0, slope, n)


def just_full_capacity(d_in: float, slope: float, n: float | None = None) -> dict:
    """1104.3.1: capacity and velocity at 93.8 % of the diameter (the maximum
    discharge depth, about 1.076 x full)."""
    d = d_in / 12.0
    y = JUST_FULL_RATIO * d
    g = circle_section(d, y)
    q = manning_q(g["area"], g["rh"], n or sewer_n(d_in), slope)
    return {"q_cfs": q, "velocity_fps": q / g["area"] if g["area"] else 0.0, "depth_ft": y, "basis": "1104.3.1"}


def normal_depth_circular(q_cfs: float, d_in: float, slope: float, n: float | None = None) -> float | None:
    """Depth carrying Q in open channel, or None when Q exceeds the just-full capacity (pressure flow)."""
    if q_cfs <= 0:
        return 0.0
    if slope <= 0 or q_cfs > just_full_capacity(d_in, slope, n)["q_cfs"]:
        return None
    d = d_in / 12.0
    lo, hi = 0.0, JUST_FULL_RATIO * d
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if circular_q(d_in, mid, slope, n) < q_cfs:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def critical_depth_circular(q_cfs: float, d_in: float) -> float:
    """dc from Q^2 T / (g A^3) = 1, capped at the diameter."""
    d = d_in / 12.0
    if q_cfs <= 0:
        return 0.0
    lo, hi = 0.0, d
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        g = circle_section(d, mid)
        if g["area"] <= 0 or g["top_width"] <= 0:
            lo = mid
            continue
        if q_cfs * q_cfs * g["top_width"] / (G * g["area"] ** 3) > 1.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def friction_slope(q_cfs: float, d_in: float, n: float | None = None) -> float:
    """Full-flow friction slope from Manning's: Sf = (Q n / (1.486 A R^2/3))^2."""
    g = circle_section(d_in / 12.0, d_in / 12.0)
    return (q_cfs * (n or sewer_n(d_in)) / (MANNING_K * g["area"] * g["rh"] ** (2.0 / 3.0))) ** 2


def size_pipe(q_cfs: float, slope: float, *, freeway: bool = False, n: float | None = None, sizes=PIPE_SIZES_IN) -> dict:
    """1104.3.1 / 1104.3.6 / 1104.3.7 / 1104.2.1 G: the smallest standard
    size at or above the minimum whose just-full capacity carries Q, with
    the velocity flags."""
    floor = min_pipe_in(freeway=freeway)
    for d in sizes:
        if d < floor:
            continue
        jf = just_full_capacity(d, slope, n)
        if jf["q_cfs"] >= q_cfs:
            return dict(d_in=d, n=n or sewer_n(d), capacity_cfs=round(jf["q_cfs"], 3), velocity_fps=round(jf["velocity_fps"], 2),
                        flags=velocity_flags(jf["velocity_fps"], slope), basis="1104.3.1 just full")
    return dict(d_in=None, n=None, capacity_cfs=None, velocity_fps=None, flags=[f"no standard size up to {sizes[-1]} in carries {q_cfs:.1f} cfs at this slope"],
                basis="1104.3.1 just full")


def velocity_flags(v_fps: float, slope: float) -> list:
    flags = []
    if v_fps < MIN_CLEANSING_VELOCITY_FPS:
        flags.append(f"velocity {v_fps:.1f} fps under the 3 fps cleansing recommendation (1104.2.1 G)")
    if v_fps > MAX_SEWER_VELOCITY_FPS:
        flags.append(f"velocity {v_fps:.1f} fps over 10 fps - drop structure (1104.3.7)")
    if slope > MAX_SEWER_SLOPE:
        flags.append(f"slope {slope:.3f} steeper than 4:1 - drop structure (1104.3.7)")
    if slope > BROKEN_BACK_SLOPE:
        flags.append("steeper than 3:1: along an embankment designate Type F broken back (1104.3.7, Figure 1104-1)")
    if v_fps > OUTLET_PROTECTION_VELOCITY_FPS:
        flags.append("outlet over 5 fps - rock channel protection per Figure 1002-4 at the 10 % storm (1104.3.8)")
    return flags


def hgl_limit_ft(*, pavement_edge_ft: float | None = None, grate_ft: float | None = None) -> float | None:
    """1104.3.2: 12 in below the near pavement edge without curb (A), the
    inlet / grate elevation with curb (B)."""
    if grate_ft is not None:
        return grate_ft
    if pavement_edge_ft is not None:
        return pavement_edge_ft - HGL_BELOW_PAVEMENT_EDGE_FT
    return None


def outlet_start_elevation(*, tailwater_ft: float | None, invert_ft: float, d_in: float, q_cfs: float) -> dict:
    """1104.3.2 / 1105.6.1: the HGL starts at the higher of the tailwater and (dc + D) / 2 above the outlet invert."""
    d = d_in / 12.0
    dc = critical_depth_circular(q_cfs, d_in)
    half = invert_ft + 0.5 * (dc + d)
    start = max(half, tailwater_ft) if tailwater_ft is not None else half
    return {"start_ft": start, "dc_ft": dc, "dc_plus_d_half_ft": half, "tailwater_ft": tailwater_ft,
            "controls": "tailwater" if tailwater_ft is not None and tailwater_ft > half else "(dc + D) / 2", "basis": "1104.3.2, 1105.6.1"}


def hydraulic_grade_line(runs: list, *, start_ft: float) -> list:
    """1104.3.2 HGL from the outlet upstream.  ``runs`` are ordered from the
    outlet run upward, each ``{q_cfs, d_in, length_ft, invert_down_ft,
    invert_up_ft, n?, limit_ft?}``.  Full runs rise along the friction slope;
    a run whose slope is steeper than its friction slope drains down to
    normal depth, and the HGL follows the water surface there until a flatter
    run fills again.  Each row carries the HGL at its upper end and whether
    it stays under the run's limit."""
    out, hgl = [], start_ft
    for r in runs:
        d_in, q, length = r["d_in"], r["q_cfs"], r["length_ft"]
        d = d_in / 12.0
        n = r.get("n") or sewer_n(d_in)
        slope = (r["invert_up_ft"] - r["invert_down_ft"]) / length if length else 0.0
        sf = friction_slope(q, d_in, n)
        yn = normal_depth_circular(q, d_in, slope, n) if slope > 0 else None
        hgl_down = max(hgl, r["invert_down_ft"] + (yn if yn is not None else d))
        hgl_up = hgl_down + sf * length                      # full: along the friction slope
        if yn is not None:
            hgl_up = max(hgl_up, r["invert_up_ft"] + yn)    # a steep run drains to normal depth
        regime = "pressure" if hgl_up > r["invert_up_ft"] + d else "open channel"
        limit = r.get("limit_ft")
        out.append({**{k: r[k] for k in ("q_cfs", "d_in", "length_ft", "invert_down_ft", "invert_up_ft")}, "n": n,
                    "slope": round(slope, 5), "friction_slope": round(sf, 5), "normal_depth_ft": round(yn, 3) if yn is not None else None,
                    "hgl_down_ft": round(hgl_down, 3), "hgl_up_ft": round(hgl_up, 3), "regime": regime, "limit_ft": limit,
                    "ok": (hgl_up <= limit) if limit is not None else None, "name": r.get("name")})
        hgl = hgl_up
    return out


def design_storm_sewer(runs: list, *, zone: str, freeway: bool = False, design_aep_pct: float = SEWER_DESIGN_AEP,
                       check_aep_pct: float = SEWER_HGL_AEP, tailwater_ft: float | None = None, first_inlet: str = "pavement") -> dict:
    """1104.4 procedure.  ``runs`` run from the top structure downstream to
    the outlet, each ``{name, c, area_acres, tc_local_min, length_ft,
    invert_up_ft, invert_down_ft, d_in?, limit_ft?}``: the local CA is added
    to the upstream total, tc is the larger of the local tc and the upstream
    tc plus pipe travel, i from Figure 1101-2 at the design storm, Q = CA i,
    the just-full size (or the given existing size checked), velocity flags
    and a crown-match drop for a smaller upstream pipe (1104.2.1 H).  Then
    the 4 % HGL with the last run's intensity for every run (1104.3.2)."""
    rows, ca, tc_prev, d_prev = [], 0.0, None, None
    for r in runs:
        ca += r["c"] * r["area_acres"]
        tc_local = idf.time_of_concentration(overland_min=r.get("tc_local_min", 0.0), first_inlet=first_inlet if tc_prev is None else None)
        tc = max(tc_local, tc_prev) if tc_prev is not None else tc_local
        i = idf.intensity(tc, design_aep_pct, zone)
        q = ca * i
        length = r["length_ft"]
        slope = (r["invert_up_ft"] - r["invert_down_ft"]) / length
        if r.get("d_in"):
            jf = just_full_capacity(r["d_in"], slope)
            pipe = dict(d_in=r["d_in"], n=sewer_n(r["d_in"]), capacity_cfs=round(jf["q_cfs"], 3), velocity_fps=round(jf["velocity_fps"], 2),
                        flags=velocity_flags(jf["velocity_fps"], slope), basis="existing size checked")
            if jf["q_cfs"] < q:
                pipe["flags"].append(f"existing {r['d_in']} in carries {jf['q_cfs']:.1f} cfs just full, under {q:.1f} cfs")
        else:
            pipe = size_pipe(q, slope, freeway=freeway)
        v = pipe["velocity_fps"] or 0.0
        travel = idf.travel_minutes(length, v) if v else 0.0
        flags = list(pipe["flags"])
        if d_prev is not None and pipe["d_in"] and pipe["d_in"] > d_prev:
            flags.append(f"match the {d_prev} in upstream crown to this {pipe['d_in']} in crown: drop {(pipe['d_in'] - d_prev) / 12:.2f} ft (1104.2.1 H)")
        if pipe["d_in"] and length > access_spacing_ft(pipe["d_in"])[1]:
            flags.append(f"run longer than the {access_spacing_ft(pipe['d_in'])[1]} ft access spacing (1104.2.3)")
        rows.append({"name": r.get("name"), "ca_acres": round(ca, 4), "tc_min": round(tc, 2), "intensity_in_hr": round(i, 3), "q_cfs": round(q, 3),
                     "slope": round(slope, 5), "length_ft": length, "invert_up_ft": r["invert_up_ft"], "invert_down_ft": r["invert_down_ft"],
                     "d_in": pipe["d_in"], "n": pipe["n"], "capacity_cfs": pipe["capacity_cfs"], "velocity_fps": pipe["velocity_fps"],
                     "travel_min": round(travel, 2), "flags": [f for f in flags if f], "limit_ft": r.get("limit_ft")})
        tc_prev, d_prev = tc + travel, pipe["d_in"] or d_prev
    # 1104.3.2: the check intensity is the last run's, applied to every run
    hgl_rows = []
    if rows and all(x["d_in"] for x in rows):
        i_check = idf.intensity(rows[-1]["tc_min"], check_aep_pct, zone)
        last = rows[-1]
        q_last = last["ca_acres"] * i_check
        start = outlet_start_elevation(tailwater_ft=tailwater_ft, invert_ft=last["invert_down_ft"], d_in=last["d_in"], q_cfs=q_last)
        up = [{"name": x["name"], "q_cfs": x["ca_acres"] * i_check, "d_in": x["d_in"], "length_ft": x["length_ft"],
               "invert_down_ft": x["invert_down_ft"], "invert_up_ft": x["invert_up_ft"], "n": x["n"], "limit_ft": x["limit_ft"]}
              for x in reversed(rows)]
        hgl_rows = hydraulic_grade_line(up, start_ft=start["start_ft"])
        for h in hgl_rows:
            h["q_check_cfs"] = round(h.pop("q_cfs"), 3)
        check = {"aep_pct": check_aep_pct, "intensity_in_hr": round(i_check, 3), "start": start, "runs": hgl_rows,
                 "ok": all(h["ok"] is not False for h in hgl_rows), "basis": "1104.3.2"}
    else:
        check = {"aep_pct": check_aep_pct, "runs": [], "ok": None, "basis": "1104.3.2", "note": "a run could not be sized"}
    return {"design_aep_pct": design_aep_pct, "zone": zone, "runs": rows, "hgl": check, "basis": "1104.4",
            "edition": "July 2026"}
