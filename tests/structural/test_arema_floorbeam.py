#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AREMA Chapter 15 floorbeam checks (ThroughPlateGirderFloorbeam.design_checks).

Properties over spans, spacings, shapes and options rather than one worked
example: statics of the two rail loads, the 1.15 A D / S distribution, the
impact curve, the Group II 1.25 increase, the compression-flange allowable,
fatigue categories, deflection against virtual work, and agreement with the
TPG floorbeam path that now calls it.
"""

from __future__ import annotations

import numpy as np
import pytest

from civilpy.general import units
from civilpy.structural.arema.rail_tpg_design import (
    FATIGUE_STRESS_RANGE, TPG, ThroughPlateGirderFloorbeam,
)

SPANS = [16, 20, 26, 34]                       # ft, girder centre to centre
SPACINGS = [1.5, 2.6, 4.0, 5.0, 7.0]           # ft, floorbeam spacing
SHAPES = ["W24X104", "W24X250", "W27X194", "W30X191"]


def fb(shape="W24X250", span=20, axle=100):
    return ThroughPlateGirderFloorbeam(shape=shape, fb_length=span * units("ft"),
                                       A=axle * units("kip"))


@pytest.mark.parametrize("span", SPANS)
@pytest.mark.parametrize("spacing", SPACINGS)
def test_live_load_statics_of_two_rail_loads(span, spacing):
    beam = fb(span=span)
    r = beam.design_checks(spacing * units("ft"))
    P = r.loads["P (per floorbeam)"]
    a = (span * units("ft") - beam.rr_gage) / 2
    assert r.loads["V_LL"].to("kip").magnitude == pytest.approx((P / 2).to("kip").magnitude)
    assert r.loads["M_LL"].to("kip*ft").magnitude == pytest.approx((P / 2 * a).to("kip*ft").magnitude)
    # 1.15 A D / S with D capped at the axle spacing S = 5 ft
    assert P.to("kip").magnitude == pytest.approx(1.15 * 100 * min(spacing, 5.0) / 5.0)


@pytest.mark.parametrize("axle", [50, 80, 100])
def test_live_load_effects_scale_with_the_axle_load(axle):
    base = fb(axle=100).design_checks(2.6 * units("ft")).loads
    r = fb(axle=axle).design_checks(2.6 * units("ft")).loads
    for key in ("P (per floorbeam)", "M_LL", "M_I", "V_LL", "V_I"):
        assert (r[key] / base[key]).magnitude == pytest.approx(axle / 100)
    assert r["M_DL"] == base["M_DL"] and r["M_W"] == base["M_W"]


def test_impact_curve_is_continuous_at_80_ft_and_decreasing():
    spans = np.arange(10, 140, 5.0)
    imp = [fb(span=L).design_checks(2 * units("ft")).loads["vertical impact"] for L in spans]
    assert np.all(np.diff(imp) < 0)
    near = [fb(span=L).design_checks(2 * units("ft")).loads["vertical impact"] for L in (79.999, 80.0)]
    assert near[0] == pytest.approx(near[1], abs=1e-4)


@pytest.mark.parametrize("ballasted", [True, False])
def test_ballasted_deck_takes_90_percent_of_impact(ballasted):
    open_ = fb().design_checks(2.6 * units("ft"), ballasted=False).loads["M_I"]
    r = fb().design_checks(2.6 * units("ft"), ballasted=ballasted).loads["M_I"]
    assert (r / open_).magnitude == pytest.approx(0.9 if ballasted else 1.0)


@pytest.mark.parametrize("span", SPANS)
@pytest.mark.parametrize("shape", SHAPES)
def test_group_ii_allowables_are_125_percent_of_group_i(span, shape):
    r = fb(shape, span).design_checks(2.6 * units("ft"))
    for part in ("Flexure, tension flange", "Flexure, compression flange", "Shear, web"):
        g1, g2 = r[f"{part}, Group I"], r[f"{part}, Group II"]
        assert (g2.allowable / g1.allowable).magnitude == pytest.approx(1.25)
        assert g2.demand >= g1.demand                      # wind only adds


@pytest.mark.parametrize("shape", SHAPES)
def test_compression_allowable_capped_and_falls_with_unbraced_length(shape):
    beam = fb(shape, 26)
    lengths = [2, 5, 10, 15, 20, 26]
    F = [beam.design_checks(2.6 * units("ft"), unbraced_length=Lb * units("ft"))
         ["Flexure, compression flange, Group I"].allowable.to("ksi").magnitude for Lb in lengths]
    assert max(F) <= 0.55 * 50 + 1e-9
    assert all(x >= y - 1e-9 for x, y in zip(F, F[1:]))


def test_heavier_shape_has_lower_ratios():
    light = fb("W24X104").design_checks(2.6 * units("ft"))
    heavy = fb("W24X250").design_checks(2.6 * units("ft"))
    for c_l, c_h in zip(light.checks, heavy.checks):
        assert c_h.ratio < c_l.ratio, c_l.name


def test_fatigue_ratio_rises_through_the_categories():
    beam = fb()
    order = ["A", "B", "B'", "C", "D", "E", "E'"]
    ratios = [beam.design_checks(2.6 * units("ft"), fatigue_category=k)[f"Fatigue, category {k}"].ratio
              for k in order]
    assert np.all(np.diff(ratios) > 0)
    assert list(FATIGUE_STRESS_RANGE) == order


@pytest.mark.parametrize("span", SPANS)
@pytest.mark.parametrize("shape", SHAPES)
def test_deflection_matches_virtual_work(span, shape):
    beam = fb(shape, span)
    r = beam.design_checks(2.6 * units("ft"))
    L = span * 12.0
    a = (span * units("ft") - beam.rr_gage).to("in").magnitude / 2
    F = (r.loads["V_LL"] * (1 + 0.9 * r.loads["vertical impact"])).to("kip").magnitude
    x = np.linspace(0, L, 20001)
    M = np.where(x < a, F * x, np.where(x > L - a, F * (L - x), F * a))
    m = np.where(x < L / 2, x / 2, (L - x) / 2)              # unit load at midspan
    EI = 29000 * beam.I_x.to("in^4").magnitude
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    delta = trapezoid(M * m, x) / EI
    got = r["Deflection"].demand.to("in").magnitude
    assert got == pytest.approx(delta, rel=1e-4)


def test_summary_properties():
    r = fb("W24X104", 34).design_checks(7 * units("ft"))
    assert r.governing.ratio == max(c.ratio for c in r.checks)
    assert r.ok == all(c.ratio <= 1 for c in r.checks)
    t = r.table()
    assert list(t.columns) == ["check", "article", "demand", "allowable", "ratio", "ok"]
    assert len(t) == len(r.checks) == 8


def test_holes_reduce_the_tension_flange_and_web_only():
    beam = fb()
    plain = beam.design_checks(2.6 * units("ft"))
    holed = beam.design_checks(2.6 * units("ft"), flange_holes=(2, 1 * units("in")),
                               web_holes=(6, 1 * units("in")))
    assert holed["Flexure, tension flange, Group I"].demand > plain["Flexure, tension flange, Group I"].demand
    assert holed["Shear, web, Group I"].demand > plain["Shear, web, Group I"].demand
    assert holed["Flexure, compression flange, Group I"].demand == plain["Flexure, compression flange, Group I"].demand


def test_built_up_floorbeam_runs_the_checks():
    beam = ThroughPlateGirderFloorbeam(rolled_shape=False)
    assert beam.depth.units == units("inch").units
    assert fb().design_checks(2.6 * units("ft")).checks[0].demand == \
        beam.design_checks(2.6 * units("ft")).checks[0].demand    # defaults = W24x250


def test_tpg_floorbeam_moment_agrees_with_design_checks():
    t = TPG()
    loads = t.fb_checks.loads
    m1 = loads["M_DL"] + loads["M_LL"] + loads["M_I"]
    # TPG takes rocking without the ballasted 0.9; everything else is the same
    rocking_gap = 0.1 * t.fb_M_re
    assert m1.to("kip*ft").magnitude == pytest.approx(
        (t.fb_M_tot_1 - rocking_gap).to("kip*ft").magnitude, rel=1e-6)
    assert t.end_fb_M_tot == max(t.end_fb_M_tot_1, t.end_fb_M_tot_2)
