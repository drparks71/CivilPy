#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Heat straightening: FHWA-IF-99-004 Examples 3.1, 5.1, 6.1 and 7.1 and the
FHWA-IF-08-999 Guide equations."""

import math

import pytest

from civilpy.structural import heat_straightening as hs


def test_example_3_1_degree_of_damage_and_strain_ratio():
    # W27x161 bottom flange, A36: offsets in ft at 5 ft and 4 ft, and three
    # offsets 4 in. apart in the yield zone
    phi_d = hs.angle_of_damage(5.0, 6.0, 5.0, 5.5, 4.5, 4.0)
    assert math.degrees(phi_d) == pytest.approx(25.35, abs=0.01)
    assert phi_d == pytest.approx(0.4424, abs=1e-4)     # the Manual prints 0.0224 rad
    r = hs.radius_of_curvature(4.4, 4.49, 4.3, 4.0)
    assert r == pytest.approx(57.1, abs=0.05)
    assert hs.yield_radius(7.01, 36) == pytest.approx(5_647, abs=1)
    mu = hs.strain_ratio(r, 7.01, 36)
    assert mu == pytest.approx(98.9, abs=0.1)            # "97.1 times" in the text is a slip
    assert hs.straightenable(mu) and not hs.straightenable(101)


@pytest.mark.parametrize("ratio,fl", [(0, 0.6), (0.10, 0.8), (0.20, 1.0), (0.25, 1.1), (0.40, 1.4), (0.50, 1.6)])
@pytest.mark.parametrize("theta,base", [(10, 0.855), (20, 1.71), (30, 2.55), (40, 3.39), (45, 3.80),
                                        (50, 4.22), (60, 5.03)])
def test_example_5_1_plate_rotation_table(ratio, fl, theta, base):
    # Table 5.1 at F_l = 1.0 is 0.0147 sin(theta/3) in milliradians; every
    # row is F_l times it (the printed 30 % / 10 deg cell repeats 0.940)
    phi = hs.plastic_rotation(theta, ratio) * 1000
    assert hs.jacking_factor(ratio) == pytest.approx(fl)
    assert phi == pytest.approx(fl * base, rel=0.005)


@pytest.mark.parametrize("name,kw,fs,fa,phi_p,n", [
    ("W36x170 weak axis", dict(z_over_s=83.8 / 53.2, b_s=36, d_s=6.02, d=12.03), 1.75, 1.05, 7.50, 11),
    ("C12x20.7 strong axis", dict(z_over_s=3.49 / 1.73, b_s=2.94, d_s=12, d=12), 1.12, 1.35, 6.17, 13),
    ("L5x3x5/8", dict(z_over_s=6.27 / 3.55, b_s=3, d_s=5, d=5, angle=True), 1.3, 1.53, 8.12, 10),
])
def test_example_6_1_rolled_shapes(name, kw, fs, fa, phi_p, n):
    assert hs.basic_plastic_rotation(30) * 1000 == pytest.approx(2.55, abs=0.01)
    assert hs.shape_factor(kw["b_s"], kw["d_s"], kw["d"]) == pytest.approx(fs, abs=0.005)
    phi = hs.plastic_rotation(30, 0.5, **kw)
    f_a = phi / (1.6 * hs.shape_factor(kw["b_s"], kw["d_s"], kw["d"]) * hs.basic_plastic_rotation(30))
    assert f_a == pytest.approx(fa, abs=0.01)
    assert phi * 1000 == pytest.approx(phi_p, rel=0.01)
    assert hs.heats_required(math.radians(4.5), phi) == n


def test_example_7_1_composite_jacking():
    gamma = hs.composite_flange_distribution(53.2)
    assert gamma == pytest.approx(0.858, abs=0.001)
    assert hs.composite_jacking_moment(119.0, 53.2, residual=22.0) == pytest.approx(20.6, abs=0.1)
    assert hs.composite_jacking_moment(119.0, 53.2) == pytest.approx(46.2, abs=0.1)


def test_vee_angle_and_limits():
    # an open end of half the plate width is a 28 deg vee
    assert math.degrees(hs.vee_angle(5.0, 10.0)) == pytest.approx(28.07, abs=0.01)
    assert hs.jacking_moment_limit(100.0) == 50.0
    assert hs.jacking_moment_limit(100.0, first_two_heats=True, residuals_computed=False) == 25.0
    assert hs.temperature_factor(1200) == pytest.approx(1.0)
    assert hs.temperature_factor(800) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        hs.temperature_factor(1300)


@pytest.mark.parametrize("chord,r", [(8.0, 57.1), (20.0, 100.0)])
def test_angle_from_radius_is_the_arc_angle(chord, r):
    phi = hs.angle_from_radius(chord, r)
    assert 2 * r * math.sin(phi / 2) == pytest.approx(chord)
