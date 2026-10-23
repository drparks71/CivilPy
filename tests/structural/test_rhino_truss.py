#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""The riveted-truss BrIM emit: built-up members drawn as the plates and
angles they are, gusset plates landed on their panel points, and the whole
thing tagged so a viewer's tree, takeoff and estimator hand-off work."""
import math

import pytest

from civilpy.structural import builtup                              # noqa: E402
from civilpy.structural import rhino_truss as rt                    # noqa: E402
from civilpy.structural.rhino_bim import read_bim_quantities, read_bim_tags
from civilpy.structural.rhino_layers import (
    LAYER_GUSSET_PLATES, LAYER_PANEL_POINTS, LAYER_TRUSS_CHORDS,
    LAYER_TRUSS_DIAGONALS, LAYER_TRUSS_VERTICALS,
)

CHORD = "2P24x9/16 4L4x4x3/8"
DIAG = "2P18x7/16 4L4x4x3/8"
COVERED = "4P24x1/2 2P16x7/16 4L4x4x1/2"


def panel_truss():
    """Two panels of a 25 ft deep truss on one line, y = 36.5 ft."""
    m = rt.TrussModel("test truss")
    y = 36.5
    for i, x in enumerate((0.0, 23.9167, 47.8333)):
        m.add_node(rt.TrussNode("U%d" % i, (x, y, 120.0), line="ON", span="5",
                                chord="U", pp=i, joint="1100%d" % i))
        m.add_node(rt.TrussNode("L%d" % i, (x, y, 95.0), line="ON", span="5",
                                chord="L", pp=i, joint="1200%d" % i))
    for i in (0, 1):
        m.members.append(rt.TrussMember("U%dU%d" % (i, i + 1), "U%d" % i,
                                        "U%d" % (i + 1), CHORD,
                                        role="truss_chord_top", line="ON", span="5"))
        m.members.append(rt.TrussMember("L%dL%d" % (i, i + 1), "L%d" % i,
                                        "L%d" % (i + 1), CHORD,
                                        role="truss_chord_bottom", line="ON", span="5"))
    for i in (0, 1, 2):
        m.members.append(rt.TrussMember("U%dL%d" % (i, i), "U%d" % i, "L%d" % i,
                                        CHORD, role="truss_vertical",
                                        line="ON", span="5"))
    m.members.append(rt.TrussMember("U0L1", "U0", "L1", DIAG,
                                    role="truss_diagonal", line="ON", span="5"))
    return m


def rect_plate(w=55.0, h=76.0):
    return ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h))


# --------------------------------------------------------------------------- #
# member geometry
# --------------------------------------------------------------------------- #
def test_lod400_draws_every_plate_and_angle_leg():
    """The point of LOD 400: the member is the pieces a rivet gang put
    together, not a box standing in for them."""
    m = panel_truss()
    member = m.members[0]
    objs = rt.member_objects(m, member, lod=400)
    rects, _meta = builtup.rects(CHORD)
    assert len(objs) == len(rects) == 10          # 2 webs + 8 angle legs
    assert {o.layer for o in objs} == {LAYER_TRUSS_CHORDS}
    assert {o.tags["bim.id"] for o in objs} == {"U0U1"}
    pieces = [o.tags["truss.piece"] for o in objs]
    assert sum("web plate" in p for p in pieces) == 2
    assert sum("angle" in p for p in pieces) == 8

    covered = rt.TrussMember("C", "U0", "U1", COVERED, role="truss_chord_top")
    assert len(rt.member_objects(m, covered, lod=400)) == 12   # + 2 cover plates


def test_lod300_collapses_the_member_to_its_envelope():
    m = panel_truss()
    objs = rt.member_objects(m, m.members[0], lod=300)
    assert len(objs) == 1
    b, h = builtup.envelope(CHORD)
    pts = objs[0].points
    width = max(p[1] for p in pts) - min(p[1] for p in pts)
    depth = max(p[2] for p in pts) - min(p[2] for p in pts)
    assert width == pytest.approx(b / 12.0)
    assert depth == pytest.approx(h / 12.0)


def test_member_pay_quantity_is_counted_once_per_member():
    """Every piece shares the member's bim.id, so only one may carry pay.qty
    or the takeoff multiplies the steel by ten."""
    m = panel_truss()
    objs = rt.member_objects(m, m.members[0], lod=400)
    with_qty = [o for o in objs if "pay.qty" in o.tags]
    assert len(with_qty) == 1
    length = m.length_ft(m.members[0])
    want = builtup.properties(CHORD)["A"] / 144.0 * builtup.STEEL_PCF * length
    assert float(with_qty[0].tags["pay.qty"]) == pytest.approx(want, rel=1e-6)
    assert all(o.tags["pay.item"] == "513E10220" for o in objs)


def test_member_width_runs_transverse_and_depth_in_the_truss_plane():
    """A truss member's webs are parallel to its truss, so the section width
    is bridge-transverse and the depth lies in the truss plane."""
    m = panel_truss()
    u, v, w, length = rt.member_frame((0.0, 36.5, 120.0), (23.9167, 36.5, 120.0),
                                      (0.0, 1.0, 0.0))
    assert u == pytest.approx((1.0, 0.0, 0.0))
    assert v == pytest.approx((0.0, 1.0, 0.0))          # across the width
    assert abs(w[2]) == pytest.approx(1.0)              # depth is vertical here
    assert length == pytest.approx(23.9167)

    # a diagonal: still transverse width, depth still in the truss plane
    _u, v2, w2, _l = rt.member_frame((0.0, 36.5, 120.0), (23.9, 36.5, 95.0),
                                     (0.0, 1.0, 0.0))
    assert v2 == pytest.approx((0.0, 1.0, 0.0))
    assert w2[1] == pytest.approx(0.0, abs=1e-12)       # no transverse component


def test_member_frame_survives_a_member_along_the_normal():
    """A transverse member (a strut) runs along the default normal; the frame
    has to fall back rather than divide by zero."""
    u, v, w, length = rt.member_frame((0.0, -36.5, 100.0), (0.0, 36.5, 100.0),
                                      (0.0, 1.0, 0.0))
    assert length == pytest.approx(73.0)
    assert abs(rt._dot(u, v)) < 1e-12
    assert abs(rt._dot(u, w)) < 1e-12


def test_shorten_trims_both_ends_but_never_inverts_a_short_member():
    m = panel_truss()
    long_m = m.members[0]
    full = rt.member_objects(m, long_m, lod=300)[0]
    trimmed = rt.member_objects(m, long_m, lod=300, shorten_ft=2.0)[0]
    assert rt._norm(trimmed.vector) == pytest.approx(
        rt._norm(full.vector) - 4.0)
    # a member shorter than the trim is left alone rather than turned inside out
    m.add_node(rt.TrussNode("A", (0.0, 36.5, 120.0)))
    m.add_node(rt.TrussNode("B", (1.0, 36.5, 120.0)))
    tiny = rt.TrussMember("tiny", "A", "B", CHORD, role="truss_chord_top")
    assert rt._norm(rt.member_objects(m, tiny, lod=300, shorten_ft=2.0)[0].vector) \
        == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# gusset placement
# --------------------------------------------------------------------------- #
def test_gusset_lands_on_its_joint_the_right_way_up():
    """The plate's local +y must come out UP: the drawing convention is x
    right / y up, and a flipped plate hangs above the top chord instead of
    below it."""
    m = panel_truss()
    g = rt.GussetPlacement("11000-out", "U0", rect_plate(55.0, 76.0),
                           work_point=(27.5, 64.0), thickness_in=0.625,
                           joint="11000", face="outside", offset_in=9.3)
    obj = rt.gusset_objects(m, g)[0]
    node = m.nodes["U0"].point
    zs = [p[2] for p in obj.points]
    assert max(zs) - node[2] == pytest.approx((76.0 - 64.0) / 12.0)   # above
    assert node[2] - min(zs) == pytest.approx(64.0 / 12.0)            # below
    assert max(zs) - min(zs) == pytest.approx(76.0 / 12.0)
    xs = [p[0] for p in obj.points]
    assert node[0] - min(xs) == pytest.approx(27.5 / 12.0)
    assert all(p[1] == pytest.approx(node[1] + 9.3 / 12.0) for p in obj.points)
    assert obj.vector == pytest.approx((0.0, 0.625 / 12.0, 0.0))
    assert obj.layer == LAYER_GUSSET_PLATES


def test_gusset_tags_carry_the_rating_and_the_loss():
    m = panel_truss()
    g = rt.GussetPlacement("11000-out", "U0", rect_plate(), work_point=(27.5, 64.0),
                           thickness_in=0.625, joint="11000",
                           t_remaining_in=0.5, rating_rf=0.985,
                           governing="rivet shear", members="U0U1,U0L0,U0L1")
    tags = rt.gusset_objects(m, g)[0].tags
    assert tags["bim.type"] == "gusset_plate"
    assert tags["gusset.joint"] == "11000"
    assert tags["gusset.rf"] == "0.985"
    assert tags["gusset.governing"] == "rivet shear"
    assert float(tags["gusset.t_remaining_in"]) == 0.5
    assert float(tags["gusset.loss_in"]) == pytest.approx(0.125)
    assert float(tags["gusset.area_in2"]) == pytest.approx(55.0 * 76.0)
    # the weight uses the REMAINING thickness -- a corroded plate weighs less
    assert float(tags["pay.qty"]) == pytest.approx(
        55.0 * 76.0 * 0.5 / 1728.0 * builtup.STEEL_PCF)
    assert float(tags["mat.fy_ksi"]) == 45.0        # MBE silicon steel


def test_gusset_placements_from_a_parsed_joint():
    """A joint traced off a failure-plane sheet drops straight onto its panel
    point -- one plate each side of the member webs."""
    gg = pytest.importorskip("civilpy.structural.gusset_geometry")
    plate = gg.GussetPlate(gg.polygon_from_bbox(0, 0, 55.0, 76.0), 0.625,
                           label="U0 outside")
    joint = gg.GussetJoint("11000", (12.0, 64.0), plate, members=[
        gg.MemberEnd("U0U1", (12.0, 64.0), (1, 0),
                     gg.rectangular_grid((15.0, 64.0), (1, 0), 4, 3, 3.0, 3.0))])
    places = rt.gusset_joint_placements(joint, "U0", half_width_in=9.0,
                                        rating_rf=6.62, governing="rivet shear")
    assert len(places) == 2
    assert {p.face for p in places} == {"inside", "outside"}
    assert places[0].offset_in == -9.0 and places[1].offset_in == 9.0
    assert all(p.work_point == (12.0, 64.0) for p in places)
    assert all(p.members == "U0U1" for p in places)
    assert all(p.rating_rf == 6.62 for p in places)


def test_a_corroded_parsed_joint_carries_its_remaining_thickness():
    gg = pytest.importorskip("civilpy.structural.gusset_geometry")
    field = gg.ThicknessField(0.625, [gg.ThicknessPatch(
        gg.polygon_from_bbox(0, 0, 55.0, 9.0), 0.4375, "pack rust")])
    plate = gg.GussetPlate(gg.polygon_from_bbox(0, 0, 55.0, 76.0), field)
    joint = gg.GussetJoint("11000", (12.0, 64.0), plate, members=[])
    places = rt.gusset_joint_placements(joint, "U0")
    assert places[0].t_remaining_in == pytest.approx(0.4375)


# --------------------------------------------------------------------------- #
# whole-model emit and the .3dm the viewer opens
# --------------------------------------------------------------------------- #
def test_emit_covers_every_family_and_can_be_filtered():
    m = panel_truss()
    m.gussets.append(rt.GussetPlacement("g", "U0", rect_plate(),
                                        work_point=(27.5, 64.0), joint="11000"))
    m.framing.append(rt.FramingMember("fb", "U0", "U1", "FB", role="floor_beam"))
    objs = rt.truss_emit(m, lod=300)
    layers = {o.layer for o in objs}
    assert {LAYER_TRUSS_CHORDS, LAYER_TRUSS_VERTICALS, LAYER_TRUSS_DIAGONALS,
            LAYER_GUSSET_PLATES, LAYER_PANEL_POINTS} <= layers
    # every upper/lower work point gets a marker; M and P nodes do not
    assert sum(1 for o in objs if o.layer == LAYER_PANEL_POINTS) == 6

    only = rt.truss_emit(m, members=False, framing=False, panel_points=False)
    assert {o.tags["bim.type"] for o in only} == {"gusset_plate"}


def test_3dm_round_trips_the_tags_the_viewer_reads(tmp_path):
    """The asset viewer keys off bim.type / bim.id and rolls the takeoff up
    from pay.*; the saved file has to carry both."""
    pytest.importorskip("rhino3dm")
    m = panel_truss()
    m.gussets.append(rt.GussetPlacement("11000-out", "U0", rect_plate(),
                                        work_point=(27.5, 64.0), joint="11000"))
    p = tmp_path / "truss.3dm"
    counts = rt.truss_to_3dm(m, p, lod=300, mesh=True)
    assert counts[LAYER_TRUSS_CHORDS] == 4
    assert counts[LAYER_GUSSET_PLATES] == 1

    back = read_bim_tags(p)
    types = {t["bim.type"] for t in back["components"]}
    assert {"truss_chord_top", "truss_vertical", "truss_diagonal",
            "gusset_plate", "panel_point"} <= types
    qty = read_bim_quantities(p)
    assert "513E10220" in qty
    assert qty["513E10220"]["qty"] > 0
    assert qty["513E10220"]["unit"] == "lb"

    bridge = back["bridge"]
    assert bridge["bridge.lod"] == "300"
    assert bridge["bridge.units"] == "feet"
    assert bridge["bridge.gusset_plates"] == "1"
    assert bridge["bridge.truss_members"] == "8"   # 4 chords + 3 verticals + 1 diagonal


def test_meshed_file_actually_contains_meshes(tmp_path):
    """three.js cannot tessellate a brep, so a brep file renders empty in the
    asset viewer -- the truss writer defaults to meshes for that reason."""
    r3 = pytest.importorskip("rhino3dm")
    m = panel_truss()
    p = tmp_path / "mesh.3dm"
    rt.truss_to_3dm(m, p, lod=300, mesh=True)
    f = r3.File3dm.Read(str(p))
    kinds = {type(o.Geometry).__name__ for o in f.Objects}
    assert "Mesh" in kinds and "Brep" not in kinds

    q = tmp_path / "brep.3dm"
    rt.truss_to_3dm(m, q, lod=300, mesh=False)
    g = r3.File3dm.Read(str(q))
    assert "Brep" in {type(o.Geometry).__name__ for o in g.Objects}


def test_unknown_member_role_is_rejected():
    m = panel_truss()
    bad = rt.TrussMember("x", "U0", "U1", CHORD, role="truss_whatever")
    with pytest.raises(ValueError, match="unknown truss member role"):
        rt.member_objects(m, bad)


def test_model_bbox_and_length():
    m = panel_truss()
    (x0, y0, z0), (x1, y1, z1) = m.bbox()
    assert (x1 - x0) == pytest.approx(47.8333)
    assert (z1 - z0) == pytest.approx(25.0)
    assert m.length_ft(m.members[0]) == pytest.approx(23.9167)


# --------------------------------------------------------------------------- #
# built-up sections
# --------------------------------------------------------------------------- #
def test_builtup_decomposes_the_plan_sheet_shorthand():
    rects, (d, B, tw, angles, covers) = builtup.rects("2P24x9/16 4L6x4x3/8")
    assert len(rects) == 10
    assert d == 24.0 and B == 18.0
    assert tw == pytest.approx(9 / 16)
    assert angles == (4, 6.0, 4.0, 0.375)
    assert covers is None
    # every piece sits inside the envelope
    b_env, h_env = builtup.envelope("2P24x9/16 4L6x4x3/8")
    for b, h, y, z in rects:
        assert abs(y) + b / 2 <= b_env / 2 + 1e-9
        assert abs(z) + h / 2 <= h_env / 2 + 1e-9


def test_builtup_properties_are_the_integral_of_the_pieces():
    spec = "4P24x1/2 2P16x7/16 4L4x4x1/2"
    rects, _ = builtup.rects(spec)
    p = builtup.properties(spec)
    assert p["A"] == pytest.approx(sum(b * h for b, h, _, _ in rects))
    assert p["Iy"] > p["Iz"]                       # deeper than it is wide
    assert p["ASz"] == pytest.approx(2 * p["tw"] * p["d"])
    assert builtup.weight_plf(spec) == pytest.approx(p["A"] / 144 * 490.0)


def test_cover_plates_close_the_box_and_stiffen_it_in_torsion():
    open_j = builtup.properties("2P24x1/2 4L4x4x1/2")["J"]
    closed_j = builtup.properties("4P24x1/2 2P16x7/16 4L4x4x1/2")["J"]
    assert closed_j > 50 * open_j                  # closed section, by far

    assert len(builtup.rects("4P24x1/2 2P16x7/16 4L4x4x1/2")[0]) == 12
    assert len(builtup.piece_labels("4P24x1/2 2P16x7/16 4L4x4x1/2")) == 12


def test_six_inch_angles_widen_the_assumed_web_spacing():
    assert builtup.WIDTH((4, 6.0, 6.0, 0.5)) == 20.0
    assert builtup.WIDTH((4, 6.0, 4.0, 0.5)) == 18.0
    assert builtup.envelope("4P30x5/8 4L6x6x5/8")[0] == 20.0


def test_a_spec_without_plates_or_angles_is_rejected():
    with pytest.raises(ValueError, match="no web plates"):
        builtup.parse("W24x76")


def test_framing_weight_comes_from_the_plates_not_a_fill_fraction():
    """A 4'-7 3/8 in floor beam is about 48 in^2 of steel.  Guessing it as a
    fraction of its 55 x 14 in envelope overstates it several times over, and
    on a truss bridge the floor system is a large share of the dead load --
    it put the whole model 60% heavy before this was fixed."""
    fb = rt.FramingMember("fb", "U0", "U1", "FB upper", depth_in=55.375,
                          width_in=14.0, web_t_in=0.375, flange_t_in=1.0)
    assert fb.area_in2 == pytest.approx(0.375 * 53.375 + 2 * 14.0 * 1.0)
    assert fb.area_in2 == pytest.approx(48.0, abs=0.1)
    assert fb.area_in2 / 144 * 490 == pytest.approx(163.0, abs=1.0)   # plf
    # nowhere near the envelope
    assert fb.area_in2 < 0.07 * fb.depth_in * fb.width_in


def test_framing_draws_a_web_and_two_flanges_at_lod400():
    m = panel_truss()
    f = rt.FramingMember("fb", "U0", "U1", "FB upper", role="floor_beam",
                         depth_in=55.375, width_in=14.0, web_t_in=0.375,
                         flange_t_in=1.0)
    objs = rt.framing_objects(m, f, lod=400)
    assert len(objs) == 3
    assert [o.tags["framing.piece"] for o in objs] == \
        ["web", "bottom flange", "top flange"]
    assert sum("pay.qty" in o.tags for o in objs) == 1     # counted once
    assert len(rt.framing_objects(m, f, lod=300)) == 1


# --------------------------------------------------------------------------- #
# the outline is clipped to the plate size that is independently known
# --------------------------------------------------------------------------- #
def _ends_at_a_four_member_joint():
    """Chord through, vertical down, diagonal down -- a normal panel point."""
    d = math.sqrt(0.5)
    return [
        rt.MemberEndAtJoint("Lm", (-1.0, 0.0), 24.0, 40.0, through=True),
        rt.MemberEndAtJoint("Lp", (1.0, 0.0), 24.0, 40.0, through=True),
        rt.MemberEndAtJoint("V", (0.0, 1.0), 20.0, 45.0),
        rt.MemberEndAtJoint("D", (d, d), 24.0, 60.0),
    ]


def test_clipping_keeps_the_outline_inside_the_tabulated_plate():
    """The rule puts each corner where its member needs it, which at a tight
    joint lands outside the plate the shop actually cut.  The overall width
    and depth are the one plate dimension the 2012 rating confirms, so the
    outline is held to them."""
    ends = _ends_at_a_four_member_joint()
    wp = (45.0, 15.0)
    free = rt.gusset_outline_from_members(ends, work_point=wp)
    assert max(q[0] for q in free) > 90.0          # the diagonal runs out
    held = rt.gusset_outline_from_members(ends, work_point=wp,
                                       bounds=(0.0, 0.0, 90.0, 80.0))
    assert held and len(held) >= 3
    for x, y in held:
        assert -1e-6 <= x <= 90.0 + 1e-6
        assert -1e-6 <= y <= 80.0 + 1e-6


def test_clipping_only_removes_area():
    ends = _ends_at_a_four_member_joint()
    wp = (45.0, 15.0)

    def area(poly):
        a = 0.0
        for i, (x0, y0) in enumerate(poly):
            x1, y1 = poly[(i + 1) % len(poly)]
            a += x0 * y1 - x1 * y0
        return abs(a) / 2.0

    free = rt.gusset_outline_from_members(ends, work_point=wp)
    held = rt.gusset_outline_from_members(ends, work_point=wp,
                                       bounds=(0.0, 0.0, 90.0, 80.0))
    assert 0.0 < area(held) < area(free)


def test_a_polygon_already_inside_the_bounds_is_left_alone():
    ends = _ends_at_a_four_member_joint()
    wp = (45.0, 15.0)
    free = rt.gusset_outline_from_members(ends, work_point=wp)
    x0 = min(q[0] for q in free) - 5.0
    y0 = min(q[1] for q in free) - 5.0
    x1 = max(q[0] for q in free) + 5.0
    y1 = max(q[1] for q in free) + 5.0
    held = rt.gusset_outline_from_members(ends, work_point=wp,
                                       bounds=(x0, y0, x1, y1))
    assert len(held) == len(free)
    for a, b in zip(held, free):
        assert a[0] == pytest.approx(b[0])
        assert a[1] == pytest.approx(b[1])


def test_clip_polygon_to_rect_on_a_plain_square():
    sq = [(-5.0, -5.0), (15.0, -5.0), (15.0, 15.0), (-5.0, 15.0)]
    out = rt.clip_polygon_to_rect(sq, 0.0, 0.0, 10.0, 10.0)
    assert sorted(round(v, 6) for v in {q[0] for q in out}) == [0.0, 10.0]
    assert sorted(round(v, 6) for v in {q[1] for q in out}) == [0.0, 10.0]
    assert rt.clip_polygon_to_rect(sq, 100.0, 100.0, 110.0, 110.0) == []


def test_an_end_joint_closes_on_its_work_point():
    """At the end of a span every member leaves on the same side, so the
    corners span less than a half turn.  The fan they make does not enclose
    the work point, and the plate has to come back to it."""
    wp = (0.0, 0.0)
    d = math.sqrt(0.5)
    ends = [
        rt.MemberEndAtJoint("C", (1.0, 0.0), 24.0, 40.0),
        rt.MemberEndAtJoint("V", (0.0, -1.0), 24.0, 50.0),
        rt.MemberEndAtJoint("D", (d, -d), 24.0, 60.0),
    ]
    poly = rt.gusset_outline_from_members(ends, work_point=wp)
    assert wp in poly
    assert len(poly) >= 4


def test_an_interior_joint_does_not_pick_up_its_work_point():
    poly = rt.gusset_outline_from_members(_ends_at_a_four_member_joint(),
                                          work_point=(0.0, 0.0))
    assert (0.0, 0.0) not in poly
    assert len(poly) >= 4


def test_a_crowded_short_member_does_not_notch_the_plate():
    """A member whose connection is short has both its corners inside its
    neighbours'.  Taken in angular order the outline dives in to them and
    back out, cutting a deep V into the middle of the plate; on the hull it
    just passes over, and the member is still covered to its full depth."""
    d = math.sqrt(0.5)
    ends = [
        rt.MemberEndAtJoint("Lm", (-1.0, 0.0), 24.0, 60.0, through=True),
        rt.MemberEndAtJoint("Lp", (1.0, 0.0), 24.0, 60.0, through=True),
        rt.MemberEndAtJoint("V", (0.0, 1.0), 20.0, 4.0),      # short, crowded
        rt.MemberEndAtJoint("D", (d, d), 24.0, 55.0),
    ]
    poly = rt.gusset_outline_from_members(ends, work_point=(0.0, 0.0))
    # convex: every turn the same way
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        cross = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        assert cross >= -1e-6, "re-entrant vertex at %d" % i
    # the short vertical is inside the plate, not a corner of it
    assert (0.0, 6.0) not in poly


def test_the_plate_is_sized_to_hold_its_fastener_field():
    """The reach only sees rivets inside a member's own depth, and a real
    field spreads wider.  Given the field, the plate must hold all of it --
    a gusset with rivets off the plate is not a gusset."""
    ends = _ends_at_a_four_member_joint()
    wp = (45.0, 15.0)
    # a field that reaches wider than any member's depth
    field = [(20.0, 2.0), (70.0, 2.0), (70.0, 40.0), (20.0, 40.0),
             (45.0, 55.0)]
    bare = rt.gusset_outline_from_members(ends, work_point=wp)
    held = rt.gusset_outline_from_members(ends, work_point=wp, fasteners=field)

    def inside(poly, q):
        n, w = len(poly), False
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if (y0 > q[1]) != (y1 > q[1]) and \
               q[0] < (x1 - x0) * (q[1] - y0) / (y1 - y0) + x0:
                w = not w
        return w

    assert not all(inside(bare, f) for f in field)      # the point of the fix
    assert all(inside(held, f) for f in field)


def test_offset_convex_outward_pushes_every_edge_out():
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    out = rt.offset_convex_outward(sq, 2.0)
    assert min(q[0] for q in out) == pytest.approx(-2.0)
    assert min(q[1] for q in out) == pytest.approx(-2.0)
    assert max(q[0] for q in out) == pytest.approx(12.0)
    assert max(q[1] for q in out) == pytest.approx(12.0)


def test_the_fastener_field_alone_makes_a_plate():
    """At a joint whose members the model does not fully carry -- a sway
    frame, a lateral, a splice -- there is still the 1932 edge-distance rule
    to fall back on, and it beats a traced polygon that clips fasteners off
    the steel."""
    field = [(10.0, 10.0), (50.0, 10.0), (50.0, 40.0), (10.0, 40.0),
             (30.0, 55.0)]
    poly = rt.gusset_outline_from_members([], fasteners=field, edge_in=2.0)
    assert len(poly) >= 3

    def inside(p, q):
        n, w = len(p), False
        for i in range(n):
            x0, y0 = p[i]
            x1, y1 = p[(i + 1) % n]
            if (y0 > q[1]) != (y1 > q[1]) and \
               q[0] < (x1 - x0) * (q[1] - y0) / (y1 - y0) + x0:
                w = not w
        return w

    assert all(inside(poly, f) for f in field)
    # and it sits an edge distance outside them, not on them
    assert min(q[0] for q in poly) < 10.0 - 1.0
    assert max(q[1] for q in poly) > 55.0 + 1.0


def test_no_members_and_no_fasteners_is_still_nothing():
    assert rt.gusset_outline_from_members([]) == []
    assert rt.gusset_outline_from_members([], fasteners=[(0.0, 0.0)]) == []


# ---------------------------------------------------------------------------
# hub adapter: the drawn members are the analysed members
# ---------------------------------------------------------------------------
SPEC = "2P24x9/16 4L6x4x3/8"


def _warren(n=4, panel=20.0, h=15.0, normal=(0.0, 1.0, 0.0)):
    m = rt.TrussModel("warren")
    for k in range(n + 1):
        m.add_node(rt.TrussNode(f"L{k}", (k * panel, 0.0, 0.0)))
    for k in range(n):
        m.add_node(rt.TrussNode(f"U{k}", ((k + 0.5) * panel, 0.0, h)))
    for k in range(n):
        m.members.append(rt.TrussMember(f"b{k}", f"L{k}", f"L{k + 1}", SPEC, normal=normal))
        m.members.append(rt.TrussMember(f"d{k}", f"L{k}", f"U{k}", SPEC, normal=normal))
        m.members.append(rt.TrussMember(f"e{k}", f"U{k}", f"L{k + 1}", SPEC, normal=normal))
        if k:
            m.members.append(rt.TrussMember(f"t{k}", f"U{k - 1}", f"U{k}", SPEC, normal=normal))
    return m


def _plane_supports(m, n):
    hold = dict(fix_y=True, fix_rx=True, fix_rz=True)
    sup = {nid: dict(hold) for nid in m.nodes}
    sup["L0"].update(fix_x=True, fix_z=True)
    sup[f"L{n}"].update(fix_z=True)
    return sup


@pytest.mark.parametrize("n", [2, 4, 6])
@pytest.mark.parametrize("joints", ["pinned", "rigid"])
def test_hub_self_weight_is_the_builtup_weight(n, joints):
    from civilpy.structural.frame_analysis import reaction_totals, solve
    m = _warren(n)
    hub = m.to_structural_model(joints=joints, supports=_plane_supports(m, n))
    r = solve(hub)["self weight"]
    want = sum(builtup.weight_plf(SPEC) * m.length_ft(x) for x in m.members) / 1000.0
    assert reaction_totals(r)[2] == pytest.approx(want, rel=1e-9)


@pytest.mark.parametrize("n", [2, 4, 6])
def test_pinned_hub_matches_method_of_joints(n):
    from civilpy.structural.frame_analysis import solve
    from civilpy.structural.truss import Truss
    m = _warren(n)
    hub = m.to_structural_model(joints="pinned", supports=_plane_supports(m, n))
    for k in range(n):
        hub.add_load(f"U{k}", fz=-10.0, case="P")
    r = solve(hub, cases=["P"])["P"]
    t = Truss()
    for nid, node in m.nodes.items():
        t.add_node(nid, node.point[0], node.point[2])
    for x in m.members:
        t.add_member(x.i, x.j)
    t.add_support("L0", fix_x=True, fix_y=True)
    t.add_support(f"L{n}", fix_y=True)
    for k in range(n):
        t.add_load(f"U{k}", fy=-10.0)
    f = t.solve()
    for x in m.members:
        assert r.element_forces[x.id] == pytest.approx(f[(x.i, x.j)], abs=1e-6)


@pytest.mark.parametrize("normal", [(0, 1, 0), (0, -1, 0), (0, 0.8, 0.6), (0.3, 1, 0.2)])
def test_hub_local_y_follows_the_member_normal(normal):
    from civilpy.structural.frame_analysis import local_axes
    m = _warren(2, normal=normal)
    hub = m.to_structural_model()
    for x in m.members:
        e = hub.elements[x.id]
        r = local_axes(hub.nodes[x.i].coords, hub.nodes[x.j].coords, e.beta_deg)
        u, v, w, _ = rt.member_frame(m.nodes[x.i].point, m.nodes[x.j].point, normal)
        assert r[1] == pytest.approx(v, abs=1e-9)
        assert r[2] == pytest.approx(w, abs=1e-9)
        p = builtup.properties(SPEC)
        assert hub.section_properties[e.section].iy == pytest.approx(p["Iy"] / 12 ** 4)
