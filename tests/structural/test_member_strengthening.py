#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Steel truss member strengthening against FHWA HIF-18-042 (Design Example
- Steel Truss Member Strengthening, Modjeski and Masters, 2018): U19-L20, a
12WF72 tension member, and L20-U21, two laced C15x33.9 in compression, on a
1958 Tennessee deck truss, rated for HL-93 and strengthened with bolted
plates.  Values quoted from the example are its own rounding."""

import math

import pytest

from civilpy.structural.aashto.lrfd import (
    bolt_bearing_resistance, bolt_shear_resistance, bolt_slip_resistance,
    box_flexure_7th, box_torsion_constant, combined_axial_flexure,
    compression_member_resistance, modified_slenderness, rivet_shear_resistance,
    tension_member_resistance, weak_axis_flexure)
from civilpy.structural.member_strengthening import (
    Material, MemberForces, StrengthenedMember, beam_column_magnifier,
    fasteners_to_develop, interaction_rating_factor, magnified_rating_factor,
    rivets_removed_capacity, staggered_net_width)

L_IN = 568.8125                                   # 47'-4 13/16"
TENSION = MemberForces(130, 10, 266, 48, 12, 72)   # U19-L20, new condition
COMPRESSION = MemberForces(-147, -13, -133, 132, 12, 48)


# ── Step 1: existing member resistances ────────────────────────────────────


def test_tension_member_existing_resistance():
    r = tension_member_resistance(a_g=21.16, f_y=33, a_n=16.87, f_u=60, u_shear_lag=0.90)
    assert r.details["yield"] == pytest.approx(663.4, abs=0.05)
    assert r.details["rupture"] == pytest.approx(728.8, abs=0.05)
    assert r.details["governing"] == "yield"
    flex = weak_axis_flexure(b_f=12.04, t_f=0.671, f_yf=33, z_y=49.2, s_y=25.57)
    assert flex.details["lambda_f"] == pytest.approx(8.97, abs=0.005)
    assert flex.details["lambda_pf"] == pytest.approx(11.26, abs=0.005)
    assert flex.details["lambda_rf"] == pytest.approx(24.6, abs=0.05)
    assert flex.capacity / 12 == pytest.approx(135.3, abs=0.05)          # k-ft


def test_compression_member_existing_resistance():
    klr_m = modified_slenderness(0.75 * L_IN / 5.41, a=12.0, r_i=0.904)
    assert klr_m == pytest.approx(79.96, abs=0.01)
    c = compression_member_resistance(a_g=19.8, f_y=33, kl_over_r=klr_m)
    assert c.details["Po"] == pytest.approx(653.4, abs=0.05)
    assert c.details["Pe"] == pytest.approx(886.4, abs=0.2)
    assert c.capacity == pytest.approx(479.9, abs=0.05)
    # equivalent box of the laced channels (AISC DG 9 Table 3.1)
    t_fe = 2 * 0.65 * 3.4 / 12.25
    assert t_fe == pytest.approx(0.36, abs=0.005)
    j = box_torsion_constant(b=12.25 - 0.4, h=15.0 - t_fe, t_flange=t_fe, t_web=0.4)
    assert j == pytest.approx(865.9, rel=0.002)       # example rounds t_fe to 0.36
    m = box_flexure_7th(f_y=33, s=79.1, i_y=553.5, j=j, length=568.8)
    assert m.details["M_CR"] == pytest.approx(68_803, rel=0.001)
    assert m.capacity == pytest.approx(2_586, abs=1.0)


# ── Step 2: existing member D/C and load rating ────────────────────────────


def test_existing_tension_member_is_8_percent_over():
    p_u, m_u = TENSION.factored()
    assert (p_u, m_u) == (pytest.approx(643.0, abs=0.5), pytest.approx(204.0))
    c = combined_axial_flexure(p_u, 663.4, m_ux=m_u, m_rx=1623.6)
    assert c.details["equation"] == "6.8.2.3-2"
    assert c.demand == pytest.approx(1.08, abs=0.005)
    assert interaction_rating_factor(663.4, 1623.6, TENSION) == pytest.approx(0.894, abs=0.001)


def test_existing_compression_member_rating_iterates_delta_b():
    # the example takes Pr = Pn = 479.9 k for the existing member (no phi_c)
    # and Pe of the y-axis with K L = 0.75 L
    p_e = math.pi ** 2 * 29_000 * 579.2 / (0.75 * 568.8) ** 2
    assert p_e == pytest.approx(910.9, abs=0.1)
    p_u, m_u = COMPRESSION.factored()
    db = beam_column_magnifier(p_u, p_e)
    assert db == pytest.approx(1.92, abs=0.005)
    c = combined_axial_flexure(p_u, 479.9, m_ux=db * m_u, m_rx=2586, compression=True)
    assert c.demand == pytest.approx(1.08, abs=0.005)

    def rf(d):
        return interaction_rating_factor(479.9, 2586, COMPRESSION, delta_b=d)

    value, db, history = magnified_rating_factor(rf, COMPRESSION, p_e)
    assert history[0][1] == pytest.approx(0.843, abs=0.001)      # first iteration
    assert history[1][0] == pytest.approx(1.781, abs=0.001)
    assert value == pytest.approx(0.863, abs=0.001)               # after four
    assert db == pytest.approx(1.797, abs=0.001)


# ── Steps 3-4: strengthening and strengthened rating ───────────────────────


def _tension_strengthened(hif):
    return StrengthenedMember(existing=Material(21.16, 33, 60, a_n=16.87, s=25.57),
                              added=Material(15.0, 50, 65, a_n=11.0),
                              s_existing=48.8, s_added=48.8, u=0.90,
                              hif_shared_stress=hif)


def _compression_strengthened(hif):
    # the example's locked-in allowable 24.24 ksi is Pn / Ag (phi_c omitted),
    # the shared one 19.29 ksi is phi_c Pn / Ag of the strengthened member
    return StrengthenedMember(existing=Material(19.8, 33, 60, s=79.1),
                              added=Material(6.0, 50, 65),
                              s_existing=81.17, s_added=188.59, compression=True,
                              pn_existing=479.9 / 0.95, pn_strengthened=523.9,
                              fb_allow=(2586 / 79.1, 2586 / 79.1),
                              hif_shared_stress=hif)


def test_tension_strengthening_reproduces_the_example():
    m = _tension_strengthened(hif=True)
    st = m.stresses(TENSION)
    assert st["existing"]["a_g DC"] == pytest.approx(6.14, abs=0.005)
    assert st["existing"]["a_n DC"] == pytest.approx(7.71, abs=0.005)
    assert st["existing"]["b DC"] == pytest.approx(1.88, abs=0.005)
    assert st["existing"]["a_g LL"] == pytest.approx(4.30, abs=0.005)
    assert st["added"]["a_g LL"] == pytest.approx(3.05, abs=0.01)
    assert st["existing"]["a_n LL"] == pytest.approx(5.77, abs=0.01)
    assert st["added"]["a_n LL"] == pytest.approx(3.77, abs=0.005)
    assert st["existing"]["b LL"] == pytest.approx(1.48, abs=0.005)
    al = m.allowables()
    assert (al["existing"]["a_g"], al["existing"]["a_n"]) == (pytest.approx(31.35), pytest.approx(43.2))
    assert (al["added"]["a_g"], al["added"]["a_n"]) == (pytest.approx(47.5), pytest.approx(46.8))
    r = m.ratios(TENSION)
    assert r["existing"]["axial gross"] == pytest.approx(0.492, abs=0.002)
    assert r["existing"]["axial net"] == pytest.approx(0.465, abs=0.001)
    assert r["existing"]["flexure"] == pytest.approx(0.161, abs=0.001)
    assert r["existing"]["interaction"] == pytest.approx(0.635, abs=0.002)
    assert r["added"]["axial net"] == pytest.approx(0.146, abs=0.001)
    assert r["added"]["interaction"] == pytest.approx(0.132, abs=0.001)
    assert m.rating_factor(TENSION) == pytest.approx(2.18, abs=0.005)


def test_compression_strengthening_reproduces_the_example():
    klr = modified_slenderness(0.75 * 568.8 / 4.99, 12.0, 0.904)
    assert klr == pytest.approx(86.48, rel=0.001)
    c = compression_member_resistance(a_g=25.8, f_y=33, kl_over_r=klr)
    assert c.details["Pe"] == pytest.approx(987.4, rel=0.001)
    # Eq. 6.9.4.1.1-1 gives 593.3 k; the example prints 523.9 k, which is
    # 0.658^(Pe/Po) Po -- the exponent inverted (conservative).  The
    # published rating below is reproduced with the example's 523.9 k.
    assert c.capacity == pytest.approx(593.3, abs=0.2)
    po, pe = c.details["Po"], 987.4
    assert 0.658 ** (pe / po) * po == pytest.approx(523.9, abs=0.2)
    m = _compression_strengthened(hif=True)
    al = m.allowables()["existing"]
    assert (al["a_g locked"], al["a_g shared"], al["b"]) == (
        pytest.approx(24.24, abs=0.005), pytest.approx(19.29, abs=0.005), pytest.approx(32.69, abs=0.005))
    r = m.ratios(COMPRESSION)
    assert r["existing"]["axial"] == pytest.approx(0.77, abs=0.005)
    assert r["existing"]["flexure"] == pytest.approx(0.10, abs=0.005)
    rf, db = m.rating_factor(COMPRESSION, p_e=c.details["Pe"])
    assert rf == pytest.approx(1.13, abs=0.006)
    assert db == pytest.approx(1.90, abs=0.005)


@pytest.mark.parametrize("build,forces", [(_tension_strengthened, TENSION),
                                          (_compression_strengthened, COMPRESSION)])
def test_shared_stress_is_strain_compatible_by_default(build, forces):
    # one modulus: the shared load stresses every material equally, and the
    # materials' forces add back to the applied force.  HIF-18-042 scales the
    # stress by each material's area fraction, which understates it.
    m, hif = build(False), build(True)
    st = m.stresses(forces)
    for case, p in (("DW", forces.p_dw), ("LL", forces.p_ll)):
        assert st["existing"][f"a_g {case}"] == pytest.approx(st["added"][f"a_g {case}"])
        total = sum(st[k][f"a_g {case}"] * getattr(m, k).a_g for k in ("existing", "added"))
        assert total == pytest.approx(abs(p))
        frac = m.existing.a_g / m.a_g
        assert hif.stresses(forces)["existing"][f"a_g {case}"] == pytest.approx(frac * st["existing"][f"a_g {case}"])
    corrected = m.rating_factor(forces) if not m.compression else m.rating_factor(
        forces, p_e=987.4)[0]
    published = hif.rating_factor(forces) if not hif.compression else hif.rating_factor(
        forces, p_e=987.4)[0]
    assert corrected < published


def test_corrected_ratings_of_the_example():
    # strain-compatible shared stresses, otherwise the example's own inputs:
    # the compression member no longer reaches RF = 1.0
    assert _tension_strengthened(False).rating_factor(TENSION) == pytest.approx(1.393, abs=0.001)
    rf, _ = _compression_strengthened(False).rating_factor(COMPRESSION, p_e=987.4)
    assert rf == pytest.approx(0.910, abs=0.001)


# ── connections of the strengthening material ──────────────────────────────


def test_fastener_resistances():
    b = bolt_shear_resistance(0.875, 120.0)                 # 7th Ed. C = 0.48
    assert b.capacity == pytest.approx(34.62, abs=0.02)     # example: Ab = 0.601
    assert b.factored_capacity == pytest.approx(27.69, abs=0.02)
    br = bolt_bearing_resistance(0.875, 0.4, 60.0, clear_distance=1.25)
    assert (br.capacity, br.factored_capacity) == (pytest.approx(36.0), pytest.approx(28.8))
    assert bolt_slip_resistance("A325", 0.875, surface_class="B").capacity == pytest.approx(19.5)
    assert rivet_shear_resistance(0.875).capacity == pytest.approx(12.62, abs=0.01)


def test_plate_development_and_rivet_removal():
    w_n = staggered_net_width(12.0, 1.0, 4, staggers=[(2.0, 2.5), (2.0, 2.5)])
    assert w_n == pytest.approx(8.8)
    plate = tension_member_resistance(a_g=0.625 * 12, f_y=50, a_n=0.625 * w_n, f_u=65)
    assert plate.details["yield"] == pytest.approx(356.25)
    assert plate.capacity == pytest.approx(286.0)
    bolt = bolt_shear_resistance(0.875, 120.0).factored_capacity
    assert plate.capacity / bolt == pytest.approx(10.3, abs=0.05)     # example: "say 10"
    assert fasteners_to_develop(plate.capacity, bolt) == 11
    comp_plate = 0.9 * 3.0 * 50
    assert fasteners_to_develop(comp_plate, bolt) == 5                # example: "say 6"
    rivet = rivet_shear_resistance(0.875).capacity
    out = rivets_removed_capacity(12, rivet)
    assert out == pytest.approx(302.0, abs=1.5)                # 24 x 12.62 k
    p_u = 1.25 * 130 + 1.75 * 266
    assert p_u / out == pytest.approx(2.08, abs=0.01)
    assert rivets_removed_capacity(12, bolt) == pytest.approx(665, abs=1.0)
    assert rivets_removed_capacity(16, bolt) == pytest.approx(886, abs=1.0)


# ── lacing effect from the shop-sheet lacing (laced_member) ────────────────


@pytest.mark.parametrize("spec", ["2P24x9/16 4L6x4x3/8", "4P24x1/2 2P16x7/16 4L4x4x1/2"])
@pytest.mark.parametrize("theta", [45.0, 60.0])
def test_laced_member_modified_slenderness(spec, theta):
    from civilpy.structural import builtup
    from civilpy.structural.laced_member import LacedMember, LacingSpec
    single = LacedMember(spec, 30.0, LacingSpec(2.5, 0.375, double=False, inclination_deg=theta))
    double = LacedMember(spec, 30.0, LacingSpec(2.5, 0.375, double=True, inclination_deg=theta))
    assert single.connector_spacing_in() == pytest.approx(2 * double.connector_spacing_in())
    assert double.connector_spacing_in() == pytest.approx(
        double.lacing_gauge_in() / math.tan(math.radians(theta)))
    # one component = the pieces on one side; its r is below the whole section's
    r_i = single.component_radius_in()
    p = builtup.properties(spec)
    assert r_i < math.sqrt(p["Iz"] / p["A"])
    klr = single.modified_slenderness(70.0)
    assert klr == pytest.approx(modified_slenderness(70.0, single.connector_spacing_in(), r_i))
    assert klr > double.modified_slenderness(70.0) > 70.0
