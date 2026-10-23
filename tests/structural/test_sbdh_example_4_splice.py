#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NSBA Steel Bridge Design Handbook Design Example 4 (B954-25, AASHTO LRFD
10th Ed.), three-span continuous horizontally curved I-girder bridge: Field
Splice #2 on Girder G4 (Section 7.12) checked independently with the civilpy
splice and connection primitives, plus the cross-frame stability bracing
check of the same example.

Splice: 7/8 in. ASTM F3125 Grade 325 bolts, standard holes, Class B; web
84 x 9/16 (smaller side), top flange 17 x 1 / bottom flange 21 x 1-1/2
(smaller side, Grade 50) with a 1/4 in. filler on the top flange.  Strength I
moments +1,445 / -7,978 k-ft, Vr = 617 k.
"""

import math

import pytest

from civilpy.structural.aashto import lrfd
from civilpy.structural.aashto.lrfd import bolted_field_splice as bfs
from civilpy.structural.aashto.lrfd import splices as sp
from civilpy.structural.aashto.lrfd import stability_bracing as sb

HOLE = 0.9375


def test_bolt_resistances():
    slip = lrfd.bolt_slip_resistance("A325", 0.875, n_planes=2)
    assert slip.capacity == pytest.approx(39.0)                        # Kh Ks Ns Pt
    x = lrfd.bolt_shear_resistance(0.875, 120.0, n_planes=2)           # threads excluded
    n = lrfd.bolt_shear_resistance(0.875, 120.0, n_planes=2, threads_excluded=False)
    assert x.capacity == pytest.approx(80.8, abs=0.1) and x.factored_capacity == pytest.approx(64.6, abs=0.1)
    assert n.capacity == pytest.approx(64.9, abs=0.1) and n.factored_capacity == pytest.approx(51.9, abs=0.1)
    # web bearing at the end bolts: Lc = 1.28 in. < 2d
    br = lrfd.bolt_bearing_resistance(0.875, 0.5625, 65.0, clear_distance=1.28)
    assert (br.capacity, br.factored_capacity) == (pytest.approx(56.16), pytest.approx(44.93, abs=0.01))
    assert 0.76 * math.pi * 0.875 ** 2 / 4 * 120 == pytest.approx(54.8, abs=0.05)   # Tn


def test_flange_design_forces_and_bolts():
    top = sp.flange_splice_design_force(17.0 - 4 * HOLE, 17.0, 50, 65)
    assert top.details["Ae"] == pytest.approx(14.5, abs=0.01) and top.capacity == pytest.approx(725, abs=0.5)
    bot = sp.flange_splice_design_force((21.0 - 4 * HOLE) * 1.5, 31.5, 50, 65)
    assert bot.details["Ae"] == pytest.approx(28.3, abs=0.05) and bot.capacity == pytest.approx(1_415, abs=2)
    r = sp.filler_plate_reduction(0.25 * 17.0, 1.0 * 17.0, total_filler_thickness=0.25)
    assert r.capacity == pytest.approx(0.83, abs=0.005)
    phi_rn = lrfd.bolt_shear_resistance(0.875, 120.0, n_planes=2).factored_capacity
    assert top.capacity / (r.capacity * phi_rn) == pytest.approx(13.5, abs=0.05)   # use 16
    assert bot.capacity / phi_rn == pytest.approx(21.9, abs=0.05)                # use 24


def test_moment_resistance_and_web_force():
    pos = sp.flange_moment_resistance(1_415, 84 + 1.5 / 2 + 4.0 + 9.0 / 2, m_u=1_445 * 12)
    assert pos.capacity / 12 == pytest.approx(10_996, abs=1) and pos.ok
    neg = sp.flange_moment_resistance(725, 84 + (1.0 + 1.5) / 2, m_u=7_978 * 12)
    assert neg.capacity / 12 == pytest.approx(5_151, abs=1) and not neg.ok
    assert bfs._web_moment_force(7_978, 5_151, 84.0) == pytest.approx(1_615, abs=1)
    # the excess moment as a web horizontal force at D/4 (C6.13.6.1.3c)
    web = sp.web_splice_design_forces(617.0, 34, m_u=7_978 * 12, m_flange=5_151 * 12,
                                      moment_arm=84.0 / 4)
    assert web.h_w == pytest.approx(1_615, abs=1)
    assert web.per_bolt * 34 == pytest.approx(1_729, abs=1)
    # top flange plus deck reinforcement (8.00 in^2 x 60 ksi) about the bottom flange
    p_rs = 8.00 * 60
    arm = (725 * (1.0 / 2 + 84.0 + 1.5 / 2) + p_rs * (4.0 + 4.0 + 84.0 + 1.5 / 2)) / (725 + p_rs)
    assert arm == pytest.approx(88.24, abs=0.01)
    assert (725 + p_rs) * arm / 12 == pytest.approx(8_861, abs=2)
    # web splice resultant and bolts (threads included)
    resultant = math.hypot(617, 1_615)
    assert resultant == pytest.approx(1_729, abs=1)
    assert resultant / 51.9 == pytest.approx(33.3, abs=0.05)          # use 34


def test_flange_splice_plates():
    yield_outer = lrfd.tension_member_resistance(21.0 * 0.875, 50)
    assert yield_outer.capacity == pytest.approx(873, abs=1)
    inner = lrfd.tension_member_resistance(2 * 9.75 * 0.875, 50, (2 * 9.75 - 4 * HOLE) * 0.875, 65)
    assert inner.details["yield"] == pytest.approx(810, abs=1)
    assert inner.details["rupture"] == pytest.approx(717, abs=1)
    outer = lrfd.tension_member_resistance(21.0 * 0.875, 50, (21.0 - 4 * HOLE) * 0.875, 65)
    assert outer.details["rupture"] == pytest.approx(785, abs=1)
    # 6.13.5.2: An <= 0.85 Ag
    assert sp.net_section_reduction_limit((21.0 - 4 * HOLE) * 0.875, 21.0 * 0.875).ok


@pytest.mark.parametrize("name,avg,avn,atn,expected", [
    ("bottom flange splice plates", 29.75, 20.73, 11.10, 1_202),
    ("bottom flange, interior planes", 102.0, 71.06, 14.44, 2_894),
    ("bottom flange, outer planes", 51.00, 35.53, 19.03, 2_061),
    ("web splice plates", 58.31, 46.71, 2.70, 1_493),
])
def test_block_shear(name, avg, avn, atn, expected):
    r = lrfd.block_shear_resistance(avg, avn, atn, 50, 65)
    assert r.factored_capacity == pytest.approx(expected, abs=1.5)


def test_web_splice_plates_and_bearing():
    shear = lrfd.connection_element_shear(2 * 0.375 * 79.50, 50, 2 * 0.375 * (79.50 - 17 * HOLE), 65)
    assert shear.details["R_gross"] == pytest.approx(1_729, abs=1)
    assert shear.details["R_net"] == pytest.approx(1_438, abs=1)
    # 34 web bolts: bearing 0.80 x 34 x 1.2 Lc t Fu = 1,826 k vs bolt shear 1,765 k
    br = lrfd.bolt_bearing_resistance(0.875, 0.5625, 65.0, clear_distance=2.0 - HOLE / 2)
    assert 34 * br.factored_capacity == pytest.approx(1_826, abs=2)
    assert 34 * 51.9 == pytest.approx(1_765, abs=1)
    # slip: Service II resultant of 361 k and Hw = 929 k on 34 x 39 k
    assert math.hypot(361, 929) == pytest.approx(997, abs=1)
    assert math.hypot(361, 929) < 34 * 39.0


def test_flange_bearing_and_tension_flange_fracture():
    # four end bolts at Lc = 1.53 in. (< 2d) and twenty interior at 2.0625 in. (>= 2d)
    end = lrfd.bolt_bearing_resistance(0.875, 1.5, 65.0, clear_distance=2.0 - HOLE / 2)
    inner = lrfd.bolt_bearing_resistance(0.875, 1.5, 65.0, clear_distance=3.0 - HOLE)
    assert 4 * end.factored_capacity == pytest.approx(573, abs=1.5)
    assert 20 * inner.factored_capacity == pytest.approx(3_276, abs=1)
    # 6.10.1.8: ft <= 0.84 (An/Ag) Fu for the top flange
    assert 0.84 * (17.0 - 4 * HOLE) / 17.0 * 65 == pytest.approx(42.56, abs=0.01)


def test_cross_frame_stability_bracing():
    beta_br = sb.brace_stiffness("x_compression", 11.0 * 12, 72.0, a_d=0.65 * 11.5)
    # the handbook prints 5.80 x 10^6; the equation gives 5.76 x 10^6
    assert beta_br == pytest.approx(5.76e6, rel=2e-3)
    beta_g = sb.in_plane_girder_stiffness(4, 11.0 * 12, 313_968, 189.4 * 12)
    assert beta_g == pytest.approx(7.30e5, rel=2e-3)
    assert sb.system_stiffness(beta_br, math.inf, beta_g) == pytest.approx(6.48e5, rel=2e-3)
    req = sb.required_stiffness(189.4 * 12, 12_865 * 12, 7, 10_010, 1.202)
    assert req == pytest.approx(5.54e4, rel=2e-3)
