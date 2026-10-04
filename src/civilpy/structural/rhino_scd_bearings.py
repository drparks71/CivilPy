#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrIM emit for the ODOT bearing SCDs: RB-1-55 rockers and bolsters,
FB-1-82 fixed bearings for steel beams, BD-1-11 beveled load plates for
box beams.

The layouts (:mod:`civilpy.structural.odot.rocker_bolster`,
:mod:`~civilpy.structural.odot.fixed_bearing`,
:func:`~civilpy.structural.odot.box_beam.layout_load_plate`) are in
**inches**, centred in plan with ``x`` along the beam (the span
direction) and ``y`` across it, ``z = 0`` at the bottom of the base /
masonry plate.  This module converts them to feet, places them on a
support line (:class:`~civilpy.structural.rhino_scd_substructure.SupportFrame`:
the beam direction is the frame's ``b`` axis, the support line its ``a``
axis) and emits tagged :class:`~civilpy.structural.rhino_bim.EmitObject`
records: ITEM 516 bearings (each) for the rocker, bolster and fixed
bearing, ITEM 513 structural steel (lb, from the plate volume at 490 pcf)
for the load plate.  It replaces the deleted Grasshopper prototypes and
fixes their recorded defects: RB drew both the rocker and the bolster
(``kind`` picks one), FB missed the base plate, BD had no preview.

Each bearing sits at ``elevation_ft`` (the top of the beam seat / cap)
and ``offset_ft`` from the alignment along the support line - call once
per girder line.
"""

from __future__ import annotations

import math

from civilpy.structural import bim
import importlib

from civilpy.structural.odot import box_beam as bb
fbm = importlib.import_module("civilpy.structural.odot.fixed_bearing")      # the package re-exports a function of that name
rbm = importlib.import_module("civilpy.structural.odot.rocker_bolster")
from civilpy.structural.rhino_bim import EmitObject, Point
from civilpy.structural.rhino_layers import LAYER_BEARINGS, LAYER_LOAD_PLATES
from civilpy.structural.rhino_scd_substructure import ScdEmit, SupportFrame, _doc, prism_volume_cy

IN = 1.0 / 12.0
STEEL_PCF = 490.0
KINDS = ("rocker", "bolster")
RB_SCD = "RB-1-55"
RB_REVISION = "07-19-2024"
BD_SCD = "BD-1-11"
BD_REVISION = "07-20-2018"


class _BearingFrame:
    """Layout (x along the beam, y across, z up) in inches -> feet on a SupportFrame."""

    def __init__(self, frame: SupportFrame):
        self.frame = frame

    def pt(self, x_in: float, y_in: float, z_in: float) -> Point:
        return self.frame.point(y_in * IN, x_in * IN, z_in * IN)

    def vec(self, dx_in: float, dy_in: float, dz_in: float = 0.0) -> Point:
        v = self.frame.vector(dy_in * IN, dx_in * IN, dz_in * IN)
        return (v[0], v[1], dz_in * IN)


def _rect(bf: _BearingFrame, half_x: float, half_y: float, z: float) -> tuple[Point, ...]:
    return (bf.pt(-half_x, -half_y, z), bf.pt(half_x, -half_y, z), bf.pt(half_x, half_y, z), bf.pt(-half_x, half_y, z))


def _frustum(bottom: tuple[Point, ...], top: tuple[Point, ...]) -> tuple[tuple[Point, ...], tuple[tuple[int, ...], ...]]:
    """Closed 8-vertex mesh between two 4-point loops (same winding)."""
    verts = tuple(bottom) + tuple(top)
    faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    return verts, faces


def _mesh_volume_cuft(verts, faces) -> float:
    """Volume of a closed mesh (divergence theorem on fan-triangulated faces)."""
    vol = 0.0
    for f in faces:
        for k in range(1, len(f) - 1):
            a, b, c = verts[f[0]], verts[f[k]], verts[f[k + 1]]
            vol += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                    + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return abs(vol) / 6.0


def _frame(alignment, station_ft, offset_ft, skew_deg, elevation_ft, side) -> _BearingFrame:
    return _BearingFrame(SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=skew_deg,
                                      elevation_ft=elevation_ft, side=side))


# ── RB-1-55 rocker / bolster ─────────────────────────────────────────────

def rocker_bolster_emit(capacity_kips: int, *, kind: str = "rocker", alignment=None, station_ft: float | None = None,
                        offset_ft: float = 0.0, skew_deg: float = 0.0, elevation_ft: float | None = None,
                        side: str = "near", bid: str | None = None, segments: int = 12) -> ScdEmit:
    """One RB-1-55 bearing of the tabulated ``capacity_kips`` line: the base
    plate, the tapered body (bolster: flat top; rocker: the curved top
    bearing surface of radius ``rocker_top_radius_in``)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    rb = rbm.rocker_bolster(capacity_kips)
    layout = rbm.layout_rocker_bolster(rb)
    bf = _frame(alignment, station_ft, offset_ft, skew_deg, elevation_ft, side)
    d = rb.dims
    T, C = layout.base_thickness_in, d["C"]
    B, L, A = d["B"], d["L"], d["A"]
    bid = bid or f"RB-{kind.upper()}-{capacity_kips}"
    fixity = "expansion" if kind == "rocker" else "fixed"
    weight = rb.weight_rocker_lb if kind == "rocker" else (rb.weight_bolster_lb or 0.0)
    tags = bim.bearing_tags(bid, fixity=fixity, kind=kind)
    tags.update({"bim.scd": RB_SCD, "bearing.capacity_kips": str(capacity_kips),
                 "bearing.no": rb.rocker_no if kind == "rocker" else rb.bolster_no,
                 "bearing.weight_lb": f"{weight:g}", "bearing.base_in": f"{B:g}x{L:g}x{T:g}",
                 "bearing.height_in": f"{layout.rocker_height_in if kind == 'rocker' else layout.bolster_height_in:g}"})
    objects: list[EmitObject] = []
    base = _rect(bf, B / 2.0, L / 2.0, 0.0)
    objects.append(EmitObject(kind="prism", layer=LAYER_BEARINGS, points=base, vector=(0.0, 0.0, T * IN),
                              tags={**tags, "bearing.part": "base plate"}))
    body_top_z = T + C
    bottom = _rect(bf, B / 2.0, L / 2.0, T)
    top = _rect(bf, A / 2.0, L / 2.0, body_top_z)
    verts, faces = _frustum(bottom, top)
    body_tags = {k: v for k, v in tags.items() if not k.startswith("pay.")}
    objects.append(EmitObject(kind="mesh", layer=LAYER_BEARINGS, points=verts, faces=faces,
                              tags={**body_tags, "bearing.part": "body"}))
    if kind == "rocker":
        r2 = layout.rocker_top_radius_in
        # half-disc profile in the x-z plane at y = -L/2, extruded across the bearing along y
        prof = [bf.pt(-r2, -L / 2.0, body_top_z)]
        for i in range(1, segments):
            a = math.pi - math.pi * i / segments
            prof.append(bf.pt(r2 * math.cos(a), -L / 2.0, body_top_z + r2 * math.sin(a)))
        prof.append(bf.pt(r2, -L / 2.0, body_top_z))
        objects.append(EmitObject(kind="prism", layer=LAYER_BEARINGS, points=tuple(prof), vector=bf.vec(0.0, L),
                                  tags={**body_tags, "bearing.part": "rocker top", "bearing.top_radius_in": f"{r2:g}"}))
    doc = _doc(RB_SCD, RB_REVISION, bf.frame, station_ft, skew_deg, offset_ft,
               {"rb.kind": kind, "rb.capacity_kips": str(capacity_kips)})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


# ── FB-1-82 fixed bearing ────────────────────────────────────────────────

def fixed_bearing_emit(designation: str, *, alignment=None, station_ft: float | None = None, offset_ft: float = 0.0,
                       skew_deg: float = 0.0, elevation_ft: float | None = None, side: str = "near",
                       top_plate_thickness_in: float = 1.0, bid: str | None = None) -> ScdEmit:
    """One FB-1-82 line (``"F-50"`` .. ``"F-400"``): masonry plate, pin
    across the beam, top plate.  The top plate thickness is not tabulated
    on the sheet; ``top_plate_thickness_in`` is a stated assumption."""
    if top_plate_thickness_in <= 0.0:
        raise ValueError("top_plate_thickness_in must be positive")
    fb = fbm.fixed_bearing(designation)
    layout = fbm.layout_fixed_bearing(fb)
    bf = _frame(alignment, station_ft, offset_ft, skew_deg, elevation_ft, side)
    d = fb.dims
    bid = bid or f"FB-{designation}"
    tags = bim.bearing_tags(bid, fixity="fixed", kind="fixed steel")
    tags.update({"bim.scd": fbm.SCD, "bearing.designation": designation, "bearing.max_load_lb": f"{fb.max_load_lb:g}",
                 "bearing.weight_lb": f"{fb.weight_lb:g}", "bearing.pin_dia_in": f"{layout.pin_diameter_in:g}",
                 "bearing.anchor_rods": "2" if fb.two_anchor_rods else "4", "bearing.stiffeners": str(fb.stiffeners_required).lower()})
    plain = {k: v for k, v in tags.items() if not k.startswith("pay.")}
    objects: list[EmitObject] = []
    base = _rect(bf, d["F"] / 2.0, d["G"] / 2.0, 0.0)
    objects.append(EmitObject(kind="prism", layer=LAYER_BEARINGS, points=base, vector=(0.0, 0.0, layout.base_thickness_in * IN),
                              tags={**tags, "bearing.part": "masonry plate"}))
    px, py, pz = layout.pin_center
    half_b = d["B"] / 2.0
    objects.append(EmitObject(kind="cylinder", layer=LAYER_BEARINGS,
                              points=(bf.pt(px, py - half_b, pz), bf.pt(px, py + half_b, pz)),
                              radius_ft=layout.pin_diameter_in / 2.0 * IN, tags={**plain, "bearing.part": "pin"}))
    top = _rect(bf, d["A"] / 2.0, d["B"] / 2.0, layout.top_z_in)
    objects.append(EmitObject(kind="prism", layer=LAYER_BEARINGS, points=top, vector=(0.0, 0.0, top_plate_thickness_in * IN),
                              tags={**plain, "bearing.part": "top plate",
                                    "bim.assumption": f"top plate {top_plate_thickness_in:g} in (not tabulated)"}))
    doc = _doc(fbm.SCD, fbm.REVISION, bf.frame, station_ft, skew_deg, offset_ft, {"fb.designation": designation})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


# ── BD-1-11 beveled load plate ───────────────────────────────────────────

def load_plate_emit(bearing_pad_name: str, *, longitudinal_grade: float = 0.0, alignment=None,
                    station_ft: float | None = None, offset_ft: float = 0.0, skew_deg: float = 0.0,
                    elevation_ft: float | None = None, side: str = "near", bid: str | None = None) -> ScdEmit:
    """The BD-1-11 beveled load plate over bearing pad ``"B1"`` / ``"B2"``:
    a closed mesh between the flat bottom face and the tilted top face,
    paid as ITEM 513 structural steel by weight."""
    layout = bb.layout_load_plate(bearing_pad_name, longitudinal_grade, skew_deg)
    bf = _frame(alignment, station_ft, offset_ft, skew_deg, elevation_ft, side)
    bottom = tuple(bf.pt(*p) for p in layout.bottom_face)
    top = tuple(bf.pt(*p) for p in layout.top_face)
    verts, faces = _frustum(bottom, top)
    weight = _mesh_volume_cuft(verts, faces) * STEEL_PCF
    bid = bid or f"BD-LP-{bearing_pad_name}"
    tags = bim.load_plate_tags(bid, thickness_in=layout.bevel_plate.min_thickness, weight_lb=round(weight, 2))
    tags.update({"bim.scd": BD_SCD, "load_plate.pad": bearing_pad_name, "load_plate.grade": f"{longitudinal_grade:g}",
                 "load_plate.skew_deg": f"{skew_deg:g}"})
    obj = EmitObject(kind="mesh", layer=LAYER_LOAD_PLATES, points=verts, faces=faces, tags=tags)
    doc = _doc(BD_SCD, BD_REVISION, bf.frame, station_ft, skew_deg, offset_ft,
               {"bd.pad": bearing_pad_name, "bd.weight_lb": f"{weight:.2f}"})
    return ScdEmit(layout=layout, objects=(obj,), doc_tags=doc)


__all__ = ["rocker_bolster_emit", "fixed_bearing_emit", "load_plate_emit", "KINDS", "prism_volume_cy"]
