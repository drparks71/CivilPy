#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrIM emit for the ODOT pipe headwall SCDs: HW-2.1 / HW-2.2 half-height
headwalls and HW-1.1 full-height headwalls with wingwalls.

The layouts (:mod:`civilpy.structural.odot.headwall`,
:mod:`~civilpy.structural.odot.full_height_headwall`) are in feet with
``x = 0`` on the culvert centreline, ``y = 0`` at the front face and
``z = 0`` at the flow line.  Here the culvert axis is placed along the
alignment's **normal** (a pipe crossing under the roadway): the frame's
``a`` axis carries the layout's ``x`` (along the wall) and ``b`` its
``y`` (along the pipe, toward higher stations), so a headwall at the
downstream toe of the embankment sits at ``station_ft`` / ``offset_ft``
with the wall face normal to the pipe.  Pass ``elevation_ft`` = the flow
line.

Concrete is paid under ITEM 511 (cy) with the sheets' own tabulated
quantities (``concrete_cy``), split over the solids by area share like
the box-culvert headwall emit; HW-1.1's tabulated reinforcing goes on a
schedule marker as ITEM 509 (lb).  The pipe opening is drawn as a
display cylinder (no boolean in the emit vocabulary).
"""

from __future__ import annotations

import importlib
import math

from civilpy.structural import bim
from civilpy.structural.rhino_bim import EmitObject
from civilpy.structural.rhino_layers import LAYER_CULVERT_REBAR, LAYER_CULVERT_WINGWALLS
from civilpy.structural.rhino_scd_substructure import (
    ScdEmit, SupportFrame, _doc, _newell, _wall_prism_placed, polygon_area,
)

hw = importlib.import_module("civilpy.structural.odot.headwall")
fhw = importlib.import_module("civilpy.structural.odot.full_height_headwall")

LAYER_HEADWALLS = "Culvert::Headwalls"
LAYER_PIPE = "Culvert::Pipe"


def _conc(bid: str, scd: str, cy: float, **dims) -> dict:
    tags = bim.substructure_concrete_tags("headwall", bid, fc_psi=4000.0, volume_cy=round(cy, 3), **dims)
    tags["bim.scd"] = scd
    return tags


def _frame(alignment, station_ft, offset_ft, elevation_ft, side):
    return SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=0.0, elevation_ft=elevation_ft, side=side)


# ── HW-2.1 / HW-2.2 half-height headwall ─────────────────────────────────

def headwall_emit(inp, *, alignment=None, station_ft: float | None = None, offset_ft: float = 0.0,
                  elevation_ft: float | None = None, side: str = "near", bid: str = "HW2", segments: int = 16) -> ScdEmit:
    """One HW-2.1 (CMP / plastic) or HW-2.2 (``concrete=True``) half-height
    headwall: the side profile swept across the wall width, plus the pipe
    as a display cylinder through it.  ``inp`` is a
    :class:`~civilpy.structural.odot.headwall.HeadwallInput`."""
    layout = hw.layout_headwall(inp)
    frame = _frame(alignment, station_ft, offset_ft, elevation_ft, side)
    scd = "HW-2.2" if inp.concrete else hw.SCD

    def place(p):
        return frame.point(p[0], p[1], p[2])

    W = layout.width_ft
    prof = tuple(place(p) for p in layout.side_profile)         # at x = -W/2
    vec = frame.vector(W, 0.0)
    objects = [EmitObject(kind="prism", layer=LAYER_HEADWALLS, points=prof, vector=vec,
                          tags=_conc(f"{bid}-WALL", scd, layout.concrete_cy, width_ft=W, height_ft=layout.height_ft,
                                     base_thickness_ft=layout.base_thickness_ft, top_thickness_ft=layout.top_thickness_ft,
                                     pipe_diameter_in=inp.diameter_in))]
    cx, cy, cz = layout.pipe_center
    t = layout.base_thickness_ft
    pipe = (place((cx, cy + t / 2.0, cz)), place((cx, cy - t / 2.0, cz)))
    objects.append(EmitObject(kind="cylinder", layer=LAYER_PIPE, points=pipe, radius_ft=layout.pipe_diameter_ft / 2.0,
                              tags={**bim._base("pipe_opening", f"{bid}-PIPE", scd=scd), "pipe.diameter_in": f"{inp.diameter_in:g}",
                                    "pipe.material": "concrete" if inp.concrete else "CMP / plastic", "bim.display_only": "true"}))
    doc = _doc(scd, hw.REVISION, frame, station_ft, 0.0, offset_ft,
               {"hw.diameter_in": f"{inp.diameter_in:g}", "hw.width_ft": f"{W:g}", "hw.height_ft": f"{layout.height_ft:g}",
                "hw.cover_in": f"{layout.cover_in:g}", "hw.concrete_cy": f"{layout.concrete_cy:g}"})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


# ── HW-1.1 full-height headwall ──────────────────────────────────────────

def full_height_headwall_emit(inp, *, alignment=None, station_ft: float | None = None, offset_ft: float = 0.0,
                              elevation_ft: float | None = None, side: str = "near", bid: str = "HW1",
                              rebar_marker: bool = True) -> ScdEmit:
    """One HW-1.1 full-height headwall: the centre face and both wingwalls
    as prisms of the tabulated thickness ``t_s``, the tabulated concrete
    split by face area, the tabulated reinforcing on a schedule marker.
    ``inp`` is a :class:`~civilpy.structural.odot.full_height_headwall.HeadwallInput`."""
    layout = fhw.layout_full_height_headwall(inp)
    frame = _frame(alignment, station_ft, offset_ft, elevation_ft, side)
    ts = layout.table.ts_ft

    def place(p):
        return frame.point(p[0], p[1], p[2])

    faces = [("FACE", tuple(place(p) for p in layout.center_face)),
             ("WW1", tuple(place(p) for p in layout.wing1)),
             ("WW2", tuple(place(p) for p in layout.wing2))]
    areas = [polygon_area(pts) for _, pts in faces]
    total = sum(areas) or 1.0
    objects = []
    for (label, pts), area in zip(faces, areas):
        pts2, vec = _wall_prism_placed(pts, ts)
        if label == "FACE":
            # the centre face's thickness goes into the fill (+y): flip if the normal points the other way
            nx, ny, _ = _newell(pts2)
            if (nx * frame.b[0] + ny * frame.b[1]) < 0:
                vec = (-vec[0], -vec[1], 0.0)
        share = layout.concrete_cy * area / total
        tags = _conc(f"{bid}-{label}", fhw.SCD, share, thickness_ft=ts, height_ft=layout.table.height_ft,
                     skew_bucket_deg=layout.skew_bucket_deg)
        tags["headwall.type"] = layout.type_
        objects.append(EmitObject(kind="prism", layer=LAYER_HEADWALLS if label == "FACE" else LAYER_CULVERT_WINGWALLS,
                                  points=pts2, vector=vec, tags=tags))
    # the pipe opening on the face, display only
    r = inp.diameter_in / 24.0
    circle = tuple(place((r * math.cos(2 * math.pi * k / 24), 0.0, r + r * math.sin(2 * math.pi * k / 24))) for k in range(24))
    objects.append(EmitObject(kind="polyline", layer=LAYER_PIPE, points=circle + (circle[0],),
                              tags={**bim._base("pipe_opening", f"{bid}-PIPE", scd=fhw.SCD), "pipe.diameter_in": f"{inp.diameter_in:g}",
                                    "bim.display_only": "true"}))
    if rebar_marker and layout.steel_lb:
        tags = bim.rebar_tags(f"{bid}-REBAR", size=layout.table.bar_size, coating="epoxy", mat="headwall", scd=fhw.SCD)
        tags.update({"pay.item": "509E00200", "pay.qty": f"{layout.steel_lb:g}", "pay.unit": "lb",
                     "rebar.schedule_marker": "true"})
        objects.append(EmitObject(kind="point", layer=LAYER_CULVERT_REBAR, points=(place((0.0, 0.0, layout.table.height_ft)),),
                                  tags=tags))
    doc = _doc(fhw.SCD, fhw.REVISION, frame, station_ft, inp.skew_deg, offset_ft,
               {"hw.diameter_in": f"{inp.diameter_in:g}", "hw.type": layout.type_, "hw.skew_bucket_deg": f"{layout.skew_bucket_deg:g}",
                "hw.concrete_cy": f"{layout.concrete_cy:g}", "hw.steel_lb": f"{layout.steel_lb:g}"})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


__all__ = ["headwall_emit", "full_height_headwall_emit", "LAYER_HEADWALLS", "LAYER_PIPE"]
