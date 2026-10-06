#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""TIMS ArcGIS REST wrappers in ``apis``: the generic ``ArcGISLayer``
query builder (exact ``/query`` params, envelope/point buffers in degrees,
feature -> attribute flattening, failure -> empty list), the TIMS layer
URL table and district/county map, ``TIMSBridge`` attribute mapping and
derived flags (epoch-ms year built, SD / scour-critical rules, numeric
coercions), and the ``TIMSProject`` / ``TIMSRoad`` / ``TIMSWaterway``
search helpers' WHERE clauses and layer URLs."""

import json
import logging

import pytest
import requests

from civilpy.state.ohio.DOT import apis
from civilpy.state.ohio.DOT.apis import (
    ODOT_DISTRICT_COUNTIES, TIMS_BASE, TIMS_URLS, ArcGISLayer, TIMSBridge, TIMSProject,
    TIMSRoad, TIMSWaterway,
)
from tests.state.ohio.DOT.apis_fixtures import (
    TIMS_SFN, arcgis_features, epoch_ms, tims_record,
)

LAYER = "https://example.invalid/ags/rest/services/Assets/Thing/MapServer/0"
BRIDGE_Q = TIMS_URLS["bridge_inventory"] + "/query"


# --- ArcGISLayer ---------------------------------------------------------------------

def test_query_default_params_and_url(fake_get):
    fake_get.add("/query", arcgis_features(tims_record()))
    layer = ArcGISLayer(LAYER + "/")
    assert layer._url == LAYER
    assert layer._max_records == 1000
    layer.query()
    call = fake_get.last
    assert call.url == LAYER + "/query"
    assert call.timeout == 30
    assert call.params == {"where": "1=1", "outFields": "*", "returnGeometry": "true", "f": "json"}


def test_query_spatial_and_paging_params(fake_get):
    fake_get.add("/query", arcgis_features())
    geom = {"x": -82.9, "y": 40.1, "spatialReference": {"wkid": 4326}}
    ArcGISLayer(LAYER).query(
        where="DISTRICT='06'", out_fields="SFN,DISTRICT", geometry=geom,
        geometry_type="esriGeometryPoint", spatial_rel="esriSpatialRelWithin",
        return_geometry=False, result_record_count=50, order_by="SFN ASC",
    )
    assert fake_get.last.params == {
        "where": "DISTRICT='06'", "outFields": "SFN,DISTRICT", "returnGeometry": "false",
        "f": "json", "geometry": json.dumps(geom), "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelWithin", "inSR": "4326",
        "resultRecordCount": 50, "orderByFields": "SFN ASC",
    }


def test_query_flattens_attributes_and_attaches_geometry(fake_get):
    a, b = tims_record(), tims_record(SFN="2102374", LATITUDE_DD=40.2)
    fake_get.add("/query", arcgis_features(a, b))
    rows = ArcGISLayer(LAYER).query()
    assert [r["SFN"] for r in rows] == [TIMS_SFN, "2102374"]
    assert rows[0]["_geometry"] == {"x": -82.949, "y": 40.182}
    assert rows[1]["_geometry"] == {"x": -82.949, "y": 40.2}
    assert {k: v for k, v in rows[0].items() if k != "_geometry"} == a


@pytest.mark.xfail(strict=True, reason="untriaged: this test and the code disagree (written 2026-10-03, never run before commit) - decide which is right")
def test_query_without_geometry_drops_geometry_key(fake_get):
    fake_get.add("/query", arcgis_features(tims_record()))   # server still sends geometry
    rows = ArcGISLayer(LAYER).query(return_geometry=False)
    assert "_geometry" not in rows[0]
    fake_get.add("/other", {"features": [{"attributes": {"SFN": "1"}}]})
    assert ArcGISLayer("https://example.invalid/other").query() == [{"SFN": "1"}]


def test_query_no_features_key(fake_get):
    fake_get.add("/query", {"error": {"code": 400, "message": "Invalid query"}})
    assert ArcGISLayer(LAYER).query() == []


@pytest.mark.parametrize("kw", [
    {"status": 500}, {"exc": requests.ConnectionError("dns")}, {"json_error": True},
])
def test_query_failures_return_empty_and_warn(fake_get, caplog, kw):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_get.add("/query", **kw)
    assert ArcGISLayer(LAYER).query() == []
    assert f"ArcGIS query failed on {LAYER}" in caplog.text


def test_query_by_bbox_builds_wgs84_envelope(fake_get):
    fake_get.add("/query", arcgis_features())
    ArcGISLayer(LAYER).query_by_bbox(-83.0, 40.0, -82.9, 40.1, out_fields="SFN", where="X=1")
    p = fake_get.last.params
    assert json.loads(p["geometry"]) == {
        "xmin": -83.0, "ymin": 40.0, "xmax": -82.9, "ymax": 40.1,
        "spatialReference": {"wkid": 4326},
    }
    assert p["geometryType"] == "esriGeometryEnvelope"
    assert p["spatialRel"] == "esriSpatialRelIntersects"
    assert (p["where"], p["outFields"], p["inSR"]) == ("X=1", "SFN", "4326")


def test_query_by_point_buffers_in_ohio_degrees_per_mile(fake_get):
    fake_get.add("/query", arcgis_features())
    ArcGISLayer(LAYER).query_by_point(-82.949, 40.182, buffer_miles=2.0)
    env = json.loads(fake_get.last.params["geometry"])
    assert env["xmin"] == pytest.approx(-82.949 - 2.0 / 54.6, abs=1e-9)
    assert env["xmax"] == pytest.approx(-82.949 + 2.0 / 54.6, abs=1e-9)
    assert env["ymin"] == pytest.approx(40.182 - 2.0 / 69.0, abs=1e-9)
    assert env["ymax"] == pytest.approx(40.182 + 2.0 / 69.0, abs=1e-9)


def test_query_by_point_default_one_mile(fake_get):
    fake_get.add("/query", arcgis_features())
    ArcGISLayer(LAYER).query_by_point(-82.0, 40.0)
    env = json.loads(fake_get.last.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(2 / 69.0)
    assert env["xmax"] - env["xmin"] == pytest.approx(2 / 54.6)


# --- constants -------------------------------------------------------------------------

def test_tims_url_table():
    assert TIMS_BASE == "https://tims.dot.state.oh.us/ags/rest/services"
    assert len(TIMS_URLS) == 25
    assert all(u.startswith(TIMS_BASE + "/") and "/MapServer/" in u for u in TIMS_URLS.values())
    assert TIMS_URLS["bridge_inventory"] == f"{TIMS_BASE}/Assets/Bridge_Inventory/MapServer/0"
    assert TIMS_URLS["dwp_points"].endswith("District_Work_Plan/MapServer/1")
    assert len(set(TIMS_URLS.values())) == 25


def test_district_county_map_covers_all_88_counties_once():
    assert list(ODOT_DISTRICT_COUNTIES) == [f"{d:02d}" for d in range(1, 13)]
    fips = [c for cs in ODOT_DISTRICT_COUNTIES.values() for c in cs]
    assert len(fips) == 88 and len(set(fips)) == 88
    assert all(c % 2 == 1 and 1 <= c <= 175 for c in fips)   # Ohio county FIPS are odd
    assert 41 in ODOT_DISTRICT_COUNTIES["06"]                 # Delaware -> D6
    assert ODOT_DISTRICT_COUNTIES["12"] == [35, 55, 85]       # Cuyahoga, Geauga, Lake


# --- TIMSBridge ---------------------------------------------------------------------------

@pytest.fixture
def bridge(fake_get):
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record()))
    return TIMSBridge(f" {TIMS_SFN}\n")


def test_fetch_queries_by_sfn(bridge, fake_get):
    call = fake_get.last
    assert call.url == BRIDGE_Q
    assert call.params["where"] == f"SFN='{TIMS_SFN}'"
    assert call.params["outFields"] == "*"
    assert call.params["returnGeometry"] == "true"
    assert bridge.sfn == TIMS_SFN
    assert bridge.raw["_geometry"] == {"x": -82.949, "y": 40.182}


def test_not_found_raises(fake_get):
    fake_get.add(BRIDGE_Q, arcgis_features())
    with pytest.raises(ValueError, match="No bridge found in TIMS with SFN '0000000'"):
        TIMSBridge("0000000")


def test_basic_attribute_mapping(bridge):
    assert (bridge.lat, bridge.lon) == (40.182, -82.949)
    assert (bridge.county, bridge.district) == ("DEL", "06")
    assert (bridge.facility_carried, bridge.feature_intersected) == ("SR 3", "ALUM CREEK")
    assert (bridge.main_material, bridge.main_type) == ("3", "02")
    assert bridge.total_spans == 3
    assert (bridge.max_span_length, bridge.overall_length) == (85.0, 240.5)
    assert (bridge.deck_width, bridge.roadway_width, bridge.deck_area) == (44.0, 40.0, 10582.0)
    assert (bridge.skew, bridge.lanes_on, bridge.lanes_under) == (15, 2, 0)
    assert (bridge.adt, bridge.future_adt) == (12500, 15800)
    assert bridge.design_load == "6"
    assert (bridge.owner, bridge.maintenance_responsibility) == ("01", "01")
    assert (bridge.functional_class, bridge.nhs_designation, bridge.bypass_detour_length) == \
        ("03", "1", "5")
    assert bridge.min_vertical_clearance == 99.99
    assert bridge.waterway_adequacy == "8"


def test_numeric_coercions(bridge):
    assert bridge.sufficiency_rating == 82.4
    assert bridge.inventory_rating_factor == 1.12
    assert bridge.operating_rating_factor == 1.45
    assert bridge.approach_roadway_width == 40.0
    assert bridge.drainage_area == 188.5
    assert bridge.stream_velocity == 4.2
    assert all(isinstance(v, float) for v in (
        bridge.sufficiency_rating, bridge.inventory_rating_factor, bridge.approach_roadway_width))


def test_numeric_coercions_tolerate_junk_and_missing(fake_get):
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(
        SUFF_RATING="N/A", RAT_INV_LOAD_FACT=None, RAT_OPR_LOAD_FACT="", APPRH_RDW_WD="?",
        DRN_AREA=None, STREAM_VELOCITY="fast")))
    b = TIMSBridge(TIMS_SFN)
    assert b.sufficiency_rating is None
    assert b.inventory_rating_factor is None
    assert b.operating_rating_factor is None
    assert b.approach_roadway_width is None
    assert b.drainage_area is None
    assert b.stream_velocity is None


def test_get_treats_null_as_missing(bridge):
    bridge._data["DECK_WD"] = None
    assert bridge._get("DECK_WD", "dflt") == "dflt"
    assert bridge._get("NOPE") is None
    assert bridge.deck_width is None


def test_year_built_from_epoch_milliseconds(bridge, fake_get):
    assert bridge.year_built == 2005
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(YR_BUILT=epoch_ms(1931, 7, 4))))
    fake_get.routes.reverse()
    assert TIMSBridge(TIMS_SFN).year_built == 1931   # pre-1970: negative ms


@pytest.mark.parametrize("raw", ["2005", None, 0, 1e30])
def test_year_built_rejects_non_epoch_values(fake_get, raw):
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(YR_BUILT=raw)))
    assert TIMSBridge(TIMS_SFN).year_built is None


def test_condition_ratings_dict(bridge):
    assert bridge.condition_ratings == {
        "deck": "7", "superstructure": "6", "substructure": "7",
        "culvert": "N", "channel": "8", "scour": "8",
    }
    assert (bridge.deck_rating, bridge.superstructure_rating, bridge.substructure_rating,
            bridge.culvert_rating, bridge.channel_rating, bridge.scour_critical) == \
        ("7", "6", "7", "N", "8", "8")


@pytest.mark.parametrize("overrides, sd", [
    ({}, False),
    ({"SUBS_SUMMARY": "4"}, True),               # threshold is <= 4
    ({"SUBS_SUMMARY": "5"}, False),
    ({"DECK_SUMMARY": "N", "SUPS_SUMMARY": "N", "SUBS_SUMMARY": "N", "CULVERT_SUMMARY": "3"}, True),
    ({"DECK_SUMMARY": None, "SUPS_SUMMARY": "x", "SUBS_SUMMARY": None, "CULVERT_SUMMARY": None}, False),
    ({"CHAN_SUMMARY": "2"}, False),              # channel never counts
])
def test_structurally_deficient_rule(fake_get, overrides, sd):
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(**overrides)))
    assert TIMSBridge(TIMS_SFN).is_structurally_deficient is sd


@pytest.mark.parametrize("code, critical", [
    ("0", True), ("3", True), ("T", True), ("U", True), ("4", False), ("8", False),
    ("N", False), (None, False), ("t", False),
])
def test_scour_critical_codes(fake_get, code, critical):
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(SCOUR_CRIT_CD=code)))
    assert TIMSBridge(TIMS_SFN).is_scour_critical is critical


def test_inspection_switches(bridge, fake_get):
    assert bridge.fracture_critical is False
    assert bridge.underwater_inspection is True
    fake_get.routes.clear()
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(FRAC_CRIT_INSP_SW="Y", DIVE_INSP_SW=None)))
    b = TIMSBridge(TIMS_SFN)
    assert b.fracture_critical is True and b.underwater_inspection is False


def test_raw_is_a_copy(bridge):
    raw = bridge.raw
    raw["SFN"] = "tampered"
    assert bridge.raw["SFN"] == TIMS_SFN


def test_repr(bridge, fake_get):
    assert repr(bridge) == (
        f"TIMSBridge(sfn='{TIMS_SFN}', 'SR 3' over 'ALUM CREEK', "
        "built=2005, D/S/S=7/6/7, suff=82.4)"
    )
    fake_get.routes.clear()
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record(
        STR_LOC_CARRIED=None, STR_LOC="", YR_BUILT=None, SUPS_SUMMARY=None, SUFF_RATING=None)))
    assert repr(TIMSBridge(TIMS_SFN)) == \
        f"TIMSBridge(sfn='{TIMS_SFN}', '?' over '?', built=?, D/S/S=7/?/7, suff=None)"


# --- TIMSBridge class searches ---------------------------------------------------------------

def test_search_by_bbox(fake_get):
    fake_get.add(BRIDGE_Q, arcgis_features(tims_record()))
    rows = TIMSBridge.search_by_bbox(-83.0, 40.0, -82.9, 40.1, where="DISTRICT='06'")
    assert rows[0]["SFN"] == TIMS_SFN
    p = fake_get.last.params
    assert p["where"] == "DISTRICT='06'"
    assert json.loads(p["geometry"])["xmin"] == -83.0
    assert fake_get.last.url == BRIDGE_Q


def test_search_near_default_radius_five_miles(fake_get):
    fake_get.add(BRIDGE_Q, arcgis_features())
    TIMSBridge.search_near(-82.949, 40.182)
    env = json.loads(fake_get.last.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(10 / 69.0)
    assert fake_get.last.params["where"] == "1=1"


def test_search_by_county_and_district_where_clauses(fake_get):
    fake_get.add(BRIDGE_Q, arcgis_features())
    TIMSBridge.search_by_county("DEL")
    assert fake_get.last.params["where"] == "COUNTY_CD='DEL'"
    TIMSBridge.search_by_district("06")
    assert fake_get.last.params["where"] == "DISTRICT='06'"
    assert "geometry" not in fake_get.last.params


# --- TIMSProject / TIMSRoad / TIMSWaterway ----------------------------------------------------

DWP_Q = TIMS_URLS["dwp_lines"] + "/query"


def test_project_searches(fake_get):
    fake_get.add(DWP_Q, arcgis_features({"PID_NBR": "112233", "PROJECT_NME": "DEL-3-2.10"}))
    assert TIMSProject.search_by_district("06")[0]["PID_NBR"] == "112233"
    assert fake_get.last.params["where"] == "DISTRICT_NBR='06'"
    assert fake_get.last.params["outFields"] == "*"
    TIMSProject.search_by_county("delaware")
    assert fake_get.last.params["where"] == "COUNTY_NME_WORK_LOCATION='DELAWARE'"
    TIMSProject.search_by_pid("112233")
    assert fake_get.last.params["where"] == "PID_NBR='112233'"
    TIMSProject.search_near(-82.9, 40.1, radius_miles=1.0)
    env = json.loads(fake_get.last.params["geometry"])
    assert env["xmax"] - env["xmin"] == pytest.approx(2 / 54.6)
    assert all(c.url == DWP_Q for c in fake_get.calls)
    assert TIMSProject._points_layer._url == TIMS_URLS["dwp_points"]


@pytest.mark.parametrize("method, key, default_radius", [
    (TIMSRoad.functional_class_near, "functional_class", 1.0),
    (TIMSRoad.nhs_routes_near, "nhs", 2.0),
    (TIMSRoad.freight_network_near, "freight_network", 5.0),
    (TIMSWaterway.scenic_rivers_near, "scenic_rivers", 2.0),
    (TIMSWaterway.mussel_streams_near, "mussel_streams", 2.0),
    (TIMSWaterway.wetlands_near, "wetlands", 1.0),
])
def test_point_search_helpers_hit_their_layer_with_default_radius(fake_get, method, key,
                                                                  default_radius):
    fake_get.add("/query", arcgis_features({"NAME": "x"}))
    assert method(-82.949, 40.182) == [{"NAME": "x", "_geometry": {"x": -82.9, "y": 40.1}}]
    call = fake_get.last
    assert call.url == TIMS_URLS[key] + "/query"
    env = json.loads(call.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(2 * default_radius / 69.0)
    assert env["xmax"] - env["xmin"] == pytest.approx(2 * default_radius / 54.6)
    method(-82.949, 40.182, radius_miles=0.5)
    env = json.loads(fake_get.last.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(1 / 69.0)


def test_road_inventory_layer_is_wired():
    assert TIMSRoad._road_inv._url == TIMS_URLS["road_inventory"]
