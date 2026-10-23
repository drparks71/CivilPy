#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Heat curving (Fabrication Spec 14.3.2.2) against the NSBA Heat Curve
Evaluator v2.01: its own example (Excel's cached results) and 60 seeded
sections recalculated in the workbook by headless LibreOffice
(data/heat_curve_golden.json, made by snbi_ui
utils/manuals/NSBA/validation/heat_curve_evaluator/make_golden.py)."""

import json
from pathlib import Path

import pytest

from civilpy.structural import heat_curving as hc
from civilpy.structural.heat_curving import Plate

GOLDEN = json.loads((Path(__file__).parent / "data" / "heat_curve_golden.json").read_text())
SECTIONS = [("example", i, s) for i, s in enumerate(GOLDEN["example"])] + \
           [("case", i, s) for i, s in enumerate(GOLDEN["cases"])]


def _plates(sec):
    (ft, bt, tt), (fw, d, tw), (fb, bb, tb) = sec["plates"]
    return Plate(bt, tt, ft), Plate(d, tw, fw), Plate(bb, tb, fb)


@pytest.mark.parametrize("src,i,sec", SECTIONS, ids=[f"{s}{i}" for s, i, _ in SECTIONS])
def test_workbook_mode_reproduces_the_evaluator(src, i, sec):
    r = hc.minimum_radius(*_plates(sec), workbook=True)
    if sec["r_min"] == "NG":
        assert not r.permitted
    else:
        assert r.r_min == pytest.approx(sec["r_min"], rel=1e-9)
    assert r.values["Psi"] == pytest.approx(sec["psi"])
    assert r.values["Psi_f"] == pytest.approx(sec["psi_f"])
    assert r.values["Psi_fo"] == pytest.approx(sec["psi_fo"])


def test_example_field_section_status():
    sections = [_plates(s) for s in GOLDEN["example"]]
    assert hc.field_section(sections, 500, workbook=True)["status"] == "CANNOT BE HEAT CURVED"
    # without the NG sections the girder still needs 336 ft <= 500 ft
    assert hc.field_section([sections[0], sections[3]], 500)["permitted"]
    assert not hc.field_section([sections[0], sections[3]], 300)["permitted"]


def test_hybrid_with_equal_flange_grades_follows_the_flowchart():
    # Example section 5: 50 ksi flanges, 36 ksi web, doubly symmetric ->
    # 14.3.2.2.3 (the spreadsheet says NG; its flowchart says Art. 14.3.2.2.3)
    top, web, bot = Plate(20, 1, 50), Plate(60, 0.5, 36), Plate(20, 1, 50)
    assert not hc.minimum_radius(top, web, bot, workbook=True).permitted
    r = hc.minimum_radius(top, web, bot)
    assert r.r_min == pytest.approx(500.571, abs=1e-3)
    assert r.values["governing"] == "14.3.2.2.3-1"           # D/tw 120 > 592/sqrt(36)


def test_branches():
    # stocky homogeneous doubly symmetric: Eq. 3-2 = 12,800 b / (Fy Psi) / 12
    top = Plate(20, 1.5, 50)
    r = hc.minimum_radius(top, Plate(48, 0.75, 50), top)
    psi = (2 * 30 + 36) / 60
    assert r.r_min == pytest.approx(max(150, 12_800 * 20 / (50 * psi) / 12))
    # a flange over 3 in. thick sets the 1,000 ft floor
    thick = hc.minimum_radius(Plate(24, 3.25, 50), Plate(60, 0.75, 50), Plate(24, 3.25, 50))
    assert thick.radii["14.3.2.2.2"] == 1000.0 and thick.r_min >= 1000.0
    # Psi_f < 0.20 is NG
    assert not hc.minimum_radius(Plate(10, 0.5, 50), Plate(60, 0.5, 50), Plate(30, 2.0, 50)).permitted
    # hybrid eta_f < 1 needs the web at the weaker flange's grade
    assert not hc.minimum_radius(Plate(20, 1, 50), Plate(60, 0.5, 36), Plate(22, 1, 70)).permitted
    ok = hc.minimum_radius(Plate(20, 1, 50), Plate(60, 0.5, 50), Plate(22, 1, 70))
    assert ok.permitted and ok.values["eta_f"] == pytest.approx(50 / 70)


def test_singly_symmetric_equation_4():
    top, web, bot = Plate(14, 0.75, 50), Plate(84, 0.5, 50), Plate(24, 1.5, 50)
    r = hc.minimum_radius(top, web, bot)
    p, pf = r.values["Psi"], r.values["Psi_f"]
    pfo = 0.68 * p - 0.79
    assert p >= 1.46 and pf < pfo
    expect = (1.43 * p * (1 - pf / pfo) ** 2 + 1) * 12_800 / 12 * 24 / (50 * p)
    assert r.radii["14.3.2.2.4-1"] == pytest.approx(expect)
