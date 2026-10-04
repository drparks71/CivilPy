#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Tests for the RB-1-55 / FB-1-82 / BD-1-11 BrIM emits (rhino_scd_bearings)."""

import math

import pytest

import importlib

from civilpy.structural.odot import box_beam as bb
fbm = importlib.import_module("civilpy.structural.odot.fixed_bearing")      # the package re-exports a function of that name
rbm = importlib.import_module("civilpy.structural.odot.rocker_bolster")
from civilpy.structural.rhino_bim import pay_item_quantities
from civilpy.structural.rhino_layers import LAYER_BEARINGS, LAYER_LOAD_PLATES
from civilpy.structural.rhino_scd_bearings import fixed_bearing_emit, load_plate_emit, rocker_bolster_emit
from civilpy.transportation.alignment import Alignment, Tangent

CAP = sorted(rbm.ROCKER_BOLSTERS)[0]
FB = sorted(fbm.FIXED_BEARINGS)[0]


def _parts(emit):
    return {o.tags.get("bearing.part", o.tags.get("bim.type")): o for o in emit.objects}


def test_rocker_has_base_body_and_curved_top_paid_once():
    emit = rocker_bolster_emit(CAP, kind="rocker")
    parts = _parts(emit)
    assert set(parts) == {"base plate", "body", "rocker top"}
    assert all(o.layer == LAYER_BEARINGS for o in emit.objects)
    q = pay_item_quantities(emit)
    assert q["516E10000"]["qty"] == 1 and q["516E10000"]["objects"] == 1
    rb = rbm.rocker_bolster(CAP)
    base = parts["base plate"]
    xs = [p[0] for p in base.points]
    ys = [p[1] for p in base.points]
    # default frame: layout x (along the beam) lands on global y, y on global x
    assert max(ys) - min(ys) == pytest.approx(rb.dims["B"] / 12.0)
    assert max(xs) - min(xs) == pytest.approx(rb.dims["L"] / 12.0)
    assert base.vector[2] == pytest.approx(rb.dims["T"] / 12.0)
    body = parts["body"]
    assert body.kind == "mesh" and len(body.points) == 8 and len(body.faces) == 6
    assert max(p[2] for p in body.points) == pytest.approx((rb.dims["T"] + rb.dims["C"]) / 12.0)
    top = parts["rocker top"]
    assert top.kind == "prism" and max(p[2] for p in top.points) > max(p[2] for p in body.points)
    assert emit.objects[0].tags["bearing.fixity"] == "expansion" and emit.doc_tags["rb.kind"] == "rocker"
    assert emit.objects[0].tags["bim.scd"] == "RB-1-55"


def test_bolster_flat_top_and_kind_guard():
    emit = rocker_bolster_emit(CAP, kind="bolster")
    parts = _parts(emit)
    assert set(parts) == {"base plate", "body"}
    assert parts["base plate"].tags["bearing.fixity"] == "fixed"
    with pytest.raises(ValueError, match="kind"):
        rocker_bolster_emit(CAP, kind="roller")


def test_fixed_bearing_parts_and_pin_across_the_beam():
    emit = fixed_bearing_emit(FB)
    parts = _parts(emit)
    assert set(parts) == {"masonry plate", "pin", "top plate"}
    fb = fbm.fixed_bearing(FB)
    pin = parts["pin"]
    assert pin.kind == "cylinder" and pin.radius_ft == pytest.approx(fb.dims["DIA"] / 24.0)
    # the pin runs across the beam: along global x in the default frame, length B
    (x0, y0, z0), (x1, y1, z1) = pin.points
    assert abs(x1 - x0) == pytest.approx(fb.dims["B"] / 12.0) and y0 == pytest.approx(y1) and z0 == pytest.approx(z1)
    assert z0 == pytest.approx((fb.dims["E"] + fb.dims["H"]) / 12.0)
    assert parts["masonry plate"].vector[2] == pytest.approx(fb.dims["E"] / 12.0)
    assert parts["top plate"].vector[2] == pytest.approx(1.0 / 12.0)
    q = pay_item_quantities(emit)
    assert q["516E10000"]["qty"] == 1
    assert parts["masonry plate"].tags["bearing.kind"] == "fixed steel"
    with pytest.raises(ValueError):
        fixed_bearing_emit(FB, top_plate_thickness_in=0.0)


def test_load_plate_is_a_closed_mesh_paid_by_weight():
    emit = load_plate_emit("B1", longitudinal_grade=0.03, skew_deg=20.0)
    (plate,) = emit.objects
    assert plate.kind == "mesh" and plate.layer == LAYER_LOAD_PLATES and len(plate.points) == 8
    pad = bb.bearing_pad("B1")
    t_min = bb.BEVELED_LOAD_PLATE.min_thickness
    # plan area x min thickness x 490 pcf is a lower bound; the bevel adds the rest
    lower = pad.length * pad.width * t_min / 1728.0 * 490.0
    weight = float(plate.tags["pay.qty"])
    assert plate.tags["pay.item"] == "513E10220" and weight >= lower * 0.999
    assert weight < lower * 3.0
    q = pay_item_quantities(emit)
    assert q["513E10220"]["qty"] == pytest.approx(weight, abs=0.01)
    assert plate.tags["bim.scd"] == "BD-1-11" and emit.doc_tags["bd.pad"] == "B1"
    flat = load_plate_emit("B2")
    zs = [p[2] for p in flat.objects[0].points]
    assert max(zs) - min(zs) == pytest.approx(t_min / 12.0)


def test_bearings_place_on_an_alignment_per_girder_line():
    al = Alignment((500.0, 500.0), 30.0, [Tangent(400.0)])
    emit = rocker_bolster_emit(CAP, alignment=al, station_ft=200.0, offset_ft=-9.0, elevation_ft=612.0)
    base = emit.objects[0]
    f = al.frame_at(200.0)
    cx = sum(p[0] for p in base.points) / 4.0
    cy = sum(p[1] for p in base.points) / 4.0
    assert cx == pytest.approx(f["point"][0] - 9.0 * f["right"][0], abs=1e-6)
    assert cy == pytest.approx(f["point"][1] - 9.0 * f["right"][1], abs=1e-6)
    assert all(p[2] == pytest.approx(612.0) for p in base.points)
    # the base's long side (B, along the beam) follows the tangent
    p0, p1 = base.points[0], base.points[1]            # the B edge (along the beam)
    d = (p1[0] - p0[0], p1[1] - p0[1])
    assert abs(d[0] * f["tangent"][0] + d[1] * f["tangent"][1]) / math.hypot(*d) > 0.999
    assert emit.doc_tags["scd.station_ft"] == "200" and emit.doc_tags["scd.offset_ft"] == "-9"


def test_bearings_bake_and_read_back(tmp_path):
    pytest.importorskip("rhino3dm")
    from civilpy.structural.rhino_bim import emit_to_3dm, read_bim_quantities
    for name, emit in (("rocker", rocker_bolster_emit(CAP)), ("bolster", rocker_bolster_emit(CAP, kind="bolster")),
                       ("fb", fixed_bearing_emit(FB)), ("lp", load_plate_emit("B1", longitudinal_grade=0.02))):
        path = tmp_path / f"{name}.3dm"
        counts = emit_to_3dm(emit, path, mesh=True)
        assert sum(counts.values()) == len(emit.objects)
        back = read_bim_quantities(path)
        for item, rec in pay_item_quantities(emit).items():
            assert back[item]["qty"] == pytest.approx(rec["qty"], abs=0.01)
