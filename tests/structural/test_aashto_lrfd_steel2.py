#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Hand-checked values for steel batch 2: Rh/Rb, compact composite flexure,
proportion limits, fatigue, tension/compression members, bolts."""

import math

import pytest

from civilpy.structural.aashto import lrfd


class TestFactors:
    def test_homogeneous_rh_is_one(self):
        r = lrfd.hybrid_factor(d_n=24.0, t_w=0.5, a_fn=16.0, f_yw=50.0, f_n=50.0)
        assert r.capacity == pytest.approx(1.0)

    def test_hybrid_rh_below_one(self):
        # 50 ksi web with 70 ksi flanges: rho = 50/70
        r = lrfd.hybrid_factor(d_n=24.0, t_w=0.5, a_fn=16.0, f_yw=50.0, f_n=70.0)
        rho = 50.0 / 70.0
        beta = 2.0 * 24.0 * 0.5 / 16.0
        expected = (12.0 + beta * (3.0 * rho - rho**3)) / (12.0 + 2.0 * beta)
        assert r.capacity == pytest.approx(expected)
        assert r.capacity < 1.0

    def test_rb_compact_web(self):
        # 2Dc/tw = 96 < 5.7*sqrt(29000/50) = 137.3
        r = lrfd.web_load_shedding_factor(
            d_c=24.0, t_w=0.5, b_fc=16.0, t_fc=1.0, f_yc=50.0
        )
        assert r.capacity == pytest.approx(1.0)
        assert not r.details["slender_web"]

    def test_rb_slender_web(self):
        # Dc = 48, tw = 0.4375: 2Dc/tw = 219.4 > 137.3
        r = lrfd.web_load_shedding_factor(
            d_c=48.0, t_w=0.4375, b_fc=18.0, t_fc=1.25, f_yc=50.0
        )
        lam_rw = 5.7 * math.sqrt(29000.0 / 50.0)
        a_wc = 2.0 * 48.0 * 0.4375 / (18.0 * 1.25)
        expected = 1.0 - a_wc / (1200.0 + 300.0 * a_wc) * (
            2.0 * 48.0 / 0.4375 - lam_rw
        )
        assert r.capacity == pytest.approx(expected)
        assert r.capacity < 1.0


class TestCompactCompositeFlexure:
    def test_full_mp_when_pna_high(self):
        r = lrfd.compact_composite_positive_flexure(
            m_p=100000.0, d_p=4.0, d_t=60.0
        )
        assert r.capacity == pytest.approx(100000.0)

    def test_penalty_when_pna_deep(self):
        r = lrfd.compact_composite_positive_flexure(
            m_p=100000.0, d_p=12.0, d_t=60.0
        )
        assert r.capacity == pytest.approx(100000.0 * (1.07 - 0.7 * 0.2))
        assert r.details["ductility_ok"]  # 12 < 0.42*60 = 25.2

    def test_ductility_flag(self):
        r = lrfd.compact_composite_positive_flexure(
            m_p=100000.0, d_p=30.0, d_t=60.0
        )
        assert not r.details["ductility_ok"]

    def test_continuous_span_cap(self):
        r = lrfd.compact_composite_positive_flexure(
            m_p=100000.0, d_p=4.0, d_t=60.0, m_y=60000.0, continuous_span=True
        )
        assert r.capacity == pytest.approx(1.3 * 60000.0)
        assert r.details["capped_13RhMy"]


class TestProportionLimits:
    GOOD = dict(d_web=48.0, t_w=0.5, b_fc=16.0, t_fc=1.0, b_ft=18.0, t_ft=1.25)

    def test_well_proportioned(self):
        r = lrfd.proportion_limits(**self.GOOD)
        assert r.ok
        assert all(r.details.values())

    def test_thin_flange_fails(self):
        r = lrfd.proportion_limits(**{**self.GOOD, "t_fc": 0.5})
        assert not r.ok
        assert not r.details["comp_flange_thickness"]  # 0.5 < 1.1*0.5

    def test_narrow_flange_fails(self):
        r = lrfd.proportion_limits(**{**self.GOOD, "b_fc": 7.0})
        assert not r.details["comp_flange_width"]  # 7 < 48/6


class TestFatigue:
    def test_fatigue_i_threshold(self):
        r = lrfd.fatigue_resistance("C'", delta_f=10.0)
        assert r.capacity == pytest.approx(12.0)
        assert r.ok

    def test_fatigue_ii_finite_life(self):
        # Category C, ADTT_SL = 500: N = 365*75*1*500 = 13.69e6
        # (44e8/13.69e6)^(1/3) = 6.86 ksi
        r = lrfd.fatigue_resistance("C", fatigue_i=False, adtt_sl=500.0)
        n = 365.0 * 75.0 * 500.0
        assert r.capacity == pytest.approx((44.0e8 / n) ** (1.0 / 3.0))

    def test_category_ordering(self):
        cats = ["A", "B", "C", "D", "E", "E'"]
        caps = [lrfd.fatigue_resistance(c).capacity for c in cats]
        assert caps == sorted(caps, reverse=True)


class TestMembers:
    def test_tension_yield_governs_no_holes(self):
        r = lrfd.tension_member_resistance(a_g=10.0, f_y=50.0)
        assert r.capacity == pytest.approx(0.95 * 500.0)
        assert r.details["governing"] == "yield"

    def test_tension_rupture_governs_with_holes(self):
        r = lrfd.tension_member_resistance(
            a_g=10.0, f_y=50.0, a_n=7.5, f_u=65.0, u_shear_lag=0.85
        )
        rupture = 0.80 * 65.0 * 7.5 * 0.85
        assert r.capacity == pytest.approx(rupture)
        assert r.details["governing"] == "rupture"

    def test_compression_inelastic(self):
        # KL/r = 60: Pe = pi^2*29000/3600*Ag; Po = 50*Ag
        r = lrfd.compression_member_resistance(a_g=20.0, f_y=50.0, kl_over_r=60.0)
        p_e = math.pi**2 * 29000.0 / 3600.0 * 20.0
        p_o = 1000.0
        assert r.details["mode"] == "inelastic"
        assert r.capacity == pytest.approx(0.658 ** (p_o / p_e) * p_o)
        assert r.phi == 0.95

    def test_compression_elastic_long_column(self):
        r = lrfd.compression_member_resistance(a_g=20.0, f_y=50.0, kl_over_r=180.0)
        assert r.details["mode"] == "elastic"
        assert r.capacity == pytest.approx(0.877 * r.details["Pe"])

    def test_compression_phi_pre_2015(self):
        r = lrfd.compression_member_resistance(
            a_g=20.0, f_y=50.0, kl_over_r=60.0, design_year=2010
        )
        assert r.phi == 0.90


class TestBolts:
    def test_shear_threads_excluded(self):
        # 7/8" A325 X: 0.48*0.6013*120 = 34.6 kip
        r = lrfd.bolt_shear_resistance(d_bolt=0.875, f_ub=120.0)
        a_b = math.pi * 0.875**2 / 4.0
        assert r.capacity == pytest.approx(0.48 * a_b * 120.0)
        assert r.phi == 0.80

    def test_shear_threads_included_lower(self):
        x = lrfd.bolt_shear_resistance(d_bolt=0.875, f_ub=120.0)
        n = lrfd.bolt_shear_resistance(d_bolt=0.875, f_ub=120.0,
                                       threads_excluded=False)
        assert n.capacity == pytest.approx(x.capacity * 0.38 / 0.48)

    def test_slip_class_b_standard(self):
        # 7/8" A325, Class B, standard holes: 1.0*0.5*1*39 = 19.5 kip
        r = lrfd.bolt_slip_resistance("A325", 0.875)
        assert r.capacity == pytest.approx(19.5)

    def test_slip_oversize_class_a(self):
        r = lrfd.bolt_slip_resistance("A325", 0.875, hole_type="oversize",
                                      surface_class="A")
        assert r.capacity == pytest.approx(0.85 * 0.33 * 39.0)

    def test_slip_creep_factor_galvanized(self):
        # 10th Ed. Kc = 0.80 for Class C (galvanized) and duplex-over-galvanized
        c = lrfd.bolt_slip_resistance("A325", 0.875, surface_class="C")
        assert c.capacity == pytest.approx(0.80 * 0.33 * 39.0)
        d = lrfd.bolt_slip_resistance("A325", 0.875, duplex_galvanized=True)
        assert d.capacity == pytest.approx(0.80 * 0.50 * 39.0)

    def test_bearing_full(self):
        # 7/8" bolt, 0.5" ply, Fu=65, clear distance 2": 2.4*0.875*0.5*65
        r = lrfd.bolt_bearing_resistance(0.875, 0.5, 65.0, clear_distance=2.0)
        assert r.capacity == pytest.approx(2.4 * 0.875 * 0.5 * 65.0)

    def test_bearing_end_distance_governed(self):
        r = lrfd.bolt_bearing_resistance(0.875, 0.5, 65.0, clear_distance=1.0)
        assert r.capacity == pytest.approx(1.2 * 1.0 * 0.5 * 65.0)
        assert not r.details["full_bearing"]


class TestRegistry:
    def test_steel2_articles_registered(self):
        for num in ("6.10.1.10.1", "6.10.1.10.2", "6.10.7.1.2", "6.10.2",
                    "6.6.1.2.5", "6.8.2.1", "6.9.4.1.1", "6.13.2.7",
                    "6.13.2.8", "6.13.2.9"):
            assert num in lrfd.ARTICLES


class TestConstructibility:
    def test_web_bend_buckling(self):
        # D=48, tw=0.5, Dc=24: k = 9/0.25 = 36
        # Fcrw = 0.9*29000*36/(96^2) = 101.9 -> capped at Rh*Fyc = 50
        r = lrfd.web_bend_buckling(d_web=48.0, t_w=0.5, d_c=24.0,
                                   f_yc=50.0, f_yw=50.0)
        assert r.details["k"] == pytest.approx(36.0)
        assert r.capacity == pytest.approx(50.0)

    def test_web_bend_buckling_slender_governs(self):
        # D=96, tw=0.4375, Dc=58: k = 9/(58/96)^2 = 24.66
        # Fcrw = 0.9*29000*24.66/(219.4)^2 = 13.4 < 50
        r = lrfd.web_bend_buckling(d_web=96.0, t_w=0.4375, d_c=58.0,
                                   f_yc=50.0, f_yw=50.0)
        k = 9.0 / (58.0 / 96.0) ** 2
        assert r.capacity == pytest.approx(
            0.9 * 29000.0 * k / (96.0 / 0.4375) ** 2
        )
        assert r.capacity < 50.0

    def test_constructibility_governing_case(self):
        # fbu = 30, fl = 9, Fnc = 35, Fcrw = 31:
        # yielding: 50 vs 39 (1.28); buckling: 35 vs 33 (1.06);
        # web: 31 vs 30 (1.03 governs)
        r = lrfd.constructibility_compression_flange(
            f_bu=30.0, f_l=9.0, f_yc=50.0, f_nc=35.0, f_crw=31.0
        )
        assert r.details["governing"] == "web_bend_buckling"
        assert r.ok

    def test_slender_web_skips_yielding(self):
        r = lrfd.constructibility_compression_flange(
            f_bu=30.0, f_l=9.0, f_yc=50.0, f_nc=35.0, slender_web=True
        )
        assert "yielding" not in r.details
        assert r.details["governing"] == "buckling"


class TestShearConnectors:
    def test_stud_strength(self):
        # 7/8" stud, f'c=4, Ec=3640: Asc=0.6013
        # 0.5*0.6013*sqrt(4*3640)=36.3 > Asc*60=36.1 -> Fu governs
        r = lrfd.shear_connector_strength(d_stud=0.875, f_c=4.0, e_c=3640.0)
        a_sc = math.pi * 0.875**2 / 4.0
        assert r.capacity == pytest.approx(
            min(0.5 * a_sc * math.sqrt(4.0 * 3640.0), a_sc * 60.0)
        )

    def test_required_count(self):
        r = lrfd.shear_connector_strength(
            d_stud=0.875, f_c=4.0, e_c=3640.0, nominal_force=1500.0
        )
        assert r.details["n_required"] == pytest.approx(
            1500.0 / (0.85 * r.capacity)
        )

    def test_fatigue_pitch_finite_life(self):
        # N = 2e6: alpha = 34.5 - 4.28*6.301 = 7.53
        r = lrfd.shear_connector_fatigue_pitch(
            d_stud=0.875, n_per_row=3, shear_flow=1.2, n_cycles=2.0e6
        )
        alpha = 34.5 - 4.28 * math.log10(2.0e6)
        assert r.details["Zr"] == pytest.approx(alpha * 0.875**2)
        assert r.capacity == pytest.approx(3.0 * alpha * 0.875**2 / 1.2)

    def test_fatigue_infinite_life_floor(self):
        inf = lrfd.shear_connector_fatigue_pitch(
            d_stud=0.875, n_per_row=3, shear_flow=1.2
        )
        assert inf.details["Zr"] == pytest.approx(5.5 * 0.875**2)


class TestBlockShear:
    def test_rupture_governs(self):
        # Avg=6, Avn=4.5, Atn=1.5, Fy=50, Fu=65, Ubs=1
        # rupture path: 0.58*65*4.5+65*1.5 = 169.65+97.5 = 267.2
        # yield path: 0.58*50*6+97.5 = 174+97.5 = 271.5 -> rupture governs
        r = lrfd.block_shear_resistance(
            a_vg=6.0, a_vn=4.5, a_tn=1.5, f_y=50.0, f_u=65.0
        )
        assert r.capacity == pytest.approx(0.58 * 65.0 * 4.5 + 65.0 * 1.5)
        assert r.phi == 0.80

    def test_punched_holes_reduction(self):
        drilled = lrfd.block_shear_resistance(6.0, 4.5, 1.5, 50.0, 65.0)
        punched = lrfd.block_shear_resistance(6.0, 4.5, 1.5, 50.0, 65.0,
                                              punched_holes=True)
        assert punched.capacity == pytest.approx(0.9 * drilled.capacity)


class TestFilletWeld:
    def test_resistance_per_inch(self):
        # 5/16" weld, E70: 0.6*0.8*70*0.707*0.3125 = 7.42 kip/in
        r = lrfd.fillet_weld_resistance(leg_size=0.3125)
        assert r.details["per_inch"] == pytest.approx(
            0.6 * 0.8 * 70.0 * 0.707 * 0.3125
        )

    def test_length_scales(self):
        one = lrfd.fillet_weld_resistance(0.3125, length=1.0)
        ten = lrfd.fillet_weld_resistance(0.3125, length=10.0)
        assert ten.capacity == pytest.approx(10.0 * one.capacity)
