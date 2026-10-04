#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Tests for the CPA-1-08 / CPP-1-08 / A-1-20 BrIM emits (rhino_scd_substructure).

Covers the support-line placement contract (alignment + station, skew,
offset, elevation, near / far), the object inventory and layers, the
concrete and pile quantities from the geometry, and the 3dm round trip.
"""

import math

import pytest

from civilpy.structural.odot import capped_pile_abutment as cpa
from civilpy.structural.odot import capped_pile_pier as cpp
from civilpy.structural.odot import typical_abutment as a120
from civilpy.structural.rhino_bim import pay_item_quantities
from civilpy.structural.rhino_layers import (
    LAYER_SUB_BACKWALLS,
    LAYER_SUB_CAPS,
    LAYER_SUB_FOOTINGS,
    LAYER_SUB_PILES,
    LAYER_SUB_WINGWALLS,
)
from civilpy.structural.rhino_scd_substructure import (
    SupportFrame,
    capped_pile_abutment_emit,
    capped_pile_pier_emit,
    polygon_area,
    prism_volume_cy,
    typical_abutment_emit,
)
from civilpy.transportation.alignment import Alignment, Tangent, VerticalProfile

CPA_IN = cpa.AbutmentInput(wingwall_length_ft=12.0, skew_deg=20.0, n_piles=6, pile_spacing_ft=7.0, footing_depth_ft=3.0)
CPP_IN = cpp.PierInput(slab_width_ft=40.0, skew_deg=15.0, n_piles=6, pile_spacing_ft=7.0)
ABT_IN = a120.AbutmentInput(width_ft=44.0, skew_deg=10.0, wingwall_length_ft=14.0, footing_depth_ft=3.0, backwall_height_ft=5.0)
ABT_SQ = a120.AbutmentInput(width_ft=44.0, skew_deg=0.0, wingwall_length_ft=14.0, footing_depth_ft=3.0, backwall_height_ft=5.0)


def _by_type(emit, t):
    return [o for o in emit.objects if o.tags.get("bim.type") == t]


def _align():
    return Alignment((1000.0, 2000.0), 60.0, [Tangent(1200.0)],
                     profile=VerticalProfile([(0.0, 600.0, 0.0), (1200.0, 612.0, 0.0)]))


# ── geometry helpers ─────────────────────────────────────────────────────

def test_polygon_area_and_prism_volume():
    sq = ((0, 0, 0), (10, 0, 0), (10, 4, 0), (0, 4, 0))
    assert polygon_area(sq) == pytest.approx(40.0)
    assert prism_volume_cy(sq, (0, 0, -3)) == pytest.approx(120.0 / 27.0)
    assert prism_volume_cy(sq, (5, 0, 0)) == pytest.approx(0.0)          # extrusion in the plane
    assert prism_volume_cy(((0, 0, 0), (1, 0, 0), (2, 0, 0)), (0, 0, 1)) == 0.0   # degenerate


# ── frame ────────────────────────────────────────────────────────────────

def test_frame_defaults_and_guards():
    f = SupportFrame()
    assert f.point(3.0, 2.0, 1.0) == pytest.approx((3.0, 2.0, 1.0))
    assert f.vector(1.0, 0.0) == pytest.approx((1.0, 0.0, 0.0))
    far = SupportFrame(side="far", elevation_ft=50.0)
    assert far.point(3.0, 2.0, 1.0) == pytest.approx((-3.0, -2.0, 51.0))
    with pytest.raises(ValueError, match="side"):
        SupportFrame(side="middle")
    with pytest.raises(ValueError, match="station_ft"):
        SupportFrame(_align())


def test_frame_on_alignment_uses_profile_and_skew():
    al = _align()
    f = SupportFrame(al, 600.0, offset_ft=5.0, skew_deg=30.0)
    fr = al.frame_at(600.0)
    assert f.origin[2] == pytest.approx(606.0)
    # offset moves the origin along the alignment's right vector
    assert f.origin[0] == pytest.approx(fr["point"][0] + 5.0 * fr["right"][0])
    # the a-axis is the right vector rotated 30 deg toward back, unit length, 30 deg from right
    ang = math.degrees(math.acos(f.a[0] * fr["right"][0] + f.a[1] * fr["right"][1]))
    assert ang == pytest.approx(30.0)
    assert math.hypot(*f.a) == pytest.approx(1.0) and math.hypot(*f.b) == pytest.approx(1.0)
    assert f.a[0] * f.b[0] + f.a[1] * f.b[1] == pytest.approx(0.0)
    g = SupportFrame(al, 600.0, elevation_ft=700.0)
    assert g.origin[2] == 700.0
    bare = Alignment((0.0, 0.0), 0.0, [Tangent(100.0)])
    assert SupportFrame(bare, 10.0).origin[2] == 0.0


# ── CPA-1-08 ─────────────────────────────────────────────────────────────

def test_cpa_inventory_layers_and_quantities():
    emit = capped_pile_abutment_emit(CPA_IN, pile_length_ft=50.0)
    caps, piles, wings = _by_type(emit, "abutment_cap"), _by_type(emit, "pile"), _by_type(emit, "wingwall")
    assert len(caps) == 1 and len(piles) == 6 and len(wings) == 2
    assert caps[0].layer == LAYER_SUB_CAPS and all(p.layer == LAYER_SUB_PILES for p in piles)
    assert all(w.layer == LAYER_SUB_WINGWALLS for w in wings)
    cap_len = 5 * 7.0 + 3.0
    expected_cy = cap_len * 3.0 * 3.0 / 27.0                 # the skew shear keeps the plan area
    q = pay_item_quantities(emit)
    assert q["507E10000"]["qty"] == pytest.approx(6 * 50.0)
    wing_cy = sum(polygon_area(w.points) * 1.5 / 27.0 for w in wings)
    assert q["511E40000"]["qty"] == pytest.approx(expected_cy + wing_cy, abs=0.02)
    assert caps[0].tags["bim.scd"] == "CPA-1-08" and emit.doc_tags["bim.scd"] == "CPA-1-08"
    assert emit.doc_tags["cpa.cap_length_ft"] == f"{cap_len:g}"
    # piles hang from the cap bottom
    for p in piles:
        assert p.points[0][2] == pytest.approx(-3.0) and p.points[1][2] == pytest.approx(-53.0)
    # the second wingwall mirrors the first about the cap centre (same reach, same rise)
    w1, w2 = wings
    assert math.hypot(*w1.points[0][:2]) == pytest.approx(math.hypot(*w2.points[0][:2]))
    assert [p[2] for p in w1.points] == pytest.approx([p[2] for p in w2.points])


def test_cpa_one_wingwall_and_guards():
    emit = capped_pile_abutment_emit(CPA_IN, both_wingwalls=False)
    assert len(_by_type(emit, "wingwall")) == 1
    with pytest.raises(ValueError):
        capped_pile_abutment_emit(CPA_IN, pile_length_ft=0.0)
    with pytest.raises(ValueError):
        capped_pile_abutment_emit(CPA_IN, wingwall_thickness_ft=-1.0)


def test_cpa_placement_on_alignment_far_side():
    al = _align()
    near = capped_pile_abutment_emit(CPA_IN, alignment=al, station_ft=300.0, elevation_ft=650.0)
    far = capped_pile_abutment_emit(CPA_IN, alignment=al, station_ft=900.0, elevation_ft=655.0, side="far")
    fr = al.frame_at(300.0)
    cap = _by_type(near, "abutment_cap")[0]
    cx = sum(p[0] for p in cap.points) / 4.0
    cy = sum(p[1] for p in cap.points) / 4.0
    assert (cx, cy) == pytest.approx(fr["point"][:2], abs=1e-6)
    assert all(p[2] == pytest.approx(650.0) for p in cap.points)
    # the wingwall flares behind the abutment: toward lower stations on the near side, higher on the far side
    def flare_along(emit, sta):
        w = _by_type(emit, "wingwall")[0]
        t = al.frame_at(sta)["tangent"]
        root, tip = w.points[0], w.points[2]
        return (tip[0] - root[0]) * t[0] + (tip[1] - root[1]) * t[1]
    assert flare_along(near, 300.0) < 0 and flare_along(far, 900.0) > 0
    assert near.doc_tags["scd.station_ft"] == "300" and far.doc_tags["scd.side"] == "far"


# ── CPP-1-08 ─────────────────────────────────────────────────────────────

def test_cpp_cap_centred_piles_and_quantities():
    emit = capped_pile_pier_emit(CPP_IN, pile_length_ft=45.0)
    cap = _by_type(emit, "pier_cap")[0]
    piles = _by_type(emit, "pile")
    assert cap.layer == LAYER_SUB_CAPS and len(piles) == 6
    xs = [p[0] for p in cap.points]
    assert (max(xs) + min(xs)) / 2.0 == pytest.approx(0.0, abs=1e-9)        # centred on the alignment
    layout = cpp.layout_capped_pile_pier(CPP_IN)
    q = pay_item_quantities(emit)
    assert q["507E10000"]["qty"] == pytest.approx(6 * 45.0)
    area = polygon_area(cap.points)
    assert q["511E40000"]["qty"] == pytest.approx(area * 2.0 / 27.0, abs=0.01)     # roll-up rounds to 0.01 cy
    assert emit.doc_tags["bim.scd"] == "CPP-1-08"
    with pytest.raises(ValueError):
        capped_pile_pier_emit(CPP_IN, pile_length_ft=0.0)


def test_cpp_on_alignment_rotates_with_skew():
    al = _align()
    emit = capped_pile_pier_emit(CPP_IN, alignment=al, station_ft=600.0)
    cap = _by_type(emit, "pier_cap")[0]
    assert all(p[2] == pytest.approx(606.0) for p in cap.points)   # profile elevation at the station
    # the long axis of the cap is the alignment normal rotated by the skew
    xs = [p[0] for p in cap.points]
    ys = [p[1] for p in cap.points]
    i0, i1 = xs.index(min(xs)), xs.index(max(xs))
    d = (xs[i1] - xs[i0], ys[i1] - ys[i0])
    f = SupportFrame(al, 600.0, skew_deg=15.0)
    cos = abs(d[0] * f.a[0] + d[1] * f.a[1]) / math.hypot(*d)
    assert cos > 0.95


# ── A-1-20 ───────────────────────────────────────────────────────────────

def test_a120_inventory_footing_fix_and_quantities():
    emit = typical_abutment_emit(ABT_SQ)
    bw, ftg, wings = _by_type(emit, "backwall")[0], _by_type(emit, "footing")[0], _by_type(emit, "wingwall")
    assert bw.layer == LAYER_SUB_BACKWALLS and ftg.layer == LAYER_SUB_FOOTINGS and len(wings) == 2
    assert bw.vector == (0.0, 0.0, 5.0) and all(p[2] == 0.0 for p in bw.points)
    assert ftg.vector == (0.0, 0.0, 3.0) and all(p[2] == -3.0 for p in ftg.points)   # -depth up to the seat
    # centred along the support line
    assert sum(p[0] for p in bw.points) / 4.0 == pytest.approx(0.0, abs=1e-9)
    q = pay_item_quantities(emit)
    bw_cy = 44.0 * a120.BACKWALL_TOP_WIDTH_FT * 5.0 / 27.0
    ftg_cy = 44.0 * (a120.BACKWALL_TOP_WIDTH_FT + 4.0) * 3.0 / 27.0
    wing_cy = 2 * polygon_area(wings[0].points) * 1.5 / 27.0
    assert q["511E40000"]["qty"] == pytest.approx(bw_cy + ftg_cy + wing_cy, rel=1e-3)
    assert "507E10000" not in q
    assert emit.doc_tags["abt.guidance_only"] == "true" and emit.doc_tags["bim.scd"] == "A-1-20"
    one = typical_abutment_emit(ABT_IN, both_wingwalls=False)
    assert len(_by_type(one, "wingwall")) == 1
    with pytest.raises(ValueError):
        typical_abutment_emit(ABT_IN, wingwall_thickness_ft=0.0)


def test_a120_wingwalls_flare_from_both_ends():
    emit = typical_abutment_emit(ABT_SQ)
    skewed = typical_abutment_emit(ABT_IN)
    assert len(skewed.objects) == len(emit.objects)
    w1, w2 = _by_type(emit, "wingwall")
    # roots at opposite ends of the backwall (x = +-W/2), tips further out
    assert w1.points[0][0] == pytest.approx(22.0, abs=1e-6) and w2.points[0][0] == pytest.approx(-22.0, abs=1e-6)
    assert abs(w1.points[2][0]) > 22.0 and abs(w2.points[2][0]) > 22.0
    assert w1.vector[2] == 0.0 and math.hypot(w1.vector[0], w1.vector[1]) == pytest.approx(1.5)


# ── 3dm round trip ───────────────────────────────────────────────────────

def test_emits_bake_and_read_back(tmp_path):
    pytest.importorskip("rhino3dm")
    from civilpy.structural.rhino_bim import emit_to_3dm, read_bim_quantities
    for name, emit in (("cpa", capped_pile_abutment_emit(CPA_IN)), ("cpp", capped_pile_pier_emit(CPP_IN)),
                       ("abt", typical_abutment_emit(ABT_IN))):
        path = tmp_path / f"{name}.3dm"
        counts = emit_to_3dm(emit, path, mesh=True)
        assert sum(counts.values()) == len(emit.objects)
        back = read_bim_quantities(path)
        for item, rec in pay_item_quantities(emit).items():
            assert back[item]["qty"] == pytest.approx(rec["qty"], rel=1e-3)
