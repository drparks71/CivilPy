#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NSBA Steel Bridge Design Handbook Design Example 1 (B951-25, AASHTO LRFD
10th Ed.): three-span continuous composite I-girder, 140-175-140 ft, four
girders at 12 ft, run through the civilpy checks with the handbook's own
inputs, asserting the handbook's printed results.

Section 1-1 (maximum positive flexure, end span): 1 x 16 top flange,
1/2 x 69 web, 1-3/4 x 18 bottom flange, Grade 50.  Section 2-2 (interior
pier): 2 x 18 top, 9/16 x 69 web (50 ksi), 2 x 20 bottom flange, HPS 70W
flanges.  Deck 9.0 in. structural (9.5 in. with the integral wearing
surface), haunch 3.5 in. above the top of the web, b_eff 114 in., n = 8.

Not covered here: the nonprismatic unbraced-length LTB of 6.10.8.2.3c /
Appendix D6.6 (Methods A-C) and the wind / deck-overhang lateral moments
that need the handbook's analysis model.
"""

import math

import pytest

from civilpy.structural.aashto import lrfd
from civilpy.structural.aashto.lrfd import appendix_d6, distribution as dist
from civilpy.structural.aashto.lrfd.bolted_field_splice import Flange, GirderSide
from civilpy.structural.aashto.lrfd.composite import CompositeGirder

E = 29000.0


def _approx(v, digits_rel=2e-3):
    return pytest.approx(v, rel=digits_rel)


# ── 7.2 live-load distribution factors ──────────────────────────────────────


def test_modular_ratio_and_kg():
    e_c = 33_000 * 1.0 * 0.145 ** 1.5 * math.sqrt(4.0)            # Eq. C5.4.2.4-2
    assert e_c == pytest.approx(3644, abs=1)
    assert E / e_c == pytest.approx(7.96, abs=0.005)
    # e_g from the girder centroid to the mid-slab
    assert dist.longitudinal_stiffness_kg(8, 68_971, 82.00, 9.0 / 2 + 3.5 + 42.26 - 1.0) == \
        pytest.approx(2.14e6, rel=3e-3)
    assert dist.longitudinal_stiffness_kg(8, 111_027, 114.8, 9.0 / 2 + 3.5 + 37.74 - 2.0) == \
        pytest.approx(2.65e6, rel=3e-3)


@pytest.mark.parametrize("l_ft,kg,one,multi", [(140.0, 2.14e6, 0.536, 0.819),
                                              (157.5, 2.65e6, 0.524, 0.809)])
def test_interior_moment_distribution(l_ft, kg, one, multi):
    df = dist.moment_df_interior(12.0, l_ft, 9.0, kg)
    assert (df.one_lane, df.multi_lane) == (pytest.approx(one, abs=6e-4), pytest.approx(multi, abs=6e-4))
    assert df.applicable
    # fatigue: one lane without the 1.2 multiple presence (3.6.1.1.2); the
    # handbook divides the rounded one-lane value
    assert round(df.one_lane, 3) / 1.2 == pytest.approx(0.447 if l_ft == 140 else 0.437, abs=6e-4)


def test_interior_shear_distribution():
    df = dist.shear_df_interior(12.0)
    assert (df.one_lane, df.multi_lane) == (pytest.approx(0.840), pytest.approx(1.082, abs=6e-4))
    assert df.one_lane / 1.2 == pytest.approx(0.700)


def test_exterior_girder_distribution():
    interior_m = dist.moment_df_interior(12.0, 140.0, 9.0, 2.14e6)
    lever = dist.lever_rule_exterior(12.0, 2.0)
    assert lever == pytest.approx(0.900)
    assert dist.lever_rule_exterior(12.0, 2.0, apply_multiple_presence=False) == pytest.approx(0.750)
    ext_m = dist.moment_df_exterior(interior_m, 2.0, lever)
    assert ext_m.multi_lane == pytest.approx(0.811, abs=6e-4)            # e = 0.990
    ext_v = dist.shear_df_exterior(dist.shear_df_interior(12.0), 2.0, lever)
    assert ext_v.multi_lane == pytest.approx(0.866, abs=6e-4)            # e = 0.80
    # special rigid-rotation analysis: lanes at 15, 3, -9 ft from the centroid
    rows = dist.rigid_rotation_exterior(4, 12.0, [15.0, 3.0, -9.0])
    assert [round(r["R"], 3) for r in rows] == [0.625, 0.950, 0.975]
    assert [round(r["mR"], 3) for r in rows] == [0.750, 0.950, 0.829]
    governing = max(ext_m.governing, max(r["mR"] for r in rows))
    assert governing == pytest.approx(0.950)                             # moment and shear


def test_deflection_distribution_and_impact():
    assert lrfd.multiple_presence_factor(3) * 3 / 4 == pytest.approx(0.638, abs=6e-4)
    assert lrfd.dynamic_load_allowance() == pytest.approx(1.33)
    assert lrfd.dynamic_load_allowance(fatigue=True) == pytest.approx(1.15)


# ── 10.1 section properties ─────────────────────────────────────────────────

SEC_1_1 = GirderSide(top_flange=Flange("Grade 50", 1.0, 16.0), bottom_flange=Flange("Grade 50", 1.75, 18.0),
                     web_material="Grade 50", web_thickness=0.5, web_depth=69.0, haunch=2.5)
SEC_2_2 = GirderSide(top_flange=Flange("HPS 70W", 2.0, 18.0), bottom_flange=Flange("HPS 70W", 2.0, 20.0),
                     web_material="Grade 50", web_thickness=0.5625, web_depth=69.0, haunch=1.5)


def _moduli(g, state):
    p = g.props(state)
    return p.inertia, p.inertia / (g.d - p.y_na), p.inertia / p.y_na


@pytest.mark.parametrize("state,i,s_top,s_bot", [("steel", 68_971, 1_632, 2_339),
                                                 ("3n", 137_441, 5_415, 2_964),
                                                 ("n", 191_183, 15_658, 3_211)])
def test_section_1_1_properties(state, i, s_top, s_bot):
    g = CompositeGirder(SEC_1_1, deck_t=9.0, deck_weff=114.0, n=8.0)
    got = _moduli(g, state)
    assert got == (_approx(i), _approx(s_top), _approx(s_bot))


def test_section_2_2_properties():
    # Kg used I = 111,027 and d_top = 37.74; Table 7 (steel + 10.56 in^2 of
    # rebar 4.63 in. above the bottom of the deck) d_bot = 38.96 (Dc 36.96)
    g = CompositeGirder(SEC_2_2, deck_t=9.0, deck_weff=114.0, n=8.0,
                        rebar_area=10.56, rebar_cover=9.0 - 4.63)
    steel = g.props("steel")
    assert steel.area == pytest.approx(114.8, abs=0.02)
    assert steel.inertia == _approx(111_027)
    assert g.d - steel.y_na == pytest.approx(37.74, abs=0.01)
    assert g.props("negative").y_na == pytest.approx(38.96, abs=0.01)


def test_minimum_negative_flexure_reinforcement():
    # 6.10.1.7: 1 % of the deck, over the 114 in. effective width
    a_deck = 4_776.0
    assert 0.01 * a_deck / (43.0 * 12) * 114.0 == pytest.approx(10.56, abs=0.01)


def test_section_1_1_plastic_and_yield_moment():
    mp = appendix_d6.plastic_moment(b_c=16.0, t_c=1.0, f_yc=50, d_web=69.0, t_w=0.5, f_yw=50,
                                    b_t=18.0, t_t=1.75, f_yt=50, f_c=4.0, b_s=114.0, t_s=9.0,
                                    t_haunch=2.5)
    assert mp.case == "II"                                   # PNA in the top flange
    assert mp.y_bar == pytest.approx(0.38, abs=0.005)
    assert mp.mp == pytest.approx(197_572, rel=1e-3)
    assert mp.dp == pytest.approx(11.88, abs=0.01)
    assert mp.dt == pytest.approx(83.25)
    my = appendix_d6.yield_moment_composite(
        m_d1=1.25 * 2_202 * 12, m_d2=(1.25 * 335 + 1.50 * 322) * 12,
        s_nc_top=1_632, s_nc_bot=2_339, s_lt_top=5_415, s_lt_bot=2_964,
        s_st_top=15_658, s_st_bot=3_211, f_y_top=50, f_y_bot=50)
    assert my.m_ad_bot / 12 == pytest.approx(8_624, abs=2)
    assert my.my / 12 == pytest.approx(12_278, abs=2)
    # 10.2.4.1.1: Dp > 0.1 Dt -> Eq. -2 (15,972), capped at 1.3 Rh My (15,961)
    mn = lrfd.compact_composite_positive_flexure(mp.mp, mp.dp, mp.dt, m_y=my.my,
                                                 m_u=9_797 * 12, continuous_span=True)
    assert mn.capacity / 12 == pytest.approx(15_961, abs=3)
    assert mn.ratio == pytest.approx(15_961 / 9_797, rel=2e-3)
    assert mp.dp / (0.42 * mp.dt) == pytest.approx(0.340, abs=1e-3)      # 6.10.7.3


# ── 10.2.1 constructability, Section 1-1 (steel section, Dc = 41.26 in.) ────

DC_1_1 = 42.26 - 1.0


def test_constructability_web_limits():
    # Eq. 6.10.6.2.3-3..-5: a_wc 2.58, c_rw 5.04, lambda_rw 121.4 < 2Dc/tw = 165.0
    lam = lrfd.web_slenderness_limit(DC_1_1, 0.5, 16.0, 1.0, 50.0)
    assert lam == pytest.approx(121.4, abs=0.1)
    assert 2 * DC_1_1 / 0.5 == pytest.approx(165.0, abs=0.1)
    fcrw = lrfd.web_bend_buckling(69.0, 0.5, DC_1_1, 50.0, 50.0)
    assert 9 / (DC_1_1 / 69.0) ** 2 == pytest.approx(25.2, abs=0.05)
    assert fcrw.capacity == pytest.approx(34.54, abs=0.05)


def test_constructability_cb_and_ltb():
    cb = lrfd.moment_gradient_factor(1.25 * (352 + 2_537), 1.25 * (352 + 2_517),
                                     1.25 * (338 + 2_505), 1.25 * (317 + 2_458))
    assert cb == pytest.approx(1.016, abs=5e-4)
    ltb = lrfd.lateral_torsional_buckling_resistance(24 * 12, 16.0, 1.0, DC_1_1, 0.5, 50, 50, c_b=cb)
    assert ltb.details["rt"] == pytest.approx(3.86, abs=0.005)
    assert ltb.details["Lp"] / 12 == pytest.approx(8.52, abs=0.01)
    assert ltb.details["Fyr"] == 25.0
    assert ltb.details["Lr"] / 12 == pytest.approx(34.42, abs=0.03)
    # the handbook carries rt = 3.86 and Cb = 1.016 (35.62); unrounded 35.65
    assert ltb.capacity == pytest.approx(35.62, abs=0.04)
    flb = lrfd.flange_local_buckling_resistance(16.0, 1.0, 50, 50)
    assert flb.capacity == 50.0                                      # lambda_f 8.0 < 9.2


@pytest.mark.parametrize("f_bu,af", [(-26.55, 1.73), (-29.74, 1.97)])
def test_flange_lateral_bending_amplification(f_bu, af):
    a = lrfd.lateral_bending_amplification(f_bu, 24 * 12, 3.86, 50.0, c_b=1.016)
    assert a["Lb_limit"] / 12 == pytest.approx(12.96 if f_bu == -26.55 else 12.25, abs=0.02)
    assert not a["first_order_ok"]
    assert a["Fe"] == pytest.approx(52.24, abs=0.02)
    assert a["AF"] == pytest.approx(af, abs=0.005)


def test_wind_case_needs_no_amplification():
    a = lrfd.lateral_bending_amplification(-3.24, 24 * 12, 3.86, 50.0, c_b=1.016)
    assert a["Lb_limit"] / 12 == pytest.approx(37.11, abs=0.03)
    assert a["AF"] == 1.0


@pytest.mark.parametrize("f_bu,f_l,ratio_yield,ratio_ltb", [(-26.55, 14.41, 0.819, 0.880),
                                                            (-29.74, 16.27, 0.920, 0.987)])
def test_constructability_top_flange(f_bu, f_l, ratio_yield, ratio_ltb):
    fcrw = lrfd.web_bend_buckling(69.0, 0.5, DC_1_1, 50.0, 50.0).capacity
    r = lrfd.constructibility_compression_flange(f_bu, f_l, 50.0, 35.62, f_crw=fcrw)
    d = r.details
    yield_demand = abs(f_bu) + f_l
    assert yield_demand / 50.0 == pytest.approx(ratio_yield, abs=1e-3)
    assert (abs(f_bu) + f_l / 3) / 35.62 == pytest.approx(ratio_ltb, abs=1e-3)
    assert r.ok
    assert d["yielding"]["demand"] == pytest.approx(yield_demand)
    assert d["web_bend_buckling"]["capacity"] / abs(f_bu) == pytest.approx(
        1 / (0.769 if f_bu == -26.55 else 0.861), rel=2e-3)


def test_constructability_shear():
    # do = 3D = 207 in.: k 5.56, C 0.266, Vcr = 266 k > 111 k
    v = lrfd.web_shear_resistance(69.0, 0.5, 50.0, v_u=111.0, d_o=207.0)
    assert v.details["k"] == pytest.approx(5.56, abs=0.005)
    assert v.details["C"] == pytest.approx(0.266, abs=5e-4)
    assert v.capacity == pytest.approx(266, abs=1)


def test_concrete_deck_cracking_limit():
    assert 0.9 * 0.24 * math.sqrt(4.0) == pytest.approx(0.432)


# ── 10.2.3 fatigue ──────────────────────────────────────────────────────────


def test_fatigue_resistances():
    # connection-plate weld, Table 6.6.1.2.3-1 Condition 4.1: Category C'
    # (threshold 12.0 ksi; the handbook calls it "Category C", whose
    # threshold is 10.0 ksi)
    plate = lrfd.fatigue_resistance("C'", 11.6)
    assert plate.capacity == 12.0
    assert 1 / plate.ratio == pytest.approx(0.967, abs=1e-3)
    assert lrfd.fatigue_resistance("C", 11.6).capacity == 10.0
    stud = lrfd.fatigue_resistance("C", 0.42, fatigue_i=False, adtt_sl=0.80 * 2_000)
    assert stud.details["N"] == pytest.approx(43.8e6)
    assert stud.capacity == pytest.approx(4.6, abs=0.06)


def test_special_fatigue_requirement_for_webs():
    # 6.10.5.3 end panel do = 87 in. -> shear buckling resistance; second
    # panel do = 201 in.: k 5.59, C 0.267, Vcr 267 k > 176 k
    v = lrfd.web_shear_resistance(69.0, 0.5, 50.0, v_u=176.0, d_o=201.0)
    assert v.details["k"] == pytest.approx(5.59, abs=0.005)
    assert v.details["C"] == pytest.approx(0.267, abs=5e-4)
    assert v.capacity == pytest.approx(267, abs=1)


# ── 10.2.4 strength, shear ──────────────────────────────────────────────────


def test_strength_shear():
    unstiffened = lrfd.web_shear_resistance(69.0, 0.5, 50.0)
    assert unstiffened.details["C"] == pytest.approx(0.239, abs=5e-4)
    assert unstiffened.capacity == pytest.approx(239, abs=1)
    end = lrfd.web_shear_resistance(69.0, 0.5, 50.0, v_u=388.0, d_o=87.0)
    assert (end.details["k"], end.details["C"]) == (pytest.approx(8.15, abs=0.005),
                                                    pytest.approx(0.390, abs=1e-3))
    assert end.capacity == pytest.approx(390, abs=1)
    # first interior panel next to the 7/8 x 18 bottom flange: ratio 2.17 <= 2.5
    first = lrfd.web_shear_resistance(69.0, 0.5, 50.0, v_u=345.0, d_o=201.0, tension_field=True,
                                      b_fc=16.0, t_fc=1.0, b_ft=18.0, t_ft=0.875)
    assert 2 * 69.0 * 0.5 / (16.0 + 18.0 * 0.875) == pytest.approx(2.17, abs=0.005)
    assert first.capacity == pytest.approx(475, abs=1)
    third = lrfd.web_shear_resistance(69.0, 0.5, 50.0, v_u=250.0, d_o=207.0, tension_field=True,
                                      b_fc=16.0, t_fc=1.0, b_ft=18.0, t_ft=1.75)
    assert third.capacity == pytest.approx(468, abs=1)


# ── 10.3 Section 2-2 (interior pier), strength ──────────────────────────────

DC_2_2 = 38.96 - 2.0


def test_section_2_2_web_and_factors():
    lam = lrfd.web_slenderness_limit(DC_2_2, 0.5625, 20.0, 2.0, 70.0)
    assert lam == pytest.approx(116.0, abs=0.1)                         # c_rw 7.91 -> 5.7
    assert 2 * DC_2_2 / 0.5625 == pytest.approx(131.4, abs=0.1)
    rb = lrfd.web_load_shedding_factor(DC_2_2, 0.5625, 20.0, 2.0, 70.0)
    assert rb.details["awc"] == pytest.approx(1.04, abs=0.005)
    assert rb.capacity == pytest.approx(0.989, abs=5e-4)
    rh = lrfd.hybrid_factor(DC_2_2, 0.5625, 40.0, 50.0, 70.0)
    assert rh.details["beta"] == pytest.approx(1.04, abs=0.005)
    assert rh.capacity == pytest.approx(0.984, abs=5e-4)
    # flange transition (1 x 20 bottom flange, Dc = Dn = 38.85): 0.967 / 0.970
    lam_t = lrfd.web_slenderness_limit(38.85, 0.5625, 20.0, 1.0, 70.0)
    assert lam_t == pytest.approx(109.7, abs=0.1)                       # c_rw 5.39
    assert lrfd.web_load_shedding_factor(38.85, 0.5625, 20.0, 1.0, 70.0).capacity == \
        pytest.approx(0.967, abs=1e-3)
    assert lrfd.hybrid_factor(38.85, 0.5625, 20.0, 50.0, 70.0).capacity == pytest.approx(0.970, abs=5e-4)
    # not compact: Appendix A6 is not available (2Dc/tw > lambda_rw)
    cls = lrfd.classify_web_negative(DC_2_2, 0.5625, 70, 70, 2 * 18 ** 3 / 12, 2 * 20 ** 3 / 12,
                                     b_fc=20.0, t_fc=2.0)
    assert cls.capacity == 0.0 and cls.details["lambda_rw"] == pytest.approx(116.0, abs=0.1)


def test_section_2_2_ltb_and_flb():
    cb = lrfd.moment_gradient_factor(14_978, 9_737, 11_486, 13_231)
    assert cb == pytest.approx(1.229, abs=5e-4)
    rb, rh = 0.989, 0.984
    ltb = lrfd.lateral_torsional_buckling_resistance(17 * 12, 20.0, 2.0, DC_2_2, 0.5625, 70, 50,
                                                     c_b=cb, r_b=rb, r_h=rh)
    assert ltb.details["rt"] == pytest.approx(5.33, abs=0.005)
    assert ltb.details["Lp"] / 12 == pytest.approx(9.94, abs=0.01)
    assert ltb.details["Lr"] / 12 == pytest.approx(40.17, abs=0.03)
    assert ltb.capacity == pytest.approx(68.12, abs=0.02)               # Fmax governs
    flb = lrfd.flange_local_buckling_resistance(20.0, 2.0, 70, 50, r_b=rb, r_h=rh)
    assert flb.capacity == pytest.approx(68.12, abs=0.02)               # lambda_f 5.0 < 7.73
    # at the flange transition (1 x 20): lambda_f 10.0, Fyr 49, lambda_rf 13.62
    flb_t = lrfd.flange_local_buckling_resistance(20.0, 1.0, 70, 50, r_b=0.967, r_h=0.970)
    assert flb_t.capacity == pytest.approx(58.62, abs=0.03)
    # Strength I bottom-flange stress check at the pier: -55.26 ksi
    assert 55.26 / flb.capacity == pytest.approx(0.811, abs=1e-3)


# ── 10.4 shear connectors, 10.5 / 10.6 stiffeners ───────────────────────────


def test_stud_fatigue_and_pitch():
    # Fatigue II: N = 365 (75)(1.5)(1,600) = 65.7e6; (dF)n = (1040e8 / N)^(1/5)
    n = 365 * 75 * 1.5 * 1_600
    z = lrfd.shear_connector_fatigue_resistance(0.875, n_cycles=n)
    assert z.details["dFn"] == pytest.approx(4.36, abs=0.005)
    assert z.capacity == pytest.approx(2.62, abs=0.01)
    # Vsr = 0.56 k/in at three studs per row -> p = 14.0 in.
    p = lrfd.shear_connector_fatigue_pitch(0.875, 3, 0.56, n_cycles=n)
    assert p.capacity == pytest.approx(14.0, abs=0.1)
    assert 1_600 < 11_320 / 1.5                       # Fatigue II applies (7,547)


def test_stud_strength():
    q = lrfd.shear_connector_strength(0.875, nominal_force=3_313.0)
    assert q.capacity == pytest.approx(25.20, abs=0.07)                 # Asc rounded to 0.60
    assert q.details["n_required"] == pytest.approx(131, abs=1)
    # Section 1-1: deck 3,488 k vs steel 3,313 k (7/8 x 18 bottom flange near the end)
    assert 0.85 * 4.0 * 114.0 * 9.0 == pytest.approx(3_488, abs=1)
    assert 50 * 69 * 0.5 + 50 * 18 * 0.875 + 50 * 16 * 1.0 == pytest.approx(3_313, abs=1)
    # point of maximum positive moment to the pier: Pp + 0.45 f'c bs ts
    total = 3_313 + 0.45 * 4.0 * 114.0 * 9.0
    assert total == pytest.approx(5_160, abs=1)
    assert lrfd.shear_connector_strength(0.875, nominal_force=total).details["n_required"] == \
        pytest.approx(205, abs=1)


def test_transverse_stiffener():
    w = lrfd.transverse_stiffener_width(6.0, 0.5, 69.0, 16.0)
    assert w.ok                                        # 4.3 <= 6.0 <= 8.0, >= bf/4 = 4.0
    i_t = 0.5 * 6.0 ** 3 / 3                            # 36.00 in^4 about the web face
    r = lrfd.transverse_stiffener_inertia(i_t, 6.0, 0.5, 69.0, 0.5, 201.0, 50.0, 50.0,
                                          tension_field=True, v_u=345.0, phi_v_cr=239.0,
                                          phi_v_n=475.0)
    assert r.details["I_t1"] == pytest.approx(4.31, abs=0.01)
    assert r.details["I_t2"] == pytest.approx(40.57, abs=0.05)
    assert r.demand == pytest.approx(20.60, abs=0.02)                  # Eq. 6.10.11.1.3-7
    assert r.ok


def test_bearing_stiffener():
    assert lrfd.bearing_stiffener_width(7.0, 0.625, 50.0).ok          # t_min 0.61 in.
    assert 7.0 / (0.48 * math.sqrt(E / 50.0)) == pytest.approx(0.61, abs=0.005)
    rb = lrfd.bearing_stiffener_resistance(2 * (7.0 - 1.5) * 0.625, 50.0, r_u=388.0)
    assert rb.capacity == pytest.approx(482, abs=1)                     # Apn rounded to 6.88
    # the handbook's effective column takes 18 tw of web (Aw 4.50): 618 k
    col = lrfd.bearing_stiffener_effective_column(7.0, 0.625, 0.5, 69.0, 50.0, p_u=388.0,
                                                  web_under_stiffener=False)
    assert col.details["Ag"] == pytest.approx(13.25)
    assert col.details["r"] == pytest.approx(3.46, abs=0.01)
    assert col.capacity * col.phi == pytest.approx(618, abs=1.5)          # Pn rounded to 651
    # with the web under the stiffeners (9 tw each side of them) 634 k
    full = lrfd.bearing_stiffener_effective_column(7.0, 0.625, 0.5, 69.0, 50.0)
    assert full.capacity * full.phi == pytest.approx(633.5, abs=0.5)
