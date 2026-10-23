#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""CIF scorecards: every worked detail of NSBA B304 (Tables 1-24), with the
guide's item scores and totals."""

import pytest

from civilpy.structural.aashto import cif
from civilpy.structural.aashto.cif import CIFDetail

#  (table, detail, expected (stress, constraint, planar), total)
EXAMPLES = [
    (1, CIFDetail("long. stiffener away from its end", "tension", 2), 1.5),
    (2, CIFDetail("long. stiffener end at a transverse stiffener, small gap", "tension", 3,
                  "perpendicular"), 3.0),
    (3, CIFDetail("long. stiffener CJP-welded to the transverse stiffener", "tension", 0,
                  "perpendicular"), 2.0),
    (4, CIFDetail("flange-to-web fillets through a flange CJP shop splice", "tension", 2, "parallel"), 1.5),
    (5, CIFDetail("flange-to-web fillets through a web CJP shop splice", "tension", 2, "parallel"), 1.5),
    (6, CIFDetail("transverse stiffener fillets across a web longitudinal splice", "tension", 0,
                  "parallel"), 1.0),
    (7, CIFDetail("transverse web stiffener at web and flange", "tension", 2, "parallel"), 1.5),
    (8, CIFDetail("bearing stiffeners at web and flange", "tension", 2, "parallel"), 1.5),
    (9, CIFDetail("transverse connection plate welded to both flanges", "tension", 2, "parallel"), 1.5),
    (10, CIFDetail("bearing stiffener / connection plate, compression flange only, small gap",
                   "tension", 3, "perpendicular"), 3.0),
    (11, CIFDetail("coped, seal-welded stiffener", "tension", 3, "parallel", relief_gap=None), (1.5, 2.0)),
    (12, CIFDetail("continuously seal-welded stiffener", "tension", 3, "parallel"), 2.0),
    (13, CIFDetail("fillet-welded long. stiffener at a web shop splice", "tension", 2, "parallel"), 1.5),
    (14, CIFDetail("continuous long. stiffener through a discontinuous transverse stiffener",
                   "tension", 3, "parallel", relief_gap=None), (1.5, 2.0)),
    (15, CIFDetail("coped and welded discontinuous long. stiffener", "tension", 3, "perpendicular",
                   relief_gap=None), (2.5, 3.0)),
    (16, CIFDetail("continuously welded discontinuous long. stiffener", "tension", 3, "perpendicular"), 3.0),
    (17, CIFDetail("gapped discontinuous long. stiffener (1/4 in. gaps)", "tension", 3,
                   "perpendicular"), 3.0),
    (18, CIFDetail("continuous lateral connection plate through a transverse stiffener", "tension", 3,
                   "parallel", relief_gap=None), (1.5, 2.0)),
    (19, CIFDetail("stay cable anchorage gusset, no constraint", "tension", 0, "parallel"), 1.0),
    (20, CIFDetail("stay cable anchorage gusset at the flange", "tension", 2, "parallel"), 1.5),
    (21, CIFDetail("orthotropic rib-to-floor-beam weld", "tension", 2, "parallel"), 1.5),
    (22, CIFDetail("column-to-base plate CJP", "tension", 3, None, relief_gap=True), 1.5),
    (23, CIFDetail("stiffener-to-base plate fillets", "tension", 3, "perpendicular", relief_gap=True), 2.5),
    (24, CIFDetail("stiffener-to-column fillets", "tension", 3, "parallel", relief_gap=True), 1.5),
]


@pytest.mark.parametrize("table,detail,total", EXAMPLES, ids=[f"table{t}" for t, *_ in EXAMPLES])
def test_b304_scorecards(table, detail, total):
    card = detail.scorecard(existing=False)
    assert card["total"] == (pytest.approx(total) if not isinstance(total, tuple) else total)


@pytest.mark.parametrize("total,new,existing", [(3.0, "high", "high"), (2.5, "high", "may be high"),
                                                (2.0, "low", "low"), (1.5, "low", "low"),
                                                (0.0, "low", "low")])
def test_screening_thresholds(total, new, existing):
    assert cif.classify(total, existing=False) == new
    assert cif.classify(total, existing=True) == existing


def test_compression_zone_details_cannot_be_high():
    for _, d, _ in EXAMPLES:
        comp = CIFDetail(d.name, "compression", d.intersecting_elements, d.planar, d.relief_gap)
        t = comp.scorecard()["total"]
        assert (t[1] if isinstance(t, tuple) else t) <= 2.0


def test_relief_gap_lowers_constraint_only_for_three_elements():
    assert cif.constraint_score(3, False) == (1.0, 1.0)
    assert cif.constraint_score(3, True) == (0.5, 0.5)
    assert cif.constraint_score(2, False) == (0.5, 0.5)
    assert cif.constraint_score(1) == (0.0, 0.0)


def test_screen_puts_the_worst_first():
    cards = cif.screen([d for _, d, _ in EXAMPLES])
    first = cards[0]["total"]
    assert (first if not isinstance(first, tuple) else first[1]) == 3.0
    assert cards[0]["susceptibility"] == "high"


def test_bad_inputs():
    with pytest.raises(ValueError):
        cif.stress_score("shear")
    with pytest.raises(ValueError):
        cif.planar_score("oblique")
