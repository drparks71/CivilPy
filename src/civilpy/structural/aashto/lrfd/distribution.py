#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AASHTO LRFD 4.6.2.2 — approximate live-load distribution factors.

Implemented for the most common cross-section: concrete deck on steel or
precast concrete I-girders (Table 4.6.2.2.1-1 types (a), (e), (k)).  The
formulas return lanes/girder with multiple presence already embedded.

Units here follow the tables: S and de in **ft**, L in ft, ts in inches,
Kg in in^4.  Results carry the table's range-of-applicability flags in
``details`` — outside those ranges the spec requires refined analysis or
the lever rule, it does not extrapolate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from civilpy.structural.aashto.lrfd.core import article


def longitudinal_stiffness_kg(
    n_modular: float, i_girder: float, a_girder: float, e_g: float
) -> float:
    """Kg = n*(I + A*eg^2) (4.6.2.2.1-1), in^4.  ``e_g`` is the distance
    between girder and deck centroids (in); ``n_modular`` the girder/deck
    modular ratio."""
    return n_modular * (i_girder + a_girder * e_g**2)


@dataclass
class DistributionFactor:
    """A distribution factor (lanes/girder) with its applicability flags."""

    one_lane: float
    multi_lane: float
    applicability: dict = field(default_factory=dict)

    @property
    def governing(self) -> float:
        return max(self.one_lane, self.multi_lane)

    @property
    def applicable(self) -> bool:
        return all(self.applicability.values())


@article("4.6.2.2.2b", "Distribution of Live Load Moment, Interior Girders")
def moment_df_interior(
    s_ft: float,
    l_ft: float,
    t_s: float,
    k_g: float,
    n_beams: int = 4,
) -> DistributionFactor:
    """Moment DF for interior I-girders (Table 4.6.2.2.2b-1, type a/e/k):

    one lane:  0.06 + (S/14)^0.4 * (S/L)^0.3 * (Kg/(12*L*ts^3))^0.1
    multi:     0.075 + (S/9.5)^0.6 * (S/L)^0.2 * (Kg/(12*L*ts^3))^0.1
    """
    stiffness = k_g / (12.0 * l_ft * t_s**3)
    one = 0.06 + (s_ft / 14.0) ** 0.4 * (s_ft / l_ft) ** 0.3 * stiffness**0.1
    multi = 0.075 + (s_ft / 9.5) ** 0.6 * (s_ft / l_ft) ** 0.2 * stiffness**0.1
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "spacing": 3.5 <= s_ft <= 16.0,
            "slab_thickness": 4.5 <= t_s <= 12.0,
            "span": 20.0 <= l_ft <= 240.0,
            "n_beams": n_beams >= 4,
            "Kg": 10000.0 <= k_g <= 7.0e6,
        },
    )


@article("4.6.2.2.3a", "Distribution of Live Load Shear, Interior Girders")
def shear_df_interior(
    s_ft: float,
    l_ft: float = 80.0,
    t_s: float = 8.0,
    n_beams: int = 4,
) -> DistributionFactor:
    """Shear DF for interior I-girders (Table 4.6.2.2.3a-1, type a/e/k):
    one lane 0.36 + S/25; multi 0.2 + S/12 - (S/35)^2."""
    one = 0.36 + s_ft / 25.0
    multi = 0.2 + s_ft / 12.0 - (s_ft / 35.0) ** 2
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "spacing": 3.5 <= s_ft <= 16.0,
            "slab_thickness": 4.5 <= t_s <= 12.0,
            "span": 20.0 <= l_ft <= 240.0,
            "n_beams": n_beams >= 4,
        },
    )


@article("4.6.2.2.2d", "Distribution of Live Load Moment, Exterior Girders")
def moment_df_exterior(
    interior_df: DistributionFactor,
    d_e_ft: float,
    one_lane_lever_rule: float | None = None,
) -> DistributionFactor:
    """Moment DF for exterior I-girders (Table 4.6.2.2.2d-1): multi-lane
    g = e * g_interior with e = 0.77 + de/9.1; the one-lane value comes
    from the lever rule (pass it in — it depends on the actual overhang
    and wheel placement).  ``d_e_ft`` is the distance from exterior web to
    the inside face of the barrier (ft, -1.0 <= de <= 5.5)."""
    e = 0.77 + d_e_ft / 9.1
    return DistributionFactor(
        one_lane=(one_lane_lever_rule if one_lane_lever_rule is not None
                  else interior_df.one_lane),
        multi_lane=e * interior_df.multi_lane,
        applicability={**interior_df.applicability,
                       "de": -1.0 <= d_e_ft <= 5.5},
    )


@article("4.6.2.2.3b", "Distribution of Live Load Shear, Exterior Girders")
def shear_df_exterior(
    interior_df: DistributionFactor,
    d_e_ft: float,
    one_lane_lever_rule: float | None = None,
) -> DistributionFactor:
    """Shear DF for exterior I-girders (Table 4.6.2.2.3b-1): multi-lane
    g = e * g_interior with e = 0.6 + de/10."""
    e = 0.6 + d_e_ft / 10.0
    return DistributionFactor(
        one_lane=(one_lane_lever_rule if one_lane_lever_rule is not None
                  else interior_df.one_lane),
        multi_lane=e * interior_df.multi_lane,
        applicability={**interior_df.applicability,
                       "de": -1.0 <= d_e_ft <= 5.5},
    )


@article("4.6.2.2.2e", "Skew Correction — Moment")
def skew_correction_moment(
    skew_deg: float,
    s_ft: float,
    l_ft: float,
    t_s: float,
    k_g: float,
) -> float:
    """Reduction of moment DF on skewed supports (Table 4.6.2.2.2e-1):
    1 - c1*(tan(theta))^1.5, with c1 = 0.25*(Kg/(12*L*ts^3))^0.25*(S/L)^0.5.
    No reduction below 30 degrees; theta capped at 60."""
    if skew_deg < 30.0:
        return 1.0
    theta = min(skew_deg, 60.0)
    c1 = 0.25 * (k_g / (12.0 * l_ft * t_s**3)) ** 0.25 * (s_ft / l_ft) ** 0.5
    return 1.0 - c1 * math.tan(math.radians(theta)) ** 1.5


@article("4.6.2.2.3c", "Skew Correction — Shear")
def skew_correction_shear(
    skew_deg: float,
    l_ft: float,
    t_s: float,
    k_g: float,
) -> float:
    """Increase of shear DF at the obtuse corner of skewed spans
    (Table 4.6.2.2.3c-1): 1 + 0.20*(12*L*ts^3/Kg)^0.3 * tan(theta)."""
    if skew_deg <= 0.0:
        return 1.0
    return 1.0 + 0.20 * (12.0 * l_ft * t_s**3 / k_g) ** 0.3 * math.tan(
        math.radians(skew_deg)
    )


@article("4.6.2.3", "Equivalent Strip Widths for Slab Bridges")
def slab_equivalent_strip(
    span_ft: float,
    width_ft: float,
    n_lanes: int,
    multi_lane: bool = True,
    skew_deg: float = 0.0,
) -> float:
    """Equivalent strip width E (in) carrying one wheel line of live load
    in a cast-in-place slab bridge (4.6.2.3):

    one lane:  E = 10.0 + 5.0*sqrt(L1*W1),  W1 capped at 30 ft
    multi:     E = 84.0 + 1.44*sqrt(L1*W1) <= 12.0*W/NL, W1 capped at 60 ft

    with L1 = min(span, 60 ft).  Skewed bridges may reduce the force
    effects by r = 1.05 - 0.25*tan(theta) <= 1.00 — the reduction is
    applied to E here (wider strip = lower demand per ft)."""
    l_1 = min(span_ft, 60.0)
    if multi_lane:
        w_1 = min(width_ft, 60.0)
        e = min(84.0 + 1.44 * math.sqrt(l_1 * w_1),
                12.0 * width_ft / n_lanes)
    else:
        w_1 = min(width_ft, 30.0)
        e = 10.0 + 5.0 * math.sqrt(l_1 * w_1)
    r = min(1.05 - 0.25 * math.tan(math.radians(skew_deg)), 1.0)
    return e / r


@article("4.6.2.2.2b-g", "Distribution of Live Load Moment, Box Beams")
def moment_df_interior_box(
    b_in: float,
    l_ft: float,
    i_beam: float,
    j_beam: float,
    n_beams: int,
) -> DistributionFactor:
    """Moment DF for interior precast box beams used in multibeam decks
    (Table 4.6.2.2.2b-1, cross-section type g):

    one lane:  k*(b/33.3L)^0.5 * (I/J)^0.25
    multi:     k*(b/305)^0.6 * (b/12L)^0.2 * (I/J)^0.06
    k = 2.5*(Nb)^-0.2 >= 1.5

    ``b_in`` is the beam width (in), ``i_beam``/``j_beam`` the moment of
    inertia and St. Venant constant (in^4)."""
    k = max(2.5 * n_beams**-0.2, 1.5)
    one = k * (b_in / (33.3 * l_ft)) ** 0.5 * (i_beam / j_beam) ** 0.25
    multi = (
        k * (b_in / 305.0) ** 0.6 * (b_in / (12.0 * l_ft)) ** 0.2
        * (i_beam / j_beam) ** 0.06
    )
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "width": 35.0 <= b_in <= 60.0,
            "span": 20.0 <= l_ft <= 120.0,
            "n_beams": 5 <= n_beams <= 20,
        },
    )


@article("4.6.2.2.2b-d", "Distribution of Live Load Moment, Multicell Box")
def moment_df_interior_multicell(
    s_ft: float,
    l_ft: float,
    n_cells: int,
) -> DistributionFactor:
    """Moment DF for an interior web of a cast-in-place multicell box
    (Table 4.6.2.2.2b-1, cross-section type d):

    one lane:  (1.75 + S/3.6) * (1/L)^0.35 * (1/Nc)^0.45
    multi:     (13/Nc)^0.3 * (S/5.8) * (1/L)^0.25

    ``s_ft`` is the web spacing; ``n_cells`` the number of cells (use 8
    in the formula when Nc > 8, per the table note)."""
    n_c = min(n_cells, 8)
    one = (1.75 + s_ft / 3.6) * (1.0 / l_ft) ** 0.35 * (1.0 / n_c) ** 0.45
    multi = (13.0 / n_c) ** 0.3 * (s_ft / 5.8) * (1.0 / l_ft) ** 0.25
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "spacing": 7.0 <= s_ft <= 13.0,
            "span": 60.0 <= l_ft <= 240.0,
            "n_cells": n_cells >= 3,
        },
    )


@article("4.6.2.2.3a-d", "Distribution of Live Load Shear, Multicell Box")
def shear_df_interior_multicell(
    s_ft: float,
    l_ft: float,
    d_in: float,
) -> DistributionFactor:
    """Shear DF for an interior web of a cast-in-place multicell box
    (Table 4.6.2.2.3a-1, type d):

    one lane:  (S/9.5)^0.6 * (d/12L)^0.1
    multi:     (S/7.3)^0.9 * (d/12L)^0.1

    ``d_in`` is the section depth (in)."""
    depth = d_in / (12.0 * l_ft)
    one = (s_ft / 9.5) ** 0.6 * depth**0.1
    multi = (s_ft / 7.3) ** 0.9 * depth**0.1
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "spacing": 6.0 <= s_ft <= 13.0,
            "span": 20.0 <= l_ft <= 240.0,
            "depth": 35.0 <= d_in <= 110.0,
        },
    )


@article("4.6.2.2.2b-spread",
         "Distribution of Live Load Moment, Spread Box Beams")
def moment_df_interior_spread_box(
    s_ft: float,
    l_ft: float,
    d_in: float,
    n_beams: int = 4,
) -> DistributionFactor:
    """Moment DF for interior precast spread box beams (Table
    4.6.2.2.2b-1):

    one lane:  (S/3.0)^0.35 * (S*d/(12*L^2))^0.25
    multi:     (S/6.3)^0.6 * (S*d/(12*L^2))^0.125

    ``d_in`` is the beam depth (in).  Beyond S = 18 ft the table sends
    you to the lever rule (``applicable`` goes False)."""
    term = s_ft * d_in / (12.0 * l_ft**2)
    one = (s_ft / 3.0) ** 0.35 * term**0.25
    multi = (s_ft / 6.3) ** 0.6 * term**0.125
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "spacing": 6.0 <= s_ft <= 18.0,
            "span": 20.0 <= l_ft <= 140.0,
            "depth": 18.0 <= d_in <= 65.0,
            "n_beams": n_beams >= 3,
        },
    )


@article("4.6.2.2.3a-spread",
         "Distribution of Live Load Shear, Spread Box Beams")
def shear_df_interior_spread_box(
    s_ft: float,
    l_ft: float,
    d_in: float,
    n_beams: int = 4,
) -> DistributionFactor:
    """Shear DF for interior precast spread box beams (Table
    4.6.2.2.3a-1):

    one lane:  (S/10)^0.6 * (d/12L)^0.1
    multi:     (S/7.4)^0.8 * (d/12L)^0.1
    """
    depth = d_in / (12.0 * l_ft)
    one = (s_ft / 10.0) ** 0.6 * depth**0.1
    multi = (s_ft / 7.4) ** 0.8 * depth**0.1
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "spacing": 6.0 <= s_ft <= 18.0,
            "span": 20.0 <= l_ft <= 140.0,
            "depth": 18.0 <= d_in <= 65.0,
            "n_beams": n_beams >= 3,
        },
    )


@article("4.6.2.2.3a-g", "Distribution of Live Load Shear, Box Beams")
def shear_df_interior_box(
    b_in: float,
    l_ft: float,
    i_beam: float,
    j_beam: float,
) -> DistributionFactor:
    """Shear DF for interior precast box beams used in multibeam decks
    (Table 4.6.2.2.3a-1, cross-section type g):

    one lane:  (b/130L)^0.15 * (I/J)^0.05
    multi:     (b/156)^0.4 * (b/12L)^0.1 * (I/J)^0.05 * (b/48), b/48 >= 1

    ``b_in`` is the beam width (in); the b/48 term never reduces the
    multi-lane factor."""
    stiffness = (i_beam / j_beam) ** 0.05
    one = (b_in / (130.0 * l_ft)) ** 0.15 * stiffness
    multi = (
        (b_in / 156.0) ** 0.4 * (b_in / (12.0 * l_ft)) ** 0.1 * stiffness
        * max(b_in / 48.0, 1.0)
    )
    return DistributionFactor(
        one_lane=one,
        multi_lane=multi,
        applicability={
            "width": 35.0 <= b_in <= 60.0,
            "span": 20.0 <= l_ft <= 120.0,
        },
    )


@article("3.6.1.1.2", "Multiple Presence Factors")
def multiple_presence_factor(n_lanes: int) -> float:
    """m (Table 3.6.1.1.2-1): 1.20 / 1.00 / 0.85 / 0.65 for 1/2/3/>3 loaded
    lanes.  Already embedded in the 4.6.2.2 DF equations — apply only with
    the lever rule or refined analysis."""
    return {1: 1.20, 2: 1.00, 3: 0.85}.get(n_lanes, 0.65)


def lever_rule_exterior(
    s_ft: float,
    d_e_ft: float,
    apply_multiple_presence: bool = True,
) -> float:
    """One-lane exterior-girder DF by the lever rule (C4.6.2.2.1): deck
    assumed hinged at the first interior girder, one truck with wheel
    lines 6 ft apart, the nearer one 2 ft from the barrier face.  Wheels
    landing inboard of the interior girder contribute nothing.

    Returns lanes/girder including the 1.2 single-lane multiple presence
    unless ``apply_multiple_presence`` is False."""
    # Wheel positions measured from the exterior girder, outboard negative
    x1 = -d_e_ft + 2.0
    x2 = x1 + 6.0
    g = (max(s_ft - x1, 0.0) + max(s_ft - x2, 0.0)) / (2.0 * s_ft)
    if apply_multiple_presence:
        g *= multiple_presence_factor(1)
    return g


def rigid_rotation_exterior(n_beams: int, s_ft: float, lane_eccentricities_ft) -> list[dict]:
    """Exterior-girder reaction of a cross section that deflects and
    rotates as a rigid body (C4.6.2.2.2d-1):
    ``R = N_L / N_b + X_ext sum(e) / sum(x^2)``, for N_L = 1, 2, ... lanes
    loaded in the order given.

    Girders at equal spacing ``s_ft`` about the centroid of the pattern;
    ``lane_eccentricities_ft`` are the lane centers' distances from that
    centroid, positive toward the exterior girder, nearest first.  Each row
    gives ``R`` (lanes) and ``mR`` with the Table 3.6.1.1.2-1 factor (the
    strength-limit value; 4.6.2.2.2d also requires it at least the
    approximate-formula value)."""
    xs = [(k - (n_beams - 1) / 2.0) * s_ft for k in range(n_beams)]
    sum_x2 = sum(x * x for x in xs)
    x_ext = max(xs)
    rows = []
    for n_l in range(1, len(lane_eccentricities_ft) + 1):
        r = n_l / n_beams + x_ext * sum(lane_eccentricities_ft[:n_l]) / sum_x2
        rows.append({"lanes": n_l, "R": r, "mR": multiple_presence_factor(n_l) * r})
    return rows


@article("4.6.2.6", "Effective Flange Width")
def effective_flange_width(
    s_ft: float,
    span_ft: float | None = None,
    t_s: float | None = None,
    t_w: float | None = None,
    b_f: float | None = None,
    design_year: int | None = None,
) -> float:
    """Effective deck width acting with an interior girder (4.6.2.6.1), in
    inches.

    Since the 2008 interim revisions this is simply the girder spacing.
    Earlier designs used the lesser of L/4, 12*ts + max(tw, bf/2), and S —
    pass ``design_year`` (with ``span_ft``, ``t_s``, ``t_w``, ``b_f``) for
    those."""
    if design_year is not None and design_year < 2008:
        if None in (span_ft, t_s, t_w, b_f):
            raise ValueError(
                "pre-2008 effective width needs span_ft, t_s, t_w, and b_f"
            )
        return min(span_ft * 12.0 / 4.0, 12.0 * t_s + max(t_w, b_f / 2.0),
                   s_ft * 12.0)
    return s_ft * 12.0


@article("3.6.2", "Dynamic Load Allowance")
def dynamic_load_allowance(component: str = "general",
                           fatigue: bool = False) -> float:
    """IM (Table 3.6.2.1-1) as a multiplier on the truck portion of live
    load: 1.33 generally, 1.15 for fatigue, 1.75 for deck joints."""
    if component == "deck_joint":
        return 1.75
    return 1.15 if fatigue else 1.33
