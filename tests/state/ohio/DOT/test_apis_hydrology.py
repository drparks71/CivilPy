#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""USGS / NHD hydrology wrappers in ``apis``: ``NHDFlowline`` (which
NHDPlus HR MapServer layer each helper queries, with what out-fields and
buffer), ``USGSStreamStats`` (delineate URL/params/timeout, parsing of
basin parameters, nested flow statistics and the watershed GeoJSON, and
the empty-result contract on failure) and ``USGSGauge`` (NWIS site bBox
string, IV parameter codes 00060/00065 -> discharge/gage height from the
latest value). All against the recording fake transport."""

import json
import logging

import pytest
import requests

from civilpy.state.ohio.DOT import apis
from civilpy.state.ohio.DOT.apis import NHDFlowline, USGSGauge, USGSStreamStats
from tests.state.ohio.DOT.apis_fixtures import (
    arcgis_features, nhd_flowline, nwis_iv_payload, streamstats_payload,
)

NHD = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer"
SS = "https://streamstats.usgs.gov/ss-delineate/v1"
NWIS = "https://waterservices.usgs.gov/nwis"
LON, LAT = -82.949, 40.182


# --- NHDFlowline ---------------------------------------------------------------

def test_flowlines_near_uses_layer_3_with_stream_order_fields(fake_get):
    fake_get.add(f"{NHD}/3/query", arcgis_features(nhd_flowline(), nhd_flowline("Big Walnut Creek", 5)))
    rows = NHDFlowline.near(LON, LAT)
    assert [(r["GNIS_Name"], r["StreamOrder"]) for r in rows] == \
        [("Alum Creek", 4), ("Big Walnut Creek", 5)]
    call = fake_get.last
    assert call.url == f"{NHD}/3/query"
    assert call.params["outFields"] == \
        "GNIS_Name,FType,FCode,StreamOrder,LengthKm,Permanent_Identifier"
    env = json.loads(call.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(1.0 / 69.0)      # default 0.5 mi
    assert NHDFlowline._flowline_layer._max_records == 2000


def test_flowlines_near_custom_radius_and_fields(fake_get):
    fake_get.add(f"{NHD}/3/query", arcgis_features())
    NHDFlowline.near(LON, LAT, radius_miles=0.1, out_fields="GNIS_Name")
    env = json.loads(fake_get.last.params["geometry"])
    assert env["xmax"] - env["xmin"] == pytest.approx(0.2 / 54.6)
    assert fake_get.last.params["outFields"] == "GNIS_Name"


def test_waterbodies_near_uses_layer_9(fake_get):
    fake_get.add(f"{NHD}/9/query", arcgis_features({"GNIS_Name": "Alum Creek Lake", "AreaSqKm": 13.7}))
    rows = NHDFlowline.waterbodies_near(LON, LAT)
    assert rows[0]["AreaSqKm"] == 13.7
    assert fake_get.last.url == f"{NHD}/9/query"
    assert fake_get.last.params["outFields"] == "GNIS_Name,FType,FCode,AreaSqKm"
    env = json.loads(fake_get.last.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(2.0 / 69.0)      # default 1 mi


def test_huc12_at_uses_layer_12_with_tiny_buffer(fake_get):
    fake_get.add(f"{NHD}/12/query", arcgis_features({"HUC12": "050600010403", "Name": "Alum Creek"}))
    assert NHDFlowline.huc12_at(LON, LAT)[0]["HUC12"] == "050600010403"
    call = fake_get.last
    assert call.url == f"{NHD}/12/query"
    assert call.params["outFields"] == "*"
    env = json.loads(call.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(0.02 / 69.0)
    assert env["xmax"] - env["xmin"] == pytest.approx(0.02 / 54.6)


def test_nhd_failure_is_empty_list(fake_get):
    fake_get.add(f"{NHD}/3/query", status=502)
    assert NHDFlowline.near(LON, LAT) == []


# --- USGSStreamStats ----------------------------------------------------------------

def test_delineate_request_and_parsing(fake_get):
    fake_get.add(f"{SS}/delineate/sshydro/OH", streamstats_payload())
    result = USGSStreamStats.delineate(LON, LAT)
    call = fake_get.last
    assert call.url == f"{SS}/delineate/sshydro/OH"
    assert call.params == {"lat": LAT, "lon": LON}
    assert call.timeout == 120
    assert result["drainage_area_sqmi"] == 188.5
    assert result["basin_characteristics"] == {"DRNAREA": 188.5, "CSL10_85": 12.3, "PRECIP": None}
    assert result["peak_flows"] == {"PK2": 4200.0, "PK100": 12400.0}      # None values dropped
    assert result["watershed_geojson"]["type"] == "FeatureCollection"
    assert result["raw"] is not None and result["raw"]["workspaceID"].startswith("OH")


def test_delineate_region_in_path(fake_get):
    fake_get.add(f"{SS}/delineate/sshydro/KY", {"parameters": []})
    result = USGSStreamStats.delineate(LON, LAT, region="KY")
    assert fake_get.last.url == f"{SS}/delineate/sshydro/KY"
    assert result["drainage_area_sqmi"] is None
    assert result["peak_flows"] == {} and result["watershed_geojson"] is None


@pytest.mark.parametrize("kw", [{"status": 500}, {"exc": requests.Timeout("slow")}, {"json_error": True}])
def test_delineate_failure_contract(fake_get, caplog, kw):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_get.add("/delineate/sshydro/", **kw)
    assert USGSStreamStats.delineate(LON, LAT) == {
        "drainage_area_sqmi": None, "basin_characteristics": {},
        "peak_flows": {}, "watershed_geojson": None, "raw": {},
    }
    assert "StreamStats delineation failed" in caplog.text


def test_delineate_features_only(fake_get, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature"}]}
    fake_get.add(f"{SS}/delineate/features/OH", fc)
    assert USGSStreamStats.delineate_features_only(LON, LAT) == fc
    call = fake_get.last
    assert call.params == {"lat": LAT, "lon": LON} and call.timeout == 60
    fake_get.add(f"{SS}/delineate/features/IN", status=404)
    assert USGSStreamStats.delineate_features_only(LON, LAT, region="IN") is None
    assert "StreamStats feature delineation failed" in caplog.text


# --- USGSGauge ------------------------------------------------------------------------

def test_gauge_near_request_params(fake_get):
    fake_get.add(f"{NWIS}/site/", {"value": {"timeSeries": [{"site_no": "03229000"}]}})
    assert USGSGauge.near(LON, LAT, radius_miles=10) == [{"site_no": "03229000"}]
    call = fake_get.last
    assert call.url == f"{NWIS}/site/"
    assert call.timeout == 30
    assert call.params == {
        "format": "json",
        "bBox": "-83.13215018315019,40.03707246376812,-82.76584981684981,40.326927536231885",
        "siteType": "ST", "siteStatus": "active", "hasDataTypeCd": "iv",
        "parameterCd": "00060", "siteOutput": "expanded",
    }


def test_gauge_near_default_radius_and_alternate_structure(fake_get):
    fake_get.add(f"{NWIS}/site/", {"value": {"queryInfo": {"sites": [{"site_no": "A"}, {"site_no": "B"}]}}})
    assert USGSGauge.near(LON, LAT) == [{"site_no": "A"}, {"site_no": "B"}]
    xmin, ymin, xmax, ymax = (float(v) for v in fake_get.last.params["bBox"].split(","))
    assert xmax - xmin == pytest.approx(20 / 54.6)
    assert ymax - ymin == pytest.approx(20 / 69.0)


def test_gauge_near_empty_and_failure(fake_get, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_get.add(f"{NWIS}/site/", {"value": {}})
    assert USGSGauge.near(LON, LAT) == []
    fake_get.routes.clear()
    fake_get.add(f"{NWIS}/site/", exc=requests.ConnectionError("x"))
    assert USGSGauge.near(LON, LAT) == []
    assert "USGS gauge query failed" in caplog.text


def test_gauge_by_site_latest_values(fake_get):
    fake_get.add(f"{NWIS}/iv/", nwis_iv_payload())
    result = USGSGauge.by_site("03229000")
    call = fake_get.last
    assert call.url == f"{NWIS}/iv/" and call.timeout == 30
    assert call.params == {"format": "json", "sites": "03229000",
                           "parameterCd": "00060,00065", "siteStatus": "active"}
    assert result == {
        "site_no": "03229000",
        "discharge_cfs": 325.0,                       # last value, not first
        "gage_height_ft": 3.41,
        "datetime": "2026-10-03T08:15:00.000-04:00",
        "site_name": "Alum Creek at Columbus OH",
    }


def test_gauge_by_site_series_without_values(fake_get):
    payload = nwis_iv_payload()
    payload["value"]["timeSeries"][0]["values"] = [{"value": []}]
    fake_get.add(f"{NWIS}/iv/", payload)
    result = USGSGauge.by_site("03229000")
    assert "discharge_cfs" not in result
    assert result["gage_height_ft"] == 3.41
    assert result["site_name"] == "Alum Creek at Columbus OH"


def test_gauge_by_site_failure(fake_get, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_get.add(f"{NWIS}/iv/", status=503)
    assert USGSGauge.by_site("03229000") == {"site_no": "03229000"}
    assert "USGS gauge IV query failed for 03229000" in caplog.text
