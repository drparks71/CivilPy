#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NSBA Steel Bridge Design Handbook Design Example 2 (B952-25, AASHTO LRFD
10th Ed.): two-span continuous (90-90 ft) composite rolled-size plate girder,
four girders at 10 ft, with the pier section designed by Appendix A6 and
moment redistribution (Appendix B6), run through the civilpy checks with
the handbook's inputs.

Section 1 (positive): 3/4 x 14 top flange, 1/2 x 42 web, 1-1/4 x 16 bottom
flange.  Section 2 (pier): 1-1/8 x 14 top, 1/2 x 42 web, 1-1/4 x 16 bottom
flange.  Grade 50 throughout; deck 8 in., 2.0 in. from the top of the web to
the bottom of the deck, b_eff 102 in., n = 8; deck reinforcement #6 at 6 in.
top (7.45 in^2, 3.0 in. down) and #5 at 8 in. bottom (3.98 in^2).
"""

import math

import pytest

from civilpy.structural.aashto import lrfd
from civilpy.structural.aashto.lrfd import appendix_a6 as a6
from civilpy.structural.aashto.lrfd import appendix_b6 as b6
from civilpy.structural.aashto.lrfd import appendix_d6 as d6
from civilpy.structural.aashto.lrfd import distribution as dist
from civilpy.structural.aashto.lrfd.bolted_field_splice import Flange, GirderSide
from civilpy.structural.aashto.lrfd.composite import CompositeGirder

SEC_1 = GirderSide(Flange("Grade 50", 0.75, 14.0), Flange("Grade 50", 1.25, 16.0), "Grade 50",
                   0.5, 42.0, haunch=2.0 - 0.75)
SEC_2 = GirderSide(Flange("Grade 50", 1.125, 14.0), Flange("Grade 50", 1.25, 16.0), "Grade 50",
                   0.5, 42.0, haunch=2.0 - 1.125)
# the two rebar layers as one at their centroid (top 3.0 in., bottom 8 - 1.9375 in. down)
A_RT, C_RT, A_RB, C_RB = 7.45, 3.0, 3.98, 8.0 - (1.0 + 5 / 8 + 5 / 16)
A_R = A_RT + A_RB
C_R = (A_RT * C_RT + A_RB * C_RB) / A_R


# ── distribution factors ────────────────────────────────────────────────────


def test_distribution_factors():
    g = CompositeGirder(SEC_1, deck_t=8.0, deck_weff=102.0, n=8.0)
    steel = g.props("steel")
    assert steel.inertia == pytest.approx(16_401, rel=1e-3)
    assert g.d - steel.y_na == pytest.approx(25.79, abs=0.01)
    kg = dist.longitudinal_stiffness_kg(8, steel.inertia, steel.area, 8.0 / 2 + 2.0 + 25.79 - 0.75)
    assert kg == pytest.approx(528_162, rel=2e-3)
    m = dist.moment_df_interior(10.0, 90.0, 8.0, 528_162)
    assert (round(m.one_lane, 3), round(m.multi_lane, 3)) == (0.510, 0.736)
    v = dist.shear_df_interior(10.0)
    assert (round(v.one_lane, 3), round(v.multi_lane, 3)) == (0.760, 0.952)
    lever = dist.lever_rule_exterior(10.0, 2.0)
    assert lever == pytest.approx(0.840)
    assert dist.moment_df_exterior(m, 2.0, lever).multi_lane == pytest.approx(0.729, abs=6e-4)
    # 0.800 x 0.952 (the handbook multiplies the rounded interior factor)
    assert dist.shear_df_exterior(v, 2.0, lever).multi_lane == pytest.approx(0.762, abs=1e-3)
    rows = dist.rigid_rotation_exterior(4, 10.0, [12.0, 0.0])
    assert [round(r["mR"], 3) for r in rows] == [0.732, 0.860]
    # fatigue (one lane / 1.2) and deflection (m N_L / N_b)
    assert round(lever / 1.2, 3) == 0.700 and round(0.510 / 1.2, 3) == 0.425
    assert 1.0 * 2 / 4 == 0.500


# ── section properties, Mp, My ──────────────────────────────────────────────


@pytest.mark.parametrize("state,i,s_top,s_bot", [("n", 49_905, 9_672, 1_285),
                                                 ("3n", 36_315, 2_700, 1_189)])
def test_section_1_properties(state, i, s_top, s_bot):
    g = CompositeGirder(SEC_1, deck_t=8.0, deck_weff=102.0, n=8.0)
    p = g.props(state)
    assert (p.inertia, p.inertia / (g.d - p.y_na), p.inertia / p.y_na) == (
        pytest.approx(i, rel=2e-3), pytest.approx(s_top, rel=2e-3), pytest.approx(s_bot, rel=2e-3))


def test_section_1_plastic_and_yield_moment():
    mp = d6.plastic_moment(b_c=14.0, t_c=0.75, f_yc=50, d_web=42.0, t_w=0.5, f_yw=50, b_t=16.0,
                           t_t=1.25, f_yt=50, f_c=4.0, b_s=102.0, t_s=8.0, t_haunch=1.25)
    assert mp.pna.startswith("slab") or mp.pna == "deck" or mp.y_pna < 8.0
    assert mp.y_pna == pytest.approx(7.43, abs=0.01)
    assert mp.mp == pytest.approx(80_672, rel=1e-3)
    g = CompositeGirder(SEC_1, deck_t=8.0, deck_weff=102.0, n=8.0)
    steel = g.props("steel")
    s_nc_bot = steel.inertia / steel.y_na
    my = d6.yield_moment_composite(m_d1=1.25 * 738 * 12, m_d2=(1.25 * 147 + 1.5 * 120) * 12,
                                   s_nc_top=steel.inertia / (g.d - steel.y_na), s_nc_bot=s_nc_bot,
                                   s_lt_top=2_700, s_lt_bot=1_189, s_st_top=9_672, s_st_bot=1_285,
                                   f_y_top=50, f_y_bot=50)
    assert my.m_ad_bot / 12 == pytest.approx(3_645, abs=3)
    assert my.my / 12 == pytest.approx(4_931, abs=3)


def test_section_2_properties_and_moments():
    g = CompositeGirder(SEC_2, deck_t=8.0, deck_weff=102.0, n=8.0, rebar_area=A_R, rebar_cover=C_R)
    neg = g.props("negative")
    assert neg.inertia == pytest.approx(27_408, rel=2e-3)
    assert neg.y_na == pytest.approx(25.40, abs=0.01)                 # Dc = 24.15
    s_top, s_bot = neg.inertia / (g.d - neg.y_na), neg.inertia / neg.y_na
    assert (s_top, s_bot) == (pytest.approx(1_444, rel=2e-3), pytest.approx(1_079, rel=2e-3))
    # minimum reinforcement (6.10.1.7): 1 % of the 3,596 in^2 deck over its
    # 37 ft width, 0.97 in^2/ft, times the 102 in. effective width
    assert 0.01 * 3_596 / 37.0 * 102 / 12 == pytest.approx(8.25, abs=0.02)
    mp = d6.plastic_moment(flexure="negative", b_c=16.0, t_c=1.25, f_yc=50, d_web=42.0, t_w=0.5,
                           f_yw=50, b_t=14.0, t_t=1.125, f_yt=50, b_s=102.0, t_s=8.0,
                           t_haunch=2.0 - 1.125, a_rt=A_RT, c_rt=C_RT, a_rb=A_RB, c_rb=C_RB, f_yr=60)
    assert mp.case == "I"
    assert mp.y_bar == pytest.approx(11.52, abs=0.02)                 # Pt rounded to 788 k
    assert mp.mp == pytest.approx(65_874, rel=1e-3)
    assert mp.dcp == pytest.approx(30.48, abs=0.02)
    steel = g.props("steel")
    kw = dict(m_d1=1.25 * 1_334 * 12, m_d2=(1.25 * 265 + 1.5 * 217) * 12,
              s_nc_top=steel.inertia / (g.d - steel.y_na), s_nc_bot=steel.inertia / steel.y_na,
              s_lt_top=s_top, s_lt_bot=s_bot, s_st_top=s_top, s_st_bot=s_bot,
              f_y_top=50, f_y_bot=50)
    my = d6.yield_moment_composite(**kw)
    assert my.my_bot / 12 == pytest.approx(4_272, abs=4)            # Myc, bottom (compression)
    assert my.my_top / 12 == pytest.approx(4_767, abs=4)            # Myt, top flange first


# ── 8.2.1 strength: Appendix A6 and moment redistribution ──────────────────

DC, DCP = 25.40 - 1.25, 30.48
MYC, MYT, MP = 4_272 * 12, 4_767 * 12, 5_490 * 12


def test_a6_applicability_and_web_plastification():
    lam = lrfd.web_slenderness_limit(DC, 0.5, 16.0, 1.25, 50)
    assert lam == pytest.approx(137.3, abs=0.1)                      # a_wc 1.21, c_rw 7.23 -> 5.7
    assert 2 * DC / 0.5 == pytest.approx(96.60)
    i_yc, i_yt = 1.25 * 16 ** 3 / 12, 1.125 * 14 ** 3 / 12
    assert i_yc / i_yt == pytest.approx(1.7, abs=0.05)               # A6.1-2 >= 0.3
    r = a6.web_plastification_factors(DC, DCP, 0.5, MP, MYC, MYT, 50, b_fc=16.0, t_fc=1.25)
    assert not r.details["compact_web"]                              # 121.9 > 66.0
    assert r.details["lambda_pw_Dcp"] == pytest.approx(66.0, abs=0.1)
    assert r.details["Rpc"] == pytest.approx(1.136, abs=1e-3)
    assert r.details["Rpt"] == pytest.approx(1.072, abs=1e-3)


def test_a6_flexural_resistance():
    r_pc, r_pt = 1.136, 1.072
    flb = a6.a6_flange_local_buckling(16.0, 1.25, 42.0, 0.5, 50, 50, 50, 1_025, 1_444, r_pc, MYC)
    assert flb.details["compact"] and flb.details["lambda_f"] == pytest.approx(6.40)
    assert flb.capacity / 12 == pytest.approx(4_853, abs=1)
    cb = lrfd.moment_gradient_factor(5_365, 3_514, 4_131, 4_748)
    assert cb == pytest.approx(1.23, abs=5e-3)
    j = a6.st_venant_j(42.0, 0.5, 16.0, 1.25, 14.0, 1.125)
    assert j == pytest.approx(17.96, abs=0.01)
    r_t = 16.0 / math.sqrt(12 * (1 + DC * 0.5 / (3 * 16.0 * 1.25)))
    assert r_t == pytest.approx(4.21, abs=0.005)
    ltb = a6.a6_lateral_torsional_buckling(120.0, r_t, j, 1.125 / 2 + 42 + 1.25 / 2, 50, 50, 50,
                                           s_xc=MYC / 50, s_xt=1_444, r_pc=r_pc, m_yc=MYC, c_b=cb,
                                           s_xc_elastic=1_079)
    assert ltb.details["Lp"] == pytest.approx(111.5, abs=0.2)
    assert ltb.details["Fyr"] == 25.0
    assert ltb.details["Lr"] == pytest.approx(491.1, abs=0.6)             # rt rounded to 4.21
    assert ltb.capacity / 12 == pytest.approx(4_853, abs=1)          # 5,894 capped at Rpc Myc
    mnt = a6.a6_tension_flange_yielding(r_pt, MYT, m_u=5_365 * 12)
    assert mnt.capacity / 12 == pytest.approx(5_110, abs=1)
    assert not mnt.ok                                                # 5,365 > 5,110 before redistribution


def test_moment_redistribution():
    web = b6.b6_web_proportions(42.0, 0.5, DC, DCP, 50)
    assert web.details["satisfied"]
    assert web.details["2Dc/tw (limit)"] == pytest.approx(163.8, abs=0.1)
    assert web.details["Dcp (limit)"] == pytest.approx(31.50)
    fl = b6.b6_flange_proportions(16.0, 1.25, 42.0, 50)
    assert fl.details["satisfied"] and fl.details["bfc_min"] == pytest.approx(9.88, abs=0.01)
    v = lrfd.web_shear_resistance(42.0, 0.5, 50.0, v_u=337.0)
    assert v.details["C"] == pytest.approx(0.645, abs=1e-3)
    assert v.capacity == pytest.approx(392.8, abs=0.5)
    # not ultracompact (2Dcp/tw 121.9 > 55.4), no stiffener within D/2: B6.5.2-2
    mpe = b6.b6_effective_plastic_moment(4_853 * 12, 16.0, 1.25, 42.0, 50, d_cp=DCP, t_w=0.5)
    assert not mpe.details["ultracompact_web"]
    assert mpe.details["factor"] * 4_853 == pytest.approx(5_013, abs=2)
    assert mpe.capacity / 12 == pytest.approx(4_853)
    mrd = b6.b6_redistribution_moment(5_365 * 12, mpe.capacity)
    assert mrd.capacity / 12 == pytest.approx(512, abs=1)
    assert mrd.capacity / (5_365 * 12) == pytest.approx(0.095, abs=1e-3)


def test_refined_method():
    rl = b6.b6_rotation_limit(16.0, 1.25, 42.0, 50)
    assert rl.capacity == pytest.approx(0.029, abs=5e-4)
    y0 = 5_365 / 4_853
    assert y0 == pytest.approx(1.106, abs=5e-4)
    hit = b6.b6_refined_effective_moment(y0, 0.032, rl.capacity)
    assert hit["theta_p"] == pytest.approx(0.00429, abs=2e-5)
    assert hit["M/phiMn"] == pytest.approx(0.957, abs=1e-3)
    assert hit["M/phiMn"] * 4_853 == pytest.approx(4_644, abs=3)
