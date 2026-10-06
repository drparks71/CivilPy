#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.DOT.OSE` (Stage 2 structural checklist).

ipywidgets are constructed headlessly; ``IPython.display.display`` is patched
so nothing renders, and ``HOME`` is pointed at ``tmp_path`` so the
``~/Documents/Reviews/<pid>/<pid>.json`` files land in the test sandbox.
Covers the project-info form (defaults, submit, JSON round trip, reload by
PID), the scope selectors and their save callbacks, the detailed-scope
follow-up widgets, and the folder/JSON helpers.
"""

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import ipywidgets as widgets
import pytest

from civilpy.state.ohio.DOT import OSE


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def display(monkeypatch):
    mock = MagicMock(name="display")
    monkeypatch.setattr(OSE, "display", mock)
    return mock


def _displayed(mock):
    """Flatten every positional argument passed to display()."""
    return [arg for call in mock.call_args_list for arg in call.args]


def _reviews(home):
    return home / "Documents" / "Reviews"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def test_check_if_review_folder_exists_creates_once(home, capsys):
    assert not _reviews(home).exists()
    OSE.check_if_review_folder_exists()
    assert _reviews(home).is_dir()
    assert "generating documents folder..." in capsys.readouterr().out
    OSE.check_if_review_folder_exists()
    assert capsys.readouterr().out == ""


def test_generate_project_info_writes_pid_json(home, capsys):
    _reviews(home).mkdir(parents=True)
    data = {"Project Info": {"pid": "123456", "sfn": "2500001"}, "Scope": {}}
    OSE.generate_project_info(data, "123456")
    target = _reviews(home) / "123456" / "123456.json"
    assert json.loads(target.read_text()) == data
    out = capsys.readouterr().out
    assert "Generating folder for PID '123456' in Documents..." in out
    assert f"JSON file Updated at: {target}" in out
    # Second call overwrites without re-creating the folder
    data["Scope"] = {"Substructure": None}
    OSE.generate_project_info(data, "123456")
    assert json.loads(target.read_text())["Scope"] == {"Substructure": None}
    assert "Generating folder" not in capsys.readouterr().out


def test_steel_stringer_and_railing_detail_widgets(display, capsys):
    s = OSE.steel_stringer_details(None)
    r = OSE.railing_details(None)
    assert isinstance(s, widgets.SelectMultiple) and s.options == ("Rolled", "Plate")
    assert s.value == () and s.rows == 2
    assert r.options == ("Deep Beam Railing", "Twin Steel Tube Railing",
                         "Sidewalk Railing with Concrete Parapet", "Parapet Type Railing",
                         "Parapet and Fence Type Railing")
    assert r.rows == 6
    assert _displayed(display) == [s, r]


# --------------------------------------------------------------------------- #
# Stage2StructuralChecklist: project info
# --------------------------------------------------------------------------- #

def test_blank_checklist_builds_placeholder_inputs(home, display):
    cl = OSE.Stage2StructuralChecklist()
    assert cl.data == {"Scope": {}, "Project Info": {}}
    assert set(cl.inputs) == {"cty_rte_sec", "checker", "sfn", "date", "pid"}
    assert cl.inputs["cty_rte_sec"].placeholder == "Bridge CTY-RTE-SEC"
    assert cl.inputs["checker"].placeholder == "Employee's Initials"
    assert cl.inputs["sfn"].placeholder == "Enter multiple if more than one"
    assert cl.inputs["pid"].placeholder == "Project PID"
    assert cl.inputs["date"].value == date.today()
    assert all(w.value == "" for k, w in cl.inputs.items() if k != "date")
    assert cl.load_button.description == "Load" and cl.load_button.button_style == "primary"
    assert cl.submit_button.description == "Submit" and cl.submit_button.button_style == "success"
    assert _reviews(home).is_dir()


def test_show_project_inputs_displays_form_in_order(home, display):
    cl = OSE.Stage2StructuralChecklist()
    display.reset_mock()
    cl.show_project_inputs()
    assert _displayed(display) == [cl.inputs["pid"], cl.inputs["cty_rte_sec"], cl.inputs["sfn"],
                                   cl.inputs["checker"], cl.inputs["date"],
                                   cl.load_button, cl.submit_button]


def test_submit_writes_project_info_and_json(home, display, capsys):
    cl = OSE.Stage2StructuralChecklist()
    cl.inputs["pid"].value = "109876"
    cl.inputs["cty_rte_sec"].value = "FRA-71-12.34"
    cl.inputs["sfn"].value = "2512345"
    cl.inputs["checker"].value = "DP"
    cl.inputs["date"].value = date(2025, 3, 7)
    cl.submit_button.click()
    expected = {"cty_rte_sec": "FRA-71-12.34", "checker": "DP", "date": "March 07, 2025",
                "sfn": "2512345", "pid": "109876"}
    assert cl.data["Project Info"] == expected
    saved = json.loads((_reviews(home) / "109876" / "109876.json").read_text())
    assert saved == {"Scope": {}, "Project Info": expected}
    assert "Project Info Updated:" in capsys.readouterr().out


def test_submit_without_date(home, display):
    cl = OSE.Stage2StructuralChecklist()
    cl.inputs["pid"].value = "1"
    cl.inputs["date"].value = None
    cl.update_project_info()
    assert cl.data["Project Info"]["date"] == "No date selected"


def test_load_by_pid_round_trips_saved_project(home, display, capsys):
    first = OSE.Stage2StructuralChecklist()
    first.inputs["pid"].value = "222"
    first.inputs["cty_rte_sec"].value = "DEL-23-1.00"
    first.inputs["sfn"].value = "2100001"
    first.inputs["checker"].value = "AB"
    first.inputs["date"].value = date(2024, 12, 31)
    first.update_project_info()
    first.data["Scope"]["Substructure"] = {"Piers": {}}
    OSE.generate_project_info(first.data, "222")
    capsys.readouterr()

    again = OSE.Stage2StructuralChecklist(pid="222")
    out = capsys.readouterr().out
    assert "Loaded Project Info:" in out and "not found" not in out
    assert again.data == first.data
    assert again.inputs["pid"].value == "222"
    assert again.inputs["cty_rte_sec"].value == "DEL-23-1.00"
    assert again.inputs["sfn"].value == "2100001"
    assert again.inputs["checker"].value == "AB"
    assert again.inputs["date"].value == datetime(2024, 12, 31)


def test_load_button_reloads_from_disk(home, display):
    cl = OSE.Stage2StructuralChecklist()
    cl.inputs["pid"].value = "333"
    cl.inputs["checker"].value = "XY"
    cl.update_project_info()
    cl.inputs["checker"].value = "edited-but-not-saved"
    cl.load_button.click()
    assert cl.inputs["checker"].value == "XY"


def test_unknown_pid_is_reported_not_raised(home, display, capsys):
    cl = OSE.Stage2StructuralChecklist(pid="999")
    out = capsys.readouterr().out
    assert "Error loading project info:" in out
    assert cl.inputs["pid"].value == "999"
    assert cl.data == {"Scope": {}, "Project Info": {"pid": "999"}}


def test_load_ignores_keys_without_inputs(home, display):
    cl = OSE.Stage2StructuralChecklist()
    folder = _reviews(home) / "444"
    folder.mkdir()
    (folder / "444.json").write_text(json.dumps(
        {"Project Info": {"pid": "444", "reviewer_phone": "n/a", "date": "May 06, 2024"}, "Scope": {}}))
    cl.inputs["pid"].value = "444"
    cl.load_project_info(None)
    assert cl.inputs["date"].value == datetime(2024, 5, 6)
    assert "reviewer_phone" not in cl.inputs


@pytest.mark.xfail(strict=True, reason=(
    "BUG: define_project_inputs' previous-data branch calls "
    "datetime.strftime(self.data['Project Info']['date'], ...) on the saved "
    "string and hands a str to DatePicker.value; it raises instead of "
    "pre-populating the form from loaded data"))
def test_define_project_inputs_prepopulates_from_loaded_data(home, display):
    cl = OSE.Stage2StructuralChecklist()
    cl.data["Project Info"] = {"pid": "555", "cty_rte_sec": "UNI-33-5.00", "checker": "ZZ",
                               "sfn": "8000001", "date": "January 02, 2025"}
    cl.define_project_inputs()
    assert cl.inputs["cty_rte_sec"].value == "UNI-33-5.00"
    assert cl.inputs["checker"].value == "ZZ"
    assert cl.inputs["sfn"].value == "8000001"
    assert cl.inputs["pid"].value == "555"
    assert cl.inputs["date"].value == date(2025, 1, 2)


# --------------------------------------------------------------------------- #
# Scope selectors
# --------------------------------------------------------------------------- #

def _scope_widgets(cl, display):
    display.reset_mock()
    cl.get_project_scope()
    shown = _displayed(display)
    temp, sup, sub, button = shown
    return temp, sup, sub, button


def test_get_project_scope_widgets_and_prompts(home, display, capsys):
    cl = OSE.Stage2StructuralChecklist()
    temp, sup, sub, button = _scope_widgets(cl, display)
    assert temp.options == (None, "Shoring", "Sheeting", "Cofferdams") and temp.rows == 4
    assert sup.options == (None, "Slab", "Prestressed Concrete Box Beams", "Prestressed Concrete I-Beams",
                           "Steel Stringers", "Railing/Fence", "Bearings", "Deck Joints", "Deck Drainage",
                           "Utilities", "Structure Grounding", "Approach Slab")
    assert sup.rows == 12
    assert sub.options == (None, "Piers", "Abutments", "Drilled Shafts")
    assert button.description == "Save Scope"
    out = capsys.readouterr().out
    assert "Does the project involve any temporary works?" in out
    assert "===Superstructure===" in out and "===Substructure===" in out
    assert cl.data["Scope"] == {}  # nothing saved until the button is clicked


def test_save_scope_builds_nested_dicts(home, display):
    cl = OSE.Stage2StructuralChecklist()
    temp, sup, sub, button = _scope_widgets(cl, display)
    temp.value = ("Shoring", "Cofferdams")
    sup.value = ("Steel Stringers", "Bearings")
    sub.value = ("Abutments",)
    button.click()
    assert cl.data["Scope"] == {
        "Temp_Works": {"Shoring": {}, "Cofferdams": {}},
        "Superstructure": {"Steel Stringers": {}, "Bearings": {}},
        "Substructure": {"Abutments": {}},
    }


def test_save_scope_none_selection_means_not_applicable(home, display):
    cl = OSE.Stage2StructuralChecklist()
    temp, sup, sub, button = _scope_widgets(cl, display)
    temp.value = (None,)
    sup.value = (None,)
    sub.value = (None,)
    button.click()
    assert cl.data["Scope"] == {"Temp_Works": None, "Superstructure": None, "Substructure": None}


def test_save_scope_empty_selection_is_empty_dict(home, display):
    cl = OSE.Stage2StructuralChecklist()
    _, _, _, button = _scope_widgets(cl, display)
    button.click()
    assert cl.data["Scope"] == {"Temp_Works": {}, "Superstructure": {}, "Substructure": {}}


# --------------------------------------------------------------------------- #
# Detailed scope
# --------------------------------------------------------------------------- #

def test_detailed_scope_requires_saved_scope(home, display, capsys):
    cl = OSE.Stage2StructuralChecklist()
    cl.get_detailed_scope()
    out = capsys.readouterr().out
    assert "Error occured" in out and "'Superstructure'" in out
    assert display.call_count == 0


def test_detailed_scope_steel_stringers_saved_on_click(home, display, capsys):
    cl = OSE.Stage2StructuralChecklist()
    cl.data["Scope"] = {"Superstructure": {"Steel Stringers": {}, "Bearings": {}, "Deck Joints": {},
                                           "Deck Drainage": {}},
                        "Substructure": {"Piers": {}, "Abutments": {}}}
    display.reset_mock()
    cl.get_detailed_scope()
    shown = _displayed(display)
    stringers, button = shown
    assert stringers.options == ("Rolled", "Plate")
    assert button.description == "Save Detailed Scope"
    out = capsys.readouterr().out
    for q in ("Bearings Question", "Deck Joints Question", "Deck Drainage Question",
              "Piers Question", "Abutments Question"):
        assert q in out
    stringers.value = ("Plate",)
    button.click()
    assert cl.data["Scope"]["Superstructure"]["Steel Stringers"] == ("Plate",)
    assert cl.data["Scope"]["Substructure"] == {"Piers": {}, "Abutments": {}}


def test_detailed_scope_with_substructure_none(home, display):
    cl = OSE.Stage2StructuralChecklist()
    cl.data["Scope"] = {"Superstructure": None, "Substructure": None}
    display.reset_mock()
    cl.get_detailed_scope()
    (button,) = _displayed(display)
    button.click()
    assert cl.data["Scope"] == {"Superstructure": None, "Substructure": None}


@pytest.mark.xfail(strict=True, reason=(
    "BUG: get_detailed_scope appends the railing selector under the "
    "'Steel Stringers' key, so saving overwrites the stringer choice and "
    "'Railing/Fence' never receives its details"))
def test_detailed_scope_saves_railing_under_its_own_key(home, display):
    cl = OSE.Stage2StructuralChecklist()
    cl.data["Scope"] = {"Superstructure": {"Steel Stringers": {}, "Railing/Fence": {}},
                        "Substructure": None}
    display.reset_mock()
    cl.get_detailed_scope()
    stringers, railing, button = _displayed(display)
    stringers.value = ("Rolled",)
    railing.value = ("Parapet Type Railing",)
    button.click()
    assert cl.data["Scope"]["Superstructure"]["Steel Stringers"] == ("Rolled",)
    assert cl.data["Scope"]["Superstructure"]["Railing/Fence"] == ("Parapet Type Railing",)
