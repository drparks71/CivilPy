#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``civilpy.structural.aashto.bearings`` beyond the happy-path Method A pad
in ``test_method_a_bearing.py``: the ``BearingSuitability`` lookup table
(AASHTO LRFD Table 14.6.2-1), ``get_bearing_strain`` and the Method A
(14.7.6) *failure* branches -- a grossly overloaded / over-thick pad that
trips the stress, deflection, shear-deformation and BDM 306.4 geometry
checks, and a thin, lightly loaded pad that trips the edge-cover, cover-layer,
anchorage (14.7.6.4) and steel-reinforcement (14.7.6.3.7) checks.  Failed
checks print a message, so stdout is captured and the text asserted.
"""

import contextlib
import io

import pytest

from civilpy.structural.aashto.bearings import (
    BearingSuitability,
    MethodABearing,
    get_bearing_strain,
    rubber_creep_values,
)


def _pad(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        b = MethodABearing(**kw)
    return b, buf.getvalue()


# ── BearingSuitability: Table 14.6.2-1 ─────────────────────────────────────

def test_suitability_defaults_and_table_shape():
    bs = BearingSuitability()
    assert (bs.type, bs.movement, bs.axis) == ("rectangular", "fixed", "x")
    assert BearingSuitability("circular", "expansion", "y").movement == "expansion"
    t = bs.table
    assert t.shape == (14, 8)
    assert list(t.columns) == ["Movement:Longitudinal", "Movement:Transverse",
                               "Rotation:Longitudinal", "Rotation:Transverse",
                               "Rotation:Vertical", "Load Resistance:Longitudinal",
                               "Load Resistance:Transverse", "Load Resistance:Vertical"]
    assert set(t.values.ravel()) <= {"S", "U", "R", "L"}
    assert t.equals(bs.get_table())


@pytest.mark.parametrize("bearing, col, code", [
    ("Plain Elastomeric Pad", "Movement:Longitudinal", "S"),
    ("Plain Elastomeric Pad", "Rotation:Vertical", "L"),
    ("Plain Elastomeric Pad", "Load Resistance:Vertical", "L"),
    ("Steel-Reinforced Elastomeric Bearing", "Load Resistance:Vertical", "S"),
    ("Cotton-duck-reinforced Pad", "Movement:Longitudinal", "U"),
    ("Cotton-duck-reinforced Pad", "Load Resistance:Vertical", "S"),
    ("Pot Bearing", "Movement:Longitudinal", "R"),
    ("Pot Bearing", "Rotation:Longitudinal", "S"),
    ("Pot Bearing", "Rotation:Vertical", "L"),
    ("Disc Bearing", "Load Resistance:Longitudinal", "S"),
    ("Rocker Bearing", "Movement:Longitudinal", "S"),
    ("Rocker Bearing", "Movement:Transverse", "U"),
    ("Rocker Bearing", "Rotation:Transverse", "S"),
    ("Rocker Bearing", "Rotation:Longitudinal", "U"),
    ("Single Roller Bearing", "Load Resistance:Longitudinal", "U"),
    ("Multiple Roller Bearing", "Rotation:Transverse", "U"),
    ("Plane Sliding Bearing", "Rotation:Longitudinal", "U"),
    ("Curved Sliding Spherical Bearing", "Rotation:Longitudinal", "S"),
    ("Curved Sliding Cylindrical Bearing", "Rotation:Longitudinal", "U"),
    ("Knuckle Pinned Bearing", "Load Resistance:Longitudinal", "S"),
])
def test_suitability_cells_match_table_14_6_2_1(bearing, col, code):
    assert BearingSuitability().table.loc[bearing, col] == code


def test_every_bearing_carries_vertical_load():
    # Table 14.6.2-1: no listed bearing is "U" for vertical load resistance
    col = BearingSuitability().table["Load Resistance:Vertical"]
    assert "U" not in set(col)
    assert (col == "S").sum() == 12 and (col == "L").sum() == 2


# ── get_bearing_strain ─────────────────────────────────────────────────────

@pytest.mark.parametrize("hardness", [50, 60, 70])
def test_bearing_strain_formula(hardness):
    # strain = sigma / (4.8 * 0.1125 * S^2): 1 ksi at S = 10 -> 1/54
    assert get_bearing_strain(1.0, 10.0, hardness) == pytest.approx(1.0 / 54.0)
    assert get_bearing_strain(0.0, 10.0, hardness) == 0.0


def test_bearing_strain_scales_linearly_with_stress_and_inverse_square_shape_factor():
    base = get_bearing_strain(1.0, 6.0, 60)
    assert get_bearing_strain(2.0, 6.0, 60) == pytest.approx(2.0 * base)
    assert get_bearing_strain(1.0, 12.0, 60) == pytest.approx(base / 4.0)
    assert get_bearing_strain(1.0, 6.0, 50) == get_bearing_strain(1.0, 6.0, 70)


@pytest.mark.parametrize("hardness", [55, 40, 0, "50"])
def test_bearing_strain_rejects_unsupported_hardness(hardness):
    assert get_bearing_strain(1.0, 10.0, hardness) == (
        "Error: Hardness not supported, please use 50, 60, or 70")


def test_creep_values_increase_with_hardness():
    # Table 14.7.6.2-1 creep deflection at 25 yr / instantaneous
    assert rubber_creep_values == {50: 0.25, 60: 0.35, 70: 0.45}


# ── Method A failure branches ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def overloaded():
    """40 x 30 in, 20 plies of 1/2 in @ 3/4 in shims under 3000 kip DL + 3000
    kip LL on a 1000 ft expansion length: fails the stress, deflection,
    shear-deformation, BDM and combined-strain checks."""
    return _pad(width=40.0, length=30.0, durometer=50, internal_t=0.5, external_t=0.25,
                steel_t=0.75, plys=20, span=100.0, expansion_length=1000.0,
                loads={"live": 3000.0, "total_dead_load": 3000.0, "total_load": 6000.0},
                max_dl_delta=1.0, max_ll_delta=0.5, max_ll_loc=50.0,
                deck_slope=0.02, plate_bev=0.0)


@pytest.fixture(scope="module")
def flimsy():
    """10 x 10 in, 3 x 1/2 in layers with 0.001 in shims and 0.4 in cover
    under 10 kip DL: fails edge cover, cover-layer thickness, anchorage and
    both steel-reinforcement checks."""
    return _pad(width=10.0, length=10.0, durometer=60, internal_t=0.5, external_t=0.4,
                steel_t=0.001, plys=3, span=50.0, expansion_length=200.0,
                loads={"live": 20.0, "total_dead_load": 10.0, "total_load": 30.0},
                max_dl_delta=0.1, max_ll_delta=0.1, max_ll_loc=25.0,
                deck_slope=0.0, plate_bev=0.0, edge_cover=0.1)


def test_overloaded_pad_derived_geometry(overloaded):
    b, _ = overloaded
    assert b.internal_shape_factor == pytest.approx(1200.0 / (2 * 0.5 * 70.0))   # 14.7.5.1-1
    assert b.total_elastomer_thickness == pytest.approx(2 * 0.25 + 19 * 0.5)      # 10 in
    assert b.total_laminate_thickness == pytest.approx(15.0)
    assert b.height == pytest.approx(0.5 + 9.5 + 15.0)
    assert b.service_ll == pytest.approx(5.0) and b.service_dl == pytest.approx(2.5)
    assert b.sigma_l == pytest.approx(2.5) and b.sigma_s == pytest.approx(2.5)
    # 14.7.6.3.4: delta_T = alpha * L * dT (in): 6e-6 * 1000 ft * 150 F * 12
    assert b.delta_t == pytest.approx(10.8) and b.delta_s == b.delta_t


def test_overloaded_pad_fails_stress_checks(overloaded):
    b, out = overloaded
    assert b.checks["#2 - Service LL Check"] == 0           # 14.7.6.3.2-7: sigma_s > 1.25 G S
    assert b.checks["#3 - Service LL < 1.25 ksi"] == 0      # 14.7.6.3.2-8
    assert "Service LL > 1.25 * G * S_i" in out and "Service LL > 1.25 ksi" in out
    assert b.service_ll > 1.25 * b.shear_modulus * b.internal_shape_factor


def test_overloaded_pad_fails_deflection_checks(overloaded):
    b, out = overloaded
    assert b.ll_deflection > 0.125
    assert b.checks["#5 - LL Deflection < 0.125"] == 0      # 14.7.6.3.3
    assert b.checks["#6 - Single Layer's Δ < 0.09 * h_ri"] == 0
    assert b.checks["#7 - Single Layer's Δ < 0.09 * h_ri"] == 0
    assert "LL Deflection > 0.125" in out
    assert out.count("Total Deflection / Number of Plies > 0.09 * h_ri") == 2
    assert "Due to Long term Creep" in out


def test_overloaded_pad_fails_shear_deformation(overloaded):
    b, out = overloaded
    assert 2 * b.delta_s > b.total_elastomer_thickness      # 14.7.6.3.4-1: h_rt >= 2 delta_s
    assert b.checks["#8 - Thermal Expansion"] == 0
    assert "2 * delta_s > h_ri" in out


def test_overloaded_pad_fails_bdm_and_geometry_limits(overloaded):
    b, out = overloaded
    assert b.checks['#9 - Maximum Elastomer height > 5"'] == 0       # BDM 306.4
    assert b.checks['#10 - Maximum laminate height < 1"'] == 0
    assert b.checks["#11 - Laminate Width / 3 > Total Laminate Thickness"] == 0   # 14.7.6.3.6
    assert b.checks["#12 - Bearing Length / 3 > Total Laminate Thickness"] == 0
    assert b.checks["#13 - Bearing Area < 1000"] == 0
    assert b.checks['#14 - Total elastomer thickness < 8"'] == 0
    assert "total elastomer height > 5" in out and "total laminate height > 1" in out
    assert out.count("Geometry Check Failed") == 4


def test_overloaded_pad_fails_combined_strain_but_passes_anchorage_and_steel(overloaded):
    b, out = overloaded
    assert b.checks["#18 - Total Strain"] == 0 and b.checks["#19 - Total Strain Check 2"] == 0
    assert "Combined Strain Check Failed" in out and "Combined Strain Check 2 Failed" in out
    assert b.checks["#15 - Total Dead Load"] == 1            # H = 123 kip << 3000 kip
    assert b.checks["#16 - Steel Reinforcement - Service Limit State"] == 1
    assert b.checks["#17 - Steel Reinforcement - Service Limit State"] == 1
    assert "Anchorage" not in out and "laminate service" not in out


def test_flimsy_pad_fails_edge_cover_and_cover_layer(flimsy):
    b, out = flimsy
    assert b.checks["Steel Laminate Edge Cover Check"] == 0            # 14.7.6.1: >= 1/4 in
    assert 'Steel Laminate Edge Cover > 1/4" - Failed' in out
    assert b.checks['External Thickness Check > 5/16"'] == 0           # 0.4 in > 5/16 in
    assert "External Thickness > 70% Internal" not in b.checks         # first branch wins
    assert 'External Thickness Check Failed > 5/16"' in out


def test_flimsy_pad_needs_anchorage(flimsy):
    b, out = flimsy
    # 14.7.6.4: H = G A delta_s / h_rt = 0.095 * 100 * 2.16 / 1.8 = 11.4 kip > 10 kip DL
    H = b.shear_modulus * b.length * b.width * b.delta_t / b.total_elastomer_thickness
    assert H == pytest.approx(11.4) and H > b.loads["total_dead_load"]
    assert b.checks["#15 - Total Dead Load"] == 0
    assert "Anchorage is required" in out


def test_flimsy_pad_fails_steel_reinforcement(flimsy):
    b, out = flimsy
    # 14.7.6.3.7: h_s >= 3 h_ri sigma_s / Fy and >= 2 h_ri sigma_L / dF_TH
    assert b.steel_t < 3 * b.internal_t * b.sigma_s / b.f_y
    assert b.steel_t < 2 * b.internal_t * b.sigma_l / 24
    assert b.checks["#16 - Steel Reinforcement - Service Limit State"] == 0
    assert b.checks["#17 - Steel Reinforcement - Service Limit State"] == 0
    assert "Steel laminate service limit state check failed" in out
    assert "Steel laminate fatigue limit state check failed" in out
    assert b.checks["#2 - Service LL Check"] == 1 and b.checks["#13 - Bearing Area < 1000"] == 1


def test_cover_layer_over_70_percent_of_internal_layer():
    # 0.3 in cover < 5/16 in, but > 0.7 * 0.4 in internal
    b, out = _pad(width=10.0, length=10.0, durometer=60, internal_t=0.4, external_t=0.3,
                  steel_t=0.1, plys=3, span=50.0, expansion_length=20.0,
                  loads={"live": 20.0, "total_dead_load": 40.0, "total_load": 60.0},
                  max_dl_delta=0.1, max_ll_delta=0.1, max_ll_loc=25.0,
                  deck_slope=0.0, plate_bev=0.0)
    assert b.checks["External Thickness > 70% Internal"] == 0
    assert 'External Thickness Check > 5/16"' not in b.checks
    assert "70% of Internal Thickness" in out
    assert b.checks["Steel Laminate Edge Cover Check"] == 1


@pytest.mark.xfail(strict=True, reason=(
    "BUG: run_checks records a failed check #7 under '#7 - Single Layer's Δ < "
    "0.09 * h_ri' but a passed one under '... - Due to Long term Creep', so "
    "the key a caller reads depends on the outcome"))
def test_check_7_key_is_the_same_whether_it_passes_or_fails(overloaded):
    b, _ = overloaded
    assert "#7 - Single Layer's Δ < 0.09 * h_ri - Due to Long term Creep" in b.checks


@pytest.mark.xfail(strict=True, reason=(
    "BUG: checks #13 (area < 1000 in2) and #14 (h_rt < 8 in) print the #12 "
    "message 'Bearing Length / 3 > Total Laminate Thickness' when they fail"))
def test_checks_13_and_14_print_their_own_messages(overloaded):
    _, out = overloaded
    assert out.count("Bearing Length / 3 > Total Laminate Thickness") == 1
