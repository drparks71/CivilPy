#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Tests for the EXJ-4-87 / EXJ-5-93 / VPF-1-24 emits (rhino_scd_details)
and the HW-2.1 / HW-2.2 / HW-1.1 emits (rhino_scd_headwalls)."""

import importlib
import math

import pytest

from civilpy.structural.rhino_bim import pay_item_quantities
from civilpy.structural.rhino_scd_details import (
    LAYER_FENCE,
    LAYER_JOINTS,
    box_beam_joint_emit,
    strip_seal_joint_emit,
    vandal_fence_emit,
)
from civilpy.structural.rhino_scd_headwalls import (
    LAYER_HEADWALLS,
    LAYER_PIPE,
    full_height_headwall_emit,
    headwall_emit,
)
from civilpy.transportation.alignment import Alignment, Tangent

ssj = importlib.import_module("civilpy.structural.odot.strip_seal_joint")
ssb = importlib.import_module("civilpy.structural.odot.strip_seal_joint_box_beam")
vpf = importlib.import_module("civilpy.structural.odot.vandal_fence")
hw = importlib.import_module("civilpy.structural.odot.headwall")
fhw = importlib.import_module("civilpy.structural.odot.full_height_headwall")


def _types(emit):
    return [o.tags["bim.type"] for o in emit.objects]


# ── strip seal joints ────────────────────────────────────────────────────

def test_strip_seal_joint_line_and_support_angles():
    inp = ssj.StripSealJointInput(width_ft=40.0, skew_deg=20.0, stringer_stations_ft=(4.0, 12.0, 20.0, 28.0, 36.0))
    emit = strip_seal_joint_emit(inp)
    assert _types(emit).count("expansion_joint") == 1 and _types(emit).count("joint_support_angle") == 5
    gland = emit.objects[0]
    assert gland.layer == LAYER_JOINTS and gland.kind == "polyline" and gland.tags["pay.item"] == "516E13000"
    # the gland runs across the deck, longer than the width by the skew
    assert float(gland.tags["pay.qty"]) == pytest.approx(40.0 / math.cos(math.radians(20.0)), rel=0.02)
    assert pay_item_quantities(emit)["516E13000"]["qty"] == pytest.approx(float(gland.tags["pay.qty"]), abs=0.01)
    # centred on the alignment in the default frame
    assert sum(p[0] for p in gland.points) / 2.0 == pytest.approx(0.0, abs=1e-9)
    sa = emit.objects[1]
    assert sa.tags["joint.display_only"] == "true" and "pay.item" not in sa.tags
    assert float(sa.tags["joint.a1_in"]) > 0
    assert emit.doc_tags["bim.scd"] == "EXJ-4-87"


def test_box_beam_joint_gaps_and_spacing_tags():
    inp = ssb.BoxBeamJointInput(n_beams=9, beam_width_in=48.0, skew_deg=10.0)
    emit = box_beam_joint_emit(inp)
    t = _types(emit)
    assert t.count("expansion_joint") == 1 and t.count("joint_beam_gap") == 8
    gland = emit.objects[0]
    layout = ssb.layout_box_beam_joint(inp)
    assert float(gland.tags["pay.qty"]) == pytest.approx(layout.length_ft, abs=0.001)
    assert gland.tags["joint.plate_a_in"] == f"{ssb.plate_spacing(48.0).dim_a_in}"
    gaps = [o for o in emit.objects if o.tags["bim.type"] == "joint_beam_gap"]
    assert all(g.kind == "polyline" and g.points[1][2] == pytest.approx(-0.5) for g in gaps)
    assert emit.doc_tags["exj.n_beams"] == "9"


def test_joint_on_alignment_follows_the_skewed_support_line():
    al = Alignment((0.0, 0.0), 45.0, [Tangent(500.0)])
    inp = ssj.StripSealJointInput(width_ft=30.0, skew_deg=15.0, stringer_stations_ft=(5.0, 15.0, 25.0))
    emit = strip_seal_joint_emit(inp, alignment=al, station_ft=250.0, elevation_ft=100.0)
    g = emit.objects[0]
    assert all(p[2] == pytest.approx(100.0) for p in g.points)
    f = al.frame_at(250.0)
    mid = ((g.points[0][0] + g.points[1][0]) / 2.0, (g.points[0][1] + g.points[1][1]) / 2.0)
    assert mid == pytest.approx(f["point"][:2], abs=1e-6)
    assert emit.doc_tags["scd.station_ft"] == "250"


# ── vandal fence ─────────────────────────────────────────────────────────

def test_fence_posts_rails_and_pay():
    inp = vpf.FenceRunInput(length_ft=100.0, post_name="PS-2/BP-1")
    emit = vandal_fence_emit(inp)
    layout = vpf.layout_fence_run(inp)
    posts = [o for o in emit.objects if o.tags["fence.part"] == "line post"]
    assert len(posts) == len(layout.post_stations_ft) and all(o.kind == "cylinder" and o.layer == LAYER_FENCE for o in posts)
    assert posts[0].radius_ft == pytest.approx(vpf.LINE_POST_OD_IN / 24.0)
    assert posts[0].points[1][2] == pytest.approx(layout.section.height_ft)
    # posts run along the alignment (global y in the default frame)
    ys = [o.points[0][1] for o in posts]
    assert ys == sorted(ys) and ys[-1] - ys[0] == pytest.approx(layout.post_stations_ft[-1] - layout.post_stations_ft[0])
    q = pay_item_quantities(emit)
    assert q["607E23000"]["qty"] == pytest.approx(100.0) and q["607E23000"]["objects"] == 1
    top = next(o for o in emit.objects if o.tags["fence.part"] == "top rail")
    assert top.radius_ft == pytest.approx(vpf.RAIL_OD_IN / 24.0) and top.points[0][2] == pytest.approx(layout.section.height_ft)
    assert emit.doc_tags["vpf.posts"] == str(len(posts)) and emit.doc_tags["bim.scd"] == "VPF-1-24"
    al = Alignment((10.0, 10.0), 90.0, [Tangent(300.0)])
    placed = vandal_fence_emit(inp, alignment=al, station_ft=50.0, offset_ft=22.0, elevation_ft=640.0)
    p0 = placed.objects[0].points[0]
    assert p0 == pytest.approx((60.0, 10.0 - 22.0, 640.0), abs=1e-6)     # east along x, right = -y, at the deck edge


# ── headwalls ────────────────────────────────────────────────────────────

def test_half_height_headwall_prism_and_pipe():
    inp = hw.HeadwallInput(diameter_in=36.0)
    emit = headwall_emit(inp)
    layout = hw.layout_headwall(inp)
    wall = emit.objects[0]
    assert wall.kind == "prism" and wall.layer == LAYER_HEADWALLS and wall.tags["bim.type"] == "headwall"
    assert math.hypot(wall.vector[0], wall.vector[1]) == pytest.approx(layout.width_ft)
    assert float(wall.tags["pay.qty"]) == pytest.approx(layout.concrete_cy, abs=0.001)
    pipe = emit.objects[1]
    assert pipe.kind == "cylinder" and pipe.layer == LAYER_PIPE and pipe.radius_ft == pytest.approx(1.5)
    assert pipe.tags["bim.display_only"] == "true" and "pay.item" not in pipe.tags
    assert emit.doc_tags["bim.scd"] == "HW-2.1"
    conc = headwall_emit(hw.HeadwallInput(diameter_in=36.0, concrete=True))
    assert conc.doc_tags["bim.scd"] == "HW-2.2" and conc.objects[1].tags["pipe.material"] == "concrete"
    q = pay_item_quantities(emit)
    assert q["511E40000"]["qty"] == pytest.approx(layout.concrete_cy, abs=0.01)


def test_full_height_headwall_faces_wings_and_schedule():
    inp = fhw.HeadwallInput(diameter_in=60.0, skew_deg=30.0)
    emit = full_height_headwall_emit(inp)
    layout = fhw.layout_full_height_headwall(inp)
    walls = [o for o in emit.objects if o.tags["bim.type"] == "headwall"]
    assert len(walls) == 3 and all(w.kind == "prism" for w in walls)
    ids = {w.tags["bim.id"] for w in walls}
    assert ids == {"HW1-FACE", "HW1-WW1", "HW1-WW2"}
    assert all(math.hypot(w.vector[0], w.vector[1]) == pytest.approx(layout.table.ts_ft) for w in walls)
    q = pay_item_quantities(emit)
    assert q["511E40000"]["qty"] == pytest.approx(layout.concrete_cy, abs=0.02)
    assert q["509E00200"]["qty"] == pytest.approx(layout.steel_lb, abs=0.01)
    face = next(w for w in walls if w.tags["bim.id"] == "HW1-FACE")
    # the face thickness goes into the fill: +y in the default frame
    assert face.vector[1] > 0
    opening = next(o for o in emit.objects if o.tags["bim.type"] == "pipe_opening")
    assert opening.kind == "polyline" and len(opening.points) == 25
    assert emit.doc_tags["hw.type"] in ("A", "B")
    plain = full_height_headwall_emit(inp, rebar_marker=False)
    assert "509E00200" not in pay_item_quantities(plain)
    square = full_height_headwall_emit(fhw.HeadwallInput(diameter_in=60.0))
    assert square.doc_tags["hw.type"] == "A"


def test_details_bake_and_read_back(tmp_path):
    pytest.importorskip("rhino3dm")
    from civilpy.structural.rhino_bim import emit_to_3dm, read_bim_quantities
    emits = {
        "exj4": strip_seal_joint_emit(ssj.StripSealJointInput(width_ft=36.0, skew_deg=0.0, stringer_stations_ft=(6.0, 18.0, 30.0))),
        "exj5": box_beam_joint_emit(ssb.BoxBeamJointInput(n_beams=7, beam_width_in=36.0)),
        "vpf": vandal_fence_emit(vpf.FenceRunInput(length_ft=60.0)),
        "hw2": headwall_emit(hw.HeadwallInput(diameter_in=24.0)),
        "hw1": full_height_headwall_emit(fhw.HeadwallInput(diameter_in=48.0, skew_deg=15.0)),
    }
    for name, emit in emits.items():
        path = tmp_path / f"{name}.3dm"
        counts = emit_to_3dm(emit, path, mesh=True)
        assert sum(counts.values()) == len(emit.objects), name
        back = read_bim_quantities(path)
        for item, rec in pay_item_quantities(emit).items():
            assert back[item]["qty"] == pytest.approx(rec["qty"], abs=0.01), (name, item)
