#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``Alignment.between_points`` and the remaining edge paths of
``civilpy.transportation.alignment`` not reached by the property tests.

``between_points`` derives bearing, length and grade from two plan points:
a single tangent (bearing = azimuth p0->p1), or one circular arc of a given
radius whose deflection comes from the chord (``delta = 2 asin(c / 2R)``,
start bearing offset ``delta / 2`` from the chord).  Elevations come from the
endpoints or a ``terrain.elevation_at(x, y)`` sampler.  The rest covers
element validation, profile extrapolation past the PVIs, the kinked (zero
curve length) interior PVI, stations past the alignment ends, the
``frame_at`` sweep frame, single-region ``continuous_station`` and ``repr``.
"""

import math

import pytest

from civilpy.transportation.alignment import (
    Alignment,
    Curve,
    Spiral,
    Tangent,
    VerticalProfile,
)


class _Terrain:
    """A sloped plane: z = 50 + 0.01 x + 0.02 y."""

    def __init__(self):
        self.samples = []

    def elevation_at(self, x, y):
        self.samples.append((x, y))
        return 50.0 + 0.01 * x + 0.02 * y


# ── tangent between two points ─────────────────────────────────────────────

def test_tangent_between_points_bearing_length_and_endpoints():
    al = Alignment.between_points((0.0, 0.0), (100.0, 100.0), start_station_ft=500.0)
    chord = math.hypot(100.0, 100.0)
    assert len(al.elements) == 1 and isinstance(al.elements[0], Tangent)
    assert al.length_ft == pytest.approx(chord)
    assert al.start_station == 500.0
    assert al.end_station == pytest.approx(500.0 + chord)
    assert al.bearing_at(600.0) == pytest.approx(45.0)        # NE, cw from North
    x, y, z = al.point_at(al.end_station)
    assert (x, y) == pytest.approx((100.0, 100.0))
    assert z == 0.0 and al.profile is None                    # flat without elevations


@pytest.mark.parametrize("p1, az", [((0.0, 200.0), 0.0), ((300.0, 0.0), 90.0),
                                    ((0.0, -40.0), 180.0), ((-50.0, 0.0), 270.0),
                                    ((-10.0, 10.0), 315.0)])
def test_tangent_between_points_azimuth_convention(p1, az):
    al = Alignment.between_points((0.0, 0.0), p1)
    assert al.bearing_at(0.0) == pytest.approx(az)
    assert al.length_ft == pytest.approx(math.hypot(*p1))


def test_between_points_offset_from_origin_start():
    al = Alignment.between_points((1000.0, 2000.0), (1000.0, 2500.0))
    assert al.start_point == (1000.0, 2000.0)
    assert al.point_at(250.0)[:2] == pytest.approx((1000.0, 2250.0))
    sta, off = al.station_offset_of((1010.0, 2250.0))
    assert (sta, off) == pytest.approx((250.0, 10.0))         # right of a north tangent


def test_between_points_rejects_coincident_points():
    with pytest.raises(ValueError, match="distinct"):
        Alignment.between_points((5.0, 5.0), (5.0, 5.0))


# ── single arc between two points ──────────────────────────────────────────

def test_arc_between_points_right_turn_hits_the_far_point():
    # chord 100 ft due east, R = 100 -> delta = 2 asin(0.5) = 60 deg
    al = Alignment.between_points((0.0, 0.0), (100.0, 0.0), radius_ft=100.0, direction="R")
    el = al.elements[0]
    assert isinstance(el, Curve) and el.direction == "R"
    assert el.delta_deg == pytest.approx(60.0) and el.radius_ft == 100.0
    assert al.length_ft == pytest.approx(100.0 * math.pi / 3.0)
    assert al.bearing_at(0.0) == pytest.approx(60.0)          # chord az 90 - delta/2
    assert al.bearing_at(al.end_station) == pytest.approx(120.0)
    assert al.point_at(al.end_station)[:2] == pytest.approx((100.0, 0.0), abs=1e-9)
    # mid-arc bulges to the left of the chord (centre is to the right, below)
    xm, ym, _ = al.point_at(al.length_ft / 2.0)
    assert xm == pytest.approx(50.0) and ym == pytest.approx(100.0 - 100.0 * math.cos(math.radians(30.0)))
    assert ym > 0.0


def test_arc_between_points_left_turn_mirrors_the_right_turn():
    right = Alignment.between_points((0.0, 0.0), (100.0, 0.0), radius_ft=100.0, direction="R")
    left = Alignment.between_points((0.0, 0.0), (100.0, 0.0), radius_ft=100.0, direction="l")
    assert left.elements[0].direction == "L"
    assert left.bearing_at(0.0) == pytest.approx(120.0)
    assert left.bearing_at(left.end_station) == pytest.approx(60.0)
    assert left.point_at(left.end_station)[:2] == pytest.approx((100.0, 0.0), abs=1e-9)
    xr, yr, _ = right.point_at(right.length_ft / 2.0)
    xl, yl, _ = left.point_at(left.length_ft / 2.0)
    assert xl == pytest.approx(xr) and yl == pytest.approx(-yr)


def test_arc_between_points_semicircle_at_the_minimum_radius():
    al = Alignment.between_points((0.0, 0.0), (0.0, 200.0), radius_ft=100.0)
    assert al.elements[0].delta_deg == pytest.approx(180.0)
    assert al.length_ft == pytest.approx(100.0 * math.pi)
    assert al.point_at(al.end_station)[:2] == pytest.approx((0.0, 200.0), abs=1e-9)
    # right turn: start heading west (az -90), swing through north, end heading east
    assert al.bearing_at(0.0) == pytest.approx(270.0)
    assert al.bearing_at(al.end_station) == pytest.approx(90.0)
    assert al.point_at(al.length_ft / 2.0)[:2] == pytest.approx((-100.0, 100.0), abs=1e-9)


def test_arc_between_points_radius_too_small():
    with pytest.raises(ValueError, match="too small"):
        Alignment.between_points((0.0, 0.0), (0.0, 200.0), radius_ft=99.0)


# ── grade from elevations / terrain ────────────────────────────────────────

def test_between_points_straight_grade_from_endpoint_elevations():
    al = Alignment.between_points((0.0, 0.0), (0.0, 500.0), start_station_ft=100.0,
                                  start_elev_ft=100.0, end_elev_ft=110.0)
    assert isinstance(al.profile, VerticalProfile)
    assert al.profile.pvis == [(100.0, 100.0, 0.0), (600.0, 110.0, 0.0)]
    assert al.elevation_at(100.0) == 100.0
    assert al.elevation_at(600.0) == pytest.approx(110.0)
    assert al.elevation_at(350.0) == pytest.approx(105.0)
    assert al.profile._grades == [pytest.approx(2.0)]        # percent


def test_between_points_grade_is_over_the_arc_length_not_the_chord():
    al = Alignment.between_points((0.0, 0.0), (100.0, 0.0), radius_ft=100.0,
                                  start_elev_ft=0.0, end_elev_ft=10.0)
    assert al.profile.pvis[-1][0] == pytest.approx(100.0 * math.pi / 3.0)
    assert al.elevation_at(al.end_station) == pytest.approx(10.0)


def test_between_points_samples_terrain_at_both_ends():
    t = _Terrain()
    al = Alignment.between_points((100.0, 0.0), (100.0, 400.0), terrain=t)
    assert t.samples == [(100.0, 0.0), (100.0, 400.0)]
    assert al.elevation_at(0.0) == pytest.approx(51.0)
    assert al.elevation_at(400.0) == pytest.approx(59.0)
    assert al.elevation_at(200.0) == pytest.approx(55.0)


def test_between_points_explicit_elevation_overrides_terrain_for_that_end():
    t = _Terrain()
    al = Alignment.between_points((100.0, 0.0), (100.0, 400.0), terrain=t,
                                  start_elev_ft=80.0)
    assert t.samples == [(100.0, 400.0)]                     # only the end is sampled
    assert al.elevation_at(0.0) == 80.0
    assert al.elevation_at(400.0) == pytest.approx(59.0)


def test_between_points_one_elevation_without_terrain_stays_flat():
    al = Alignment.between_points((0.0, 0.0), (0.0, 100.0), start_elev_ft=10.0)
    assert al.profile is None and al.elevation_at(50.0) == 0.0


# ── remaining element / profile validation paths ───────────────────────────

def test_curve_validation_and_hcurve():
    with pytest.raises(ValueError, match="delta_deg"):
        Curve(radius_ft=500.0, delta_deg=0.0)
    with pytest.raises(ValueError, match="radius_ft"):
        Curve(radius_ft=0.0, delta_deg=30.0)
    hc = Curve(radius_ft=500.0, delta_deg=30.0).hcurve
    assert hc.radius == 500.0 and hc.delta == pytest.approx(math.radians(30.0))


def test_unknown_element_type_is_rejected():
    class Bump:                                   # quacks like an element, is none
        length = 10.0

    with pytest.raises(TypeError, match="unknown alignment element"):
        Alignment((0.0, 0.0), 0.0, [Tangent(10.0), Bump()])


def test_profile_needs_two_pvis():
    with pytest.raises(ValueError, match="at least two"):
        VerticalProfile([(0.0, 100.0, 0.0)])


def test_profile_kinked_interior_pvi_and_extrapolation_past_the_ends():
    # +2 % then -2 %, no vertical curve at the kink
    vp = VerticalProfile([(0.0, 100.0, 0.0), (500.0, 110.0, 0.0), (1000.0, 100.0, 0.0)])
    assert vp._curves == []
    assert vp.elevation_at(500.0) == pytest.approx(110.0)
    assert vp.elevation_at(250.0) == pytest.approx(105.0)
    assert vp.elevation_at(750.0) == pytest.approx(105.0)
    assert vp.elevation_at(-100.0) == pytest.approx(98.0)     # first grade carried back
    assert vp.elevation_at(1200.0) == pytest.approx(96.0)     # last grade carried on


def test_point_before_the_start_extrapolates_the_first_tangent():
    al = Alignment((0.0, 0.0), 0.0, [Tangent(100.0)], start_station_ft=1000.0)
    assert al.point_at(990.0)[:2] == pytest.approx((0.0, -10.0))
    assert al.point_at(1150.0)[:2] == pytest.approx((0.0, 150.0))


def test_point_before_a_leading_spiral_extrapolates_its_entry_tangent():
    al = Alignment((0.0, 0.0), 0.0, [Spiral(100.0, math.inf, 500.0)])
    x, y, _ = al.point_at(-10.0)
    assert (x, y) == pytest.approx((0.0, -10.0))
    assert al.bearing_at(-10.0) == pytest.approx(0.0)
    assert al.point_at(0.0)[:2] == pytest.approx((0.0, 0.0))


def test_frame_at_gives_point_tangent_and_right():
    al = Alignment((0.0, 0.0), 90.0, [Tangent(100.0)],
                   profile=VerticalProfile([(0.0, 10.0, 0.0), (100.0, 20.0, 0.0)]))
    fr = al.frame_at(50.0)
    assert fr["point"] == pytest.approx((50.0, 0.0, 15.0))
    assert fr["tangent"] == pytest.approx((1.0, 0.0))        # east
    assert fr["right"] == pytest.approx((0.0, -1.0))         # south is right of east
    assert fr["bearing_deg"] == pytest.approx(90.0)


def test_continuous_station_single_region_hit_needs_no_region():
    al = Alignment((0.0, 0.0), 0.0, [Tangent(1000.0)], station_equations=[(600.0, 800.0)])
    assert al.continuous_station(300.0) == 300.0             # region 0
    assert al.continuous_station(900.0) == pytest.approx(700.0)   # region 1: 600 + (900-800)
    with pytest.raises(ValueError, match="not on this alignment"):
        al.continuous_station(700.0)                          # the 600-800 gap


def test_repr_reports_start_station_length_and_element_count():
    al = Alignment((0.0, 0.0), 0.0, [Tangent(200.0), Curve(500.0, 30.0)], start_station_ft=1000.0)
    assert repr(al) == f"Alignment(start_sta=10+00.00, len={al.length_ft:.2f} ft, 2 elements)"
