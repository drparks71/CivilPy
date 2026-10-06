#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.db_tables`.

The module bootstraps a Django project (settings auto-detection, sys.path,
``DJANGO_ALLOW_ASYNC_UNSAFE``) and then validates every ``bridges.models.Bridge``
row against the Pydantic SNBI model, writing a per-field error log. Django is
not installed in the test environment and no real database is touched: the
``django`` and ``bridges`` packages are stubbed in ``sys.modules`` and the
Django queryset is a fake iterator. The validator model is a small Pydantic
stand-in so the mapping and error-accounting logic can be checked exactly.
"""

import json
import os
import sys
import types
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from civilpy.state.ohio import db_tables
from civilpy.state.ohio import snbi as real_snbi  # imported before any sys.modules stubbing


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def fake_django(monkeypatch):
    """A ``django`` module whose ``setup`` is a mock."""
    mod = types.ModuleType("django")
    mod.setup = MagicMock(name="django.setup")
    monkeypatch.setitem(sys.modules, "django", mod)
    return mod


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.delenv("DJANGO_ALLOW_ASYNC_UNSAFE", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))


def _project(tmp_path, *settings_dirs):
    root = tmp_path / "proj"
    root.mkdir()
    for d in settings_dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "settings.py").write_text("")
    return root


# --------------------------------------------------------------------------- #
# setup_django_environment
# --------------------------------------------------------------------------- #

def test_missing_project_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Project path does not exist"):
        db_tables.setup_django_environment(tmp_path / "nowhere")


def test_autodetects_single_settings_module(tmp_path, fake_django, clean_env, capsys):
    root = _project(tmp_path, "mysite")
    db_tables.setup_django_environment(root)
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "mysite.settings"
    assert os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] == "true"
    assert sys.path[0] == str(root.resolve())
    fake_django.setup.assert_called_once_with()
    out = capsys.readouterr().out
    assert "Auto-detected Django settings: mysite.settings" in out
    assert "Django configured successfully" in out


def test_nested_settings_module_uses_dotted_path(tmp_path, fake_django, clean_env):
    root = _project(tmp_path, os.path.join("apps", "config"))
    db_tables.setup_django_environment(root)
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "apps.config.settings"


def test_prefers_core_settings_when_several_found(tmp_path, fake_django, clean_env):
    root = _project(tmp_path, "aaa", "core", "zzz")
    db_tables.setup_django_environment(root)
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "core.settings"


def test_settings_in_project_root_is_skipped_and_defaults(tmp_path, fake_django, clean_env, capsys):
    root = _project(tmp_path, ".")
    db_tables.setup_django_environment(root)
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "core.settings"
    assert "Could not auto-detect settings.py. Defaulting to 'core.settings'" in capsys.readouterr().out


def test_preset_settings_module_is_respected(tmp_path, fake_django, clean_env, monkeypatch, capsys):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "explicit.settings")
    root = _project(tmp_path, "core")
    db_tables.setup_django_environment(root)
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "explicit.settings"
    assert "Auto-detected" not in capsys.readouterr().out


def test_sys_path_not_duplicated(tmp_path, fake_django, clean_env):
    root = _project(tmp_path, "core")
    db_tables.setup_django_environment(root)
    db_tables.setup_django_environment(root)
    assert sys.path.count(str(root.resolve())) == 1


def test_django_setup_failure_exits_1(tmp_path, fake_django, clean_env, capsys):
    fake_django.setup.side_effect = RuntimeError("no settings")
    with pytest.raises(SystemExit) as exc:
        db_tables.setup_django_environment(_project(tmp_path, "core"))
    assert exc.value.code == 1
    assert "Failed to setup Django: no settings" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# validate_bridge_data
# --------------------------------------------------------------------------- #

class _Row:
    """A Django ``Bridge`` row with every column the mapper reads."""

    _COLUMNS = [
        "bid01_bridge_number", "bid02_bridge_name", "bid03_prev_bridge_number",
        "bl01_state_code", "bl02_county_code", "bl03_place_code", "bl04_highway_district",
        "bl05_latitude", "bl06_longitude", "bl07_border_bridge_num", "bl08_border_state_code",
        "bl09_border_insp_resp", "bl10_border_lead_state", "bl11_bridge_location", "bl12_mpo",
        "bcl01_owner", "bcl02_maint_resp", "bcl03_land_access", "bcl04_historic_sig",
        "bcl05_toll", "bcl06_emerg_evac", "brh01_railings", "brh02_transitions",
        "bg01_nbis_len", "bg02_total_len", "bg03_max_span_len", "bg04_min_span_len",
        "bg05_width_out_to_out", "bg06_width_curb_to_curb", "bg07_left_curb_width",
        "bg08_right_curb_width", "bg09_appr_road_width", "bg10_median", "bg11_skew",
        "bg12_curved", "bg13_max_height", "bg14_sidehill", "bg15_irregular_area",
        "bg16_calc_deck_area", "blr01_design_load", "blr02_design_method", "blr03_load_date",
        "blr04_rating_method", "blr05_inv_factor", "blr06_opr_factor", "blr07_legal_factor",
        "blr08_permit_loads", "bir01_nstm_req", "bir02_fatigue", "bir03_underwater_req",
        "bir04_complex_feature", "bc01_deck_cond", "bc02_super_cond", "bc03_sub_cond",
        "bc04_culvert_cond", "bc05_rail_cond", "bc06_trans_cond", "bc07_bearing_cond",
        "bc08_joint_cond", "bc09_channel_cond", "bc10_prot_cond", "bc11_scour_cond",
        "bc12_cond_class", "bc13_lowest_rating", "bc14_nstm_cond", "bc15_underwater_cond",
        "bap01_appr_align", "bap02_overtopping", "bap03_scour_vuln", "bap04_scour_poa",
        "bap05_seismic", "bw01_year_built",
    ]

    def __init__(self, **overrides):
        for col in self._COLUMNS:
            setattr(self, col, None)
        self.bid01_bridge_number = "FRA-00071-0001"
        self.bl02_county_code = 49
        self.bl05_latitude = 39.96
        self.__dict__.update(overrides)


class _Strict(BaseModel):
    """Stand-in for ``civilpy.state.ohio.snbi.Bridge``: a few typed fields."""
    model_config = ConfigDict(extra="ignore")
    BID01: str = Field(min_length=1)
    BID03: str
    BL04: Optional[int] = None
    BL05: float = Field(ge=-90, le=90)


class _Capturing(_Strict):
    seen: list = []

    def __init__(self, **data):
        type(self).seen.append(dict(data))
        super().__init__(**data)


class _QuerySet:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def filter(self, **kw):
        self.filters.append(kw)
        return self

    def iterator(self):
        return iter(self.rows)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Stub django + bridges.models, chdir to tmp for the log, use _Capturing as SNBI model."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_tables, "setup_django_environment", MagicMock(name="setup"))

    bridges = types.ModuleType("bridges")
    models = types.ModuleType("bridges.models")
    bridges.models = models
    models.Bridge = MagicMock(name="DjangoBridge")
    monkeypatch.setitem(sys.modules, "bridges", bridges)
    monkeypatch.setitem(sys.modules, "bridges.models", models)

    snbi = types.ModuleType("civilpy.state.ohio.snbi")
    snbi.Bridge = _Capturing
    _Capturing.seen = []
    monkeypatch.setitem(sys.modules, "civilpy.state.ohio.snbi", snbi)

    def use(rows):
        qs = _QuerySet(rows)
        models.Bridge.objects.all.return_value = qs
        return qs

    return types.SimpleNamespace(use=use, tmp=tmp_path, setup=db_tables.setup_django_environment)


def _log(tmp_path, name):
    return (tmp_path / name).read_text(encoding="utf-8")


def test_statewide_run_counts_and_logs(harness, capsys):
    rows = [_Row(), _Row(bid01_bridge_number="BAD", bl05_latitude=123.0)]
    qs = harness.use(rows)
    db_tables.validate_bridge_data("/proj")
    harness.setup.assert_called_once_with("/proj")
    assert qs.filters == []  # statewide: no county filter
    out = capsys.readouterr().out
    assert "Scanning Statewide." in out
    assert "Success: 1" in out and "Errors:  1" in out
    assert f"Log saved to: {harness.tmp / 'statewide_validation_log.txt'}" in out
    log = _log(harness.tmp, "statewide_validation_log.txt")
    assert "Bridge BAD Failed:" in log
    assert "- Field: BL05 | Value: '123.0' | Issue: Input should be less than or equal to 90" in log
    assert "ERROR SUMMARY BY FIELD" in log
    assert "- BL05: 1 failures" in log
    assert "Bridge FRA-00071-0001 Failed" not in log


def test_district_filter_uses_odot_county_codes(harness, capsys):
    qs = harness.use([_Row()])
    db_tables.validate_bridge_data("/proj", target_district=6)
    # ODOT District 6: Delaware 41, Fayette 47, Franklin 49, Madison 97,
    # Marion 101, Morrow 117, Pickaway 129, Union 159
    d6 = [41, 47, 49, 97, 101, 117, 129, 159]
    assert qs.filters == [{"bl02_county_code__in": d6}]
    out = capsys.readouterr().out
    assert f"Targeting District 6 (Counties: {d6})" in out
    log = _log(harness.tmp, "d6_validation_log.txt")
    assert log.startswith(f"Targeting District 6 (Counties: {d6})")


@pytest.mark.parametrize("district, counties", [
    ("1", [3, 39, 63, 65, 125, 137, 161, 175]),
    ("12", [35, 55, 85]),
])
def test_district_map_edges(harness, district, counties):
    qs = harness.use([])
    db_tables.validate_bridge_data("/proj", target_district=district)
    assert qs.filters == [{"bl02_county_code__in": counties}]


def test_unknown_district_scans_statewide_with_warning(harness, capsys):
    qs = harness.use([_Row()])
    db_tables.validate_bridge_data("/proj", target_district=13)
    assert qs.filters == []
    assert "District 13 not found in map. Scanning all." in capsys.readouterr().out
    assert "District 13 not found. Scanning statewide." in _log(harness.tmp, "d13_validation_log.txt")


def test_field_mapping_and_casts(harness):
    harness.use([_Row(bid02_bridge_name="Main St", bid03_prev_bridge_number="",
                      bl04_highway_district="06", bw01_year_built=1965,
                      bc01_deck_cond="7", bap05_seismic="N")])
    db_tables.validate_bridge_data("/proj")
    data = _Capturing.seen[0]
    assert data["BID01"] == "FRA-00071-0001"
    assert data["BID02"] == "Main St"
    assert data["BID03"] == "0"           # empty previous number -> "0"
    assert data["BL02"] == 49
    assert data["BL04"] == 6              # digit string cast to int
    assert data["BL05"] == 39.96
    assert data["BW01"] == 1965
    assert data["BC01"] == "7" and data["BAP05"] == "N"
    assert "BW02" not in data and "BW03" not in data
    assert len(data) == 72  # 3 BID + 12 BL + 6 BCL + 2 BRH + 16 BG + 8 BLR + 4 BIR + 15 BC + 5 BAP + 1 BW


def test_bid03_kept_when_present_and_bl04_non_digit_stays_none(harness):
    harness.use([_Row(bid03_prev_bridge_number="OLD-1", bl04_highway_district="D6"),
                 _Row(bl04_highway_district=None)])
    db_tables.validate_bridge_data("/proj")
    assert _Capturing.seen[0]["BID03"] == "OLD-1"
    assert _Capturing.seen[0]["BL04"] is None
    assert _Capturing.seen[1]["BL04"] is None


def test_multiple_errors_per_bridge_counted_per_field(harness):
    harness.use([_Row(bid01_bridge_number="", bl05_latitude=-100.0),
                 _Row(bl05_latitude=95.0)])
    db_tables.validate_bridge_data("/proj", target_district="9")
    log = _log(harness.tmp, "d9_validation_log.txt")
    assert log.count("Failed:") == 2
    summary = log.split("ERROR SUMMARY BY FIELD")[1]
    assert "- BL05: 2 failures" in summary
    assert "- BID01: 1 failures" in summary
    assert summary.index("BL05") < summary.index("BID01")  # sorted by count desc


def test_progress_message_every_thousand(harness, capsys):
    harness.use([_Row() for _ in range(1001)])
    db_tables.validate_bridge_data("/proj")
    out = capsys.readouterr().out
    assert "Processed 1000 bridges..." in out
    assert "Processed 0 bridges" not in out
    assert "Success: 1001" in out


def test_missing_bridges_app_returns_early(harness, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "bridges", None)
    monkeypatch.delitem(sys.modules, "bridges.models")
    assert db_tables.validate_bridge_data("/proj") is None
    assert "Could not import 'bridges.models'" in capsys.readouterr().out
    assert not list(harness.tmp.glob("*_log.txt"))


def test_missing_civilpy_snbi_returns_early(harness, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "civilpy.state.ohio.snbi", None)
    assert db_tables.validate_bridge_data("/proj") is None
    out = capsys.readouterr().out
    assert "Django Bridge model imported." in out
    assert "Could not import 'civilpy'" in out


def test_log_file_is_rewritten_each_run(harness):
    harness.use([_Row(bl05_latitude=99.0)])
    db_tables.validate_bridge_data("/proj")
    harness.use([_Row()])
    db_tables.validate_bridge_data("/proj")
    log = _log(harness.tmp, "statewide_validation_log.txt")
    assert "Failed" not in log  # filemode='w'


@pytest.mark.xfail(strict=True, reason=(
    "BUG: validate_bridge_data casts BL04 (highway district) to int, but "
    "civilpy.state.ohio.snbi.Bridge types BL04 as an Optional 2-char str; "
    "every record with a district therefore fails validation on BL04"))
def test_bl04_is_passed_in_the_type_the_snbi_model_accepts(harness):
    harness.use([_Row(bl04_highway_district="06")])
    db_tables.validate_bridge_data("/proj")
    value = _Capturing.seen[0]["BL04"]
    adapter = TypeAdapter(real_snbi.Bridge.model_fields["BL04"].annotation)
    assert adapter.validate_python(value) == "06"


# --------------------------------------------------------------------------- #
# __main__ prompt
# --------------------------------------------------------------------------- #

def test_main_prompts_for_path_and_district(harness, fake_django, clean_env, monkeypatch, capsys):
    import builtins
    import runpy
    import warnings

    answers = iter(["", "6"])  # default path (cwd), district 6
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    qs = harness.use([_Row()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("civilpy.state.ohio.db_tables", run_name="__main__")
    out = capsys.readouterr().out
    assert out.startswith("--- SNBI Bridge Validator ---")
    # cwd (tmp) has no settings.py -> the re-executed module bootstraps with the default
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "core.settings"
    fake_django.setup.assert_called_once_with()
    assert qs.filters == [{"bl02_county_code__in": [41, 47, 49, 97, 101, 117, 129, 159]}]
    assert (harness.tmp / "d6_validation_log.txt").exists()
