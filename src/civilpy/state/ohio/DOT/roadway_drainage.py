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
    widths (:func:`ditch_check`), a ditch run reach by reach with CDSS's
    time-of-flow rule (:func:`analyze_ditch`; CDSS's lining / 0.040 n pair
    by default, one n for both storms as an option; trapezoid, V or round
    bottom (:class:`CircularChannel`); an optional lining progression that
    re-runs the shear storm with each rougher lining), the CB-2-2-A window
    weir, depressed median
    catch basin spacing (1102.3.6).

Pavement (1103)
    design storms and allowable spread by facility (Table 1103-1), the gutter
    equation ``Q = 0.56 Z S^1/2 Y^8/3 / n`` straight and composite (1103.4),
    gutter flow areas and travel time at 0.75 Q / A, grate / curb-opening
    interception on grade with the July 2026 corrected equations (1103.5.2),
    sag grates and windows (1103.6, HEC-22 coefficients, :func:`sag_depth`),
    scupper efficiency ``1 - (1 - W/T)^2.67`` and bridge-end treatment
    (1103.8), slotted drains (1103.9), the Figure 1103-1 local depressions,
    an inlet-spacing walk along a continuous grade (:func:`space_inlets`) and
    a run of given inlets element by element with the time-of-concentration
    loop and sags (:func:`analyze_inlet_run`, the layout of CDSS's Inlet
    Spacing).

Storm sewers (1104)
    just-full (0.938 D) sizing at 10 % AEP working downstream with the
    rational method (:func:`design_storm_sewer`), n 0.015 / 0.013, minimum
    12 / 15 in, 3 fps cleansing and 10 fps / 4:1 limits, cover and access
    spacing, single chains or branched systems, inverts or crowns given, and
    the 4 % AEP hydraulic grade line worked upstream from the outlet starting
    at the higher of tailwater and ``(dc + D) / 2`` (:func:`hydraulic_grade_line`),
    with junctions at the higher of normal depth and ``(dc + D) / 2`` and the
    intensity re-taken where the HGL is repositioned (ODOT OHE, October 2026;
    CDSS 1.0.0.3's ``(dc + D) / 2``-only rule as an option), checked against
    12 in below the pavement edge (ditch sections) or the grate elevation
    (curbed).

The analyzers take the rainfall as a zone (Figure 1101-2) or as functions
of duration (:func:`idf.intensity_function`, :func:`idf.idf_curve`), so a
tool with its own rainfall table runs the same calculation.  Standard-drawing
dimensions (grate lengths, window lengths, open areas) are inputs here as
:class:`InletBasin` - take them from the Hydraulic SCDs (:data:`CB_6` is
built in).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

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


@dataclass(frozen=True)
class CircularChannel:
    """A round-bottomed ditch: a circular segment of radius r, flowing up to
    2 r deep."""
    radius_ft: float

    def _g(self, y):
        return circle_section(2.0 * self.radius_ft, y)

    def area(self, y):
        return self._g(y)["area"]

    def top_width(self, y):
        return self._g(y)["top_width"]

    def wetted_perimeter(self, y):
        return self._g(y)["perimeter"]

    def hydraulic_radius(self, y):
        return self._g(y)["rh"]


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


N_METHODS = ("single", "cdss")
CDSS_DEPTH_N = 0.040                 # ODOT CDSS: the depth storm's n (velocity / shear storm: the lining's n)


def ditch_n(lining: str = "seeded", *, n_method: str = "cdss", depth_n: float = CDSS_DEPTH_N) -> dict:
    """Manning's n for the two ditch storms.  ``cdss`` (default; how ODOT
    CDSS works - the 0.040 is built into the program, not an input): the
    lining n for the velocity / shear storm, ``depth_n`` (0.040, or the
    lining n if higher) for the depth storm - stability checked smooth,
    capacity checked rough.  ``single``: the Table 1102-2 lining n for both."""
    if n_method not in N_METHODS:
        raise ValueError(f"n_method must be one of {N_METHODS}")
    n = LINING_N[lining]
    return {"shear": n, "depth": max(n, depth_n) if n_method == "cdss" else n}


def ditch_check(q_depth_cfs: float, q_shear_cfs: float, section: Trapezoid, slope: float, *, lining: str = "seeded",
                pavement_edge_above_flowline_ft: float | None = None, bank_height_ft: float | None = None,
                n_method: str = "cdss", depth_n: float = CDSS_DEPTH_N, **lining_kw) -> dict:
    """1102.3.1 / 1102.3.2 at one ditch checkpoint: normal depth at the depth
    storm against 1 ft below the pavement edge (and the bank in toe-of-slope
    ditches), shear at the shear storm against the lining, the lining that
    would pass and its width.  ``lining`` names a Table 1102-2 entry for n;
    ``n_method`` picks CDSS's pair (default) or one n for both storms
    (:func:`ditch_n`)."""
    ns = ditch_n(lining, n_method=n_method, depth_n=depth_n)
    n = ns["shear"]
    y = normal_depth(q_depth_cfs, section, ns["depth"], slope)
    y_s = normal_depth(q_shear_cfs, section, n, slope)
    tau = shear_stress(y_s, slope)
    v = q_depth_cfs / section.area(y) if y > 0 else 0.0
    out = {"depth_ft": round(y, 3), "velocity_fps": round(v, 2), "top_width_ft": round(section.top_width(y), 2),
           "shear_depth_ft": round(y_s, 3), "shear_lb_sqft": round(tau, 3), "n": n, "depth_n": ns["depth"],
           "n_method": n_method, "basis": "1102.3.1 / 1102.3.2", "flags": []}
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


def _ditch_storm(sec, ca, start, n, slope, length_ft, intensity, max_depth_ft):
    """One storm on one reach (CDSS's time-of-flow rule): the velocity at the
    flow from the start-time intensity sets the travel time, not iterated;
    i, Q, depth, velocity and shear are then at the arrival time."""
    q0 = ca * intensity(start)
    y0 = normal_depth(q0, sec, n, slope, y_max_ft=max_depth_ft)
    v0 = q0 / sec.area(y0) if y0 > 0 else 0.0
    t = start + (idf.travel_minutes(length_ft, v0) if v0 > 0 else 0.0)
    i = intensity(t)
    q = ca * i
    y = normal_depth(q, sec, n, slope, y_max_ft=max_depth_ft)
    return {"n": n, "start_min": start, "time_min": t, "intensity_in_hr": i, "q_cfs": q, "depth_ft": y,
            "velocity_fps": q / sec.area(y) if y > 0 else 0.0, "shear_lb_sqft": shear_stress(y, slope),
            "top_width_ft": sec.top_width(y)}


def analyze_ditch(reaches: list, *, zone: str | None = None, depth_aep_pct: float | None = None,
                  shear_aep_pct: float | None = None, lining: str = "seeded", n_method: str = "cdss",
                  depth_n: float = CDSS_DEPTH_N, default_tc_min: float = idf.MIN_TC_DITCH_MIN, intensity: dict | None = None,
                  start_min: float = 0.0, progression: list | None = None, max_depth_ft: float = 20.0,
                  round_output: bool = True) -> dict:
    """A ditch run reach by reach, top down, as ODOT CDSS's Ditch Analysis.

    ``reaches`` each ``{name?, length_ft, slope, c, area_acres, tc_min?,
    inflows?, lining?, pavement_edge_above_flowline_ft?, bank_height_ft?}``
    with the section as ``bottom_ft, z_left, z_right`` (:class:`Trapezoid`)
    or ``section`` (any object with ``area(y)``, ``hydraulic_radius(y)`` and
    ``top_width(y)``, e.g. :class:`CircularChannel`).  CA accumulates down
    the run.  ``inflows`` are concentrated flows entering at the reach's
    upstream end (CDSS "Concent" lines), each ``{c, area_acres, tc_min}``:
    their CA is added and the reach cannot start before their tc.  Each
    storm (shear / velocity and depth) is carried down on its own, from
    ``start_min``: a reach starts at the later of its own ``tc_min``
    (``default_tc_min`` when absent or zero) and that storm's arrival from
    the reach above; travel = L / (60 V0) with V0 the velocity at the flow
    from the intensity at the start time (CDSS does not iterate it to the
    arrival time - OHE, October 2026); i, Q, depth, velocity, shear and top
    width are then at the arrival time.  The storms come from Figure 1101-2
    (``zone``, ``depth_aep_pct``, ``shear_aep_pct`` - the designer's choice;
    :func:`ditch_design_aeps` gives the 1102.3.1 pair) or ``intensity`` =
    ``{"shear": i(t), "depth": i(t)}``.

    Without ``progression`` each reach is checked with :func:`ditch_check`
    at the two arrival flows, ``n_method`` as in :func:`ditch_n`.  With
    ``progression`` - an ordered list of ``{name, n, allowable_lb_sqft}``,
    softest first (a reach may carry its own) - the shear storm runs with
    the first lining and, while its shear passes the lining's allowable, again
    with the next, one trial each (CDSS's lining progression); the depth
    storm then runs at the higher of the final lining's n and ``depth_n``
    (OHE: 0.040, or the rock channel protection's 0.060) with ``n_method``
    ``cdss``, at the final lining's n with ``single``."""
    if intensity is None:
        if zone is None or depth_aep_pct is None or shear_aep_pct is None:
            raise ValueError("give zone, depth_aep_pct and shear_aep_pct (Figure 1101-2), or intensity")
        intensity = {"shear": idf.intensity_function(zone, shear_aep_pct), "depth": idf.intensity_function(zone, depth_aep_pct)}
    rnd = _rounder(round_output)

    def show(st, aep):
        return {"aep_pct": aep, "n": st["n"], "start_min": rnd(st["start_min"], 2), "time_min": rnd(st["time_min"], 2),
                "intensity_in_hr": rnd(st["intensity_in_hr"], 3), "q_cfs": rnd(st["q_cfs"], 3), "depth_ft": rnd(st["depth_ft"], 3),
                "velocity_fps": rnd(st["velocity_fps"], 2), "shear_lb_sqft": rnd(st["shear_lb_sqft"], 3),
                "top_width_ft": rnd(st["top_width_ft"], 2), **({"lining": st["lining"]} if "lining" in st else {})}

    out, ca = [], 0.0
    arrival = {"shear": start_min, "depth": start_min}
    aeps = {"shear": shear_aep_pct, "depth": depth_aep_pct}
    for r in reaches:
        inflows = r.get("inflows") or []
        ca += r["c"] * r["area_acres"] + sum(f["c"] * f["area_acres"] for f in inflows)
        sec = r.get("section") or Trapezoid(r["bottom_ft"], r["z_left"], r["z_right"])
        own_tc = max([r.get("tc_min") or default_tc_min] + [f.get("tc_min") or 0.0 for f in inflows])
        starts = {k: max(own_tc, arrival[k]) for k in ("shear", "depth")}
        prog = r.get("progression", progression)
        if prog:
            trials, k = [], 0
            while True:
                lin = prog[k]
                st = _ditch_storm(sec, ca, starts["shear"], lin["n"], r["slope"], r["length_ft"], intensity["shear"], max_depth_ft)
                st["lining"] = lin["name"]
                trials.append(st)
                if st["shear_lb_sqft"] > lin["allowable_lb_sqft"] and k + 1 < len(prog):
                    k += 1
                    continue
                break
            final = prog[k]
            n_d = max(final["n"], depth_n) if n_method == "cdss" else final["n"]
            dst = _ditch_storm(sec, ca, starts["depth"], n_d, r["slope"], r["length_ft"], intensity["depth"], max_depth_ft)
            dst["lining"] = final["name"]
            shear = trials[-1]
            flags = []
            if shear["shear_lb_sqft"] > final["allowable_lb_sqft"]:
                flags.append(f"shear {shear['shear_lb_sqft']:.2f} lb/sq ft over the last lining's allowable "
                             f"{final['allowable_lb_sqft']:g} ({final['name']})")
            edge = r.get("pavement_edge_above_flowline_ft")
            if edge is not None and dst["depth_ft"] > edge - DITCH_FREEBOARD_BELOW_PAVEMENT_FT:
                flags.append(f"depth {dst['depth_ft']:.2f} ft exceeds {edge - DITCH_FREEBOARD_BELOW_PAVEMENT_FT:.2f} ft "
                             "(1 ft below the pavement edge) - catch basin or deeper ditch")
            if r.get("bank_height_ft") is not None and dst["depth_ft"] > r["bank_height_ft"]:
                flags.append(f"depth {dst['depth_ft']:.2f} ft overtops the {r['bank_height_ft']:.2f} ft ditch bank (1102.3.1)")
            if dst["depth_ft"] >= max_depth_ft - 1e-6:
                flags.append(f"depth reached the {max_depth_ft:g} ft limit of the calculation")
            storms = {"shear": show(shear, aeps["shear"]), "depth": show(dst, aeps["depth"]),
                      "shear_trials": [show(t, aeps["shear"]) for t in trials]}
            arrival = {"shear": shear["time_min"], "depth": dst["time_min"]}
            out.append({"name": r.get("name"), "ca_acres": rnd(ca, 4), "lining": final["name"], "storms": storms,
                        "check": {"flags": flags, "lining_required": {"lining": final["name"],
                                                                      "allowable_lb_sqft": final["allowable_lb_sqft"]}}})
            continue
        rl = r.get("lining", lining)
        ns = ditch_n(rl, n_method=n_method, depth_n=depth_n)
        storms = {}
        for key in ("shear", "depth"):
            st = _ditch_storm(sec, ca, starts[key], ns[key], r["slope"], r["length_ft"], intensity[key], max_depth_ft)
            storms[key] = show(st, aeps[key])
            arrival[key] = st["time_min"]
        chk = ditch_check(storms["depth"]["q_cfs"], storms["shear"]["q_cfs"], sec, r["slope"], lining=rl,
                          pavement_edge_above_flowline_ft=r.get("pavement_edge_above_flowline_ft"),
                          bank_height_ft=r.get("bank_height_ft"), n_method=n_method, depth_n=depth_n)
        out.append({"name": r.get("name"), "ca_acres": rnd(ca, 4), "storms": storms, "check": chk})
    return {"zone": zone, "n_method": n_method, "reaches": out, "basis": "1102.3", "edition": "July 2026"}


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


#: Gutter travel time at 0.75 x the full-flow gutter velocity Q / A (ODOT Office of Hydraulic Engineering,
#: October 2026 - the factor ODOT's CDSS has always used).
GUTTER_VELOCITY_FACTOR = 0.75


def gutter_area(y_ft: float, sx: float) -> float:
    """Flow area of a triangular gutter at depth Y at the curb: Y^2 / (2 Sx)."""
    return y_ft * y_ft / (2.0 * sx) if y_ft > 0 else 0.0


def composite_gutter_area(y_ft: float, *, gutter_width_ft: float, sw: float, sx: float) -> float:
    """Flow area of a composite gutter (1103.4 section): the gutter strip of
    width W at Sw, then the pavement at Sx beyond it."""
    if y_ft <= 0:
        return 0.0
    if y_ft <= gutter_width_ft * sw:
        return gutter_area(y_ft, sw)
    y1 = y_ft - gutter_width_ft * sw
    return 0.5 * (y_ft + y1) * gutter_width_ft + gutter_area(y1, sx)


def gutter_travel_minutes(length_ft: float, q_cfs: float, area_sqft: float, *,
                          velocity_factor: float = GUTTER_VELOCITY_FACTOR) -> float:
    """Travel time along a gutter (min): L / (factor x Q / A) / 60."""
    if length_ft <= 0:
        return 0.0
    if q_cfs <= 0 or area_sqft <= 0:
        return math.inf
    return length_ft / (velocity_factor * q_cfs / area_sqft) / 60.0


def side_capture_fraction(a_ft: float, y2_ft: float, l_ft: float, la_ft: float, *, min_fraction: float = 0.0) -> float:
    """1103.5.2 (July 2026): the fraction of the flow beside the grate / window
    intercepted by an opening of length L when La is the length for 100 %:
    ``[(A/Y2 + 1)^2.5 - (A/Y2 + 1 - L/La)^2.5] / [(A/Y2 + 1)^2.5 - (A/Y2)^2.5]``.
    ``min_fraction`` floors the result (some programs never let an inlet take
    less than a set share of the flow beside it)."""
    if y2_ft <= 0 or la_ft <= 0:
        return 0.0
    r = l_ft / la_ft
    if r >= 1.0:
        return 1.0
    k = a_ft / y2_ft
    num = (k + 1.0) ** 2.5 - (k + 1.0 - r) ** 2.5
    den = (k + 1.0) ** 2.5 - k ** 2.5
    f = num / den if den > 0 else 0.0
    return min(max(f, min_fraction, 0.0), 1.0)


_side_capture_ratio = side_capture_fraction


def capture_per_foot(a_ft: float, y_ft: float) -> float:
    """Qa / La = 0.7 (A + Y)^1.5 (1 - (1 - Y / (A + Y))^2.5) (1103.5.2): the
    flow one foot of opening takes, depth Y at the opening, local depression A."""
    if y_ft <= 0 or a_ft + y_ft <= 0:
        return 0.0
    return 0.7 * (a_ft + y_ft) ** 1.5 * (1.0 - (1.0 - y_ft / (a_ft + y_ft)) ** 2.5)


def opening_capture_length(q_side_cfs: float, a_ft: float, y_ft: float) -> float:
    """La: the opening length that takes all of ``q_side_cfs`` (1103.5.2)."""
    if y_ft <= 0 or q_side_cfs <= 0:
        return 0.0
    per_ft = capture_per_foot(a_ft, y_ft)
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


# ── an inlet run, element by element (1103.3-1103.6) ──────────────────────

@dataclass(frozen=True)
class InletBasin:
    """A catch basin or curb / barrier inlet as the inlet analysis sees it.

    ``grate_width_ft`` is the grate's width across the flow (0 for a curb or
    barrier window with no grate counted); ``length_ft`` is the grate or
    window length along the curb.  In a sag the grate takes weir flow over
    ``perimeter_ft`` (default 2 x width + length - the curb side takes none)
    and orifice flow through ``open_area_sqft``; a window uses
    ``window_height_ft``.  ``grate_cross_slope`` is the grate's own slope
    across the gutter (Figure 1103-1; 0 = flush with the pavement)."""

    name: str
    grate_width_ft: float = 0.0
    length_ft: float = 0.0
    open_area_sqft: float | None = None
    perimeter_ft: float | None = None
    window_height_ft: float | None = None
    grate_cross_slope: float | None = None
    source: str = ""

    @property
    def has_grate(self) -> bool:
        return self.grate_width_ft > 0

    @property
    def weir_length_ft(self) -> float:
        return self.perimeter_ft if self.perimeter_ft is not None else 2.0 * self.grate_width_ft + self.length_ft


#: SCD CB-6 (2024-07-19): 35-1/4 in x 17-3/4 in grate, long side along the curb, 60 slots 5/8 in x 4-1/2 in.
CB_6 = InletBasin("CB-6", grate_width_ft=17.75 / 12.0, length_ft=35.25 / 12.0, open_area_sqft=60 * 0.625 * 4.5 / 144.0,
                  grate_cross_slope=0.0, source="SCD CB-6 (2024-07-19); local depression A 1-1/4 in (Figure 1103-1)")

SAG_WINDOW_WEIR_C = 3.0               # HEC-22 Eq. 4-31, curb opening in a sag, weir (depth up to the opening height)
SAG_WINDOW_ORIFICE_C = 0.67           # HEC-22 Eq. 4-32, orifice (depth over 1.4 x the opening height)
SAG_WINDOW_ORIFICE_FROM = 1.4         # x the opening height


def _depth_for(flow: Callable[[float], float], q_cfs: float, *, y_max_ft: float = 50.0, tol_ft: float = 1e-7) -> float:
    """The depth at which an increasing ``flow(y)`` reaches ``q_cfs`` (bisection)."""
    if q_cfs <= 0:
        return 0.0
    lo, hi = 0.0, 0.5
    while flow(hi) < q_cfs:
        lo, hi = hi, 2.0 * hi
        if hi > y_max_ft:
            return y_max_ft
    while hi - lo > tol_ft:
        mid = 0.5 * (lo + hi)
        if flow(mid) < q_cfs:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def sag_depth(q_cfs: float, *, weir_q: Callable[[float], float], orifice_q: Callable[[float], float],
              weir_limit_ft: float = SAG_WEIR_DEPTH_LIMIT_FT, orifice_from_ft: float | None = None) -> dict:
    """Ponded depth at which a sag inlet passes ``q_cfs``: weir flow
    (``weir_q(depth)``) up to ``weir_limit_ft`` (0.4 ft for grates, 1103.6),
    orifice flow (``orifice_q(depth)``) from ``orifice_from_ft`` up, and a
    straight line in Q between the two depths (HEC-22's transition).  With no
    ``orifice_from_ft`` the orifice takes over at the weir limit (1103.6)."""
    if q_cfs <= 0:
        return {"depth_ft": 0.0, "regime": "dry"}
    y_w = _depth_for(weir_q, q_cfs)
    if y_w <= weir_limit_ft:
        return {"depth_ft": y_w, "regime": "weir"}
    top = weir_limit_ft if orifice_from_ft is None else orifice_from_ft
    y_o = _depth_for(orifice_q, q_cfs)
    if top <= weir_limit_ft:
        return {"depth_ft": max(y_o, weir_limit_ft), "regime": "orifice"}
    if y_o >= top:
        return {"depth_ft": y_o, "regime": "orifice"}
    qw, qo = weir_q(weir_limit_ft), orifice_q(top)
    return {"depth_ft": weir_limit_ft + (q_cfs - qw) / (qo - qw) * (top - weir_limit_ft), "regime": "transition"}


def ponded_spread(depth_ft: float, *, sx: float, sw: float | None = None, gutter_width_ft: float = 0.0,
                  depression_ft: float = 0.0) -> float:
    """Spread of water ponded ``depth_ft`` deep at an inlet with local
    depression ``depression_ft``: the normal gutter section's top width at
    ``depth - depression`` (1103.6)."""
    y = max(depth_ft - depression_ft, 0.0)
    if gutter_width_ft > 0 and sw and abs(sw - sx) > 1e-12:
        return y / sw if y <= gutter_width_ft * sw else gutter_width_ft + (y - gutter_width_ft * sw) / sx
    return y / sx


def sag_inlet(basin: InletBasin, q_cfs: float, el: dict) -> dict:
    """The default sag check for :func:`analyze_inlet_run`: a grate by 1103.6
    (weir over the grate edge to 0.4 ft, the whole open area as an orifice
    above, HEC-22 coefficients), a window by HEC-22 Eqs. 4-31 / 4-32 (weir to
    the opening height, orifice from 1.4 x it, straight line between), and
    the spread from :func:`ponded_spread`."""
    if basin.has_grate:
        if not basin.open_area_sqft:
            raise ValueError(f"{basin.name}: a grate in a sag needs open_area_sqft")
        r = sag_depth(q_cfs, weir_q=lambda y: SAG_WEIR_C * basin.weir_length_ft * y ** 1.5,
                      orifice_q=lambda y: SAG_ORIFICE_C * basin.open_area_sqft * math.sqrt(2 * G * y))
    else:
        h = basin.window_height_ft
        if not h or basin.length_ft <= 0:
            raise ValueError(f"{basin.name}: a window in a sag needs length_ft and window_height_ft")
        r = sag_depth(q_cfs, weir_q=lambda y: SAG_WINDOW_WEIR_C * basin.length_ft * y ** 1.5,
                      orifice_q=lambda y: SAG_WINDOW_ORIFICE_C * h * basin.length_ft * math.sqrt(2 * G * max(y - h / 2.0, 0.0)),
                      weir_limit_ft=h, orifice_from_ft=SAG_WINDOW_ORIFICE_FROM * h)
    r["spread_ft"] = ponded_spread(r["depth_ft"], sx=el["sx"], sw=el.get("sw"), gutter_width_ft=el.get("gutter_width_ft") or 0.0,
                                   depression_ft=el.get("depression_ft") or 0.0)
    return r


def _time_consistent_depth(flow, area, q_at, tc_min, length_ft, velocity_factor):
    """Depth y at which the gutter's own flow equals the flow arriving at
    ``tc + gutter time(y)`` - the time-of-concentration loop of an inlet: a
    deeper flow travels faster, so less time passes, the intensity rises.
    Returns (y, gutter time)."""
    def tg(y):
        return gutter_travel_minutes(length_ft, flow(y), area(y), velocity_factor=velocity_factor)
    hi = _depth_for(flow, q_at(tc_min))                 # no gutter time: the largest flow
    lo = 0.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if flow(mid) < q_at(tc_min + tg(mid)):
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-8:
            break
    y = 0.5 * (lo + hi)
    t = tg(y)
    return y, (t if math.isfinite(t) else 0.0)


INLET_KINDS = ("start", "inlet", "sag_side", "sag")


def analyze_inlet_run(elements: list, *, intensity: Callable[[float], float], min_time_min: float = idf.MIN_TC_PAVEMENT_MIN,
                      velocity_factor: float = GUTTER_VELOCITY_FACTOR,
                      overland: Callable[[float, float, float], float] = idf.overland_flow_chart_minutes,
                      sag: Callable[[InletBasin, float, dict], dict] = sag_inlet, min_capture_fraction: float = 0.0,
                      allowable_spread_ft: float | None = None, allowable_depth_ft: float | None = None) -> dict:
    """Catch basins and inlets along a curbed pavement, element by element
    down the gutter (1103.3-1103.6) - the layout of ODOT CDSS's Inlet Spacing.

    ``elements`` in order, each a dict:

    * ``kind``: ``"start"`` (top of a gutter run: bypass resets), ``"inlet"``
      (on a continuous grade), ``"sag_side"`` (the end of one side of a sag:
      its flow is held for the sag) or ``"sag"`` (the low point: the inlet
      takes its own flow plus the held flow);
    * ``station_ft``; ``gutter_length_ft`` (default: the distance from the
      element above);
    * ``basin``: :class:`InletBasin`; ``depression_ft``: the local depression
      at the opening (Figure 1103-1, A for grates, B for windows);
    * ``s`` (longitudinal slope), ``sx`` (pavement cross slope), optionally
      ``sw`` and ``gutter_width_ft`` for a composite gutter, ``n_gutter`` /
      ``n_pavement`` (:data:`GUTTER_N`);
    * the flow: ``c`` and ``area_acres`` (rational method), or ``q_cfs`` (a
      flow entered as is, no rainfall); the bypass of the inlet above is
      added either way;
    * time of concentration: ``tc_min``, or ``overland`` as ``{c, length_ft,
      slope_pct}`` for the ``overland`` callable (default the Figure 1101-1
      chart).

    Gutter flow and spread by 1103.4 (straight, or composite once the depth
    passes the gutter strip).  With rainfall the depth is the one at which
    the gutter's flow equals C i A + bypass with i at tc + the gutter travel
    time at that depth (``velocity_factor`` x Q / A); the duration used is
    at least ``min_time_min`` (10 minutes, 1103.3).  On grade a grate takes
    the flow over its width and the flow beside it by the 1103.5.2 window
    equations at the depth at the grate edge (:func:`capture_per_foot`,
    :func:`side_capture_fraction`); a window takes the flow by the same
    equations at the curb depth.  ``sag(basin, q, element)`` returns the sag's
    ponded ``depth_ft`` and ``spread_ft`` (default :func:`sag_inlet`)."""
    rows, bypass, held, prev_sta = [], 0.0, 0.0, None
    for el in elements:
        kind = el.get("kind", "inlet")
        if kind not in INLET_KINDS:
            raise ValueError(f"kind must be one of {INLET_KINDS}, not {kind!r}")
        sta = el.get("station_ft")
        if kind == "start":
            bypass, prev_sta = 0.0, sta
            rows.append({"station_ft": sta, "kind": "start"})
            continue
        length = el.get("gutter_length_ft") or (abs(sta - prev_sta) if sta is not None and prev_sta is not None else 0.0)
        prev_sta = sta
        basin: InletBasin = el["basin"]
        s, sx = el["s"], el["sx"]
        sw = el.get("sw") or sx
        w_gutter = el.get("gutter_width_ft") or 0.0
        ng = el.get("n_gutter") or GUTTER_N
        np_ = el.get("n_pavement") or GUTTER_N
        if not el.get("sw"):
            ng = np_                                   # one cross slope: the pavement's n
        a_dep = el.get("depression_ft") or 0.0
        can_compose = w_gutter > 0 and abs(sw - sx) > 1e-12

        def flow_straight(y):
            return gutter_flow(y, sw, s, ng)

        def flow_comp(y):
            return composite_gutter_flow(y, gutter_width_ft=w_gutter, sw=sw, sx=sx, s=s, n_gutter=ng, n_pavement=np_)["q_cfs"]

        def area_straight(y):
            return gutter_area(y, sw)

        def area_comp(y):
            return composite_gutter_area(y, gutter_width_ft=w_gutter, sw=sw, sx=sx)

        bypass_in = bypass
        if el.get("q_cfs"):
            tc = tg = 0.0
            i = time_used = None
            q = el["q_cfs"] + bypass_in
            y = _depth_for(flow_straight, q)
            composite = can_compose and y >= w_gutter * sw
            if composite:
                y = _depth_for(flow_comp, q)
        else:
            ca = (el.get("c") or 0.0) * (el.get("area_acres") or 0.0)
            if el.get("tc_min"):
                tc = el["tc_min"]
            elif el.get("overland"):
                o = el["overland"]
                tc = overland(o["c"], o["length_ft"], o["slope_pct"])
            else:
                tc = 0.0

            def q_at(t):
                return ca * intensity(t) + bypass_in
            y, tg = _time_consistent_depth(flow_straight, area_straight, q_at, tc, length, velocity_factor)
            composite = can_compose and y >= w_gutter * sw
            if composite:
                y, tg = _time_consistent_depth(flow_comp, area_comp, q_at, tc, length, velocity_factor)
            time_used = max(tc + tg, min_time_min)
            i = intensity(time_used)
            q = ca * i + bypass_in
            if tc + tg < min_time_min:
                y = _depth_for(flow_comp if composite else flow_straight, q)
        spread = w_gutter + (y - w_gutter * sw) / sx if composite else y / sw
        row = {"station_ft": sta, "kind": kind, "basin": basin.name, "gutter_length_ft": length, "c": el.get("c"),
               "area_acres": el.get("area_acres"), "tc_min": tc, "gutter_time_min": tg, "time_min": time_used,
               "intensity_in_hr": i, "bypass_in_cfs": bypass_in, "q_cfs": q, "depth_ft": y, "spread_ft": spread,
               "composite": composite, "flags": []}

        if kind == "sag":
            total = q + held
            r = sag(basin, total, el)
            row.update(sag={"total_cfs": total, **r}, intercepted_cfs=q, bypass_cfs=0.0)
            bypass, held = 0.0, 0.0
        else:
            w = basin.grate_width_ft
            if basin.has_grate:
                if composite and w > w_gutter:
                    f0 = y - w_gutter * sw - (w - w_gutter) * sx
                    beside = gutter_flow(f0, sx, s, np_) if f0 > 0 else 0.0
                elif composite:
                    f0 = y - w * sw
                    beside = (composite_gutter_flow(f0, gutter_width_ft=w_gutter - w, sw=sw, sx=sx, s=s, n_gutter=ng,
                                                    n_pavement=np_)["q_cfs"] if f0 > 0 else 0.0)
                else:
                    f0 = y - w * sw
                    beside = gutter_flow(f0, sw, s, ng) if f0 > 0 else 0.0
                beside = min(beside, q)
                front = q - beside
                per = capture_per_foot(a_dep, f0) if f0 > 0 else 0.0
                la = beside / per if per > 0 else 0.0
                if per <= 0 or la < basin.length_ft:
                    qi = q
                else:
                    qi = front + beside * side_capture_fraction(a_dep, f0, basin.length_ft, la, min_fraction=min_capture_fraction)
                row.update(edge_depth_ft=f0, front_cfs=front)
            else:
                per = capture_per_foot(a_dep, y)
                la = q / per if per > 0 else 0.0
                if per <= 0 or la < basin.length_ft:
                    qi = q
                else:
                    qi = q * side_capture_fraction(a_dep, y, basin.length_ft, la, min_fraction=min_capture_fraction)
            qi = min(qi, q)
            row.update(required_length_ft=la, inlet_length_ft=basin.length_ft)
            if kind == "sag_side":
                held = q
                bypass = 0.0
                row.update(intercepted_cfs=None, bypass_cfs=None)
            else:
                bypass = q - qi
                row.update(intercepted_cfs=qi, bypass_cfs=bypass)
        if allowable_spread_ft and spread > allowable_spread_ft + 1e-9:
            row["flags"].append(f"spread {spread:.2f} ft over the allowable {allowable_spread_ft:g} ft (Table 1103-1)")
        if allowable_depth_ft and y > allowable_depth_ft + 1e-9:
            row["flags"].append(f"depth {y:.3f} ft over the allowable {allowable_depth_ft:g} ft")
        if "sag" in row:
            if allowable_spread_ft and row["sag"]["spread_ft"] > allowable_spread_ft + 1e-9:
                row["flags"].append(f"sag spread {row['sag']['spread_ft']:.2f} ft over the allowable {allowable_spread_ft:g} ft")
            if allowable_depth_ft and row["sag"]["depth_ft"] > allowable_depth_ft + 1e-9:
                row["flags"].append(f"ponded depth {row['sag']['depth_ft']:.3f} ft over the allowable {allowable_depth_ft:g} ft")
        rows.append(row)
    return {"rows": rows, "velocity_factor": velocity_factor, "min_time_min": min_time_min, "basis": "1103.3-1103.6"}


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


HGL_METHODS = ("ohe", "cdss", "single_intensity")


def flowing_full(q_cfs: float, d_in: float, slope: float, n: float | None = None, *, full_q_ratio: float | None = None) -> bool:
    """Whether a run counts as flowing full: Q over its just-full capacity
    (1104.3.1), or, with ``full_q_ratio``, Q at or over that multiple of its
    flowing-full capacity (ODOT keeps CDSS's switch to Q / A full within
    about 1 % of just-full - OHE, October 2026)."""
    if q_cfs <= 0:
        return False
    if slope <= 0:
        return True
    if full_q_ratio is not None and q_cfs >= full_q_ratio * full_flow_q(d_in, slope, n):
        return True
    return normal_depth_circular(q_cfs, d_in, slope, n) is None


def flow_depth(q_cfs: float, d_in: float, slope: float, n: float | None = None, *, full_q_ratio: float | None = None) -> float:
    """Normal depth of the run, or the diameter when it counts as flowing full (:func:`flowing_full`)."""
    if q_cfs <= 0:
        return 0.0
    if flowing_full(q_cfs, d_in, slope, n, full_q_ratio=full_q_ratio):
        return d_in / 12.0
    return normal_depth_circular(q_cfs, d_in, slope, n)


def mean_velocity(q_cfs: float, d_in: float, slope: float, n: float | None = None, *, full_q_ratio: float | None = None) -> float:
    """Mean velocity at the design flow: the normal-depth velocity while the
    pipe runs part full, Q / A full once it counts as flowing full
    (:func:`flowing_full`) - what ODOT CDSS prints and uses for pipe travel
    time."""
    if q_cfs <= 0:
        return 0.0
    if flowing_full(q_cfs, d_in, slope, n, full_q_ratio=full_q_ratio):
        return q_cfs / (math.pi * (d_in / 24.0) ** 2)
    return q_cfs / circle_section(d_in / 12.0, normal_depth_circular(q_cfs, d_in, slope, n))["area"]


def junction_hgl(*, downstream_hgl_ft: float, invert_down_ft: float, d_in: float, q_cfs: float, slope: float,
                 n: float | None = None, method: str = "ohe", full_q_ratio: float | None = None) -> dict:
    """HGL at the downstream end of a run, where it leaves a junction whose HGL is ``downstream_hgl_ft``.

    ``ohe`` (default; ODOT Office of Hydraulic Engineering, October 2026):
    the higher of the junction HGL and the run's flow line + the higher of
    normal depth (the diameter when flowing full) and (dc + D) / 2 - raised
    ("repositioned") when that stands above the junction's.
    ``cdss`` (ODOT CDSS 1.0.0.3, as its printouts show): (dc + D) / 2 only -
    normal depth never repositions it; for re-checking a CDSS design.
    ``single_intensity``: flow line + yn, or + D when the run is over its
    just-full capacity."""
    d = d_in / 12.0
    yn = normal_depth_circular(q_cfs, d_in, slope, n) if slope > 0 else None
    half = invert_down_ft + 0.5 * (critical_depth_circular(q_cfs, d_in) + d)
    if method == "cdss":
        own = half
    elif method == "ohe":
        own = max(half, invert_down_ft + flow_depth(q_cfs, d_in, slope, n, full_q_ratio=full_q_ratio))
    else:
        own = invert_down_ft + (yn if yn is not None else d)
    return {"hgl_ft": max(downstream_hgl_ft, own), "own_ft": own, "repositioned": own > downstream_hgl_ft + 1e-9,
            "normal_depth_ft": yn}


def _hgl_run(r: dict, start_ft: float, method: str, full_q_ratio: float | None = None, round_output: bool = True) -> dict:
    """One run of the HGL from the HGL at its downstream junction."""
    d_in, q, length = r["d_in"], r["q_cfs"], r["length_ft"]
    d = d_in / 12.0
    n = r.get("n") or sewer_n(d_in)
    slope = (r["invert_up_ft"] - r["invert_down_ft"]) / length if length else 0.0
    sf = friction_slope(q, d_in, n)
    j = junction_hgl(downstream_hgl_ft=start_ft, invert_down_ft=r["invert_down_ft"], d_in=d_in, q_cfs=q, slope=slope, n=n,
                     method=method, full_q_ratio=full_q_ratio)
    yn, hgl_down = j["normal_depth_ft"], j["hgl_ft"]
    hgl_up = hgl_down + sf * length                      # full: along the friction slope
    if yn is not None:
        hgl_up = max(hgl_up, r["invert_up_ft"] + yn)    # a steep run drains to normal depth
    elif method in ("cdss", "ohe"):
        hgl_up = max(hgl_up, r["invert_up_ft"] + d)     # over capacity: flowing full, at least the crown
    regime = "pressure" if hgl_up > r["invert_up_ft"] + d else "open channel"
    limit = r.get("limit_ft")
    rnd = _rounder(round_output)
    return {**{k: r[k] for k in ("q_cfs", "d_in", "length_ft", "invert_down_ft", "invert_up_ft")}, "n": n,
            "slope": rnd(slope, 5), "friction_slope": rnd(sf, 5), "normal_depth_ft": rnd(yn, 3) if yn is not None else None,
            "hgl_down_ft": rnd(hgl_down, 3), "hgl_up_ft": rnd(hgl_up, 3), "repositioned": j["repositioned"],
            "regime": regime, "limit_ft": limit, "ok": (hgl_up <= limit) if limit is not None else None, "name": r.get("name"),
            "_hgl_up": hgl_up}


def _rounder(round_output: bool):
    return (lambda x, k: round(x, k)) if round_output else (lambda x, k: x)


def hydraulic_grade_line(runs: list, *, start_ft: float, method: str = "ohe", full_q_ratio: float | None = None,
                         round_output: bool = True) -> list:
    """1104.3.2 HGL from the outlet upstream along one chain.  ``runs`` are
    ordered from the outlet run upward, each ``{q_cfs, d_in, length_ft,
    invert_down_ft, invert_up_ft, n?, limit_ft?}``.  At each run's downstream
    end the HGL is raised to the run's own water surface where that stands
    higher (:func:`junction_hgl`); full runs rise along the friction slope;
    a run steeper than its friction slope drains down to normal depth.  Each
    row carries the HGL at both ends and whether the upper end stays under
    the run's limit.  Branched systems: :func:`design_storm_sewer`."""
    if method not in HGL_METHODS:
        raise ValueError(f"method must be one of {HGL_METHODS}")
    out, hgl = [], start_ft
    for r in runs:
        row = _hgl_run(r, hgl, method, full_q_ratio, round_output)
        hgl = row.pop("_hgl_up")
        out.append(row)
    return out


def _network(runs: list) -> tuple:
    """(from, to) junction ids per run - given as ``from_junction`` /
    ``to_junction``, else a single chain in list order - the runs in
    upstream-first order, and the outlet run."""
    if any("from_junction" in r or "to_junction" in r for r in runs):
        ends = [(str(r["from_junction"]), str(r["to_junction"])) for r in runs]
    else:
        ends = [(f"J{k}", f"J{k + 1}") for k in range(len(runs))]
    starts = {}
    for k, (a, _) in enumerate(ends):
        if a in starts and a not in ("0", ""):
            raise ValueError(f"two runs leave junction {a!r}; a junction has one outgoing run")
        starts.setdefault(a, k)
    incoming = {k: [m for m, (_, b) in enumerate(ends) if b == a and m != k] for k, (a, _) in enumerate(ends)}
    for k, (a, _) in enumerate(ends):
        if a in ("0", ""):                       # CDSS: junction "0" = a structure with no pipe coming in
            incoming[k] = []
    outlets = [k for k, (_, b) in enumerate(ends) if b not in starts or b in ("0", "")]
    if len(outlets) != 1:
        raise ValueError(f"a storm sewer system needs exactly one outlet run, found {len(outlets)}")
    order, done = [], set()

    def visit(k, path=()):
        if k in done:
            return
        if k in path:
            raise ValueError("the runs form a loop")
        for m in incoming[k]:
            visit(m, path + (k,))
        done.add(k)
        order.append(k)

    for k in range(len(runs)):
        visit(k)
    return ends, incoming, order, outlets[0]


def design_storm_sewer(runs: list, *, zone: str | None = None, freeway: bool = False, design_aep_pct: float = SEWER_DESIGN_AEP,
                       check_aep_pct: float = SEWER_HGL_AEP, tailwater_ft: float | None = None, first_inlet: str = "pavement",
                       hgl_method: str = "ohe", intensity: Callable[[float], float] | None = None,
                       check_intensity: Callable[[float], float] | None = None, sizes=PIPE_SIZES_IN, min_d_in: float | None = None,
                       start_at_upstream_size: bool = False, full_q_ratio: float | None = None, round_output: bool = True) -> dict:
    """1104.4 procedure for a single chain or a branched system.

    ``runs`` each ``{name, c, area_acres (or areas=[(acres, C), ...]),
    tc_local_min, length_ft, invert_up_ft, invert_down_ft (or crown_up_ft,
    crown_down_ft - inverts follow the size chosen), slope?, d_in?, n?,
    limit_ft?, from_junction?, to_junction?}``.  A ``slope`` sets the
    downstream end from the upstream one; ``n`` replaces the 1104.3.5 value.
    Without junction ids the runs are one chain from the top structure down
    to the outlet; with them, any tree with one outlet run (junction "0" is a
    structure with no pipe coming in, as in CDSS).  Working downstream: the
    CA of every run reaching a junction is added to the local CA; tc is the
    larger of the local tc and each incoming run's tc plus its travel time;
    i from Figure 1101-2 at the design storm (or ``intensity(t)``); Q = CA i;
    the smallest size in ``sizes`` at or above ``min_d_in`` (1104.3.6 by
    ``freeway`` when not given) - and, with ``start_at_upstream_size``, at or
    above the largest pipe coming in - whose just-full capacity carries Q, or
    a given ``d_in`` held and flagged when too small (OHE: keep entered sizes);
    velocity flags and a crown-match drop for a smaller incoming pipe
    (1104.2.1 H).

    Then the 4 % AEP HGL from the outlet upward (``check_intensity(t)`` in
    place of the zone's curve).  ``hgl_method``:

    ``ohe`` (default; ODOT OHE, October 2026): pipe travel at the mean
      velocity at the design flow (:func:`mean_velocity`); the check
      intensity at the time the water reaches the outlet, held upstream and
      re-taken at a run's own arrival time wherever the HGL is repositioned
      at its downstream junction; junction HGL from :func:`junction_hgl` -
      the higher of normal depth and ``(dc + D) / 2``.
    ``cdss``: the same with CDSS 1.0.0.3's junction rule, ``(dc + D) / 2``
      only - checked run by run against its printouts; for re-checking a
      CDSS design.
    ``single_intensity``: travel at the just-full velocity, the outlet run's
      intensity at its own tc on every run, junction HGL at normal depth or
      the crown.

    ``full_q_ratio`` sets when a run counts as flowing full for its velocity
    and junction depth (:func:`flowing_full`).  ``round_output=False`` returns
    unrounded numbers."""
    if hgl_method not in HGL_METHODS:
        raise ValueError(f"hgl_method must be one of {HGL_METHODS}")
    if zone is None and (intensity is None or check_intensity is None):
        raise ValueError("give the rainfall zone (Figure 1101-2) or both intensity and check_intensity")
    i_design = intensity or idf.intensity_function(zone, design_aep_pct)
    i_check = check_intensity or idf.intensity_function(zone, check_aep_pct)
    floor = min_d_in if min_d_in is not None else min_pipe_in(freeway=freeway)
    rnd = _rounder(round_output)
    ends, incoming, order, outlet = _network(runs)
    rows = [None] * len(runs)
    arrive = {}                                   # run -> time the flow reaches its downstream end
    for k in order:
        r = runs[k]
        ups = [rows[m] for m in incoming[k]]
        if r.get("areas") is not None:
            local_a = sum(a for a, _ in r["areas"])
            local_ca = sum(a * c for a, c in r["areas"])
        else:
            local_a = r.get("area_acres", 0.0)
            local_ca = r.get("c", 0.0) * local_a
        ca = local_ca + sum(u["_ca"] for u in ups)
        a_total = local_a + sum(u["_area"] for u in ups)
        tc_local = idf.time_of_concentration(overland_min=r.get("tc_local_min", 0.0), first_inlet=None if ups else first_inlet)
        tc = max([tc_local] + [arrive[m] for m in incoming[k]])
        i = i_design(tc)
        q = ca * i
        length = r["length_ft"]

        def inverts(d_in, r=r, length=length):
            if r.get("crown_up_ft") is not None:
                up, dn = r["crown_up_ft"] - d_in / 12.0, r["crown_down_ft"] - d_in / 12.0
            else:
                up, dn = r["invert_up_ft"], r["invert_down_ft"]
            if r.get("slope"):
                dn = up - r["slope"] * length
            return up, dn

        def n_for(d_in, r=r):
            return r.get("n") or sewer_n(d_in)

        held = bool(r.get("d_in"))
        flags = []
        if held:
            d = r["d_in"]
        else:
            start = max([floor] + ([u["d_in"] for u in ups if u["d_in"]] if start_at_upstream_size else []))
            d = None
            for cand in sizes:
                if cand < start:
                    continue
                up_, dn_ = inverts(cand)
                s_ = (up_ - dn_) / length if length else 0.0
                if s_ > 0 and just_full_capacity(cand, s_, n_for(cand))["q_cfs"] >= q:
                    d = cand
                    break
            if d is None:
                flags.append(f"no size up to {sizes[-1]} in carries {q:.1f} cfs at this slope")
        inv_up, inv_dn = inverts(d if d else sizes[-1])
        slope = (inv_up - inv_dn) / length if length else 0.0
        n = n_for(d) if d else None
        if d and slope > 0:
            jf = just_full_capacity(d, slope, n)
        else:
            jf = {"q_cfs": 0.0, "velocity_fps": 0.0}
        if d:
            if slope <= 0:
                flags.append("flat or adverse slope")
            flags += velocity_flags(jf["velocity_fps"], slope) if slope > 0 else []
            if jf["q_cfs"] < q:
                flags.append(f"{'held' if held else 'largest'} {d:g} in carries {jf['q_cfs']:.2f} cfs just full, under {q:.2f} cfs")
            if held and d < floor:
                flags.append(f"held {d:g} in is below the {floor:g} in minimum (1104.3.6)")
        v_mean = mean_velocity(q, d, slope, n, full_q_ratio=full_q_ratio) if d else 0.0
        v = v_mean if hgl_method in ("cdss", "ohe") else jf["velocity_fps"]
        travel = idf.travel_minutes(length, v) if v else 0.0
        arrive[k] = tc + travel
        d_up = max([u["d_in"] for u in ups if u["d_in"]], default=None)
        if d_up is not None and d and d > d_up:
            flags.append(f"match the {d_up:g} in upstream crown to this {d:g} in crown: drop {(d - d_up) / 12:.2f} ft (1104.2.1 H)")
        if d_up is not None and d and d < d_up:
            flags.append(f"smaller than the {d_up:g} in pipe coming in")
        if d and length > access_spacing_ft(d)[1]:
            flags.append(f"run longer than the {access_spacing_ft(d)[1]} ft access spacing (1104.2.3)")
        rows[k] = {"name": r.get("name"), "from_junction": ends[k][0], "to_junction": ends[k][1],
                   "area_acres": local_a, "area_acres_total": a_total, "ca_local_acres": rnd(local_ca, 4), "ca_acres": rnd(ca, 4),
                   "tc_min": rnd(tc, 2), "intensity_in_hr": rnd(i, 3), "q_cfs": rnd(q, 3),
                   "slope": rnd(slope, 5), "length_ft": length, "invert_up_ft": inv_up, "invert_down_ft": inv_dn,
                   "d_in": d, "held": held, "n": n, "capacity_cfs": rnd(jf["q_cfs"], 3), "velocity_fps": rnd(jf["velocity_fps"], 2),
                   "mean_velocity_fps": rnd(v_mean, 2), "travel_min": rnd(travel, 2), "flags": [f for f in flags if f],
                   "limit_ft": r.get("limit_ft"), "_ca": ca, "_area": a_total}
    hgl_rows = []
    if all(x["d_in"] for x in rows):
        last = rows[outlet]
        t_check = arrive[outlet] if hgl_method in ("cdss", "ohe") else last["tc_min"]
        i0 = i_check(t_check)
        start = outlet_start_elevation(tailwater_ft=tailwater_ft, invert_ft=last["invert_down_ft"], d_in=last["d_in"],
                                       q_cfs=last["_ca"] * i0)

        def run_input(x, i):
            return {"name": x["name"], "q_cfs": x["_ca"] * i, "d_in": x["d_in"], "length_ft": x["length_ft"],
                    "invert_down_ft": x["invert_down_ft"], "invert_up_ft": x["invert_up_ft"], "n": x["n"], "limit_ft": x["limit_ft"]}

        def walk(k, junction_ft, i):
            x = rows[k]
            h = _hgl_run(run_input(x, i), junction_ft, hgl_method, full_q_ratio, round_output)
            if hgl_method in ("cdss", "ohe") and h["repositioned"] and k != outlet:
                i = i_check(arrive[k])                       # re-taken where the HGL is repositioned
                h = _hgl_run(run_input(x, i), junction_ft, hgl_method, full_q_ratio, round_output)
                h["repositioned"] = True
            up = h.pop("_hgl_up")
            h["q_check_cfs"] = rnd(h.pop("q_cfs"), 3)
            h["intensity_in_hr"] = rnd(i, 3)
            h["from_junction"], h["to_junction"] = x["from_junction"], x["to_junction"]
            hgl_rows.append(h)
            for m in incoming[k]:
                walk(m, up, i)

        walk(outlet, start["start_ft"], i0)
        check = {"aep_pct": check_aep_pct, "method": hgl_method, "intensity_in_hr": rnd(i0, 3), "time_min": rnd(t_check, 2),
                 "start": start, "runs": hgl_rows, "ok": all(h["ok"] is not False for h in hgl_rows), "basis": "1104.3.2"}
    else:
        check = {"aep_pct": check_aep_pct, "method": hgl_method, "runs": [], "ok": None, "basis": "1104.3.2",
                 "note": "a run could not be sized"}
    for x in rows:
        x.pop("_ca")
        x.pop("_area")
    return {"design_aep_pct": design_aep_pct, "zone": zone, "runs": rows, "outlet": rows[outlet]["name"], "outlet_index": outlet,
            "hgl": check, "basis": "1104.4", "edition": "July 2026"}
