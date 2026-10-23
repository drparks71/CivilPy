#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AISC *Moments, Shears and Reactions for Continuous Highway Bridges*
(1959, rev. 1986): Table 2.0 (two equal spans, HS20-44, every tabulated
length) and the influence coefficients of Table A3.7 (three spans L, 1.7L,
L) reproduced with ContinuousBeam influence lines and
InfluenceLine.hs20_44_effect.  The digitized tables are in
``tests/structural/data`` (table_2_0.csv, table_A3_7_span1.csv)."""

import csv
from pathlib import Path

import pytest

from civilpy.structural.aashto.vehicles import HS20Load
from civilpy.structural.continuous_beam import ContinuousBeam, UnitResponses, _Point

DATA = Path(__file__).parent / "data"
TABLE_2_0 = list(csv.DictReader(open(DATA / "table_2_0.csv")))
TABLE_A3_7 = list(csv.DictReader(open(DATA / "table_A3_7_span1.csv")))


def _row_id(r):
    return f"L{r['L_ft']}"


@pytest.mark.parametrize("row", TABLE_2_0, ids=_row_id)
def test_table_2_0_reactions_and_negative_moment(row):
    span = float(row["L_ft"])
    beam = ContinuousBeam([0.0, span, 2 * span])
    r_a = beam.reaction_influence_line(0, per_span=200).hs20_44_effect(concentrated="shear")
    r_b = beam.reaction_influence_line(1, per_span=200).hs20_44_effect(concentrated="shear")
    m_b = beam.continuous_moment_influence_line(span, per_span=200).hs20_44_effect(
        sign=-1, second_concentrated=True)
    assert r_a["total"] == pytest.approx(float(row["R_A"]), abs=0.06)
    assert r_b["total"] == pytest.approx(float(row["R_B"]), abs=0.06)
    assert m_b["total"] == pytest.approx(float(row["M_B"]), abs=0.15)


@pytest.mark.parametrize("row", TABLE_2_0[::2], ids=_row_id)
def test_table_2_0_shear_and_positive_moment(row):
    span = float(row["L_ft"])
    beam = ContinuousBeam([0.0, span, 2 * span])
    v = beam.shear_influence_line(span, per_span=200).hs20_44_effect(
        sign=-1, concentrated="shear", step=0.005)
    assert v["total"] == pytest.approx(float(row["V_AB_B"]), abs=0.06)
    # the maximum positive moment in AB: the truck envelope (the lane load
    # never governs positive moment in this table)
    env = UnitResponses.from_beam(beam, step=0.25).envelope([8.0, 32.0, 32.0], [0.0, 14.0, 28.0])
    in_ab = env.stations <= span
    assert env.moment_max[in_ab].max() == pytest.approx(float(row["M_AB_X"]), abs=0.15)
    lane = max(beam.continuous_moment_influence_line(f * span, per_span=200).hs20_44_effect()["lane"]
               for f in (0.4, 0.42, 0.44))
    assert lane < float(row["M_AB_X"])


@pytest.mark.parametrize("row", TABLE_2_0, ids=_row_id)
def test_table_2_0_impact(row):
    span = float(row["L_ft"])
    assert HS20Load.impact_factor(span) == pytest.approx(float(row["imp_I"]), abs=6e-4)
    assert HS20Load.impact_factor(2 * span) == pytest.approx(float(row["imp_IV"]), abs=6e-4)


def test_table_2_0_dead_load_coefficients():
    beam = ContinuousBeam([0.0, 1.0, 2.0]).add_udl(1.0)
    r = beam.reactions()
    assert (r[0], r[1]) == (pytest.approx(0.375), pytest.approx(1.25))
    assert beam.shear_at(1.0) == pytest.approx(-0.625)
    assert beam.moment_at(1.0) == pytest.approx(-0.125)
    assert beam.moment_at(0.375) == pytest.approx(0.0703, abs=5e-5)


def test_lane_governs_the_long_spans_and_truck_the_short():
    short = ContinuousBeam([0.0, 30.0, 60.0]).continuous_moment_influence_line(
        30.0, per_span=200).hs20_44_effect(sign=-1, second_concentrated=True)
    long = ContinuousBeam([0.0, 120.0, 240.0]).continuous_moment_influence_line(
        120.0, per_span=200).hs20_44_effect(sign=-1, second_concentrated=True)
    assert not short["lane_governs"] and long["lane_governs"]


@pytest.mark.parametrize("row", TABLE_A3_7, ids=lambda r: f"P@{r['load_at']}")
def test_table_a3_7_influence_coefficients(row):
    # three spans L, 1.7 L, L; unit load at tenth points of span 1 or 2,
    # moments / (P L) at the tenth points of span 1 and at B
    n = 1.7
    beam = ContinuousBeam([0.0, 1.0, 1.0 + n, 2.0 + n])
    span, tenth = row["load_at"].split(".")
    x_load = int(tenth) / 10 if span == "1" else 1.0 + n * int(tenth) / 10
    for k in range(1, 10):
        got = beam.moment_at(k / 10, [_Point(1.0, x_load)])
        assert got == pytest.approx(float(row[f"M.{k}"]), abs=6e-5), k
    assert beam.moment_at(1.0, [_Point(1.0, x_load)]) == pytest.approx(float(row["M_B"]), abs=6e-5)


def test_hl93_dual_truck_negative_moment():
    # LRFD 3.6.1.3.1: 90 % of two trucks (>= 50 ft apart) + 90 % lane at the pier
    # of two 100 ft spans, against a brute-force placement on ContinuousBeam
    import numpy as np
    beam = ContinuousBeam([0.0, 100.0, 200.0])
    il = beam.continuous_moment_influence_line(100.0, per_span=200)
    r = il.hl93_effect(sign=-1, dual_truck=True)
    assert r["dual_truck_governs"]
    lane = -0.64 * 100.0 ** 2 / 8.0                              # both spans loaded: -wL^2/8
    best = 0.0
    ps = [8.0, 32.0, 32.0, 8.0, 32.0, 32.0]
    for a in np.arange(-56.0, 200.0, 0.5):                       # first axle position
        for gap in np.arange(50.0, 150.0, 1.0):
            xs = [a, a + 14.0, a + 28.0, a + 28.0 + gap, a + 42.0 + gap, a + 56.0 + gap]
            loads = [_Point(p, x) for p, x in zip(ps, xs) if 0.0 <= x <= 200.0]
            best = min(best, beam.moment_at(100.0, loads))
    expected = 0.9 * (best * 1.33 + lane)
    assert r["total"] == pytest.approx(expected, rel=5e-3)
    single = il.hl93_effect(sign=-1)
    assert r["total"] < single["total"]


def test_dual_truck_only_between_points_of_contraflexure():
    beam = ContinuousBeam([0.0, 100.0, 200.0])
    near_pier = beam.continuous_moment_influence_line(90.0, per_span=200)
    mid_span = beam.continuous_moment_influence_line(40.0, per_span=200)
    # uniform load on both spans: contraflexure at 0.75 L from the abutments
    assert near_pier.hl93_effect(sign=-1, dual_truck="contraflexure")["in_negative_region"]
    far = mid_span.hl93_effect(sign=-1, dual_truck="contraflexure")
    assert not far["in_negative_region"] and "dual_truck" not in far
    assert far["total"] == pytest.approx(mid_span.hl93_effect(sign=-1)["total"])
