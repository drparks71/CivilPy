#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Fatigue retrofit categories, crack-arrest holes and retrofitted life
(G14.1-2021 and the FHWA fatigue crack repair manual)."""

import math

import pytest

from civilpy.structural.aashto import fatigue_retrofit as fr
from civilpy.structural.aashto import mbe_fatigue
from civilpy.structural.aashto.lrfd.steel import FATIGUE_DETAIL_CATEGORIES


@pytest.mark.parametrize("original,retrofit,after", [
    ("E", "hammer_peening", "D"),                 # G14.1: one category
    ("E", "uit", "C"),                            # G14.1: E -> C
    ("E'", "uit", "D"),                           # two rungs
    ("E'", "uit_cover_plate", "C"),               # Roy et al.: treated cover-plate ends
    ("E'", "gta_remelt_or_peen_cover_plate", "C"),
    ("E", "bolted_splice", "B"),
    ("E'", "bolted_splice", "B"),
    ("E", "radius_gusset_termination", "D"),
    ("E", "web_isolation_holes", "C"),
    ("C", "grind_groove_weld", "B"),
    ("D", "drilled_hole", "C"),
    ("D", "drilled_hole_bolted", "B"),
    ("B", "welded_doubler", "B"),                 # never a downgrade
    ("C", "welded_doubler", "C"),
])
def test_retrofit_categories(original, retrofit, after):
    assert fr.retrofit_category(original, retrofit)[0] == after


def test_bolted_hole_is_refused_for_distortion_cracks():
    with pytest.raises(ValueError, match="distortion"):
        fr.retrofit_category("C", "drilled_hole_bolted", distortion_induced=True)
    assert fr.retrofit_category("C", "drilled_hole", distortion_induced=True)[0] == "C"


@pytest.mark.parametrize("cat", ["A", "B", "B'", "C", "C'", "D", "E", "E'"])
def test_improvement_never_worsens_and_peening_moves_one_rung(cat):
    after = fr.improve(cat, 1)
    assert fr._ON_LADDER[after] <= fr._ON_LADDER[cat]
    assert fr._ON_LADDER[after] == max(0, fr._ON_LADDER[cat] - 1)


@pytest.mark.parametrize("sr,a,fy", [(6.0, 2.0, 36.0), (10.0, 3.0, 50.0), (4.0, 1.0, 50.0)])
def test_hole_satisfies_the_curvature_criterion(sr, a, fy):
    d = fr.crack_arrest_hole_diameter(sr, a, fy)
    rho = d / 2
    dk = sr * math.sqrt(math.pi * a)
    assert dk / math.sqrt(rho) <= 4 * math.sqrt(fy) + 1e-9
    if d > 1.0:
        assert dk / math.sqrt(rho) == pytest.approx(4 * math.sqrt(fy))
    edge = fr.crack_arrest_hole_diameter(sr, a, fy, edge_crack=True)
    assert edge == pytest.approx(max(1.25 * sr ** 2 * math.pi * a / (8 * fy), 1.0))


def test_si_form_agrees_with_the_us_form():
    # Fig. 21: D = S_r^2 pi a / (55 Fy) in MPa and mm
    sr, a, fy = 10.0, 3.0, 50.0
    d_in = fr.crack_arrest_hole_diameter(sr, a, fy, minimum=0.0)
    d_mm = (sr * 6.894757) ** 2 * math.pi * (a * 25.4) / (55.0 * fy * 6.894757)
    assert d_mm / 25.4 == pytest.approx(d_in, rel=0.01)


def test_web_gap_criterion():
    assert fr.drilled_holes_suffice_for_web_gap(5.0, 12.0)
    assert not fr.drilled_holes_suffice_for_web_gap(7.0, 12.0)
    assert not fr.drilled_holes_suffice_for_web_gap(5.0, 16.0)
    assert not fr.drilled_holes_suffice_for_web_gap(5.0, 12.0, skewed=True)


def test_retrofitted_life_starts_today_and_improves():
    t = mbe_fatigue.Traffic(2000, 800, 4000, 1965, 2024, growth=0.02, span_ft=90, lanes=2)
    before = mbe_fatigue.evaluate(3.0, "E'", t)
    after = fr.retrofitted_life(3.0, "E'", "bolted_splice", t)
    assert after.category == "B"
    assert after.infinite or (after.n_1 == 0.0 and after.remaining_years > before.remaining_years)


@pytest.mark.parametrize("cat", ["B", "C", "D", "E"])
def test_threshold_ordering_matches_the_ladder(cat):
    better = fr.improve(cat, 1)
    assert FATIGUE_DETAIL_CATEGORIES[better][1] > FATIGUE_DETAIL_CATEGORIES[cat][1]
