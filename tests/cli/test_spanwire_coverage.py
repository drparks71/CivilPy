#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``spanwire`` leftovers: malformed load/signal specs with the right
shape but wrong content, a system with no attachment loads (design-factor
floor), a solver error surfacing from a config, and a box in balance."""

import json

from civilpy.cli.batch import execute

from tests.cli.test_spanwire_commands import BOX_CONFIG


def test_load_spec_with_too_many_parts(capsys):
    assert execute(["spanwire", "simple", "100", "--sag", "5",
                    "--loads", "50:101:2:9"]) == 2
    assert "bad load spec '50:101:2:9'" in capsys.readouterr().out


def test_load_spec_with_non_numeric_weight(capsys):
    assert execute(["spanwire", "simple", "100", "--sag", "5",
                    "--loads", "50:heavy"]) == 2
    out = capsys.readouterr().out
    assert "bad load spec 'heavy'" not in out
    assert "bad load spec '50:heavy'" in out and "use x:weight[:area]" in out


def test_simple_span_with_wire_only_has_no_loads_table(tmp_path, capsys):
    out = tmp_path / "simple.csv"
    assert execute(["spanwire", "simple", "100", "--sag", "5",
                    "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "no attachment loads: design factor floor 1.8 used" in text
    assert "Loads" not in text.replace("no attachment loads", "")
    assert out.exists()                                   # single table → bare name
    assert not list(tmp_path.glob("simple_*.csv"))        # no 'Loads' table written


def test_signal_spec_with_non_numeric_position(capsys):
    assert execute(["spanwire", "simple", "100", "--sag", "5",
                    "--signals", "mid:3BA"]) == 2
    out = capsys.readouterr().out
    assert "bad signal spec 'mid:3BA'" in out and "use x:CODE" in out


def test_system_without_loads_uses_the_factor_floor(tmp_path, capsys):
    config = {
        "configuration": "custom",
        "poles": {"P1": [0, 0], "P2": [100, 0]},
        "segments": [{"name": "S1", "start": "P1", "end": "P2"}],
        "wire_weight_plf": 1.0,
        "required_sag_ft": 5.0,
    }
    p = tmp_path / "wire-only.json"
    p.write_text(json.dumps(config))
    assert execute(["spanwire", "system", str(p)]) == 0
    out = capsys.readouterr().out
    assert "no attachment loads: design factor floor 1.8 used" in out


def test_system_solver_error_becomes_cli_error(tmp_path, capsys):
    config = {
        "configuration": "custom",
        "poles": {"P1": [0, 0], "P2": [100, 0]},
        "segments": [{"name": "S1", "start": "P1", "end": "P2"}],
        "wire_weight_plf": 0.0,
        "required_sag_ft": 5.0,
    }
    p = tmp_path / "no-load.json"
    p.write_text(json.dumps(config))
    assert execute(["spanwire", "system", str(p)]) == 2
    assert "no load" in capsys.readouterr().out


def test_symmetric_box_is_reported_in_balance(tmp_path, capsys):
    config = dict(BOX_CONFIG, tail_bearings=[225, 315, 45, 135],
                  loads={"R1R2": [{"x_ft": 20, "weight_lb": 90, "area_sqft": 2.3}],
                         "R3R4": [{"x_ft": 20, "weight_lb": 90, "area_sqft": 2.3}]})
    p = tmp_path / "box.json"
    p.write_text(json.dumps(config))
    assert execute(["spanwire", "system", str(p)]) == 0
    out = capsys.readouterr().out
    assert "system is in balance" in out
    assert "rotate" not in out
