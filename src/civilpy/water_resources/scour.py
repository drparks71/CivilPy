#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Bridge scour by the FHWA HEC-18 method.

Implements the local pier-scour (CSU) equation, the contraction-scour
equations (live-bed Laursen and clear-water), and the supporting critical-
velocity and correction-factor relationships from FHWA HEC-18, *Evaluating
Scour at Bridges* (5th ed., 2012).  The bed grain size these equations
need -- D50 and D95 -- is exactly what a particle-size analysis on a boring
log provides, so :func:`pier_scour_from_boring` reads it straight from a
:class:`~civilpy.geotech.boring.Borehole`.

US customary units throughout: lengths in feet, velocities in ft/s,
discharge in cubic feet per second, grain sizes in millimetres (converted
internally), angles in degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Gravitational acceleration, ft/s^2.
G_FT_S2 = 32.2
#: Millimetres per foot.
MM_PER_FT = 304.8
#: Critical-velocity coefficient Ku, English units (HEC-18 Eq. 6.1).
KU_CRITICAL_VELOCITY = 11.17
#: Clear-water contraction-scour coefficient Ku, English (HEC-18 Eq. 6.4).
KU_CLEARWATER = 0.0077

#: Pier nose shape factor K1 (HEC-18 Table 7.1).
PIER_SHAPE_K1 = {
    "square": 1.1,
    "round": 1.0,
    "cylinder": 1.0,
    "sharp": 0.9,
    "group": 1.0,
}


def froude_number(velocity_fps: float, depth_ft: float) -> float:
    """Froude number Fr = V / sqrt(g y)."""
    if depth_ft <= 0:
        raise ValueError("depth must be positive")
    return velocity_fps / math.sqrt(G_FT_S2 * depth_ft)


def critical_velocity(depth_ft: float, d50_mm: float) -> float:
    """Critical (incipient-motion) velocity Vc (ft/s) for bed material of
    median size ``d50_mm`` at flow depth ``depth_ft`` (HEC-18 Eq. 6.1):
    Vc = Ku y^(1/6) D50^(1/3), Ku = 11.17 (English), D50 in feet."""
    d50_ft = d50_mm / MM_PER_FT
    return KU_CRITICAL_VELOCITY * depth_ft ** (1.0 / 6.0) * d50_ft ** (1.0 / 3.0)


def angle_of_attack_factor(
    pier_length_ft: float, pier_width_ft: float, skew_deg: float
) -> float:
    """Flow angle-of-attack correction K2 (HEC-18 Eq. 7.2):
    K2 = (cos theta + (L/a) sin theta)^0.65."""
    theta = math.radians(skew_deg)
    ratio = pier_length_ft / pier_width_ft
    return (math.cos(theta) + ratio * math.sin(theta)) ** 0.65


def armoring_factor_k4(
    approach_velocity_fps: float,
    depth_ft: float,
    pier_width_ft: float,
    d50_mm: float,
    d95_mm: float,
) -> float:
    """Coarse-bed armoring correction K4 (HEC-18 Eqs. 7.3-7.6).

    Applies only when the bed is coarse (D50 >= 2 mm and D95 >= 20 mm);
    otherwise K4 = 1.0.  K4 = 0.4 (VR)^0.15 with a floor of 0.4, where the
    velocity ratio VR uses the approach velocity for incipient motion at
    the pier for D50 and D95.
    """
    if d50_mm < 2.0 or d95_mm < 20.0:
        return 1.0
    vc_d50 = critical_velocity(depth_ft, d50_mm)
    vc_d95 = critical_velocity(depth_ft, d95_mm)
    d50_ft = d50_mm / MM_PER_FT
    d95_ft = d95_mm / MM_PER_FT
    vic_d50 = 0.645 * (d50_ft / pier_width_ft) ** 0.053 * vc_d50
    vic_d95 = 0.645 * (d95_ft / pier_width_ft) ** 0.053 * vc_d95
    denom = vc_d50 - vic_d95
    if denom <= 0:
        return 1.0
    v_r = (approach_velocity_fps - vic_d50) / denom
    if v_r <= 0:
        return 0.4
    return max(0.4, 0.4 * v_r ** 0.15)


def pier_scour_csu(
    approach_velocity_fps: float,
    approach_depth_ft: float,
    pier_width_ft: float,
    k1: float = 1.0,
    k2: float = 1.0,
    k3: float = 1.1,
    k4: float = 1.0,
) -> float:
    """Local pier scour depth ys (ft) by the CSU equation (HEC-18 Eq. 7.1):

    ys = 2.0 K1 K2 K3 K4 y1 (a/y1)^0.65 Fr1^0.43

    K1 nose shape, K2 angle of attack, K3 bed condition (1.1 typical plane
    bed), K4 coarse-bed armoring.
    """
    fr = froude_number(approach_velocity_fps, approach_depth_ft)
    return (
        2.0 * k1 * k2 * k3 * k4 * approach_depth_ft
        * (pier_width_ft / approach_depth_ft) ** 0.65
        * fr ** 0.43
    )


def live_bed_contraction_scour(
    approach_depth_ft: float,
    approach_discharge_cfs: float,
    contracted_discharge_cfs: float,
    approach_width_ft: float,
    contracted_width_ft: float,
    existing_depth_ft: float,
    k1: float = 0.64,
) -> float:
    """Live-bed contraction scour depth ys (ft), Laursen (HEC-18 Eq. 6.2):
    y2/y1 = (Q2/Q1)^(6/7) (W1/W2)^k1, ys = y2 - y0.

    ``k1`` is the bed-transport-mode exponent (0.59-0.69; 0.64 default).
    """
    y2 = (
        approach_depth_ft
        * (contracted_discharge_cfs / approach_discharge_cfs) ** (6.0 / 7.0)
        * (approach_width_ft / contracted_width_ft) ** k1
    )
    return y2 - existing_depth_ft


def clear_water_contraction_scour(
    contracted_discharge_cfs: float,
    contracted_width_ft: float,
    d50_mm: float,
    existing_depth_ft: float,
) -> float:
    """Clear-water contraction scour depth ys (ft), Laursen (HEC-18
    Eq. 6.4): y2 = [Ku Q^2 / (Dm^(2/3) W^2)]^(3/7), Dm = 1.25 D50,
    Ku = 0.0077 (English, Dm in feet); ys = y2 - y0."""
    dm_ft = 1.25 * d50_mm / MM_PER_FT
    y2 = (
        KU_CLEARWATER * contracted_discharge_cfs ** 2
        / (dm_ft ** (2.0 / 3.0) * contracted_width_ft ** 2)
    ) ** (3.0 / 7.0)
    return y2 - existing_depth_ft


@dataclass
class PierScourResult:
    """Local pier scour with the correction factors that produced it."""

    scour_depth_ft: float
    froude: float
    k1: float
    k2: float
    k3: float
    k4: float
    d50_mm: float | None = None
    d95_mm: float | None = None


def pier_scour_from_boring(
    borehole,
    streambed_depth_ft: float,
    approach_velocity_fps: float,
    approach_depth_ft: float,
    pier_width_ft: float,
    pier_length_ft: float | None = None,
    skew_deg: float = 0.0,
    shape: str = "round",
    k3: float = 1.1,
) -> PierScourResult:
    """Local pier scour using the bed gradation from a boring log.

    Reads D50 (and D95 for armoring) from the particle-size analysis
    nearest ``streambed_depth_ft`` in ``borehole`` and applies the CSU
    equation.  K1 comes from ``shape`` (HEC-18 Table 7.1), K2 from the
    pier geometry and ``skew_deg`` when ``pier_length_ft`` is given, and K4
    from coarse-bed armoring when the gradation is coarse enough.
    """
    if shape not in PIER_SHAPE_K1:
        raise ValueError(
            f"unknown pier shape {shape!r}; choose from {sorted(PIER_SHAPE_K1)}"
        )
    k1 = PIER_SHAPE_K1[shape]
    k2 = 1.0
    if pier_length_ft is not None and skew_deg:
        k2 = angle_of_attack_factor(pier_length_ft, pier_width_ft, skew_deg)

    grading = borehole.grading_at(streambed_depth_ft)
    d50_mm = grading.d50 if grading else None
    d95_mm = grading.d_size(95) if grading else None

    k4 = 1.0
    if d50_mm is not None and d95_mm is not None:
        k4 = armoring_factor_k4(
            approach_velocity_fps, approach_depth_ft, pier_width_ft, d50_mm, d95_mm
        )

    ys = pier_scour_csu(
        approach_velocity_fps, approach_depth_ft, pier_width_ft,
        k1=k1, k2=k2, k3=k3, k4=k4,
    )
    return PierScourResult(
        scour_depth_ft=ys,
        froude=froude_number(approach_velocity_fps, approach_depth_ft),
        k1=k1, k2=k2, k3=k3, k4=k4, d50_mm=d50_mm, d95_mm=d95_mm,
    )


@dataclass
class ScourThroughStrata:
    """Design scour at one substructure unit set against a boring."""

    streambed_elev_ft: float
    degradation_ft: float
    contraction_ft: float
    local_ft: float
    total_ft: float
    unlimited_elev_ft: float             # streambed - total scour
    resistant_rock_elev_ft: float | None  # top of scour-resistant rock at the boring
    design_elev_ft: float                # unlimited, floored at resistant rock
    limited_by_rock: bool
    strata: list = field(default_factory=list)   # layers the scour passes through, top down
    notes: list = field(default_factory=list)

    @property
    def scour_depth_ft(self) -> float:
        return self.streambed_elev_ft - self.design_elev_ft


def scour_through_strata(streambed_elev_ft: float, *, contraction_ft: float, local_ft: float,
                         degradation_ft: float = 0.0, borehole=None,
                         min_rqd_pct: float = 50.0) -> ScourThroughStrata:
    """Total scour (HEC-18: long-term degradation + contraction + local) at a
    unit, carried down through the logged strata of ``borehole`` (a
    :class:`civilpy.geotech.boring.Borehole` with a collar elevation).

    The scour line stops at the top of scour-resistant rock
    (:meth:`~civilpy.geotech.boring.Layer.scour_resistant`); weak or
    weathered rock and every soil layer are scoured through.  Cohesive
    layers (silt, clay) are noted: HEC-18 lets their ultimate scour be
    reduced only from site erosion testing (time-rate analysis), so the full
    depth stands here.
    """
    total = max(degradation_ft, 0.0) + max(contraction_ft, 0.0) + max(local_ft, 0.0)
    unlimited = streambed_elev_ft - total
    notes, strata = [], []
    rock_elev = None
    if borehole is not None and getattr(borehole, "ground_elevation_ft", None) is not None and borehole.layers:
        collar = borehole.ground_elevation_ft
        top = borehole.resistant_rock_top_ft(min_rqd_pct)
        rock_elev = None if top is None else collar - top
        for lay in borehole.layers:
            z_top, z_bot = collar - lay.depth_top_ft, collar - lay.depth_bottom_ft
            lo = max(z_bot, max(unlimited, rock_elev if rock_elev is not None else -math.inf))
            hi = min(z_top, streambed_elev_ft)
            if hi > lo:
                strata.append({"group": lay.group, "label": lay.label, "top_elev_ft": round(hi, 2),
                               "bottom_elev_ft": round(lo, 2), "scour_resistant": lay.scour_resistant(min_rqd_pct)})
        if any(s["group"] in ("silt", "clay") for s in strata):
            notes.append("scour passes through cohesive layers: HEC-18 allows a reduction only from erosion "
                         "testing of those soils (time-rate) - full depth used")
        if any(s["group"] == "rock" for s in strata):
            notes.append("scour passes through weak / weathered rock, treated as erodible")
        deepest = collar - (borehole.total_depth_ft or max(lay.depth_bottom_ft for lay in borehole.layers))
        if unlimited < deepest and (rock_elev is None or rock_elev < unlimited):
            notes.append(f"scour line {unlimited:.1f} is below the bottom of the boring {deepest:.1f}")
    elif borehole is None:
        notes.append("no boring: strata unknown, scour not limited by rock")
    else:
        notes.append("boring has no collar elevation or no logged layers: scour not limited")
    limited = rock_elev is not None and rock_elev > unlimited
    design = rock_elev if limited else unlimited
    return ScourThroughStrata(streambed_elev_ft, degradation_ft, contraction_ft, local_ft, total, unlimited,
                              rock_elev, min(design, streambed_elev_ft), limited, strata, notes)
