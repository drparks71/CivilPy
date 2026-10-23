#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AASHTO LRFD Appendix A6 — flexural resistance of straight composite
I-sections in negative flexure with compact or noncompact webs.

Where 6.10.8 caps resistance at Rb*Rh*Fyc (stress format), A6 lets stockier
sections reach up to Mp (moment format) through the web plastification
factors Rpc/Rpt.  Applicable when Fy <= 70 ksi, the web is not slender, and
Iyc/Iyt >= 0.3.  Units: kip, inch, ksi; moments kip-in.
"""

from __future__ import annotations

import math

from civilpy.structural.aashto.lrfd.core import CheckResult, article
from civilpy.structural.aashto.lrfd.steel import (
    E_STEEL, PHI_F, _fyr_ltb, _lp_coefficient, _tenth_edition, web_slenderness_limit)


def st_venant_j(
    d_web: float, t_w: float,
    b_fc: float, t_fc: float,
    b_ft: float, t_ft: float,
) -> float:
    """St. Venant torsional constant (A6.3.3-9):
    J = D*tw^3/3 + sum(bf*tf^3/3 * (1 - 0.63*tf/bf)), in^4."""
    return (
        d_web * t_w**3 / 3.0
        + b_fc * t_fc**3 / 3.0 * (1.0 - 0.63 * t_fc / b_fc)
        + b_ft * t_ft**3 / 3.0 * (1.0 - 0.63 * t_ft / b_ft)
    )


def _fyr_a6(f_yc: float, f_yw: float, f_yt: float, s_xt: float, s_xc: float,
            r_h: float) -> float:
    """Fyr for A6.3 (A6.3.2/A6.3.3): min(0.7*Fyc, Rh*Fyt*Sxt/Sxc, Fyw),
    floored at 0.5*Fyc."""
    return max(min(0.7 * f_yc, r_h * f_yt * s_xt / s_xc, f_yw), 0.5 * f_yc)


@article("A6.2", "Web Plastification Factors")
def web_plastification_factors(
    d_c: float,
    d_cp: float,
    t_w: float,
    m_p: float,
    m_yc: float,
    m_yt: float,
    f_yc: float,
    r_h: float = 1.0,
    b_fc: float | None = None,
    t_fc: float | None = None,
    design_year: int | None = None,
) -> CheckResult:
    """Web plastification factors Rpc and Rpt (A6.2).

    Compact webs (2*Dcp/tw within lambda_pw(Dcp), A6.2.1) reach the full
    plastic moment: Rpc = Mp/Myc, Rpt = Mp/Myt.  Noncompact webs (A6.2.2)
    interpolate between Rh and Mp/My.  ``d_c``/``d_cp`` are the elastic and
    plastic depths of web in compression (in).  lambda_rw is c_rw
    sqrt(E/Fyc) (Eq. A6.1-3, 10th Ed.) when the compression flange
    ``b_fc`` x ``t_fc`` is given, else 5.7 sqrt(E/Fyc).  ``capacity`` holds
    Rpc; Rpt and the slenderness parameters are in ``details``."""
    lam_rw = web_slenderness_limit(d_c, t_w, b_fc, t_fc, f_yc, design_year)
    lam_pw_dcp = min(
        math.sqrt(E_STEEL / f_yc)
        / (0.54 * m_p / (r_h * m_yc) - 0.09) ** 2,
        lam_rw * d_cp / d_c,
    )  # A6.2.1-2
    if 2.0 * d_cp / t_w <= lam_pw_dcp:
        r_pc = m_p / m_yc
        r_pt = m_p / m_yt
        compact_web = True
    else:
        lam_w = 2.0 * d_c / t_w
        lam_pw_dc = min(lam_pw_dcp * d_c / d_cp, lam_rw)  # A6.2.2-6
        interp = (lam_w - lam_pw_dc) / (lam_rw - lam_pw_dc)
        r_pc = min(
            (1.0 - (1.0 - r_h * m_yc / m_p) * interp) * m_p / m_yc,
            m_p / m_yc,
        )  # A6.2.2-4
        r_pt = min(
            (1.0 - (1.0 - r_h * m_yt / m_p) * interp) * m_p / m_yt,
            m_p / m_yt,
        )  # A6.2.2-5
        compact_web = False
    return CheckResult(
        article="A6.2",
        name="Web Plastification Factors",
        capacity=r_pc,
        details={"Rpc": r_pc, "Rpt": r_pt, "compact_web": compact_web,
                 "lambda_rw": lam_rw, "lambda_pw_Dcp": lam_pw_dcp},
    )


@article("A6.3.2", "Flange Local Buckling Resistance (Appendix A6)")
def a6_flange_local_buckling(
    b_fc: float,
    t_fc: float,
    d_web: float,
    t_w: float,
    f_yc: float,
    f_yw: float,
    f_yt: float,
    s_xc: float,
    s_xt: float,
    r_pc: float,
    m_yc: float,
    m_u: float | None = None,
    r_h: float = 1.0,
) -> CheckResult:
    """Compression-flange local buckling resistance Mnc in moment format
    (A6.3.2): the plateau Rpc*Myc for compact flanges, interpolated toward
    Fyr*Sxc using kc = 4/sqrt(D/tw) (0.35 <= kc <= 0.76) for noncompact."""
    lam_f = b_fc / (2.0 * t_fc)
    lam_pf = 0.38 * math.sqrt(E_STEEL / f_yc)
    if lam_f <= lam_pf:
        m_nc = r_pc * m_yc
        compact = True
        lam_rf = None
    else:
        f_yr = _fyr_a6(f_yc, f_yw, f_yt, s_xt, s_xc, r_h)
        k_c = min(max(4.0 / math.sqrt(d_web / t_w), 0.35), 0.76)
        lam_rf = 0.95 * math.sqrt(E_STEEL * k_c / f_yr)
        m_nc = (
            1.0
            - (1.0 - f_yr * s_xc / (r_pc * m_yc))
            * (lam_f - lam_pf) / (lam_rf - lam_pf)
        ) * r_pc * m_yc
        compact = False
    return CheckResult(
        article="A6.3.2",
        name="Flange Local Buckling Resistance (Appendix A6)",
        capacity=m_nc,
        demand=m_u,
        phi=PHI_F,
        details={"lambda_f": lam_f, "lambda_pf": lam_pf,
                 "lambda_rf": lam_rf, "compact": compact},
    )


@article("A6.3.3", "Lateral Torsional Buckling Resistance (Appendix A6)")
def a6_lateral_torsional_buckling(
    l_b: float,
    r_t: float,
    j_torsion: float,
    h_depth: float,
    f_yc: float,
    f_yw: float,
    f_yt: float,
    s_xc: float,
    s_xt: float,
    r_pc: float,
    m_yc: float,
    c_b: float = 1.0,
    m_u: float | None = None,
    r_h: float = 1.0,
    welded: bool = True,
    s_xc_elastic: float | None = None,
    design_year: int | None = None,
) -> CheckResult:
    """Lateral torsional buckling resistance Mnc in moment format (A6.3.3),
    which credits the St. Venant stiffness J that 6.10.8.2.3 neglects.

    ``r_t`` is the effective radius of gyration (in), ``j_torsion`` from
    :func:`st_venant_j`, ``h_depth`` the distance between flange centroids
    (in).  ``s_xc`` is Myc / Fyc; ``s_xc_elastic`` the elastic section
    modulus to the compression flange, which Eq. A6.3.3.1-5 (Lr) uses in the
    10th Ed. (defaults to ``s_xc``).  10th Ed.: Lp = 1.1 rt sqrt(E/Fyc),
    Fyr = 0.5 Fyc welded / 0.7 Fyc rolled; ``design_year`` before 2024:
    1.0 rt sqrt(E/Fyc) and Fyr = min(0.7 Fyc, Rh Fyt Sxt/Sxc, Fyw)."""
    if _tenth_edition(design_year):
        f_yr = _fyr_ltb(f_yc, f_yw, welded, False, design_year)
    else:
        f_yr = _fyr_a6(f_yc, f_yw, f_yt, s_xt, s_xc, r_h)
    l_p = _lp_coefficient(design_year) * r_t * math.sqrt(E_STEEL / f_yc)  # A6.3.3.1-4
    s_lr = s_xc_elastic if s_xc_elastic is not None else s_xc
    ratio = f_yr / E_STEEL * s_lr * h_depth / j_torsion
    l_r = (
        1.95 * r_t * E_STEEL / f_yr
        * math.sqrt(j_torsion / (s_lr * h_depth))
        * math.sqrt(1.0 + math.sqrt(1.0 + 6.76 * ratio**2))
    )  # A6.3.3.1-5
    m_max = r_pc * m_yc
    if l_b <= l_p:
        m_nc = m_max
        regime = "plateau"
    elif l_b <= l_r:
        m_nc = min(
            c_b
            * (1.0 - (1.0 - f_yr * s_xc / m_max) * (l_b - l_p) / (l_r - l_p))
            * m_max,
            m_max,
        )  # A6.3.3-2
        regime = "inelastic"
    else:
        f_cr = (
            c_b * math.pi**2 * E_STEEL / (l_b / r_t) ** 2
            * math.sqrt(1.0 + 0.078 * j_torsion / (s_xc * h_depth)
                        * (l_b / r_t) ** 2)
        )  # A6.3.3-8
        m_nc = min(f_cr * s_xc, m_max)
        regime = "elastic"
    return CheckResult(
        article="A6.3.3",
        name="Lateral Torsional Buckling Resistance (Appendix A6)",
        capacity=m_nc,
        demand=m_u,
        phi=PHI_F,
        details={"Lp": l_p, "Lr": l_r, "Fyr": f_yr, "Cb": c_b,
                 "regime": regime},
    )


@article("A6.4", "Tension Flange Yielding (Appendix A6)")
def a6_tension_flange_yielding(
    r_pt: float,
    m_yt: float,
    m_u: float | None = None,
) -> CheckResult:
    """Tension-flange yielding resistance (A6.4-1): Mnt = Rpt*Myt."""
    return CheckResult(
        article="A6.4",
        name="Tension Flange Yielding (Appendix A6)",
        capacity=r_pt * m_yt,
        demand=m_u,
        phi=PHI_F,
        details={"Rpt": r_pt},
    )
