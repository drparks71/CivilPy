#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrIM emit for the ODOT substructure SCDs: CPA-1-08 capped pile abutment,
CPP-1-08 capped pile pier, A-1-20 typical abutment.

The layouts (:mod:`civilpy.structural.odot.capped_pile_abutment`,
:mod:`~civilpy.structural.odot.capped_pile_pier`,
:mod:`~civilpy.structural.odot.typical_abutment`) carry the sheet's
geometry in a local frame; this module places that frame on a support line
and turns it into tagged, transport-neutral
:class:`~civilpy.structural.rhino_bim.EmitObject` records - the same
vocabulary the approach slab, box beams and headwalls emit - so the units
bake to ``.3dm`` / IFC and roll up through ``pay_item_quantities`` like
every other civilpy component.  It replaces the deleted Grasshopper
prototypes (``Notebooks/Rhino Components/CPA-1-08.py`` ...), whose TODO
blocks asked for exactly this: skew honoured, wingwalls as solids, near /
far handling and alignment placement, user-text tags.

Support-line placement
----------------------
:class:`SupportFrame` maps the layout's local axes onto a support line:

``alignment`` + ``station_ft``
    The support line crosses the roadway alignment at ``station_ft``.
    With no alignment the frame sits on a due-north tangent through the
    origin (the :class:`~civilpy.transportation.alignment.Alignment`
    default), stations along +Y, transverse along +X.
``skew_deg``
    The support line is the alignment normal rotated by the skew (the
    convention of the layouts' own ``x + y tan(skew)`` shear, so the same
    number is given to the layout and to the frame: cap ends come out
    parallel to the roadway).
``offset_ft``
    Transverse offset of the unit's centre from the alignment, right
    positive.
``elevation_ft``
    Elevation of the layout's ``z = 0`` (the bridge seat / top of cap).
    Default: the alignment's profile elevation at the station, else 0.
``side``
    ``"near"`` keeps the layout's +y toward higher stations (the wingwall
    of CPA-1-08 / A-1-20 flares away from the bridge at the far-station
    end of the cap); ``"far"`` rotates 180 degrees in plan.

Quantities come from the geometry: concrete (ITEM 511, ``cy``) from each
prism's volume, piles (ITEM 507, ``ft``) from the pile length given (the
sheets leave it to the project).  Wingwall thickness is not on any of the
three sheets; ``wingwall_thickness_ft`` (default 1.5) is a stated
assumption carried in the tags.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from civilpy.structural import bim
from civilpy.structural.odot import capped_pile_abutment as cpa
from civilpy.structural.odot import capped_pile_pier as cpp
from civilpy.structural.odot import typical_abutment as a120
from civilpy.structural.rhino_bim import EmitObject, Point
from civilpy.structural.rhino_layers import (
    LAYER_SUB_BACKWALLS,
    LAYER_SUB_CAPS,
    LAYER_SUB_FOOTINGS,
    LAYER_SUB_PILES,
    LAYER_SUB_WINGWALLS,
)

SIDES = ("near", "far")
DEFAULT_PILE_LENGTH_FT = 40.0
DEFAULT_WINGWALL_THICKNESS_FT = 1.5
HP12X53_WIDTH_FT = 12.0 / 12.0       # drawn as a round of the flange width
PILE_SHAPE = "HP12X53"


@dataclass(frozen=True)
class ScdEmit:
    """One placed SCD unit - duck-compatible with ``emit_to_json`` /
    ``emit_to_3dm`` / ``pay_item_quantities``."""

    layout: object
    objects: tuple[EmitObject, ...]
    doc_tags: dict[str, str] = field(default_factory=dict)


class SupportFrame:
    """Local (a, b, z) -> global: ``a`` along the support line (right
    positive), ``b`` normal to it toward higher stations, ``z`` up from
    ``elevation_ft``."""

    def __init__(self, alignment=None, station_ft: float | None = None, *,
                 offset_ft: float = 0.0, skew_deg: float = 0.0,
                 elevation_ft: float | None = None, side: str = "near"):
        if side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}, not {side!r}")
        if alignment is not None and station_ft is None:
            raise ValueError("placing on an alignment requires station_ft")
        if alignment is None:
            origin = (0.0, 0.0, 0.0)
            t, r = (0.0, 1.0), (1.0, 0.0)
            z0 = 0.0 if elevation_ft is None else elevation_ft
        else:
            f = alignment.frame_at(station_ft)
            origin = f["point"]
            t, r = f["tangent"], f["right"]
            if elevation_ft is None:
                prof = getattr(alignment, "profile", None)
                z0 = float(prof.elevation_at(station_ft)) if prof is not None else 0.0
            else:
                z0 = elevation_ft
        # rotate the normal/right pair about z by the skew
        th = math.radians(skew_deg)
        c, s = math.cos(th), math.sin(th)
        # a-axis: right rotated toward "back" for positive skew (azimuth = bearing + 90 + skew)
        self.a = (r[0] * c - t[0] * s, r[1] * c - t[1] * s)
        self.b = (t[0] * c + r[0] * s, t[1] * c + r[1] * s)
        self.sgn = 1.0 if side == "near" else -1.0
        self.origin = (origin[0] + r[0] * offset_ft, origin[1] + r[1] * offset_ft, z0)
        self.side = side

    def point(self, a: float, b: float, z: float) -> Point:
        a, b = self.sgn * a, self.sgn * b
        return (self.origin[0] + a * self.a[0] + b * self.b[0],
                self.origin[1] + a * self.a[1] + b * self.b[1],
                self.origin[2] + z)

    def vector(self, da: float, db: float, dz: float = 0.0) -> Point:
        da, db = self.sgn * da, self.sgn * db
        return (da * self.a[0] + db * self.b[0], da * self.a[1] + db * self.b[1], dz)


# ── geometry helpers ─────────────────────────────────────────────────────

def _newell(points) -> tuple[float, float, float]:
    nx = ny = nz = 0.0
    n = len(points)
    for i in range(n):
        x0, y0, z0 = points[i]
        x1, y1, z1 = points[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx / 2.0, ny / 2.0, nz / 2.0


def polygon_area(points) -> float:
    """Area of a planar polygon in 3D (Newell's method)."""
    nx, ny, nz = _newell(points)
    return math.sqrt(nx * nx + ny * ny + nz * nz)


def prism_volume_cy(points, vector) -> float:
    """Volume (cy) of a prism: base polygon area x the extrusion's component along the base normal."""
    nx, ny, nz = _newell(points)
    area = math.sqrt(nx * nx + ny * ny + nz * nz)
    if area < 1e-12:
        return 0.0
    height = abs(nx * vector[0] + ny * vector[1] + nz * vector[2]) / area
    return area * height / 27.0


def _wall_prism(frame: SupportFrame, quad, thickness_ft: float) -> tuple[tuple[Point, ...], Point]:
    """A vertical wall quad (local coords) as a prism: the quad placed, plus
    the thickness vector along its horizontal normal."""
    return _wall_prism_placed(tuple(frame.point(*p) for p in quad), thickness_ft)


def _pile(frame: SupportFrame, p, length_ft: float, bid: str, scd: str) -> EmitObject:
    top = frame.point(*p)
    tip = (top[0], top[1], top[2] - length_ft)
    tags = bim.pile_tags(bid, shape=PILE_SHAPE, length_ft=length_ft)
    tags["bim.scd"] = scd
    return EmitObject(kind="cylinder", layer=LAYER_SUB_PILES, points=(top, tip),
                      radius_ft=HP12X53_WIDTH_FT / 2.0, tags=tags)


def _conc(btype: str, bid: str, scd: str, volume_cy: float, fc_psi: float, **dims) -> dict:
    tags = bim.substructure_concrete_tags(btype, bid, fc_psi=fc_psi, volume_cy=round(volume_cy, 3), **dims)
    tags["bim.scd"] = scd
    return tags


def _doc(scd: str, revision: str, frame: SupportFrame, station_ft, skew_deg, offset_ft, extra: dict) -> dict:
    d = {"bim.scd": scd, "bim.scd_rev": revision, "bim.units": "ft", "scd.side": frame.side,
         "scd.skew_deg": f"{skew_deg:g}", "scd.offset_ft": f"{offset_ft:g}",
         "scd.elevation_ft": f"{frame.origin[2]:g}"}
    if station_ft is not None:
        d["scd.station_ft"] = f"{station_ft:g}"
    d.update(extra)
    return d


# ── CPA-1-08 capped pile abutment ────────────────────────────────────────

def capped_pile_abutment_emit(inp: cpa.AbutmentInput, *, alignment=None, station_ft: float | None = None,
                              offset_ft: float = 0.0, elevation_ft: float | None = None, side: str = "near",
                              pile_length_ft: float = DEFAULT_PILE_LENGTH_FT,
                              wingwall_thickness_ft: float = DEFAULT_WINGWALL_THICKNESS_FT,
                              both_wingwalls: bool = True, bid: str = "CPA") -> ScdEmit:
    """CPA-1-08: the cap (down from the seat by the footing depth), the
    HP12x53 piles below it, and the flared wingwall(s) as solids.  The sheet
    draws one wingwall; ``both_wingwalls`` mirrors it to the other end."""
    if pile_length_ft <= 0.0 or wingwall_thickness_ft <= 0.0:
        raise ValueError("pile_length_ft and wingwall_thickness_ft must be positive")
    layout = cpa.layout_capped_pile_abutment(inp)
    frame = SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=inp.skew_deg,
                         elevation_ft=elevation_ft, side=side)
    fc = cpa_fc_psi()
    objects: list[EmitObject] = []
    cap_pts = tuple(frame.point(*p) for p in layout.cap_outline)
    cap_vec = (0.0, 0.0, -inp.footing_depth_ft)
    cap_len = (inp.n_piles - 1) * inp.pile_spacing_ft + 2.0 * cpa.CAP_HALF_ZONE_FT
    objects.append(EmitObject(kind="prism", layer=LAYER_SUB_CAPS, points=cap_pts, vector=cap_vec,
                              tags=_conc("abutment_cap", f"{bid}-CAP", cpa.SCD, prism_volume_cy(cap_pts, cap_vec), fc,
                                         length_ft=round(cap_len, 3), width_ft=inp.cap_width_ft,
                                         depth_ft=inp.footing_depth_ft, skew_deg=inp.skew_deg)))
    for i, p in enumerate(layout.pile_points, start=1):
        objects.append(_pile(frame, p, pile_length_ft, f"{bid}-PILE-{i}", cpa.SCD))
    wings = [("WW1", layout.wingwall_outline)]
    if both_wingwalls:
        wings.append(("WW2", tuple((-x, y, z) for x, y, z in layout.wingwall_outline)))
    for label, quad in wings:
        pts, vec = _wall_prism(frame, quad, wingwall_thickness_ft)
        tags = _conc("wingwall", f"{bid}-{label}", cpa.SCD, prism_volume_cy(pts, vec), fc,
                     length_ft=inp.wingwall_length_ft, thickness_ft=wingwall_thickness_ft)
        tags["bim.assumption"] = f"wingwall thickness {wingwall_thickness_ft:g} ft (not on the sheet)"
        objects.append(EmitObject(kind="prism", layer=LAYER_SUB_WINGWALLS, points=pts, vector=vec, tags=tags))
    doc = _doc(cpa.SCD, cpa.REVISION, frame, station_ft, inp.skew_deg, offset_ft,
               {"cpa.n_piles": str(inp.n_piles), "cpa.pile_spacing_ft": f"{inp.pile_spacing_ft:g}",
                "cpa.cap_length_ft": f"{cap_len:g}", "cpa.pile_length_ft": f"{pile_length_ft:g}"})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


def cpa_fc_psi() -> float:
    """CPA-1-08 class QC1 concrete, 4,000 psi (BDM 304.2 / the sheet's design data)."""
    return 4000.0


# ── CPP-1-08 capped pile pier ────────────────────────────────────────────

def capped_pile_pier_emit(inp: cpp.PierInput, *, alignment=None, station_ft: float | None = None,
                          offset_ft: float = 0.0, elevation_ft: float | None = None, side: str = "near",
                          pile_length_ft: float = DEFAULT_PILE_LENGTH_FT, bid: str = "CPP") -> ScdEmit:
    """CPP-1-08: the rounded-end cap (top at the seat elevation, ``cap_depth_ft``
    deep) centred on the alignment, and the HP12x53 piles below it."""
    if pile_length_ft <= 0.0:
        raise ValueError("pile_length_ft must be positive")
    layout = cpp.layout_capped_pile_pier(inp)
    frame = SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=inp.skew_deg,
                         elevation_ft=elevation_ft, side=side)
    # the layout runs from the near-end arc centre; centre it on the pier
    shift = (layout.length_ft - 2.0 * cpp.CAP_END_RADIUS_FT) / 2.0
    objects: list[EmitObject] = []
    cap_pts = tuple(frame.point(x - shift, y, z) for x, y, z in layout.cap_outline)
    cap_vec = (0.0, 0.0, -inp.cap_depth_ft)
    objects.append(EmitObject(kind="prism", layer=LAYER_SUB_CAPS, points=cap_pts, vector=cap_vec,
                              tags=_conc("pier_cap", f"{bid}-CAP", cpp.SCD, prism_volume_cy(cap_pts, cap_vec),
                                         cpp.CONCRETE_STRENGTH_KSI * 1000.0, length_ft=round(layout.length_ft, 3),
                                         width_ft=cpp.CAP_WIDTH_FT, depth_ft=inp.cap_depth_ft, skew_deg=inp.skew_deg)))
    for i, (x, y, z) in enumerate(layout.pile_points, start=1):
        objects.append(_pile(frame, (x - shift, y, z), pile_length_ft, f"{bid}-PILE-{i}", cpp.SCD))
    doc = _doc(cpp.SCD, cpp.REVISION, frame, station_ft, inp.skew_deg, offset_ft,
               {"cpp.n_piles": str(inp.n_piles), "cpp.pile_spacing_ft": f"{inp.pile_spacing_ft:g}",
                "cpp.length_ft": f"{layout.length_ft:g}", "cpp.pile_length_ft": f"{pile_length_ft:g}"})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


# ── A-1-20 typical abutment ──────────────────────────────────────────────

def typical_abutment_emit(inp: a120.AbutmentInput, *, alignment=None, station_ft: float | None = None,
                          offset_ft: float = 0.0, elevation_ft: float | None = None, side: str = "near",
                          wingwall_thickness_ft: float = DEFAULT_WINGWALL_THICKNESS_FT,
                          both_wingwalls: bool = True, bid: str = "ABT") -> ScdEmit:
    """A-1-20 (guidance): the backwall up from the seat, the footing below
    it, and the flared wingwall(s).  The layout runs along its local y from
    0 to the width; it is centred here.  The deleted prototype extruded the
    footing from ``-depth`` a further ``depth`` down; the footing is drawn
    from ``-depth`` up to the seat instead."""
    if wingwall_thickness_ft <= 0.0:
        raise ValueError("wingwall_thickness_ft must be positive")
    layout = a120.layout_typical_abutment(inp)
    frame = SupportFrame(alignment, station_ft, offset_ft=offset_ft, skew_deg=inp.skew_deg,
                         elevation_ft=elevation_ft, side=side)
    half_w = inp.width_ft / 2.0

    def place(p):            # layout x is across the backwall, y along it: swap into (a, b)
        x, y, z = p
        return frame.point(y - half_w, x, z)

    fc = a120.CONCRETE_STRENGTH_KSI * 1000.0
    objects: list[EmitObject] = []
    bw = tuple(place(p) for p in layout.backwall_outline)
    bw_vec = (0.0, 0.0, inp.backwall_height_ft)
    objects.append(EmitObject(kind="prism", layer=LAYER_SUB_BACKWALLS, points=bw, vector=bw_vec,
                              tags=_conc("backwall", f"{bid}-BW", a120.SCD, prism_volume_cy(bw, bw_vec), fc,
                                         height_ft=inp.backwall_height_ft, width_ft=inp.width_ft,
                                         thickness_ft=round(a120.BACKWALL_TOP_WIDTH_FT, 3), skew_deg=inp.skew_deg)))
    ftg = tuple(place(p) for p in layout.footing_outline)
    ftg_vec = (0.0, 0.0, inp.footing_depth_ft)
    objects.append(EmitObject(kind="prism", layer=LAYER_SUB_FOOTINGS, points=ftg, vector=ftg_vec,
                              tags=_conc("footing", f"{bid}-FTG", a120.SCD, prism_volume_cy(ftg, ftg_vec), fc,
                                         depth_ft=inp.footing_depth_ft, width_ft=inp.width_ft)))
    wings = [("WW1", layout.wingwall_outline)]
    if both_wingwalls:
        # mirror about the backwall's mid-width (local y = W/2) and flip x
        wings.append(("WW2", tuple((-x, inp.width_ft - y, z) for x, y, z in layout.wingwall_outline)))
    for label, quad in wings:
        pts, vec = _wall_prism_placed(tuple(place(p) for p in quad), wingwall_thickness_ft)
        tags = _conc("wingwall", f"{bid}-{label}", a120.SCD, prism_volume_cy(pts, vec), fc,
                     length_ft=inp.wingwall_length_ft, thickness_ft=wingwall_thickness_ft)
        tags["bim.assumption"] = f"wingwall thickness {wingwall_thickness_ft:g} ft (not on the sheet)"
        objects.append(EmitObject(kind="prism", layer=LAYER_SUB_WINGWALLS, points=pts, vector=vec, tags=tags))
    doc = _doc(a120.SCD, a120.REVISION, frame, station_ft, inp.skew_deg, offset_ft,
               {"abt.width_ft": f"{inp.width_ft:g}", "abt.backwall_height_ft": f"{inp.backwall_height_ft:g}",
                "abt.dim_a_ft": f"{layout.dim_a_ft:g}", "abt.guidance_only": "true"})
    return ScdEmit(layout=layout, objects=tuple(objects), doc_tags=doc)


def _wall_prism_placed(pts: tuple[Point, ...], thickness_ft: float) -> tuple[tuple[Point, ...], Point]:
    nx, ny, nz = _newell(pts)
    h = math.hypot(nx, ny)
    if h < 1e-12:
        raise ValueError("wingwall quad is not vertical")
    return pts, (thickness_ft * nx / h, thickness_ft * ny / h, 0.0)
