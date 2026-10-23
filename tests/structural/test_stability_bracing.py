#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Torsional stability bracing and lean-on bracing: the NSBA Lean-On Bracing
Reference Guide (B303) Design Examples 1 and 2, and the brace stiffness
equations checked against plane-truss / frame solutions of the brace itself
(civilpy.structural.frame_analysis)."""

import math

import numpy as np
import pytest

from civilpy.structural.aashto.lrfd import stability_bracing as sb
from civilpy.structural.aashto.lrfd.stability_bracing import (
    BraceLine, BraceMember, LeanOnBracing)
from civilpy.structural.frame_analysis import solve
from civilpy.structural.structural_model import (
    MaterialProperties, SectionProperties, StructuralModel)

E = 29000.0

# ── B303 Design Examples ────────────────────────────────────────────────────

L6x6x34 = BraceMember(a_g=8.46, f_y=50.0, f_u=70.0, a_n=7.62, u=0.41, r_x=132.0 / 72.53, r_z=1.17)
L4x4x12 = BraceMember(a_g=3.75, f_y=50.0, f_u=70.0)

#: (name, LeanOnBracing kwargs, B303 results)
EXAMPLES = [
    ("Ex1 positive", dict(l=140 * 12, n=5, l_b=24 * 12, n_g=4, s=144, i_x=62653,
                          i_yeff=sb.effective_weak_axis_inertia(341.3, 668.3, 39.13, 31.06),
                          h_o=70.19, d=69, t_w=0.5, m_u=1.25 * 26157 + 1.5 * 14648, h_b=62,
                          member=L6x6x34, n_gc=2, b_s=6, t_s=0.5, l_d=146),
     dict(beta_br=1_380_125, beta_g=214_536, beta_T_act=185_674, beta_T_req=119_128,
          M_br=782, F_br=12.6, F_diagonal=25.6, F_strut=12.6)),
    ("Ex1 negative", dict(l=175 * 12, n=6, l_b=23.5 * 12, n_g=4, s=144, i_x=111028,
                          i_yeff=sb.effective_weak_axis_inertia(1333.3, 972.0, 34.26, 36.74),
                          h_o=71.0, d=69, t_w=0.5625, m_u=1.25 * 58080 + 1.5 * 23652, c_b=1.25,
                          h_b=62, member=L6x6x34, n_gc=2, b_s=6, t_s=0.5, l_d=146),
     dict(beta_br=1_380_125, beta_g=194_653, beta_T_act=170_593, beta_T_req=113_920,
          M_br=724, F_br=11.7, F_diagonal=23.7, F_strut=11.7)),
    ("Ex2 positive", dict(l=85 * 12, n=3, l_b=24 * 12 + 2, n_g=4, s=114, i_x=15189,
                          i_yeff=sb.effective_weak_axis_inertia(341.3, 486.0, 20.24, 18.76),
                          h_o=39.0, d=38, t_w=0.5, m_u=1.25 * 5700 + 1.5 * 4050, h_b=31,
                          member=L4x4x12, n_gc=4, b_s=9, t_s=0.5, l_d=101, skew_deg=20),
     dict(beta_br=44_661, beta_g=145_647, beta_T_act=34_180, beta_T_req=7_738,
          M_br=98, F_br=3.2, F_diagonal=11.3, F_strut=9.6)),
    ("Ex2 negative", dict(l=125 * 12, n=5, l_b=18.75 * 12, n_g=4, s=114, i_x=26952,
                          i_yeff=sb.effective_weak_axis_inertia(1166.7, 597.3, 18.18, 21.57),
                          h_o=39.75, d=38, t_w=0.5, m_u=1.25 * 20640 + 1.5 * 6539, c_b=1.25,
                          h_b=31, member=L4x4x12, n_gc=2, b_s=9, t_s=0.5, l_d=101, skew_deg=20),
     dict(beta_br=220_080, beta_g=81_262, beta_T_act=59_348, beta_T_req=13_432,
          M_br=130, F_br=4.2, F_diagonal=7.4, F_strut=4.2)),
]


@pytest.mark.parametrize("name,kw,expected", EXAMPLES, ids=[e[0] for e in EXAMPLES])
def test_b303_design_examples(name, kw, expected):
    lob = LeanOnBracing(**kw)
    got = {**lob.stiffness(), **lob.forces()}
    assert math.isinf(got["beta_sec"])                # h_b >= 0.8 D in every example
    for key, value in expected.items():
        # B303 rounds I_yeff and the forces to the printed digits, and takes
        # the member forces from F_br rounded to 0.1 k (Ex. 2: 4 x 3.2 x 101 /
        # 114 = 11.3 k; 11.2 k from F_br = 3.16 k)
        tol = 0.15 if key.startswith("F_") else 0.6 if key == "M_br" else None
        assert got[key] == (pytest.approx(value, abs=tol) if tol else pytest.approx(value, rel=1.5e-3)), key


def test_b303_example_1_member_checks():
    r = LeanOnBracing(**EXAMPLES[0][1]).check()
    assert r.details["phi_Pr_tension"] == pytest.approx(175.0, abs=0.1)   # net-section fracture
    assert r.details["KL_r_eff"] == pytest.approx(126.4, abs=0.05)        # 72 + 0.75 (72.53)
    assert r.details["phi_Pn_compression"] == pytest.approx(126.4, abs=0.2)
    assert r.details["KL_r_strut"] == pytest.approx(113, abs=0.5)
    assert r.ok
    # margins: stiffness 185,674 / 119,128 = 1.56, tension 175 / 25.6,
    # compression 126.4 / 12.6; the strut slenderness 140 / 113 governs
    assert r.ratio == pytest.approx(140 / (132 / 1.17))


def test_lean_on_bracing_flags_too_many_girders_per_cross_frame():
    kw = dict(EXAMPLES[2][1], n_gc=5)
    assert any("n_gc = 5" in n for n in LeanOnBracing(**kw).check().details["notes"])


def test_existing_check_reproduces_b303():
    from civilpy.structural.aashto import lrfd
    kw = EXAMPLES[1][1]
    r = lrfd.stability_bracing_torsional(kw["m_u"], kw["l"], kw["n"], kw["i_yeff"], 170_593,
                                         c_b=1.25, l_b=kw["l_b"], h_o=kw["h_o"])
    assert r.details["beta_T_req"] == pytest.approx(113_920, rel=1e-3)
    assert r.details["M_br_req"] == pytest.approx(724, abs=0.6)
    assert r.ok


# ── stiffness equations against the brace's own truss / frame solution ──────

S, HB = 144.0, 62.0
AD, AH = 4.0, 6.0


def _brace_frame(nodes, members, n_girders):
    """Brace joints restrained vertically (the girders' in-plane stiffness is
    beta_g's business), one joint horizontally; a unit twisting moment on
    each girder as horizontal couples 1 / h_b at its top and bottom joints.
    Returns the girder rotations and the member forces."""
    m = StructuralModel()
    m.material_properties["st"] = MaterialProperties(e=E)
    m.section_properties["d"] = SectionProperties(area=AD, iy=10.0, iz=10.0, j=1.0)
    m.section_properties["h"] = SectionProperties(area=AH, iy=10.0, iz=10.0, j=1.0)
    ids = {k: m.add_node(x, 0.0, z).id for k, (x, z) in nodes.items()}
    elems = {}
    for a, b, sec in members:
        elems[(a, b)] = m.add_element(ids[a], ids[b], section=sec, material="st").id
    corners = {f"{p}{g}" for p in "tb" for g in range(n_girders)}
    for k, nid in ids.items():
        m.add_restraint(nid, fix_y=True, fix_z=k in corners, fix_x=k == "b0",
                        fix_rx=True, fix_ry=True, fix_rz=True)
    for g in range(n_girders):
        m.add_load(ids[f"t{g}"], fx=1.0 / HB)
        m.add_load(ids[f"b{g}"], fx=-1.0 / HB)
    r = solve(m)["default"]
    d = r.displacements
    theta = np.array([(d[ids[f"t{g}"]][0] - d[ids[f"b{g}"]][0]) / HB for g in range(n_girders)])
    return theta, {k: r.element_forces[e] for k, e in elems.items()}


def _corners(n_girders):
    pts = {}
    for g in range(n_girders):
        pts[f"t{g}"] = (g * S, HB)
        pts[f"b{g}"] = (g * S, 0.0)
    return pts


@pytest.mark.parametrize("system,members,extra", [
    ("x_tension", [("t0", "b1", "d"), ("t0", "t1", "h"), ("b0", "b1", "h")], {}),
    ("x_compression", [("t0", "b1", "d"), ("b0", "t1", "d")], {}),
    ("k", [("t0", "bm", "d"), ("t1", "bm", "d"), ("b0", "bm", "h"), ("bm", "b1", "h"),
           ("t0", "t1", "h")], {"bm": (S / 2, 0.0)}),
    ("k", [("b0", "tm", "d"), ("b1", "tm", "d"), ("t0", "tm", "h"), ("tm", "t1", "h"),
           ("b0", "b1", "h")], {"tm": (S / 2, HB)}),
])
def test_cross_frame_stiffness_matches_the_truss(system, members, extra):
    theta, _ = _brace_frame({**_corners(2), **extra}, members, 2)
    # two girders, each with a unit moment: work 2 x 1 x theta_avg
    assert 1.0 / theta.mean() == pytest.approx(sb.brace_stiffness(system, S, HB, a_d=AD, a_h=AH),
                                               rel=1e-6)


@pytest.mark.parametrize("n_gc", [2, 3, 4, 5, 6])
def test_lean_on_stiffness_is_that_of_the_farthest_girder(n_gc):
    for bay in range(n_gc - 1):
        members = [(f"{p}{g}", f"{p}{g + 1}", "d") for p in "tb" for g in range(n_gc - 1)]
        members.append((f"t{bay}", f"b{bay + 1}", "d"))
        theta, forces = _brace_frame(_corners(n_gc), members, n_gc)
        beta = sb.lean_on_brace_stiffness(S, HB, AD, n_gc, bay)
        assert 1.0 / theta.max() == pytest.approx(beta, rel=1e-6)
        f = sb.lean_on_member_forces(1.0, HB, S, n_gc, bay)
        assert abs(forces[(f"t{bay}", f"b{bay + 1}")]) == pytest.approx(f["F_diagonal"], rel=1e-6)
        strut = max(abs(v) for k, v in forces.items() if k[0][0] == k[1][0])
        assert strut == pytest.approx(f["F_strut"], rel=1e-6)
    # the exterior bay is the conservative choice everywhere
    assert sb.lean_on_brace_stiffness(S, HB, AD, n_gc) == pytest.approx(
        min(sb.lean_on_brace_stiffness(S, HB, AD, n_gc, b) for b in range(n_gc - 1)))


@pytest.mark.parametrize("n_gc", [2, 4, 6])
def test_b303_interior_equation_is_exact_for_an_even_count(n_gc):
    assert sb.lean_on_brace_stiffness(S, HB, AD, n_gc, "interior", b303=True) == pytest.approx(
        sb.lean_on_brace_stiffness(S, HB, AD, n_gc, n_gc // 2 - 1))


@pytest.mark.parametrize("n_gc", [3, 5])
def test_b303_interior_equation_overstates_an_odd_count(n_gc):
    printed = sb.lean_on_brace_stiffness(S, HB, AD, n_gc, "interior", b303=True)
    assert printed > sb.lean_on_brace_stiffness(S, HB, AD, n_gc, "interior")


def test_two_girder_lean_on_is_the_aashto_cross_frame():
    assert sb.lean_on_brace_stiffness(S, HB, AD, 2) == pytest.approx(
        sb.brace_stiffness("x_tension", S, HB, a_d=AD, a_h=AD))


@pytest.mark.parametrize("system,coef", [("diaphragm", 6.0), ("diaphragm_below", 2.0)])
def test_diaphragm_stiffness_matches_the_beam(system, coef):
    i_b = 300.0
    m = StructuralModel()
    m.material_properties["st"] = MaterialProperties(e=E)
    m.section_properties["w"] = SectionProperties(area=20.0, iy=i_b, iz=i_b, j=5.0)
    a, b = m.add_node(0, 0, 0), m.add_node(S, 0, 0)
    m.add_element(a.id, b.id, section="w", material="st", midas_type="BEAM")
    # reverse curvature: both ends twisted the same way; single curvature
    # (through-girder floor beam): the girder tops separate, ends opposite
    sign = 1.0 if system == "diaphragm" else -1.0
    m.add_restraint(a.id, fix_x=True, fix_y=True, fix_z=True, fix_rx=True, fix_rz=True)
    m.add_restraint(b.id, fix_y=True, fix_z=True, fix_rx=True, fix_rz=True)
    m.add_load(a.id, my=1.0)
    m.add_load(b.id, my=sign)
    d = solve(m)["default"].displacements
    assert 1.0 / d[a.id][4] == pytest.approx(sb.brace_stiffness(system, S, i_b=i_b), rel=1e-6)
    assert sb.brace_stiffness(system, S, i_b=i_b) == pytest.approx(coef * E * i_b / S)


# ── the other components ────────────────────────────────────────────────────


def test_web_distortion_stiffness():
    assert math.isinf(sb.web_distortion_stiffness(69, 0.5, 55.2))
    # a shallow brace: the two web portions in series (Eq. 6.7.4.2.2-12)
    d, tw, ts, bs = 60.0, 0.5, 0.5, 6.0
    one = 3.3 * E / 10.0 * (d / 10.0) ** 2 * (1.5 * 10.0 * tw ** 3 / 12 + ts * bs ** 3 / 12)
    assert sb.web_distortion_stiffness(d, tw, 40.0, (10.0, 10.0), t_s=ts, b_s=bs) == pytest.approx(one / 2)
    with pytest.raises(ValueError):
        sb.web_distortion_stiffness(d, tw, 40.0)


def test_lean_on_halves_the_in_plane_girder_stiffness():
    full = sb.in_plane_girder_stiffness(4, 144, 62653, 1680)
    assert sb.in_plane_girder_stiffness(4, 144, 62653, 1680, lean_on=True) == pytest.approx(full / 2)


def test_skew_limits():
    assert sb.skewed_stiffness(100.0, 20) == pytest.approx(100 * math.cos(math.radians(20)) ** 2)
    with pytest.raises(ValueError, match="normal to the girders"):
        sb.skewed_brace_moment(100.0, 25)


def test_shallow_brace_uses_the_3_6_equations():
    assert sb.required_stiffness(1000, 5000, 3, 500, full_depth=False) == pytest.approx(
        1.5 * sb.required_stiffness(1000, 5000, 3, 500))
    assert sb.required_brace_moment(1000, 5000, 3, 500, 250, 40, full_depth=False) == pytest.approx(
        1.5 * sb.required_brace_moment(1000, 5000, 3, 500, 250, 40))


@pytest.mark.parametrize("l_rx,kl_r", [(72.53, 126.4), (80.0, 132.0), (100.0, 157.0)])
def test_single_angle_slenderness(l_rx, kl_r):
    assert sb.single_angle_slenderness(l_rx) == pytest.approx(kl_r, abs=0.05)


# ── framing-plan layout ─────────────────────────────────────────────────────


def _b303_example_1_plan():
    # Fig. 5-2: full lines at the bearings, cross-frames in an S-pattern
    support = BraceLine(("x", "x", "x"), kind="support")
    left = BraceLine(("x", "strut", "strut"), distance_from_bearing=288)
    middle = BraceLine(("strut", "x", "strut"))
    right = BraceLine(("strut", "strut", "x"))
    return [support, left, left, middle, right, right, support]


def test_b303_example_plan_passes():
    assert sb.lean_on_layout(4, _b303_example_1_plan()) == []
    assert sb.design_n_gc(4, _b303_example_1_plan()) == 4.0


def test_layout_findings():
    support_short = BraceLine(("x", "strut", "x"), kind="support")
    open_bay = BraceLine(("x", "", "strut"))
    no_frame = BraceLine(("strut", "strut", "strut"))
    close = BraceLine(("x", "strut", "strut"), distance_from_bearing=30)
    sparse = BraceLine(("x",) + ("strut",) * 3)
    f = sb.lean_on_layout(4, [support_short, open_bay, no_frame, close], curved=True,
                          skew_deg=25, parallel_to_skew=True, frame_depth=40, girder_depth=60)
    text = " | ".join(f)
    for needle in ("straight girders", "25 deg skew", "0.75 x girder depth",
                   "support lines need cross-frames", "unbraced bay", "no cross-frame",
                   "< about 4 ft", "[2, 3]"):
        assert needle in text, needle
    assert any("n_gc = 5" in x for x in sb.lean_on_layout(5, [sparse]))
    skewed = sb.lean_on_layout(4, [BraceLine(("x", "strut", "x"), distance_from_bearing=60)],
                               skew_deg=15, flange_width=18, unbraced_length=288)
    assert any("max(4 b_f, 0.4 L_b) = 115.2" in x for x in skewed)
