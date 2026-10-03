#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Tests for vertical and horizontal roadway curves."""

import math

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from civilpy.transportation.curves import (
    VerticalCurve, HorizontalCurve, station_str)


def crest():
    return VerticalCurve(g1_pct=2.5, g2_pct=-1.5, length_ft=800.0,
                         pvi_station_ft=4200.0, pvi_elevation_ft=620.0)


def test_station_formatting():
    assert station_str(2560.0) == "25+60.00"
    assert station_str(98.75) == "0+98.75"


def test_vertical_curve_endpoints_and_k():
    vc = crest()
    assert vc.a_pct == pytest.approx(-4.0)
    assert vc.is_crest
    assert vc.k_value == pytest.approx(200.0)
    assert vc.bvc_station == pytest.approx(3800.0)
    assert vc.bvc_elevation == pytest.approx(620.0 - 0.025 * 400.0)
    assert vc.evc_elevation == pytest.approx(620.0 - 0.015 * 400.0)
    # curve meets the tangents at BVC/EVC
    assert vc.elevation_at(3800.0) == pytest.approx(vc.bvc_elevation)
    assert vc.elevation_at(4600.0) == pytest.approx(vc.evc_elevation)


def test_vertical_curve_high_point_at_zero_grade():
    vc = crest()
    sta, el = vc.high_low_point()
    x = sta - vc.bvc_station
    assert x == pytest.approx(2.5 * 800.0 / 4.0)       # x = g1*L/|A|
    assert vc.grade_at(sta) == pytest.approx(0.0, abs=1e-9)
    # highest elevation on the curve
    assert el >= max(vc.elevation_at(s)
                     for s in range(3800, 4601, 25)) - 1e-9


def test_sag_curve_low_point_and_external():
    sag = VerticalCurve(-3.0, 2.0, 500.0, 1000.0, 100.0)
    assert not sag.is_crest
    sta, el = sag.high_low_point()
    assert el < sag.elevation_at(sag.bvc_station)
    assert sag.external_distance() == pytest.approx(5.0 * 500.0 / 800.0)
    # grades that never change sign have no high/low point
    assert VerticalCurve(1.0, 3.0, 400.0).high_low_point() is None


def test_horizontal_curve_geometry():
    hc = HorizontalCurve(radius_ft=1000.0, delta_deg=30.0,
                         pi_station_ft=5000.0)
    assert hc.tangent_ft == pytest.approx(1000.0 * math.tan(math.radians(15)))
    assert hc.length_ft == pytest.approx(1000.0 * math.radians(30.0))
    assert hc.chord_ft == pytest.approx(2000.0 * math.sin(math.radians(15)))
    assert hc.external_ft == pytest.approx(
        1000.0 * (1.0 / math.cos(math.radians(15)) - 1.0))
    assert hc.middle_ordinate_ft < hc.external_ft
    assert hc.pc_station == pytest.approx(5000.0 - hc.tangent_ft)
    assert hc.pt_station == pytest.approx(hc.pc_station + hc.length_ft)
    assert hc.degree_of_curve_deg == pytest.approx(5.7296, rel=1e-4)


def test_superelevation_point_mass():
    # R = V^2 / (15 (e + f))
    r = HorizontalCurve.min_radius(60.0, e_max=0.06, f_max=0.12)
    assert r == pytest.approx(60.0**2 / (15.0 * 0.18))
    hc = HorizontalCurve(r, 20.0)
    assert hc.side_friction_demand(60.0, 0.06) == pytest.approx(0.12)


def test_curve_plots_return_figures():
    for fig in (crest().plot(),
                HorizontalCurve(800.0, 45.0, 2000.0).plot()):
        assert fig is not None
        plt.close(fig)


# ── unsymmetrical vertical curves ─────────────────────────────────────────

import pytest as _pt

from civilpy.transportation.curves import UnsymmetricalVerticalCurve as _UVC
from civilpy.transportation.curves import VerticalCurve as _VC


@_pt.mark.parametrize("g1, g2, l1, l2", [(3.0, -2.0, 300.0, 500.0), (-4.0, 1.5, 600.0, 200.0),
                                          (2.0, 5.0, 150.0, 450.0), (-1.0, -3.0, 400.0, 400.0)])
def test_unsymmetrical_curve_geometry(g1, g2, l1, l2):
    vc = _UVC(g1, g2, l1, l2, pvi_station_ft=1000.0, pvi_elevation_ft=500.0)
    # ends on the tangents, slopes continuous there
    assert vc.bvc_station == 1000.0 - l1 and vc.evc_station == 1000.0 + l2
    assert abs(vc.elevation_at(vc.bvc_station) - (500.0 - g1 / 100 * l1)) < 1e-9
    assert abs(vc.elevation_at(vc.evc_station) - (500.0 + g2 / 100 * l2)) < 1e-9
    assert abs(vc.grade_at(vc.bvc_station + 1e-9) - g1) < 1e-6 and abs(vc.grade_at(vc.evc_station - 1e-9) - g2) < 1e-6
    # the two parabolas meet at the PVI station with a common tangent
    left, right = vc.elevation_at(1000.0 - 1e-7), vc.elevation_at(1000.0 + 1e-7)
    assert abs(left - right) < 1e-6 and abs(vc.grade_at(1000.0 - 1e-7) - vc.grade_at(1000.0 + 1e-7)) < 1e-5
    # textbook external distance from the PVI: A L1 L2 / (2 (L1 + L2))
    a = (g2 - g1) / 100.0
    assert abs(vc.elevation_at(1000.0) - (500.0 + a * l1 * l2 / (2 * (l1 + l2)))) < 1e-9
    # grade is linear on each half and the second derivative has the sign of A
    xs = [vc.bvc_station + k * l1 / 10 for k in range(11)]
    gr = [vc.grade_at(x) for x in xs]
    d = [b - a_ for a_, b in zip(gr, gr[1:])]
    assert all(abs(x - d[0]) < 1e-9 for x in d) and (d[0] < 0) == (g2 < g1)


def test_unsymmetrical_with_equal_halves_is_the_equal_tangent_curve():
    u = _UVC(2.0, -3.0, 250.0, 250.0, 2000.0, 700.0)
    s = _VC(2.0, -3.0, 500.0, 2000.0, 700.0)
    for x in range(1700, 2301, 25):
        assert abs(u.elevation_at(x) - s.elevation_at(x)) < 1e-9
        assert abs(u.grade_at(x) - s.grade_at(x)) < 1e-9
    assert u.high_low_point() is not None and abs(u.high_low_point()[0] - s.high_low_point()[0]) < 1e-9


def test_unsymmetrical_high_point_on_either_half():
    crest_left = _UVC(1.0, -6.0, 400.0, 200.0, 1000.0, 100.0)       # turns over before the PVI
    crest_right = _UVC(6.0, -1.0, 200.0, 400.0, 1000.0, 100.0)      # turns over after the PVI
    for vc in (crest_left, crest_right):
        sta, z = vc.high_low_point()
        assert vc.bvc_station < sta < vc.evc_station and abs(vc.grade_at(sta)) < 1e-6
        assert z >= max(vc.elevation_at(sta - 5), vc.elevation_at(sta + 5))
    assert crest_left.high_low_point()[0] < 1000.0 < crest_right.high_low_point()[0]
    assert _UVC(2.0, 4.0, 100.0, 200.0).high_low_point() is None
    with _pt.raises(ValueError):
        _UVC(2.0, -2.0, 0.0, 100.0)
