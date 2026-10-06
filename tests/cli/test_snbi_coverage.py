#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``snbi validate`` input edge cases: a missing file, an empty array,
records that are not objects, and a single bare record."""

import csv
import json

import pytest

from civilpy.cli.batch import execute
from civilpy.cli.commands.snbi import _record_label

pytest.importorskip("pydantic")


def _record():
    from tests.state.ohio.test_snbi import make_bridge

    return make_bridge().model_dump(exclude_none=True)


def test_record_label_prefers_bid01():
    assert _record_label({"BID01": "SFN1234"}, 0) == "SFN1234"
    assert _record_label({"BID01": ""}, 0) == "record 1"
    assert _record_label(42, 4) == "record 5"


def test_missing_file(capsys):
    assert execute(["snbi", "validate", "nope.json"]) == 2
    assert "no such file" in capsys.readouterr().out


def test_empty_array_has_nothing_to_validate(tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text("[]")
    assert execute(["snbi", "validate", str(p)]) == 2
    assert "no bridge records to validate" in capsys.readouterr().out


def test_non_object_records_are_type_errors(tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "s.json"
    p.write_text(json.dumps([42, _record()]))
    out = tmp_path / "s.xlsx"
    assert execute(["snbi", "validate", str(p), "-o", str(out)]) == 1
    text = capsys.readouterr().out
    assert "record 1" in text and "not a JSON object" in text
    wb = openpyxl.load_workbook(out)
    summary = [c.value for c in wb["SNBI validation"][2]]
    assert summary == [2, 1, 1, 1]  # records, passed, failed, errors
    errors = [c.value for c in wb["Errors"][2]]
    assert errors == ["record 1", "(record)", "record is not a JSON object", "type"]


def test_single_bare_record_is_wrapped(tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_record()))
    out = tmp_path / "s.csv"
    assert execute(["snbi", "validate", str(p), "-o", str(out)]) == 0
    capsys.readouterr()
    with open(out, newline="") as fh:
        (row,) = list(csv.DictReader(fh))
    assert row == {"Records": "1", "Passed": "1", "Failed": "0", "Errors": "0"}
