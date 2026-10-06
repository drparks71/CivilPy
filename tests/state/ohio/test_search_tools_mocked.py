#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""District 6 bridge lookup and plan-set tooling (civilpy.state.ohio.search_tools)
with every external dependency replaced.

The original ``tests/state/ohio/test_search_tools.py`` is entirely commented
out ("Removed to stop hitting TIMs API"), so the module had no coverage at
all. These tests feed ``D6BridgeLookup`` a local ``Bridges.tsv`` and
``PLANINDX.TXT`` written under ``tmp_path``, swap the module's ``os`` and
``tifftools`` references for recorders so nothing is written to the
hard-coded ``W:\\CivilPy_Output`` paths, build real single- and multi-page
TIFFs with Pillow for the PDF conversion, and answer the Overpass query
with a canned OSM JSON document. ``requests`` never reaches the network.
"""

from __future__ import annotations

import json
import math
import os
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from PIL import Image

from civilpy.state.ohio import search_tools as st
from civilpy.state.ohio.search_tools import D6BridgeLookup

SFN = 2102374


# ── fixtures: a local Bridges.tsv and PLANINDX.TXT ───────────────────────────
def _bridges_tsv(path, **overrides):
    """A two-row TIMS export. The spare row carries non-numeric text in the
    columns ``get_summary`` slices, so pandas keeps them as strings (as the
    real export, with its mixed values, does)."""
    cols = ["Structure File Number", "County Code", "Facility Carried By Structure",
            "Feature Intersected", "Latitude", "Longitude", "Inventory Route",
            "Straight Line Mileage"]
    row = {"Structure File Number": SFN, "County Code": "DEL",
           "Facility Carried By Structure": "I-71 NB",
           "Feature Intersected": "TR 105 (PLUMB RD.)",
           "Latitude": "400730500", "Longitude": "830215250",
           "Inventory Route": "SR00315", "Straight Line Mileage": "1234"}
    row.update(overrides)
    spare = {"Structure File Number": 1, "County Code": "FRA",
             "Facility Carried By Structure": "x", "Feature Intersected": "y",
             "Latitude": "none", "Longitude": "none", "Inventory Route": "none",
             "Straight Line Mileage": "none"}      # not "N/A": pandas would read that as NaN
    pd.DataFrame([row, spare], columns=cols).to_csv(path, sep="\t", index=False)
    return path


def _planindx(path, rows):
    """``PLANINDX.TXT`` as D6 keeps it: ``^``-delimited, ``~``-quoted."""
    cols = ["County_code", "Route", "Log_beg", "Log_end", "Yr", "Type", "Archno",
            "Commnt", "Path"]
    with open(path, "w") as fh:
        fh.write("^".join(cols) + "\n")
        for r in rows:
            fh.write("^".join(f"~{r[c]}~" for c in cols) + "\n")
    return path


@pytest.fixture
def bridge(tmp_path, capsys):
    b = D6BridgeLookup(SFN, data_path=str(_bridges_tsv(tmp_path / "Bridges.tsv")))
    capsys.readouterr()
    return b


# ── construction, coordinates, summary ──────────────────────────────────────
def test_lookup_reads_the_tsv_row_and_prints_a_summary(tmp_path, capsys):
    b = D6BridgeLookup(SFN, data_path=str(_bridges_tsv(tmp_path / "Bridges.tsv")))
    out = capsys.readouterr().out
    assert b.SFN == SFN and b.raw_data["County Code"] == "DEL"
    assert b.raw_data["Facility Carried By Structure"] == "I-71 NB"
    assert b.photo_url == "" and b.plan_sets_list == []
    # 40 deg 07' 30.500" N, 83 deg 02' 15.250" W
    assert b.clean_lat == pytest.approx(40 + 7 / 60 + 30.5 / 3600, abs=1e-9)
    assert b.clean_long == pytest.approx(-(83 + 2 / 60 + 15.25 / 3600), abs=1e-9)
    assert b.cty_rte_sec == "DEL-315-1.34"
    assert "Report for SFN: 2102374 (DEL - I-71 NB over TR 105 (PLUMB RD.))" in out
    assert "Latitude: 40.12514, Longitude: -83.03757" in out


def test_unknown_sfn_has_no_row(tmp_path):
    _bridges_tsv(tmp_path / "Bridges.tsv")
    with pytest.raises(IndexError):
        D6BridgeLookup(9999999, data_path=str(tmp_path / "Bridges.tsv"))


def test_parse_coordinates_handles_numeric_input():
    lat, lon = D6BridgeLookup._parse_coordinates(382112345, 830000000)
    assert lat == pytest.approx(38 + 21 / 60 + 12.345 / 3600)
    assert lon == pytest.approx(-83.0)


def test_summary_strips_route_prefix_and_zero_padding(tmp_path, capsys):
    b = D6BridgeLookup(SFN, data_path=str(_bridges_tsv(
        tmp_path / "Bridges.tsv", **{"Inventory Route": "US00023", "Straight Line Mileage": "0567"})))
    capsys.readouterr()
    assert b.get_summary() == "DEL-23-.67"          # leading zero of the mile is stripped too


# ── plan sets ───────────────────────────────────────────────────────────────
class FakeOS:
    """``os`` as search_tools sees it: real listdir, but the W:\\ output tree
    is simulated and every mkdir is recorded instead of created."""

    def __init__(self, existing=()):
        self.existing = set(existing)
        self.mkdirs = []
        self.path = SimpleNamespace(exists=lambda p: p in self.existing or os.path.exists(p),
                                    basename=os.path.basename)

    def listdir(self, p):
        return os.listdir(p)

    def mkdir(self, p):
        self.mkdirs.append(p)
        self.existing.add(p)


class FakeTiffTools:
    def __init__(self, write_error=None):
        self.written = []
        self.write_error = write_error

    def read_tiff(self, path):
        return {"ifds": [path.replace("\\", "/").rsplit("/", 1)[-1]]}   # sheet name as the IFD

    def write_tiff(self, info, path):
        if self.write_error:
            raise self.write_error
        self.written.append((path, list(info["ifds"])))


def _set_name(folder):
    """The name the module gives a merged set: it joins folder and file with
    a backslash, so on POSIX the "parent" is one level up from the folder."""
    from pathlib import Path
    return Path(f"{folder}\\sheet.tif").parent.name


OUT = f"W:\\CivilPy_Output\\pulled_plans\\{SFN}"


def _plan_folder(root, name, sheets):
    folder = root / name
    folder.mkdir()
    for s in sheets:
        (folder / s).write_bytes(b"II*\x00")
    (folder / "index.txt").write_text("not a tiff")
    return folder


@pytest.fixture
def plan_env(tmp_path, bridge, monkeypatch):
    """Two indexed plan sets for DEL-315 around mile 1.34, one for another
    county, one out of the mile range; ``Log_beg`` is kept as text by a
    non-numeric row the way the real index is."""
    f1 = _plan_folder(tmp_path, "1998_BR_A1", ["sheet10.tif", "sheet2.tif", "sheet1.TIF"])
    (tmp_path / "other").mkdir()
    f2 = _plan_folder(tmp_path / "other", "2004_RD_A2", ["p1.tif"])
    rows = [
        {"County_code": "DEL", "Route": "315", "Log_beg": "0", "Log_end": 2, "Yr": 1998,
         "Type": "BR", "Archno": "A1", "Commnt": "Bridge rehab", "Path": str(f1)},
        {"County_code": "DEL", "Route": "315", "Log_beg": "1", "Log_end": 3, "Yr": 2004,
         "Type": "RD", "Archno": "A2", "Commnt": "Resurfacing", "Path": str(f2)},
        {"County_code": "DEL", "Route": "315", "Log_beg": "5", "Log_end": 7, "Yr": 2010,
         "Type": "RD", "Archno": "A3", "Commnt": "too far north", "Path": "/nope"},
        {"County_code": "FRA", "Route": "71A", "Log_beg": "none", "Log_end": 9, "Yr": 2011,
         "Type": "RD", "Archno": "A4", "Commnt": "other county", "Path": "/nope"},
    ]
    index = _planindx(tmp_path / "PLANINDX.TXT", rows)
    fake_os, fake_tt = FakeOS(), FakeTiffTools()
    monkeypatch.setattr(st, "os", fake_os)
    monkeypatch.setattr(st, "tifftools", fake_tt)
    converted = []
    monkeypatch.setattr(bridge, "tiff_to_pdf", lambda p: converted.append(p))
    return SimpleNamespace(index=str(index), os=fake_os, tt=fake_tt, converted=converted,
                           f1=f1, f2=f2)


def test_plan_sets_are_filtered_merged_in_natural_order_and_written(bridge, plan_env, capsys):
    out = bridge.get_d6_plan_sets(district_df_path=plan_env.index)
    assert out == "Files written to W:\\CivilPy_Output\\pulled_plans\\"
    printed = capsys.readouterr().out
    assert "1998-BR-A1\nBridge rehab" in printed and "2004-RD-A2\nResurfacing" in printed
    assert "too far north" not in printed and "other county" not in printed
    # the output folder is created once per SFN, then reused
    assert plan_env.os.mkdirs == [OUT]
    # single-page tiffs merged into one multi-page file in natural (not lexical) order
    set1, set2 = _set_name(plan_env.f1), _set_name(plan_env.f2)
    assert plan_env.tt.written == [
        (f"{OUT}\\{set1}.tiff", ["sheet1.TIF", "sheet2.tif", "sheet10.tif"]),
        (f"{OUT}\\{set2}.tiff", ["p1.tif"])]
    assert plan_env.converted == [f"{OUT}\\{set1}.tiff", f"{OUT}\\{set2}.tiff"]


def test_existing_tiff_is_not_rewritten(bridge, plan_env, capsys):
    done = f"{OUT}\\{_set_name(plan_env.f1)}.tiff"
    plan_env.os.existing.update({OUT, done})
    bridge.get_d6_plan_sets(district_df_path=plan_env.index)
    assert plan_env.os.mkdirs == []
    assert [p for p, _ in plan_env.tt.written] == [f"{OUT}\\{_set_name(plan_env.f2)}.tiff"]
    assert done in plan_env.converted                 # conversion still attempted


def test_bad_tiff_and_failed_conversion_are_reported_not_raised(bridge, plan_env, monkeypatch, capsys):
    plan_env.tt.write_error = AttributeError("ifds")
    monkeypatch.setattr(bridge, "tiff_to_pdf", lambda p: (_ for _ in ()).throw(OSError("corrupt")))
    bridge.get_d6_plan_sets(district_df_path=plan_env.index)
    out = capsys.readouterr().out
    assert out.count("There is a problem with the tiff file") == 2
    assert out.count("possibly corrupted") == 2
    assert plan_env.tt.written == []


@pytest.mark.xfail(strict=True, reason="BUG: get_d6_plan_sets compares Log_beg to a str "
                   "and Route to a str; a cleanly numeric PLANINDX raises TypeError / matches nothing")
def test_plan_sets_with_a_numeric_index(bridge, tmp_path, monkeypatch, plan_env):
    rows = [{"County_code": "DEL", "Route": 315, "Log_beg": 0, "Log_end": 2, "Yr": 1998,
             "Type": "BR", "Archno": "A1", "Commnt": "Bridge rehab", "Path": str(plan_env.f1)}]
    index = _planindx(tmp_path / "NUMERIC.TXT", rows)
    bridge.get_d6_plan_sets(district_df_path=str(index))
    assert len(plan_env.tt.written) == 1


def test_get_tiff_files_lists_only_tiffs(bridge, tmp_path, capsys):
    folder = _plan_folder(tmp_path, "set", ["b.tif", "a.TIF", "c.tiff"])
    files = bridge.get_tiff_files(str(folder))
    assert sorted(files) == [f"{folder}\\a.TIF", f"{folder}\\b.tif"]      # .tiff is not .tif
    out = capsys.readouterr().out
    assert f"folder: {folder}" in out and f"{folder}\\b.tif" in out


# ── tiff -> pdf ─────────────────────────────────────────────────────────────
def _tiff(path, pages):
    frames = [Image.new("L", (8, 6), color=40 * i) for i in range(pages)]
    frames[0].save(path, save_all=True, append_images=frames[1:]) if pages > 1 else frames[0].save(path)
    return path


def test_tiff_to_pdf_single_and_multi_page(bridge, tmp_path):
    # Pillow's PDF writer reaches for Image.SAVE["JPEG"] directly; with lazy
    # plugin loading that key only exists once the registry is initialised
    Image.init()
    one = _tiff(tmp_path / "one.tiff", 1)
    pdf = bridge.tiff_to_pdf(str(one))
    assert pdf == str(tmp_path / "one.pdf") and os.path.getsize(pdf) > 0
    three = _tiff(tmp_path / "three.tiff", 3)
    pdf3 = bridge.tiff_to_pdf(str(three))
    with open(pdf3, "rb") as fh:
        data = fh.read()
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") == 3


def test_tiff_to_pdf_missing_file(bridge, tmp_path):
    with pytest.raises(Exception, match="Not found"):
        bridge.tiff_to_pdf(str(tmp_path / "nope.tiff"))


# ── Overpass ────────────────────────────────────────────────────────────────
OSM = {"version": 0.6, "elements": [
    {"type": "relation", "id": 1, "tags": {"ref": "10", "name": "SR 10", "network": "US:OH",
                                          "route": "road", "type": "route"}},
    {"type": "way", "id": 2, "tags": {"name": "Olentangy River", "waterway": "river"}},
    {"type": "relation", "id": 3, "tags": {"ref": "2;4", "name": "SR 2", "route": "road",
                                          "type": "route"}},
    {"type": "way", "id": 4, "tags": {"ref": "CSX", "railway": "rail", "name": "Main Line"}},
    {"type": "way", "id": 5, "tags": {"highway": "cycleway", "name": "Olentangy Trail",
                                     "bridge": "yes", "surface": "asphalt"}},
]}


class FakeResponse:
    def __init__(self, payload=None, status=200, json_error=False):
        self._payload, self.status_code, self._json_error = payload, status, json_error

    def json(self):
        if self._json_error:
            raise json.JSONDecodeError("bad", "", 0)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")


@pytest.fixture
def pandas_display():
    keys = ("display.max_rows", "display.max_columns", "display.width")
    saved = {k: pd.get_option(k) for k in keys}
    yield
    for k, v in saved.items():
        pd.set_option(k, v)


def test_osm_query_sorts_by_ref_and_keeps_preferred_columns(monkeypatch, capsys, pandas_display):
    calls = []

    def post(url, data=None, **kw):
        calls.append((url, data))
        return FakeResponse(json.loads(json.dumps(OSM)))
    monkeypatch.setattr(st.requests, "post", post)

    df = st.get_ohio_data_from_open_street_maps()
    url, query = calls[0]
    assert url == "https://overpass-api.de/api/interpreter"
    assert '[out:json][timeout:180];' in query and 'area["ISO3166-2"="US-OH"]->.ohio;' in query
    assert 'relation["type"="route"]["route"="road"](area.ohio);' in query
    assert query.strip().endswith("out tags;")
    assert list(df.columns) == ["ref", "name", "network", "route", "highway", "railway",
                                "waterway", "bridge", "type"]          # "surface" dropped
    # numeric refs first (2;4 -> 2 before 10), non-numeric refs after, in input order
    assert df["ref"].tolist() == ["2;4", "10", "", "CSX", ""]
    assert df["name"].tolist() == ["SR 2", "SR 10", "Olentangy River", "Main Line",
                                   "Olentangy Trail"]
    assert (df["network"] == "").sum() == 4                         # NaN -> ""
    assert pd.get_option("display.width") == 120
    assert "Found 5 features in Ohio" in capsys.readouterr().out


def test_osm_query_transport_and_decode_errors(monkeypatch, capsys, pandas_display):
    monkeypatch.setattr(st.requests, "post", lambda *a, **k: FakeResponse(status=504))
    assert st.get_ohio_data_from_open_street_maps() is None
    assert "An error occurred: 504" in capsys.readouterr().out
    monkeypatch.setattr(st.requests, "post", lambda *a, **k: FakeResponse(json_error=True))
    assert st.get_ohio_data_from_open_street_maps() is None
    assert "Failed to decode the response" in capsys.readouterr().out


def test_module_flag_and_label_list():
    assert st.test_init is True
    assert "Structure File Number" in st.default_bridge_labels
    assert len(st.default_bridge_labels) == len(set(st.default_bridge_labels)) == 306
    assert math.isfinite(D6BridgeLookup._parse_coordinates("400000000", "830000000")[0])
