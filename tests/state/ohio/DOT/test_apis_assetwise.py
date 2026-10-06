#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""HTTP clients in ``apis`` that wrap per-bridge REST services:
``AssetwiseRawBridge`` (Bentley AssetWise, basic-auth session; SFN ->
as_id resolution, current values, element quantities, latest report
discovery, field names) and ``BridgeDBAsset`` (the internal Django API).
Every test pins the URL, headers/auth and timeout sent, how the JSON
envelope is unpacked, and the non-200 / exception branches, all against
a recording fake transport."""

import logging

import pytest
import requests
from requests.auth import HTTPBasicAuth

from civilpy.state.ohio.DOT import apis
from civilpy.state.ohio.DOT.apis import AssetwiseRawBridge, BridgeDBAsset
from tests.state.ohio.DOT.apis_fixtures import (
    TIMS_SFN, aw_assets, aw_current_values, aw_elements, aw_reports,
)

AW = "https://ohiodot-it-api.bentley.com"


@pytest.fixture
def aw_secrets(secrets):
    return secrets(BENTLEY_ASSETWISE_KEY_NAME="odot-reader", BENTLEY_ASSETWISE_API="k3y")


@pytest.fixture
def aw(fake_session, aw_secrets, caplog):
    """Transport pre-routed for a successful SFN -> as_id -> values resolve."""
    caplog.set_level(logging.DEBUG, logger=apis.logger.name)
    fake_session.add("/api/Asset/GetAssetsByCode/", aw_assets())
    fake_session.add("/api/CurrentValue/GetCurrentValuesByAssetId/", aw_current_values())
    return fake_session


# --- construction / resolve -----------------------------------------------------

def test_session_auth_and_headers_from_secrets(aw):
    bridge = AssetwiseRawBridge(TIMS_SFN)
    session = aw.sessions[0]
    assert isinstance(session.auth, HTTPBasicAuth)
    assert (session.auth.username, session.auth.password) == ("odot-reader", "k3y")
    assert session.headers == {"Accept": "application/json", "Content-Type": "application/json"}
    assert bridge._session is session


def test_requires_secrets(fake_session, home):
    with pytest.raises(FileNotFoundError):
        AssetwiseRawBridge(TIMS_SFN)


def test_resolve_then_fetch_current_values(aw):
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert aw.urls == [
        f"{AW}/api/Asset/GetAssetsByCode/{TIMS_SFN}",
        f"{AW}/api/CurrentValue/GetCurrentValuesByAssetId/555",
    ]
    assert bridge.as_id == "555"
    # cv_value, then value, then va_value; items without fe_id are dropped
    assert bridge.current_values == {101: "DEL", 102: "2005", 103: "7"}


def test_resolve_no_asset_logs_warning_and_stops(fake_session, aw_secrets, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_session.add("/GetAssetsByCode/", {"success": True, "data": []})
    bridge = AssetwiseRawBridge("0000001")
    assert bridge.as_id is None and bridge.current_values == {}
    assert len(fake_session.calls) == 1
    assert "No asset found for SFN 0000001" in caplog.text


def test_resolve_http_error_logged(fake_session, aw_secrets, caplog):
    caplog.set_level(logging.ERROR, logger=apis.logger.name)
    fake_session.add("/GetAssetsByCode/", status=503, text="Service Unavailable")
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.as_id is None
    rec = caplog.records[-1]
    assert rec.levelno == logging.ERROR
    assert "API error 503" in rec.message and "Service Unavailable" in rec.message


def test_resolve_transport_exception_logged(fake_session, aw_secrets, caplog):
    caplog.set_level(logging.ERROR, logger=apis.logger.name)
    fake_session.add("/GetAssetsByCode/", exc=requests.ConnectionError("VPN down"))
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.as_id is None
    assert "Request failed for SFN" in caplog.text and "VPN down" in caplog.text


@pytest.mark.parametrize("payload, status, expect", [
    ({"success": False, "message": "not authorised"}, 200, "success=False"),
    (None, 500, "API error 500"),
])
def test_current_values_failure_branches(fake_session, aw_secrets, caplog, payload, status, expect):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_session.add("/GetAssetsByCode/", aw_assets())
    fake_session.add("/GetCurrentValuesByAssetId/", payload, status=status)
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.as_id == "555" and bridge.current_values == {}
    assert expect in caplog.text


def test_current_values_exception_logged(fake_session, aw_secrets, caplog):
    caplog.set_level(logging.ERROR, logger=apis.logger.name)
    fake_session.add("/GetAssetsByCode/", aw_assets())
    fake_session.add("/GetCurrentValuesByAssetId/", exc=requests.Timeout("slow"))
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.current_values == {}
    assert "AssetWise values: Request failed for as_id=555" in caplog.text


def test_fetch_current_values_noop_without_as_id(aw):
    bridge = AssetwiseRawBridge(TIMS_SFN)
    bridge.as_id = None
    bridge.current_values = {}
    bridge._fetch_current_values()
    assert bridge.current_values == {} and len(aw.calls) == 2


# --- elements -------------------------------------------------------------------

def test_get_elements_with_explicit_report(aw):
    aw.add("/api/StructureElement/GetElements/", {"success": True, "value": aw_elements()})
    bridge = AssetwiseRawBridge(TIMS_SFN)
    elems = bridge.get_elements(report_id="9007")
    assert aw.last.url == f"{AW}/api/StructureElement/GetElements/1/9007/555"
    assert [e["se_display_id"] for e in elems] == ["12", "107"]
    assert elems[0]["totalQuantity"] == 10582


@pytest.mark.parametrize("payload, expect_len", [
    ({"data": aw_elements()}, 2),          # 'data' envelope
    (aw_elements(), 2),                     # bare list
    ({"success": True}, 0),                 # neither key
])
def test_get_elements_envelopes(aw, payload, expect_len):
    aw.add("/GetElements/", payload)
    assert len(AssetwiseRawBridge(TIMS_SFN).get_elements("1")) == expect_len


def test_get_elements_non_200_and_exception_return_empty(aw, caplog):
    aw.add("/GetElements/1/404/", status=404)
    aw.add("/GetElements/1/boom/", exc=RuntimeError("socket"))
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.get_elements("404") == []
    assert bridge.get_elements("boom") == []
    assert f"Failed to fetch elements for SFN {TIMS_SFN}" in caplog.text


def test_get_elements_without_as_id_short_circuits(aw):
    bridge = AssetwiseRawBridge(TIMS_SFN)
    bridge.as_id = None
    assert bridge.get_elements() == []
    assert len(aw.calls) == 2


def test_get_elements_discovers_latest_report(aw):
    aw.add("/api/Report/GetReportsByAssetId/", aw_reports())
    aw.add("/GetElements/", {"value": aw_elements()})
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert len(bridge.get_elements()) == 2
    assert aw.urls[2:] == [
        f"{AW}/api/Report/GetReportsByAssetId/555",
        f"{AW}/api/StructureElement/GetElements/1/9007/555",   # newest rp_date, not max rp_id order
    ]


def test_get_elements_no_reports_returns_empty_without_elements_call(aw):
    aw.add("/GetReportsByAssetId/", {"success": True, "data": []})
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.get_elements() == []
    assert not aw.calls_to("GetElements")


def test_latest_report_id_failure_branches(aw, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    bridge = AssetwiseRawBridge(TIMS_SFN)
    aw.add("/GetReportsByAssetId/", status=500)
    assert bridge._get_latest_report_id() is None
    aw.routes.clear()
    aw.add("/GetReportsByAssetId/", exc=requests.ConnectionError("reset"))
    assert bridge._get_latest_report_id() is None
    assert "Failed to get reports for as_id=555" in caplog.text
    bridge.as_id = None
    assert bridge._get_latest_report_id() is None


# --- field names ----------------------------------------------------------------

def test_get_field_name(aw):
    aw.add("/api/Field/101", {"success": True, "data": {"fe_id": 101, "fe_name": "County"}})
    aw.add("/api/Field/102", {"success": True, "data": {"fe_id": 102}})
    aw.add("/api/Field/103", {"success": False})
    aw.add("/api/Field/104", status=404)
    aw.add("/api/Field/105", exc=RuntimeError("x"))
    bridge = AssetwiseRawBridge(TIMS_SFN)
    assert bridge.get_field_name(101) == "County"
    assert aw.last.url == f"{AW}/api/Field/101"
    assert [bridge.get_field_name(i) for i in (102, 103, 104, 105)] == ["Unknown"] * 4


def test_repr(aw):
    assert repr(AssetwiseRawBridge(TIMS_SFN)) == \
        f"AssetwiseRawBridge(sfn='{TIMS_SFN}', as_id=555, fields=3)"


# --- BridgeDBAsset ----------------------------------------------------------------

DJANGO_RECORD = {
    "sfn": TIMS_SFN, "condition": "Fair", "snbiStatus": "Compliant",
    "lastInspection": "2024-06-15", "coordinates": {"lat": 40.182, "lng": -82.949},
    "bid02_bridge_name": "SR 3 over Alum Creek", "bw01_year_built": 2005,
    "bl04_highway_district": "06",
}


def test_bridge_db_asset_fetches_and_maps(fake_get):
    fake_get.add("/api/bridges/", DJANGO_RECORD)
    bridge = BridgeDBAsset(TIMS_SFN, base_url="http://bridgedb.internal:8000/")
    call = fake_get.last
    assert call.url == f"http://bridgedb.internal:8000/api/bridges/{TIMS_SFN}/"
    assert call.timeout == 10
    assert bridge.condition == "Fair"
    assert bridge.snbi_status == "Compliant"
    assert bridge.last_inspection == "2024-06-15"
    assert bridge.coordinates == {"lat": 40.182, "lng": -82.949}
    assert bridge.bridge_name == "SR 3 over Alum Creek"
    assert bridge.year_built == 2005
    assert bridge.district == "06"
    assert repr(bridge) == f"BridgeDBAsset(sfn='{TIMS_SFN}', condition='Fair', status='Compliant')"


def test_bridge_db_asset_default_base_url(fake_get):
    fake_get.add("/api/bridges/", {})
    BridgeDBAsset(TIMS_SFN)
    assert fake_get.last.url == f"http://localhost:8000/api/bridges/{TIMS_SFN}/"


def test_bridge_db_asset_http_error_gives_empty_record(fake_get, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_get.add("/api/bridges/", status=404)
    bridge = BridgeDBAsset("0000000")
    assert bridge._data == {}
    assert bridge.condition is None and bridge.coordinates is None
    assert "Failed to fetch bridge 0000000 from API" in caplog.text
    assert repr(bridge) == "BridgeDBAsset(sfn='0000000', condition=None, status=None)"


def test_bridge_db_asset_connection_error(fake_get):
    fake_get.add("/api/bridges/", exc=requests.ConnectionError("refused"))
    assert BridgeDBAsset(TIMS_SFN)._data == {}


def test_fetch_compliance_metrics(fake_get):
    fake_get.add("/api/bridges/", DJANGO_RECORD)
    fake_get.add("/api/compliance-metrics/", {"M1": 42.1, "M8": 311})
    bridge = BridgeDBAsset(TIMS_SFN)
    assert bridge.fetch_compliance_metrics() == {"M1": 42.1, "M8": 311}
    assert fake_get.last.url == "http://localhost:8000/api/compliance-metrics/"
    assert fake_get.last.timeout == 30


def test_fetch_comparison(fake_get):
    fake_get.add("/compare/", {"tims": {"year_built": 2005}, "assetwise": {"year_built": 2005}})
    fake_get.add("/api/bridges/", DJANGO_RECORD)
    bridge = BridgeDBAsset(TIMS_SFN)
    assert bridge.fetch_comparison()["tims"] == {"year_built": 2005}
    assert fake_get.last.url == f"http://localhost:8000/api/bridges/{TIMS_SFN}/compare/"
    assert fake_get.last.timeout == 10


def test_secondary_fetches_swallow_request_errors(fake_get, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_get.add("/compare/", status=500)
    fake_get.add("/compliance-metrics/", exc=requests.Timeout("slow"))
    fake_get.add("/api/bridges/", DJANGO_RECORD)
    bridge = BridgeDBAsset(TIMS_SFN)
    assert bridge.fetch_comparison() == {}
    assert bridge.fetch_compliance_metrics() == {}
    assert f"Failed to fetch comparison for {TIMS_SFN}" in caplog.text
    assert "Failed to fetch compliance metrics" in caplog.text
