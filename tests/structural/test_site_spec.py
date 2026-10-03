#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Site schema records: round trips through Alignment and JSON, validation."""

import json
import math
import random

import pytest

from civilpy.state.ohio import coordinates as oc
from civilpy.structural.bim_spec import SOURCES, Provenance
from civilpy.structural.site_spec import (
    AlignmentRecord,
    BridgeSiteRecord,
    CoordinateSystemRecord,
    HorizontalElementRecord,
    PVIRecord,
    ProfileRecord,
    TerrainRecord,
)
from civilpy.transportation.alignment import Alignment, Curve, Spiral, Tangent, VerticalProfile


def _alignment(rng):
    r = rng.uniform(400.0, 5000.0)
    d = rng.choice("RL")
    elements = [Tangent(rng.uniform(50, 500)), Spiral(rng.uniform(80, 300), math.inf, r, d),
                Curve(r, rng.uniform(5.0, 40.0), d), Spiral(rng.uniform(80, 300), r, math.inf, d),
                Tangent(rng.uniform(50, 500))]
    start = rng.uniform(0, 5e4)
    length = sum(e.length for e in elements)
    return Alignment((rng.uniform(1e5, 9e5), rng.uniform(1e5, 9e5)), rng.uniform(0, 360), elements,
                     profile=VerticalProfile([(start, 900.0, 0.0), (start + length / 2, 905.0, 300.0),
                                              (start + length, 899.0, 0.0)]),
                     start_station_ft=start,
                     station_equations=[(start + 300.0, start + 150.0)],
                     superelevation=[(start, -2.0, -2.0), (start + 400.0, 6.0, -6.0)])


@pytest.mark.parametrize("seed", range(10))
def test_alignment_record_round_trips_through_json(seed):
    rng = random.Random(seed)
    al = _alignment(rng)
    code = rng.choice(sorted(oc.ZONES))
    rec = AlignmentRecord.from_alignment(
        al, "CL", role="existing",
        coordinate_system=CoordinateSystemRecord("OCCS", f"OCCS-{code}"),
        source_ref="test", provenance=Provenance("gis"))
    assert rec.validate() == []
    doc = json.loads(json.dumps(rec.to_dict()))
    back = AlignmentRecord.from_dict(doc)
    assert back == rec
    al2 = back.to_alignment()
    for _ in range(25):
        sta = rng.uniform(al.start_station, al.end_station)
        p, q = al.point_at(sta, -8.0, apply_cross_slope=True), al2.point_at(sta, -8.0, apply_cross_slope=True)
        assert math.dist(p, q) < 1e-9
    assert al2.display_station(al.end_station) == al.display_station(al.end_station)


@pytest.mark.parametrize("code", sorted(oc.ZONES) + sorted(oc.STATE_PLANE_EPSG))
def test_every_ohio_coordinate_code_validates(code):
    kind = "STATE_PLANE" if code in oc.STATE_PLANE_EPSG else "OCCS"
    assert CoordinateSystemRecord(kind, code).validate() == []


@pytest.mark.parametrize("rec, fragment", [
    (CoordinateSystemRecord("OCCS", None), "required"),
    (CoordinateSystemRecord("OCCS", "XYZ"), "not an OCCS zone"),
    (CoordinateSystemRecord("OCCS", "OH83-SF"), "does not match"),
    (CoordinateSystemRecord("STATE_PLANE", "HAM"), "does not match"),
    (CoordinateSystemRecord("LOCAL"), "combined_scale_factor"),
    (CoordinateSystemRecord("OCCS", "HAM", linear_unit="furlong"), "not in"),
    (HorizontalElementRecord("arc", 100.0, "R"), "radius_ft"),
    (HorizontalElementRecord("arc", 100.0, None, 500.0), "direction"),
    (HorizontalElementRecord("spiral", 100.0, "L"), "at least one"),
    (HorizontalElementRecord("line", -1.0), "must be > 0"),
    (ProfileRecord(pvis=(PVIRecord(10.0, 1.0),)), "at least two"),
    (ProfileRecord(pvis=(PVIRecord(10.0, 1.0), PVIRecord(5.0, 1.0))), "strictly increase"),
    (TerrainRecord("t", "ogrip_3dep_las", extent_ft=(1.0, 2.0, 3.0)), "extent_ft"),
    (TerrainRecord("t", "ogrip_3dep_las", extent_ft=(5.0, 2.0, 3.0, 4.0)), "min must be below"),
    (TerrainRecord("t", "google"), "not in"),
])
def test_validation_catches(rec, fragment):
    problems = rec.validate()
    assert any(fragment in p for p in problems), problems


def test_bridge_site_stations_must_lie_on_the_alignment():
    al = AlignmentRecord.from_alignment(Alignment((0, 0), 0.0, [Tangent(1000.0)], start_station_ft=100.0), "CL")
    ok = BridgeSiteRecord(al, 300.0, 500.0,
                          TerrainRecord("g", "ogrip_3dep_las", 2019, 3.0, (0.0, 0.0, 10.0, 10.0)),
                          Provenance("obm"))
    assert ok.validate() == []
    assert BridgeSiteRecord.from_dict(json.loads(json.dumps(ok.to_dict()))) == ok
    assert any("greater" in p for p in BridgeSiteRecord(al, 500.0, 300.0).validate())
    assert any("outside" in p for p in BridgeSiteRecord(al, 50.0, 300.0).validate())
    assert any("at least one element" in p for p in BridgeSiteRecord(
        AlignmentRecord("x", 0.0, 0.0, 0.0), 0.0, 1.0).validate())


def test_new_provenance_sources():
    for src in ("obm", "gis", "design_file"):
        assert src in SOURCES and Provenance(src).validate() == []


def test_pvi_record_keeps_unsymmetrical_halves():
    from civilpy.structural.site_spec import AlignmentRecord, PVIRecord
    from civilpy.transportation.alignment import Alignment, Tangent, VerticalProfile

    prof = VerticalProfile([(0.0, 10.0, 0.0), (500.0, 20.0, 100.0, 300.0), (1000.0, 15.0, 200.0), (1500.0, 15.0, 0.0)])
    al = Alignment((0.0, 0.0), 0.0, [Tangent(1500.0)], profile=prof)
    rec = AlignmentRecord.from_alignment(al, "U")
    p1, p2 = rec.profile.pvis[1], rec.profile.pvis[2]
    assert (p1.curve_length_ft, p1.curve_length_in_ft, p1.curve_length_out_ft) == (400.0, 100.0, 300.0)
    assert (p2.curve_length_ft, p2.curve_length_in_ft, p2.curve_length_out_ft) == (200.0, 0.0, 0.0)
    assert PVIRecord(1.0, 2.0, 50.0).as_pvi() == (1.0, 2.0, 50.0)
    again = rec.to_alignment()
    for s in range(0, 1501, 25):
        assert abs(again.profile.elevation_at(s) - prof.elevation_at(s)) < 1e-9
