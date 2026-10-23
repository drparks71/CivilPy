#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Internal redundancy evaluation (AASHTO Guide Specifications for Internal
Redundancy of Mechanically-Fastened Built-up Steel Members) and the MBE
Section 7 fatigue life it rests on.

The worked members are the NSBA Implementation Guide's examples (B010-20,
2020): truss members L0-L1 and U1-L1 of the 1917 Portland deck truss
(Section 3) and cross section XSec-1 of the 1958 riveted two-girder bridge
(Section 4), with the results the NSBA IRM Evaluator v3.2 reports for
them.  The full member-by-member comparison with the evaluator workbooks
(9 axial members, 4 cross sections, 6 two-component cases) lives in
snbi_ui with the workbooks."""

import math

import pytest

from civilpy.structural.aashto import irm, mbe_fatigue
from civilpy.structural.aashto.irm import (
    Angle, FlangeAngle, FlangePlate, FlexuralMember, MultiComponentAxialMember,
    RolledChannel, TwoComponentAxialMember)
from civilpy.structural.aashto.mbe_fatigue import Traffic

PORTLAND = Traffic(adtt_present=7200, adtt_0=50, adtt_limit=7200, year_built=1917,
                   year_current=2019, growth=1e-6, span_ft=261, lanes=3)


# ── Guide Spec rules ────────────────────────────────────────────────────────


@pytest.mark.parametrize("year,override,fcp", [(1917, False, False), (1978, False, False),
                                               (1979, False, True), (1995, True, False)])
def test_fcp_and_redundancy_ii_factors(year, override, fcp):
    assert irm.built_to_fcp(year, override) is fcp
    assert irm.redundancy_ii_factors(fcp) == ((1.05, 1.05, 1.30) if fcp else (1.15, 1.25, 1.50))


@pytest.mark.parametrize("life,case,interval", [
    (math.inf, "I(a)", 10), (25.0, "II", 10), (20.0, "I(b)", 10), (12.11, "I(b)", 8),
    (7.83, "I(b)", 4), (4.38, "I(b)", 4), (1.0, "I(b)", 2), (9.23, "II", 6), (14.78, "II", 8),
    (5.69, "II", 4), (4.0, "II", 2), (3.0, "II", 1.5), (1.4, "II", 1.0), (0.3, "II", 0.5)])
def test_special_inspection_interval(life, case, interval):
    assert irm.special_inspection_interval(life, case) == interval


@pytest.mark.parametrize("n,xi", [(1, 1.29), (2, 1.24), (3, 1.19), (6, 1.04)])
def test_bending_factor(n, xi):
    assert irm.bending_factor(n) == pytest.approx(xi)


@pytest.mark.parametrize("n,beta", [(1, 1.3125), (2, 1.375), (4, 1.5)])
def test_cover_plate_adjustment(n, beta):
    assert irm.cover_plate_adjustment(n) == pytest.approx(beta)


def test_categories_and_cases():
    assert irm.unfaulted_category("rivet") == "D"
    assert irm.unfaulted_category("bolt") == "B"
    assert irm.unfaulted_category("bolt", punched=True) == "D"
    assert irm.faulted_category() == "C" and irm.faulted_category(True) == "E'"
    assert [irm.fatigue_case(a, b) for a, b in ((True, True), (True, False), (False, False))] == [
        "I(a)", "I(b)", "II"]
    assert irm.hole_diameter(0.875) == 0.9375 and irm.hole_diameter(1.0) == 1.125


def test_total_remaining_life():
    assert irm.total_remaining_life(12.0, math.inf, 100) == 12.0
    assert irm.total_remaining_life(29.31, 28.51, 62) == pytest.approx(29.31 * (1 - 62 / 90.51))


# ── MBE 7 fatigue life ──────────────────────────────────────────────────────


@pytest.mark.parametrize("g", [0.005, 0.02, 0.04])
@pytest.mark.parametrize("cycles", [2e6, 3e7])
def test_remaining_life_inverts_the_growing_traffic_sum(g, cycles):
    t = Traffic(adtt_present=1500, adtt_0=500, adtt_limit=1e9, year_built=1960,
                year_current=2020, growth=g)
    y = mbe_fatigue.remaining_life(cycles, 0.0, t).years
    consumed = 365 * 1500 * ((1 + g) ** y - 1) * (1 + g) / g
    assert consumed == pytest.approx(cycles, rel=1e-9)


def test_adtt_limit_caps_the_growth():
    free = Traffic(1500, 500, 1e9, 1960, 2020, growth=0.03)
    capped = Traffic(1500, 500, 2000, 1960, 2020, growth=0.03)
    a = mbe_fatigue.remaining_life(4e7, 0.0, free)
    b = mbe_fatigue.remaining_life(4e7, 0.0, capped)
    assert not a.limited and b.limited and b.years > a.years
    assert b.y_limit == pytest.approx(math.log(2000 / 1500) / math.log(1.03))


def test_constant_traffic_consumed_cycles():
    t = Traffic(800, 800, 800, 1980, 2020)
    assert mbe_fatigue.consumed_cycles(t) == pytest.approx(365 * 41 * 800)


@pytest.mark.parametrize("cat", ["B", "C", "D", "E'"])
def test_infinite_life_threshold(cat):
    th = {"B": 16, "C": 10, "D": 7, "E'": 2.6}[cat]
    eff = th * 0.8 / 1.75
    assert mbe_fatigue.infinite_life(eff * 0.999, cat)[0]
    assert not mbe_fatigue.infinite_life(eff * 1.001, cat)[0]


# ── multi-component axial: the Portland deck truss ─────────────────────────


def test_l0_l1_fails_strength_and_gets_8_years():
    m = MultiComponentAxialMember(fy=30, fu=60, d_fastener=0.875,
                                  full_plates=[FlangePlate(24, 0.4375, 2, 2.5)],
                                  angle=Angle(3.5, 0.5, 1, 0))
    r = m.evaluate(p_dc=400, p_ll=156, p_fat=48.75, traffic=PORTLAND)
    assert r.p_u == pytest.approx(694.0)
    assert (r.dc_net, r.dc_gross) == (pytest.approx(1.19244, abs=1e-5), pytest.approx(1.73935, abs=1e-5))
    assert not r.strength_ok
    assert r.details["Xi_B"] == pytest.approx(1.29)
    assert r.faulted.delta_f == pytest.approx(4.97913, abs=1e-5)
    assert r.unfaulted.infinite and r.case == "I(b)"
    assert r.total_life == pytest.approx(12.1146, abs=1e-4)
    assert r.interval == 8


def test_u1_l1_built_up_i_uses_the_40_over_fastener_rule():
    m = MultiComponentAxialMember(fy=30, fu=60, d_fastener=0.875,
                                  full_plates=[FlangePlate(14, 0.3125, 2, 1.25)],
                                  angle=Angle(2.49, 0.375, 1, 0), i_section=True)
    assert m.angle_rule_required() and m.bending_factor() == 1.0
    r = m.evaluate(p_dc=90, p_ll=107, p_fat=33.75, traffic=PORTLAND)
    assert r.strength_ok
    assert r.dc_net == pytest.approx(0.321496, abs=1e-6)
    gov = max(r.faulted_stress_ranges, key=r.faulted_stress_ranges.get)
    assert gov == "angle (40-over-fastener)"
    assert r.faulted.delta_f == pytest.approx(6.98999, abs=1e-5)
    assert r.total_life == pytest.approx(4.37868, abs=1e-5)
    assert r.interval == 4


@pytest.mark.parametrize("spec", ["2P24x9/16 4L6x4x3/8", "4P24x1/2 2P16x7/16 4L4x4x1/2"])
def test_from_builtup_matches_the_spec_area(spec):
    from civilpy.structural import builtup
    m = MultiComponentAxialMember.from_builtup(spec, fy=30, fu=60, d_fastener=0.875,
                                               holes_per_web_plate=0, angle_holes=(0, 0),
                                               holes_per_cover_plate=0)
    a = m.areas()
    assert a["Ag"] == pytest.approx(builtup.properties(spec)["A"], rel=1e-3)
    assert a["An"] == pytest.approx(a["Ag"])
    webs, covers, _ = builtup.parse(spec)
    assert len(m.full_plates) == webs[0] // 2
    assert (m.web_top is not None) == bool(covers)


def test_more_plates_shed_less_bending():
    one = MultiComponentAxialMember(fy=36, fu=60, d_fastener=0.875,
                                    full_plates=[FlangePlate(24, 0.5, 2)], angle=Angle(3.5, 0.5))
    three = MultiComponentAxialMember(fy=36, fu=60, d_fastener=0.875,
                                      full_plates=[FlangePlate(24, 0.5, 2)] * 3, angle=Angle(3.5, 0.5))
    assert three.bending_factor() < one.bending_factor()
    cases = three.failure_cases()
    assert cases["PL-2f"]["exterior"] and not cases["PL-0"]["exterior"]


# ── flexural: the 1958 riveted two-girder bridge, XSec-1 ───────────────────


def _xsec1(**kw):
    angle = FlangeAngle(13.3, 0.875, 79.7, 2.31, (6.0,), 1)
    return FlexuralMember(fy=33, fu=66, d_fastener=0.875, web_depth=70, web_t=0.5,
                          depth_angles=70.5, tension_plates=[(20, 0.4375)] * 2,
                          compression_plates=[(20, 0.4375)] * 2, tension_angle=angle,
                          compression_angle=angle, composite=True, b_eff=84, t_slab=8,
                          n=29000 / 3400, b_haunch=22, t_haunch=3.9, **kw)


XSEC1_TRAFFIC = Traffic(1606, 600, 5100, 1958, 2020, growth=0.01, span_ft=111.24, lanes=2)
XSEC1_LOADS = dict(m_dc1=1118, m_dw=148, m_ll=3354, m_fat=1382.5, traffic=XSEC1_TRAFFIC)


def test_xsec1_reproduces_the_evaluator_with_its_net_inertia():
    r = _xsec1(nsba_net_inertia=True).evaluate(**XSEC1_LOADS)
    d = r.details
    assert d["S_AFN_COMP"] == pytest.approx(3047.953, abs=1e-3)
    assert d["S_AFN_NC"] == pytest.approx(2450.972, abs=1e-3)
    assert d["S_N"] == pytest.approx(3600.291, abs=1e-3)
    assert (r.dc_net, r.dc_gross) == (pytest.approx(0.508155, abs=1e-6), pytest.approx(0.777176, abs=1e-6))
    assert r.unfaulted.delta_f == pytest.approx(3.686369, abs=1e-6)
    assert r.faulted.delta_f == pytest.approx(5.987297, abs=1e-6)
    assert r.unfaulted.remaining_years == pytest.approx(28.512756, abs=1e-5)
    assert r.faulted.remaining_years == pytest.approx(29.311862, abs=1e-5)
    assert r.case == "II" and r.total_life == pytest.approx(9.233637, abs=1e-5)
    assert r.interval == 6


def test_net_inertia_is_about_the_net_centroid_by_default():
    # parallel-axis theorem: the evaluator's mixed-axis net inertia misses
    # A_g (y_g - y_n)^2; the corrected section is stiffer, the interval unchanged
    a, b = _xsec1(), _xsec1(nsba_net_inertia=True)
    for comp in (True, False):
        g = a.section(net=False, composite=comp)
        n_ok, n_nsba = a.section(net=True, composite=comp), b.section(net=True, composite=comp)
        assert n_ok["I"] - n_nsba["I"] == pytest.approx(g["A"] * (g["y"] - n_ok["y"]) ** 2, rel=1e-9)
    assert a.evaluate(**XSEC1_LOADS).interval == b.evaluate(**XSEC1_LOADS).interval == 6


@pytest.mark.parametrize("failed", [1, 2])
def test_failing_a_cover_plate_lowers_the_section(failed):
    m = _xsec1()
    whole, faulted = m.section(net=False), m.section(net=False, faulted=failed)
    assert faulted["A"] == pytest.approx(whole["A"] - 20 * 0.4375)
    assert faulted["S"] < whole["S"]


# ── two-component members ──────────────────────────────────────────────────


@pytest.mark.parametrize("continuous,laced", [(True, True), (True, False), (False, True), (False, False)])
def test_channel_additional_moment_is_linear_in_load(continuous, laced):
    kw = dict(d_ch=12.0, e=1.2, continuous=continuous, laced=laced, n_stay_pairs=4,
              panel_length=60.0, lattice_spacing=18.0, lattice_factor=1.0)
    m1, m2 = irm.channel_additional_moment(100, **kw), irm.channel_additional_moment(200, **kw)
    assert m2 == pytest.approx(2 * m1)


def test_two_angle_member_surviving_angle_carries_the_load():
    m = TwoComponentAxialMember(fy=36, fu=60, d_fastener=0.875, angle=Angle(11.5, 0.75, 1, 1),
                                i_intact=69.9)
    t = Traffic(1200, 300, 4000, 1931, 2024, growth=0.01, span_ft=180, lanes=2)
    r = m.evaluate(p_dc=60, p_ll=70, p_fat=30, traffic=t)
    a_n = 11.5 - 2 * 0.75 * 0.9375
    assert r.stresses_net["surviving"] == pytest.approx(174 / a_n)
    assert r.details["Xi_B"] == pytest.approx(1.2 + 0.15 * (2 + 69.9 / 11))
    assert r.unfaulted.delta_f == pytest.approx(24 / (2 * a_n))
    assert r.total_life == pytest.approx(20.0719, abs=1e-4) and r.interval == 10


def test_two_channel_member_adds_the_bending_stress():
    ch = RolledChannel(7.34, 0.501, 0.387, holes_web=2)
    m = TwoComponentAxialMember(fy=36, fu=60, d_fastener=0.875, channel=ch, channel_depth=12,
                                c=2.4, i_y=4.45, e=1.2, continuous=True, laced=True,
                                panel_length=60, lattice_spacing=18, lattice_factor=1.0)
    t = Traffic(1200, 300, 4000, 1931, 2024, growth=0.01, span_ft=180, lanes=2)
    r = m.evaluate(p_dc=80, p_ll=90, p_fat=35, traffic=t)
    assert r.details["M_AF"] == pytest.approx(14.158644, abs=1e-6)
    a_n = 7.34 - 0.9375 * 0.387 * 2
    assert r.stresses_net["surviving"] == pytest.approx(227 / a_n + 14.158644 * 2.4 / 4.45, abs=1e-5)
    assert r.interval == 4
