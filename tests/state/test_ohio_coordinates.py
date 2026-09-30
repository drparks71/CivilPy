#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""OCCS + State Plane: every published test point, and round trips."""

import random

import pytest

from civilpy.state.ohio import coordinates as oc

COUNTIES = sorted(oc.ZONES)


def test_all_88_counties_have_a_zone_and_a_test_point():
    assert len(oc.ZONES) == 88 and set(oc.ZONES) == set(oc.TEST_POINTS)
    assert sorted(z.number for z in oc.ZONES.values()) == list(range(1, 89))


@pytest.mark.parametrize("abbr", COUNTIES)
def test_zone_reproduces_its_published_test_point(abbr):
    tp = oc.TEST_POINTS[abbr]
    n, e = oc.to_grid(tp.lat, tp.lon, abbr, unit="m")
    tol = oc.TEST_POINT_TOLERANCE_M.get(abbr, 0.001)
    assert abs(n - tp.northing_m) <= tol and abs(e - tp.easting_m) <= tol


@pytest.mark.parametrize("abbr", COUNTIES)
def test_combined_scale_matches_published_ppm(abbr):
    if abbr in oc.TEST_POINT_PPM_UNRESOLVED:
        pytest.skip("published PPM disagrees with height/scale (module docstring)")
    tp = oc.TEST_POINTS[abbr]
    ppm = (oc.combined_scale_factor(tp.lat, tp.lon, tp.height_m, abbr) - 1.0) * 1e6
    assert abs(ppm - tp.ppm) < 0.6


@pytest.mark.parametrize("abbr", COUNTIES)
def test_zone_lookup_by_abbr_name_number_and_code(abbr):
    z = oc.ZONES[abbr]
    assert oc.zone(abbr) is z
    assert oc.zone(z.name.upper()) is z
    assert oc.zone(z.number) is z
    n1 = oc.to_grid(39.9, -82.9, z.code)
    assert n1 == oc.to_grid(39.9, -82.9, abbr)


def test_zone_lookup_rejects_unknown():
    with pytest.raises(KeyError):
        oc.zone("XYZ")


SYSTEMS = COUNTIES + sorted(oc.STATE_PLANE_EPSG)


@pytest.mark.parametrize("system", SYSTEMS)
def test_geodetic_grid_round_trip_in_both_units(system):
    rng = random.Random(hash(system) & 0xFFFF)
    anchor = oc.TEST_POINTS[system] if system in oc.TEST_POINTS else None
    for _ in range(20):
        lat = (anchor.lat if anchor else 40.0) + rng.uniform(-0.2, 0.2)
        lon = (anchor.lon if anchor else -82.5) + rng.uniform(-0.2, 0.2)
        n_ft, e_ft = oc.to_grid(lat, lon, system)
        n_m, e_m = oc.to_grid(lat, lon, system, unit="m")
        assert n_ft * oc.US_FT == pytest.approx(n_m, abs=1e-6)
        assert e_ft * oc.US_FT == pytest.approx(e_m, abs=1e-6)
        lat2, lon2 = oc.to_geodetic(n_ft, e_ft, system)
        assert lat2 == pytest.approx(lat, abs=1e-9) and lon2 == pytest.approx(lon, abs=1e-9)


@pytest.mark.parametrize("abbr", COUNTIES)
def test_low_distortion_near_the_test_point(abbr):
    # OCCS zones are designed to keep grid-to-ground distortion small
    # (L&D Vol 4 Section 2101: "often less than 1 part in 50,000" = 20 ppm).
    tp = oc.TEST_POINTS[abbr]
    k = oc.combined_scale_factor(tp.lat, tp.lon, tp.height_m, abbr)
    assert abs(k - 1.0) < 30e-6


def test_state_plane_north_and_south_agree_with_epsg_units():
    # same point, 2011 vs original NAD 83 realization: no datum shift applied,
    # so the grids agree to the difference in the EPSG definitions (none).
    assert oc.to_grid(41.0, -82.0, "OH83-NF") == pytest.approx(oc.to_grid(41.0, -82.0, "OH83-2011-NF"), abs=1e-3)
    assert oc.to_grid(39.5, -82.0, "OH83-SF") == pytest.approx(oc.to_grid(39.5, -82.0, "OH83-2011-SF"), abs=1e-3)
