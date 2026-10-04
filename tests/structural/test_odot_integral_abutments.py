#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ICD-1-20 / ICD-2-18 integral and SICD-1-21 semi-integral abutments:
the catalogs and limits, the layouts, and their BrIM emits."""

import importlib
import math

import pytest

from civilpy.structural.rhino_bim import pay_item_quantities
from civilpy.structural.rhino_scd_substructure import (
    LAYER_SUB_DIAPHRAGMS,
    integral_abutment_emit,
    polygon_area,
    semi_integral_abutment_emit,
)
from civilpy.transportation.alignment import Alignment, Tangent, VerticalProfile

ia = importlib.import_module("civilpy.structural.odot.integral_abutment")
sa = importlib.import_module("civilpy.structural.odot.semi_integral_abutment")

IAB = ia.IntegralAbutmentInput(width_ft=44.0, skew_deg=20.0, n_piles=6, pile_spacing_ft=7.0, cap_height_ft=4.0, diaphragm_height_ft=6.0)
SAB = sa.SemiIntegralAbutmentInput(width_ft=44.0, skew_deg=15.0, stem_height_ft=12.0, diaphragm_height_ft=6.0, n_supports=6, support_spacing_ft=7.0)


# ── catalogs and limits ─────────────────────────────────────────────────

def test_pile_table_and_spacing_limits():
    assert ia.min_pile_length_ft("HP10x42") == 30.0 and ia.min_pile_length_ft("HP10x42", "sand") == 25.0
    assert ia.min_pile_length_ft('14" CIP') == 50.0
    assert ia.pile_row("HP14X73").diameter_in == pytest.approx(math.hypot(13.6, 14.6))
    assert ia.min_pile_spacing_ft("HP12X53") == pytest.approx(3 * math.hypot(11.8, 12.0) / 12.0)
    with pytest.raises(KeyError, match="approval"):
        ia.pile_row("HP16X88")
    with pytest.raises(ValueError):
        ia.min_pile_length_ft("HP12X53", "rock")


def test_expansion_length_interpolates_by_skew_and_beam_type():
    assert ia.max_expansion_length_ft(0.0) == 267.0 and ia.max_expansion_length_ft(30.0) == 133.0
    assert ia.max_expansion_length_ft(15.0) == pytest.approx(200.0)
    assert ia.max_expansion_length_ft(0.0, "ps_i") == 333.0 and ia.max_expansion_length_ft(-30.0, "ps_i") == 166.5
    with pytest.raises(ValueError, match="30"):
        ia.max_expansion_length_ft(31.0)
    with pytest.raises(ValueError):
        ia.max_expansion_length_ft(0.0, "timber")
    assert ia.rebar_mark("A401").bend_type == 3 and ia.rebar_mark("D801").bend_type == 18
    with pytest.raises(KeyError):
        ia.rebar_mark("Z999")


# ── integral layout ──────────────────────────────────────────────────────

def test_integral_layout_geometry():
    L = ia.layout_integral_abutment(IAB)
    assert L.length_ft == pytest.approx(47.0)                     # 44 + 2 x 1.5 protrusion
    assert len(L.pile_points) == 6 and all(p[2] == pytest.approx(-2.0) for p in L.pile_points)   # embedded 2 ft
    xs = [p[0] for p in L.pile_points]
    assert max(xs) - min(xs) == pytest.approx(35.0) and sum(xs) / 6 == pytest.approx(0.0, abs=1e-9)
    assert L.cap_outline == L.diaphragm_outline and all(p[2] == 0.0 for p in L.cap_outline)
    # the cap plan is a 47 x 3 ft parallelogram sheared by the skew
    assert polygon_area(L.cap_outline) == pytest.approx(47.0 * 3.0)
    assert L.max_expansion_length_ft == pytest.approx(267 - (267 - 133) * 20 / 30)
    # wingwalls beside the diaphragm ends: from its back face 2.5 ft toward the bridge, up to the diaphragm height
    wl, wr = L.wingwall_left, L.wingwall_right
    assert wl[0][1] == pytest.approx(-1.5) and wl[3][1] - wl[0][1] == pytest.approx(2.5) and wl[1][2] == pytest.approx(6.0)
    assert wr[0][0] - wl[0][0] == pytest.approx(47.0 + 2 * 2.0 / 12.0, abs=1e-9)
    assert L.seat_notch[0][2] == pytest.approx(6.0)
    assert "ICD-1-20" in L.notes[0]
    ps = ia.layout_integral_abutment(ia.IntegralAbutmentInput(40.0, 0.0, 5, 6.0, 3.0, 7.0, beam_type="ps_i", wingwall_height_ft=4.0))
    assert "ICD-2-18" in ps.notes[0] and ps.wingwall_left[1][2] == 4.0 and ps.max_expansion_length_ft == 333.0


@pytest.mark.parametrize("bad, match", [
    (dict(width_ft=0.0), "positive"),
    (dict(n_piles=3), "at least 4"),
    (dict(pile_spacing_ft=9.0), "spacing"),
    (dict(pile_spacing_ft=2.0), "spacing"),
    (dict(cap_height_ft=8.0), "cap height"),
    (dict(cap_height_ft=2.0), "cap height"),
    (dict(skew_deg=35.0), "30"),
    (dict(n_piles=9, pile_spacing_ft=8.0), "do not fit"),
])
def test_integral_layout_limits(bad, match):
    kw = dict(width_ft=44.0, skew_deg=20.0, n_piles=6, pile_spacing_ft=7.0, cap_height_ft=4.0, diaphragm_height_ft=6.0)
    kw.update(bad)
    with pytest.raises(ValueError, match=match):
        ia.layout_integral_abutment(ia.IntegralAbutmentInput(**kw))


# ── semi-integral layout ────────────────────────────────────────────────

def test_semi_integral_layout_piles_and_shafts():
    L = sa.layout_semi_integral_abutment(SAB)
    assert L.length_ft == pytest.approx(47.0)
    assert len(L.support_points) == 12                             # two rows of six
    ys = {round(p[1] - (p[0] - p[0]), 3) for p in L.support_points}
    assert all(p[2] == pytest.approx(-12.0 - 3.0 + 1.0) for p in L.support_points)
    assert L.footing_outline[0][2] == pytest.approx(-15.0)
    assert polygon_area(L.footing_outline) == pytest.approx(47.0 * 6.0)
    assert polygon_area(L.stem_outline) == pytest.approx(47.0 * 2.0)
    assert L.diaphragm_bottom_ft == pytest.approx(0.75) and L.seat_notch[0][2] == pytest.approx(6.75)
    assert len(L.guide_points) == 2 and all(g[2] == 0.0 for g in L.guide_points)
    shafts = sa.layout_semi_integral_abutment(sa.SemiIntegralAbutmentInput(40.0, 0.0, 10.0, 6.0, 4, 8.0, foundation="shafts", guides=3))
    assert len(shafts.support_points) == 4 and polygon_area(shafts.footing_outline) == pytest.approx(43.0 * 4.0)
    assert len(shafts.guide_points) == 3
    for bad, match in ((dict(foundation="caissons"), "foundation"), (dict(n_supports=1), "2 supports"),
                       (dict(support_spacing_ft=9.0), "maximum"), (dict(stem_height_ft=0.0), "positive"),
                       (dict(n_supports=12, support_spacing_ft=8.0), "do not fit")):
        kw = dict(width_ft=44.0, skew_deg=15.0, stem_height_ft=12.0, diaphragm_height_ft=6.0, n_supports=6, support_spacing_ft=7.0)
        kw.update(bad)
        with pytest.raises(ValueError, match=match):
            sa.layout_semi_integral_abutment(sa.SemiIntegralAbutmentInput(**kw))


# ── emits ────────────────────────────────────────────────────────────────

def _by(emit, t):
    return [o for o in emit.objects if o.tags.get("bim.type") == t]


def test_integral_emit_objects_and_quantities():
    emit = integral_abutment_emit(IAB)
    assert len(_by(emit, "abutment_cap")) == 1 and len(_by(emit, "pile")) == 6
    assert len(_by(emit, "end_diaphragm")) == 1 and len(_by(emit, "wingwall")) == 2 and len(_by(emit, "approach_slab_seat")) == 1
    dia = _by(emit, "end_diaphragm")[0]
    assert dia.layer == LAYER_SUB_DIAPHRAGMS and dia.tags["pay.item"] == "511E12100"
    assert float(dia.tags["pay.qty"]) == pytest.approx(47.0 * 3.0 * 6.0 / 27.0, abs=0.01)
    q = pay_item_quantities(emit)
    assert q["511E12100"]["qty"] == pytest.approx(47 * 3 * 6 / 27, abs=0.01)
    assert q["507E10000"]["qty"] == pytest.approx(6 * 35.0)        # HP12x53 in clay: 35 ft minimum
    cap_cy = 47.0 * 3.0 * 4.0 / 27.0
    assert q["511E40000"]["qty"] > cap_cy and q["511E40000"]["qty"] < cap_cy + 10.0
    pile = _by(emit, "pile")[0]
    assert pile.points[0][2] == pytest.approx(-2.0) and pile.points[1][2] == pytest.approx(-37.0)
    assert emit.doc_tags["iab.max_expansion_length_ft"] == "178" and emit.doc_tags["bim.scd"] == "ICD-1-20"
    sand = integral_abutment_emit(IAB, soil="sand")
    assert pay_item_quantities(sand)["507E10000"]["qty"] == pytest.approx(6 * 25.0)
    given = integral_abutment_emit(IAB, pile_length_ft=60.0)
    assert pay_item_quantities(given)["507E10000"]["qty"] == pytest.approx(360.0)
    with pytest.raises(ValueError):
        integral_abutment_emit(IAB, pile_length_ft=0.0)


def test_integral_emit_on_alignment_with_profile():
    al = Alignment((100.0, 200.0), 90.0, [Tangent(800.0)], profile=VerticalProfile([(0.0, 650.0, 0.0), (800.0, 658.0, 0.0)]))
    emit = integral_abutment_emit(IAB, alignment=al, station_ft=400.0, side="far")
    cap = _by(emit, "abutment_cap")[0]
    assert all(p[2] == pytest.approx(654.0) for p in cap.points)   # seat at the profile elevation
    cx = sum(p[0] for p in cap.points) / 4.0
    assert cx == pytest.approx(500.0, abs=1e-6)
    # far side: the wingwall root (back face) is at the higher station, its 2.5 ft run toward the bridge (-x here)
    wl = _by(emit, "wingwall")[0]
    assert wl.points[0][0] > wl.points[2][0]


def test_semi_integral_emit_piles_and_shafts():
    emit = semi_integral_abutment_emit(SAB)
    assert len(_by(emit, "backwall")) == 1 and len(_by(emit, "footing")) == 1 and len(_by(emit, "pile")) == 12
    assert len(_by(emit, "end_diaphragm")) == 1 and len(_by(emit, "diaphragm_guide")) == 2
    q = pay_item_quantities(emit)
    assert q["507E10000"]["qty"] == pytest.approx(12 * 40.0)
    assert q["511E40000"]["qty"] == pytest.approx(47 * 2 * 12 / 27 + 47 * 6 * 3 / 27 + 2 * polygon_area(_by(emit, "wingwall")[0].points) * 1.5 / 27, abs=0.05)
    dia = _by(emit, "end_diaphragm")[0]
    assert all(p[2] == pytest.approx(0.75) for p in dia.points) and float(dia.tags["diaphragm.clearance_in"]) == 9.0
    shafts = semi_integral_abutment_emit(sa.SemiIntegralAbutmentInput(40.0, 0.0, 10.0, 6.0, 4, 8.0, foundation="shafts"), shaft_length_ft=25.0)
    sh = _by(shafts, "drilled_shaft")
    assert len(sh) == 4 and sh[0].radius_ft == 1.5 and "507E10000" not in pay_item_quantities(shafts)
    assert float(sh[0].tags["pay.qty"]) == pytest.approx(math.pi / 4 * 9 * 25 / 27, abs=0.01)
    assert emit.doc_tags["sab.guides"] == "2" and _by(emit, "diaphragm_guide")[0].tags["bim.scd"] == "SICD-2-14"
    with pytest.raises(ValueError):
        semi_integral_abutment_emit(SAB, pile_length_ft=0.0)


def test_integral_emits_bake_and_read_back(tmp_path):
    pytest.importorskip("rhino3dm")
    from civilpy.structural.rhino_bim import emit_to_3dm, read_bim_quantities
    for name, emit in (("iab", integral_abutment_emit(IAB)), ("sab", semi_integral_abutment_emit(SAB))):
        path = tmp_path / f"{name}.3dm"
        counts = emit_to_3dm(emit, path, mesh=True)
        assert sum(counts.values()) == len(emit.objects)
        back = read_bim_quantities(path)
        for item, rec in pay_item_quantities(emit).items():
            assert back[item]["qty"] == pytest.approx(rec["qty"], abs=0.01), (name, item)
