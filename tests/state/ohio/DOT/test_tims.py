#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT TIMS access (civilpy.state.ohio.DOT.TIMS) against mocked transports.

Checks the exact ArcGIS REST requests the module sends (layer metadata,
paged ``/query`` POSTs, the per-SFN GET), how feature sets become
DataFrames / ``TIMSBridge`` attributes / the legacy ``TimsBridge`` and
``Project`` records, every error branch, the ``__repr__`` code
translations, and the plan-sheet label tables and file-name patterns
folded in from the retired ``legacy.py``. Nothing here opens a socket:
``requests.get`` / ``requests.post`` / ``requests.Session`` are replaced
with recorders fed payloads from :mod:`tims_payloads`.

The legacy ``gis.dot.state.oh.us`` scrapers reference ``BeautifulSoup``,
``OrderedDict`` and ``os`` without importing them; those are pinned as
strict xfails, and their parsing logic is exercised separately with the
missing names injected into the module namespace.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
import bs4
import pandas as pd
import pytest
import requests

from civilpy.state.ohio.DOT import TIMS

from .tims_payloads import (
    BRIDGE_KEYS, PROJECT_KEYS, arcgis_error, bridge_attributes, feature_set,
    html_id_listing, layer_metadata, pjson_feature, project_attributes,
)

BRIDGE_QUERY = ("https://tims.dot.state.oh.us/ags/rest/services/Assets/"
                "Bridge_Inventory/MapServer/0/query")
ROADWAY_LAYER = ("https://tims.dot.state.oh.us/ags/rest/services/"
                 "Roadway_Information/Road_Inventory/MapServer/0")


class FakeResponse:
    def __init__(self, payload=None, status=200, content=None, json_error=False):
        self._payload = payload
        self.status_code = status
        self.content = content if content is not None else json.dumps(payload or {}).encode()
        self.text = self.content.decode()
        self._json_error = json_error

    def json(self, **kw):
        if self._json_error:
            raise json.JSONDecodeError("bad", "x", 0)
        if kw.get("object_pairs_hook"):
            return json.loads(self.content, object_pairs_hook=kw["object_pairs_hook"])
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


class Recorder:
    """Stands in for ``requests.get`` / ``requests.post``: serves queued
    responses in order and keeps every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ── get_tims_data ───────────────────────────────────────────────────────────
class TestGetTimsData:
    def test_pages_through_the_layer_and_builds_a_dataframe(self, monkeypatch, capsys):
        get = Recorder(FakeResponse(layer_metadata(["OBJECTID", "SFN", "COUNTY_CD"])))
        rows1 = [{"OBJECTID": 1, "SFN": "0100013", "COUNTY_CD": "ATH"},
                 {"OBJECTID": 2, "SFN": "0100021", "COUNTY_CD": "ATH"}]
        post = Recorder(FakeResponse(feature_set(rows1)), FakeResponse(feature_set([])))
        monkeypatch.setattr(TIMS.requests, "get", get)
        monkeypatch.setattr(TIMS.requests, "post", post)

        df = TIMS.get_tims_data("Bridge", where="COUNTY_CD='ATH'")

        assert get.calls[0][0] == BRIDGE_QUERY.replace("/query", "") + "?f=json"
        assert [c[0] for c in post.calls] == [BRIDGE_QUERY, BRIDGE_QUERY]
        p0, p1 = post.calls[0][1]["data"], post.calls[1][1]["data"]
        assert p0 == {"where": "COUNTY_CD='ATH'", "outFields": "OBJECTID,SFN,COUNTY_CD",
                      "resultOffset": 0, "resultRecordCount": 1000,
                      "returnGeometry": False, "f": "json"}
        assert p1["resultOffset"] == 1000                 # one batch size further
        assert list(df.columns) == ["OBJECTID", "SFN", "COUNTY_CD"]
        assert df["SFN"].tolist() == ["0100013", "0100021"]
        out = capsys.readouterr().out
        assert "Fetched 2 records. Total so far: 2" in out
        assert "No more features found. Fetched 1000 total records." in out
        assert "shape: (2, 3)" in out

    def test_default_source_is_the_roadway_layer(self, monkeypatch):
        get = Recorder(FakeResponse(layer_metadata(["NLF_ID"])))
        post = Recorder(FakeResponse(feature_set([{"NLF_ID": "SFRAIR00071**C"}])),
                        FakeResponse(feature_set([])))
        monkeypatch.setattr(TIMS.requests, "get", get)
        monkeypatch.setattr(TIMS.requests, "post", post)
        df = TIMS.get_tims_data()
        assert get.calls[0][0] == ROADWAY_LAYER + "?f=json"
        assert post.calls[0][1]["data"]["where"] == "1=1"
        assert df.iloc[0]["NLF_ID"] == "SFRAIR00071**C"

    def test_http_error_stops_paging_but_keeps_what_was_fetched(self, monkeypatch, capsys):
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(layer_metadata(["SFN"]))))
        monkeypatch.setattr(TIMS.requests, "post", Recorder(
            FakeResponse(feature_set([{"SFN": "1"}])), FakeResponse(status=503)))
        df = TIMS.get_tims_data("Bridge")
        assert df["SFN"].tolist() == ["1"]
        assert "HTTP Error: 503 error" in capsys.readouterr().out

    def test_generic_error_is_reported_and_stops(self, monkeypatch, capsys):
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(layer_metadata(["SFN"]))))
        monkeypatch.setattr(TIMS.requests, "post", Recorder(
            FakeResponse(feature_set([{"SFN": "1"}])), ConnectionError("reset by peer")))
        df = TIMS.get_tims_data("Bridge")
        assert len(df) == 1
        assert "An error occurred: reset by peer" in capsys.readouterr().out

    def test_unknown_layer_name_rejected(self):
        with pytest.raises(KeyError):
            TIMS.get_tims_data("Culverts")

    @pytest.mark.xfail(strict=True, reason="BUG: get_tims_data returns the unbound local "
                       "`df` (UnboundLocalError) when no records match; the docstring "
                       "promises an empty DataFrame")
    def test_no_records_gives_an_empty_dataframe(self, monkeypatch):
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(layer_metadata(["SFN"]))))
        monkeypatch.setattr(TIMS.requests, "post", Recorder(FakeResponse(feature_set([]))))
        df = TIMS.get_tims_data("Bridge", where="SFN='0000000'")
        assert isinstance(df, pd.DataFrame) and df.empty


# ── TIMSBridge ──────────────────────────────────────────────────────────────
class TestTIMSBridge:
    def test_fetch_sends_the_sfn_query_and_lowercases_attributes(self, monkeypatch):
        get = Recorder(FakeResponse(feature_set([bridge_attributes()])))
        monkeypatch.setattr(TIMS.requests, "get", get)
        b = TIMS.TIMSBridge("2102374")
        url, kw = get.calls[0]
        assert url == TIMS.TIMSBridge._API_URL == BRIDGE_QUERY
        assert kw["params"] == {"where": "SFN = '2102374'", "outFields": "*", "f": "json",
                                "returnGeometry": "true", "resultRecordCount": 1}
        assert kw["timeout"] == 30
        assert b.sfn == "2102374" and b.str_loc_carried == "I-71 NB"
        assert b.latitude_dd == 40.209175 and b.county_cd == "DEL"
        assert not hasattr(b, "STR_LOC_CARRIED")

    def test_no_feature_is_a_value_error(self, monkeypatch):
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(feature_set([]))))
        with pytest.raises(ValueError, match="No bridge found with SFN '0000000'"):
            TIMS.TIMSBridge("0000000")

    def test_api_error_document_is_a_runtime_error(self, monkeypatch):
        monkeypatch.setattr(TIMS.requests, "get",
                            Recorder(FakeResponse(arcgis_error(400, "Invalid query"))))
        with pytest.raises(RuntimeError, match="TIMS/ArcGIS API error: .*Invalid query"):
            TIMS.TIMSBridge("2102374")

    def test_transport_failures_are_wrapped(self, monkeypatch):
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(status=502)))
        with pytest.raises(RuntimeError, match="Network error fetching bridge data for SFN '2102374'"):
            TIMS.TIMSBridge("2102374")
        monkeypatch.setattr(TIMS.requests, "get",
                            Recorder(requests.exceptions.ConnectionError("down")))
        with pytest.raises(RuntimeError, match="down"):
            TIMS.TIMSBridge("2102374")

    def test_repr_translates_codes_dates_and_links(self, monkeypatch):
        monkeypatch.setattr(TIMS.requests, "get",
                            Recorder(FakeResponse(feature_set([bridge_attributes()]))))
        text = repr(TIMS.TIMSBridge("2102374"))
        assert "<TIMSBridge SFN: '2102374'>" in text
        assert "Route Carried: I-71 NB" in text
        assert "NLFID:         SDELIR00071**C" in text
        assert "Location:      DEL County, District 06" in text
        assert "https://www.google.com/maps?q=40.209175,-82.930444" in text
        assert "Year Built:    1959" in text                # negative epoch handled
        assert "Material/Type: Steel Continuous / Stringer/Multi-beam or Girder (4/02)" in text
        assert "Sufficiency:   84.3" in text and "Deck:          6" in text

    def test_repr_falls_back_for_missing_or_odd_fields(self, monkeypatch):
        sparse = {"SFN": "0000001", "YR_BUILT": "unknown", "MAIN_STR_MTL_CD": "X"}
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(feature_set([sparse]))))
        text = repr(TIMS.TIMSBridge("0000001"))
        assert "Year Built:    unknown" in text             # TypeError path keeps the raw value
        assert "Material/Type: Unknown / Unknown (X/N/A)" in text
        assert "Route Carried: N/A" in text
        assert "maps?q=0,0" in text

    def test_repr_with_no_year(self, monkeypatch):
        monkeypatch.setattr(TIMS.requests, "get",
                            Recorder(FakeResponse(feature_set([bridge_attributes(YR_BUILT=None)]))))
        assert "Year Built:    N/A" in repr(TIMS.TIMSBridge("2102374"))


# ── get_bridge_sfns_by_district ─────────────────────────────────────────────
class TestBridgeSfnsByDistrict:
    def test_district_filter_is_zero_padded(self, monkeypatch, capsys):
        get = Recorder(FakeResponse(feature_set([{"SFN": "2102374"}, {"SFN": "2100134"},
                                                 {"OBJECTID": 3}])))
        monkeypatch.setattr(TIMS.requests, "get", get)
        out = TIMS.get_bridge_sfns_by_district(6)
        url, kw = get.calls[0]
        assert url == BRIDGE_QUERY
        assert kw["params"] == {"where": "DISTRICT = '06'", "outFields": "SFN",
                                "returnGeometry": "false", "f": "json"}
        assert kw["timeout"] == 30
        assert out == ["2102374", "2100134"]              # the row without SFN is skipped
        assert "Querying API for District 06" in capsys.readouterr().out

    @pytest.mark.parametrize("district", [None, 0, 13])
    def test_out_of_range_or_missing_district_queries_everything(self, monkeypatch, district):
        get = Recorder(FakeResponse(feature_set([{"SFN": "1"}])))
        monkeypatch.setattr(TIMS.requests, "get", get)
        assert TIMS.get_bridge_sfns_by_district(district) == ["1"]
        assert get.calls[0][1]["params"]["where"] == "1=1"

    def test_custom_url(self, monkeypatch):
        get = Recorder(FakeResponse(feature_set([{"SFN": "1"}])))
        monkeypatch.setattr(TIMS.requests, "get", get)
        TIMS.get_bridge_sfns_by_district(12, url="http://127.0.0.1/q")
        assert get.calls[0][0] == "http://127.0.0.1/q"
        assert get.calls[0][1]["params"]["where"] == "DISTRICT = '12'"

    def test_api_error_and_empty_results_give_empty_list(self, monkeypatch, capsys):
        monkeypatch.setattr(TIMS.requests, "get",
                            Recorder(FakeResponse(arcgis_error(400, "Invalid field"))))
        assert TIMS.get_bridge_sfns_by_district(1) == []
        assert "API returned an error: Invalid field" in capsys.readouterr().out
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(feature_set([]))))
        assert TIMS.get_bridge_sfns_by_district(1) == []
        assert "no features were found" in capsys.readouterr().out

    def test_transport_json_and_key_errors_are_swallowed(self, monkeypatch, capsys):
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(status=500)))
        assert TIMS.get_bridge_sfns_by_district(2) == []
        assert "An error occurred during the API request" in capsys.readouterr().out
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse(json_error=True)))
        assert TIMS.get_bridge_sfns_by_district(2) == []
        assert "Could not decode the response" in capsys.readouterr().out
        # an error document without a message -> KeyError branch
        monkeypatch.setattr(TIMS.requests, "get", Recorder(FakeResponse({"error": {"code": 500}})))
        assert TIMS.get_bridge_sfns_by_district(2) == []
        assert "missing the 'SFN' field" in capsys.readouterr().out


# ── legacy scrapers (gis.dot.state.oh.us) ───────────────────────────────────
class FakeSession:
    """``requests.Session`` stand-in: serves queued responses to ``get``."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = 0

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)

    def close(self):
        self.closed += 1


def _inject_missing_names(monkeypatch):
    """The legacy scrapers use names the module never imports; give them
    the real objects (bs4's own parser, since html5lib is not installed)."""
    monkeypatch.setattr(TIMS, "BeautifulSoup",
                        lambda content, parser: bs4.BeautifulSoup(content, "html.parser"),
                        raising=False)
    monkeypatch.setattr(TIMS, "OrderedDict", OrderedDict, raising=False)


@pytest.mark.xfail(strict=True, reason="BUG: TIMS.get_bridge_data_from_tims calls "
                   "BeautifulSoup, which TIMS.py never imports (NameError)")
def test_get_bridge_data_from_tims_as_written(monkeypatch):
    session = FakeSession(
        FakeResponse(content=html_id_listing(["/arcgis/rest/services/TIMS/Assets/MapServer/5/9001"])),
        FakeResponse(content=pjson_feature({"SFN": "6500609"})))
    monkeypatch.setattr(TIMS.requests, "Session", lambda: session)
    assert TIMS.get_bridge_data_from_tims("6500609") == {"SFN": "6500609"}


def test_get_bridge_data_from_tims_scrapes_the_last_link(monkeypatch, capsys):
    _inject_missing_names(monkeypatch)
    attrs = {"SFN": "6500609", "COUNTY_CD": "ROS"}
    session = FakeSession(
        FakeResponse(content=html_id_listing(["/arcgis/rest/services/TIMS/Assets/MapServer/5/9000",
                                              "/arcgis/rest/services/TIMS/Assets/MapServer/5/9001"])),
        FakeResponse(content=pjson_feature(attrs)))
    monkeypatch.setattr(TIMS.requests, "Session", lambda: session)

    assert TIMS.get_bridge_data_from_tims("6500609") == attrs
    first_url, first_kw = session.calls[0]
    assert first_url.startswith("https://gis.dot.state.oh.us/arcgis/rest/services/TIMS/Assets/"
                                "MapServer/5/query?where=sfn%3D6500609&")
    assert "returnIdsOnly=true" in first_url and first_url.endswith("f=html")
    assert first_kw == {"timeout": 5}
    assert session.calls[1][0] == ("https://gis.dot.state.oh.us//arcgis/rest/services/TIMS/"
                                   "Assets/MapServer/5/9001?f=pjson")
    assert session.closed == 2
    assert "Retrieving data from url at" in capsys.readouterr().out


@pytest.mark.xfail(strict=True, reason="BUG: TIMS.get_project_data_from_tims calls "
                   "BeautifulSoup/OrderedDict, which TIMS.py never imports (NameError)")
def test_get_project_data_from_tims_as_written(monkeypatch):
    session = FakeSession(FakeResponse(content=html_id_listing([])))
    monkeypatch.setattr(TIMS.requests, "Session", lambda: session)
    assert TIMS.get_project_data_from_tims("96213") == {"no_of_pts": 0}


def test_get_project_data_from_tims_collects_numeric_links(monkeypatch):
    _inject_missing_names(monkeypatch)
    p1, p2 = project_attributes(ObjectID=1), project_attributes(ObjectID=2)
    session = FakeSession(
        FakeResponse(content=html_id_listing(["/arcgis/rest/services/TIMS/Projects/MapServer/0/41",
                                              "/arcgis/rest/services/TIMS/Projects/MapServer/0/42"])),
        FakeResponse(content=pjson_feature(p1)),
        FakeResponse(content=pjson_feature(p2)))
    monkeypatch.setattr(TIMS.requests, "Session", lambda: session)

    out = TIMS.get_project_data_from_tims("96213")
    assert out["no_of_pts"] == 2
    assert list(out) == ["41", "42", "no_of_pts"]
    assert isinstance(out["41"], OrderedDict) and out["41"]["ObjectID"] == 1
    assert list(out["42"]) == list(PROJECT_KEYS)              # field order preserved
    assert session.calls[0][0].startswith("https://gis.dot.state.oh.us/arcgis/rest/services/"
                                          "TIMS/Projects/MapServer/0/query?where=PID_NBR%3D96213&")
    assert session.calls[1][0] == ("https://gis.dot.state.oh.us/arcgis/rest/services/TIMS/"
                                   "Projects/MapServer/0/41?f=pjson")
    # the breadcrumb links (non-numeric text) were ignored
    assert len(session.calls) == 3


def test_get_project_data_from_tims_returns_raw_document_when_shape_is_wrong(monkeypatch):
    _inject_missing_names(monkeypatch)
    session = FakeSession(
        FakeResponse(content=html_id_listing(["/arcgis/rest/services/TIMS/Projects/MapServer/0/41"])),
        FakeResponse(content=json.dumps({"error": {"code": 500}}).encode()))
    monkeypatch.setattr(TIMS.requests, "Session", lambda: session)
    assert TIMS.get_project_data_from_tims("96213") == {"error": {"code": 500}}


@pytest.mark.xfail(strict=True, reason="BUG: get_project_data_from_tims concatenates url_3 "
                   "twice, duplicating the relationParam..returnGeometry query fragment")
def test_get_project_data_url_has_no_duplicated_parameters(monkeypatch):
    _inject_missing_names(monkeypatch)
    session = FakeSession(FakeResponse(content=html_id_listing([])))
    monkeypatch.setattr(TIMS.requests, "Session", lambda: session)
    TIMS.get_project_data_from_tims("96213")
    url = session.calls[0][0]
    assert url.count("returnGeometry=") == 1


# ── TimsBridge / Project records ────────────────────────────────────────────
def test_tims_bridge_record_maps_every_column_and_builds_a_map(monkeypatch, capsys):
    monkeypatch.setattr(TIMS, "get_bridge_data_from_tims",
                        lambda sfn: bridge_attributes(SFN=sfn))
    b = TIMS.TimsBridge("2102374")
    assert b.SFN == b.sfn == "2102374"
    assert b.latitude == b.latitude_dd == 40.209175
    assert b.longitude == -82.930444
    assert b.str_loc_carried == "I-71 NB" and b.yr_built == -331516800000
    for key in BRIDGE_KEYS:
        assert hasattr(b, key.lower()), key
    assert b.plan_sets_list == [] and b.photo_url == ""
    import folium
    assert isinstance(b.map, folium.Map)
    assert b.map.location == [40.209175, -82.930444]
    html = b.map.get_root().render()
    assert "2102374" in html and "Lat: 40.209175" in html
    assert "TIMS Bridge Initiated" in capsys.readouterr().out


def test_tims_bridge_record_requires_every_column(monkeypatch):
    row = bridge_attributes()
    del row["DECK_AREA"]
    monkeypatch.setattr(TIMS, "get_bridge_data_from_tims", lambda sfn: row)
    with pytest.raises(KeyError, match="DECK_AREA"):
        TIMS.TimsBridge("2102374")


def test_project_record_uses_the_first_point(monkeypatch):
    pts = {"41": project_attributes(ObjectID=41, PROJECT_NME="DEL-71-12.34"),
           "42": project_attributes(ObjectID=42, PROJECT_NME="other"), "no_of_pts": 2}
    monkeypatch.setattr(TIMS, "get_project_data_from_tims", lambda pid: pts)
    p = TIMS.Project("96213")
    assert p.PID == "96213" and p.objectid == 41 and p.pid_nbr == 96213
    assert p.project_nme == "DEL-71-12.34" and p.county_nme == "DELAWARE"
    assert p.structure_file_nbr == "2102374"
    for key in PROJECT_KEYS:
        assert hasattr(p, key.lower()), key


# ── state codes ─────────────────────────────────────────────────────────────
def test_state_code_lookups():
    assert TIMS.get_3_digit_st_cd_from_2("39") == "395"
    assert TIMS.get_3_digit_st_cd_from_2(39) == "395"
    assert TIMS.get_3_digit_st_cd_from_2("99") == "99"            # unknown passes through
    assert TIMS.state_code_conversion("39") == "Ohio"
    assert TIMS.state_code_conversion(39) == "Ohio"
    assert TIMS.state_code_conversion("395") == "Ohio"
    assert TIMS.state_code_conversion("543") == "West Virginia"
    with pytest.raises(KeyError):
        TIMS.state_code_conversion("000")


# ── label tables, file patterns, county tables ──────────────────────────────
def test_label_tables_are_complete_and_consistent():
    assert TIMS.help_function() is None
    assert set(TIMS.all_labels) == {
        "basemap_labels", "bridge_labels", "drainage_labels", "geotechnical_labels",
        "landscaping_labels", "lighting_labels", "mot_labels", "row_labels",
        "roadway_labels", "signal_labels", "traffic_control_labels", "utility_labels",
        "wall_labels"}
    assert TIMS.all_labels["bridge_labels"] is TIMS.bridge_labels
    assert TIMS.basemap_labels["BA"] == "Aerial Mapping"
    assert TIMS.bridge_labels["SG"] == "General Plan"
    for name, table in TIMS.all_labels.items():
        assert all(len(k) == 2 and k.isupper() for k in table), name
        assert len(set(table.values())) == len(table), f"duplicate label text in {name}"


@pytest.mark.parametrize("pattern, good, bad", [
    (TIMS.gen_file_pattern, "96213_GP001.dgn", "96213_GP01.dgn"),
    (TIMS.gen_file_pattern, "123456_BA012.dgn", "1234_BA012.dgn"),
    (TIMS.bridge_file_pattern, "96213_SFN2102374_SG001.dgn", "96213_SFN210237_SG001.dgn"),
    (TIMS.culvert_file_pattern, "96213_CFN2102374_DC001.dgn", "96213_SFN2102374_DC001.dgn"),
    (TIMS.wall_file_pattern, "96213_WALL001_WP001.dgn", "96213_WALL1_WP001.dgn"),
])
def test_file_name_patterns(pattern, good, bad):
    assert pattern.search(good)
    assert not pattern.search(bad)
    assert not pattern.search(good + ".bak")


@pytest.mark.xfail(strict=True, reason="BUG: filter_files_by_category uses os.path.basename "
                   "but TIMS.py never imports os (NameError)")
def test_filter_files_by_category_as_written():
    files = ["C:/proj/96213_SFN2102374_SG001.dgn", "C:/proj/EngData/96213_SFN2102374_SG002.dgn",
             "C:/proj/96213_GP001.dgn"]
    assert TIMS.filter_files_by_category(files, TIMS.bridge_labels) == \
        ["C:/proj/96213_SFN2102374_SG001.dgn"]


def test_filter_files_by_category_logic_with_os_injected(monkeypatch):
    import os
    monkeypatch.setattr(TIMS, "os", os, raising=False)
    files = ["C:/proj/96213_SFN2102374_SG001.dgn",
             "C:/proj/EngData/96213_SFN2102374_SG002.dgn",      # reference folder dropped
             "C:/proj/96213_GP001.dgn",                        # roadway sheet, not a bridge label
             "C:/proj/96213_SFN2102374_SD001.dgn"]
    out = TIMS.filter_files_by_category(files, TIMS.bridge_labels)
    assert set(out) == {"C:/proj/96213_SFN2102374_SG001.dgn", "C:/proj/96213_SFN2102374_SD001.dgn"}
    # matching is by substring, so the "SFN" token also hits the "SF" (Forward
    # Abutment) label and every bridge file is listed once per label it contains
    assert len(out) == 4
    assert TIMS.filter_files_by_category(files, TIMS.roadway_labels) == ["C:/proj/96213_GP001.dgn"]


def test_county_tables_cover_all_88_counties():
    by_district = [c for cs in TIMS.odot_counties_by_district.values() for c in cs]
    assert len(by_district) == 88 and len(set(by_district)) == 88
    assert set(by_district) == set(TIMS.ohio_counties)
    assert sorted(TIMS.odot_counties_by_district) == list(range(1, 13))
    assert TIMS.ohio_counties["DELAWARE"] == "DEL" and TIMS.ohio_counties["VAN WERT"] == "VAN"
    assert len(set(TIMS.ohio_counties.values())) == 88
    assert all(re.fullmatch(r"[A-Z]{3}", v) for v in TIMS.ohio_counties.values())
    assert TIMS.NBIS_state_codes["395"] == "Ohio"
    assert TIMS.NBI_MATERIAL_CODES["5"] == "Prestressed Concrete"
    assert TIMS.NBI_DESIGN_TYPE_CODES["19"] == "Culvert"
