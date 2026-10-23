"""AASHTO LRFD Appendix B6 — moment redistribution from interior-pier
sections of continuous-span steel I-girders.

Instead of designing every pier section for the full elastic envelope,
B6 lets a limited share of the pier moment shift to the spans when the
section can sustain inelastic rotation: the redistribution moment Mrd is
the amount by which the elastic moment exceeds the effective plastic
moment Mpe, capped at 20% of the elastic moment.

Scope (B6.2): straight continuous I-girders with Fy <= 70 ksi and
web/flange/bracing limits enforced by the checks below.  Units: kips,
inches, ksi; moments kip-in.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math

from civilpy.structural.aashto.lrfd.core import CheckResult, article
from civilpy.structural.aashto.lrfd.steel import E_STEEL, PHI_F


@article("B6.2.1", "Moment Redistribution — Web Proportions")
def b6_web_proportions(
    d: float,
    t_w: float,
    d_c: float,
    d_cp: float,
    f_yc: float,
) -> CheckResult:
    """Web proportion limits for redistribution sections (B6.2.1):
    D/tw <= 150 (B6.2.1-1), 2Dc/tw <= 6.8*sqrt(E/Fyc) (B6.2.1-2), and
    Dcp <= 0.75D (B6.2.1-3).  ``d_c``/``d_cp`` are the elastic and
    plastic depths of web in compression (in).  ``capacity``/``demand``
    report the governing utilization (limit and actual for the worst
    ratio); ``details["satisfied"]`` is the overall verdict."""
    slender_limit = 6.8 * math.sqrt(E_STEEL / f_yc)
    checks = {
        "D/tw": (d / t_w, 150.0),
        "2Dc/tw": (2.0 * d_c / t_w, slender_limit),
        "Dcp": (d_cp, 0.75 * d),
    }
    worst = max(checks, key=lambda k: checks[k][0] / checks[k][1])
    return CheckResult(
        article="B6.2.1",
        name="Moment Redistribution — Web Proportions",
        capacity=checks[worst][1],
        demand=checks[worst][0],
        details={
            **{f"{k} (limit)": v[1] for k, v in checks.items()},
            **{k: v[0] for k, v in checks.items()},
            "governing": worst,
            "satisfied": all(v[0] <= v[1] + 1e-9 for v in checks.values()),
        },
    )


@article("B6.2.2", "Moment Redistribution — Compression Flange Proportions")
def b6_flange_proportions(
    b_fc: float,
    t_fc: float,
    d: float,
    f_yc: float,
) -> CheckResult:
    """Compression flange limits for redistribution sections (B6.2.2):
    bfc/2tfc <= 0.38*sqrt(E/Fyc) (B6.2.2-1) and bfc >= D/4.25
    (B6.2.2-2)."""
    slenderness = b_fc / (2.0 * t_fc)
    slender_limit = 0.38 * math.sqrt(E_STEEL / f_yc)
    width_min = d / 4.25
    satisfied = slenderness <= slender_limit + 1e-9 and b_fc >= width_min - 1e-9
    return CheckResult(
        article="B6.2.2",
        name="Moment Redistribution — Compression Flange Proportions",
        capacity=slender_limit,
        demand=slenderness,
        details={"bfc/2tfc": slenderness, "limit": slender_limit,
                 "bfc": b_fc, "bfc_min": width_min,
                 "satisfied": satisfied},
    )


@article("B6.2.4", "Moment Redistribution — Compression Flange Bracing")
def b6_bracing_limit(
    r_t: float,
    f_yc: float,
    m1: float,
    m2: float,
    l_b: float | None = None,
) -> CheckResult:
    """Unbraced length limit adjacent to the pier (B6.2.4-1):
    Lb <= (0.1 - 0.06*(M1/M2)) * rt*E/Fyc.

    ``m1``/``m2`` are the smaller and larger moments at the brace points
    bounding the unbraced length (kip-in, signed — same sign for single
    curvature); ``r_t`` is the effective LTB radius of gyration
    (6.10.8.2.3-9, in).  ``capacity`` is the allowed Lb (in)."""
    limit = (0.1 - 0.06 * (m1 / m2)) * r_t * E_STEEL / f_yc
    return CheckResult(
        article="B6.2.4",
        name="Moment Redistribution — Compression Flange Bracing",
        capacity=limit,
        demand=l_b,
        details={"M1/M2": m1 / m2, "rt": r_t},
    )


@article("B6.5", "Effective Plastic Moment")
def b6_effective_plastic_moment(
    m_n: float,
    b_fc: float,
    t_fc: float,
    d: float,
    f_yc: float,
    limit_state: str = "strength",
    stiffener_within_d_over_2: bool = False,
    d_cp: float | None = None,
    t_w: float | None = None,
) -> CheckResult:
    """Effective plastic moment Mpe of an interior-pier section (B6.5).

    ``m_n`` is the section's nominal negative-flexure resistance as a
    moment (min of the flange capacities from 6.10.8 or Appendix A6,
    kip-in).  Sections with enhanced moment-rotation characteristics —
    a transverse stiffener within D/2 of the pier, or an ultracompact
    web with 2Dcp/tw <= 2.3*sqrt(E/Fyc) (B6.5.1-1) — reach Mpe = Mn at
    the service limit state (B6.5.1-2) and the 2.78-coefficient
    reduction at strength (B6.5.1-3); all other sections use the 2.90
    (service, B6.5.2-1) or 2.63 (strength, B6.5.2-2) coefficient.

    Pass ``d_cp`` (plastic depth of web in compression) and ``t_w`` to
    evaluate the ultracompact-web alternative; ``capacity`` is Mpe.
    """
    if limit_state not in ("service", "strength"):
        raise ValueError("limit_state must be 'service' or 'strength'")
    ultracompact = False
    if d_cp is not None and t_w is not None:
        ultracompact = 2.0 * d_cp / t_w <= 2.3 * math.sqrt(E_STEEL / f_yc)
    enhanced = stiffener_within_d_over_2 or ultracompact

    beta = b_fc / t_fc * math.sqrt(f_yc / E_STEEL)
    delta = d / b_fc

    def factor(coefficient: float) -> float:
        return coefficient - 2.3 * beta - 0.35 * delta + 0.39 * beta * delta

    if enhanced and limit_state == "service":
        f = 1.0
        equation = "B6.5.1-2"
    elif enhanced:
        f = factor(2.78)
        equation = "B6.5.1-3"
    else:
        f = factor(2.90 if limit_state == "service" else 2.63)
        equation = "B6.5.2-1" if limit_state == "service" else "B6.5.2-2"
    m_pe = min(f * m_n, m_n)

    return CheckResult(
        article="B6.5",
        name="Effective Plastic Moment",
        capacity=m_pe,
        details={"enhanced": enhanced, "ultracompact_web": ultracompact,
                 "equation": equation, "Mpe/Mn": m_pe / m_n, "factor": f,
                 "Mn": m_n},
    )


@article("B6.4.2.1", "Redistribution Moment at Interior-Pier Sections")
def b6_redistribution_moment(
    m_e: float,
    m_pe: float,
    limit_state: str = "strength",
    f_l: float = 0.0,
    s_x: float = 0.0,
) -> CheckResult:
    """Redistribution moment Mrd at an interior-pier section.

    At the service limit state (B6.3.3.1): ``Mrd = |Me| - Mpe``.  At
    strength (B6.4.2.1): ``Mrd = |Me| + fl*Sx/3 - phi_f*Mpe``, evaluated
    for each flange (pass the governing ``f_l``/``s_x``; zero when
    flange lateral bending is negligible).  In both cases
    ``0 <= Mrd <= 0.2|Me|`` — when the computed Mrd exceeds the 20% cap,
    redistribution is not permitted and the section must satisfy the
    ordinary elastic checks (``details["permitted"]`` is False).

    ``m_e`` is the elastic pier moment from the factored envelope
    (kip-in, sign ignored); ``capacity`` is the usable Mrd (kip-in).
    """
    if limit_state not in ("service", "strength"):
        raise ValueError("limit_state must be 'service' or 'strength'")
    me = abs(m_e)
    if limit_state == "service":
        m_rd = me - m_pe
        equation = "B6.3.3.1-1"
    else:
        m_rd = me + f_l * s_x / 3.0 - PHI_F * m_pe
        equation = "B6.4.2.1-1"
    m_rd = max(m_rd, 0.0)
    cap = 0.2 * me
    permitted = m_rd <= cap + 1e-9
    return CheckResult(
        article="B6.4.2.1" if limit_state == "strength" else "B6.3.3.1",
        name="Redistribution Moment at Interior-Pier Sections",
        capacity=m_rd if permitted else 0.0,
        details={"Mrd_computed": m_rd, "0.2|Me|": cap,
                 "permitted": permitted, "equation": equation,
                 "limit_state": limit_state},
    )


@article("B6.6.2", "Moment-Rotation Model (Refined Method)")
def b6_rotation_limit(
    b_fc: float,
    t_fc: float,
    d: float,
    f_yc: float,
) -> CheckResult:
    """theta_RL, the plastic rotation at which the moment of a pier section
    without enhanced moment-rotation characteristics begins to drop below
    Mn (Eq. B6.6.2-2, radians):
    ``0.128 - 0.143 beta - 0.0216 D/bfc + 0.0241 beta D/bfc`` with
    ``beta = (bfc/tfc) sqrt(Fyc/E)``.  ``capacity`` is theta_RL."""
    beta = b_fc / t_fc * math.sqrt(f_yc / E_STEEL)
    delta = d / b_fc
    theta = 0.128 - 0.143 * beta - 0.0216 * delta + 0.0241 * beta * delta
    return CheckResult(article="B6.6.2", name="Moment-Rotation Model (Refined Method)",
                       capacity=theta, details={"beta": beta, "D/bfc": delta})


def b6_refined_effective_moment(y_intercept: float, x_intercept: float,
                                theta_rl: float) -> dict:
    """Intersection of a continuity line with the moment-rotation curve of
    Fig. B6.6.2-1 (B6.6.1): the continuity relationship of the girder runs
    from ``M / phi Mn = y_intercept`` at zero rotation (the elastic pier
    moment over phi Mn) to zero moment at ``x_intercept`` (rad, from the
    structure's response to unit plastic rotation); the section follows
    ``M / Mn = 0.7 + 60 theta_p`` up to 0.005 rad, then Mn to ``theta_rl``.
    Returns theta_p and M / phi Mn (= Mpe / phi Mn).  Intersections past
    theta_RL (the unloading branch) are refused."""
    slope = y_intercept / x_intercept
    theta = (y_intercept - 0.7) / (60.0 + slope)
    if theta <= 0.0:
        return {"theta_p": 0.0, "M/phiMn": y_intercept, "branch": "elastic"}
    if theta <= 0.005:
        return {"theta_p": theta, "M/phiMn": 0.7 + 60.0 * theta, "branch": "rising"}
    theta = (y_intercept - 1.0) / slope
    if theta > theta_rl:
        raise ValueError("continuity line meets the curve past theta_RL (unloading branch)")
    return {"theta_p": theta, "M/phiMn": 1.0, "branch": "plateau"}
