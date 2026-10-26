#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Shape-table lookups in civilpy.structural.steel, over the whole tables.

Every current shape is found by its EDI name and by its AISC manual label
(they differ for pipes and HSS), in any case; a missing label raises the
KeyError the docstring promises; every historic name resolves, or asks for a
designation when it is listed under several.
"""

from __future__ import annotations

import pytest

from civilpy.general import units
from civilpy.structural.steel import (
    HP, W, WF, HistoricSteelSection, SteelSection, historic_steel_tables, steel_tables,
)

ROWS = steel_tables[["EDI_Std_Nomenclature", "AISC_Manual_Label", "W"]].itertuples(index=False)
# Names the class can look up (it strips spaces and upper-cases), each one
# shape per designation; the table also holds size-group rows ("WF 8x8")
_h = historic_steel_tables.dropna(subset=["Name"])
_h = _h[_h["Name"] == _h["Name"].str.replace(" ", "").str.upper()]
_h = _h[~_h.duplicated(["Name", "Designation"], keep=False)]
NAME_COUNTS = _h["Name"].value_counts()


@pytest.mark.parametrize("edi, manual, weight", list(ROWS))
def test_every_shape_is_found_by_edi_name_and_manual_label(edi, manual, weight):
    for label in {edi, manual, manual.lower()}:
        assert SteelSection(label).weight == weight * units("lbf/ft")


@pytest.mark.parametrize("label", ["W36X151", "Pipe6XX", "HSS1X1X1", "nonsense"])
def test_a_label_in_neither_column_raises_key_error(label):
    with pytest.raises(KeyError, match="not found"):
        SteelSection(label)


def test_the_error_suggests_close_labels():
    with pytest.raises(KeyError, match="W36X150"):
        SteelSection("W36X15O")                      # letter O for zero


@pytest.mark.parametrize("cls", [W, HP])
def test_flange_slenderness_is_a_plain_ratio(cls):
    for label in steel_tables.loc[steel_tables["Type"] == cls.__name__, "AISC_Manual_Label"][:25]:
        section = cls(label)
        ratio = section.slenderness_ratio_flange
        assert isinstance(ratio, float)
        bf, tf = section.flange_width.magnitude, section.flange_thickness.magnitude
        assert ratio == pytest.approx(bf / (2 * tf), abs=0.06)   # table rounds bf, tf


@pytest.mark.parametrize("name", NAME_COUNTS[NAME_COUNTS == 1].index[:60])
def test_a_historic_name_under_one_designation_needs_none(name):
    assert HistoricSteelSection(name).aisc_value["Name"].tolist() == [name]


@pytest.mark.parametrize("name", NAME_COUNTS[NAME_COUNTS > 1].index[:60])
def test_a_historic_name_under_several_designations_asks_for_one(name):
    designations = _h.loc[_h["Name"] == name, "Designation"]
    with pytest.raises(ValueError, match="designation"):
        HistoricSteelSection(name)
    for d in designations:
        assert HistoricSteelSection(name, designation=d).aisc_value["Designation"].tolist() == [d]
    with pytest.raises(KeyError, match="no designation"):
        HistoricSteelSection(name, designation="not-a-designation")


@pytest.mark.parametrize("label", ["WF36X150", "99WF1", "nonsense"])
def test_an_unknown_historic_name_raises_key_error(label):
    with pytest.raises(KeyError, match="not found"):
        WF(label)
