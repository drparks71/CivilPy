#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AASHTO Manual for Bridge Evaluation (MBE) Section 6A — LRFR load rating.

The general rating equation composes any of the capacity checks in this
package into a load rating:

    RF = (C - gamma_DC*DC - gamma_DW*DW +/- gamma_P*P) / (gamma_LL*(LL+IM))

where C = phi_c * phi_s * phi * Rn at strength limit states (with
phi_c*phi_s >= 0.85) or the allowable stress fR at service limit states.

Factors default to the published MBE values but every one is overridable —
agencies routinely customize them.
Consistent force/moment units in = same units out; RF is dimensionless.
"""

from __future__ import annotations

import math

from civilpy.structural.aashto.lrfd.core import CheckResult, article

# Condition factor phi_c (Table 6A.4.2.3-1), keyed by member condition
CONDITION_FACTORS = {"good": 1.00, "satisfactory": 1.00, "fair": 0.95,
                     "poor": 0.85}

# System factor phi_s for flexure/axial (Table 6A.4.2.4-1)
SYSTEM_FACTORS = {
    "welded_two_girder": 0.85,
    "riveted_two_girder": 0.90,
    "multiple_eyebar_truss": 0.90,
    "three_girder_spacing_le_6ft": 0.85,
    "four_girder_spacing_le_4ft": 0.95,
    "other_girder_slab": 1.00,
    "floorbeams_spacing_gt_12ft": 0.85,
    "redundant_subsystem": 1.00,
}

# Design-load live load factors (Table 6A.4.2.2-1)
GAMMA_LL_INVENTORY = 1.75
GAMMA_LL_OPERATING = 1.35


@article("6A.4.2.1", "LRFR General Load Rating Equation")
def rating_factor(
    nominal_capacity: float,
    dc: float,
    ll_im: float,
    dw: float = 0.0,
    phi: float = 1.0,
    level: str = "inventory",
    gamma_ll: float | None = None,
    gamma_dc: float = 1.25,
    gamma_dw: float = 1.50,
    condition: str = "good",
    system: str = "other_girder_slab",
    permanent_other: float = 0.0,
    gamma_p: float = 1.0,
    service: bool = False,
) -> CheckResult:
    """General LRFR rating factor (MBE 6A.4.2.1-1).

    ``nominal_capacity`` is Rn from any capacity check in this package
    (pass the check's ``capacity`` and its ``phi``); ``dc``/``dw``/``ll_im``
    are the unfactored force effects, with ``ll_im`` already including the
    distribution factor and dynamic load allowance.  ``level`` selects the
    design-load gamma_LL (1.75 inventory / 1.35 operating) unless
    ``gamma_ll`` is given (legal/permit ratings).  At service limit states
    pass ``service=True`` to skip the condition/system factors.

    ``capacity`` on the result holds RF; ok means RF >= 1.0."""
    if gamma_ll is None:
        gamma_ll = (GAMMA_LL_OPERATING if level == "operating"
                    else GAMMA_LL_INVENTORY)
    if service:
        c = phi * nominal_capacity
        phi_c = phi_s = 1.0
    else:
        phi_c = CONDITION_FACTORS[condition]
        phi_s = SYSTEM_FACTORS[system]
        cs = max(phi_c * phi_s, 0.85)  # 6A.4.2.1-3
        c = cs * phi * nominal_capacity
    rf = (c - gamma_dc * dc - gamma_dw * dw - gamma_p * permanent_other) / (
        gamma_ll * ll_im
    )
    return CheckResult(
        article="6A.4.2.1",
        name="LRFR General Load Rating Equation",
        capacity=rf,
        demand=1.0,
        details={"C": c, "phi_c": phi_c, "phi_s": phi_s,
                 "gamma_LL": gamma_ll, "level": level},
    )


@article("6A.4.4.2.3a", "Legal Load Live Load Factor")
def legal_load_factor(adtt: float | None = None) -> float:
    """Generalized live load factor for legal-load ratings
    (Table 6A.4.4.2.3a-1): 1.30 at one-direction ADTT <= 1000, 1.45 at
    ADTT >= 5000 (or unknown), linearly interpolated between."""
    if adtt is None or adtt >= 5000.0:
        return 1.45
    if adtt <= 1000.0:
        return 1.30
    return 1.30 + 0.15 * (adtt - 1000.0) / 4000.0


@article("6A.8.3", "Posting Load")
def posting_load(rf: float, vehicle_weight_tons: float) -> float:
    """Safe posting load for a legal vehicle (6A.8.3-1):
    W*(RF - 0.3)/0.7 for 0.3 <= RF < 1.0; the full vehicle weight when
    RF >= 1.0; 0 (close the bridge to that vehicle) when RF < 0.3."""
    if rf >= 1.0:
        return vehicle_weight_tons
    if rf < 0.3:
        return 0.0
    return vehicle_weight_tons * (rf - 0.3) / 0.7


# Permit load factors (Table 6A.4.5.4.2a-1, 2013 revision and later):
# routine/annual permits mixed with traffic are keyed by one-direction
# ADTT row and GVW/AL band (kips/ft) — (<2, 2 to <3, >=3); special or
# limited-crossing permits are keyed by trip/escort condition.  Like the
# condition/system factors above, agencies may override any value.
PERMIT_ROUTINE_FACTORS = {
    5000: (1.40, 1.35, 1.30),
    1000: (1.35, 1.25, 1.20),
    100: (1.30, 1.20, 1.15),
}

PERMIT_SPECIAL_FACTORS = {
    "single_trip_escorted": 1.10,
    "single_trip_mixed": 1.20,
    "multiple_trip_mixed": 1.40,
}


#: Routine permits rated with the one-lane distribution factor, all ADTTs
#: (Table 6A.4.5.4.2a-1; SBDH Ch. 18 Table 7).
PERMIT_ROUTINE_ONE_LANE = 1.40

#: Emergency vehicles EV2 / EV3 (FHWA memorandum, November 3 2016): rated at
#: the legal-load level with gamma_LL = 1.30, in one lane of one direction.
EMERGENCY_VEHICLE_LOAD_FACTOR = 1.30


@article("6A.4.5.4.2a", "Permit Live Load Factor")
def permit_load_factor(
    permit_type: str = "routine",
    adtt: float | None = None,
    gvw_kips: float | None = None,
    axle_length_ft: float | None = None,
    gvw_over_al: float | None = None,
    factors: dict | None = None,
    *,
    one_lane: bool = False,
    refined_analysis: bool = False,
    crawl_speed: bool = False,
) -> float:
    """Live load factor for permit ratings (Table 6A.4.5.4.2a-1).

    ``permit_type`` is ``"routine"`` (annual, mixed with traffic, two or
    more lanes) or one of the special/limited-crossing types:
    ``"single_trip_escorted"``, ``"single_trip_mixed"``,
    ``"multiple_trip_mixed"`` (fewer than 100 crossings).

    Routine permits need the one-direction ``adtt`` and the permit
    weight intensity GVW/AL — pass ``gvw_over_al`` directly (kips/ft)
    or ``gvw_kips`` with ``axle_length_ft`` (distance between the
    extreme axles).  Factors interpolate linearly on ADTT between 100
    and 5000 within each GVW/AL band; ADTT above 5000 (or unknown) uses
    the top row.  ``factors`` overrides the published table for agency
    customizations (same shapes as ``PERMIT_ROUTINE_FACTORS`` /
    ``PERMIT_SPECIAL_FACTORS``).

    Adjustments (MBE 6A.4.5.4.2a; SBDH Ch. 18 Sec. 6.5.4.3):
    ``one_lane`` -- a routine permit with the one-lane distribution factor
    takes 1.40 at all ADTTs; ``refined_analysis`` -- routine permits add
    0.10 (two permit trucks in adjacent lanes) and a special permit mixed
    with traffic takes 1.00 on the permit truck (with 1.10 on the governing
    legal truck in the adjacent lane, not returned here); ``crawl_speed``
    -- an escorted special permit at crawl speed with no dynamic load
    allowance is increased by 1.05.
    """
    if permit_type != "routine":
        table = factors or PERMIT_SPECIAL_FACTORS
        if permit_type not in table:
            raise ValueError(f"unknown permit type {permit_type!r}; "
                             f"expected 'routine' or one of {sorted(table)}")
        if refined_analysis and permit_type in ("single_trip_mixed", "multiple_trip_mixed"):
            return 1.00
        f = table[permit_type]
        if crawl_speed and permit_type == "single_trip_escorted":
            f *= 1.05
        return f
    if one_lane:
        return PERMIT_ROUTINE_ONE_LANE
    if refined_analysis:
        return _routine_permit(adtt, gvw_kips, axle_length_ft, gvw_over_al, factors) + 0.10
    return _routine_permit(adtt, gvw_kips, axle_length_ft, gvw_over_al, factors)


def _routine_permit(adtt, gvw_kips, axle_length_ft, gvw_over_al, factors):
    if gvw_over_al is None:
        if gvw_kips is None or axle_length_ft is None:
            raise ValueError("routine permits need gvw_over_al, or "
                             "gvw_kips with axle_length_ft")
        gvw_over_al = gvw_kips / axle_length_ft
    band = 0 if gvw_over_al < 2.0 else (1 if gvw_over_al < 3.0 else 2)

    table = factors or PERMIT_ROUTINE_FACTORS
    rows = sorted(table)                       # [100, 1000, 5000]
    if adtt is None or adtt >= rows[-1]:
        return table[rows[-1]][band]
    if adtt <= rows[0]:
        return table[rows[0]][band]
    for lo, hi in zip(rows, rows[1:]):
        if lo <= adtt <= hi:
            f_lo, f_hi = table[lo][band], table[hi][band]
            return f_lo + (f_hi - f_lo) * (adtt - lo) / (hi - lo)
    raise AssertionError("unreachable")


@article("6A.6.4.2.2", "Service II Flange Stress Limit")
def service_ii_flange_limit(f_yf: float, r_h: float = 1.0,
                            composite: bool = True) -> float:
    """Allowable flange stress f_R for the Service II (permanent
    deformation) rating of steel girders (MBE 6A.6.4.2.2 via LRFD
    6.10.4.2.2): 0.95 R_h F_yf for both flanges of composite sections,
    0.80 R_h F_yf for noncomposite sections."""
    return (0.95 if composite else 0.80) * r_h * f_yf


#: Evaluation live-load factors by level (Table 6A.4.2.2-1, SBDH Ch. 18
#: Table 3): Strength I design inventory / operating, Service II.
SERVICE_II_LL = {"inventory": 1.30, "operating": 1.00, "legal": 1.30, "permit": 1.00}


def steel_member_rating(
    *,
    level: str = "inventory",
    moment: tuple | None = None,
    shear: tuple | None = None,
    service_stress: tuple | None = None,
    phi_moment: float = 1.0,
    phi_shear: float = 1.0,
    condition: str = "good",
    system: str = "other_girder_slab",
    gamma_ll: float | None = None,
    adtt: float | None = None,
) -> dict[str, CheckResult]:
    """The steel-member LRFR flow of MBE 6A / SBDH Ch. 18 for one rating
    level: Strength (flexure and shear) and Service II rating factors.

    ``moment`` / ``shear`` are ``(nominal capacity, DC, DW, LL+IM)`` in any
    consistent units, the capacity *nominal* (``phi_moment`` / ``phi_shear``
    applied here); ``service_stress`` is ``(f_R, f_DC, f_DW, f_LL+IM)`` in
    ksi with f_R from :func:`service_ii_flange_limit`.

    ``level``: ``"inventory"`` / ``"operating"`` (HL-93, Strength I 1.75 /
    1.35), ``"legal"`` (Strength I at :func:`legal_load_factor` of
    ``adtt``), ``"permit"`` (Strength II -- pass ``gamma_ll`` from
    :func:`permit_load_factor`), or ``"emergency"`` (1.30).  The condition
    factor applies to both strength checks, the system factor to flexure
    only (shear is brittle: phi_s = 1.0, MBE C6A.4.2.4); neither applies
    at Service II."""
    if gamma_ll is None:
        gamma_ll = {"inventory": GAMMA_LL_INVENTORY, "operating": GAMMA_LL_OPERATING,
                    "legal": legal_load_factor(adtt),
                    "emergency": EMERGENCY_VEHICLE_LOAD_FACTOR}.get(level)
        if gamma_ll is None:
            raise ValueError("permit ratings need gamma_ll (permit_load_factor)")
    out = {}
    if moment is not None:
        rn, dc, dw, ll = moment
        out["flexure"] = rating_factor(rn, dc, ll, dw=dw, phi=phi_moment, level=level,
                                       gamma_ll=gamma_ll, condition=condition, system=system)
    if shear is not None:
        rn, dc, dw, ll = shear
        out["shear"] = rating_factor(rn, dc, ll, dw=dw, phi=phi_shear, level=level,
                                     gamma_ll=gamma_ll, condition=condition,
                                     system="redundant_subsystem")
    if service_stress is not None:
        f_r, f_dc, f_dw, f_ll = service_stress
        sll = SERVICE_II_LL["legal" if level == "emergency" else level]
        out["service II"] = rating_factor(f_r, f_dc, f_ll, dw=f_dw, level=level, gamma_ll=sll,
                                          gamma_dc=1.0, gamma_dw=1.0, service=True)
    for k, r in out.items():
        r.details["limit"] = k
    if out:
        gov = min(out, key=lambda k: out[k].capacity)
        out["governing"] = out[gov]
    return out


@article("6A.6.12.6", "Rivet Shear Resistance")
def rivet_shear_resistance(d_rivet: float, n_planes: int = 1,
                           phi_f_r: float = 21.0,
                           v_u: float | None = None) -> CheckResult:
    """Factored shear resistance of one rivet for rating: ``phi F_r`` (ksi,
    the factored rivet shear strength of the MBE table -- 21 ksi for ASTM
    A141 / A502 Grade 1 rivets, the 2003 LRFR Guide Manual Table 6-14 value
    used by FHWA HIF-18-042) times the nominal rivet area and the number of
    shear planes.  ``capacity`` is already factored (phi = 1.0)."""
    a_r = math.pi * d_rivet ** 2 / 4.0
    return CheckResult(article="6A.6.12.6", name="Rivet Shear Resistance",
                       capacity=phi_f_r * a_r * n_planes, demand=v_u,
                       details={"Ar": a_r, "phiFr": phi_f_r, "Ns": n_planes})
