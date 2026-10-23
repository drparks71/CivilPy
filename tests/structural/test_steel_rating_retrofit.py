#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Steel LRFR (MBE 6A as summarized in NSBA SBDH Chapter 18) and the
retrofit design examples FHWA HIF-18-043 (plate girder shear and flexural
strengthening, 86-ft noncomposite A36 girder with corrosion loss) and
HIF-18-044 (stringer retrofit: composite action and continuity, W24x76 to
W24x62).  Values are the examples' own; where an example slips, the test
pins both the example's arithmetic and the corrected value."""

import math

import pytest

from civilpy.structural.aashto.lrfd import (
    bolt_shear_resistance, compact_composite_positive_flexure,
    lateral_torsional_buckling_resistance, plastic_moment, web_shear_resistance,
    yield_moment_composite)
from civilpy.structural.aashto.lrfd.composite import transformed_composite_section
from civilpy.structural.aashto.lrfd.lrfr import (
    CONDITION_FACTORS, EMERGENCY_VEHICLE_LOAD_FACTOR, SYSTEM_FACTORS, legal_load_factor,
    permit_load_factor, rating_factor, service_ii_flange_limit, steel_member_rating)
from civilpy.structural.member_strengthening import (
    Piece, StrengthenedGirder, eccentric_bolt_group, effective_net_width,
    partial_composite_plastic_moment, post_installed_connector_strength,
    section_from_pieces, shear_flow_bolt_force, splice_web_design_shear)


# ── SBDH Ch. 18 tables ──────────────────────────────────────────────────────


def test_condition_and_system_factors():
    assert (CONDITION_FACTORS["good"], CONDITION_FACTORS["fair"], CONDITION_FACTORS["poor"]) == (1.0, 0.95, 0.85)
    assert SYSTEM_FACTORS["welded_two_girder"] == 0.85
    assert SYSTEM_FACTORS["riveted_two_girder"] == SYSTEM_FACTORS["multiple_eyebar_truss"] == 0.90
    assert SYSTEM_FACTORS["four_girder_spacing_le_4ft"] == 0.95
    assert SYSTEM_FACTORS["floorbeams_spacing_gt_12ft"] == 0.85


@pytest.mark.parametrize("adtt,gamma", [(None, 1.45), (6000, 1.45), (5000, 1.45), (1000, 1.30),
                                        (500, 1.30), (3000, 1.375)])
def test_legal_load_factors(adtt, gamma):
    assert legal_load_factor(adtt) == pytest.approx(gamma)


@pytest.mark.parametrize("adtt,pwr,gamma", [(6000, 1.5, 1.40), (6000, 2.5, 1.35), (6000, 3.5, 1.30),
                                            (1000, 1.5, 1.35), (1000, 2.5, 1.25), (1000, 3.5, 1.20),
                                            (50, 1.5, 1.30), (50, 2.5, 1.20), (50, 3.5, 1.15)])
def test_routine_permit_table(adtt, pwr, gamma):
    assert permit_load_factor("routine", adtt=adtt, gvw_over_al=pwr) == pytest.approx(gamma)
    assert permit_load_factor("routine", adtt=adtt, gvw_over_al=pwr,
                              refined_analysis=True) == pytest.approx(gamma + 0.10)
    assert permit_load_factor("routine", adtt=adtt, gvw_over_al=pwr, one_lane=True) == 1.40


def test_special_permits_and_emergency_vehicles():
    assert permit_load_factor("single_trip_escorted") == 1.10
    assert permit_load_factor("single_trip_mixed") == 1.20
    assert permit_load_factor("multiple_trip_mixed") == 1.40
    assert permit_load_factor("single_trip_escorted", crawl_speed=True) == pytest.approx(1.155)
    assert permit_load_factor("single_trip_mixed", refined_analysis=True) == 1.00
    assert EMERGENCY_VEHICLE_LOAD_FACTOR == 1.30


@pytest.mark.parametrize("composite,limit", [(True, 0.95 * 50), (False, 0.80 * 50)])
def test_service_ii_limit(composite, limit):
    assert service_ii_flange_limit(50.0, composite=composite) == pytest.approx(limit)


def test_shear_takes_the_condition_factor_but_not_the_system_factor():
    m, v = (5000.0, 1500.0, 200.0, 1200.0), (400.0, 80.0, 10.0, 90.0)
    reduced = steel_member_rating(moment=m, shear=v, condition="fair", system="riveted_two_girder")
    assert reduced["shear"].capacity == pytest.approx((0.95 * 400 - 1.25 * 80 - 1.5 * 10) / (1.75 * 90))
    cs = max(0.95 * 0.90, 0.85)
    want = (cs * 5000 - 1.25 * 1500 - 1.5 * 200) / (1.75 * 1200)
    assert reduced["flexure"].capacity == pytest.approx(want)


def test_cs_floor_and_service_ii_levels():
    r = rating_factor(1000, 300, 200, condition="poor", system="welded_two_girder")
    assert r.details["C"] == pytest.approx(0.85 * 1000)       # 0.85 x 0.85 floored at 0.85
    inv = steel_member_rating(service_stress=(47.5, 20.0, 2.0, 15.0))
    opr = steel_member_rating(level="operating", service_stress=(47.5, 20.0, 2.0, 15.0))
    assert inv["service II"].capacity == pytest.approx((47.5 - 22.0) / (1.30 * 15.0))
    assert opr["service II"].capacity == pytest.approx((47.5 - 22.0) / (1.00 * 15.0))


# ── HIF-18-043: plate girder with corrosion loss ───────────────────────────

P = Piece.plate
TF, WEB, BF = P(15, 1.375, 30.1875), P(0.375, 59, 0.0), P(15, 1.375, -30.1875)
LOSS = Piece(-5.625, -30.6875, -15 * 0.375 ** 3 / 12)          # 3/8 in. off the bottom flange
MOMENTS = (1266.0, 168.0, 1091.0)                              # DC1, DW, LL+IM at 0.5 L, k-ft
SHEARS = (58.87, 7.84, 64.19)                                  # at the bearing, kip


def test_as_built_and_as_inspected_sections():
    ab = section_from_pieces([TF, WEB, BF])
    assert ab["I"] == pytest.approx(44_015, abs=1)
    assert ab["I"] / 30.875 == pytest.approx(1_426, abs=1)
    ai = section_from_pieces([TF, WEB, BF, LOSS])
    assert ai["y"] == pytest.approx(2.989, abs=1e-3)
    assert ai["I"] == pytest.approx(38_202, abs=1)
    assert ai["I"] / (30.875 - ai["y"]) == pytest.approx(1_370, abs=1)
    assert ai["I"] / (30.5 + ai["y"]) == pytest.approx(1_141, abs=1)


def test_end_panel_shear_with_web_loss():
    full = web_shear_resistance(59, 0.375, 36, d_o=48)
    assert full.details["k"] == pytest.approx(12.554, abs=1e-3)
    assert full.details["C"] == pytest.approx(0.6414, abs=1e-4)
    assert full.capacity == pytest.approx(296.3, abs=0.1)
    lost = web_shear_resistance(59, 0.375, 36, d_o=48, web_loss_area=36 * 0.25)
    assert lost.details["Vp"] == pytest.approx(274.05)
    assert lost.capacity == pytest.approx(175.8, abs=0.1)


def test_existing_ratings_match_the_example():
    built = steel_member_rating(moment=(4278.0, *MOMENTS), shear=(296.3, *SHEARS))
    assert built["flexure"].capacity == pytest.approx(1.279, abs=1e-3)
    assert built["shear"].capacity == pytest.approx(1.878, abs=1e-3)
    inspected = steel_member_rating(moment=(3423.0, *MOMENTS), shear=(175.8, *SHEARS))
    assert inspected["flexure"].capacity == pytest.approx(0.832, abs=1e-3)
    assert inspected["shear"].capacity == pytest.approx(0.805, abs=1e-3)
    assert inspected["governing"] is inspected["shear"]


def test_strengthened_flexure_on_the_examples_geometry():
    # the example's pieces: existing net section with its hole strip, the
    # strengthened net section with the combined-ply holes
    top_pl = Piece(5.625, -29.75, 11.25 * 0.5 ** 3 / 12)
    bot_pl = Piece(5.625, -31.0625, 15 * 0.375 ** 3 / 12)
    g = StrengthenedGirder(existing=[TF, WEB, BF, LOSS, Piece(-2.25, -29.0)], added=[top_pl, bot_pl],
                           strengthened=[TF, WEB, BF, LOSS, top_pl, bot_pl, Piece(-4.219, -30.125)],
                           fibers={"flange": (-30.875, "existing"), "plate": (-31.25, "added")},
                           fy_existing=36, fy_added=50)
    s = section_from_pieces(g.strengthened)
    assert (s["y"], s["I"]) == (pytest.approx(-0.654, abs=1e-3), pytest.approx(45_268, abs=1))
    r = g.rating_factors(*MOMENTS)
    assert r["flange"]["S_existing"] == pytest.approx(1_018, abs=1)
    assert r["flange"]["S_strengthened"] == pytest.approx(1_498, abs=1)
    assert r["plate"]["S_strengthened"] == pytest.approx(1_480, abs=1)
    assert r["flange"]["f_DC"] == pytest.approx(14.92, abs=0.01)
    assert r["flange"]["f_u"] == pytest.approx(35.97, abs=0.02)
    assert r["plate"]["f_u"] == pytest.approx(17.52, abs=0.02)
    assert r["flange"]["RF"] == pytest.approx(1.00, abs=0.005)
    # the example rates the new Gr 50 plate at 36 ksi (2.19); at 50 ksi it is 3.10
    assert r["plate"]["RF"] == pytest.approx(3.10, abs=0.01)
    g.fy_added = 36.0
    assert g.rating_factors(*MOMENTS)["plate"]["RF"] == pytest.approx(2.19, abs=0.01)


def test_the_examples_net_flange_modulus_skips_the_section_loss():
    # 35,806 / 35.161 = 1,018 in^3 measures to the original flange bottom; the
    # corroded bottom is 3/8 in. higher (ybf - SL), 1,029 in^3
    net = section_from_pieces([TF, WEB, BF, LOSS, Piece(-2.25, -29.0)])
    assert net["I"] == pytest.approx(35_806, abs=1)
    assert net["I"] / (30.875 + net["y"]) == pytest.approx(1_018, abs=1)
    assert net["I"] / (30.5 + net["y"]) == pytest.approx(1_029, abs=1)


def test_bolted_connections_of_the_shear_strengthening():
    bolt = bolt_shear_resistance(0.875, 120.0, n_planes=2)
    assert bolt.factored_capacity == pytest.approx(55.40, abs=0.05)
    assert effective_net_width(15.0, 1.0, 2) == pytest.approx(12.75)         # 0.85 Wg governs
    assert effective_net_width(5.625, 1.0, 1) == pytest.approx(4.625)
    v_uv = splice_web_design_shear(197.68, 812.0)
    assert v_uv == pytest.approx(296.52)
    bolts = [(sx * 1.5, (k - 3.5) * 3.0) for sx in (-1, 1) for k in range(8)]
    g = eccentric_bolt_group(bolts, v_uv, v_uv * 3.5)
    assert g["J"] == pytest.approx(792.0)
    assert g["R_max"] == pytest.approx(24.69, abs=0.01)
    assert shear_flow_bolt_force(197.68, 478.498, 55_382, 6.0) == pytest.approx(10.25, abs=0.01)


# ── HIF-18-044: stringer composite action and continuity ───────────────────

W24X62 = dict(steel_area=18.2, steel_i=1550, steel_depth=23.74, t_slab=8, t_haunch=1.5)


def test_short_long_and_negative_composite_sections():
    st = transformed_composite_section(b_eff=78, n=8, **W24X62)
    assert (st["x"], st["y"]) == (pytest.approx(7.26, abs=0.01), pytest.approx(14.11, abs=0.01))
    assert st["I"] == pytest.approx(6_418, abs=2)
    assert (st["S_top_slab"], st["S_bottom_steel"]) == (pytest.approx(884, abs=1), pytest.approx(247, abs=1))
    lt = transformed_composite_section(b_eff=78, n=24, **W24X62)
    assert lt["y"] == pytest.approx(10.22, abs=0.01) and lt["I"] == pytest.approx(4_920, abs=2)
    assert (lt["S_top_slab"], lt["S_bottom_steel"]) == (pytest.approx(441, abs=1), pytest.approx(223, abs=1))
    ng = transformed_composite_section(rebar_area=6.63, rebar_depth=9.5 + 11.87 - 16.88,
                                       negative=True, **W24X62)
    assert ng["y"] == pytest.approx(4.51, abs=0.01) and ng["I"] == pytest.approx(2_935, abs=1)
    assert ng["S_bottom_steel"] == pytest.approx(179, abs=1)


@pytest.mark.parametrize("b,t,d,tw,rt,fnc", [(8.99, 0.68, 23.92, 0.44, 2.29, 29.73),
                                             (7.04, 0.59, 23.74, 0.43, 1.71, 26.2)])
def test_negative_flexure_ltb_of_the_stringers(b, t, d, tw, rt, fnc):
    r = lateral_torsional_buckling_resistance(169.5, b, t, (d - 2 * t) / 2, tw, 36, 36)
    assert r.details["rt"] == pytest.approx(rt, abs=0.015)
    assert r.capacity == pytest.approx(fnc, rel=0.006)          # the example rounds rt


def test_composite_positive_flexure_resistance():
    # D6.2.2 with the example's numbers: it enters MDC1 as 304 k-in (25.3 k-ft)
    # where the factored moment is 32 k-ft = 384 k-in
    kw = dict(m_d2=(5.6 + 8.1) * 12, s_nc_top=131, s_nc_bot=131, s_lt_top=1e9, s_lt_bot=223,
              s_st_top=1e9, s_st_bot=247, f_y_top=36, f_y_bot=36)
    assert yield_moment_composite(m_d1=304, **kw).my / 12 == pytest.approx(724 - (32 - 304 / 12), abs=1)
    my = yield_moment_composite(m_d1=384, **kw).my
    assert my / 12 == pytest.approx(711.2, abs=0.1)
    mp = plastic_moment(b_c=7.04, t_c=0.59, f_yc=36, d_web=22.56, t_w=0.43, f_yw=36, b_t=7.04,
                        t_t=0.59, f_yt=36, f_c=3.5, b_s=78, t_s=8, t_haunch=1.5)
    # 0.85 f'c slab block (the example uses f'c: 1,101 k-ft)
    assert mp.mp / 12 == pytest.approx(1_079, abs=1)
    mn = compact_composite_positive_flexure(mp.mp, mp.dp, 33.24, m_y=my, continuous_span=True)
    assert mn.details["capped_13RhMy"] and mn.capacity == pytest.approx(1.3 * my)


def test_stringer_ratings():
    existing_pos = rating_factor(528, 59.3, 171.3)
    existing_neg = rating_factor(436, 105.5, 148.0)
    assert (existing_pos.capacity, existing_neg.capacity) == (pytest.approx(1.51, abs=0.01),
                                                              pytest.approx(1.17, abs=0.01))
    assert existing_neg.capacity / 1.25 == pytest.approx(0.94, abs=0.01)         # HS-25
    pos = rating_factor(941, 25.6 + 4.5, 128.1, dw=5.4)
    neg = rating_factor(391, 50.7 + 8.9, 119.0, dw=10.7)
    assert (pos.capacity, neg.capacity) == (pytest.approx(3.99, abs=0.01), pytest.approx(1.44, abs=0.01))
    # those live-load moments are the HS-20 table values; as HS-25 ratings
    assert (pos.capacity / 1.25, neg.capacity / 1.25) == (pytest.approx(3.19, abs=0.01),
                                                          pytest.approx(1.15, abs=0.01))


# ── post-installed shear connectors ────────────────────────────────────────

GIRDER = dict(b_c=7.04, t_c=0.59, d_web=22.56, t_w=0.43, b_t=7.04, t_t=0.59, f_y=36, b_s=78,
              t_s=8, f_c=3.5, t_haunch=1.5)


def test_partial_composite_limits():
    full = plastic_moment(b_c=7.04, t_c=0.59, f_yc=36, d_web=22.56, t_w=0.43, f_yw=36, b_t=7.04,
                          t_t=0.59, f_yt=36, f_c=3.5, b_s=78, t_s=8, t_haunch=1.5)
    assert partial_composite_plastic_moment(sum_qn=1e9, **GIRDER).mp == pytest.approx(full.mp)
    steel = plastic_moment(flexure="negative", b_c=7.04, t_c=0.59, f_yc=36, d_web=22.56, t_w=0.43,
                           f_yw=36, b_t=7.04, t_t=0.59, f_yt=36)
    assert partial_composite_plastic_moment(sum_qn=0.0, **GIRDER).mp == pytest.approx(steel.mp)


def test_partial_composite_grows_with_connectors():
    ms = [partial_composite_plastic_moment(sum_qn=q, **GIRDER) for q in range(0, 700, 50)]
    assert all(b.mp >= a.mp for a, b in zip(ms, ms[1:]))
    assert ms[-1].composite_ratio == pytest.approx(1.0)
    third = partial_composite_plastic_moment(sum_qn=0.3 * ms[-1].c_slab, **GIRDER)
    assert 1.3 < third.mp / ms[0].mp < ms[-1].mp / ms[0].mp


def test_post_installed_connector_strength():
    assert post_installed_connector_strength(0.875, 120.0) == pytest.approx(0.5 * 120 * math.pi * 0.875 ** 2 / 4)
