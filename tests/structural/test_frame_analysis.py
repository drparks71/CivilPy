#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Property and closed-form tests for the hub frame solver.

Geometry is generated (orientations, spans, load positions) so the checks
hold for any member, not one model; the end-to-end check against a real
bridge (TSC's 2009 STAAD decks for HAM-50-2180N, 1,017 truss members within
0.16 k of the rating sheets) lives with the private data in snbi_ui."""

import math

import numpy as np
import pytest

from civilpy.structural.frame_analysis import (
    combine, end_moments, local_axes, reaction_totals, solve)
from civilpy.structural.structural_model import (
    MaterialProperties, SectionProperties, StructuralModel)

E = 4.176e6                       # ksf
SEC = SectionProperties(area=0.2, iy=0.06, iz=0.02, j=0.004)
FIXED = dict(fix_x=True, fix_y=True, fix_z=True, fix_rx=True, fix_ry=True, fix_rz=True)


def _model(sec=SEC):
    m = StructuralModel()
    m.section_properties["S"] = sec
    m.material_properties["steel"] = MaterialProperties(e=E, density=0.49)
    return m


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


DIRECTIONS = {"x": (1, 0, 0), "y": (0, 1, 0), "-x": (-1, 0, 0), "skew": (3, -2, 0),
              "inclined": (2, 1, 1.5), "up": (0, 0, 1), "down": (0, 0, -1)}


@pytest.mark.parametrize("name", DIRECTIONS)
def test_local_axes_are_orthonormal_and_right_handed(name):
    r = local_axes((0, 0, 0), DIRECTIONS[name], beta_deg=17.0)
    assert r @ r.T == pytest.approx(np.eye(3), abs=1e-12)
    assert np.cross(r[0], r[1]) == pytest.approx(r[2], abs=1e-12)
    assert r[0] == pytest.approx(_unit(DIRECTIONS[name]))


@pytest.mark.parametrize("name", DIRECTIONS)
@pytest.mark.parametrize("length", [8.0, 25.0])
@pytest.mark.parametrize("beta", [0.0, 30.0, 90.0])
def test_cantilever_tip_load_any_orientation(name, length, beta):
    # tip load perpendicular to the member along its local z: delta = PL^3/3EIy
    m = _model()
    d = _unit(DIRECTIONS[name]) * length
    a, b = m.add_node(0, 0, 0), m.add_node(*d)
    e = m.add_element(a.id, b.id, midas_type="BEAM", section="S", beta_deg=beta)
    m.add_restraint(a.id, **FIXED)
    ez = local_axes((0, 0, 0), d, beta)[2]
    p = 12.0
    m.add_load(b.id, fx=-p * ez[0], fy=-p * ez[1], fz=-p * ez[2])
    r = solve(m)["default"]
    tip = np.array(r.displacements[b.id][:3])
    assert tip @ ez == pytest.approx(-p * length ** 3 / (3 * E * SEC.iy), rel=1e-9)
    assert end_moments(r, e.id, "y")[0] == pytest.approx(-p * length, rel=1e-9)
    assert reaction_totals(r) == pytest.approx(tuple(p * ez), abs=1e-9)


@pytest.mark.parametrize("asz", [0.0, 0.05, 0.12])
def test_shear_deformation_adds_pl_over_gas(asz):
    m = _model(SectionProperties(area=0.2, iy=0.06, iz=0.02, j=0.004, asz=asz))
    a, b = m.add_node(0, 0, 0), m.add_node(10, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", section="S")
    m.add_restraint(a.id, **FIXED)
    m.add_load(b.id, fz=-5.0)
    g = E / 2.6
    want = 5 * 1000 / (3 * E * 0.06) + (5 * 10 / (g * asz) if asz else 0.0)
    assert -solve(m)["default"].displacements[b.id][2] == pytest.approx(want, rel=1e-9)


def _fixed_fixed(span=24.0, release_j=""):
    m = _model()
    a, b = m.add_node(0, 0, 0), m.add_node(span, 0, 0)
    rel = ("000000", release_j or "000000")
    e = m.add_element(a.id, b.id, midas_type="BEAM", section="S", releases=rel)
    m.add_restraint(a.id, **FIXED)
    m.add_restraint(b.id, **FIXED)
    return m, a, b, e


@pytest.mark.parametrize("frac", [0.1, 0.25, 0.5, 0.8])
def test_point_load_fixed_end_moments(frac):
    span, p = 24.0, 10.0
    m, a, b, e = _fixed_fixed(span)
    m.add_beam_load(e.id, -p, kind="point", start=frac)
    r = solve(m)["default"]
    aa, bb = frac * span, (1 - frac) * span
    mi, mj = end_moments(r, e.id)
    assert mi == pytest.approx(-p * aa * bb ** 2 / span ** 2, rel=1e-9)
    assert mj == pytest.approx(-p * aa ** 2 * bb / span ** 2, rel=1e-9)


@pytest.mark.parametrize("seg", [(0.0, 1.0), (0.2, 0.6), (0.5, 1.0)])
@pytest.mark.parametrize("w", [(-1.0, -1.0), (-0.5, -2.0)])
def test_partial_trapezoid_load_statics(seg, w):
    span = 30.0
    m, a, b, e = _fixed_fixed(span)
    m.add_beam_load(e.id, w[0], w[1], start=seg[0], end=seg[1])
    r = solve(m)["default"]
    length = (seg[1] - seg[0]) * span
    total = (w[0] + w[1]) / 2 * length
    assert reaction_totals(r)[2] == pytest.approx(-total, rel=1e-9)
    # moment of the reactions about a balances the load
    xa, xb = seg[0] * span, seg[1] * span
    xc = xa + length * (w[0] + 2 * w[1]) / (3 * (w[0] + w[1]))
    ra, rb = r.reactions[a.id], r.reactions[b.id]
    about_a = rb[2] * span - rb[4] - ra[4]
    assert about_a == pytest.approx(-total * xc, rel=1e-9)


def test_end_release_gives_propped_cantilever():
    span, w = 20.0, 1.2
    m, a, b, e = _fixed_fixed(span, release_j="000010")
    m.add_beam_load(e.id, -w)
    r = solve(m)["default"]
    assert r.reactions[b.id][2] == pytest.approx(3 * w * span / 8, rel=1e-9)
    assert end_moments(r, e.id)[0] == pytest.approx(-w * span ** 2 / 8, rel=1e-9)
    assert end_moments(r, e.id)[1] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("strain", [-4e-4, 2.5e-4])
def test_initial_strain_restrained_and_free(strain):
    m, a, b, e = _fixed_fixed()
    m.add_element_strain(e.id, strain)
    r = solve(m)["default"]
    assert r.element_forces[e.id] == pytest.approx(-E * SEC.area * strain, rel=1e-9)
    # released at the far end: free to change length, no force
    m2 = _model()
    a2, b2 = m2.add_node(0, 0, 0), m2.add_node(24, 0, 0)
    e2 = m2.add_element(a2.id, b2.id, midas_type="TRUSS", section="S")
    m2.add_restraint(a2.id, **FIXED)
    m2.add_restraint(b2.id, fix_y=True, fix_z=True)
    m2.add_element_strain(e2.id, strain)
    r2 = solve(m2)["default"]
    assert r2.element_forces[e2.id] == pytest.approx(0.0, abs=1e-6)
    assert r2.displacements[b2.id][0] == pytest.approx(strain * 24, rel=1e-9)


def test_self_weight_totals_density_times_volume():
    m = _model()
    pts = [(0, 0, 0), (10, 0, 0), (10, 6, 3), (0, 6, 8)]
    ids = [m.add_node(*p).id for p in pts]
    for i, j in zip(ids, ids[1:] + ids[:1]):
        m.add_element(i, j, midas_type="BEAM", section="S")
    for nid in ids:
        m.add_restraint(nid, **FIXED)
    m.add_body_force()
    r = solve(m)["default"]
    perim = sum(math.dist(p, q) for p, q in zip(pts, pts[1:] + pts[:1]))
    assert reaction_totals(r)[2] == pytest.approx(0.49 * SEC.area * perim, rel=1e-9)


def test_rigid_link_carries_offset_load_as_force_plus_moment():
    # load on a slave node offset from the cantilever tip = load + moment at the tip
    def build(on_slave):
        m = _model()
        a, b = m.add_node(0, 0, 0), m.add_node(12, 0, 0)
        m.add_element(a.id, b.id, midas_type="BEAM", section="S")
        m.add_restraint(a.id, **FIXED)
        if on_slave:
            s = m.add_node(12, 3, 0)
            m.add_rigid_link(b.id, [s.id])
            m.add_load(s.id, fz=-4.0)
        else:
            m.add_load(b.id, fz=-4.0, mx=-4.0 * 3)
        return m, b

    (m1, b1), (m2, b2) = build(True), build(False)
    d1 = solve(m1)["default"].displacements[b1.id]
    d2 = solve(m2)["default"].displacements[b2.id]
    assert d1 == pytest.approx(d2, rel=1e-9, abs=1e-12)


def test_truss_only_node_rotations_are_held_and_noted():
    m = _model()
    a, b, c = m.add_node(0, 0, 0), m.add_node(12, 0, 0), m.add_node(6, 0, 8)
    for i, j in ((a, b), (a, c), (b, c)):
        m.add_element(i.id, j.id, midas_type="TRUSS", section="S")
    for n in (a, b, c):
        m.add_restraint(n.id, fix_y=True, fix_x=n is a, fix_z=n is not c)
    m.add_load(c.id, fx=10.0)
    r = solve(m)["default"]
    assert any("unstiffened" in n for n in r.notes)
    # method of joints: horizontal load at apex of 6-8-10 triangles
    ac = next(k for k, e in m.elements.items() if {e.node_a, e.node_b} == {a.id, c.id})
    assert r.element_forces[ac] == pytest.approx(10.0 / (2 * 0.6), rel=1e-9)


def test_combine_is_linear():
    m, a, b, e = _fixed_fixed()
    m.add_beam_load(e.id, -1.0, case="D")
    m.add_beam_load(e.id, -0.3, case="W", kind="point", start=0.3)
    res = solve(m)
    both = _fixed_fixed()
    both[0].add_beam_load(both[3].id, -1.25)
    both[0].add_beam_load(both[3].id, -0.3 * 1.5, kind="point", start=0.3)
    want = solve(both[0])["default"]
    got = combine(res, {"D": 1.25, "W": 1.5})
    assert got.end_forces[e.id] == pytest.approx(want.end_forces[both[3].id], rel=1e-9)


def test_plate_elements_are_refused():
    m = _model()
    ids = [m.add_node(*p).id for p in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
    m.add_element(ids[0], ids[1], nodes=ids, midas_type="PLATE", section="S")
    with pytest.raises(ValueError, match="plate"):
        solve(m)
