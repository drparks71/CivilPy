#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NDS/AASHTO adjustment factors in ``civilpy.structural.wood`` that
``tests/structural/test_wood.py`` does not reach: the flat-use factor
``Cfu`` (NDS 2024 Table 4.3.7), the bolt geometry factor ``C_delta``
(NDS 12.5.1: end distance Table 12.5.1A, spacing 12.5.1.2, edge distance
Table 12.5.1C) and its use inside ``Z_prime``, and the timber-stringer live
load distribution factor (AASHTO LRFD Table 4.6.2.2.2a-1).
"""

import pytest

from civilpy.structural.wood import (
    AdjustmentFactors,
    BoltConnection,
    GlulamSection,
    LumberSection,
    TimberStringer,
    units,
)


# ── Cfu: NDS Table 4.3.7 (members 2 in and 3 in thick, loaded on the wide face)

@pytest.mark.parametrize("depth, cfu", [(4, 1.10), (6, 1.15), (8, 1.15),
                                        (10, 1.20), (12, 1.20), (14, 1.20)])
def test_flat_use_factor_dimension_lumber(depth, cfu):
    af = AdjustmentFactors(LumberSection(2, depth, "Douglas Fir-Larch", "No. 2"))
    assert af.Cfu(flat_use=True) == cfu


def test_flat_use_factor_is_unity_when_not_flatwise():
    af = AdjustmentFactors(LumberSection(2, 10, "Douglas Fir-Larch", "No. 2"))
    assert af.Cfu() == 1.0
    assert af.Cfu(flat_use=False) == 1.0


def test_flat_use_factor_does_not_apply_to_beams_and_stringers_or_glulam():
    bs = AdjustmentFactors(LumberSection(6, 12, "Douglas Fir-Larch", "No. 1"))
    assert bs.section._cf_size_class() is None
    assert bs.Cfu(flat_use=True) == 1.0
    gl = AdjustmentFactors(GlulamSection(6.75, 30, "24F-V4", "Douglas Fir"))
    assert gl.Cfu(flat_use=True) == 1.0


# ── C_delta: NDS 12.5.1 geometry factor ────────────────────────────────────

@pytest.fixture
def conn():
    # 3/4 in bolt: full end 7D = 5.25 in, reduced 3.5D = 2.625 in,
    # edge 1.5D = 1.125 in, full spacing 4D = 3.0 in, reduced 3D = 2.25 in
    return BoltConnection(
        bolt_diameter=0.75 * units("in"), main_thickness=7.5 * units("in"),
        side_thickness=0.375 * units("in"), main_species_gravity=0.50,
        side_material="steel", loading="single_shear", angle_to_grain=0)


def _cd(conn, end, edge, spacing, row=None):
    kw = {} if row is None else {"row_spacing": row * units("in")}
    return conn.C_delta(end * units("in"), edge * units("in"), spacing * units("in"), **kw)


def test_geometry_factor_unity_at_full_dimensions(conn):
    assert _cd(conn, 7.0, 2.0, 4.0) == 1.0
    assert _cd(conn, 5.25, 1.125, 3.0) == 1.0          # exactly at the full minimums


def test_geometry_factor_reduced_end_distance_is_actual_over_full(conn):
    # NDS 12.5.1(c): C_delta = actual end distance / full end distance
    assert _cd(conn, 4.0, 2.0, 4.0) == round(4.0 / 5.25, 3) == 0.762
    assert _cd(conn, 3.625, 2.0, 4.0) == round(3.625 / 5.25, 3)


def test_geometry_factor_reduced_spacing_is_actual_over_full(conn):
    assert _cd(conn, 7.0, 2.0, 2.5) == round(2.5 / 3.0, 3) == 0.833
    assert _cd(conn, 7.0, 2.0, 2.25) == 0.75             # 3D reduced minimum


def test_geometry_factor_takes_the_smaller_reduction(conn):
    assert _cd(conn, 4.0, 2.0, 2.5) == 0.762              # min(0.762, 0.833)
    assert _cd(conn, 5.0, 2.0, 2.5) == 0.833              # min(0.952, 0.833)


def test_geometry_factor_zero_below_absolute_minimums(conn):
    assert _cd(conn, 2.5, 2.0, 4.0) == 0.0                # end < 3.5D = 2.625 in
    assert _cd(conn, 2.625, 2.0, 4.0) == 0.5              # exactly 3.5D -> 3.5/7
    assert _cd(conn, 7.0, 1.0, 4.0) == 0.0                # edge < 1.5D (pass/fail)
    assert _cd(conn, 7.0, 2.0, 2.0) == 0.0                # spacing < 3D
    assert _cd(conn, 2.5, 1.0, 2.0) == 0.0


def test_geometry_factor_scales_with_bolt_diameter():
    one_inch = BoltConnection(
        bolt_diameter=1.0 * units("in"), main_thickness=7.5 * units("in"),
        side_thickness=0.375 * units("in"), main_species_gravity=0.50,
        side_material="steel")
    # 4 in end distance is full for a 3/4 in bolt? no: 7D = 5.25 -> 0.762;
    # for a 1 in bolt 7D = 7 in -> 4/7 = 0.571, and 2.5 in spacing < 3D = 3 in -> 0
    assert _cd(one_inch, 4.0, 2.0, 4.0) == round(4.0 / 7.0, 3)
    assert _cd(one_inch, 4.0, 2.0, 2.5) == 0.0


def test_geometry_factor_row_spacing_is_ignored(conn):
    assert _cd(conn, 4.0, 2.0, 4.0, row=1.0) == _cd(conn, 4.0, 2.0, 4.0)


def test_z_prime_applies_geometry_factor_when_distances_given(conn):
    full = conn.Z_prime(num_bolts=2, num_bolts_in_row=2)
    assert full["factors"]["C_delta"] == 1.0
    red = conn.Z_prime(num_bolts=2, num_bolts_in_row=2,
                       end_distance=4.0 * units("in"), edge_distance=2.0 * units("in"),
                       bolt_spacing=4.0 * units("in"))
    assert red["factors"]["C_delta"] == 0.762
    assert red["factors"]["Cg"] == 1.00 and red["factors"]["CD"] == 1.0
    z = conn.Z_reference()["Z"]
    assert red["Z_prime"].magnitude == pytest.approx(round(z * 2 * 0.762, 1))
    assert red["Z_prime"].magnitude == pytest.approx(full["Z_prime"].magnitude * 0.762, rel=1e-3)
    assert red["Z_prime"].units == units("lbf").units


def test_z_prime_temperature_factor_bands(conn):
    assert conn.Z_prime(temperature_f=100.0)["factors"]["Ct"] == 1.0
    assert conn.Z_prime(temperature_f=110.0)["factors"]["Ct"] == 0.80
    assert conn.Z_prime(temperature_f=130.0)["factors"]["Ct"] == 0.70


# ── TimberStringer live-load distribution factor ───────────────────────────

def _stringer(spacing_ft, deck_type, num_lanes=1):
    sec = LumberSection(8, 16, "Douglas Fir-Larch", "Select Structural")
    return TimberStringer(sec, 20 * units("ft"), spacing_ft * units("ft"),
                          num_lanes=num_lanes, deck_type=deck_type)


@pytest.mark.parametrize("deck", ["nail_laminated", "spike_laminated", "glulam",
                                  "stress_laminated", "plank", "other"])
def test_distribution_factor_is_linear_in_spacing(deck):
    g4 = _stringer(4.0, deck).live_load_distribution_factor()
    g8 = _stringer(8.0, deck).live_load_distribution_factor()
    assert g4 > 0.0
    assert g8 == pytest.approx(2.0 * g4, abs=2e-3)       # S/D, rounded to 3 places


@pytest.mark.parametrize("deck", ["nail_laminated", "glulam", "stress_laminated", "plank"])
def test_shear_factor_equals_moment_factor(deck):
    ts = _stringer(4.0, deck, num_lanes=2)
    assert ts.live_load_distribution_factor_shear() == ts.live_load_distribution_factor()


def test_distribution_factor_unknown_deck_uses_s_over_5():
    assert _stringer(4.0, "concrete").live_load_distribution_factor() == 0.8
    assert _stringer(4.0, "concrete", num_lanes=2).live_load_distribution_factor() == 0.8


def test_distribution_factor_is_rounded_to_three_places():
    g = _stringer(3.1, "nail_laminated").live_load_distribution_factor()
    assert g == round(3.1 / 6.0, 3)
    assert g == round(g, 3)


# AASHTO LRFD Table 4.6.2.2.2a-1, "Wood Beams" (cross-sections a, l):
#   Plank                               S/6.7   S/7.5
#   Stressed Laminated                  S/9.2   S/9.0
#   Spike Laminated                     S/8.3   S/8.5
#   Glued Laminated Panels on Glued
#     Laminated Stringers               S/10.0  S/10.0
_LRFD_WOOD_BEAM_D = {
    "plank": (6.7, 7.5),
    "stress_laminated": (9.2, 9.0),
    "spike_laminated": (8.3, 8.5),
    "glulam": (10.0, 10.0),
}


@pytest.mark.xfail(strict=True, reason=(
    "BUG: TimberStringer.live_load_distribution_factor cites AASHTO LRFD Table "
    "4.6.2.2.2a-1 but divides S by 4.0/3.5 (plank), 7.0/5.5 (stress-lam), "
    "6.0/5.0 (spike/nail-lam) and 6.5/5.5 (glulam); the table gives S/6.7, "
    "S/7.5 ... S/10.0 (see _LRFD_WOOD_BEAM_D)"))
@pytest.mark.parametrize("deck", sorted(_LRFD_WOOD_BEAM_D))
@pytest.mark.parametrize("lanes", [1, 2])
def test_distribution_factor_matches_lrfd_table_4_6_2_2_2a_1(deck, lanes):
    d_one, d_two = _LRFD_WOOD_BEAM_D[deck]
    g = _stringer(4.0, deck, num_lanes=lanes).live_load_distribution_factor()
    assert g == pytest.approx(4.0 / (d_one if lanes == 1 else d_two), abs=5e-4)
