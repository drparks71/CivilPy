#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT IDF curves and the rational method (civilpy.state.ohio.DOT.idf)."""

import pytest

from civilpy.state.ohio.DOT import idf


def test_figure_example_zone_b_10pct_25min():
    # LD2 Appendix A worked example: Area B, 10 % AEP storm, 25 min tc -> i = 3.4 in/hr
    # the example reads the value off the plotted curve; the fitted equation gives 3.24
    assert idf.intensity(25.0, 10, "B") == pytest.approx(3.4, abs=0.2)


@pytest.mark.parametrize("zone", idf.ZONES)
@pytest.mark.parametrize("aep", idf.AEPS)
def test_curves_fall_with_duration_and_rise_with_rarity(zone, aep):
    ts = [5, 10, 15, 30, 60, 120, 180]
    vals = [idf.intensity(t, aep, zone) for t in ts]
    assert all(a > b for a, b in zip(vals, vals[1:]))
    assert 0.3 < vals[-1] < vals[0] < 12.0


@pytest.mark.parametrize("zone", idf.ZONES)
def test_rarer_storms_are_more_intense_at_an_hour(zone):
    vals = [idf.intensity(60, aep, zone) for aep in idf.AEPS]        # 50 % .. 1 %
    assert all(a < b for a, b in zip(vals, vals[1:]))


def test_zones_order_by_the_contoured_statistic_and_breaks_are_between():
    d = [idf.depth_in(60, 10, z) for z in idf.ZONES]
    assert d == sorted(d)                                     # A lightest .. D heaviest, as the figure says
    brks = idf.zone_depth_breaks()
    assert len(brks) == 3 and all(d[i] < brks[i] < d[i + 1] for i in range(3))
    for z in idf.ZONES:
        assert idf.zone_from_depth(idf.depth_in(60, 10, z)) == z
    assert idf.zone_from_depth(0.5) == "A" and idf.zone_from_depth(5.0) == "D"


def test_zone_from_atlas14_table():
    class PF:
        def depth(self, dur_h, ari_yr):
            assert (dur_h, ari_yr) == (1.0, 10.0)
            return idf.depth_in(60, 10, "C")
    assert idf.zone_from_atlas14(PF()) == "C"


def test_duration_clamped_and_bad_aep_rejected():
    assert idf.intensity(1.0, 10, "A") == idf.intensity(5.0, 10, "A")
    assert idf.intensity(500.0, 10, "A") == idf.intensity(180.0, 10, "A")
    with pytest.raises(ValueError):
        idf.intensity(30.0, 25, "A")


def test_time_of_concentration_pieces():
    to = idf.overland_flow_minutes(0.3, 300.0, 2.0)
    assert to == pytest.approx(1.8 * 0.8 * 300 ** 0.5 / 2 ** (1 / 3), rel=1e-6)
    v = idf.shallow_flow_velocity_fps("paved area", 4.0)
    assert v == pytest.approx(3.3 * 0.619 * 2.0, rel=1e-6)
    assert idf.travel_minutes(600.0, 5.0) == 2.0
    assert idf.time_of_concentration(overland_min=4, shallow_min=2, channel_min=1) == 7.0
    assert idf.time_of_concentration(overland_min=4, first_inlet="ditch") == 15.0
    assert idf.time_of_concentration(overland_min=4, first_inlet="pavement") == 10.0
    assert idf.time_of_concentration(overland_min=40, first_inlet="pavement") == 40.0


def test_rational_q_and_weighted_c():
    c = idf.weighted_c([(0.9, 1.0), (0.3, 3.0)])
    assert c == pytest.approx(0.45)
    assert idf.rational_q(0.9, 3.4, 2.5) == pytest.approx(7.65)
    with pytest.raises(ValueError):
        idf.rational_q(0.5, 3.0, 150.0)
