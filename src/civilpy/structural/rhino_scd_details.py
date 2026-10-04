#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrIM emit for the ODOT detail SCDs that are lines and pipe: EXJ-4-87 and
EXJ-5-93 strip seal expansion joints, VPF-1-24 vandal protection fencing.

Joints
    The gland centreline is a ``polyline`` across the deck at the joint
    station, skewed with the support line, carrying ITEM 516 strip seal
    (ft).  The EXJ-4-87 support angles (one run per stringer, the sheet's
    a1-a4 lengths) and the EXJ-5-93 beam-gap plate stations are display
    polylines with their dimensions in the tags - the hardware the sheet
    details (retainer angles, support channel, studs) is cataloged in the
    layouts' notes, not drawn.
Fence
    Line posts as cylinders (2.880 in OD pipe), top and bottom rails as
    cylinders (1.660 in OD) between the end posts, placed along the
    alignment at ``offset_ft`` (the deck edge / railing line).  The top
    rail carries ITEM 607 (ft).

The layouts (:mod:`civilpy.structural.odot.strip_seal_joint`,
:mod:`~civilpy.structural.odot.strip_seal_joint_box_beam`,
:mod:`~civilpy.structural.odot.vandal_fence`) are in feet, ``z = 0`` at
the top of deck; placement through
:class:`~civilpy.structural.rhino_scd_substructure.SupportFrame`.
"""

from __future__ import annotations

import importlib

from civilpy.structural import bim
from civilpy.structural.rhino_bim import EmitObject
from civilpy.structural.rhino_scd_substructure import ScdEmit, SupportFrame, _doc

ssj = importlib.import_module("civilpy.structural.odot.strip_seal_joint")
ssb = importlib.import_module("civilpy.structural.odot.strip_seal_joint_box_beam")
vpf = importlib.import_module("civilpy.structural.odot.vandal_fence")

LAYER_JOINTS = "Deck::Expansion Joints"
LAYER_FENCE = "Deck::Vandal Fence"
JOINT_PAY_ITEM = "516E13000"
FENCE_PAY_ITEM = "607E23000"
IN = 1.0 / 12.0


def _joint_tags(bid: str, scd: str, length_ft: float, **extra) -> dict:
    tags = {**bim._base("expansion_joint", bid, scd=scd), "joint.kind": "strip seal",
            "joint.length_ft": f"{length_ft:g}", **bim._pay_tags(JOINT_PAY_ITEM, round(length_ft, 3))}
    tags.update({f"joint.{k}": str(v) for k, v in extra.items()})
    return tags


def _length(p0, p1) -> float:
    return ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2 + (p1[2] - p0[2]) ** 2) ** 0.5


# ── EXJ-4-87 strip seal joint, steel stringers ───────────────────────────

def strip_seal_joint_emit(inp, *, alignment=None, station_ft: float | None = None, offset_ft: float = 0.0,
                          elevation_ft: float | None = None, side: str = "near", bid: str = "EXJ4") -> ScdEmit:
    """EXJ-4-87: the gland centreline across the deck plus one support-angle
    run per stringer station.  ``inp`` is a
    :class:`~civilpy.structural.odot.strip_seal_joint.StripSealJointInput`."""
    layout = ssj.layout_strip_seal_joint(inp)
    # the layout is in roadway axes (x along, y across) with the skew as its own shear:
    # the frame stays square and the gland's midpoint goes on the station
    frame = SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=0.0,
                         elevation_ft=elevation_ft, side=side)
    (jx0, jy0, _), (jx1, jy1, _) = layout.joint_line
    cx, cy = (jx0 + jx1) / 2.0, (jy0 + jy1) / 2.0

    def place(p):                   # layout x along the roadway, y across the deck from one edge
        return frame.point(p[1] - cy, p[0] - cx, p[2])

    objects = []
    line = tuple(place(p) for p in layout.joint_line)
    length = _length(*line)
    objects.append(EmitObject(kind="polyline", layer=LAYER_JOINTS, points=line,
                              tags=_joint_tags(f"{bid}-GLAND", ssj.SCD, length, skew_deg=inp.skew_deg,
                                               width_ft=inp.width_ft, stringers=len(layout.support_angles))))
    for i, run in enumerate(layout.support_angles, start=1):
        pts = tuple(place(p) for p in run.points)
        tags = {**bim._base("joint_support_angle", f"{bid}-SA-{i}", scd=ssj.SCD), "joint.station_ft": f"{run.station_ft:g}",
                "joint.a1_in": f"{run.a1_in:g}", "joint.a2_in": f"{run.a2_in:g}", "joint.a3_in": f"{run.a3_in:g}",
                "joint.a4_in": f"{run.a4_in:g}", "joint.display_only": "true"}
        objects.append(EmitObject(kind="polyline", layer=LAYER_JOINTS, points=pts, tags=tags))
    doc = _doc(ssj.SCD, ssj.REVISION, frame, station_ft, inp.skew_deg, offset_ft,
               {"exj.width_ft": f"{inp.width_ft:g}", "exj.length_ft": f"{length:.3f}",
                "exj.hardware": "; ".join(layout.notes)[:400]})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


# ── EXJ-5-93 strip seal joint, box beams ─────────────────────────────────

def box_beam_joint_emit(inp, *, alignment=None, station_ft: float | None = None, offset_ft: float = 0.0,
                        elevation_ft: float | None = None, side: str = "near", bid: str = "EXJ5") -> ScdEmit:
    """EXJ-5-93: the gland centreline over ``n_beams`` box beams plus a tick at
    every beam gap (plate "A"/"B"/"C" spacing in the tags).  ``inp`` is a
    :class:`~civilpy.structural.odot.strip_seal_joint_box_beam.BoxBeamJointInput`."""
    layout = ssb.layout_box_beam_joint(inp)
    frame = SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=0.0,
                         elevation_ft=elevation_ft, side=side)
    (jx0, jy0, _), (jx1, jy1, _) = layout.joint_line
    cx, cy = (jx0 + jx1) / 2.0, (jy0 + jy1) / 2.0

    def place(p):
        return frame.point(p[1] - cy, p[0] - cx, p[2])

    objects = []
    line = tuple(place(p) for p in layout.joint_line)
    sp = layout.spacing
    objects.append(EmitObject(kind="polyline", layer=LAYER_JOINTS, points=line,
                              tags=_joint_tags(f"{bid}-GLAND", ssb.SCD, layout.length_ft, skew_deg=inp.skew_deg,
                                               n_beams=inp.n_beams, beam_width_in=inp.beam_width_in,
                                               plate_a_in=sp.dim_a_in, plate_b_in=sp.dim_b_in, plate_c_in=sp.dim_c_in)))
    for i, s in enumerate(layout.beam_gap_stations_ft, start=1):
        tick = (place((0.0, s, 0.0)), place((0.0, s, -0.5)))
        objects.append(EmitObject(kind="polyline", layer=LAYER_JOINTS, points=tick,
                                  tags={**bim._base("joint_beam_gap", f"{bid}-GAP-{i}", scd=ssb.SCD),
                                        "joint.gap_station_ft": f"{s:g}", "joint.display_only": "true"}))
    doc = _doc(ssb.SCD, ssb.REVISION, frame, station_ft, inp.skew_deg, offset_ft,
               {"exj.n_beams": str(inp.n_beams), "exj.length_ft": f"{layout.length_ft:g}"})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


# ── VPF-1-24 vandal protection fence ─────────────────────────────────────

def vandal_fence_emit(inp, *, alignment=None, station_ft: float | None = None, offset_ft: float = 0.0,
                      elevation_ft: float | None = None, bid: str = "VPF") -> ScdEmit:
    """VPF-1-24: a fence run along the alignment from ``station_ft`` - posts
    as cylinders, the top and bottom rails between the end posts.  ``inp`` is
    a :class:`~civilpy.structural.odot.vandal_fence.FenceRunInput`."""
    layout = vpf.layout_fence_run(inp)
    frame = SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=0.0, elevation_ft=elevation_ft)
    sec = layout.section

    def place(p):                   # layout x along the fence (the alignment), y = 0, z up from the base plate
        return frame.point(p[1], p[0], p[2])

    objects = []
    r_post = vpf.LINE_POST_OD_IN / 2.0 * IN
    r_rail = vpf.RAIL_OD_IN / 2.0 * IN
    base = {**bim._base("vandal_fence", f"{bid}", scd=vpf.SCD), "fence.post_section": sec.name,
            "fence.base_plate": sec.base_plate, "fence.height_ft": f"{sec.height_ft:g}",
            "fence.post_spacing_ft": f"{(inp.spacing_ft or sec.max_spacing_ft):g}"}
    for i, s in enumerate(layout.post_stations_ft, start=1):
        objects.append(EmitObject(kind="cylinder", layer=LAYER_FENCE, points=(place((s, 0.0, 0.0)), place((s, 0.0, sec.height_ft))),
                                  radius_ft=r_post, tags={**base, "bim.id": f"{bid}-POST-{i}", "fence.part": "line post",
                                                         "fence.station_ft": f"{s:g}"}))
    top = tuple(place(p) for p in layout.top_rail)
    bottom = tuple(place(p) for p in layout.bottom_rail)
    objects.append(EmitObject(kind="cylinder", layer=LAYER_FENCE, points=top, radius_ft=r_rail,
                              tags={**base, "bim.id": f"{bid}-TOP", "fence.part": "top rail",
                                    **bim._pay_tags(FENCE_PAY_ITEM, round(inp.length_ft, 3))}))
    objects.append(EmitObject(kind="cylinder", layer=LAYER_FENCE, points=bottom, radius_ft=r_rail,
                              tags={**base, "bim.id": f"{bid}-BOT", "fence.part": "bottom rail"}))
    doc = _doc(vpf.SCD, vpf.REVISION, frame, station_ft, 0.0, offset_ft,
               {"vpf.length_ft": f"{inp.length_ft:g}", "vpf.posts": str(len(layout.post_stations_ft)),
                "vpf.pay_item": " ".join(vpf.PAY_ITEM)})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


__all__ = ["strip_seal_joint_emit", "box_beam_joint_emit", "vandal_fence_emit", "LAYER_JOINTS", "LAYER_FENCE"]
