#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""FEMA NFHL at a crossing: parsing the map-service answers, the 1% water
surface estimate, and the NFIP rule each mapped condition points at.
Synthetic inputs only - no network."""

import pytest

from civilpy.water_resources import nfhl as nf


def zones(*specs):
    return {"features": [{"attributes": {"FLD_ZONE": z, "ZONE_SUBTY": s, "SFHA_TF": t, "STATIC_BFE": b,
                                         "DFIRM_ID": "39131C"}} for z, s, t, b in specs]}


def line(x0, elev, field="ELEV", **extra):
    return {"attributes": {field: elev, "V_DATUM": "NAVD88", "LEN_UNIT": "Feet", **extra},
            "geometry": {"paths": [[[x0, 39.0], [x0, 39.01]]]}}


def hazard(at=None, nearby=(), xs=(), bfes=(), lomrs=(), panels=("39131C0095C",)):
    h = nf.FloodHazard(39.005, -83.0, 250.0)
    h.zone_at_point = at
    h.zones_nearby = list(nearby)
    h.cross_sections = list(xs)
    h.bfes = list(bfes)
    h.lomrs = list(lomrs)
    h.panels = [nf.Panel(p) for p in panels]
    return h


def test_parse_zones_reads_floodway_sfha_and_static_bfe():
    z = nf.parse_zones(zones(("AE", "FLOODWAY", "T", -9999.0), ("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD", "F", None),
                             ("AE", "", "T", 712.4)))
    assert z[0].floodway and z[0].sfha and z[0].static_bfe_ft is None
    assert z[1].shaded_x and not z[1].sfha and not z[1].floodway
    assert z[2].static_bfe_ft == 712.4 and not z[2].floodway


def test_parse_elevations_sorts_by_distance_and_converts_metres():
    lon0 = -83.0
    resp = {"features": [line(lon0 + 0.002, 581.0), line(lon0 + 0.0001, 580.0),
                         line(lon0 - 0.001, 177.0, LEN_UNIT="Meters")]}
    got = nf.parse_elevations(resp, 39.005, lon0, "bfe")
    assert [round(e.elev_ft, 1) for e in got] == [580.0, round(177.0 / 0.3048, 1), 581.0]
    assert got[0].distance_ft == pytest.approx(0.0001 * 364000 * 0.777, rel=0.02)


def test_cross_sections_skip_missing_wsel():
    resp = {"features": [line(-83.0, -9999.0, "WSEL_REG"), line(-83.001, 600.5, "WSEL_REG", XS_LTR="AB", WTR_NM="Scioto")]}
    got = nf.parse_elevations(resp, 39.005, -83.0, "cross_section")
    assert len(got) == 1 and got[0].letter == "AB" and got[0].stream == "Scioto"


def test_panels_and_lomrs_are_distinct_with_iso_dates():
    p = nf.parse_panels({"features": [{"attributes": {"FIRM_PAN": "39131C0095C", "EFF_DATE": 1288828800000}}] * 2})
    assert [(x.panel, x.effective) for x in p] == [("39131C0095C", "2010-11-04")]
    lo = nf.parse_lomrs({"features": [{"attributes": {"CASE_NO": "19-05-1234P", "EFF_DATE": 1560000000000}}]})
    assert lo[0].case == "19-05-1234P" and lo[0].effective.startswith("2019-06")


def test_service_error_raises():
    with pytest.raises(nf.NFHLError):
        nf.parse_zones({"error": {"code": 500}})


# ── water surface estimate ────────────────────────────────────────────────

def el(v, d, kind="cross_section"):
    return nf.Elevation(elev_ft=v, distance_ft=d, kind=kind)


def test_wsel_interpolates_the_two_nearest_cross_sections_by_distance():
    h = hazard(xs=[el(580.0, 100.0), el(584.0, 300.0), el(590.0, 900.0)])
    assert h.wsel_1pct_ft == pytest.approx(581.0)


@pytest.mark.parametrize("seed", range(10))
def test_wsel_stays_between_the_two_it_uses(seed):
    import random
    rnd = random.Random(seed)
    a, b = rnd.uniform(500, 900), rnd.uniform(500, 900)
    h = hazard(xs=sorted([el(a, rnd.uniform(1, 500)), el(b, rnd.uniform(1, 500))], key=lambda e: e.distance_ft))
    assert min(a, b) - 1e-9 <= h.wsel_1pct_ft <= max(a, b) + 1e-9


def test_wsel_falls_back_to_bfes_then_static_bfe():
    assert hazard(bfes=[el(628.0, 50.0, "bfe")]).wsel_1pct_ft == 628.0
    assert hazard(at=nf.Zone("AE", sfha=True, static_bfe_ft=702.0)).wsel_1pct_ft == 702.0
    assert hazard(at=nf.Zone("A", sfha=True)).wsel_1pct_ft is None


# ── the rule ──────────────────────────────────────────────────────────────

def test_floodway_anywhere_near_the_crossing_means_no_rise():
    h = hazard(at=nf.Zone("AE", sfha=True), nearby=[nf.Zone("AE", "FLOODWAY", True)])
    r = nf.regulatory(h)
    assert r["key"] == "floodway" and r["cite"] == "44 CFR 60.3(d)(3)" and "no increase" in r["requirement"]


def test_detailed_zone_without_floodway_is_the_one_foot_rule():
    r = nf.regulatory(hazard(at=nf.Zone("X", "AREA OF MINIMAL FLOOD HAZARD"), nearby=[nf.Zone("AE", "", True)]))
    assert r["key"] == "ae_no_floodway" and r["cite"] == "44 CFR 60.3(c)(10)" and "1.0 ft" in r["requirement"]


def test_a_bfe_line_on_another_stream_does_not_make_zone_a_detailed():
    r = nf.regulatory(hazard(at=nf.Zone("A", "", True), bfes=[el(628.0, 966.0, "bfe")]))
    assert r["key"] == "approximate_a" and r["cite"] == "44 CFR 60.3(b)(4)"


@pytest.mark.parametrize("zone, key", [(nf.Zone("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD"), "shaded_x"),
                                       (nf.Zone("X", "AREA OF MINIMAL FLOOD HAZARD"), "outside")])
def test_outside_the_sfha(zone, key):
    assert nf.regulatory(hazard(at=zone))["key"] == key


def test_unmapped_and_notes():
    assert nf.regulatory(hazard(panels=()))["key"] == "unmapped"
    r = nf.regulatory(hazard(at=nf.Zone("AE", "FLOODWAY", True), lomrs=[nf.LOMR("19-05-1234P")],
                             xs=[nf.Elevation(600.0, 10.0, datum="NGVD29")]))
    assert any("LOMR" in n for n in r["notes"]) and any("NGVD29" in n for n in r["notes"])


class FakeSession:
    def __init__(self, payloads):
        self.payloads, self.calls = payloads, []

    def request(self, method, url, params=None, **kw):
        self.calls.append((url, dict(params)))
        layer = int(url.rsplit("/", 2)[-2])
        payload = self.payloads.get(layer, {"features": []})

        class R:
            def raise_for_status(self): pass
            def json(self): return payload
        return R()


def test_flood_hazard_queries_each_layer_and_never_sends_distance_zero():
    s = FakeSession({28: zones(("AE", "FLOODWAY", "T", None)), 16: {"features": [line(-82.9001, 581.0)]},
                     3: {"features": [{"attributes": {"FIRM_PAN": "39131C0095C", "EFF_DATE": 0}}]}})
    h = nf.flood_hazard(39.005, -82.9, radius_ft=250, session=s)
    assert h.in_floodway and h.zone == "AE" and h.bfes[0].elev_ft == 581.0 and h.panels[0].panel == "39131C0095C"
    point_calls = [p for u, p in s.calls if "distance" not in p]
    assert point_calls and all(p.get("distance", 1) != 0 for _, p in s.calls)
    assert {int(u.rsplit("/", 2)[-2]) for u, _ in s.calls} == {28, 16, 14, 3, 1}
