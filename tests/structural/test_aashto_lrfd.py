#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Hand-checked values for the AASHTO LRFD check functions.

Reference values computed by hand from the 9th Edition equations; geometry
loosely follows the FHWA Steel Bridge Design Handbook example I-girder.
"""

import math

import pytest

from civilpy.structural.aashto import lrfd


class TestFlangeLocalBuckling:
    def test_compact_flange_reaches_fyc(self):
        # 16 x 1.0 flange, lambda_f = 8.0 < lambda_pf = 0.38*sqrt(29000/50) = 9.15
        r = lrfd.flange_local_buckling_resistance(
            b_fc=16.0, t_fc=1.0, f_yc=50.0, f_yw=50.0
        )
        assert r.capacity == pytest.approx(50.0)
        assert r.details["compact"] is True

    def test_noncompact_flange_interpolates(self):
        # 20 x 0.875 flange: lambda_f = 11.43, lambda_pf = 9.15
        # Fyr = max(min(0.7*50, 50), 25) = 35 ksi
        # lambda_rf = 0.56*sqrt(29000/35) = 16.12
        # Fnc = (1 - (1 - 35/50)*(11.43-9.15)/(16.12-9.15))*50 = 45.10 ksi
        r = lrfd.flange_local_buckling_resistance(
            b_fc=20.0, t_fc=0.875, f_yc=50.0, f_yw=50.0
        )
        lam_f = 20.0 / (2 * 0.875)
        lam_pf = 0.38 * math.sqrt(29000.0 / 50.0)
        lam_rf = 0.56 * math.sqrt(29000.0 / 35.0)
        expected = (1 - (1 - 35.0 / 50.0) * (lam_f - lam_pf) / (lam_rf - lam_pf)) * 50.0
        assert r.capacity == pytest.approx(expected)
        assert r.capacity == pytest.approx(45.10, abs=0.05)
        assert r.details["compact"] is False

    def test_demand_sets_ratio(self):
        r = lrfd.flange_local_buckling_resistance(
            b_fc=16.0, t_fc=1.0, f_yc=50.0, f_yw=50.0, f_bu=40.0
        )
        assert r.ratio == pytest.approx(50.0 / 40.0)
        assert r.ok


class TestLateralTorsionalBuckling:
    # rt for bfc=16, tfc=1.0, Dc=24, tw=0.5:
    #   rt = 16/sqrt(12*(1 + 24*0.5/(3*16*1.0))) = 4.105 in
    RT = 16.0 / math.sqrt(12.0 * (1.0 + 24.0 * 0.5 / (3.0 * 16.0 * 1.0)))

    def kwargs(self, l_b):
        return dict(
            l_b=l_b, b_fc=16.0, t_fc=1.0, d_c=24.0, t_w=0.5, f_yc=50.0, f_yw=50.0
        )

    def test_plateau_below_lp(self):
        l_p = self.RT * math.sqrt(29000.0 / 50.0)
        r = lrfd.lateral_torsional_buckling_resistance(**self.kwargs(l_p * 0.9))
        assert r.capacity == pytest.approx(50.0)
        assert r.details["regime"] == "inelastic-plateau"

    def test_inelastic_interpolation(self):
        l_p = self.RT * math.sqrt(29000.0 / 50.0)
        l_r = math.pi * self.RT * math.sqrt(29000.0 / 35.0)
        l_b = (l_p + l_r) / 2.0
        r = lrfd.lateral_torsional_buckling_resistance(**self.kwargs(l_b))
        expected = (1 - (1 - 35.0 / 50.0) * 0.5) * 50.0  # midpoint of Lp..Lr
        assert r.capacity == pytest.approx(expected)

    def test_elastic_buckling(self):
        l_r = math.pi * self.RT * math.sqrt(29000.0 / 35.0)
        l_b = 1.5 * l_r
        r = lrfd.lateral_torsional_buckling_resistance(**self.kwargs(l_b))
        f_cr = math.pi**2 * 29000.0 / (l_b / self.RT) ** 2
        assert r.capacity == pytest.approx(f_cr)
        assert r.details["regime"] == "elastic"

    def test_cb_capped_at_plateau(self):
        l_p = self.RT * math.sqrt(29000.0 / 50.0)
        l_b = l_p * 1.05
        r = lrfd.lateral_torsional_buckling_resistance(**self.kwargs(l_b) | {"c_b": 2.0})
        assert r.capacity == pytest.approx(50.0)  # Cb amplification capped at RbRhFyc


class TestWebShear:
    def test_stocky_web_full_plastic(self):
        # D/tw = 48/0.75 = 64 < 1.12*sqrt(29000*5/50) = 60.3? No: 60.3 < 64,
        # use a thicker web: 48/1.0 = 48 < 60.3 -> C = 1.0
        r = lrfd.web_shear_resistance(d_web=48.0, t_w=1.0, f_yw=50.0)
        assert r.details["C"] == pytest.approx(1.0)
        assert r.capacity == pytest.approx(0.58 * 50.0 * 48.0 * 1.0)

    def test_slender_web_elastic_buckling(self):
        # D/tw = 96/0.5 = 192 > 1.40*sqrt(29000*5/50) = 75.4 -> elastic C
        r = lrfd.web_shear_resistance(d_web=96.0, t_w=0.5, f_yw=50.0)
        c = 1.57 / 192.0**2 * (29000.0 * 5.0 / 50.0)
        assert r.details["C"] == pytest.approx(c)
        assert r.capacity == pytest.approx(c * 0.58 * 50.0 * 96.0 * 0.5)

    def test_tension_field_exceeds_c_vp(self):
        r_no_tf = lrfd.web_shear_resistance(d_web=96.0, t_w=0.5, f_yw=50.0, d_o=96.0)
        r_tf = lrfd.web_shear_resistance(
            d_web=96.0, t_w=0.5, f_yw=50.0, d_o=96.0,
            tension_field=True, b_fc=20.0, t_fc=1.5, b_ft=20.0, t_ft=1.5,
        )
        assert r_tf.capacity > r_no_tf.capacity
        assert r_tf.details["equation"] == "6.10.9.3.2-2"

    def test_tension_field_requires_flanges(self):
        with pytest.raises(ValueError):
            lrfd.web_shear_resistance(
                d_web=96.0, t_w=0.5, f_yw=50.0, d_o=96.0, tension_field=True
            )


class TestLongitudinalStiffener:
    def test_governing_limit_is_moment_of_inertia(self):
        r = lrfd.longitudinal_stiffener_proportions(
            proj_width=4.0, t_s=0.5, moment_of_inertia=25.0,
            radius_of_gyration=1.5, d_web=96.0, t_w=0.5, d_o=96.0,
            f_ys=50.0, f_yc=50.0)
        # b_l_max = 0.48*0.5*sqrt(29000/50)
        assert r.details["b_l_max"] == pytest.approx(
            0.48 * 0.5 * math.sqrt(29000.0 / 50.0))
        # I_l_req = 96*0.5^3*(2.4*1 - 0.13) = 27.24
        assert r.details["I_l_req"] == pytest.approx(27.24, rel=1e-3)
        assert r.details["width_ok"] and r.details["r_ok"]
        assert r.details["governing"] == "I_l"
        assert r.ok is False                      # 25 < 27.24 required
        assert r.ratio == pytest.approx(25.0 / 27.24, rel=1e-3)

    def test_adequate_stiffener_passes(self):
        r = lrfd.longitudinal_stiffener_proportions(
            proj_width=4.0, t_s=0.5, moment_of_inertia=40.0,
            radius_of_gyration=1.5, d_web=96.0, t_w=0.5, d_o=96.0,
            f_ys=50.0, f_yc=50.0)
        assert r.ok is True and r.ratio >= 1.0

    def test_registered_in_articles(self):
        assert (lrfd.ARTICLES["6.10.11.3"]
                is lrfd.longitudinal_stiffener_proportions)


class TestStabilityBracing:
    def test_stiffness_and_strength(self):
        r = lrfd.stability_bracing_torsional(
            m_r=6000.0, l_span=1200.0, n_braces=5, i_eff=200.0,
            brace_stiffness=5.0e5, c_b=1.0)
        # beta_T_req = 2.4*L*Mr^2 / (phi*n*E*Ieff*Cb^2)
        # phi_sb = 0.80 (6.5.4.2, 10th Ed.)
        expected = (2.4 * 1200.0 * 6000.0**2
                    / (0.80 * 5 * 29000.0 * 200.0 * 1.0**2))
        assert r.details["beta_T_req"] == pytest.approx(expected)
        # M_br = 0.024*Mr*L/(n*Cb*L_b), L_b default = L/(n+1) = 200
        assert r.details["L_b"] == pytest.approx(200.0)
        assert r.details["M_br_req"] == pytest.approx(
            0.024 * 6000.0 * 1200.0 / (5 * 1.0 * 200.0))
        assert r.ok is True                       # provided 5e5 > required
        assert r.details["validate_against_brr"] is True

    def test_10th_edition_strength_with_h_o(self):
        # NSBA B303 Example 1, positive moment: 782 k-in, 119,128 k-in/rad
        r = lrfd.stability_bracing_torsional(
            m_r=54668.0, l_span=1680.0, n_braces=5, i_eff=872.0,
            brace_stiffness=185674.0, l_b=288.0, h_o=70.19)
        assert r.details["M_br_req"] == pytest.approx(782.0, abs=1.0)
        assert r.details["beta_T_req"] == pytest.approx(119128.0, rel=1e-3)
        r3 = lrfd.stability_bracing_torsional(
            m_r=54668.0, l_span=1680.0, n_braces=5, i_eff=872.0,
            brace_stiffness=185674.0, l_b=288.0, h_o=70.19, full_depth=False)
        assert r3.details["beta_T_req"] == pytest.approx(1.5 * r.details["beta_T_req"])

    def test_registered_in_articles(self):
        assert (lrfd.ARTICLES["6.7.4.2.2"]
                is lrfd.stability_bracing_torsional)


class TestTransverseStiffener:
    def test_projecting_width_margins(self):
        # D=96: b_t >= 2+96/30=5.2; b_t <= 16*0.5=8; b_t >= 16/4=4
        r = lrfd.transverse_stiffener_width(b_t=6.0, t_p=0.5, d_web=96.0,
                                            b_f=16.0)
        assert r.details["b_t_min_depth"] == pytest.approx(5.2)
        assert r.details["b_t_max"] == pytest.approx(8.0)
        assert r.ok is True
        assert r.ratio == pytest.approx(6.0 / 5.2)      # depth limit governs
        assert r.details["governing"] == "depth"
        # too narrow fails
        assert lrfd.transverse_stiffener_width(
            b_t=3.5, t_p=0.5, d_web=96.0, b_f=16.0).ok is False

    def test_moment_of_inertia_buckling_path(self):
        # do=D=96: J = 2.5/1 - 2 = 0.5; I_t1 = 96*0.5^3*0.5 = 6.0
        r = lrfd.transverse_stiffener_inertia(
            moment_of_inertia=36.0, b_t=6.0, t_p=0.5, d_web=96.0, t_w=0.5,
            d_o=96.0, f_yw=50.0, f_ys=50.0)
        assert r.details["J"] == pytest.approx(0.5)
        assert r.details["I_t1"] == pytest.approx(6.0)
        # Fcrs = 0.31E/(12)^2 = 62.4 -> capped at Fys=50 -> rho_t = 1.0
        assert r.details["Fcrs"] == pytest.approx(50.0)
        assert r.details["rho_t"] == pytest.approx(1.0)
        assert r.demand == pytest.approx(6.0) and r.ok is True

    def test_moment_of_inertia_tension_field_conservative(self):
        r = lrfd.transverse_stiffener_inertia(
            moment_of_inertia=36.0, b_t=6.0, t_p=0.5, d_web=96.0, t_w=0.5,
            d_o=96.0, f_yw=50.0, f_ys=50.0, tension_field=True)
        i_t2 = 96.0**4 / 40.0 * (50.0 / 29000.0) ** 1.5
        assert r.details["I_t2"] == pytest.approx(i_t2, rel=1e-6)
        assert r.demand == pytest.approx(i_t2, rel=1e-6)   # I_t2 governs
        assert r.ok is False                               # 36 < ~152
        assert r.details["validate_against_brr"] is True


class TestBearingStiffenerDetails:
    def test_projecting_width(self):
        # limit = 0.48*0.625*sqrt(29000/50) = 7.225
        r = lrfd.bearing_stiffener_width(b_t=7.0, t_p=0.625, f_ys=50.0)
        assert r.capacity == pytest.approx(
            0.48 * 0.625 * math.sqrt(29000.0 / 50.0))
        assert r.ok is True
        assert lrfd.bearing_stiffener_width(
            b_t=7.5, t_p=0.625, f_ys=50.0).ok is False

    def test_effective_column(self):
        r = lrfd.bearing_stiffener_effective_column(
            b_t=7.0, t_p=0.625, t_w=0.5625, d_web=96.0, f_ys=50.0,
            p_u=300.0)
        # recompute the effective section by hand
        strip = 18.0 * 0.5625 + 0.625
        a_g = 2 * 7.0 * 0.625 + strip * 0.5625
        off = 0.5625 / 2 + 3.5
        i = 2 * (0.625 * 7.0**3 / 12 + 0.625 * 7.0 * off**2) \
            + strip * 0.5625**3 / 12
        assert r.details["Ag"] == pytest.approx(a_g)
        assert r.details["r"] == pytest.approx(math.sqrt(i / a_g))
        assert r.details["KL/r"] == pytest.approx(
            0.75 * 96.0 / math.sqrt(i / a_g))
        assert r.phi == 0.95 and r.capacity > 0.0 and r.ok is True


class TestFlangeResistanceFamily:
    def test_fnc_wrapper_takes_the_minimum(self):
        r = lrfd.compression_flange_resistance(
            l_b=240.0, b_fc=16.0, t_fc=1.5, d_c=48.0, t_w=0.5625,
            f_yc=50.0, f_yw=50.0)
        assert r.capacity == pytest.approx(
            min(r.details["Fnc_FLB"], r.details["Fnc_LTB"]))
        assert r.details["governing"] in ("FLB", "LTB")
        # a compact flange with a short unbraced length reaches Rb*Rh*Fyc
        r2 = lrfd.compression_flange_resistance(
            l_b=60.0, b_fc=16.0, t_fc=1.5, d_c=48.0, t_w=0.5625,
            f_yc=50.0, f_yw=50.0)
        assert r2.capacity == pytest.approx(50.0)

    def test_discretely_braced_combo(self):
        r = lrfd.discretely_braced_compression_flange(
            f_nc=45.0, f_bu=30.0, f_l=9.0, f_yf=50.0)
        assert r.demand == pytest.approx(33.0)          # fbu + fl/3
        assert r.ratio == pytest.approx(45.0 / 33.0)
        assert r.details["fl_ok"] is True               # 9 <= 0.6*50

    def test_continuously_braced(self):
        r = lrfd.continuously_braced_flange(f_yf=50.0, f_bu=42.0)
        assert r.capacity == pytest.approx(50.0)
        assert r.ok is True


class TestShearConnectorDetails:
    def test_fatigue_resistance_infinite_life(self):
        r = lrfd.shear_connector_fatigue_resistance(d_stud=0.875)
        assert r.capacity == pytest.approx(5.5 * 0.875**2)
        assert r.details["combination"] == "Fatigue I"

    def test_fatigue_resistance_finite_life(self):
        r = lrfd.shear_connector_fatigue_resistance(d_stud=0.875,
                                                    n_cycles=2.0e6)
        alpha = 34.5 - 4.28 * math.log10(2.0e6)
        assert r.details["alpha"] == pytest.approx(alpha)
        assert r.capacity == pytest.approx(alpha * 0.875**2)

    def test_transverse_spacing(self):
        # gauge 3.0 < 4d = 3.5 -> fails on gauge
        bad = lrfd.shear_connector_transverse_spacing(
            d_stud=0.875, n_per_row=3, gauge_in=3.0, flange_width_in=12.0)
        assert bad.ok is False and bad.details["governing"] == "gauge"
        # gauge 4.0 passes; edge clear = (12 - 8 - 0.875)/2 = 1.5625
        good = lrfd.shear_connector_transverse_spacing(
            d_stud=0.875, n_per_row=3, gauge_in=4.0, flange_width_in=12.0)
        assert good.details["edge_clear"] == pytest.approx(1.5625)
        assert good.ok is True


class TestNonslenderElement:
    def test_angle_leg(self):
        # L4x4x1/2: b/t = 8; limit 0.45*sqrt(580) = 10.84
        r = lrfd.nonslender_element_limit(b=4.0, t=0.5, f_y=50.0)
        assert r.capacity == pytest.approx(0.45 * math.sqrt(29000.0 / 50.0))
        assert r.demand == pytest.approx(8.0)
        assert r.ok is True


class TestConnectionElementShear:
    def test_gross_and_net(self):
        r = lrfd.connection_element_shear(a_vg=20.0, f_y=50.0, a_vn=16.0,
                                          f_u=65.0)
        assert r.details["R_gross"] == pytest.approx(0.58 * 50.0 * 20.0)
        assert r.details["R_net"] == pytest.approx(0.8 * 0.58 * 65.0 * 16.0)
        assert r.capacity == pytest.approx(
            min(r.details["R_gross"], r.details["R_net"]))
        assert r.details["governing"] == "net"

    def test_gross_only(self):
        r = lrfd.connection_element_shear(a_vg=20.0, f_y=50.0, v_u=500.0)
        assert r.capacity == pytest.approx(580.0)
        assert r.ok is True


class TestRCFlexure:
    def test_singly_reinforced_rectangular(self):
        # As = 3.0 in^2, fy = 60, f'c = 4, b = 12, ds = 21.5
        # a = 3*60/(0.85*4*12) = 4.412 in, c = a/0.85 = 5.190
        # Mn = 180*(21.5 - 2.206) = 3472.9 kip-in
        # eps_t = 0.003*(21.5-5.190)/5.190 = 0.00943 > 0.005 -> phi = 0.9
        r = lrfd.rc_rectangular_flexural_resistance(
            a_s=3.0, f_y=60.0, f_c=4.0, b=12.0, d_s=21.5
        )
        assert r.details["a"] == pytest.approx(4.4118, abs=1e-3)
        assert r.capacity == pytest.approx(180.0 * (21.5 - 4.4118 / 2.0), rel=1e-4)
        assert r.phi == pytest.approx(0.9)
        assert r.details["tension_controlled"]

    def test_over_reinforced_reduces_phi(self):
        # Heavy steel drives c up and eps_t below 0.005
        r = lrfd.rc_rectangular_flexural_resistance(
            a_s=12.0, f_y=60.0, f_c=4.0, b=12.0, d_s=21.5
        )
        assert r.details["eps_t"] < 0.005
        assert r.phi < 0.9

    def test_compression_steel_increases_capacity(self):
        base = lrfd.rc_rectangular_flexural_resistance(
            a_s=8.0, f_y=60.0, f_c=4.0, b=12.0, d_s=21.5
        )
        with_comp = lrfd.rc_rectangular_flexural_resistance(
            a_s=8.0, f_y=60.0, f_c=4.0, b=12.0, d_s=21.5,
            a_s_prime=2.0, d_s_prime=2.5,
        )
        assert with_comp.factored_capacity > base.factored_capacity


class TestRCMinReinforcement:
    def test_mcr_governs_without_demand(self):
        # 12x24 beam: Sc = 12*24^2/6 = 1152 in^3, fr = 0.24*sqrt(4) = 0.48
        # Mcr = 0.67*1.6*0.48*1152 = 592.8 kip-in
        r = lrfd.rc_minimum_reinforcement(m_n=1000.0, phi=0.9, f_c=4.0, s_c=1152.0)
        assert r.demand == pytest.approx(0.67 * 1.6 * 0.48 * 1152.0)
        assert r.ok

    def test_133_mu_governs_when_smaller(self):
        r = lrfd.rc_minimum_reinforcement(
            m_n=1000.0, phi=0.9, f_c=4.0, s_c=1152.0, m_u=300.0
        )
        assert r.demand == pytest.approx(1.33 * 300.0)


class TestRCShear:
    def test_concrete_only_simplified(self):
        # bv = 12, dv = 20, f'c = 4: Vc = 0.0316*2*2*12*20 = 30.34 kip
        r = lrfd.rc_shear_resistance(b_v=12.0, d_v=20.0, f_c=4.0)
        assert r.capacity == pytest.approx(0.0316 * 2.0 * 2.0 * 12.0 * 20.0)
        assert r.phi == 0.9

    def test_stirrups_add_vs(self):
        # #4 stirrups (Av = 0.40) at 12 in, theta = 45: Vs = 0.4*60*20/12 = 40
        r = lrfd.rc_shear_resistance(
            b_v=12.0, d_v=20.0, f_c=4.0, a_v=0.40, s=12.0, f_y=60.0
        )
        assert r.details["Vs"] == pytest.approx(40.0)

    def test_upper_limit_governs(self):
        r = lrfd.rc_shear_resistance(
            b_v=12.0, d_v=20.0, f_c=4.0, a_v=4.0, s=3.0, f_y=60.0
        )
        assert r.capacity == pytest.approx(0.25 * 4.0 * 12.0 * 20.0)


class TestRegistry:
    def test_articles_registered(self):
        for num in ("6.10.8.2.2", "6.10.8.2.3", "6.10.8.1.2", "6.10.9",
                    "5.6.3.2", "5.6.3.3", "5.7.3.3"):
            assert num in lrfd.ARTICLES

    def test_design_loop_over_flange_sizes(self):
        """The motivating use case: size a compression flange by looping."""
        demand = 42.0  # ksi factored flange stress
        candidates = [(w, t) for w in (12, 14, 16, 18) for t in (0.75, 1.0, 1.25)]
        passing = [
            (w, t)
            for w, t in candidates
            if lrfd.flange_local_buckling_resistance(
                b_fc=w, t_fc=t, f_yc=50.0, f_yw=50.0, f_bu=demand
            ).ok
        ]
        assert passing  # at least one candidate works
        assert all(
            w / (2 * t) <= 0.56 * math.sqrt(29000.0 / 35.0) for w, t in passing
        )
