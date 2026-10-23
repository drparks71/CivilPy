#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AASHTO LRFD 6.13.6.1 — bolted field splices for flexural members
(8th Edition simplified method).

These functions produce the splice *design forces*; the plates and bolts
are then checked with the existing primitives (
:func:`~civilpy.structural.aashto.lrfd.steel.tension_member_resistance`,
``bolt_shear_resistance``, ``bolt_slip_resistance``,
``block_shear_resistance``).  Units: kip, inch, ksi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from civilpy.structural.aashto.lrfd.core import CheckResult, article


@article("6.13.6.1.3b", "Flange Splice Design Force")
def flange_splice_design_force(
    a_n: float,
    a_g: float,
    f_y: float,
    f_u: float,
    f_design: float | None = None,
) -> CheckResult:
    """Design force for a flange splice (6.13.6.1.3b-1): P = Fcf*Ae with
    the effective flange area Ae = (phi_u*Fu)/(phi_y*Fy)*An <= Ag
    (6.13.6.1.3b-2); phi_u = 0.80, phi_y = 0.95.

    ``f_design`` is the flange design stress Fcf (6.13.6.1.3b): when omitted it
    defaults to the full yield stress ``f_y`` (the conservative upper bound,
    correct for a fully stressed flange).  Supply the AASHTO Fcf --
    ``max((|fcf|/Rh + alpha*phi_f*Fyf)/2, 0.75*alpha*phi_f*Fyf)`` computed from
    the actual factored flange stress ``fcf`` -- to design a lightly stressed
    splice for its real demand (the ODOT BDM / NSBA workbook method).

    The splice plates, their bolts, and the flange itself are then checked
    against the returned force.  ``capacity`` holds P (kip)."""
    a_e = min(0.80 * f_u / (0.95 * f_y) * a_n, a_g)
    stress = f_y if f_design is None else f_design
    p_fy = stress * a_e
    return CheckResult(
        article="6.13.6.1.3b",
        name="Flange Splice Design Force",
        capacity=p_fy,
        details={"Ae": a_e, "An": a_n, "Ag": a_g, "Fcf": stress},
    )


def flange_design_stress_fcf(
    fcf: float,
    f_yf: float,
    r_h: float = 1.0,
    alpha: float = 1.0,
    phi_f: float = 1.0,
) -> float:
    """Flange design stress Fcf (AASHTO LRFD 6.13.6.1.3b):

    ``Fcf = max( (|fcf|/Rh + alpha*phi_f*Fyf)/2 , 0.75*alpha*phi_f*Fyf )``

    ``fcf`` is the maximum factored flexural stress at the mid-thickness of the
    flange under the governing strength combination (ksi, sign ignored).  Rh is
    the hybrid factor (1.0 non-hybrid), alpha = 1.0 (0.85 for compression
    flanges w/ slender web), phi_f = 1.0.  The result is capped in practice by
    Fyf and floored at 0.75*alpha*phi_f*Fyf (the minimum splice design stress
    of C6.13.6.1.3b)."""
    computed = (abs(fcf) / r_h + alpha * phi_f * f_yf) / 2.0
    floor = 0.75 * alpha * phi_f * f_yf
    return max(computed, floor)


@article("6.13.6.1.4c", "Flange Splice Design Forces (pre-8th Edition)")
def stress_based_flange_design_forces(
    cases,
    a_e: dict,
    a_g: dict,
    f_yf: dict,
    r_h: float = 1.0,
    alpha: float = 1.0,
    phi_f: float = 1.0,
) -> dict:
    """Flange splice design forces by the pre-8th-Edition design-stress
    method (6.13.6.1.4c through the 7th Edition).

    ``cases`` is an iterable of concurrent ``(f_top, f_bottom)`` factored
    Strength I stresses (ksi) at the flange mid-thicknesses, tension
    positive, one pair per load case.  ``a_e``, ``a_g`` and ``f_yf`` are
    keyed ``"top"``/``"bottom"`` and hold the smaller effective and gross
    areas and the flange yield strength of the two sides of the splice.

    In each case the controlling flange is the one with the larger ratio of
    stress to factored flexural resistance; it is designed for
    ``Fcf = max((|fcf|/Rh + alpha*phi_f*Fyf)/2, 0.75*alpha*phi_f*Fyf)``.  The
    other flange is designed for ``Fncf = max(Rcf*|fncf|/Rh,
    0.75*alpha*phi_f*Fyf)`` with ``Rcf = |Fcf/fcf|``.  A flange in tension
    uses Ae, one in compression Ag.  Each flange's design force is the
    largest over the cases.  Returns ``{"top": P, "bottom": P,
    "tension": {...}, "compression": {...}, "cases": [...]}`` (kip): the
    governing force per flange plus its largest tension and compression
    forces, which the splice-plate tension and compression checks use."""
    out = {"top": 0.0, "bottom": 0.0, "cases": [],
           "tension": {"top": 0.0, "bottom": 0.0},
           "compression": {"top": 0.0, "bottom": 0.0}}
    for f_top, f_bot in cases:
        f = {"top": f_top, "bottom": f_bot}
        ctrl = max(f, key=lambda k: abs(f[k]) / (alpha * phi_f * f_yf[k]))
        nctrl = "bottom" if ctrl == "top" else "top"
        floor = {k: 0.75 * alpha * phi_f * f_yf[k] for k in f}
        f_cf = flange_design_stress_fcf(f[ctrl], f_yf[ctrl], r_h=r_h,
                                        alpha=alpha, phi_f=phi_f)
        r_cf = abs(f_cf / f[ctrl]) if f[ctrl] else 1.0
        f_ncf = max(r_cf * abs(f[nctrl]) / r_h, floor[nctrl])
        design = {ctrl: f_cf, nctrl: f_ncf}
        row = {"controlling": ctrl, "Rcf": r_cf}
        for k in f:
            area = a_e[k] if f[k] > 0 else a_g[k]
            force = design[k] * area
            row[k] = {"f": f[k], "F": design[k], "area": area, "P": force}
            out[k] = max(out[k], force)
            sense = "tension" if f[k] > 0 else "compression"
            out[sense][k] = max(out[sense][k], force)
        out["cases"].append(row)
    return out


@dataclass
class WebSpliceForces:
    """Design forces for a web splice (6.13.6.1.3c): the vertical design
    shear Vuw, the horizontal force Hw from the moment not carried by the
    flanges, and the resultant per-bolt force to compare against the bolt
    shear/slip resistance."""

    v_uw: float
    h_w: float
    per_bolt: float
    n_bolts: int


@article("6.13.6.1.3c", "Web Splice Design Forces")
def web_splice_design_forces(
    v_r_web: float,
    n_bolts: int,
    m_u: float = 0.0,
    m_flange: float = 0.0,
    moment_arm: float | None = None,
) -> WebSpliceForces:
    """Web splice design forces (6.13.6.1.3c, 8th Ed. method).

    ``v_r_web`` is the smaller factored shear resistance phi_v*Vn of the
    webs on either side of the splice (6.10.9) — the web splice is designed
    for the full web capacity, not the applied shear.  When the factored
    moment ``m_u`` (kip-in) exceeds the moment the flange splices can carry
    ``m_flange``, the excess is resisted by a horizontal force couple in
    the web: ``Hw = (|Mu| - Mrf)/arm``.  Each of the ``n_bolts`` (one side of
    the splice) sees the vector sum of Vuw/Nb and Hw/Nb."""
    v_uw = v_r_web
    h_w = 0.0
    excess = abs(m_u) - m_flange
    if excess > 0.0:
        if moment_arm is None:
            raise ValueError(
                "moment_arm is required when |Mu| exceeds the "
                "flange-resisted moment"
            )
        h_w = excess / moment_arm
    per_bolt = math.hypot(v_uw / n_bolts, h_w / n_bolts)
    return WebSpliceForces(v_uw=v_uw, h_w=h_w, per_bolt=per_bolt,
                           n_bolts=n_bolts)


# ---------------------------------------------------------------------------
# Splice-plate proportioning and per-plate design forces
# ---------------------------------------------------------------------------

@dataclass
class SplicePlateForces:
    """How the flange design force ``Pfy`` is apportioned to the inner and
    outer splice plates (C6.13.6.1.3b).  ``double_shear`` is True when the
    inner and outer plate areas are within 10% and the force is shared
    equally (each plate group works in double shear at Pfy/2); otherwise
    each plate carries the fraction of Pfy proportional to its area."""

    outer: float
    inner: float
    double_shear: bool
    ratio_outer: float


@article("6.13.6.1.3b", "Splice Plate Design Force")
def splice_plate_design_force(
    p_fy: float,
    a_g_outer: float,
    a_g_inner: float,
) -> SplicePlateForces:
    """Apportion the flange design force ``Pfy`` between the outer and inner
    splice plates (C6.13.6.1.3b).  If the plate areas differ by no more than
    10%, the force is divided equally (double shear, Pfy/2 each); otherwise
    it is split in proportion to plate area."""
    total = a_g_outer + a_g_inner
    pct_diff = abs(a_g_outer - a_g_inner) / max(a_g_outer, a_g_inner)
    if pct_diff <= 0.10:
        return SplicePlateForces(outer=0.5 * p_fy, inner=0.5 * p_fy,
                                 double_shear=True, ratio_outer=0.5)
    ratio_outer = a_g_outer / total
    return SplicePlateForces(
        outer=ratio_outer * p_fy,
        inner=(1.0 - ratio_outer) * p_fy,
        double_shear=False,
        ratio_outer=ratio_outer,
    )


@article("6.13.6.1.4", "Filler Plate Reduction Factor")
def filler_plate_reduction(
    a_f: float,
    a_p: float,
    total_filler_thickness: float = 1.0,
) -> CheckResult:
    """Bolt shear-resistance reduction for fillers (6.13.6.1.4).  When the
    total thickness of the fillers is 0.25 in or greater, the factored bolt
    shear resistance is multiplied by R = (1 + gamma)/(1 + 2*gamma), with
    gamma = Af/Ap; Af is the sum of the filler areas and Ap is the smaller of
    the connected-plate area or the sum of the splice-plate areas.  Below
    0.25 in of filler, R = 1.0.  ``capacity`` holds R."""
    if total_filler_thickness < 0.25 or a_f <= 0.0:
        r = 1.0
        gamma = 0.0
    else:
        gamma = a_f / a_p
        r = (1.0 + gamma) / (1.0 + 2.0 * gamma)
    return CheckResult(
        article="6.13.6.1.4",
        name="Filler Plate Reduction Factor",
        capacity=r,
        details={"gamma": gamma, "Af": a_f, "Ap": a_p},
    )


@article("6.13.5.2", "Net Section Reduction Limit")
def net_section_reduction_limit(a_n: float, a_g: float) -> CheckResult:
    """Effective net area limit for splice plates in tension (6.13.5.2):
    the net area used for the fracture check is taken as An but not more than
    0.85*Ag.  Reported as a NOTICE (not a strength failure): ``ok`` is True
    when An <= 0.85*Ag; ``details['An_eff']`` is the area to use downstream."""
    limit = 0.85 * a_g
    return CheckResult(
        article="6.13.5.2",
        name="Net Section Reduction Limit",
        capacity=limit,
        demand=a_n,
        details={"An": a_n, "An_eff": min(a_n, limit)},
    )


@article("D6.1", "Composite Slab Crushing Resistance")
def slab_crushing_resistance(
    f_c: float,
    b_eff: float,
    t_s: float,
    demand_force: float | None = None,
) -> CheckResult:
    """Plastic compressive force the composite deck can deliver at the splice
    (Appendix D6.1): Prb = 0.85*f'c*b_eff*t_s.  For a composite section the
    flange tension force plus the web horizontal force Hw must not exceed
    this, otherwise the deck is over-stressed and the splice should be
    designed as non-composite.  Pass ``demand_force`` = flange force + Hw."""
    p_rb = 0.85 * f_c * b_eff * t_s
    return CheckResult(
        article="D6.1",
        name="Composite Slab Crushing Resistance",
        capacity=p_rb,
        demand=demand_force,
        details={"b_eff": b_eff, "t_s": t_s},
    )


@article("6.13.6.1.3c", "Flange Moment Resistance")
def flange_moment_resistance(
    flange_force: float,
    moment_arm: float,
    m_u: float | None = None,
) -> CheckResult:
    """Moment the flange splices alone can resist as a force couple
    (6.13.6.1.3c): Mflange = Pfl * arm.  Compared against the factored
    design moment ``m_u``; any excess ``|Mu| - Mflange`` is carried by the web
    as the horizontal force Hw (see :func:`web_splice_design_forces`).
    Forces in kip, arm in inches, moments in kip-in."""
    m_flange = flange_force * moment_arm
    return CheckResult(
        article="6.13.6.1.3c",
        name="Flange Moment Resistance",
        capacity=m_flange,
        demand=None if m_u is None else abs(m_u),
        details={"flange_force": flange_force, "moment_arm": moment_arm},
    )


# ---------------------------------------------------------------------------
# Bolt spacing / edge / end distance limits (6.13.2.6)
# ---------------------------------------------------------------------------

# Table 6.13.2.6.6-1 minimum edge distance (in) for sheared vs rolled/gas-cut
# edges, keyed by bolt diameter (in).
MIN_EDGE_DISTANCE = {
    0.625: (1.125, 0.875), 0.75: (1.25, 1.0), 0.875: (1.5, 1.125),
    1.0: (1.75, 1.25), 1.125: (2.0, 1.5), 1.25: (2.25, 1.625),
    1.375: (2.4375, 1.71875),
}


@dataclass
class SpacingLimits:
    """Result of the 6.13.2.6 layout limit checks.  Each ``*_ok`` flag is
    True when the corresponding provided dimension is within the spec limit;
    the limit values are exposed for reporting."""

    min_spacing: float
    max_spacing_seal: float
    min_edge: float
    max_edge: float
    pitch_ok: bool | None
    gage_ok: bool | None
    edge_ok: bool | None
    end_ok: bool | None


# ---------------------------------------------------------------------------
# Splice-plate proportioning (sizing the plates, not just checking them)
# ---------------------------------------------------------------------------

def _round_to(value: float, increment: float, mode: str) -> float:
    """Round ``value`` to a multiple of ``increment`` (``mode`` = 'up',
    'down', or 'nearest')."""
    if increment <= 0.0:
        return value
    q = value / increment
    if mode == "up":
        q = math.ceil(q - 1e-9)
    elif mode == "down":
        q = math.floor(q + 1e-9)
    else:
        q = round(q)
    return q * increment


@dataclass
class FlangeSplicePlates:
    """Proportioned flange splice plates (C6.13.6.1.3b and the AASHTO/NSBA
    "develop the flange" guidance).  A single outer plate spans the full
    flange width; a pair of inner plates straddle the web, separated by the
    ``clearance`` gap needed for the web and its fillet welds.  Widths and
    thicknesses in inches.

    ``inner_thickness`` is the ideal thickness that makes the two inner plates
    equal in area to the outer plate; ``inner_thickness_band`` is the
    (low, high) range that keeps the inner/outer areas within 10% so the
    connection may be proportioned for the full flange force in double shear
    (C6.13.6.1.3b).  Pick any standard plate inside the band."""

    outer_width: float
    outer_thickness: float
    inner_width: float
    inner_width_exact: float
    inner_thickness: float
    inner_thickness_band: tuple[float, float]
    clearance: float
    min_thickness: float


@article("6.13.6.1.3b", "Flange Splice Plate Sizing")
def size_flange_splice_plates(
    flange_width_left: float,
    flange_width_right: float,
    flange_thickness: float,
    web_thickness_left: float,
    web_thickness_right: float,
    weld_size: float = 0.0,
    outer_thickness: float | None = None,
    width_increment: float = 0.5,
    thickness_increment: float = 0.0625,
) -> FlangeSplicePlates:
    """Proportion the outer and inner flange splice plates from the girder
    geometry (C6.13.6.1.3b; NSBA *Bolted Field Splices for Steel Bridge
    Flexural Members*).

    * Outer plate width = the narrower connected flange, ``min(bf_left,
      bf_right)`` — the outer plate must be at least as wide as the narrowest
      flange at the splice.
    * Web clearance gap = ``max(tw_left, tw_right) + 2*(weld_size + 1/8)`` so
      the inner plates clear the web and its fillet welds.
    * Inner plate width = ``(outer_width - clearance)/2`` (each of the pair),
      rounded down to ``width_increment``.
    * Minimum plate thickness = ``flange_thickness/2 + 1/16``.
    * With the outer thickness chosen (defaults to the rounded-up minimum),
      the ideal inner thickness equalises the plate areas:
      ``t_inner = t_outer * b_outer / (2*b_inner_exact)``, rounded up to
      ``thickness_increment``; the returned band keeps the areas within 10%.

    ``flange_thickness`` is the thickness of the flange being developed (the
    thicker adjoining flange governs the minimum plate thickness)."""
    b_outer = min(flange_width_left, flange_width_right)
    clearance = max(web_thickness_left, web_thickness_right) + 2.0 * (
        weld_size + 0.125
    )
    inner_width_exact = 0.5 * (b_outer - clearance)
    inner_width = _round_to(inner_width_exact, width_increment, "down")
    min_thickness = 0.5 * flange_thickness + 0.0625
    if outer_thickness is None:
        outer_thickness = _round_to(min_thickness, thickness_increment, "up")
    area_outer = b_outer * outer_thickness
    ideal = area_outer / (2.0 * inner_width_exact)
    inner_thickness = _round_to(ideal, thickness_increment, "up")
    band = (0.9 * area_outer / (2.0 * inner_width),
            1.1 * area_outer / (2.0 * inner_width))
    return FlangeSplicePlates(
        outer_width=b_outer,
        outer_thickness=outer_thickness,
        inner_width=inner_width,
        inner_width_exact=inner_width_exact,
        inner_thickness=inner_thickness,
        inner_thickness_band=band,
        clearance=clearance,
        min_thickness=min_thickness,
    )


@dataclass
class WebSplicePlates:
    """Proportioned web splice plates (6.13.6.1.3c; 6.13.2.6.2).  A pair of
    plates covers each face of the web over nearly the full depth.  ``height``
    is the plate depth (near-full web depth); ``max_pitch_seal`` is the
    maximum bolt spacing for sealing (6.13.2.6.2) and ``min_bolts_per_row``
    the resulting minimum number of bolts in a vertical line.  Inches."""

    thickness: float
    min_thickness: float
    height: float
    max_pitch_seal: float
    min_bolts_per_row: int
    filler_required: bool


@article("6.13.6.1.3c", "Web Splice Plate Sizing")
def size_web_splice_plate(
    web_depth: float,
    web_thickness: float,
    web_thickness_other: float,
    flange_clearance: float,
    thickness: float | None = None,
    thickness_increment: float = 0.0625,
) -> WebSplicePlates:
    """Proportion the web splice plates from the web geometry (6.13.6.1.3c;
    seal spacing 6.13.2.6.2).

    * Minimum plate thickness = ``web_thickness/2 + 1/16`` (``web_thickness``
      is the governing/thinner connected web).
    * Plate height = ``web_depth - 2*flange_clearance`` — the plates extend
      nearly the full web depth, clearing the flanges by ``flange_clearance``
      top and bottom.
    * Maximum bolt pitch for sealing = ``min(4.0 + 4.0*t, 7.0)`` in
      (6.13.2.6.2), giving a minimum of ``1 + ceil(height/max_pitch)`` bolts
      in each vertical line.
    * A filler is required when the two webs differ by more than 1/16 in.

    No filler is needed when the web-thickness difference is under 1/16 in."""
    min_thickness = 0.5 * web_thickness + 0.0625
    if thickness is None:
        thickness = _round_to(min_thickness, thickness_increment, "up")
    height = web_depth - 2.0 * flange_clearance
    max_pitch_seal = min(4.0 + 4.0 * thickness, 7.0)
    min_bolts_per_row = 1 + math.ceil(height / max_pitch_seal - 1e-9)
    filler_required = abs(web_thickness - web_thickness_other) > 0.0625
    return WebSplicePlates(
        thickness=thickness,
        min_thickness=min_thickness,
        height=height,
        max_pitch_seal=max_pitch_seal,
        min_bolts_per_row=min_bolts_per_row,
        filler_required=filler_required,
    )


@article("6.13.2.6", "Bolt Spacing and Edge Distance Limits")
def bolt_spacing_limits(
    d_bolt: float,
    plate_t: float,
    pitch: float | None = None,
    gage: float | None = None,
    edge_dist: float | None = None,
    end_dist: float | None = None,
    sheared_edge: bool = False,
) -> SpacingLimits:
    """Geometric layout limits for a bolt group (6.13.2.6):

    * minimum spacing (pitch and gage) = 3.0*d (6.13.2.6.1);
    * maximum spacing for sealing = min(4.0 + 4.0*t, 7.0) in (6.13.2.6.2);
    * minimum edge/end distance from Table 6.13.2.6.6-1;
    * maximum edge distance = min(8.0*t, 5.0) in (6.13.2.6.6).

    Any provided dimension is checked against its limit and the boolean flag
    set accordingly; ``None`` dimensions leave the flag ``None``."""
    min_spacing = 3.0 * d_bolt
    max_spacing_seal = min(4.0 + 4.0 * plate_t, 7.0)
    edges = MIN_EDGE_DISTANCE.get(round(d_bolt, 4), (2.0 * d_bolt, 1.5 * d_bolt))
    min_edge = edges[0] if sheared_edge else edges[1]
    max_edge = min(8.0 * plate_t, 5.0)
    return SpacingLimits(
        min_spacing=min_spacing,
        max_spacing_seal=max_spacing_seal,
        min_edge=min_edge,
        max_edge=max_edge,
        pitch_ok=None if pitch is None
        else min_spacing <= pitch <= max_spacing_seal,
        gage_ok=None if gage is None else gage >= min_spacing,
        edge_ok=None if edge_dist is None
        else min_edge <= edge_dist <= max_edge,
        end_ok=None if end_dist is None else end_dist >= min_edge,
    )
