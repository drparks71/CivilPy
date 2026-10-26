"""Gusset checks: reproduce the 2012 ODOT OSE LFR gusset rating sheet
numbers (LFR path) and sanity-check the LRFD 6.14.2.8 path."""
import math

import pytest

from civilpy.structural.aashto.lrfd import gusset as g


# ---- 2012 workbook, joint 42133 display (vertical U126-L126, chord L125-L126) --
def test_lfr_rivet_check_reproduces_2012_capacities():
    r = g.lfr_rivet_check(n_fasteners=134, d=1.0, t_gusset_total=1.5, t_base_total=1.25,
                          connection_length=62.6)
    assert r.details["C_shear"] == pytest.approx(1744.514, rel=1e-4)      # 134*0.785*20.72*0.8
    assert r.details["C_bearing_gusset"] == pytest.approx(8140.5, rel=1e-4)
    assert r.details["C_bearing_base"] == pytest.approx(6783.75, rel=1e-4)
    assert r.capacity == pytest.approx(1744.514, rel=1e-4)
    r2 = g.lfr_rivet_check(80, 1.0, 1.5, 0.75, 38.398)
    assert r2.details["C_shear"] == pytest.approx(1301.876, rel=1e-4)      # no long-joint reduction


def test_lfr_whitmore_tension_reproduces_2012():
    r = g.lfr_whitmore_tension(a_gross=29.25, a_net=22.5, fy=45.0, beta=0.15)
    assert r.details["Ae"] == pytest.approx(26.8875, rel=1e-4)
    assert r.capacity == pytest.approx(1209.938, rel=1e-4)


def test_lfr_block_shear_reproduces_2012():
    # one plate: Avg 60.225, Avn 44.194, Atg 14.625, Atn 11.25 -> 2005.467 / 2084.53 per plate
    r = g.lfr_block_shear(60.225, 44.194, 14.625, 11.25)
    assert r.details["C1"] * 2 == pytest.approx(4010.933, rel=1e-4)
    assert r.details["C2"] * 2 == pytest.approx(4169.065, rel=1e-4)
    assert r.capacity * 2 == pytest.approx(4010.933, rel=1e-4)


def test_lfr_global_shear_reproduces_2012():
    r = g.lfr_global_shear(a_gross=39.931 * 1.5, a_net=30.368 * 1.5)
    assert r.details["C_yield"] == pytest.approx(1156.841, rel=1e-4)
    assert r.details["C_fracture"] == pytest.approx(1572.025, rel=1e-4)


# ---- joint 11000 (U0, truss A): Trouble-Shoot RFs 5.149 (rivets) and 16.018 (buckling)
def test_lfr_joint_11000_rating_factors():
    # diagonal U0L1 governs the rivet check: 60 rivets both plates, L = 36 in,
    # DL +313.2 k, HS-20 inventory LL +50.95 k (no impact, no MPF in the sheet), f2 = 2.17
    rf_d = g.lfr_rating_factor(g.lfr_rivet_check(60, 1.0, 1.25, 1.0, 36.0).capacity, 313.2, 50.95)
    assert rf_d == pytest.approx(5.149, rel=2e-3)
    # vertical U0L0 buckling: Whitmore b 47.971 in x 0.625 in x 2 plates, Lc 6.372, K 1.2
    comp = g.lfr_whitmore_compression(a_gross=47.971 * 0.625 * 2, t=0.625, lc=6.372)
    rf_v = g.lfr_rating_factor(comp.factored_capacity, 326.9, 49.1)
    assert rf_v == pytest.approx(16.018, rel=2e-3)


# ---- LRFD path sanity ----------------------------------------------------
def test_lrfd_functions_basic():
    f = g.fastener_shear_resistance(60, 1.0, 46.0, rivet=True, connection_length=36.0)
    assert f.capacity == pytest.approx(60 * 0.7854 * 0.75 * 46.0, rel=1e-3)
    assert f.phi == 0.80
    t = g.whitmore_tension_resistance(29.25, 22.5, 45.0, 70.0)
    assert t.capacity == pytest.approx(min(0.95 * 45 * 29.25, 0.80 * 70 * 22.5))
    c = g.whitmore_compression_resistance(59.96, 0.625, 6.372, 45.0)
    assert 0 < c.capacity <= 45.0 * 59.96 and c.phi == 0.75
    s = g.plate_shear_resistance(59.9, 45.55, 45.0, 70.0)
    assert s.details["R_yield"] == pytest.approx(0.58 * 45 * 59.9 * 0.88)
    e = g.edge_slenderness_ok(20.761, 0.75, 45.0)
    assert e.ok and e.details["limit_L_over_t"] == pytest.approx(2.06 * (29000 / 45) ** 0.5)
    b = g.block_shear_resistance(60.225, 44.194, 11.25, 45.0, 70.0)
    assert b.phi == 0.80


# --------------------------------------------------------------------------- #
# Chord splices (MBE 6A.6.12.6.9) and pins (6.7.6.2)
# --------------------------------------------------------------------------- #
def test_chord_splice_section_symmetric_has_no_eccentricity():
    # chord centred on the plate: splice plates add area but no eccentricity
    sec = g.chord_splice_section(h_plate=40.0, t_plates=1.0, d_chord=20.0, t_splice=1.0, chord_at="bottom", edge=10.0)
    assert sec["A"] == pytest.approx(60.0)
    assert sec["e_p"] == pytest.approx(0.0)
    assert sec["y_c"] == pytest.approx(20.0)


def test_chord_splice_section_lower_chord_eccentricity_and_modulus():
    # plate 40 x 1, no splice plates, chord 20 deep at the bottom: force at 10, centroid at 20
    sec = g.chord_splice_section(h_plate=40.0, t_plates=1.0, d_chord=20.0)
    assert sec["e_p"] == pytest.approx(10.0)
    assert sec["S"] == pytest.approx(1.0 * 40.0 ** 2 / 6.0)     # to the bottom edge, c = 20
    top = g.chord_splice_section(h_plate=40.0, t_plates=1.0, d_chord=20.0, chord_at="top")
    assert top["e_p"] == pytest.approx(10.0) and top["S"] == pytest.approx(sec["S"])


def test_chord_splice_resistance_amplifier_and_factors():
    sec = g.chord_splice_section(h_plate=40.0, t_plates=1.0, d_chord=20.0)
    c = g.chord_splice_resistance(sec["A"], sec["S"], sec["e_p"], 33.0, compression=True)
    amp = 1.0 + 10.0 * 40.0 / (40.0 ** 2 / 6.0)                   # 1 + e A / S = 2.5
    assert c.details["amplifier"] == pytest.approx(amp)
    assert c.capacity == pytest.approx(0.85 * 33.0 * 40.0 / amp)
    t = g.chord_splice_resistance(sec["A"], sec["S"], sec["e_p"], 33.0, compression=False, fu=60.0, a_n=36.0, s_n=240.0)
    assert t.details["R_yield"] == pytest.approx(0.95 * 33.0 * 40.0 / amp)
    assert t.details["R_fracture"] == pytest.approx(0.80 * 60.0 * 36.0 / (1.0 + 10.0 * 36.0 / 240.0))
    assert t.capacity == pytest.approx(min(t.details["R_yield"], t.details["R_fracture"]))


def test_chord_splice_compression_slenderness():
    sec = g.chord_splice_section(h_plate=40.0, t_plates=1.0, d_chord=20.0)
    short = g.chord_splice_resistance(sec["A"], sec["S"], sec["e_p"], 33.0, compression=True, l_splice=5.0, t=0.5)
    assert short.details["Fcr"] == pytest.approx(33.0)              # K L / r = 0.5*5/(0.5/sqrt 12) = 17.3 <= 25
    long = g.chord_splice_resistance(sec["A"], sec["S"], sec["e_p"], 33.0, compression=True, l_splice=60.0, t=0.5)
    assert long.details["Fcr"] < 33.0                               # K L / r = 208: column curve


def test_pin_bearing_and_shear():
    b = g.pin_bearing_resistance(4.5, 4.0, 33.0)
    assert b.capacity == pytest.approx(1.5 * 4.0 * 4.5 * 33.0) and b.phi == 1.0
    v = g.pin_shear_resistance(4.5, 33.0)
    assert v.capacity == pytest.approx(2 * 0.58 * 33.0 * math.pi * 4.5 ** 2 / 4.0)


def test_pin_flexure_and_interaction():
    m = g.pin_flexure_resistance(7.0, 33.0)
    assert m.capacity == pytest.approx(33.0 * 343.0 / 6.0)
    assert g.pin_interaction(0.6 * m.capacity, m.capacity, 0.8 * 100.0, 100.0) == pytest.approx(0.36 + 0.64)
