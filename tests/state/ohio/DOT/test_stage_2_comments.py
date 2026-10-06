#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.DOT.stage_2_comments`.

The module is a data library: named ``*_criteria`` lists of review comments
(``{"label": ..., "reference": ...}``) plus ``all_criteria``, the registry the
OSE checklist builder iterates. These tests pin the registry's shape and a
sample of the BDM-referenced comment texts, and flag the lists that are
accidentally wrapped in a tuple by a trailing comma.
"""

import pytest

from civilpy.state.ohio.DOT import stage_2_comments as s2


# Lists in the source that end with "]," and therefore evaluate to a 1-tuple
# wrapping the real list.
_TUPLE_WRAPPED = [
    "general_criteria", "site_plan_criteria", "general_plan_criteria",
    "general_notes_criteria", "detail_notes_criteria",
    "estimated_quantitites_criteria", "reinforcing_details_criteria",
    "typical_sections_criteria", "temporary_sheeting_criteria",
    "temporary_railing_criteria", "slab_bridges_criteria",
    "lateral_restraint_criteria",
]


def _entries(value):
    """Unwrap the tuple-wrapped lists so the content checks can still run."""
    return value[0] if isinstance(value, tuple) else value


# --------------------------------------------------------------------------- #
# Registry shape
# --------------------------------------------------------------------------- #

def test_all_criteria_registers_every_criteria_variable():
    expected = {name for name in vars(s2) if name.endswith("_criteria")} - {"all_criteria"}
    assert set(s2.all_criteria) == expected
    assert len(s2.all_criteria) == 52
    assert "all_criteria" not in s2.all_criteria
    assert "all_comments" not in s2.all_criteria


def test_registry_values_are_the_module_objects():
    for name, value in s2.all_criteria.items():
        assert getattr(s2, name) is value


@pytest.mark.parametrize("name", sorted(s2.all_criteria))
def test_every_entry_is_a_labelled_dict(name):
    entries = _entries(s2.all_criteria[name])
    assert isinstance(entries, list)
    for entry in entries:
        assert set(entry) <= {"label", "reference"}, entry
        assert isinstance(entry["label"], str) and entry["label"].strip()
        if "reference" in entry:
            assert isinstance(entry["reference"], str)


def test_eight_entries_carry_a_blank_reference_placeholder():
    blanks = [(n, i) for n, v in s2.all_criteria.items()
              for i, e in enumerate(_entries(v)) if e.get("reference", "x") == ""]
    assert blanks == [
        ("general_plan_criteria", 1), ("stage_cons_misc_criteria", 13),
        ("prestressed_concrete_box_criteria", 6), ("prestressed_concrete_box_criteria", 21),
        ("prestressed_concrete_box_criteria", 22), ("prestressing_steel_criteria", 3),
        ("prestressing_steel_criteria", 5), ("prestressing_steel_criteria", 10),
    ]


def test_only_steel_criteria_is_an_empty_placeholder():
    empties = [n for n, v in s2.all_criteria.items() if not _entries(v)]
    assert empties == ["steel_criteria"]


def test_library_size():
    total = sum(len(_entries(v)) for v in s2.all_criteria.values())
    assert total == 388
    referenced = sum(1 for v in s2.all_criteria.values() for e in _entries(v) if "reference" in e)
    assert referenced == 230


def test_no_duplicate_labels_within_a_list():
    for name, value in s2.all_criteria.items():
        labels = [e["label"] for e in _entries(value)]
        assert len(labels) == len(set(labels)), name


# --------------------------------------------------------------------------- #
# Content spot checks (ODOT BDM / SCD references)
# --------------------------------------------------------------------------- #

def test_general_criteria_cites_bdm_sheet_ordering_and_title_block():
    entries = _entries(s2.general_criteria)
    assert len(entries) == 17
    assert entries[0] == {"label": "All Stage I comments resolved and detailed design is as per approved Stage I."}
    assert entries[2] == {"label": "All bridge plan sheet are in order.", "reference": "BDM 103"}
    assert entries[4] == {"label": "Project number and bridge number correct?", "reference": "BDM 102.4"}
    assert entries[5] == {"label": "Plans compliant with L&D, Vol. 3?", "reference": "L&D Vol. 3"}


def test_grounding_cites_scd_hl_50_21():
    assert s2.grounding_criteria == [
        {"label": "Verify the structure is properly grounded as per Standard Drawing HL-50.21.",
         "reference": "ODOT SCD HL-50.21"}
    ]


def test_slab_criteria_sealing_and_drip_strip():
    assert s2.slab_criteria[0] == {"label": "Sealing of concrete surfaces shown and appropriate?",
                                   "reference": "306.1.2"}
    assert s2.slab_criteria[1]["reference"] == "309.2 and 309.7"


def test_concrete_criteria():
    assert s2.concrete_criteria == [
        {"label": "Concrete surfaces sealed", "reference": "BDM 306.1.2, 309.2.1 and 403.3"},
        {"label": "Epoxy only sealer not used.", "reference": "BDM 309.2.1-G"},
    ]


def test_elastomeric_bearings_reference_lrfd_14_7():
    labels = {e["label"]: e.get("reference") for e in s2.elastomeric_bearings_criteria}
    assert len(labels) == 11
    assert labels["Elastomer hardness specified?"] == "306.4.2.1"
    assert labels["No top cover layer for bearing with load plate."] == "AASHTO LRFD 14.7.6.1"
    assert labels["BDM Note no. 702.13 provided with bearing details."] == "BDM 702.13"
    assert ("For prestressed box beam bridges without external steel load plates, bearing shall "
            "conform to Standard Drawing BD-1-11?") in labels
    assert labels["Top and bottom cover layers should not be thicker than 70% of internal layers"] \
        == "AASHTO LRFD 14.7.6.1"


def test_piers_general_footing_proportions_cite_bdm_306_3_1():
    first = s2.piers_general_criteria[0]
    assert first["reference"] == "BDM 306.3.1"
    assert "one-fourth the height where founded on soil" in first["label"]
    assert "one-fifth the height where founded on rock" in first["label"]
    assert len(s2.piers_general_criteria) == 11


def test_end_dams_and_utilities_have_no_references():
    assert len(s2.end_dams_criteria) == 4
    assert all("reference" not in e for e in s2.end_dams_criteria)
    assert len(s2.utilities_criteria) == 6
    assert all("reference" not in e for e in s2.utilities_criteria)


def test_erosion_protection_three_foot_minimum():
    assert any("3'-0\" minimum" in e["label"] for e in s2.erosion_protection_criteria)
    assert len(s2.erosion_protection_criteria) == 3


def test_elastomeric_trough_discharge_opening():
    assert {"label": "Large discharge openings (12 inch diameter minimum)?"} in s2.elastomeric_trough_criteria


def test_lateral_restraint_cites_sicd_2_14():
    entries = _entries(s2.lateral_restraint_criteria)
    assert entries[-1]["label"].endswith("SICD-2-14.")


# --------------------------------------------------------------------------- #
# Tuple-wrapping bug
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", _TUPLE_WRAPPED)
@pytest.mark.xfail(strict=True, reason=(
    "BUG: these criteria lists end with '],' in stage_2_comments.py, so the "
    "name is bound to a 1-tuple containing the list instead of the list; "
    "iterating them yields a single list, not the comment dicts"))
def test_criteria_list_is_a_list_of_dicts(name):
    value = s2.all_criteria[name]
    assert isinstance(value, list)
    assert all(isinstance(e, dict) for e in value)


def test_tuple_wrapped_lists_are_exactly_the_known_set():
    # Guard so the xfail list above tracks the source: if someone fixes a
    # trailing comma, the strict xfail will XPASS and this set shrinks.
    wrapped = sorted(n for n, v in s2.all_criteria.items() if isinstance(v, tuple))
    assert wrapped == sorted(_TUPLE_WRAPPED)
