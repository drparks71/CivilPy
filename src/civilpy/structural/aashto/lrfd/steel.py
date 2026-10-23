#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AASHTO LRFD Chapter 6 — steel I-girder design checks.

Articles follow the 9th/10th Edition numbering (unchanged since the 5th
Edition for these checks).  Units: kip, inch, ksi.
"""

from __future__ import annotations

import math

from civilpy.structural.aashto.lrfd.core import CheckResult, article

E_STEEL = 29000.0  # ksi, modulus of elasticity (6.4.1)
PHI_F = 1.0  # resistance factor for flexure (6.5.4.2)
PHI_V = 1.0  # resistance factor for shear (6.5.4.2)


def _fyr(f_yc: float, f_yw: float) -> float:
    """Fyr = min(0.7*Fyc, Fyw), floored at 0.5*Fyc — the stress level the
    buckling equations treat as the start of yielding in the compression
    flange once residual stresses are accounted for."""
    return max(min(0.7 * f_yc, f_yw), 0.5 * f_yc)


@article("6.10.8.2.2", "Local Buckling Resistance")
def flange_local_buckling_resistance(
    b_fc: float,
    t_fc: float,
    f_yc: float,
    f_yw: float,
    f_bu: float | None = None,
    r_b: float = 1.0,
    r_h: float = 1.0,
) -> CheckResult:
    """Compression-flange local buckling resistance Fnc (6.10.8.2.2).

    Parameters: flange width ``b_fc`` and thickness ``t_fc`` (in), yield
    strengths ``f_yc``/``f_yw`` (ksi), factored compression-flange stress
    ``f_bu`` (ksi, optional demand), web load-shedding factor ``r_b``
    (6.10.1.10.2) and hybrid factor ``r_h`` (6.10.1.10.1).
    """
    lam_f = b_fc / (2.0 * t_fc)  # 6.10.8.2.2-3
    lam_pf = 0.38 * math.sqrt(E_STEEL / f_yc)  # 6.10.8.2.2-4
    f_yr = _fyr(f_yc, f_yw)
    lam_rf = 0.56 * math.sqrt(E_STEEL / f_yr)  # 6.10.8.2.2-5

    if lam_f <= lam_pf:
        f_nc = r_b * r_h * f_yc  # 6.10.8.2.2-1
    else:
        f_nc = (
            1.0 - (1.0 - f_yr / (r_h * f_yc)) * (lam_f - lam_pf) / (lam_rf - lam_pf)
        ) * r_b * r_h * f_yc  # 6.10.8.2.2-2

    return CheckResult(
        article="6.10.8.2.2",
        name="Local Buckling Resistance",
        capacity=f_nc,
        demand=f_bu,
        phi=PHI_F,
        details={
            "lambda_f": lam_f,
            "lambda_pf": lam_pf,
            "lambda_rf": lam_rf,
            "Fyr": f_yr,
            "compact": lam_f <= lam_pf,
        },
    )


@article("6.10.8.2.3", "Lateral Torsional Buckling Resistance")
def lateral_torsional_buckling_resistance(
    l_b: float,
    b_fc: float,
    t_fc: float,
    d_c: float,
    t_w: float,
    f_yc: float,
    f_yw: float,
    c_b: float = 1.0,
    f_bu: float | None = None,
    r_b: float = 1.0,
    r_h: float = 1.0,
) -> CheckResult:
    """Compression-flange lateral torsional buckling resistance Fnc
    (6.10.8.2.3).

    Parameters: unbraced length ``l_b`` (in), compression flange ``b_fc`` x
    ``t_fc`` (in), depth of web in compression ``d_c`` (in), web thickness
    ``t_w`` (in), yield strengths (ksi), moment gradient modifier ``c_b``,
    optional factored flange stress demand ``f_bu`` (ksi).
    """
    # Effective radius of gyration for LTB (6.10.8.2.3-9)
    r_t = b_fc / math.sqrt(12.0 * (1.0 + d_c * t_w / (3.0 * b_fc * t_fc)))
    l_p = 1.0 * r_t * math.sqrt(E_STEEL / f_yc)  # 6.10.8.2.3-4
    f_yr = _fyr(f_yc, f_yw)
    l_r = math.pi * r_t * math.sqrt(E_STEEL / f_yr)  # 6.10.8.2.3-5

    f_max = r_b * r_h * f_yc
    if l_b <= l_p:
        f_nc = f_max  # 6.10.8.2.3-1
        regime = "inelastic-plateau"
    elif l_b <= l_r:
        f_nc = min(
            c_b
            * (1.0 - (1.0 - f_yr / (r_h * f_yc)) * (l_b - l_p) / (l_r - l_p))
            * f_max,
            f_max,
        )  # 6.10.8.2.3-2
        regime = "inelastic"
    else:
        f_cr = c_b * r_b * math.pi**2 * E_STEEL / (l_b / r_t) ** 2  # 6.10.8.2.3-8
        f_nc = min(f_cr, f_max)  # 6.10.8.2.3-3
        regime = "elastic"

    return CheckResult(
        article="6.10.8.2.3",
        name="Lateral Torsional Buckling Resistance",
        capacity=f_nc,
        demand=f_bu,
        phi=PHI_F,
        details={"rt": r_t, "Lp": l_p, "Lr": l_r, "Fyr": f_yr, "Cb": c_b,
                 "regime": regime},
    )


@article("6.10.8.1.2", "Discretely Braced Flanges in Tension")
def tension_flange_resistance(
    f_yt: float,
    f_bu: float | None = None,
    f_l: float = 0.0,
    r_h: float = 1.0,
) -> CheckResult:
    """Tension-flange nominal resistance Fnt = Rh*Fyt (6.10.8.3), checked as
    fbu + fl/3 <= phi_f*Fnt (6.10.8.1.2-1).  ``f_l`` is the flange lateral
    bending stress (ksi)."""
    f_nt = r_h * f_yt  # 6.10.8.3-1
    demand = None if f_bu is None else f_bu + f_l / 3.0
    return CheckResult(
        article="6.10.8.1.2",
        name="Discretely Braced Flanges in Tension",
        capacity=f_nt,
        demand=demand,
        phi=PHI_F,
        details={"fl": f_l},
    )


@article("6.10.1.10.1", "Hybrid Factor Rh")
def hybrid_factor(
    d_n: float,
    t_w: float,
    a_fn: float,
    f_yw: float,
    f_n: float,
) -> CheckResult:
    """Hybrid factor Rh (6.10.1.10.1-1) accounting for early web yielding
    when the web is a lower grade than the flanges:
    Rh = (12 + beta*(3*rho - rho^3)) / (12 + 2*beta), rho = min(Fyw/fn, 1),
    beta = 2*Dn*tw/Afn.

    ``d_n`` is the distance from the elastic NA to the inside of the
    controlling flange (in), ``a_fn`` that flange's area (in^2), ``f_n``
    its yield (or buckling) stress.  Homogeneous girders get Rh = 1.0.
    ``capacity`` holds Rh."""
    rho = min(f_yw / f_n, 1.0)
    beta = 2.0 * d_n * t_w / a_fn
    r_h = (12.0 + beta * (3.0 * rho - rho**3)) / (12.0 + 2.0 * beta)
    return CheckResult(
        article="6.10.1.10.1",
        name="Hybrid Factor Rh",
        capacity=r_h,
        details={"rho": rho, "beta": beta},
    )


@article("6.10.1.10.2", "Web Load-Shedding Factor Rb")
def web_load_shedding_factor(
    d_c: float,
    t_w: float,
    b_fc: float,
    t_fc: float,
    f_yc: float,
) -> CheckResult:
    """Web load-shedding factor Rb (6.10.1.10.2): 1.0 for compact and
    noncompact webs (2*Dc/tw <= lambda_rw = 5.7*sqrt(E/Fyc)); slender webs
    shed stress to the compression flange per -3:
    Rb = 1 - awc/(1200 + 300*awc) * (2*Dc/tw - lambda_rw) <= 1.0.
    ``capacity`` holds Rb."""
    lam_rw = 5.7 * math.sqrt(E_STEEL / f_yc)
    slenderness = 2.0 * d_c / t_w
    a_wc = 2.0 * d_c * t_w / (b_fc * t_fc)
    if slenderness <= lam_rw:
        r_b = 1.0
    else:
        r_b = min(
            1.0 - a_wc / (1200.0 + 300.0 * a_wc) * (slenderness - lam_rw), 1.0
        )
    return CheckResult(
        article="6.10.1.10.2",
        name="Web Load-Shedding Factor Rb",
        capacity=r_b,
        details={"lambda_rw": lam_rw, "2Dc/tw": slenderness, "awc": a_wc,
                 "slender_web": slenderness > lam_rw},
    )


@article("6.10.7.1.2", "Compact Composite Sections in Positive Flexure")
def compact_composite_positive_flexure(
    m_p: float,
    d_p: float,
    d_t: float,
    m_u: float | None = None,
    m_y: float | None = None,
    r_h: float = 1.0,
    continuous_span: bool = False,
) -> CheckResult:
    """Nominal flexural resistance of a compact composite section in
    positive flexure (6.10.7.1.2): Mn = Mp when Dp <= 0.1*Dt, else the
    penalty Mn = Mp*(1.07 - 0.7*Dp/Dt); continuous spans not meeting the
    B6 conditions cap Mn at 1.3*Rh*My.

    ``m_p`` is the plastic moment (kip-in, from a D6.1 PNA analysis),
    ``d_p`` the depth from the top of slab to the PNA, ``d_t`` the total
    composite depth.  The 6.10.7.3 ductility limit Dp <= 0.42*Dt is
    reported in details."""
    if d_p <= 0.1 * d_t:
        m_n = m_p
    else:
        m_n = m_p * (1.07 - 0.7 * d_p / d_t)
    capped = False
    if continuous_span and m_y is not None:
        cap = 1.3 * r_h * m_y
        capped = m_n > cap
        m_n = min(m_n, cap)
    return CheckResult(
        article="6.10.7.1.2",
        name="Compact Composite Sections in Positive Flexure",
        capacity=m_n,
        demand=m_u,
        phi=PHI_F,
        details={"Dp/Dt": d_p / d_t, "ductility_ok": d_p <= 0.42 * d_t,
                 "capped_13RhMy": capped},
    )


@article("6.10.2", "Cross-Section Proportion Limits")
def proportion_limits(
    d_web: float,
    t_w: float,
    b_fc: float,
    t_fc: float,
    b_ft: float,
    t_ft: float,
    i_yc: float | None = None,
    i_yt: float | None = None,
) -> CheckResult:
    """I-girder proportion limits (6.10.2): web D/tw <= 150 (without
    longitudinal stiffeners); each flange bf/2tf <= 12, bf >= D/6,
    tf >= 1.1*tw; and 0.1 <= Iyc/Iyt <= 10 when flange inertias are given.

    Pass/fail only — ``capacity`` is 1.0/0.0 against a ``demand`` of 1.0 so
    ``ok`` reflects all limits; per-limit booleans are in ``details``."""
    checks = {
        "web_slenderness": d_web / t_w <= 150.0,
        "comp_flange_slenderness": b_fc / (2.0 * t_fc) <= 12.0,
        "tens_flange_slenderness": b_ft / (2.0 * t_ft) <= 12.0,
        "comp_flange_width": b_fc >= d_web / 6.0,
        "tens_flange_width": b_ft >= d_web / 6.0,
        "comp_flange_thickness": t_fc >= 1.1 * t_w,
        "tens_flange_thickness": t_ft >= 1.1 * t_w,
    }
    if i_yc is not None and i_yt is not None:
        checks["flange_inertia_ratio"] = 0.1 <= i_yc / i_yt <= 10.0
    all_ok = all(checks.values())
    return CheckResult(
        article="6.10.2",
        name="Cross-Section Proportion Limits",
        capacity=1.0 if all_ok else 0.0,
        demand=1.0,
        details=checks,
    )


# Table 6.6.1.2.5-1 (detail category constant A, x10^8 ksi^3) and
# Table 6.6.1.2.5-3 (constant-amplitude fatigue thresholds, ksi)
FATIGUE_DETAIL_CATEGORIES = {
    "A": (250.0e8, 24.0),
    "B": (120.0e8, 16.0),
    "B'": (61.0e8, 12.0),
    "C": (44.0e8, 10.0),
    "C'": (44.0e8, 12.0),
    "D": (22.0e8, 7.0),
    "E": (11.0e8, 4.5),
    "E'": (3.9e8, 2.6),
}


@article("6.6.1.2.5", "Load-Induced Fatigue Resistance")
def fatigue_resistance(
    category: str,
    delta_f: float | None = None,
    fatigue_i: bool = True,
    adtt_sl: float = 1000.0,
    n_cycles_per_truck: float = 1.0,
    design_life_years: float = 75.0,
) -> CheckResult:
    """Nominal fatigue resistance (6.6.1.2.5): Fatigue I (infinite life)
    uses the constant-amplitude threshold (delta_F)TH; Fatigue II (finite
    life) uses (A/N)^(1/3) with N = 365 * years * n * ADTT_SL.

    ``category`` is the Table 6.6.1.2.3-1 detail category (A through E');
    ``delta_f`` the live-load stress range demand (ksi)."""
    a_const, threshold = FATIGUE_DETAIL_CATEGORIES[category]
    n = 365.0 * design_life_years * n_cycles_per_truck * adtt_sl
    if fatigue_i:
        resistance = threshold
    else:
        resistance = (a_const / n) ** (1.0 / 3.0)
    return CheckResult(
        article="6.6.1.2.5",
        name="Load-Induced Fatigue Resistance",
        capacity=resistance,
        demand=delta_f,
        details={"category": category, "N": n, "A": a_const,
                 "threshold": threshold,
                 "limit_state": "Fatigue I" if fatigue_i else "Fatigue II"},
    )


@article("6.8.2.1", "Tension Member Resistance")
def tension_member_resistance(
    a_g: float,
    f_y: float,
    a_n: float | None = None,
    f_u: float | None = None,
    u_shear_lag: float = 1.0,
    p_u: float | None = None,
) -> CheckResult:
    """Factored tensile resistance (6.8.2.1): lesser of yielding on the
    gross section (phi_y = 0.95) and rupture on the net section
    (phi_u = 0.80, with shear-lag factor U).  ``capacity`` holds the
    governing *factored* resistance (phi already applied — ``phi`` on the
    result is 1.0 to avoid double-counting)."""
    yield_r = 0.95 * f_y * a_g
    cases = {"yield": yield_r}
    if a_n is not None and f_u is not None:
        cases["rupture"] = 0.80 * f_u * a_n * u_shear_lag
    governing = min(cases, key=cases.get)
    return CheckResult(
        article="6.8.2.1",
        name="Tension Member Resistance",
        capacity=cases[governing],
        demand=p_u,
        details={**cases, "governing": governing},
    )


@article("6.9.4.1.1", "Compression Member Nominal Resistance")
def compression_member_resistance(
    a_g: float,
    f_y: float,
    kl_over_r: float,
    p_u: float | None = None,
    q_slender: float = 1.0,
    design_year: int | None = None,
) -> CheckResult:
    """Axial compressive resistance of a non-slender-element column
    (6.9.4.1.1): Pe = pi^2*E/(KL/r)^2 * Ag; Po = Q*Fy*Ag;
    Pn = 0.658^(Po/Pe)*Po when Pe >= 0.44*Po, else 0.877*Pe.

    ``q_slender`` is the slender-element reduction (6.9.4.2; 1.0 for
    nonslender plates).  phi_c is 0.95 (0.90 for designs before the 2015
    interim — pass ``design_year``)."""
    p_o = q_slender * f_y * a_g
    p_e = math.pi**2 * E_STEEL / kl_over_r**2 * a_g
    if p_e >= 0.44 * p_o:
        p_n = 0.658 ** (p_o / p_e) * p_o
        mode = "inelastic"
    else:
        p_n = 0.877 * p_e
        mode = "elastic"
    phi_c = 0.90 if design_year is not None and design_year < 2015 else 0.95
    return CheckResult(
        article="6.9.4.1.1",
        name="Compression Member Nominal Resistance",
        capacity=p_n,
        demand=p_u,
        phi=phi_c,
        details={"Pe": p_e, "Po": p_o, "mode": mode, "KL/r": kl_over_r},
    )


@article("6.8.2.3", "Combined Axial and Flexure")
def combined_axial_flexure(
    p_u: float,
    p_r: float,
    m_ux: float = 0.0,
    m_rx: float = math.inf,
    m_uy: float = 0.0,
    m_ry: float = math.inf,
    compression: bool = False,
) -> CheckResult:
    """Interaction of axial force and flexure: 6.8.2.3 for tension members,
    6.9.2.2 for compression members (``compression=True``; pass the
    already-magnified moments).  With Pu/Pr < 0.2 the sum is
    ``Pu/(2 Pr) + (Mux/Mrx + Muy/Mry)``, otherwise
    ``Pu/Pr + 8/9 (Mux/Mrx + Muy/Mry)``; it must not exceed 1.0
    (``capacity`` 1.0, ``demand`` the sum)."""
    ratio = abs(p_u) / p_r
    flex = abs(m_ux) / m_rx + abs(m_uy) / m_ry
    if ratio < 0.2:
        total, eq = ratio / 2.0 + flex, "-1"
    else:
        total, eq = ratio + 8.0 / 9.0 * flex, "-2"
    art = "6.9.2.2" if compression else "6.8.2.3"
    return CheckResult(article=art, name="Combined Axial and Flexure",
                       capacity=1.0, demand=total,
                       details={"Pu/Pr": ratio, "M/Mr": flex,
                                "equation": f"{art}{eq}"})


def modified_slenderness(kl_over_r: float, a: float, r_i: float) -> float:
    """Modified slenderness of a built-up member whose components are
    connected by lacing, batten plates or intermittent fasteners
    (Eq. C6.9.4.3.1-1): ``sqrt((KL/r)_o^2 + (a/r_i)^2)`` with ``a`` the
    connector spacing and ``r_i`` the least radius of gyration of one
    component."""
    return math.hypot(kl_over_r, a / r_i)


@article("6.12.2.2.1", "Weak-Axis Flexure of I- and H-Shapes")
def weak_axis_flexure(
    b_f: float,
    t_f: float,
    f_yf: float,
    z_y: float,
    s_y: float,
    m_u: float | None = None,
) -> CheckResult:
    """Nominal weak-axis flexural resistance of an I- or H-shape or of two
    channel flanges joined by a web (6.12.2.2.1): ``Mp = Fyf Zy`` while the
    flange slenderness bf/2tf <= 0.38 sqrt(E/Fyf), then Eq. 6.12.2.2.1-2
    toward ``Fyf Sy`` at 0.83 sqrt(E/Fyf).  phi_f = 1.00; kip-in."""
    lam = b_f / (2.0 * t_f)
    lam_p = 0.38 * math.sqrt(E_STEEL / f_yf)
    lam_r = 0.83 * math.sqrt(E_STEEL / f_yf)
    m_p = f_yf * z_y
    if lam <= lam_p:
        m_n, mode = m_p, "compact"
    elif lam <= lam_r:
        m_n = (1.0 - (1.0 - s_y / z_y) * (lam - lam_p)
               / (0.45 * math.sqrt(E_STEEL / f_yf))) * m_p
        mode = "noncompact"
    else:
        raise ValueError(f"flange slenderness {lam:.2f} > lambda_rf {lam_r:.2f}: "
                         f"slender flange, outside 6.12.2.2.1")
    return CheckResult(article="6.12.2.2.1",
                       name="Weak-Axis Flexure of I- and H-Shapes",
                       capacity=m_n, demand=m_u, phi=1.0,
                       details={"lambda_f": lam, "lambda_pf": lam_p,
                                "lambda_rf": lam_r, "Mp": m_p, "mode": mode})


def box_torsion_constant(b: float, h: float, t_flange: float, t_web: float) -> float:
    """St. Venant J of a thin-walled single-cell box with webs ``t_web``
    apart ``b`` (centre to centre) and flanges ``t_flange`` apart ``h``
    (AISC Design Guide 9, Table 3.1): ``2 tf tw b^2 h^2 / (tw b + tf h)``."""
    return 2.0 * t_flange * t_web * b * b * h * h / (t_web * b + t_flange * h)


@article("C6.12.2.2.2 (7th Ed.)", "Box-Section Flexure (7th Edition)")
def box_flexure_7th(
    f_y: float,
    s: float,
    i_y: float,
    j: float,
    length: float,
    m_u: float | None = None,
    g: float | None = None,
) -> CheckResult:
    """Flexural resistance of a box-shaped member by the 7th Edition
    (2014) commentary of 6.12.2.2.2, the form used for rating and
    strengthening older laced box members (FHWA HIF-18-042):
    ``M_CR = (pi/L) sqrt(E Iy G J)`` (Eq. C6.12.2.2.2-1) and
    ``Mn = Fy S (1 - Fy S / (4 M_CR))`` (Eq. C6.12.2.2.2-4), with
    G = 0.385 E.  The 9th Edition replaced this with Article 6.12.2.2.2's
    local-buckling based provisions.  kip-in."""
    g = 0.385 * E_STEEL if g is None else g
    m_cr = math.pi / length * math.sqrt(E_STEEL * i_y * g * j)
    m_y = f_y * s
    m_n = m_y * (1.0 - m_y / (4.0 * m_cr))
    return CheckResult(article="C6.12.2.2.2 (7th Ed.)",
                       name="Box-Section Flexure (7th Edition)",
                       capacity=m_n, demand=m_u, phi=1.0,
                       details={"M_CR": m_cr, "My": m_y, "G": g})


# Table 6.13.2.8-2 minimum bolt pretension Pt (kip)
BOLT_PRETENSION = {
    ("A325", 0.625): 19.0, ("A325", 0.75): 28.0, ("A325", 0.875): 39.0,
    ("A325", 1.0): 51.0, ("A325", 1.125): 56.0, ("A325", 1.25): 71.0,
    ("A490", 0.625): 24.0, ("A490", 0.75): 35.0, ("A490", 0.875): 49.0,
    ("A490", 1.0): 64.0, ("A490", 1.125): 80.0, ("A490", 1.25): 102.0,
}

# Kh (hole size) and Ks (surface class) factors of 6.13.2.8
SLIP_HOLE_FACTORS = {"standard": 1.0, "oversize": 0.85,
                     "long_slot_perp": 0.70, "long_slot_par": 0.60}
SLIP_SURFACE_FACTORS = {"A": 0.33, "B": 0.50, "C": 0.33}


@article("6.13.2.7", "Bolt Shear Resistance")
def bolt_shear_resistance(
    d_bolt: float,
    f_ub: float,
    n_planes: int = 1,
    threads_excluded: bool = True,
    v_u: float | None = None,
    long_joint: bool = False,
    design_year: int | None = None,
) -> CheckResult:
    """Shear resistance of a high-strength bolt (6.13.2.7):
    Rn = C*Ab*Fub*Ns; joints longer than 38 in between extreme bolts take a
    0.83 reduction.  phi_s = 0.80.

    The shear-strength coefficient C was raised in the 8th Edition (2017):
    ``design_year`` >= 2017 uses C = 0.56 (threads excluded) / 0.45 (threads
    included); earlier editions (the default) use 0.48 / 0.38."""
    a_b = math.pi * d_bolt**2 / 4.0
    if design_year is not None and design_year >= 2017:
        factor = 0.56 if threads_excluded else 0.45
    else:
        factor = 0.48 if threads_excluded else 0.38
    r_n = factor * a_b * f_ub * n_planes
    if long_joint:
        r_n *= 0.83
    return CheckResult(
        article="6.13.2.7",
        name="Bolt Shear Resistance",
        capacity=r_n,
        demand=v_u,
        phi=0.80,
        details={"Ab": a_b, "factor": factor, "Ns": n_planes},
    )


@article("6.13.2.8", "Bolt Slip Resistance")
def bolt_slip_resistance(
    bolt_grade: str,
    d_bolt: float,
    n_planes: int = 1,
    hole_type: str = "standard",
    surface_class: str = "B",
    v_serv: float | None = None,
    duplex_galvanized: bool = False,
) -> CheckResult:
    """Slip resistance of one bolt in a slip-critical connection
    (6.13.2.8-1): Rn = Kc*Kh*Ks*Ns*Pt, checked under Service II (phi = 1.0).
    Pretension Pt from Table 6.13.2.8-2.

    The creep factor Kc (10th Edition) is 0.80 for Class C (galvanized)
    faying surfaces and for duplex coatings over a galvanized subsurface
    (``duplex_galvanized``), 1.0 otherwise."""
    p_t = BOLT_PRETENSION[(bolt_grade, d_bolt)]
    k_h = SLIP_HOLE_FACTORS[hole_type]
    k_s = SLIP_SURFACE_FACTORS[surface_class]
    k_c = 0.80 if (surface_class == "C" or duplex_galvanized) else 1.0
    r_n = k_c * k_h * k_s * n_planes * p_t
    return CheckResult(
        article="6.13.2.8",
        name="Bolt Slip Resistance",
        capacity=r_n,
        demand=v_serv,
        details={"Pt": p_t, "Kc": k_c, "Kh": k_h, "Ks": k_s, "Ns": n_planes},
    )


@article("6.13.2.9", "Bearing Resistance at Bolt Holes")
def bolt_bearing_resistance(
    d_bolt: float,
    t_ply: float,
    f_u_ply: float,
    clear_distance: float,
    v_u: float | None = None,
) -> CheckResult:
    """Bearing on connected material at a bolt hole (6.13.2.9):
    Rn = 2.4*d*t*Fu when the clear distance to the next hole or end is at
    least 2.0*d, else Rn = 1.2*Lc*t*Fu.  phi_bb = 0.80."""
    if clear_distance >= 2.0 * d_bolt:
        r_n = 2.4 * d_bolt * t_ply * f_u_ply
        deformation_governed = True
    else:
        r_n = 1.2 * clear_distance * t_ply * f_u_ply
        deformation_governed = False
    return CheckResult(
        article="6.13.2.9",
        name="Bearing Resistance at Bolt Holes",
        capacity=r_n,
        demand=v_u,
        phi=0.80,
        details={"clear_distance": clear_distance,
                 "full_bearing": deformation_governed},
    )


@article("6.10.10.4", "Shear Connector Strength Limit State")
def shear_connector_strength(
    d_stud: float,
    f_c: float,
    e_c: float,
    nominal_force: float | None = None,
    f_u_stud: float = 60.0,
) -> CheckResult:
    """Nominal resistance of one stud shear connector (6.10.10.4.3-1):
    Qn = 0.5*Asc*sqrt(f'c*Ec) <= Asc*Fu, phi_sc = 0.85.

    Pass the interface force ``nominal_force`` P (6.10.10.4.2 — the lesser
    of the deck crushing and steel yielding forces, kip) to get the
    required connector count in ``details``."""
    a_sc = math.pi * d_stud**2 / 4.0
    q_n = min(0.5 * a_sc * math.sqrt(f_c * e_c), a_sc * f_u_stud)
    details = {"Asc": a_sc, "Qn": q_n}
    if nominal_force is not None:
        details["n_required"] = nominal_force / (0.85 * q_n)
    return CheckResult(
        article="6.10.10.4",
        name="Shear Connector Strength Limit State",
        capacity=q_n,
        phi=0.85,
        details=details,
    )


@article("6.10.10.1.2", "Shear Connector Fatigue Pitch")
def shear_connector_fatigue_pitch(
    d_stud: float,
    n_per_row: int,
    shear_flow: float,
    n_cycles: float | None = None,
    pitch: float | None = None,
) -> CheckResult:
    """Required stud pitch for fatigue (6.10.10.1.2): p <= n*Zr/Vsr, where
    the fatigue resistance of one stud is Zr = 5.5*d^2 for Fatigue I
    (infinite life, ``n_cycles`` omitted) or Zr = alpha*d^2 with
    alpha = 34.5 - 4.28*log10(N) for Fatigue II (6.10.10.2).  (The old
    4th-edition single-combination rule floored alpha*d^2 at 5.5*d^2/2;
    the floor died with the Fatigue I/II split.)

    ``shear_flow`` is the fatigue shear flow Vsr = Vf*Q/I (kip/in).
    ``capacity`` is the maximum permitted pitch (in); pass the actual
    ``pitch`` as demand — note larger-is-worse, so ok means pitch <= max."""
    if n_cycles is None:
        z_r = 5.5 * d_stud**2
    else:
        alpha = 34.5 - 4.28 * math.log10(n_cycles)
        z_r = alpha * d_stud**2
    p_max = n_per_row * z_r / shear_flow
    return CheckResult(
        article="6.10.10.1.2",
        name="Shear Connector Fatigue Pitch",
        capacity=p_max,
        demand=pitch,
        details={"Zr": z_r, "shear_flow": shear_flow},
    )


@article("6.13.4", "Block Shear Rupture Resistance")
def block_shear_resistance(
    a_vg: float,
    a_vn: float,
    a_tn: float,
    f_y: float,
    f_u: float,
    p_u: float | None = None,
    u_bs: float = 1.0,
    punched_holes: bool = False,
) -> CheckResult:
    """Block shear rupture (6.13.4-1):
    Rn = Rp*(0.58*Fu*Avn + Ubs*Fu*Atn), not to exceed
    Rp*(0.58*Fy*Avg + Ubs*Fu*Atn); phi_bs = 0.80.

    ``u_bs`` = 1.0 for uniform tension stress, 0.5 for nonuniform;
    Rp = 0.9 for punched holes, 1.0 drilled."""
    r_p = 0.9 if punched_holes else 1.0
    r_n = r_p * min(
        0.58 * f_u * a_vn + u_bs * f_u * a_tn,
        0.58 * f_y * a_vg + u_bs * f_u * a_tn,
    )
    return CheckResult(
        article="6.13.4",
        name="Block Shear Rupture Resistance",
        capacity=r_n,
        demand=p_u,
        phi=0.80,
        details={"Rp": r_p, "Ubs": u_bs},
    )


@article("6.13.3.2.4", "Fillet Weld Shear Resistance")
def fillet_weld_resistance(
    leg_size: float,
    f_exx: float = 70.0,
    length: float = 1.0,
    v_u: float | None = None,
) -> CheckResult:
    """Factored shear resistance of a fillet weld on its effective throat
    (6.13.3.2.4b): Rr = 0.6*phi_e2*Fexx with phi_e2 = 0.80, applied to the
    throat 0.707*leg.  ``capacity`` holds the factored resistance for the
    given ``length`` of weld (kip), so ``phi`` is 1.0 on the result."""
    throat = 0.707 * leg_size
    r_r = 0.6 * 0.80 * f_exx * throat * length
    return CheckResult(
        article="6.13.3.2.4",
        name="Fillet Weld Shear Resistance",
        capacity=r_r,
        demand=v_u,
        details={"throat": throat, "per_inch": 0.6 * 0.80 * f_exx * throat},
    )


@article("6.10.1.9.1", "Web Bend-Buckling Resistance")
def web_bend_buckling(
    d_web: float,
    t_w: float,
    d_c: float,
    f_yc: float,
    f_yw: float,
    r_h: float = 1.0,
) -> CheckResult:
    """Nominal web bend-buckling resistance (6.10.1.9.1-1):
    Fcrw = 0.9*E*k/(D/tw)^2 with k = 9/(Dc/D)^2, capped at
    min(Rh*Fyc, Fyw/0.7).  ``capacity`` holds Fcrw (ksi)."""
    k = 9.0 / (d_c / d_web) ** 2
    f_crw = min(
        0.9 * E_STEEL * k / (d_web / t_w) ** 2,
        r_h * f_yc,
        f_yw / 0.7,
    )
    return CheckResult(
        article="6.10.1.9.1",
        name="Web Bend-Buckling Resistance",
        capacity=f_crw,
        details={"k": k, "D/tw": d_web / t_w},
    )


@article("6.10.3.2.1", "Constructibility — Discretely Braced Compression Flange")
def constructibility_compression_flange(
    f_bu: float,
    f_l: float,
    f_yc: float,
    f_nc: float,
    f_crw: float | None = None,
    r_h: float = 1.0,
    slender_web: bool = False,
) -> CheckResult:
    """Constructibility checks on a discretely braced compression flange
    during deck placement (6.10.3.2.1): flange yielding
    fbu + fl <= phi*Rh*Fyc (skipped for slender webs), flange buckling
    fbu + fl/3 <= phi*Fnc, and web bend-buckling fbu <= phi*Fcrw.

    ``f_bu``/``f_l`` are the factored vertical-bending and lateral-bending
    flange stresses under the steel-plus-wet-concrete condition; ``f_nc``
    from the 6.10.8.2 functions and ``f_crw`` from
    :func:`web_bend_buckling`.  ``capacity``/``demand`` carry the governing
    case; all three appear in ``details``."""
    cases = {}
    if not slender_web:
        cases["yielding"] = (PHI_F * r_h * f_yc, f_bu + f_l)
    cases["buckling"] = (PHI_F * f_nc, f_bu + f_l / 3.0)
    if f_crw is not None:
        cases["web_bend_buckling"] = (PHI_F * f_crw, f_bu)
    governing = min(
        cases, key=lambda c: cases[c][0] / cases[c][1] if cases[c][1] else 1e9
    )
    cap, dem = cases[governing]
    return CheckResult(
        article="6.10.3.2.1",
        name="Constructibility — Discretely Braced Compression Flange",
        capacity=cap,
        demand=dem,
        phi=1.0,  # phi folded into each case above
        details={**{k: {"capacity": v[0], "demand": v[1]}
                    for k, v in cases.items()},
                 "governing": governing},
    )


@article("6.10.11.2.3", "Bearing Stiffener Bearing Resistance")
def bearing_stiffener_resistance(
    a_pn: float,
    f_ys: float,
    r_u: float | None = None,
) -> CheckResult:
    """Bearing resistance of fitted bearing-stiffener ends
    (6.10.11.2.3-1): Rn = 1.4*Apn*Fys with phi_b = 1.0.

    ``a_pn`` is the stiffener area in contact with the flange after the
    clip for the web-to-flange weld (in^2).  The companion axial check of
    the stiffener-plus-web effective column (6.10.11.2.4) composes with
    :func:`compression_member_resistance` using KL = 0.75*D and the
    effective-section properties."""
    r_n = 1.4 * a_pn * f_ys
    return CheckResult(
        article="6.10.11.2.3",
        name="Bearing Stiffener Bearing Resistance",
        capacity=r_n,
        demand=r_u,
        phi=1.0,
        details={"Apn": a_pn},
    )


@article("6.10.9", "Web Shear Resistance")
def web_shear_resistance(
    d_web: float,
    t_w: float,
    f_yw: float,
    v_u: float | None = None,
    d_o: float | None = None,
    tension_field: bool = False,
    b_fc: float | None = None,
    t_fc: float | None = None,
    b_ft: float | None = None,
    t_ft: float | None = None,
    web_loss_area: float = 0.0,
) -> CheckResult:
    """Nominal web shear resistance Vn (6.10.9).

    Unstiffened webs (``d_o`` is None): Vn = C*Vp (6.10.9.2-1).  Stiffened
    interior panels with ``tension_field=True`` use 6.10.9.3.2-2, downgraded
    to 6.10.9.3.2-8 when the panel fails the flange-proportion limit
    2*D*tw/(bfc*tfc + bft*tft) <= 2.5.  ``d_web`` is the web depth D (in),
    ``d_o`` the transverse stiffener spacing (in), ``v_u`` the factored
    shear demand (kip).

    ``web_loss_area`` (in^2) is corroded web area lost over the panel: the
    plastic shear force is taken on the remaining area while k and C stay
    those of the full web, the usual rating treatment of localized loss
    (FHWA HIF-18-043).
    """
    v_p = 0.58 * f_yw * (d_web * t_w - web_loss_area)  # plastic shear (6.10.9.2-2)
    k = 5.0 if d_o is None else 5.0 + 5.0 / (d_o / d_web) ** 2  # 6.10.9.3.2-7

    slenderness = d_web / t_w
    ek_fyw = math.sqrt(E_STEEL * k / f_yw)
    if slenderness <= 1.12 * ek_fyw:
        c = 1.0  # 6.10.9.3.2-4
    elif slenderness <= 1.40 * ek_fyw:
        c = 1.12 / slenderness * ek_fyw  # 6.10.9.3.2-5
    else:
        c = 1.57 / slenderness**2 * (E_STEEL * k / f_yw)  # 6.10.9.3.2-6

    details = {"Vp": v_p, "C": c, "k": k}
    if d_o is not None and tension_field:
        if None in (b_fc, t_fc, b_ft, t_ft):
            raise ValueError(
                "tension_field=True requires flange dimensions "
                "b_fc, t_fc, b_ft, t_ft for the 6.10.9.3.2 proportion check"
            )
        post_buckling = 0.87 * (1.0 - c)
        if 2.0 * d_web * t_w / (b_fc * t_fc + b_ft * t_ft) <= 2.5:
            v_n = v_p * (c + post_buckling / math.sqrt(1.0 + (d_o / d_web) ** 2))
            details["equation"] = "6.10.9.3.2-2"
        else:
            v_n = v_p * (
                c
                + post_buckling
                / (math.sqrt(1.0 + (d_o / d_web) ** 2) + d_o / d_web)
            )
            details["equation"] = "6.10.9.3.2-8"
    else:
        v_n = c * v_p
        details["equation"] = "6.10.9.2-1" if d_o is None else "6.10.9.3.2-1"

    return CheckResult(
        article="6.10.9",
        name="Web Shear Resistance",
        capacity=v_n,
        demand=v_u,
        phi=PHI_V,
        details=details,
    )


@article("6.10.11.1.2", "Transverse Stiffener Projecting Width")
def transverse_stiffener_width(
    b_t: float,
    t_p: float,
    d_web: float,
    b_f: float,
) -> CheckResult:
    """Transverse-stiffener projecting-width limits (6.10.11.1.2):
    b_t >= 2.0 + D/30 (6.10.11.1.2-1) and 16*t_p >= b_t >= b_f/4
    (6.10.11.1.2-2), with ``b_f`` the full width of the widest compression
    flange in the field section.  The governing (minimum) margin is the
    reported ratio."""
    lo_depth = 2.0 + d_web / 30.0
    lo_flange = b_f / 4.0
    hi = 16.0 * t_p
    m_lo_depth = b_t / lo_depth
    m_lo_flange = b_t / lo_flange
    m_hi = hi / b_t if b_t > 0 else float("inf")
    governing = min(m_lo_depth, m_lo_flange, m_hi)
    return CheckResult(
        article="6.10.11.1.2",
        name="Transverse Stiffener Projecting Width",
        capacity=governing,
        demand=1.0,
        phi=1.0,
        details={"b_t_min_depth": lo_depth, "b_t_min_flange": lo_flange,
                 "b_t_max": hi,
                 "governing": ("depth" if governing == m_lo_depth else
                               "flange" if governing == m_lo_flange
                               else "thickness")},
    )


@article("6.10.11.1.3", "Transverse Stiffener Moment of Inertia")
def transverse_stiffener_inertia(
    moment_of_inertia: float,
    b_t: float,
    t_p: float,
    d_web: float,
    t_w: float,
    d_o: float,
    f_yw: float,
    f_ys: float,
    tension_field: bool = False,
) -> CheckResult:
    """Transverse-stiffener moment-of-inertia requirement (6.10.11.1.3).

    ``moment_of_inertia`` is the provided I_t (in^4; single stiffener taken
    about the web face, a pair about the web mid-thickness).

    * I_t1 = b * tw^3 * J with b = min(d_o, D) and
      J = 2.5/(d_o/D)^2 - 2.0 >= 0.5 (6.10.11.1.3-1/-2)
    * I_t2 = D^4 * rho_t^1.3 / 40 * (Fyw/E)^1.5 (6.10.11.1.3-3), with
      rho_t = max(Fyw/Fcrs, 1.0) and
      Fcrs = 0.31 E/(b_t/t_p)^2 <= Fys (6.10.11.1.3-4)

    Web shear buckling only (``tension_field=False``): I_t1 governs.  When the
    web's postbuckling (tension-field) resistance is relied on and I_t2 > I_t1,
    the requirement rises toward I_t2 — this implementation conservatively
    requires I_t2 on that path (the spec permits a shear-demand interpolation);
    ``validate_against_brr`` is set for the tension-field path."""
    j = max(2.5 / (d_o / d_web) ** 2 - 2.0, 0.5)
    i_t1 = min(d_o, d_web) * t_w**3 * j
    f_crs = min(0.31 * E_STEEL / (b_t / t_p) ** 2, f_ys)
    rho_t = max(f_yw / f_crs, 1.0)
    i_t2 = d_web**4 * rho_t**1.3 / 40.0 * (f_yw / E_STEEL) ** 1.5

    required = i_t1
    if tension_field and i_t2 > i_t1:
        required = i_t2
    details = {"I_t1": i_t1, "I_t2": i_t2, "J": j, "Fcrs": f_crs,
               "rho_t": rho_t, "governing": "I_t2" if required == i_t2
               and required != i_t1 else "I_t1"}
    if tension_field:
        details["validate_against_brr"] = True
    return CheckResult(
        article="6.10.11.1.3",
        name="Transverse Stiffener Moment of Inertia",
        capacity=moment_of_inertia,
        demand=required,
        phi=1.0,
        details=details,
    )


@article("6.10.11.2.2", "Bearing Stiffener Projecting Width")
def bearing_stiffener_width(
    b_t: float,
    t_p: float,
    f_ys: float,
) -> CheckResult:
    """Bearing-stiffener projecting-width limit (6.10.11.2.2-1):
    b_t <= 0.48 * t_p * sqrt(E/Fys)."""
    limit = 0.48 * t_p * math.sqrt(E_STEEL / f_ys)
    return CheckResult(
        article="6.10.11.2.2",
        name="Bearing Stiffener Projecting Width",
        capacity=limit,
        demand=b_t,
        phi=1.0,
        details={"b_t_max": limit},
    )


@article("6.10.11.2.4", "Bearing Stiffener Effective Column")
def bearing_stiffener_effective_column(
    b_t: float,
    t_p: float,
    t_w: float,
    d_web: float,
    f_ys: float,
    pairs: int = 1,
    p_u: float | None = None,
    design_year: int | None = None,
) -> CheckResult:
    """Axial resistance of the bearing-stiffener effective column
    (6.10.11.2.4): the stiffener plates acting with a web strip extending
    9*tw to each side, radius of gyration about the web mid-thickness,
    KL = 0.75*D, resistance per 6.9.4.1.1 (Q = 1.0 — bearing stiffeners
    are exempt from the slender-element reduction)."""
    strip_len = 18.0 * t_w + pairs * t_p            # 9tw each side + plates
    a_g = 2.0 * pairs * b_t * t_p + strip_len * t_w
    # plates about the web mid-thickness (each at tw/2 + b_t/2 offset)
    offset = t_w / 2.0 + b_t / 2.0
    i_plates = 2.0 * pairs * (t_p * b_t**3 / 12.0 + t_p * b_t * offset**2)
    i_strip = strip_len * t_w**3 / 12.0
    r = math.sqrt((i_plates + i_strip) / a_g)
    kl_over_r = 0.75 * d_web / r
    base = compression_member_resistance(
        a_g=a_g, f_y=f_ys, kl_over_r=kl_over_r, p_u=p_u,
        design_year=design_year)
    return CheckResult(
        article="6.10.11.2.4",
        name="Bearing Stiffener Effective Column",
        capacity=base.capacity,
        demand=p_u,
        phi=base.phi,
        details={**base.details, "Ag": a_g, "r": r, "strip_len": strip_len},
    )


@article("6.10.8.2.1", "Compression Flange Flexural Resistance")
def compression_flange_resistance(
    l_b: float,
    b_fc: float,
    t_fc: float,
    d_c: float,
    t_w: float,
    f_yc: float,
    f_yw: float,
    c_b: float = 1.0,
    f_bu: float | None = None,
    r_b: float = 1.0,
    r_h: float = 1.0,
) -> CheckResult:
    """Compression-flange flexural resistance Fnc (6.10.8.2.1-1): the
    smaller of local buckling (6.10.8.2.2) and lateral-torsional buckling
    (6.10.8.2.3)."""
    flb = flange_local_buckling_resistance(
        b_fc=b_fc, t_fc=t_fc, f_yc=f_yc, f_yw=f_yw, r_b=r_b, r_h=r_h)
    ltb = lateral_torsional_buckling_resistance(
        l_b=l_b, b_fc=b_fc, t_fc=t_fc, d_c=d_c, t_w=t_w, f_yc=f_yc,
        f_yw=f_yw, c_b=c_b, r_b=r_b, r_h=r_h)
    f_nc = min(flb.capacity, ltb.capacity)
    return CheckResult(
        article="6.10.8.2.1",
        name="Compression Flange Flexural Resistance",
        capacity=f_nc,
        demand=f_bu,
        phi=PHI_F,
        details={"Fnc_FLB": flb.capacity, "Fnc_LTB": ltb.capacity,
                 "governing": "FLB" if flb.capacity <= ltb.capacity
                 else "LTB"},
    )


@article("6.10.8.1.1", "Discretely Braced Compression Flange")
def discretely_braced_compression_flange(
    f_nc: float,
    f_bu: float,
    f_l: float = 0.0,
    f_yf: float | None = None,
) -> CheckResult:
    """Discretely braced compression-flange check (6.10.8.1.1-1):
    f_bu + f_l/3 <= phi_f * Fnc, with ``f_nc`` from 6.10.8.2.1 and ``f_l``
    the flange lateral bending stress.  When ``f_yf`` is given the 6.10.1.6
    limit f_l <= 0.6*Fyf is also verified (reported in details)."""
    demand = f_bu + f_l / 3.0
    details = {"fl": f_l}
    if f_yf is not None:
        details["fl_limit"] = 0.6 * f_yf
        details["fl_ok"] = f_l <= 0.6 * f_yf
    return CheckResult(
        article="6.10.8.1.1",
        name="Discretely Braced Compression Flange",
        capacity=f_nc,
        demand=demand,
        phi=PHI_F,
        details=details,
    )


@article("6.10.8.1.3", "Continuously Braced Flanges")
def continuously_braced_flange(
    f_yf: float,
    f_bu: float | None = None,
    r_h: float = 1.0,
) -> CheckResult:
    """Continuously braced flange in tension or compression
    (6.10.8.1.3-1): f_bu <= phi_f * Rh * Fyf (no lateral-bending term — the
    deck braces the flange continuously)."""
    return CheckResult(
        article="6.10.8.1.3",
        name="Continuously Braced Flanges",
        capacity=r_h * f_yf,
        demand=f_bu,
        phi=PHI_F,
        details={"Rh": r_h},
    )


@article("6.10.10.2", "Shear Connector Fatigue Resistance")
def shear_connector_fatigue_resistance(
    d_stud: float,
    n_cycles: float | None = None,
) -> CheckResult:
    """Fatigue shear resistance of one stud (6.10.10.2): Fatigue I
    (infinite life, ``n_cycles=None``): Zr = 5.5*d^2 (6.10.10.2-1).
    Fatigue II: Zr = alpha*d^2 with alpha = 34.5 - 4.28*log10(N)."""
    if n_cycles is None:
        z_r = 5.5 * d_stud**2
        details = {"combination": "Fatigue I"}
    else:
        alpha = 34.5 - 4.28 * math.log10(n_cycles)
        z_r = alpha * d_stud**2
        details = {"combination": "Fatigue II", "alpha": alpha}
    return CheckResult(
        article="6.10.10.2",
        name="Shear Connector Fatigue Resistance",
        capacity=z_r,
        phi=1.0,
        details=details,
    )


@article("6.10.10.3", "Shear Connector Transverse Spacing")
def shear_connector_transverse_spacing(
    d_stud: float,
    n_per_row: int,
    gauge_in: float,
    flange_width_in: float,
) -> CheckResult:
    """Transverse spacing limits for stud rows (6.10.10.3): center-to-center
    >= 4 stud diameters, and clear distance from the flange edge to the
    nearest stud >= 1.0 in.  The governing margin is the reported ratio."""
    m_gauge = (gauge_in / (4.0 * d_stud)) if n_per_row > 1 else float("inf")
    edge_clear = (flange_width_in - (n_per_row - 1) * gauge_in - d_stud) / 2.0
    m_edge = edge_clear / 1.0
    governing = min(m_gauge, m_edge)
    return CheckResult(
        article="6.10.10.3",
        name="Shear Connector Transverse Spacing",
        capacity=governing,
        demand=1.0,
        phi=1.0,
        details={"gauge_min": 4.0 * d_stud, "edge_clear": edge_clear,
                 "governing": "gauge" if governing == m_gauge else "edge"},
    )


@article("6.9.4.2.1", "Nonslender Element Width-Thickness Limit")
def nonslender_element_limit(
    b: float,
    t: float,
    f_y: float,
    k: float = 0.45,
) -> CheckResult:
    """Plate width-to-thickness limit for a nonslender compression element
    (6.9.4.2.1-1): b/t <= k*sqrt(E/Fy).  ``k`` per Table 6.9.4.2.1-1 (0.45
    outstanding angle legs / plates supported on one edge, 0.56 rolled-shape
    flanges, 1.49 stiffened webs).  Exceeding the limit means the member
    needs the slender-element Q reduction (6.9.4.2.2)."""
    limit = k * math.sqrt(E_STEEL / f_y)
    return CheckResult(
        article="6.9.4.2.1",
        name="Nonslender Element Width-Thickness Limit",
        capacity=limit,
        demand=b / t,
        phi=1.0,
        details={"k": k, "b_over_t": b / t},
    )


@article("6.13.5.3", "Connection Element Shear Resistance")
def connection_element_shear(
    a_vg: float,
    f_y: float,
    a_vn: float | None = None,
    f_u: float | None = None,
    v_u: float | None = None,
) -> CheckResult:
    """Shear resistance of a connection element — splice/gusset plate
    (6.13.5.3): gross-section yielding Rr = phi_v*0.58*Fy*Avg (phi = 1.0);
    net-section rupture Rr = phi_vu*0.58*Fu*Avn (phi = 0.80) when the net
    path is given.  The governing factored resistance is reported."""
    r_gross = 1.0 * 0.58 * f_y * a_vg
    details = {"R_gross": r_gross}
    r_gov = r_gross
    if a_vn is not None and f_u is not None:
        r_net = 0.80 * 0.58 * f_u * a_vn
        details["R_net"] = r_net
        r_gov = min(r_gross, r_net)
        details["governing"] = "gross" if r_gov == r_gross else "net"
    return CheckResult(
        article="6.13.5.3",
        name="Connection Element Shear Resistance",
        capacity=r_gov,
        demand=v_u,
        phi=1.0,
        details=details,
    )


@article("6.10.11.3", "Longitudinal Stiffener Proportions")
def longitudinal_stiffener_proportions(
    proj_width: float,
    t_s: float,
    moment_of_inertia: float,
    radius_of_gyration: float,
    d_web: float,
    t_w: float,
    d_o: float,
    f_ys: float,
    f_yc: float,
    r_h: float = 1.0,
    beta: float = 1.0,
) -> CheckResult:
    """Longitudinal web-stiffener proportioning limits (6.10.11.3).

    Three requirements, all expressed as provided/required margins; the
    governing (minimum) margin is the reported ``ratio`` (>= 1.0 passes):

    * projecting width (6.10.11.3.2-1): ``proj_width`` <= 0.48 t_s sqrt(E/Fys)
    * moment of inertia (6.10.11.3.3-1):
      ``I_l`` >= D tw^3 [2.4 (do/D)^2 - 0.13] beta
    * radius of gyration (6.10.11.3.3-4):
      ``r`` >= 0.16 do sqrt(Fys/E) / sqrt(1 - 0.6 Fyc/(Rh Fys))

    ``proj_width`` is the stiffener projecting width b_l (in), ``t_s`` its
    thickness (in), ``moment_of_inertia`` I_l about the web face (in^4),
    ``radius_of_gyration`` r (in), ``d_web`` the web depth D (in), ``d_o`` the
    transverse-stiffener/panel spacing (in), ``beta`` the curvature factor (1.0
    for straight girders, 6.10.11.3.3-2 for curved).  ``capacity``/``demand``
    carry the I_l pair (the sizing driver); the width and r margins are in
    ``details``.
    """
    width_limit = 0.48 * t_s * math.sqrt(E_STEEL / f_ys)          # 6.10.11.3.2-1
    i_required = d_web * t_w**3 * (2.4 * (d_o / d_web) ** 2 - 0.13) * beta
    r_required = (0.16 * d_o * math.sqrt(f_ys / E_STEEL)
                  / math.sqrt(1.0 - 0.6 * f_yc / (r_h * f_ys)))   # 6.10.11.3.3-4

    m_width = width_limit / proj_width if proj_width > 0 else float("inf")
    m_i = moment_of_inertia / i_required if i_required > 0 else float("inf")
    m_r = radius_of_gyration / r_required if r_required > 0 else float("inf")
    governing = min(m_width, m_i, m_r)

    # capacity/demand carry the governing margin so ratio/ok reflect the most
    # critical of the three limits; the dimensional values are in details.
    return CheckResult(
        article="6.10.11.3",
        name="Longitudinal Stiffener Proportions",
        capacity=governing,
        demand=1.0,
        phi=1.0,
        details={
            "b_l_max": width_limit, "width_ok": m_width >= 1.0,
            "width_margin": m_width,
            "I_l_req": i_required, "I_l_ok": m_i >= 1.0, "I_l_margin": m_i,
            "r_req": r_required, "r_ok": m_r >= 1.0, "r_margin": m_r,
            "governing": ("width" if governing == m_width
                          else "I_l" if governing == m_i else "r"),
        },
    )


@article("6.7.4.2.2", "Cross-Frame / Diaphragm Stability Bracing")
def stability_bracing_torsional(
    m_r: float,
    l_span: float,
    n_braces: int,
    i_eff: float,
    brace_stiffness: float,
    c_b: float = 1.0,
    l_b: float | None = None,
    phi: float = 0.80,
    h_o: float | None = None,
    full_depth: bool = True,
) -> CheckResult:
    """Torsional stability-bracing stiffness + strength for cross-frames /
    diaphragms (6.7.4.2.2, 10th Edition), the adopted Yura provisions.

    * Required torsional brace stiffness (Eq. 6.7.4.2.2-2, or -3 with
      ``full_depth=False`` for braces shallower than 0.8 of the girder or
      without full-depth connection plates):
      beta_Treq = 2.4 (3.6) L Mr^2 / (phi_sb n E I_eff C_b^2), phi_sb = 0.80
      (6.5.4.2)
    * Required brace strength (Eq. 6.7.4.2.2-14 / -15) when the flange
      centroid distance ``h_o`` is given:
      M_br = 2.4 (3.6) L Mr^2 / (n E I_eff C_b^2) x L_b / (500 h_o);
      without ``h_o`` the AISC 360 Appendix 6 form
      M_br = 0.024 Mr L / (n C_b L_b) is reported instead

    ``m_r`` is the required flexural strength Mr (kip-in), ``l_span`` the span L
    (in), ``n_braces`` the number of intermediate brace points, ``i_eff`` the
    effective lateral moment of inertia I_eff (in^4), ``brace_stiffness`` the
    provided torsional stiffness beta_T (kip-in/rad), ``c_b`` the moment
    gradient, ``l_b`` the unbraced length (in, defaults to L/(n+1)).  The
    reported ``ratio`` is the provided/required *stiffness* margin; the required
    brace moment is in ``details``.  The components of beta_T (cross-frame,
    web distortion, in-plane girder, lean-on bracing) are in
    :mod:`civilpy.structural.aashto.lrfd.stability_bracing`, validated against
    the NSBA lean-on bracing guide (B303) examples.
    """
    from civilpy.structural.aashto.lrfd import stability_bracing as sb

    if l_b is None:
        l_b = l_span / (n_braces + 1)
    beta_t_req = sb.required_stiffness(l_span, m_r, n_braces, i_eff, c_b,
                                       full_depth=full_depth, phi_sb=phi)
    if h_o is not None:
        m_br = sb.required_brace_moment(l_span, m_r, n_braces, i_eff, l_b, h_o, c_b,
                                        full_depth=full_depth)
    else:
        m_br = 0.024 * m_r * l_span / (n_braces * c_b * l_b)

    return CheckResult(
        article="6.7.4.2.2",
        name="Cross-Frame / Diaphragm Stability Bracing",
        capacity=brace_stiffness,
        demand=beta_t_req,
        phi=1.0,
        details={
            "beta_T_req": beta_t_req, "M_br_req": m_br, "L_b": l_b,
            "M_br_form": "6.7.4.2.2-14/-15" if h_o is not None else "AISC 360 App. 6",
            "validate_against_brr": True,
        },
    )


@article("6.10.6.2.2", "Composite Section Classification — Positive Flexure")
def classify_composite_positive(
    d_cp: float,
    t_w: float,
    f_yc: float,
    f_yt: float,
    d_web: float,
    straight: bool = True,
    has_longitudinal_stiffeners: bool = False,
) -> CheckResult:
    """Compact / noncompact classification of a composite section in
    positive flexure (6.10.6.2.2).  Compact requires all of: a straight
    bridge, both flange yield strengths <= 70 ksi, the web proportion
    limit of 6.10.2.1.1 (no longitudinal stiffeners), and
    2*Dcp/tw <= 3.76*sqrt(E/Fyc).

    ``d_cp`` is the depth of web in compression at the plastic moment
    (D6.3.2 — zero when the PNA is in or above the top flange, which is
    why most composite positive sections classify compact trivially).
    ``capacity`` is 1.0 when compact; per-condition booleans in details.
    """
    lam_w = 2.0 * d_cp / t_w
    lam_pw = 3.76 * math.sqrt(E_STEEL / f_yc)
    checks = {
        "straight_bridge": straight,
        "fy_flanges_le_70": max(f_yc, f_yt) <= 70.0,
        "web_proportion_61021": (not has_longitudinal_stiffeners
                                 and d_web / t_w <= 150.0),
        "web_slenderness_2Dcp_tw": lam_w <= lam_pw,
    }
    compact = all(checks.values())
    return CheckResult(
        article="6.10.6.2.2",
        name="Composite Section Classification — Positive Flexure",
        capacity=1.0 if compact else 0.0,
        demand=1.0,
        details={**checks, "2Dcp/tw": lam_w, "3.76sqrt(E/Fyc)": lam_pw,
                 "classification": "compact" if compact else "noncompact"},
    )


@article("6.10.6.2.3", "Web Classification — Negative Flexure")
def classify_web_negative(
    d_c: float,
    t_w: float,
    f_yc: float,
    f_yt: float,
    i_yc: float,
    i_yt: float,
    straight: bool = True,
) -> CheckResult:
    """Slender-web screen for composite sections in negative flexure and
    noncomposite sections (6.10.6.2.3): sections of straight bridges with
    flange yields <= 70 ksi, web slenderness 2*Dc/tw < 5.7*sqrt(E/Fyc),
    and Iyc/Iyt >= 0.3 may use the Appendix A6 provisions (web
    plastification, resistances up to Mp); anything else takes the
    slender-web 6.10.8 stress-based path.

    ``d_c`` is the *elastic* depth of web in compression (D6.3.1).
    ``capacity`` is 1.0 when A6-eligible (nonslender); details carry the
    slenderness numbers.
    """
    lam_w = 2.0 * d_c / t_w
    lam_rw = 5.7 * math.sqrt(E_STEEL / f_yc)
    checks = {
        "straight_bridge": straight,
        "fy_flanges_le_70": max(f_yc, f_yt) <= 70.0,
        "web_nonslender_2Dc_tw": lam_w < lam_rw,
        "flange_inertia_Iyc_Iyt": i_yc / i_yt >= 0.3,
    }
    eligible = all(checks.values())
    return CheckResult(
        article="6.10.6.2.3",
        name="Web Classification — Negative Flexure",
        capacity=1.0 if eligible else 0.0,
        demand=1.0,
        details={**checks, "2Dc/tw": lam_w, "5.7sqrt(E/Fyc)": lam_rw,
                 "classification": ("nonslender (A6 eligible)" if eligible
                                    else "slender web (use 6.10.8)")},
    )
