#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``boring parse`` on a hole-less document and the whole of
``boring batch``: recursive discovery, malformed files reported as notes,
and the three ways a folder can fail."""

import pytest

from civilpy.cli.batch import execute

from tests.geotechnical.test_boring import DIGGS_FIXTURE
from tests.cli.test_session_coverage import NO_HOLE_FIXTURE, TWO_HOLE_FIXTURE


def test_parse_document_without_boreholes_exits_2(tmp_path, capsys):
    p = tmp_path / "empty.xml"
    p.write_text(NO_HOLE_FIXTURE)
    assert execute(["boring", "parse", str(p)]) == 2
    assert "empty.xml: no boreholes found" in capsys.readouterr().out


def test_parse_hole_without_tests_emits_only_the_header_table(tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    bare = TWO_HOLE_FIXTURE
    # keep only the second (test-less) hole by dropping the first borehole
    start = bare.index("<samplingFeature>")
    end = bare.index("</samplingFeature>") + len("</samplingFeature>")
    bare = bare[:start] + bare[end:]
    p = tmp_path / "bare.xml"
    p.write_text(bare)
    out = tmp_path / "bare.xlsx"
    assert execute(["boring", "parse", str(p), "-o", str(out)]) == 0
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Boreholes", "provenance"]
    assert wb["Boreholes"]["A2"].value == "B-002"


def test_batch_walks_subfolders_and_notes_malformed_files(tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    folder = tmp_path / "logs"
    (folder / "site-a").mkdir(parents=True)
    (folder / "site-a" / "B-001.xml").write_text(DIGGS_FIXTURE)
    (folder / "B-002.xml").write_text(
        TWO_HOLE_FIXTURE.replace("B-001-0-21", "B-101"))
    (folder / "malformed.xml").write_text("<Diggs><unterminated>")
    out = tmp_path / "batch.xlsx"
    assert execute(["boring", "batch", str(folder), "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "skipped malformed.xml" in text
    wb = openpyxl.load_workbook(out)
    ids = [wb["Boreholes"].cell(row=r, column=1).value for r in range(2, 5)]
    assert sorted(ids) == ["B-001-0-21", "B-002", "B-101"]
    notes = [c.value for row in wb["Boreholes"].iter_rows() for c in row
             if isinstance(c.value, str) and c.value.startswith("Note:")]
    assert len(notes) == 1 and "malformed.xml" in notes[0]
    prov = [row[1].value for row in wb["provenance"].iter_rows()
            if row[0].value == "input file"]
    assert len(prov) == 3  # every discovered file, including the bad one


def test_batch_not_a_folder(tmp_path, capsys):
    assert execute(["boring", "batch", str(tmp_path / "nope")]) == 2
    assert "not a folder" in capsys.readouterr().out


def test_batch_folder_without_xml(tmp_path, capsys):
    (tmp_path / "readme.txt").write_text("x")
    assert execute(["boring", "batch", str(tmp_path)]) == 2
    assert "no .xml files under" in capsys.readouterr().out


def test_batch_only_malformed_files(tmp_path, capsys):
    (tmp_path / "bad.xml").write_text("<Diggs><unterminated>")
    assert execute(["boring", "batch", str(tmp_path)]) == 2
    assert "no boreholes parsed from any file" in capsys.readouterr().out
