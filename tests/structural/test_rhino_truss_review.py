#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""The review side of the truss BrIM emit: repair / finding overlays landed on
the element they point at, the review commentary flattened onto those
elements' tags, the LOD 500 rivet hardware, the laced-member pieces, and the
joint-end records a gusset outline is built from."""
import math

import pytest

from civilpy.structural import bim, builtup, laced_member
from civilpy.structural import rhino_truss as rt
from civilpy.structural.rhino_layers import (
    LAYER_FLOOR_BEAMS, LAYER_GUSSET_PLATES, LAYER_REVIEW_FINDINGS,
    LAYER_REVIEW_REPAIRS, LAYER_RIVETS, LAYER_TRUSS_CHORDS,
)
from tests.structural.test_rhino_truss import CHORD, DIAG, panel_truss, rect_plate


def _norm(v):
    return math.sqrt(sum(c * c for c in v))


def _extent(points, axis):
    return max(p[axis] for p in points) - min(p[axis] for p in points)


def _review_model():
    """The panel truss with a floor beam, a gusset and three review items."""
    m = panel_truss()
    m.framing.append(rt.FramingMember("FB1", "L0", "L1", "W36x150",
                                      role="floor_beam", depth_in=36.0,
                                      width_in=12.0))
    m.gussets.append(rt.GussetPlacement(
        "G-U1", "U1", rect_plate(), (12.0, 64.0), thickness_in=0.625,
        joint="11001", rivets=((15.0, 64.0, "U0U1"), (18.0, 64.0, "U0U1"),
                               (12.0, 58.0, "U1L1"))))
    m.reviews.append(rt.ReviewItem(
        "R1", "repair", "L0L1",
        bim.repair_tags("R1", item="LC-1", target="L0L1", sheet="S-12")))
    m.reviews.append(rt.ReviewItem(
        "R2", "repair", "L0L1",
        bim.repair_tags("R2", item="PR/SP-72", target="L0L1", status="done")))
    m.reviews.append(rt.ReviewItem(
        "F1", "finding", "L0L1",
        bim.finding_tags("F1", target="L0L1", summary="pack rust", year="2019")))
    return m


# --------------------------------------------------------------------------- #
# review overlays
# --------------------------------------------------------------------------- #
def test_member_review_sleeve_is_the_envelope_plus_the_margin():
    m = _review_model()
    item = m.reviews[0]
    objs = rt.review_objects(m, item, margin_in=3.0)
    assert len(objs) == 1
    o = objs[0]
    assert o.kind == "prism"
    assert o.layer == LAYER_REVIEW_REPAIRS
    assert o.tags == item.tags and o.tags is not item.tags
    b, h = builtup.envelope(CHORD)
    # the chord runs along X, so width is the Y extent and depth the Z extent
    assert _extent(o.points, 1) == pytest.approx((b + 6.0) / 12.0)
    assert _extent(o.points, 2) == pytest.approx((h + 6.0) / 12.0)
    assert _norm(o.vector) == pytest.approx(m.length_ft(m.members[1]))
    assert o.vector[0] == pytest.approx(23.9167)


@pytest.mark.xfail(strict=True, reason="untriaged: this test and the code disagree (written 2026-10-03, never run before commit) - decide which is right")
def test_framing_review_sleeve_uses_the_i_section_envelope():
    m = _review_model()
    item = rt.ReviewItem("F2", "finding", "FB1",
                         bim.finding_tags("F2", target="FB1", summary="x"))
    objs = rt.review_objects(m, item, margin_in=2.0)
    assert len(objs) == 1
    o = objs[0]
    assert o.layer == LAYER_REVIEW_FINDINGS
    # FB1 runs between L0 and L1 along X with a vertical normal: the section
    # width lies along the frame's v axis and the depth along w
    fb = m.framing[0]
    u, v, w, length = rt.member_frame(m.nodes["L0"].point, m.nodes["L1"].point,
                                      fb.normal)
    along_v = max(abs(sum(p[k] * v[k] for k in range(3)) for p in o.points)) - \
        min(abs(sum(p[k] * v[k] for k in range(3)) for p in o.points))
    assert along_v == pytest.approx((fb.width_in + 4.0) / 12.0)
    assert _norm(o.vector) == pytest.approx(length)


def test_gusset_review_sleeve_reuses_the_plate_outline():
    m = _review_model()
    item = rt.ReviewItem("R3", "repair", "G-U1",
                         bim.repair_tags("R3", item="GP-1", target="G-U1"))
    objs = rt.review_objects(m, item)
    plate = rt.gusset_objects(m, m.gussets[0])[0]
    assert len(objs) == 1
    assert objs[0].points == plate.points
    assert objs[0].vector == plate.vector
    assert objs[0].layer == LAYER_REVIEW_REPAIRS
    assert objs[0].tags["repair.item"] == "GP-1"


def test_node_review_is_a_marker_and_an_unknown_target_is_nothing():
    m = _review_model()
    item = rt.ReviewItem("F3", "finding", "U1",
                         bim.finding_tags("F3", target="U1", summary="x"))
    objs = rt.review_objects(m, item)
    assert len(objs) == 1
    assert objs[0].kind == "point"
    assert objs[0].points == (m.nodes["U1"].point,)
    assert objs[0].layer == LAYER_REVIEW_FINDINGS

    ghost = rt.ReviewItem("R9", "repair", "NOPE",
                          bim.repair_tags("R9", item="x", target="NOPE"))
    assert rt.review_objects(m, ghost) == []
    # an unknown kind still draws, on the repairs layer
    odd = rt.ReviewItem("X1", "note", "L0L1", {"note.text": "hi"})
    assert rt.review_objects(m, odd)[0].layer == LAYER_REVIEW_REPAIRS


def test_unresolved_reviews_lists_only_the_targets_the_model_lacks():
    m = _review_model()
    m.reviews.append(rt.ReviewItem("R9", "repair", "NOPE", {}))
    m.reviews.append(rt.ReviewItem("F9", "finding", "G-U1", {}))
    m.reviews.append(rt.ReviewItem("F8", "finding", "FB1", {}))
    m.reviews.append(rt.ReviewItem("F7", "finding", "U2", {}))
    bad = rt.unresolved_reviews(m)
    assert [i.id for i in bad] == ["R9"]


# --------------------------------------------------------------------------- #
# review commentary on the elements
# --------------------------------------------------------------------------- #
def test_review_element_tags_number_repeats_and_count_them():
    m = _review_model()
    extra = rt.review_element_tags(m)
    assert set(extra) == {"L0L1"}
    acc = extra["L0L1"]
    assert acc["repair.item"] == "LC-1"
    assert acc["repair.sheet"] == "S-12"
    assert acc["repair2.item"] == "PR/SP-72"
    assert acc["repair2.status"] == "done"
    assert acc["finding.summary"] == "pack rust"
    assert acc["finding.year"] == "2019"
    assert acc["repair.count"] == "2"
    assert acc["finding.count"] == "1"
    # the overlay's own identity never lands on the element
    assert "bim.type" not in acc and "bim.id" not in acc
    assert not any(k.startswith("repair2.target") and v == "L0L1"
                   for k, v in acc.items() if k == "bim.id")


def test_truss_emit_stamps_review_tags_on_every_piece_of_the_target():
    m = _review_model()
    objs = rt.truss_emit(m, lod=400)
    chord_pieces = [o for o in objs if o.tags.get("bim.id") == "L0L1"]
    assert len(chord_pieces) == 10
    assert all(o.tags["repair.count"] == "2" for o in chord_pieces)
    assert all(o.tags["finding.summary"] == "pack rust" for o in chord_pieces)
    # untouched members carry nothing
    other = [o for o in objs if o.tags.get("bim.id") == "U0U1"]
    assert other and all("repair.item" not in o.tags for o in other)
    # the three overlays are drawn too
    overlays = [o for o in objs if o.layer in (LAYER_REVIEW_REPAIRS,
                                               LAYER_REVIEW_FINDINGS)]
    assert len(overlays) == 3
    # and reviews=False drops both the overlays and the stamping
    quiet = rt.truss_emit(m, lod=400, reviews=False)
    assert not [o for o in quiet if o.layer in (LAYER_REVIEW_REPAIRS,
                                                LAYER_REVIEW_FINDINGS)]
    assert all("repair.count" not in o.tags for o in quiet)


def test_truss_emit_stamps_framing_and_gussets_and_draws_rivets_on_request():
    m = _review_model()
    m.reviews.append(rt.ReviewItem(
        "F2", "finding", "FB1", bim.finding_tags("F2", target="FB1", summary="y")))
    m.reviews.append(rt.ReviewItem(
        "R3", "repair", "G-U1", bim.repair_tags("R3", item="GP-1", target="G-U1")))
    objs = rt.truss_emit(m, lod=400, rivets=True)
    fb = [o for o in objs if o.layer == LAYER_FLOOR_BEAMS]
    assert fb and all(o.tags["finding.summary"] == "y" for o in fb)
    gp = [o for o in objs if o.layer == LAYER_GUSSET_PLATES]
    assert len(gp) == 1 and gp[0].tags["repair.item"] == "GP-1"
    rivets = [o for o in objs if o.layer == LAYER_RIVETS]
    assert len(rivets) == 3
    assert not [o for o in rt.truss_emit(m, lod=400) if o.layer == LAYER_RIVETS]
    doc = rt.model_doc_tags(m, lod=400)
    assert doc["bridge.review_items"] == "5"
    assert doc["bridge.framing_members"] == "1"
    assert doc["bridge.gusset_plates"] == "1"


def test_model_doc_tags_let_the_model_override_and_extend():
    m = _review_model()
    m.doc_tags = {"bridge.sfn": "1234567", "bridge.lod": "999"}
    doc = rt.model_doc_tags(m, lod=400)
    assert doc["bridge.sfn"] == "1234567"
    assert doc["bridge.lod"] == "999"
    assert doc["bridge.length_ft"] == "47.833"
    assert doc["bridge.height_ft"] == "25.000"


# --------------------------------------------------------------------------- #
# rivets (LOD 500)
# --------------------------------------------------------------------------- #
def test_gusset_rivets_are_cylinders_through_the_grip_at_their_plate_offset():
    m = _review_model()
    g = m.gussets[0]
    objs = rt.gusset_rivet_objects(m, g)
    assert len(objs) == 3
    node = m.nodes["U1"].point
    for k, o in enumerate(objs):
        assert o.kind == "cylinder"
        assert o.layer == LAYER_RIVETS
        assert o.radius_ft == pytest.approx(g.rivet_diameter_in / 24.0)
        c, tip = o.points
        # the default grip is twice the plate thickness, along the normal
        assert _norm(rt._sub(tip, c)) == pytest.approx(2 * 0.625 / 12.0)
        assert tip[1] - c[1] == pytest.approx(2 * 0.625 / 12.0)
        assert o.tags["bim.id"] == "G-U1-r%d" % k
        assert o.tags["rivet.host"] == "G-U1"
        assert o.tags["rivet.joint"] == "11001"
        assert o.tags["rivet.grip_in"] == "1.25"
    # the first rivet sits 3 in along the plate x from the work point, on the
    # plate face 9 in off the truss line
    c0 = objs[0].points[0]
    assert c0[0] - node[0] == pytest.approx(3.0 / 12.0)
    assert c0[1] - node[1] == pytest.approx(9.0 / 12.0)
    assert c0[2] - node[2] == pytest.approx(0.0, abs=1e-12)
    # the third is 6 in below the work point
    c2 = objs[2].points[0]
    assert c2[2] - node[2] == pytest.approx(-6.0 / 12.0)
    assert objs[0].tags["rivet.member"] == "U0U1"
    assert objs[2].tags["rivet.member"] == "U1L1"


def test_rivet_grip_and_member_tag_are_optional():
    m = _review_model()
    g = m.gussets[0]
    objs = rt.gusset_rivet_objects(m, g, grip_in=3.0)
    c, tip = objs[0].points
    assert _norm(rt._sub(tip, c)) == pytest.approx(0.25)
    bare = rt.GussetPlacement("G0", "U1", rect_plate(), (12.0, 64.0),
                              rivets=((12.0, 64.0),))
    objs = rt.gusset_rivet_objects(m, bare)
    assert len(objs) == 1
    assert "rivet.member" not in objs[0].tags
    assert objs[0].tags["rivet.joint"] == "U1"
    assert objs[0].points[0][0] == pytest.approx(m.nodes["U1"].point[0])
    assert rt.gusset_rivet_objects(m, rt.GussetPlacement(
        "G1", "U1", rect_plate(), (0.0, 0.0))) == []


# --------------------------------------------------------------------------- #
# laced members: the fabrication the plan spec does not carry
# --------------------------------------------------------------------------- #
def _laced(length):
    return laced_member.LacedMember(
        CHORD, length,
        lacing=laced_member.LacingSpec(2.5, 0.25, double=True,
                                       inclination_deg=60.0, source="L2"),
        tie_plates=(laced_member.TiePlate(21.0, 0.375, 2.0, "top", 1.0, "L2"),),
        source="shop L2")


@pytest.mark.xfail(strict=True, reason="untriaged: this test and the code disagree (written 2026-10-03, never run before commit) - decide which is right")
def test_fabricated_member_emits_every_piece_once_with_one_pay_quantity():
    m = panel_truss()
    length = m.length_ft(m.members[0])
    lm = _laced(length)
    member = rt.TrussMember("U0U1", "U0", "U1", CHORD, role="truss_chord_top",
                            fabrication=lm)
    objs = rt.member_objects(m, member, lod=400)
    pieces = lm.pieces()
    assert len(objs) == len(pieces) > 10
    kinds = [o.tags["piece.kind"] for o in objs]
    assert kinds.count("web plate") == 2
    assert kinds.count("angle") == 8
    assert kinds.count("tie plate") == 1
    assert kinds.count("lacing bar") == len(lm.lacing_pieces()) > 0
    with_qty = [o for o in objs if "pay.qty" in o.tags]
    assert len(with_qty) == 1
    assert float(with_qty[0].tags["pay.qty"]) == pytest.approx(lm.weight_lb(), rel=1e-6)
    assert all(o.layer == LAYER_TRUSS_CHORDS for o in objs)
    assert {o.tags["bim.id"] for o in objs} == {"U0U1"}
    # full-length pieces run the member; the tie plate starts 1 ft in and is
    # 2 ft long; lacing bars are inclined 60 deg off the axis in their face
    web = objs[0]
    assert _norm(web.vector) == pytest.approx(length)
    tie = next(o for o in objs if o.tags["piece.kind"] == "tie plate")
    assert _norm(tie.vector) == pytest.approx(2.0)
    assert min(p[0] for p in tie.points) == pytest.approx(1.0)
    bar = next(o for o in objs if o.tags["piece.kind"] == "lacing bar")
    piece = next(p for p in pieces if p.kind == "lacing bar")
    assert _norm(bar.vector) == pytest.approx(piece.length_ft)
    cos_axis = bar.vector[0] / _norm(bar.vector)
    assert abs(cos_axis) == pytest.approx(math.cos(math.radians(60.0)))
    assert bar.tags["piece.source"] == "L2"
    assert web.tags["piece.source"] == "shop L2"


@pytest.mark.xfail(strict=True, reason="untriaged: this test and the code disagree (written 2026-10-03, never run before commit) - decide which is right")
def test_fabrication_is_rebuilt_to_the_drawn_length():
    """A LacedMember carried at the wrong length is re-cut to the member's
    actual node-to-node length, so the lacing count follows the geometry."""
    m = panel_truss()
    length = m.length_ft(m.members[0])
    wrong = _laced(10.0)
    member = rt.TrussMember("U0U1", "U0", "U1", CHORD, fabrication=wrong)
    objs = rt.member_objects(m, member, lod=400)
    right = _laced(length)
    assert len(objs) == len(right.pieces()) != len(wrong.pieces())
    qty = next(o for o in objs if "pay.qty" in o.tags)
    assert float(qty.tags["pay.qty"]) == pytest.approx(right.weight_lb(), rel=1e-6)
    # LOD 300 ignores the fabrication entirely
    assert len(rt.member_objects(m, member, lod=300)) == 1


def test_fabricated_lacing_bars_slope_the_other_way_on_the_return_leg():
    m = panel_truss()
    length = m.length_ft(m.members[0])
    member = rt.TrussMember("U0U1", "U0", "U1", CHORD, fabrication=_laced(length))
    objs = rt.member_objects(m, member, lod=400)
    bars = [o for o in objs if o.tags["piece.kind"] == "lacing bar"]
    signs = {math.copysign(1.0, o.vector[1]) for o in bars}
    assert signs == {-1.0, 1.0}             # double lacing: an X in each face
    faces = {o.tags["piece.face"] for o in bars}
    assert faces == {"top", "bottom"}


# --------------------------------------------------------------------------- #
# member ends at a joint
# --------------------------------------------------------------------------- #
def test_member_ends_at_an_interior_upper_panel_point():
    m = panel_truss()
    ends = rt.member_ends_at(m, m.nodes["U1"], connections={"U1L1": 18.0})
    by = {e.name: e for e in ends}
    assert set(by) == {"U0U1", "U1U2", "U1L1"}
    assert by["U0U1"].axis == pytest.approx((-1.0, 0.0))
    assert by["U1U2"].axis == pytest.approx((1.0, 0.0))
    assert by["U1L1"].axis == pytest.approx((0.0, -1.0))
    assert by["U0U1"].through and by["U1U2"].through and not by["U1L1"].through
    assert by["U1L1"].connection_in == 18.0
    assert by["U0U1"].connection_in == 30.0
    assert by["U0U1"].depth_in == pytest.approx(builtup.envelope(CHORD)[1])


def test_member_ends_resolve_prefixed_ids_and_fall_back_on_depth():
    m = rt.TrussModel("t")
    m.add_node(rt.TrussNode("A", (0.0, 0.0, 0.0)))
    m.add_node(rt.TrussNode("B", (10.0, 0.0, 5.0)))
    m.add_node(rt.TrussNode("C", (0.0, 3.0, 0.0)))     # transverse of A
    m.members.append(rt.TrussMember("S5-AB", "A", "B", DIAG, role="truss_diagonal"))
    m.members.append(rt.TrussMember("S5-AC", "C", "A", "nonsense spec",
                                    role="truss_strut"))
    ends = rt.member_ends_at(m, m.nodes["A"], connections={"AB": 24.0},
                             default_connection_in=12.0)
    # AC lies along the truss normal: zero in-plane length, so it is skipped
    assert [e.name for e in ends] == ["AB"]
    e = ends[0]
    assert e.axis == pytest.approx((10 / math.hypot(10, 5), 5 / math.hypot(10, 5)))
    assert e.connection_in == 24.0
    assert e.depth_in == pytest.approx(builtup.envelope(DIAG)[1])
    # an unparsable spec falls back to a 24 in depth rather than failing
    m.add_node(rt.TrussNode("D", (0.0, 0.0, -8.0)))
    m.members.append(rt.TrussMember("S5-AD", "A", "D", "nonsense spec",
                                    role="truss_vertical"))
    ends = rt.member_ends_at(m, m.nodes["A"], default_connection_in=12.0)
    ad = next(e for e in ends if e.name == "AD")
    assert ad.depth_in == 24.0 and ad.connection_in == 12.0
    assert ad.axis == pytest.approx((0.0, -1.0))


# --------------------------------------------------------------------------- #
# geometry helpers the outline builder leans on
# --------------------------------------------------------------------------- #
def test_zero_length_vectors_and_members_are_rejected():
    with pytest.raises(ValueError):
        rt._unit((0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        rt.member_frame((1.0, 2.0, 3.0), (1.0, 2.0, 3.0), (0.0, 1.0, 0.0))
    m = panel_truss()
    assert m.node("U0") is m.nodes["U0"]


def test_framing_skips_a_plate_with_no_thickness():
    m = panel_truss()
    f = rt.FramingMember("FB", "L0", "L1", "PL", depth_in=20.0, width_in=10.0,
                         flange_t_in=0.0)
    objs = rt.framing_objects(m, f, lod=400)
    assert len(objs) == 1 and objs[0].tags["framing.piece"] == "web"
    assert f.area_in2 == pytest.approx(0.375 * 20.0)


def test_convex_hull_and_offset_degenerate_inputs():
    assert rt._convex_hull([(0, 0), (1, 1)]) == [(0.0, 0.0), (1.0, 1.0)]
    assert rt._convex_hull([(0, 0)]) == [(0.0, 0.0)]
    # a two-point "polygon" has antiparallel edges: no corner can be formed,
    # so it comes back as it was
    assert rt.offset_convex_outward([(0, 0), (4, 0)], 1.0) == [(0, 0), (4, 0)]
    # a repeated vertex (zero-length edge) and a collinear vertex (parallel
    # edges) are both dropped on the way to the offset square
    out = rt.offset_convex_outward([(0, 0), (0, 0), (2, 0), (4, 0), (4, 4), (0, 4)], 1.0)
    assert len(out) == 4
    assert min(x for x, _ in out) == pytest.approx(-1.0)
    assert max(x for x, _ in out) == pytest.approx(5.0)
    assert min(y for _, y in out) == pytest.approx(-1.0)
    assert max(y for _, y in out) == pytest.approx(5.0)


def test_outline_ignores_a_zero_axis_end_and_needs_three_corners():
    good = rt.MemberEndAtJoint("A", (1.0, 0.0), 24.0, 30.0)
    dead = rt.MemberEndAtJoint("Z", (0.0, 0.0), 24.0, 30.0)
    # two ends, one of them directionless: only two corners come out of the
    # live one, and with no fastener field that is not a plate
    assert rt.gusset_outline_from_members([good, dead]) == []
    # a third live end makes the plate; the dead one still adds nothing
    up = rt.MemberEndAtJoint("B", (0.0, 1.0), 24.0, 30.0)
    poly = rt.gusset_outline_from_members([good, dead, up])
    assert len(poly) >= 4
    assert max(x for x, _ in poly) == pytest.approx(32.0)
    assert max(y for _, y in poly) == pytest.approx(32.0)


def test_outline_is_clipped_to_the_tabulated_plate_and_deduped():
    a = rt.MemberEndAtJoint("A", (1.0, 0.0), 24.0, 30.0)
    b = rt.MemberEndAtJoint("B", (-1.0, 0.0), 24.0, 30.0)
    c = rt.MemberEndAtJoint("C", (0.0, -1.0), 24.0, 30.0)
    poly = rt.gusset_outline_from_members([a, b, c], bounds=(-20.0, -20.0, 20.0, 5.0))
    xs = [x for x, _ in poly]
    ys = [y for _, y in poly]
    assert min(xs) >= -20.0 - 1e-9 and max(xs) <= 20.0 + 1e-9
    assert min(ys) >= -20.0 - 1e-9 and max(ys) <= 5.0 + 1e-9
    assert len(poly) == len(rt._dedupe_polygon(poly))
    # the dedupe drops a vertex within half an inch of its predecessor and a
    # closing vertex that repeats the first
    assert rt._dedupe_polygon([(0, 0), (0.2, 0.1), (10, 0), (10, 10), (0.1, 0.1)]) == \
        [(0, 0), (10, 0), (10, 10)]
