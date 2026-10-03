#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""LandXML alignments: write -> read round trips and reader edge cases."""

import io
import math
import random

import pytest

from civilpy.transportation.alignment import Alignment, Curve, Spiral, Tangent, VerticalProfile
from civilpy.transportation.landxml import read_alignments, write_alignments

US_FT_M = 1200.0 / 3937.0


def _random_alignment(rng):
    r = rng.uniform(400.0, 5000.0)
    d = rng.choice("RL")
    elements = [Tangent(rng.uniform(50, 500)),
                Spiral(rng.uniform(80, 300), math.inf, r, d),
                Curve(r, rng.uniform(5.0, 40.0), d),
                Spiral(rng.uniform(80, 300), r, math.inf, d),
                Tangent(rng.uniform(50, 500)),
                Curve(rng.uniform(800, 4000), rng.uniform(2, 15), rng.choice("RL"))]
    start = rng.uniform(0, 5e4)
    probe = Alignment((0, 0), 0, elements, start_station_ft=start)
    length = probe.length_ft
    b1 = start + length * rng.uniform(0.2, 0.4)
    eq = [(b1, b1 + rng.choice([-150.0, 220.0]))]
    s0, s1 = start, start + length
    mid = (s0 + s1) / 2
    profile = VerticalProfile([(s0, 800.0, 0.0), (mid, 800.0 + rng.uniform(-20, 20), rng.uniform(100, 400)),
                               (s1, 800.0 + rng.uniform(-30, 30), 0.0)])
    return Alignment((rng.uniform(1e5, 9e5), rng.uniform(1e5, 9e5)), rng.uniform(0, 360), elements,
                     profile=profile, start_station_ft=start, station_equations=eq)


def _round_trip(als, units):
    buf = io.StringIO()
    write_alignments(als, buf, units=units)
    return read_alignments(io.StringIO(buf.getvalue()))


@pytest.mark.parametrize("units", ["USSurveyFoot", "meter"])
@pytest.mark.parametrize("seed", range(10))
def test_write_read_round_trip(seed, units):
    rng = random.Random(seed)
    als = {f"CL-{i}": _random_alignment(rng) for i in range(2)}
    back = _round_trip(als, units)
    assert set(back) == set(als)
    tol = 1e-4 if units == "meter" else 1e-5          # 6-decimal text in meters
    for name, al in als.items():
        b = back[name]
        assert b.start_station == pytest.approx(al.start_station, abs=tol)
        assert b.length_ft == pytest.approx(al.length_ft, abs=tol)
        assert [type(e) for e in b.elements] == [type(e) for e in al.elements]
        for _ in range(30):
            sta = rng.uniform(al.start_station, al.end_station)
            p, q = al.point_at(sta, 12.0), b.point_at(sta, 12.0)
            assert math.hypot(p[0] - q[0], p[1] - q[1]) < 10 * tol
            assert q[2] == pytest.approx(p[2], abs=10 * tol)
        assert len(b.station_equations) == len(al.station_equations)
        for (b0, a0), (b1, a1) in zip(al.station_equations, b.station_equations):
            assert (b1, a1) == (pytest.approx(b0, abs=tol), pytest.approx(a0, abs=tol))


METRIC = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units><Metric linearUnit="meter"/></Units>
  <Alignments>
    <Alignment name="A" staStart="100" length="0">
      <CoordGeom>
        <Line><Start>1000 2000</Start><End>1100 2000</End></Line>
        <Curve rot="ccw" radius="200">
          <Start>1100 2000</Start><Center>1100 1800</Center><End>1300 1800</End>
        </Curve>
      </CoordGeom>
    </Alignment>
  </Alignments>
</LandXML>"""


def test_metric_file_converts_to_feet_and_derives_curve_from_end_point():
    al = read_alignments(io.StringIO(METRIC))["A"]
    ft = 1.0 / US_FT_M
    assert al.start_station == pytest.approx(100 * ft)
    assert al.start_point == pytest.approx((2000 * ft, 1000 * ft))
    assert al.start_bearing == pytest.approx(0.0)            # due north
    assert isinstance(al.elements[1], Curve)
    assert al.elements[1].direction == "L"
    assert al.elements[1].delta_deg == pytest.approx(90.0)
    x, y, _ = al.point_at(al.end_station)
    assert (x, y) == (pytest.approx(1800 * ft, abs=1e-6), pytest.approx(1300 * ft, abs=1e-6))


@pytest.mark.parametrize("snippet, match", [
    ('<Spiral rot="cw" spiType="bloss" length="100" radiusStart="INF" radiusEnd="500">'
     '<Start>0 0</Start><End>100 0</End></Spiral>', "spiType"),
    ('<Curve rot="up" radius="100"><Start>0 0</Start><Center>0 100</Center><End>1 1</End></Curve>', "rot"),
    ('<Chain>1 2</Chain>', "unsupported"),
])
def test_unsupported_geometry_is_rejected(snippet, match):
    xml = METRIC.replace('<Line><Start>1000 2000</Start><End>1100 2000</End></Line>', snippet)
    with pytest.raises(ValueError, match=match):
        read_alignments(io.StringIO(xml))


def test_unsymmetric_vertical_curve_is_read():
    xml = METRIC.replace("</CoordGeom>", "</CoordGeom><Profile><ProfAlign>"
                         "<PVI>100 10</PVI><UnsymParaCurve lengthIn='10' lengthOut='20'>150 12</UnsymParaCurve>"
                         "<PVI>300 11</PVI></ProfAlign></Profile>")
    al = next(iter(read_alignments(io.StringIO(xml)).values()))
    f = 3937.0 / 1200.0                                 # METRIC is in meters; profiles come out in US survey ft
    assert al.profile.pvi_lengths[1] == pytest.approx((10 * f, 20 * f))
    assert al.profile.pvis[1][2] == pytest.approx(30 * f)


def test_write_rejects_unknown_units():
    with pytest.raises(ValueError):
        write_alignments({}, io.StringIO(), units="furlong")


def test_unsymmetrical_parabola_round_trips_through_landxml(tmp_path):
    import io

    from civilpy.transportation.alignment import Alignment, Tangent, VerticalProfile
    from civilpy.transportation.landxml import read_alignments, write_alignments

    prof = VerticalProfile([(0.0, 600.0, 0.0), (800.0, 624.0, 200.0, 350.0), (1600.0, 610.0, 300.0), (2400.0, 612.0, 0.0)])
    al = Alignment((1000.0, 2000.0), 45.0, [Tangent(2400.0)], profile=prof)
    buf = io.StringIO()
    write_alignments({"U": al}, buf)
    xml = buf.getvalue()
    assert "UnsymParaCurve" in xml and 'lengthIn="200' in xml and 'lengthOut="350' in xml
    back = read_alignments(io.StringIO(xml))["U"]
    assert back.profile.pvi_lengths[1] == (200.0, 350.0) and back.profile.pvis[1][2] == 550.0
    for s in range(0, 2401, 50):
        assert abs(back.profile.elevation_at(s) - prof.elevation_at(s)) < 1e-6
