#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT L&D Vol 2 rules (civilpy.state.ohio.DOT.drainage): design flood by
road class, the scour flood table, headwater controls, RCP, TAF, WQv, file
numbers and the floodplain self-compliance documents."""

import pytest

from civilpy.state.ohio.DOT import drainage as ld2


@pytest.mark.parametrize("func_class, aadt, kw, aep, scour", [
    ("1", 50000, {}, 2.0, (1.0, 0.2)),        # rural interstate
    ("11", 2000, {}, 2.0, (1.0, 0.2)),        # urban interstate, ADT irrelevant
    ("12", 900, {}, 2.0, (1.0, 0.2)),         # urban freeway / expressway (legacy NBI 26)
    ("02", 900, {}, 2.0, (1.0, 0.2)),         # legacy, zero-padded
    ("2", 900, {}, 2.0, (1.0, 0.2)),          # SNBI other freeway / expressway
    ("3", 20000, {}, 4.0, (2.0, 1.0)),        # SNBI principal arterial - other: not a freeway
    ("5", 509, {}, 10.0, (4.0, 2.0)),         # rural major collector, under 3,000
    ("5", 3000, {}, 4.0, (2.0, 1.0)),         # exactly 3,000 is "3,000 and over"
    ("7", None, {}, 4.0, (2.0, 1.0)),         # unknown ADT -> conservative 4 %
    (None, None, {}, 4.0, (2.0, 1.0)),
    ("7", 100, {"ramp": True}, 4.0, (2.0, 1.0)),
    ("7", 100, {"bikeway": True}, 20.0, (4.0, 2.0)),
    ("7", 100, {"freeway": True}, 2.0, (1.0, 0.2)),
])
def test_design_aep_and_scour_floods(func_class, aadt, kw, aep, scour):
    d = ld2.design_aep(func_class, aadt, **kw)
    assert d.aep_pct == aep and (d.scour_design_pct, d.scour_check_pct) == scour
    assert d.recurrence_yr == ld2.AEP_TO_RI[aep] and "1004.2" in d.basis


def test_scour_floods_table_is_the_manual_table():
    assert ld2.scour_floods(10.0) == (4.0, 2.0) and ld2.scour_floods(4.0) == (2.0, 1.0) and ld2.scour_floods(2.0) == (1.0, 0.2)


def test_flood_clearance():
    c = ld2.flood_clearance(600.0, travelled_way_low_ft=602.5, low_chord_ft=601.0)
    assert c["travelled_way_margin_ft"] == 2.5 and not c["travelled_way_ok"]
    assert c["low_chord_margin_ft"] == 1.0 and c["low_chord_ok"]
    assert "low_chord_ok" not in ld2.flood_clearance(600.0, travelled_way_low_ft=603.0)


def test_culvert_headwater_controls():
    h = ld2.culvert_headwater_controls(pavement_low_edge_ft=100.0, inlet_crown_ft=92.0, drainage_area_acres=1500, rise_ft=4.0)
    assert h["design"]["A_pavement_ft"] == 98.0 and h["design"]["BC_crown_ft"] == 94.0
    assert h["design"]["allowable_ft"] == 94.0 and h["design"]["controls"] == "B"
    assert h["check"]["max_1pct_depth_ft"] == 8.0
    small = ld2.culvert_headwater_controls(pavement_low_edge_ft=100.0, inlet_crown_ft=98.5, drainage_area_acres=40)
    assert small["design"]["A_pavement_ft"] == 99.0 and small["design"]["controls"] == "A"
    deep = ld2.culvert_headwater_controls(pavement_low_edge_ft=100.0, inlet_crown_ft=80.0, drainage_area_acres=40, deep_ravine=True)
    assert deep["design"]["BC_crown_ft"] == 84.0 and deep["design"]["controls"] == "C"


@pytest.mark.parametrize("v, t, thick, ohe", [(3.0, "C", 24, False), (8.0, "C", 24, False), (9.5, "B", 30, False),
                                               (10.0, "B", 30, False), (11.0, "A", 36, False), (13.0, "A", 36, True)])
def test_rcp_type(v, t, thick, ohe):
    r = ld2.rcp_type(v)
    assert (r["type"], r["thickness_in"], r["contact_ohe"]) == (t, thick, ohe)


def test_taf_standard_discharge():
    t = ld2.taf_standard_discharge(18.8)
    assert t["max_mean_monthly_cfs"] == pytest.approx(2.01 * 18.8 ** 1.01, abs=0.1)
    assert t["standard_temporary_discharge_cfs"] == pytest.approx(2 * t["max_mean_monthly_cfs"], abs=0.1)
    assert t["analysis_required"] and not t["suggest_2d"]
    assert not ld2.taf_standard_discharge(1.5)["analysis_required"]
    big = ld2.taf_standard_discharge(6345.0, max_mean_monthly_cfs=12000.0)
    assert big["standard_temporary_discharge_cfs"] == 24000.0 and big["suggest_2d"] and "StreamStats" in big["source"]


def test_water_quality_volume_and_large_river():
    w = ld2.water_quality_volume(10.0, 1.0)
    assert w["rv"] == 0.95 and w["wqv_acre_ft"] == pytest.approx(0.95 * 0.9 * 10 / 12, abs=1e-4)
    assert ld2.water_quality_volume(10.0, 0.0)["rv"] == 0.05
    assert ld2.large_river(150.0, 2) and ld2.large_river(20.0, 4) and not ld2.large_river(20.0, 3)


@pytest.mark.parametrize("opening, kind", [(None, None), (0.5, None), (1.0, "CFN"), (9.99, "CFN"), (10.0, "SFN"), (172.8, "SFN")])
def test_file_number_kind(opening, kind):
    assert ld2.file_number_kind(opening) == kind


def test_conduit_end_of_life():
    assert ld2.conduit_end_of_life(4) and ld2.conduit_end_of_life("3") and not ld2.conduit_end_of_life(5)
    assert ld2.conduit_end_of_life(None) is None


def test_floodplain_documents_by_zone():
    fw = ld2.floodplain_documents("AE", floodway=True)
    assert any("LD-50" in d for d in fw["documents"]) and fw["surcharge_ft"] == 0.0 and "FEMA" in fw["coordination"]
    ae = ld2.floodplain_documents("AE", floodway=False)
    assert not any("LD-50" in d for d in ae["documents"]) and any("hydraulic" in d for d in ae["documents"])
    a = ld2.floodplain_documents("A", floodway=False)
    assert any("carrying capacity" in d for d in a["documents"]) and "FEMA" not in a["coordination"]
    assert any("LD-52" in d for d in a["documents"]) and any("LD-51" in d for d in a["documents"])
    ex = ld2.floodplain_documents("AE", floodway=True, exempt=True)
    assert ex["documents"] == ["LD-53 Letter of Notification of SFHA Exemption"]
    assert ld2.floodplain_documents("X", floodway=False)["documents"] == []


@pytest.mark.parametrize("zone, culvert_min, req", [("X", False, True), ("", False, True), ("A", False, False),
                                                    ("AE", False, False), ("A12", False, False), ("X", True, False)])
def test_flood_hazard_evaluation_required(zone, culvert_min, req):
    assert ld2.flood_hazard_evaluation_required(zone, minimum_size_culvert=culvert_min) is req


def test_hh_extent_and_2d():
    assert ld2.hh_model_extent_ft(False, 2000) == 500.0 and ld2.hh_model_extent_ft(True, 2000) == 4000.0
    assert ld2.hh_model_extent_ft(True, 100) == 500.0
    p = ld2.prefer_2d(6345.0, in_sfha=True)
    assert p["two_d"] and "fema_note" in p
    assert not ld2.prefer_2d(18.8)["two_d"] and ld2.prefer_2d(18.8, skewed=True)["two_d"]
    assert ld2.fis_discharge_governs(True) and ld2.fis_discharge_governs(False) is None
