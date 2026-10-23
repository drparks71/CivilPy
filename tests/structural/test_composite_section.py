#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Composite-section checks against a synthetic rectangular hand calculation.

Two 12 x 1 flanges and a 22 x 0.5 web give A=35, y=12,
I=10859/3. An 8 x 96 deck centered at y=30 adds A=96, I=512
at n=8 (one third of each at 3n). The parallel-axis theorem gives
the fixed expected values below. No private project results are used.
"""
import pytest
from civilpy.structural.aashto.lrfd import Flange, GirderSide
from civilpy.structural.aashto.lrfd.composite import CompositeGirder, modular_ratio


def _girder():
    side = GirderSide(
        top_flange=Flange("Grade 50", 1.0, 12.0),
        bottom_flange=Flange("Grade 50", 1.0, 12.0),
        web_material="Grade 50", web_thickness=0.5, web_depth=22.0,
        haunch=2.0,
    )
    return CompositeGirder(side, deck_t=8.0, deck_weff=96.0, n=8.0,
                           rebar_area=6.0, rebar_cover=2.0)


def test_modular_ratio_is_about_eight():
    assert modular_ratio(4.0) == pytest.approx(8.0, abs=0.1)


@pytest.mark.parametrize("state,area,y,inertia", [
    ("steel", 35.0, 12.0, 3619.666666666667),
    ("n", 131.0, 25.19083969465649, 12441.895674300255),
    ("3n", 67.0, 20.597014925373134, 9206.452736318408),
    # Cracked deck: six square inches of reinforcement at y=32.
    ("negative", 41.0, 612.0 / 41.0, 3619.666666666667 + 35 * 6 / 41 * 20**2),
])
def test_hand_calculated_section_properties(state, area, y, inertia):
    p = _girder().props(state)
    assert p.area == pytest.approx(area)
    assert p.y_na == pytest.approx(y)
    assert p.inertia == pytest.approx(inertia)


@pytest.mark.parametrize("state,moment,expected", [
    ("steel", 20.0, 0.7625011511188876),
    ("3n", 5.0, 0.13097562438631352),
    ("3n", 8.0, 0.20956099901810163),
    ("n", 280.0, 6.667892381175398),
])
def test_hand_calculated_service_stress(state, moment, expected):
    # sigma = 12 M (y_na - 0.5) / I, bottom flange centroid at y=0.5.
    cg = _girder()
    assert cg.props(state).stress(moment, cg.y_bottom_flange) == pytest.approx(expected)


def test_factored_stress_sums_construction_stages():
    expected = 1.25 * (0.7625011511188876 + 0.13097562438631352)
    expected += 1.5 * 0.20956099901810163 + 1.75 * 6.667892381175398
    assert _girder().flange_stress("bottom", {
        "dc1": 1.25 * 20, "dc2": 1.25 * 5, "dw": 1.5 * 8,
        "ll_pos": 1.75 * 280,
    }) == pytest.approx(expected)


def test_flange_fcf_selects_governing_direction():
    from civilpy.structural.aashto.lrfd import SpliceLoads
    # With no permanent loads, identical +/- live loads expose the difference
    # between the uncracked positive and cracked negative section.
    cg = _girder()
    loads = SpliceLoads(ll_pos_m=100.0, ll_neg_m=-100.0)
    positive = 1.75 * 100 * 0.023813901361340706
    negative = 1.75 * 100 * 12 * (612 / 41 - 0.5) / (10859 / 3 + 35 * 6 / 41 * 400)
    assert cg.flange_fcf("bottom", loads) == pytest.approx(max(positive, negative))


class TestDesignRolledSplice:
    """Synthetic end-to-end case, with computed composite flange stresses."""

    def test_synthetic_splice_without_supplied_fcf(self):
        from civilpy.structural.aashto.lrfd import (
            design_rolled_splice, SpliceLoads, BoltSpec, PlatePair, WebPlate,
        )
        loads = SpliceLoads(
            dc1_m=20.0, dc1_v=-12.0, dc2_m=5.0, dc2_v=-3.0,
            dw_m=8.0, dw_v=-5.0, ll_pos_m=280.0, ll_neg_m=-160.0,
            ll_neg_v=-30.0)
        plates = PlatePair("Grade 50", 0.5, 5.0, 0.5, 12.5, 2)
        d = design_rolled_splice(
            "W24X131", "W24X104", loads, grade="Grade 50",
            deck_thickness=8.0, deck_eff_width=96.0, deck_fc=4.0,
            rebar_area=6.0,
            bolts=BoltSpec("A325", 0.875, flange_threads_excluded=False,
                           web_threads_excluded=False, surface_class="C",
                           hole_type="oversize"),
            top_plates=plates, bottom_plates=plates,
            web_plate=WebPlate("Grade 50", 0.5, 2),
            top_flange_rows=2, bottom_flange_rows=2, web_rows=4,
            bolt_spacing=3.0, flange_edge=1.5, flange_end=1.5,
            web_edge=1.5, web_end=1.5, design_year=2016)
        # Low-stress floor; the top flange is in compression under positive
        # moment, so its design area is the gross area (pre-8th Ed.
        # 6.13.6.1.4c), not the effective net area.
        assert d.top_flange.design_force == pytest.approx(37.5 * 12.8 * 0.75)
        assert d.top_flange.total_bolts == 10
        assert d.bottom_flange.total_bolts == 10
        assert d.ok
