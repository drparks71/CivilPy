#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Spirals, station equations and cross slopes on Alignment (property tests)."""

import math
import random

import pytest

from civilpy.transportation.alignment import Alignment, Curve, Spiral, Tangent

SEEDS = range(12)


def _layout(rng):
    """Random tangent - spiral - curve - spiral - tangent (a typical highway curve)."""
    r = rng.uniform(400.0, 5000.0)
    ls1 = rng.uniform(80.0, min(400.0, r * 0.6))
    ls2 = rng.uniform(80.0, min(400.0, r * 0.6))
    d = rng.choice("RL")
    elements = [Tangent(rng.uniform(50, 500)),
                Spiral(ls1, math.inf, r, d),
                Curve(r, rng.uniform(5.0, 40.0), d),
                Spiral(ls2, r, math.inf, d),
                Tangent(rng.uniform(50, 500))]
    al = Alignment((rng.uniform(-1e4, 1e4), rng.uniform(-1e4, 1e4)), rng.uniform(0, 360),
                   elements, start_station_ft=rng.uniform(0, 1e5))
    return al, r, d


@pytest.mark.parametrize("seed", SEEDS)
def test_entering_spiral_matches_series_formulas(seed):
    # Classic clothoid: theta = Ls/(2R); X = Ls(1 - t^2/10 + t^4/216),
    # Y = Ls(t/3 - t^3/42 + t^5/1320), from the TS along/right of the tangent.
    rng = random.Random(seed)
    r = rng.uniform(300.0, 6000.0)
    ls = rng.uniform(50.0, min(500.0, r * 0.8))
    al = Alignment((0.0, 0.0), 0.0, [Spiral(ls, math.inf, r, "R")])
    x, y, _ = al.point_at(ls)
    t = ls / (2.0 * r)
    along = ls * (1 - t**2 / 10 + t**4 / 216 - t**6 / 9360)
    right = ls * (t / 3 - t**3 / 42 + t**5 / 1320 - t**7 / 75600)
    assert y == pytest.approx(along, abs=1e-6)
    assert x == pytest.approx(right, abs=1e-6)
    assert al.bearing_at(ls) == pytest.approx(math.degrees(t), abs=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_heading_and_position_continuous_at_every_joint(seed):
    al, _, _ = _layout(random.Random(seed))
    eps = 1e-6
    for seg in al._segments[:-1]:
        s = seg["s1"]
        before, after = al._on_point(s - eps), al._on_point(s + eps)
        assert math.hypot(before[0] - after[0], before[1] - after[1]) < 1e-5
        assert abs((before[2] - after[2] + 180) % 360 - 180) < 1e-4


@pytest.mark.parametrize("seed", SEEDS)
def test_total_deflection_is_sum_of_elements(seed):
    al, r, d = _layout(random.Random(seed))
    total = sum(el.delta_deg for el in al.elements if not isinstance(el, Tangent))
    sign = 1 if d == "R" else -1
    turned = (al.bearing_at(al.end_station) - al.start_bearing) % 360
    assert turned == pytest.approx((sign * total) % 360, abs=1e-8)


@pytest.mark.parametrize("seed", SEEDS)
def test_entering_spiral_reversed_is_an_exiting_spiral(seed):
    rng = random.Random(seed)
    r, ls, az0 = rng.uniform(300, 4000), rng.uniform(60, 300), rng.uniform(0, 360)
    fwd = Alignment((0.0, 0.0), az0, [Spiral(ls, math.inf, r, "R")])
    px, py, _ = fwd.point_at(ls)
    back = Alignment((px, py), fwd.bearing_at(ls) + 180.0, [Spiral(ls, r, math.inf, "L")])
    qx, qy, _ = back.point_at(ls)
    assert math.hypot(qx, qy) < 1e-6
    assert (back.bearing_at(ls) - (az0 + 180.0) + 180) % 360 - 180 == pytest.approx(0.0, abs=1e-8)


@pytest.mark.parametrize("seed", SEEDS)
def test_compound_spiral_deflection(seed):
    rng = random.Random(seed)
    r1, r2, ls = rng.uniform(500, 3000), rng.uniform(500, 3000), rng.uniform(50, 300)
    sp = Spiral(ls, r1, r2, "L")
    assert math.radians(sp.delta_deg) == pytest.approx(ls * (1 / r1 + 1 / r2) / 2)


@pytest.mark.parametrize("seed", SEEDS)
def test_station_offset_round_trip_on_spiral_layouts(seed):
    rng = random.Random(seed)
    al, r, _ = _layout(rng)
    for _ in range(25):
        sta = rng.uniform(al.start_station, al.end_station)
        off = rng.uniform(-r / 5, r / 5)
        x, y, _ = al.point_at(sta, off)
        sta2, off2 = al.station_offset_of((x, y))
        assert sta2 == pytest.approx(sta, abs=1e-4)
        assert off2 == pytest.approx(off, abs=1e-4)


def test_spiral_validation():
    with pytest.raises(ValueError):
        Spiral(100.0)                         # both radii infinite
    with pytest.raises(ValueError):
        Spiral(0.0, math.inf, 500.0)
    with pytest.raises(ValueError):
        Spiral(100.0, -5.0, 500.0)
    with pytest.raises(ValueError):
        Spiral(100.0, math.inf, 500.0, "X")


@pytest.mark.parametrize("seed", SEEDS)
def test_station_equations_round_trip(seed):
    rng = random.Random(seed)
    start = rng.uniform(0, 5000)
    length = 3000.0
    b1 = start + rng.uniform(200, 900)
    a1 = b1 + rng.choice([-300.0, 250.0])        # overlapping or gapped stationing
    b2 = a1 + rng.uniform(300, 900)
    a2 = b2 + rng.uniform(-200, 200)
    al = Alignment((0, 0), 90.0, [Tangent(length)], start_station_ft=start,
                   station_equations=[(b1, a1), (b2, a2)])
    for _ in range(50):
        cont = rng.uniform(al.start_station, al.end_station)
        disp, region = al.display_station(cont)
        assert al.continuous_station(disp, region) == pytest.approx(cont, abs=1e-9)
    # at the first equation point the ahead region wins
    c_eq = start + (b1 - start)
    assert al.display_station(c_eq) == (pytest.approx(a1), 1)


def test_ambiguous_displayed_station_needs_a_region():
    al = Alignment((0, 0), 0.0, [Tangent(1000.0)], station_equations=[(600.0, 400.0)])
    with pytest.raises(ValueError, match="regions"):
        al.continuous_station(500.0)            # both before and after the equation
    assert al.continuous_station(500.0, region=0) == pytest.approx(500.0)
    assert al.continuous_station(500.0, region=1) == pytest.approx(700.0)
    with pytest.raises(ValueError, match="not on this alignment"):
        al.continuous_station(5000.0)
    with pytest.raises(ValueError):
        Alignment((0, 0), 0.0, [Tangent(1000.0)], station_equations=[(-10.0, 0.0)])


def test_cross_slope_interpolation_and_offset_elevation():
    al = Alignment((0, 0), 0.0, [Tangent(1000.0)],
                   superelevation=[(100.0, -2.0, -2.0), (300.0, 4.0, -4.0)])
    assert al.cross_slope_at(0.0) == (-2.0, -2.0)
    assert al.cross_slope_at(200.0) == pytest.approx((1.0, -3.0))
    assert al.cross_slope_at(900.0) == (4.0, -4.0)
    assert al.point_at(200.0, 10.0)[2] == 0.0                       # off by default
    assert al.point_at(200.0, 10.0, apply_cross_slope=True)[2] == pytest.approx(-0.3)
    assert al.point_at(200.0, -10.0, apply_cross_slope=True)[2] == pytest.approx(0.1)
    assert Alignment((0, 0), 0.0, [Tangent(10.0)]).cross_slope_at(5.0) == (0.0, 0.0)
