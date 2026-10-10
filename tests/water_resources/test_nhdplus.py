#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NHDPlus HR flowline check on StreamStats basins: SNBI waterway names
against GNIS names, the drainage bracket, nearest point on a flowline, and
the query parsing.  Synthetic inputs only - no network."""

import math
import random

import pytest

from civilpy.water_resources import nhdplus as nh


# ── names ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("snbi, gnis", [
    ("WEST BRANCH OF THE LITTLE HOCKING RIVER", "West Branch Little Hocking River"),
    ("W BR LITTLE HOCKING R", "West Branch Little Hocking River"),
    ("BLANCHARD RIVER #", "Blanchard River"),
    ("SUNDAY CK", "Sunday Creek"),
    ("MILLERS RN-BACK RN(STREA", "Millers Run"),
    ("TWO ROOT CREEK LUCKEY RD", "Two Root Creek"),
    ("Leslie Run Creek", "Leslie Run"),
    ("S. BRANCH KOKOSING RIVER", "South Branch Kokosing River"),
])
def test_names_that_match(snbi, gnis):
    assert nh.names_match(snbi, gnis)


@pytest.mark.parametrize("snbi, gnis", [
    ("WEST BRANCH OF THE LITTLE HOCKING RIVER", "Burnett Run"),
    ("WEST BRANCH OF THE LITTLE HOCKING RIVER", "Little Hocking River"),    # branch is not the main stem
    ("LITTLE HOCKING RIVER", "Hocking River"),
    ("TRIB OF SUNDAY CK", "Sunday Creek"),
    ("TRIBUTARY TO M&E CANAL", "Miami and Erie Canal"),
    ("T WALNUT CR(M-PORT RD NE", "Walnut Creek"),
    ("BRANCH OF TODDS FORK", "Todds Fork"),
    ("BRA OF RATTLESNAKE CREEK", "Rattlesnake Creek"),
    ("TRIB. S. BRANCH KOKOSING", "South Branch Kokosing River"),
    ("STREAM", "Sunday Creek"),
    ("", "Sunday Creek"),
    ("SUNDAY CREEK", ""),
])
def test_names_that_do_not_match(snbi, gnis):
    assert not nh.names_match(snbi, gnis)


@pytest.mark.parametrize("name", ["Sunday Creek", "Blanchard River", "Todds Fork", "Little Hocking River"])
@pytest.mark.parametrize("pattern", ["TRIB OF {}", "TRIBUTARY TO {}", "T {}", "BRANCH OF {}", "BRA OF {}"])
def test_a_tributary_never_matches_the_stream_it_feeds(name, pattern):
    assert nh.is_tributary_name(pattern.format(name.upper()))
    assert not nh.names_match(pattern.format(name.upper()), name)


@pytest.mark.parametrize("name", ["Sunday Creek", "Blanchard River", "Todds Fork", "Hocking River"])
@pytest.mark.parametrize("qualifier", sorted(nh.QUALIFIERS - {"branch", "fork"}))
def test_a_qualified_name_never_matches_the_plain_stream(name, qualifier):
    assert nh.names_match(name.upper(), name)
    assert not nh.names_match(f"{qualifier.upper()} {name.upper()}", name)


# ── drainage bracket ──────────────────────────────────────────────────────

def flowline(total=18.9, local=2.1, name="West Branch Little Hocking River", dist=7.0):
    return nh.Flowline(1, name, 4, total, local, dist, (39.34, -81.76))


def test_burnett_run_snap_disagrees_and_the_branch_agrees():
    fl = flowline()
    assert fl.da_range_sq_mi == pytest.approx((16.8, 18.9))
    assert nh.area_agrees(2.0, fl) is False
    assert nh.area_agrees(18.77, fl) is True
    assert nh.disagreement(2.0, fl) == pytest.approx(8.4)
    assert nh.disagreement(18.77, fl) == 1.0


def test_nothing_to_compare_is_none():
    assert nh.area_agrees(None, flowline()) is None
    assert nh.area_agrees(3.0, None) is None
    assert nh.area_agrees(3.0, flowline(total=None)) is None


@pytest.mark.parametrize("seed", range(20))
def test_agreement_is_the_bracket_widened_by_the_tolerance(seed):
    rnd = random.Random(seed)
    for _ in range(50):
        total = 10 ** rnd.uniform(-1, 3.7)
        fl = flowline(total=total, local=total * rnd.uniform(0, 0.9))
        low, high = fl.da_range_sq_mi
        area = 10 ** rnd.uniform(-2, 4)
        assert nh.area_agrees(area, fl) == (low / 2 <= area <= high * 2)
        assert nh.area_agrees(area, fl) == (nh.disagreement(area, fl) <= 2.0)


def test_matching_flowline_is_the_nearest_named_one():
    fls = [flowline(total=2.0, name="Burnett Run", dist=3.0),
           flowline(dist=40.0), flowline(total=17.0, dist=7.0), flowline(total=0.4, name="", dist=1.0)]
    got = nh.matching_flowline(fls, "WEST BRANCH OF THE LITTLE HOCKING RIVER")
    assert got.distance_m == 7.0 and got.total_da_sq_mi == 17.0
    assert nh.matching_flowline(fls, "TRIB OF BURNETT RUN") is None


# ── geometry and parsing ──────────────────────────────────────────────────

@pytest.mark.parametrize("seed", range(25))
def test_nearest_point_on_a_north_south_line(seed):
    rnd = random.Random(seed)
    lat, lon = rnd.uniform(38.5, 41.9), rnd.uniform(-84.8, -80.6)
    along_m, offset_m = rnd.uniform(-500, 500), rnd.uniform(1, 500)
    dlat = 1 / 111_195.0
    dlon = 1 / (111_195.0 * math.cos(math.radians(lat)))
    path = [[lon + offset_m * dlon, lat - 1000 * dlat], [lon + offset_m * dlon, lat + 1000 * dlat]]
    d, (nlat, nlon) = nh.nearest_on_paths(lat + along_m * dlat, lon, [path])
    assert d == pytest.approx(offset_m, rel=1e-3, abs=0.05)
    assert nlat == pytest.approx(lat + along_m * dlat, abs=1e-6)
    assert nlon == pytest.approx(lon + offset_m * dlon, abs=1e-7)


def hr_response():
    def feat(name, tot_km2, loc_km2, dx_deg):
        x = -81.762461 + dx_deg
        return {"attributes": {"NHDPlusID": 24000300039179, "GNIS_Name": name, "StreamOrde": 4,
                               "TotDASqKm": tot_km2, "DivDASqKm": tot_km2, "AreaSqKm": loc_km2},
                "geometry": {"paths": [[[x, 39.33], [x, 39.35]]]}}
    return {"features": [feat("Burnett Run", 5.1664, 1.0, 0.0003),
                         feat("West Branch Little Hocking River", 49.0319, 5.4, -0.0001),
                         feat(None, 0.3, 0.3, 0.001)]}


def test_parse_flowlines_sorts_nearest_first_and_converts_areas():
    fls = nh.parse_flowlines(hr_response(), 39.341011, -81.762461)
    assert [f.name for f in fls] == ["West Branch Little Hocking River", "Burnett Run", ""]
    wb = fls[0]
    assert wb.total_da_sq_mi == pytest.approx(18.931, abs=1e-3)
    assert wb.distance_m == pytest.approx(8.6, abs=0.2)
    assert wb.nearest[1] == pytest.approx(-81.762561, abs=1e-7)


def test_divergence_routed_drainage_wins_over_total():
    resp = {"features": [{"attributes": {"GNIS_Name": "Ottawa River", "TotDASqKm": 1980.0, "DivDASqKm": 370.6,
                                         "AreaSqKm": 14.0},
                          "geometry": {"paths": [[[-83.6084, 41.66], [-83.6084, 41.67]]]}}]}
    fl = nh.parse_flowlines(resp, 41.661469, -83.608389)[0]
    assert fl.total_da_sq_mi == pytest.approx(143.1, abs=0.1)
    assert nh.area_agrees(154.64, fl)


def test_total_drainage_is_the_fallback_without_divda():
    resp = {"features": [{"attributes": {"GNIS_Name": "X Creek", "TotDASqKm": 25.9, "AreaSqKm": 1.0},
                          "geometry": {"paths": [[[-83.0, 40.0], [-83.0, 40.01]]]}}]}
    assert nh.parse_flowlines(resp, 40.005, -83.0)[0].total_da_sq_mi == pytest.approx(10.0, abs=0.01)


def test_parse_flowlines_raises_on_a_service_error():
    with pytest.raises(nh.NHDPlusError):
        nh.parse_flowlines({"error": {"code": 400}}, 39.0, -82.0)


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw["params"]))
        payload = self.payload

        class R:
            status_code = 200
            def json(self): return payload
            def raise_for_status(self): pass
        return R()


def test_flowlines_near_queries_the_hr_network_layer():
    s = FakeSession(hr_response())
    fls = nh.flowlines_near(39.341011, -81.762461, radius_m=150, session=s)
    method, url, params = s.calls[0]
    assert url == nh.HR_FLOWLINES and params["distance"] == 150 and params["outSR"] == 4326
    assert len(fls) == 3
