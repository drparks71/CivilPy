"""Tests for the composed Alignment placement object."""

import math

import pytest

from civilpy.transportation.alignment import (
    Alignment, Curve, Tangent, VerticalProfile,
)


def _tangent_north():
    return Alignment(start_point=(0.0, 0.0), start_bearing_deg=0.0,
                     start_station_ft=1000.0, elements=[Tangent(500.0)])


def test_tangent_length_and_end_station():
    al = _tangent_north()
    assert al.length_ft == pytest.approx(500.0)
    assert al.end_station == pytest.approx(1500.0)


def test_tangent_centerline_point():
    al = _tangent_north()
    x, y, z = al.point_at(1200.0, 0.0)
    assert (x, y, z) == pytest.approx((0.0, 200.0, 0.0))


def test_positive_offset_is_right_of_travel():
    # heading north, right is +x (East)
    al = _tangent_north()
    x, y, _ = al.point_at(1200.0, 30.0)
    assert x == pytest.approx(30.0)
    assert y == pytest.approx(200.0)
    # negative offset is to the left (-x)
    xl, _, _ = al.point_at(1200.0, -30.0)
    assert xl == pytest.approx(-30.0)


def test_bearing_on_tangent():
    al = _tangent_north()
    assert al.bearing_at(1250.0) == pytest.approx(0.0)


def _quarter_right():
    # north, then a 100-ft-radius 90-deg right curve
    return Alignment(start_point=(0.0, 0.0), start_bearing_deg=0.0,
                     elements=[Tangent(0.0),
                               Curve(radius_ft=100.0, delta_deg=90.0,
                                     direction="R")])


def test_curve_endpoint_and_bearing():
    al = _quarter_right()
    assert al.length_ft == pytest.approx(100.0 * math.pi / 2.0)
    end = al.end_station
    x, y, _ = al.point_at(end, 0.0)
    assert (x, y) == pytest.approx((100.0, 100.0))     # quarter circle
    assert al.bearing_at(end) == pytest.approx(90.0)   # now heading East


def test_curve_midpoint_on_radius():
    al = _quarter_right()
    mid = al.length_ft / 2.0
    x, y, _ = al.point_at(mid, 0.0)
    # every centerline point is radius 100 from the center (100, 0)
    assert math.hypot(x - 100.0, y - 0.0) == pytest.approx(100.0)
    assert al.bearing_at(mid) == pytest.approx(45.0)


def test_left_curve_turns_the_other_way():
    al = Alignment(start_point=(0.0, 0.0), start_bearing_deg=0.0,
                   elements=[Curve(radius_ft=100.0, delta_deg=90.0,
                                   direction="L")])
    x, y, _ = al.point_at(al.end_station, 0.0)
    assert (x, y) == pytest.approx((-100.0, 100.0))    # curves West
    assert al.bearing_at(al.end_station) == pytest.approx(270.0)


def test_vertical_profile_straight_grade():
    prof = VerticalProfile([(0.0, 100.0, 0.0), (1000.0, 120.0, 0.0)])
    assert prof.elevation_at(500.0) == pytest.approx(110.0)      # 2% grade


def test_vertical_profile_crest_curve():
    prof = VerticalProfile([(0.0, 100.0, 0.0),
                            (500.0, 110.0, 200.0),
                            (1000.0, 100.0, 0.0)])
    # crest of a +2/-2 equal-tangent curve sits 1.0 ft below the PVI
    assert prof.elevation_at(500.0) == pytest.approx(109.0)
    assert prof.elevation_at(100.0) == pytest.approx(102.0)      # on grade


def test_point_at_uses_profile_elevation():
    prof = VerticalProfile([(1000.0, 500.0, 0.0), (1500.0, 505.0, 0.0)])
    al = Alignment(start_point=(0.0, 0.0), start_bearing_deg=0.0,
                   start_station_ft=1000.0, elements=[Tangent(500.0)],
                   profile=prof)
    _, _, z = al.point_at(1250.0, 40.0)
    assert z == pytest.approx(502.5)


@pytest.mark.parametrize("station,offset", [
    (1000.0, 0.0), (1120.0, 25.0), (1200.0, -18.0),
])
def test_inverse_roundtrip_tangent_and_curve(station, offset):
    prof = VerticalProfile([(1000.0, 100.0, 0.0), (2000.0, 100.0, 0.0)])
    al = Alignment(start_point=(10.0, 5.0), start_bearing_deg=35.0,
                   start_station_ft=1000.0, profile=prof,
                   elements=[Tangent(150.0),
                             Curve(radius_ft=300.0, delta_deg=40.0,
                                   direction="R"),
                             Tangent(150.0)])
    x, y, _ = al.point_at(station, offset)
    got_sta, got_off = al.station_offset_of((x, y))
    assert got_sta == pytest.approx(station, abs=1e-4)
    assert got_off == pytest.approx(offset, abs=1e-4)


def test_curve_validation():
    with pytest.raises(ValueError):
        Curve(radius_ft=-1.0, delta_deg=10.0)
    with pytest.raises(ValueError):
        Curve(radius_ft=100.0, delta_deg=10.0, direction="X")


def test_profile_requires_increasing_stations():
    with pytest.raises(ValueError):
        VerticalProfile([(100.0, 10.0, 0.0), (100.0, 12.0, 0.0)])


def test_vertical_profile_takes_unsymmetrical_pvis():
    """(station, elevation, len_in, len_out) builds an unsymmetrical curve; the
    stored pvis stay 3-tuples (total length) with the halves in pvi_lengths."""
    import pytest
    from civilpy.transportation.alignment import VerticalProfile
    from civilpy.transportation.curves import UnsymmetricalVerticalCurve

    prof = VerticalProfile([(0.0, 100.0, 0.0), (1000.0, 120.0, 300.0, 500.0), (2000.0, 110.0, 400.0), (3000.0, 110.0, 0.0)])
    assert prof.pvis[1] == (1000.0, 120.0, 800.0) and prof.pvi_lengths[1] == (300.0, 500.0)
    assert prof.pvi_lengths[2] == (200.0, 200.0)
    vc = prof._curves[0][2]
    assert isinstance(vc, UnsymmetricalVerticalCurve)
    assert abs(prof.elevation_at(700.0) - (100.0 + 0.02 * 700.0)) < 1e-9          # BVC on the tangent
    assert abs(prof.elevation_at(1500.0) - (120.0 - 0.01 * 500.0)) < 1e-9         # EVC on the tangent
    assert abs(prof.elevation_at(1000.0) - vc.elevation_at(1000.0)) < 1e-12
    with pytest.raises(ValueError):
        VerticalProfile([(0.0, 0.0, 0.0), (500.0, 5.0, 100.0, 0.0), (1000.0, 0.0, 0.0)])
