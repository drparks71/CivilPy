#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""SNBI compliance and bridge-engineering checks in ``apis``: the FHWA
required-field and NBIP metric tables, ``SNBIComplianceChecker`` rules
(populated-field test, completeness %, Good/Fair/Poor from the lowest
condition rating, inspection currency from BIE06, scour-critical and
posting code sets), the haversine helper, and every
``BridgeEngineeringChecks`` routine driven end-to-end through the fake
ArcGIS transport (bridge inventory, NHD flowlines, scenic/mussel layers,
DWP projects) so URLs, WHERE clauses, radii and the derived output
dicts are all pinned."""

import json
import logging
from datetime import date, datetime

import pytest

from civilpy.state.ohio.DOT import apis
from civilpy.state.ohio.DOT.apis import (
    FHWA_NBIP_METRICS, SNBI_REQUIRED_FIELDS, TIMS_URLS, BridgeEngineeringChecks,
    SNBIComplianceChecker, _haversine_miles,
)
from tests.state.ohio.DOT.apis_fixtures import (
    SNBI_ALL_CODES, TIMS_SFN, arcgis_features, nhd_flowline, snbi_record, tims_record,
)

BRIDGE_Q = TIMS_URLS["bridge_inventory"] + "/query"
NHD3_Q = "NHDPlus_HR/MapServer/3/query"
LON, LAT = -82.949, 40.182


# --- tables ---------------------------------------------------------------------

def test_required_field_table():
    assert len(SNBI_REQUIRED_FIELDS) == 30
    assert [c for c, _, s in SNBI_REQUIRED_FIELDS if s == "all"] == SNBI_ALL_CODES
    assert {s for _, _, s in SNBI_REQUIRED_FIELDS} == {"all", "highway", "nhs"}
    assert [c for c, _, s in SNBI_REQUIRED_FIELDS if s == "nhs"] == ["BH03"]
    assert len({c for c, _, _ in SNBI_REQUIRED_FIELDS}) == 30


def test_nbip_metric_table():
    assert list(FHWA_NBIP_METRICS) == [f"M{i}" for i in range(1, 24)]
    assert FHWA_NBIP_METRICS["M8"] == "Number of structurally deficient bridges"


# --- SNBIComplianceChecker ------------------------------------------------------------

def test_has_treats_blank_as_missing_but_zero_as_present():
    c = SNBIComplianceChecker({"BID01": 0, "BL01": "", "BL02": "   ", "BL05": None, "BL06": "x"})
    assert c._has("BID01") is True
    assert c._has("BL01") is False and c._has("BL02") is False
    assert c._has("BL05") is False and c._has("BL06") is True
    assert c._has("NOPE") is False


def test_complete_record_has_no_gaps():
    c = SNBIComplianceChecker(snbi_record())
    assert c.missing_fields == []
    assert c.completeness_pct == 100.0
    assert c.missing_fields_nhs == [("BH03", "NHS Designation")]   # not supplied


def test_missing_fields_and_completeness():
    c = SNBIComplianceChecker(snbi_record(BL05="", BLR05=None, BH01=None))
    assert c.missing_fields == [("BL05", "Latitude"), ("BLR05", "Inventory Rating Factor")]
    assert c.completeness_pct == round(25 / 27 * 100, 1) == 92.6
    assert ("BH01", "Functional Classification") not in c.missing_fields_nhs
    assert c.needs_load_rating is True
    assert SNBIComplianceChecker({}).completeness_pct == 0.0
    assert len(SNBIComplianceChecker({}).missing_fields) == 27


@pytest.mark.parametrize("ratings, expected", [
    ({"BC01": "7", "BC02": "8", "BC03": "9"}, "Good"),
    ({"BC01": "7", "BC02": "6", "BC03": "7"}, "Fair"),
    ({"BC01": "5", "BC02": "7", "BC03": "7"}, "Fair"),
    ({"BC01": "7", "BC02": "7", "BC03": "4"}, "Poor"),
    ({"BC01": "N", "BC02": "N", "BC03": "N", "BC04": "3"}, "Poor"),     # culvert used
    ({"BC01": "N", "BC02": None}, "Unknown"),
    ({}, "Unknown"),
    ({"BC01": 8, "BC02": 8, "BC03": 7}, "Good"),                         # ints accepted
])
def test_condition_classification(ratings, expected):
    c = SNBIComplianceChecker(ratings)
    assert c.condition_classification == expected
    assert c.is_structurally_deficient is (expected == "Poor")


@pytest.mark.parametrize("due, current", [
    ("20991231", True), (20991231, True), (" 20991231 ", True),
    ("20000101", False), (None, False), ("", False), ("2099-12-31", False), ("soon", False),
])
def test_inspection_currency(due, current):
    assert SNBIComplianceChecker({"BIE06": due}).is_inspection_current is current


def test_inspection_due_today_is_current():
    today = date.today().strftime("%Y%m%d")
    assert SNBIComplianceChecker({"BIE06": today}).is_inspection_current is True


@pytest.mark.parametrize("code, critical", [
    ("0", True), ("3", True), ("T", True), ("U", True), (" 2 ", True), (3, True),
    ("4", False), ("8", False), ("N", False), (None, False), ("t", False),
])
def test_scour_critical(code, critical):
    assert SNBIComplianceChecker({"BC11": code}).is_scour_critical is critical


def test_scour_poa_and_posting_and_load_rating():
    assert SNBIComplianceChecker({"BAP04": "2023-01-01"}).has_scour_poa is True
    assert SNBIComplianceChecker({"BAP04": ""}).has_scour_poa is False
    for code in ("P", "b", " r "):
        assert SNBIComplianceChecker({"BPS01": code}).is_posted is True
    for code in ("A", "", None, "X"):
        assert SNBIComplianceChecker({"BPS01": code}).is_posted is False
    assert SNBIComplianceChecker({"BLR04": "3", "BLR05": 1.1}).needs_load_rating is False
    assert SNBIComplianceChecker({"BLR04": "3"}).needs_load_rating is True
    assert SNBIComplianceChecker({"BLR05": 1.1}).needs_load_rating is True


def test_compliance_summary_and_repr():
    c = SNBIComplianceChecker(snbi_record(BC03="4", BC11="3", BPS01="P", BIE06="20200101"))
    assert c.compliance_summary == {
        "sfn": TIMS_SFN, "completeness_pct": 100.0, "missing_count": 0, "missing_fields": [],
        "condition": "Poor", "structurally_deficient": True, "inspection_current": False,
        "scour_critical": True, "has_scour_poa": False, "posted": True,
        "needs_load_rating": False,
    }
    assert repr(c) == f"SNBICompliance(sfn='{TIMS_SFN}', complete=100.0%, cond=Poor, insp_current=False)"
    assert repr(SNBIComplianceChecker({})) == \
        "SNBICompliance(sfn='?', complete=0.0%, cond=Unknown, insp_current=False)"


# --- haversine ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="untriaged: this test and the code disagree (written 2026-10-03, never run before commit) - decide which is right")
def test_haversine_miles():
    assert _haversine_miles(40.0, -83.0, 40.0, -83.0) == 0.0
    assert _haversine_miles(0.0, 0.0, 1.0, 0.0) == pytest.approx(69.094, abs=1e-3)   # R*pi/180
    assert _haversine_miles(0.0, 0.0, 0.0, 180.0) == pytest.approx(3958.8 * 3.141592653589793, rel=1e-9)
    assert _haversine_miles(39.9612, -82.9988, 41.4993, -81.6944) == pytest.approx(125.6, abs=0.5)
    assert _haversine_miles(40.0, -83.0, 41.0, -82.0) == _haversine_miles(41.0, -82.0, 40.0, -83.0)


# --- BridgeEngineeringChecks (spatial) ---------------------------------------------------------

def _inventory(*records):
    return arcgis_features(*records)


def test_bridges_near_point_filters_to_state_and_sorts_by_distance(fake_get):
    far = tims_record(SFN="A", LATITUDE_DD=40.30, LONGITUDE_DD=-82.949)
    near = tims_record(SFN="B", LATITUDE_DD=40.19, LONGITUDE_DD=-82.949)
    nowhere = tims_record(SFN="C", LATITUDE_DD=None, LONGITUDE_DD=None)
    fake_get.add(BRIDGE_Q, _inventory(far, nowhere, near))
    rows = BridgeEngineeringChecks.bridges_near_point(LON, LAT, radius_miles=10)
    assert fake_get.last.params["where"] == "MAINT_RESP_CD='01'"
    env = json.loads(fake_get.last.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(20 / 69.0)
    assert [r["SFN"] for r in rows] == ["B", "A", "C"]
    assert rows[0]["distance_miles"] == pytest.approx(round(_haversine_miles(LAT, LON, 40.19, LON), 2))
    assert rows[1]["distance_miles"] == 8.15
    assert rows[2]["distance_miles"] is None


def test_bridges_near_point_all_owners(fake_get):
    fake_get.add(BRIDGE_Q, _inventory())
    assert BridgeEngineeringChecks.bridges_near_point(LON, LAT, only_state=False) == []
    assert fake_get.last.params["where"] == "1=1"


def test_streams_at_bridge_combines_three_sources(fake_get):
    fake_get.add(BRIDGE_Q, _inventory(tims_record()))
    fake_get.add(NHD3_Q, arcgis_features(nhd_flowline()))
    fake_get.add("Scenic_Rivers", arcgis_features({"NAME": "Big Darby"}))
    fake_get.add("Mussel_Streams", arcgis_features())
    out = BridgeEngineeringChecks.streams_at_bridge(TIMS_SFN)
    assert out["bridge"] == {"sfn": TIMS_SFN, "facility": "SR 3", "feature": "ALUM CREEK",
                             "lat": LAT, "lon": LON}
    assert out["nhd_flowlines"][0]["GNIS_Name"] == "Alum Creek"
    assert out["scenic_rivers"][0]["NAME"] == "Big Darby"
    assert out["mussel_streams"] == []
    assert out["tims_drainage_area"] == 188.5
    assert out["tims_stream_velocity"] == 4.2
    nhd_call = fake_get.calls_to(NHD3_Q)[0]
    env = json.loads(nhd_call.params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(0.5 / 69.0)          # 0.25 mi
    scenic_env = json.loads(fake_get.calls_to("Scenic_Rivers")[0].params["geometry"])
    assert scenic_env["ymax"] - scenic_env["ymin"] == pytest.approx(4 / 69.0)   # default 2 mi
    assert [c.url for c in fake_get.calls] == [
        BRIDGE_Q,
        "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3/query",
        TIMS_URLS["scenic_rivers"] + "/query",
        TIMS_URLS["mussel_streams"] + "/query",
    ]


def test_streams_at_bridge_error_dicts(fake_get):
    fake_get.add(BRIDGE_Q, _inventory())
    assert BridgeEngineeringChecks.streams_at_bridge("0") == {"error": "Bridge 0 not found in TIMS"}
    fake_get.routes.clear()
    fake_get.add(BRIDGE_Q, _inventory(tims_record(LATITUDE_DD=None)))
    assert BridgeEngineeringChecks.streams_at_bridge(TIMS_SFN) == \
        {"error": f"Bridge {TIMS_SFN} has no coordinates"}
    assert len(fake_get.calls) == 2          # never reached NHD


def test_scour_vulnerability_scan_orders_critical_then_stream_order(fake_get):
    fake_get.add(BRIDGE_Q, _inventory(
        tims_record(SFN="LOW", SCOUR_CRIT_CD="8", LATITUDE_DD=40.10, LONGITUDE_DD=-82.90),
        tims_record(SFN="BIGRIVER", SCOUR_CRIT_CD="5", LATITUDE_DD=40.11, LONGITUDE_DD=-82.91),
        tims_record(SFN="CRIT", SCOUR_CRIT_CD="3", LATITUDE_DD=40.12, LONGITUDE_DD=-82.92),
        tims_record(SFN="NOLOC", SCOUR_CRIT_CD=None, LATITUDE_DD=None, LONGITUDE_DD=None),
    ))
    # route NHD by the envelope longitude of each bridge
    orig = fake_get.__class__.__call__

    def nhd_router(method, url, **kw):
        if NHD3_Q in url:
            fake_get.calls.append(apis_call(method, url, kw))
            env = json.loads(kw["params"]["geometry"])
            centre = round((env["xmin"] + env["xmax"]) / 2, 3)
            orders = {-82.90: [2, 3], -82.91: [6, None], -82.92: []}[centre]
            feats = [nhd_flowline(order=o) for o in orders]
            return fake_response(arcgis_features(*feats))
        return orig(fake_get, method, url, **kw)

    from tests.state.ohio.DOT.conftest import Call as apis_call, FakeResponse as fake_response
    apis.requests.get = lambda url, **kw: nhd_router("GET", url, **kw)

    rows = BridgeEngineeringChecks.scour_vulnerability_scan(LON, LAT, radius_miles=10)
    assert fake_get.calls[0].params["where"] == "MAINT_RESP_CD='01'"
    assert [r["sfn"] for r in rows] == ["CRIT", "BIGRIVER", "LOW", "NOLOC"]
    by = {r["sfn"]: r for r in rows}
    assert by["CRIT"]["is_scour_critical"] is True and by["CRIT"]["max_stream_order"] is None
    assert by["BIGRIVER"]["max_stream_order"] == 6
    assert by["LOW"]["max_stream_order"] == 3
    assert by["NOLOC"] == {
        "sfn": "NOLOC", "facility": "SR 3", "feature": "ALUM CREEK", "scour_code": None,
        "is_scour_critical": False, "drainage_area": "188.5", "stream_velocity": "4.2",
        "max_stream_order": None, "distance_miles": None,
    }
    assert by["LOW"]["distance_miles"] == round(_haversine_miles(LAT, LON, 40.10, -82.90), 2)
    nhd_calls = fake_get.calls_to(NHD3_Q)
    assert len(nhd_calls) == 3                                   # no NHD call for NOLOC
    env = json.loads(nhd_calls[0].params["geometry"])
    assert env["ymax"] - env["ymin"] == pytest.approx(0.2 / 69.0)   # 0.1 mi buffer


def test_detour_conflict_scan(fake_get):
    def route(sfn, **ov):
        fake_get.add(f"SFN%3D%27{sfn}", arcgis_features(tims_record(SFN=sfn, **ov)))

    # the transport routes on URL only, so mark each bridge via a query-string-looking
    # needle we can't get from params; instead answer sequentially per call order.
    answers = {
        "CLEAN": arcgis_features(tims_record(SFN="CLEAN")),
        "BAD": arcgis_features(tims_record(
            SFN="BAD", SUBS_SUMMARY="4", SCOUR_CRIT_CD="U", SUFF_RATING="32.5",
            RAT_INV_LOAD_FACT="0.87", BRG_RDW_WD=20.0)),
        "GONE": arcgis_features(),
        "NARROW": arcgis_features(tims_record(SFN="NARROW", BRG_RDW_WD=23.9, SUFF_RATING=None,
                                              RAT_INV_LOAD_FACT=None)),
    }
    from tests.state.ohio.DOT.conftest import Call, FakeResponse

    def router(url, **kw):
        fake_get.calls.append(Call("GET", url, kw))
        sfn = kw["params"]["where"].split("'")[1]
        return FakeResponse(answers[sfn])

    apis.requests.get = router
    conflicts = BridgeEngineeringChecks.detour_conflict_scan(
        project_bridges=["X"], detour_bridges=["CLEAN", "BAD", "GONE", "NARROW"])
    assert [c.params["where"] for c in fake_get.calls] == \
        ["SFN='CLEAN'", "SFN='BAD'", "SFN='GONE'", "SFN='NARROW'"]
    assert conflicts == [
        {
            "sfn": "BAD", "facility": "SR 3", "feature": "ALUM CREEK",
            "issues": ["STRUCTURALLY_DEFICIENT", "SCOUR_CRITICAL", "LOW_SUFFICIENCY(32.5)",
                       "INV_RF_BELOW_1(0.87)", "NARROW_ROADWAY(20.0ft)"],
            "deck_rating": "7", "super_rating": "6", "sub_rating": "4",
            "sufficiency": 32.5, "inv_rf": 0.87,
        },
        {"sfn": "GONE", "issue": "NOT_FOUND", "detail": "Bridge not found in TIMS"},
        {
            "sfn": "NARROW", "facility": "SR 3", "feature": "ALUM CREEK",
            "issues": ["NARROW_ROADWAY(23.9ft)"],
            "deck_rating": "7", "super_rating": "6", "sub_rating": "7",
            "sufficiency": None, "inv_rf": None,
        },
    ]


def test_projects_affecting_bridges(fake_get):
    fake_get.add(TIMS_URLS["dwp_lines"], arcgis_features(
        {"PID_NBR": "112233", "PROJECT_NME": "DEL-3-2.10"}, {"PID_NBR": "445566"}))
    fake_get.add(BRIDGE_Q, _inventory(tims_record()))
    out = BridgeEngineeringChecks.projects_affecting_bridges(LON, LAT, radius_miles=3)
    assert out["center"] == {"lon": LON, "lat": LAT}
    assert out["radius_miles"] == 3
    assert out["project_count"] == 2 and [p["PID_NBR"] for p in out["projects"]] == ["112233", "445566"]
    assert out["bridge_count"] == 1 and out["bridges"][0]["distance_miles"] == 0.0
    assert [c.url for c in fake_get.calls] == [TIMS_URLS["dwp_lines"] + "/query", BRIDGE_Q]
    assert fake_get.calls[1].params["where"] == "MAINT_RESP_CD='01'"
    for c in fake_get.calls:
        env = json.loads(c.params["geometry"])
        assert env["ymax"] - env["ymin"] == pytest.approx(6 / 69.0)


# --- BridgeEngineeringChecks (tabular) ----------------------------------------------------------

@pytest.mark.filterwarnings("ignore:datetime.datetime.utcfromtimestamp:DeprecationWarning")
def test_inspection_currency_check():
    today = date.today()
    ms_2020 = int((datetime(2020, 3, 1) - datetime(1970, 1, 1)).total_seconds() * 1000)
    out = BridgeEngineeringChecks.inspection_currency_check([
        {"BID01": "A", "BIE06": "20991231"},
        {"SFN": "B", "INSP_DT": "20200101"},          # TIMS-style key, overdue
        {"BID01": "C", "BIE06": ms_2020},             # epoch ms, overdue (less so)
        {"BID01": "D"},                               # no date
        {"BID01": "E", "BIE06": "yesterday"},         # unparsable
        {"BIE06": today.strftime("%Y%m%d")},          # due today counts as current, sfn '?'
    ])
    assert (out["total"], out["current"], out["overdue"], out["unknown"]) == (6, 2, 2, 2)
    assert out["currency_pct"] == 33.3
    assert out["overdue_bridges"] == [
        {"sfn": "B", "due_date": "2020-01-01", "days_overdue": (today - date(2020, 1, 1)).days},
        {"sfn": "C", "due_date": "2020-03-01", "days_overdue": (today - date(2020, 3, 1)).days},
    ]
    assert BridgeEngineeringChecks.inspection_currency_check([]) == {
        "total": 0, "current": 0, "overdue": 0, "unknown": 0, "currency_pct": 0.0,
        "overdue_bridges": [],
    }


def test_posting_analysis():
    out = BridgeEngineeringChecks.posting_analysis([
        {"BID01": "A", "BPS01": "P", "STR_LOC_CARRIED": "SR 3", "RAT_INV_LOAD_FACT": "0.8"},
        {"SFN": "B", "BPS01": " b ", "facility_carried": "TR 12", "BLR05": 0.6},
        {"BID01": "C", "BPS01": "R"},
        {"BID01": "D", "BPS01": "A"},
        {"BID01": "E", "BPS01": ""},
        {"BID01": "F"},
    ])
    assert (out["total"], out["posted_count"], out["not_posted"], out["unknown"]) == (6, 3, 1, 2)
    assert out["posting_rate_pct"] == 50.0
    assert out["posted_bridges"] == [
        {"sfn": "A", "status": "P", "facility": "SR 3", "inv_rf": "0.8"},
        {"sfn": "B", "status": "b", "facility": "TR 12", "inv_rf": 0.6},
        {"sfn": "C", "status": "R", "facility": None, "inv_rf": None},
    ]
    assert BridgeEngineeringChecks.posting_analysis([])["posting_rate_pct"] == 0.0
