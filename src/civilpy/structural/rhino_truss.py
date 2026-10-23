#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""BrIM emit for a riveted steel truss -- the source-of-truth 3-D model.

:mod:`civilpy.structural.rhino_bim` does this for the parametric plate-girder
bridge; this is its twin for the trusses that make up most of the old long
spans, where there is no parametric layout to generate from -- the geometry
comes off the erection and member sheets, panel point by panel point.

The model is *as-built*, not schematic.  A truss member of the riveted era
is a bundle of flat plates and angles, and at LOD 400 that is exactly what
is drawn: :mod:`civilpy.structural.builtup` decomposes the plan-sheet
shorthand (``"2P24x9/16 4L6x4x3/8"``) into its web plates, its four corner
angles and its cover plates, and each becomes its own solid on the member's
axis.  At LOD 300 the member collapses to the single box that envelopes it,
which is what a whole-bridge file wants.  Gusset plates are real plates:
the outline traced off the failure-plane sheets, extruded at the measured
thickness, sitting on the faces of the member webs at the joint -- with
their rating write-back on board, so a viewer can pick any plate in the
bridge and read what governs it.

Everything is stamped with :mod:`civilpy.structural.bim` tags
(``bim.type``/``bim.id``, a ``pay.*`` block, a ``mat.*`` block carrying the
MBE historic-steel yield and tensile), so the same file drives the model
tree, the quantity takeoff and the estimator hand-off that the girder
pipeline already feeds.

Coordinates are **feet** (the hub convention): X along the bridge, Y
transverse, Z elevation.  Section dimensions in the tags stay in inches.

Member orientation
------------------
A truss member's webs are parallel to the plane of its truss, so the
section's local axes follow from the member axis and the truss plane
normal:

* local **u** -- along the member, node i to node j
* local **y** -- across the width (web to web), the truss plane normal,
  i.e. bridge-transverse for a truss in a vertical plane
* local **z** -- through the depth, in the truss plane, perpendicular to
  the member

which is the same y/z that :mod:`civilpy.structural.builtup` uses, so a
section rectangle maps straight onto the member with no extra convention.

Backends
--------
:func:`truss_emit` returns the same neutral ``EmitObject`` records
``rhino_bim`` uses, so both of its backends work unchanged:
:func:`~civilpy.structural.rhino_bim.objects_to_3dm` bakes a ``.3dm`` with
standalone ``rhino3dm`` (use ``mesh=True`` for a file the web viewer can
shade), and the live-document driver consumes the same JSON.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from civilpy.structural import bim, builtup, laced_member
from civilpy.structural.rhino_bim import EmitObject
from civilpy.structural.rhino_layers import (
    LAYER_FLOOR_BEAMS,
    LAYER_GUSSET_PLATES,
    LAYER_LATERAL_BRACING,
    LAYER_PANEL_POINTS,
    LAYER_REVIEW_FINDINGS,
    LAYER_REVIEW_REPAIRS,
    LAYER_RIVETS,
    LAYER_STRINGERS,
    LAYER_SWAY_BRACING,
    LAYER_TRUSS_CHORDS,
    LAYER_TRUSS_DIAGONALS,
    LAYER_TRUSS_END_POSTS,
    LAYER_TRUSS_STRUTS,
    LAYER_TRUSS_PINS,
    LAYER_TRUSS_VERTICALS,
)

Point3 = tuple

#: ``bim.type`` -> layer for every object this module emits.
TYPE_LAYER = {
    "truss_chord_top": LAYER_TRUSS_CHORDS,
    "truss_chord_bottom": LAYER_TRUSS_CHORDS,
    "truss_vertical": LAYER_TRUSS_VERTICALS,
    "truss_diagonal": LAYER_TRUSS_DIAGONALS,
    "truss_end_post": LAYER_TRUSS_END_POSTS,
    "truss_strut": LAYER_TRUSS_STRUTS,
    "gusset_plate": LAYER_GUSSET_PLATES,
    "floor_beam": LAYER_FLOOR_BEAMS,
    "stringer": LAYER_STRINGERS,
    "lateral_brace": LAYER_LATERAL_BRACING,
    "sway_brace": LAYER_SWAY_BRACING,
    "portal_brace": LAYER_SWAY_BRACING,
    "panel_point": LAYER_PANEL_POINTS,
    "rivet": LAYER_RIVETS,
    "repair": LAYER_REVIEW_REPAIRS,
    "finding": LAYER_REVIEW_FINDINGS,
}


# --------------------------------------------------------------------------- #
# vector helpers (feet)
# --------------------------------------------------------------------------- #
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _norm(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _unit(a):
    n = _norm(a)
    if n < 1e-12:
        raise ValueError("zero-length vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TrussNode:
    """A panel point (or any other work point) in bridge coordinates, feet."""
    id: str
    point: Point3
    line: str = ""            # truss line, e.g. "OS" / "IS" / "IN" / "ON"
    span: str = ""
    chord: str = ""           # "U" upper, "L" lower, "M" intermediate, "P" pier
    pp: int = 0               # panel-point index along the span
    joint: str = ""           # the rating joint id this work point carries


@dataclass(frozen=True)
class TrussMember:
    """One truss member between two nodes, described by its plan-sheet spec.

    ``normal`` is the truss plane normal (the direction the section's width
    runs); it defaults to bridge-transverse, which is right for a truss in a
    vertical plane."""
    id: str
    i: str
    j: str
    spec: str
    role: str = "truss_chord_top"
    line: str = ""
    span: str = ""
    normal: Point3 = (0.0, 1.0, 0.0)
    steel: str = "silicon 1917-1936"
    #: The fabrication the plan-sheet spec does not carry -- lacing and tie
    #: plates, read off the shop sheets.  With it the member emits at LOD 400
    #: as its real pieces; without it only the bare section can be drawn.
    fabrication: object = None


@dataclass(frozen=True)
class FramingMember:
    """A floor beam, stringer or bracing member, described as an I: overall
    depth and flange width with the web and flange thicknesses.

    Carrying the plate thicknesses rather than a fill fraction matters more
    than it looks -- a 55 in deep floor beam is about 48 in^2 of steel, and
    guessing it as a fraction of its 55 x 14 in envelope overstates the floor
    system several times over, which on a truss bridge is a large share of
    the dead load."""
    id: str
    i: str
    j: str
    section: str
    role: str = "floor_beam"
    depth_in: float = 18.0
    width_in: float = 8.0
    web_t_in: float = 0.375
    flange_t_in: float = 0.5
    level: str = ""
    span: str = ""
    normal: Point3 = (0.0, 0.0, 1.0)

    @property
    def area_in2(self) -> float:
        """Cross-sectional area of the I (in^2)."""
        web = self.web_t_in * max(self.depth_in - 2 * self.flange_t_in, 0.0)
        return web + 2 * self.width_in * self.flange_t_in

    def rects(self):
        """``(b_y, h_z, y_c, z_c)`` per plate, the way
        :func:`civilpy.structural.builtup.rects` reports a truss member."""
        d, b = self.depth_in, self.width_in
        tw, tf = self.web_t_in, self.flange_t_in
        out = [(tw, max(d - 2 * tf, 0.0), 0.0, 0.0)]
        for sz in (-1, 1):
            out.append((b, tf, 0.0, sz * (d / 2 - tf / 2)))
        return out


@dataclass(frozen=True)
class GussetPlacement:
    """One gusset plate positioned at a joint.

    ``outline`` is the plate polygon in the drawing's own 2-D plate
    coordinates (inches, x right / y up, the convention
    :mod:`civilpy.structural.gusset_geometry` uses) and ``work_point`` the
    point in those coordinates that sits on ``node``.  ``plane_x`` is the
    direction the plate's local +x runs in bridge coordinates (default: along
    +X) and ``normal`` the plate normal; ``offset_in`` slides the plate along
    its normal to the face of the member webs it is riveted to."""
    id: str
    node: str
    outline: tuple
    work_point: tuple
    thickness_in: float = 0.625
    joint: str = ""
    face: str = "outside"
    offset_in: float = 9.0
    plane_x: Point3 = (1.0, 0.0, 0.0)
    normal: Point3 = (0.0, 1.0, 0.0)
    members: str = ""
    rivets: tuple = ()          # (x, y) in plate coordinates, inches
    rivet_diameter_in: float = 1.0
    t_remaining_in: float = None
    rating_rf: float = None
    governing: str = ""
    steel: str = "silicon 1917-1936"


@dataclass(frozen=True)
class PinPlacement:
    """A pin at a joint: the shared :class:`civilpy.structural.aashto.lrfd.
    pins.Pin` (diameter, Fy, packing positions along its axis, inches from
    the work point) and the direction its axis runs in bridge coordinates
    (default transverse).  ``rating_rf`` / ``governing`` carry the write-back
    of :func:`~civilpy.structural.aashto.lrfd.pins.pin_checks`."""
    id: str
    node: str
    pin: object
    axis: Point3 = (0.0, 1.0, 0.0)
    joint: str = ""
    projection_in: float = 1.0
    rating_rf: float = None
    governing: str = ""


@dataclass(frozen=True)
class ReviewItem:
    """A proposed repair, or a past inspection finding, located on an element.

    This is what turns the model into a *review* model.  A repair set and an
    inspection history are normally prose plus a sheet number, and answering
    "where on the bridge is this, and what else is happening there?" means
    holding the whole structure in your head.  Attached to the element the
    question becomes a click.

    ``kind`` is ``"repair"`` or ``"finding"``; ``target`` the ``bim.id`` of
    the member, plate or node it applies to; ``tags`` the
    :func:`~civilpy.structural.bim.repair_tags` /
    :func:`~civilpy.structural.bim.finding_tags` block.
    """
    id: str
    kind: str
    target: str
    tags: dict = field(default_factory=dict)


@dataclass
class TrussModel:
    """A whole truss bridge: work points, members, framing and gusset plates."""
    name: str
    nodes: dict = field(default_factory=dict)
    members: list = field(default_factory=list)
    framing: list = field(default_factory=list)
    gussets: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    doc_tags: dict = field(default_factory=dict)
    pins: list = field(default_factory=list)

    def node(self, nid: str) -> TrussNode:
        return self.nodes[nid]

    def add_node(self, node: TrussNode) -> TrussNode:
        self.nodes[node.id] = node
        return node

    def length_ft(self, m) -> float:
        return _norm(_sub(self.nodes[m.j].point, self.nodes[m.i].point))

    def bbox(self):
        pts = [n.point for n in self.nodes.values()]
        return (tuple(min(p[k] for p in pts) for k in range(3)),
                tuple(max(p[k] for p in pts) for k in range(3)))

    def to_structural_model(self, *, joints: str = "rigid",
                            include_framing: bool = True,
                            e_ksi: float = 29000.0, supports=None):
        """This as-built model as a :class:`~civilpy.structural.
        structural_model.StructuralModel` hub (kips / ft), so the same
        members the BrIM emit draws are what
        :mod:`civilpy.structural.frame_analysis` solves and
        :func:`civilpy.structural.midas_models.midas_payloads` exports.

        Truss members get their exact plan-sheet properties from
        :func:`civilpy.structural.builtup.properties` (``Iy`` in-plane,
        width along the member's ``normal``, so the element beta comes from
        the normal); framing members from their web and flange plates.
        ``joints="pinned"`` makes the truss members axial-only.  Steel
        density gives self weight in a ``"self weight"`` case.  ``supports``
        is ``{node_id: preset or fix-flag dict}`` (hub
        :meth:`~StructuralModel.add_restraint` arguments); without it the
        model carries no restraints."""
        from civilpy.structural.frame_analysis import beta_for_normal
        from civilpy.structural.structural_model import (
            MaterialProperties, SectionProperties, StructuralModel, Units)

        if joints not in ("pinned", "rigid"):
            raise ValueError("joints must be 'pinned' or 'rigid'")
        hub = StructuralModel(units=Units(force="kips", length="ft"))
        hub.material_properties["steel"] = MaterialProperties(
            e=e_ksi * 144.0, poisson=0.3, density=builtup.STEEL_PCF / 1000.0)
        for n in self.nodes.values():
            hub.add_node(*n.point, label=n.id, id=n.id)

        def props(label, p):
            if label not in hub.section_properties:
                hub.section_properties[label] = SectionProperties(
                    area=p["A"] / 144.0, iy=p["Iy"] / 12 ** 4,
                    iz=p["Iz"] / 12 ** 4, j=p["J"] / 12 ** 4,
                    asy=p.get("ASy", 0.0) / 144.0, asz=p.get("ASz", 0.0) / 144.0,
                    depth=p["H"] / 12.0, width=p["B"] / 12.0)
            return label

        for m in self.members:
            pi, pj = self.nodes[m.i].point, self.nodes[m.j].point
            e = hub.add_element(m.i, m.j, id=m.id, role=m.role,
                                midas_type="TRUSS" if joints == "pinned" else "BEAM",
                                section=props(m.spec, builtup.properties(m.spec)),
                                material="steel",
                                beta_deg=beta_for_normal(pi, pj, m.normal))
            e.metadata.update({"truss.line": m.line, "truss.span": m.span,
                               "truss.spec": m.spec})
        if include_framing:
            for f in self.framing:
                pi, pj = self.nodes[f.i].point, self.nodes[f.j].point
                e = hub.add_element(f.i, f.j, id=f.id, role=f.role,
                                    midas_type="BEAM",
                                    section=props(f.section, builtup.rect_properties(f.rects())),
                                    material="steel",
                                    beta_deg=beta_for_normal(pi, pj, f.normal))
                e.metadata.update({"truss.level": f.level, "truss.span": f.span})
        for nid, spec in (supports or {}).items():
            if isinstance(spec, str):
                hub.add_restraint(nid, preset=spec)
            else:
                hub.add_restraint(nid, **spec)
        hub.add_body_force("self weight")
        return hub


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def member_frame(p_i: Point3, p_j: Point3, normal: Point3):
    """``(u, v, w, length)`` for a member: ``u`` along it, ``v`` across the
    width (the truss plane normal, squared up against ``u``), ``w`` through
    the depth in the truss plane."""
    d = _sub(p_j, p_i)
    length = _norm(d)
    if length < 1e-9:
        raise ValueError("member has zero length")
    u = _scale(d, 1.0 / length)
    v = _sub(normal, _scale(u, _dot(normal, u)))     # normal, orthogonalised
    if _norm(v) < 1e-9:                              # member runs along the normal
        alt = (0.0, 0.0, 1.0) if abs(u[2]) < 0.9 else (1.0, 0.0, 0.0)
        v = _sub(alt, _scale(u, _dot(alt, u)))
    v = _unit(v)
    w = _cross(u, v)
    return u, v, w, length


def _rect_loop(origin, v, w, y_c, z_c, b, h):
    """The four corners of a section rectangle, in bridge coordinates (feet).

    ``y_c``/``z_c``/``b``/``h`` are inches in the section's own axes."""
    ft = 1.0 / 12.0
    pts = []
    for sy, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        y = (y_c + sy * b / 2.0) * ft
        z = (z_c + sz * h / 2.0) * ft
        pts.append(_add(origin, _add(_scale(v, y), _scale(w, z))))
    return tuple(pts)


def member_objects(model: TrussModel, m: TrussMember, *, lod: int = 400,
                   shorten_ft: float = 0.0) -> list:
    """The solids for one truss member.

    At ``lod >= 400`` one prism per plate and per angle leg -- the member as
    it was riveted; at LOD 300 a single enveloping box.  ``shorten_ft``
    trims both ends, so members can stop clear of the gusset plates instead
    of running through them."""
    p_i = model.nodes[m.i].point
    p_j = model.nodes[m.j].point
    u, v, w, length = member_frame(p_i, p_j, m.normal)
    if shorten_ft > 0.0 and length > 2.2 * shorten_ft:
        p_i = _add(p_i, _scale(u, shorten_ft))
        length -= 2.0 * shorten_ft
    vector = _scale(u, length)
    props = builtup.properties(m.spec)
    weight_lb = props["A"] / 144.0 * builtup.STEEL_PCF * length
    if m.role not in TYPE_LAYER:
        raise ValueError("unknown truss member role %r; expected one of %s"
                         % (m.role, ", ".join(bim.TRUSS_MEMBER_TYPES)))
    layer = TYPE_LAYER[m.role]

    if lod < 400:
        # One enveloping box, so the whole bridge opens in a browser -- but
        # the box still records what the shop built.  LOD 400 is a statement
        # about the attributes as much as the geometry.
        b, h = builtup.envelope(m.spec)
        tags = bim.truss_member_tags(
            m.id, role=m.role, spec=m.spec, length_ft=length,
            weight_lb=weight_lb, line=m.line, span=m.span, steel=m.steel,
            fabrication=m.fabrication)
        return [EmitObject("prism", layer, _rect_loop(p_i, v, w, 0.0, 0.0, b, h),
                           tags, vector)]

    if lod >= 400 and m.fabrication is not None:
        return _fabricated_objects(m, p_i, u, v, w, length, layer)

    rects, _meta = builtup.rects(m.spec)
    labels = builtup.piece_labels(m.spec)
    out = []
    for k, (b, h, y_c, z_c) in enumerate(rects):
        # the pay quantity rides on the first piece only: every piece shares
        # the member's bim.id, and the takeoff sums pay.qty
        tags = bim.truss_member_tags(
            m.id, role=m.role, spec=m.spec, length_ft=length,
            weight_lb=weight_lb if k == 0 else None,
            line=m.line, span=m.span, steel=m.steel,
            piece=labels[k] if k < len(labels) else "piece %d" % k)
        out.append(EmitObject("prism", layer,
                              _rect_loop(p_i, v, w, y_c, z_c, b, h),
                              tags, vector))
    return out


def _fabricated_objects(m, p_i, u, v, w, length, layer) -> list:
    """Every piece of a laced member as its own solid.

    Full-length pieces (web plates, angles, cover plates) run along the
    member axis.  Tie plates do too but start partway along and are short.
    Lacing bars run at their inclination *within* a face, so their axis is a
    combination of the member axis and the across direction and their
    thickness lies through the face."""
    lm = m.fabrication
    if getattr(lm, "length_ft", None) != length:
        lm = laced_member.LacedMember(
            spec=lm.spec, length_ft=length, lacing=lm.lacing,
            tie_plates=lm.tie_plates, rivet_dia_in=lm.rivet_dia_in,
            rivet_hole_in=lm.rivet_hole_in, source=lm.source)
    ft = 1.0 / 12.0
    out = []
    first = True
    for piece in lm.pieces():
        tags = bim.member_piece_tags(
            m.id, role=m.role, spec=m.spec, piece_kind=piece.kind,
            label=piece.label, designation=piece.designation,
            length_ft=piece.length_ft,
            weight_lb=lm.weight_lb() if first else None,
            face=piece.face, source=piece.source, line=m.line, span=m.span,
            steel=m.steel)
        first = False
        start = _add(p_i, _scale(u, piece.along_ft))
        if piece.kind == "lacing bar":
            # the bar lies in its face: axis is inclined from the member axis
            # by angle_deg, thickness through the face
            th = math.radians(abs(piece.angle_deg))
            sign = 1.0 if piece.angle_deg >= 0 else -1.0
            axis = _unit(_add(_scale(u, math.cos(th)),
                              _scale(v, sign * math.sin(th))))
            across = _cross(w, axis)                   # in the face, across the bar
            origin = _add(_add(start, _scale(w, piece.z_in * ft)),
                          _scale(v, -sign * lm.lacing_gauge_in() / 2.0 * ft))
            loop = _rect_loop(origin, across, w, 0.0, 0.0,
                              piece.b_in, piece.h_in)
            out.append(EmitObject("prism", layer, loop, tags,
                                  _scale(axis, piece.length_ft)))
        else:
            loop = _rect_loop(start, v, w, piece.y_in, piece.z_in,
                              piece.b_in, piece.h_in)
            out.append(EmitObject("prism", layer, loop, tags,
                                  _scale(u, piece.length_ft)))
    return out


def framing_objects(model: TrussModel, f: FramingMember, *,
                    lod: int = 400) -> list:
    """The solids for a floor beam, stringer or brace: web and flanges at
    LOD 400, one enveloping box below that."""
    p_i = model.nodes[f.i].point
    p_j = model.nodes[f.j].point
    u, v, w, length = member_frame(p_i, p_j, f.normal)
    weight_lb = f.area_in2 / 144.0 * builtup.STEEL_PCF * length
    vector = _scale(u, length)
    layer = TYPE_LAYER[f.role]
    if lod < 400:
        tags = bim.truss_framing_tags(
            f.id, role=f.role, section=f.section, length_ft=length,
            weight_lb=weight_lb, level=f.level or None, span=f.span or None)
        return [EmitObject("prism", layer,
                           _rect_loop(p_i, v, w, 0.0, 0.0, f.width_in, f.depth_in),
                           tags, vector)]
    names = ("web", "bottom flange", "top flange")
    out = []
    for k, (b, h, y_c, z_c) in enumerate(f.rects()):
        if b <= 0.0 or h <= 0.0:
            continue
        tags = bim.truss_framing_tags(
            f.id, role=f.role, section=f.section, length_ft=length,
            weight_lb=weight_lb if k == 0 else None,
            level=f.level or None, span=f.span or None)
        tags["framing.piece"] = names[k] if k < len(names) else "piece %d" % k
        out.append(EmitObject("prism", layer,
                              _rect_loop(p_i, v, w, y_c, z_c, b, h), tags, vector))
    return out


def gusset_objects(model: TrussModel, g: GussetPlacement) -> list:
    """One plate solid for a gusset, positioned on its joint.

    The plate's 2-D outline is carried into bridge coordinates by putting its
    work point on the node, its local +x along ``plane_x`` and its local +y
    on the in-plane perpendicular, then extruding along the normal by the
    plate thickness."""
    node = model.nodes[g.node]
    n = _unit(g.normal)
    ex = _sub(g.plane_x, _scale(n, _dot(g.plane_x, n)))
    ex = _unit(ex)
    # plate +y must come out UP: with the plate normal transverse (+Y) and
    # its +x along the bridge (+X), that is cross(ex, n), not cross(n, ex) --
    # the other order lands the drawing upside down on the joint.
    ey = _cross(ex, n)
    ft = 1.0 / 12.0
    base = _add(node.point, _scale(n, g.offset_in * ft))
    wx, wy = g.work_point
    pts = tuple(
        _add(base, _add(_scale(ex, (px - wx) * ft), _scale(ey, (py - wy) * ft)))
        for px, py in g.outline)

    area = abs(_polygon_area(g.outline))
    t = g.t_remaining_in if g.t_remaining_in is not None else g.thickness_in
    weight_lb = area * t / 1728.0 * builtup.STEEL_PCF
    tags = bim.gusset_plate_tags(
        g.id, joint=g.joint or g.node, thickness_in=g.thickness_in,
        face=g.face, area_in2=area, weight_lb=weight_lb,
        members=g.members or None, t_remaining_in=g.t_remaining_in,
        rating_rf=g.rating_rf, governing=g.governing or None, steel=g.steel)
    return [EmitObject("prism", LAYER_GUSSET_PLATES, pts, tags,
                       _scale(n, g.thickness_in * ft))]


def pin_objects(model: TrussModel, p: PinPlacement) -> list:
    """The pin as one cylinder along its axis through the work point,
    spanning its packing (outer plate faces) plus ``projection_in`` at each
    end for the nuts or caps."""
    pin = p.pin
    if pin.packing:
        lo = min(k.position - k.thickness / 2 for k in pin.packing)
        hi = max(k.position + k.thickness / 2 for k in pin.packing)
    else:
        lo = hi = 0.0
    lo, hi = lo - p.projection_in, hi + p.projection_in
    ft = 1.0 / 12.0
    a = _unit(p.axis)
    c = model.nodes[p.node].point
    base, tip = _add(c, _scale(a, lo * ft)), _add(c, _scale(a, hi * ft))
    length_in = hi - lo
    weight = math.pi * (pin.diameter / 2) ** 2 * length_in / 1728.0 * builtup.STEEL_PCF
    tags = bim.truss_pin_tags(p.id, diameter_in=pin.diameter, length_in=length_in,
                              fy_ksi=pin.fy, joint=p.joint or p.node, weight_lb=weight,
                              rating_rf=p.rating_rf, governing=p.governing)
    return [EmitObject("cylinder", LAYER_TRUSS_PINS, (base, tip), tags,
                       radius_ft=pin.diameter / 2.0 * ft)]


def gusset_rivet_objects(model: TrussModel, g: GussetPlacement, *,
                         grip_in: float = None) -> list:
    """One cylinder per traced rivet, driven through the plate.

    This is what takes a gusset from LOD 400 to 500: the plate is no longer a
    blank, it is the plate with the connection that is actually on it, and a
    reviewer can see which member each rivet belongs to and count them
    against the rating.  The rivet runs the full grip -- the plate plus the
    member webs behind it -- so it reads as hardware rather than as a dimple
    on a face."""
    if not g.rivets:
        return []
    node = model.nodes[g.node]
    n = _unit(g.normal)
    ex = _unit(_sub(g.plane_x, _scale(n, _dot(g.plane_x, n))))
    ey = _cross(ex, n)
    ft = 1.0 / 12.0
    base = _add(node.point, _scale(n, g.offset_in * ft))
    wx, wy = g.work_point
    grip = grip_in if grip_in is not None else g.thickness_in * 2.0
    out = []
    for k, r in enumerate(g.rivets):
        px, py = r[0], r[1]
        member = r[2] if len(r) > 2 else ""
        c = _add(base, _add(_scale(ex, (px - wx) * ft), _scale(ey, (py - wy) * ft)))
        tip = _add(c, _scale(n, grip * ft))
        tags = bim.rivet_tags("%s-r%d" % (g.id, k), host=g.id,
                              diameter_in=g.rivet_diameter_in, grip_in=grip,
                              member=member)
        tags["rivet.joint"] = g.joint or g.node
        out.append(EmitObject("cylinder", LAYER_RIVETS, (c, tip), tags,
                              radius_ft=g.rivet_diameter_in / 2.0 * ft))
    return out


def _polygon_area(poly) -> float:
    a = 0.0
    n = len(poly)
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


@dataclass(frozen=True)
class MemberEndAtJoint:
    """One member framing into a joint, as the gusset sees it.

    ``axis`` points away from the work point in plate coordinates (x along
    the bridge, y up); ``depth_in`` is the member's depth in the truss plane,
    which is how wide the plate must be where that member lands;
    ``connection_in`` is how far out along the member the connection runs --
    the 2012 rating tabulates exactly this ("connection length for one line
    of connectors").  ``through`` marks a member that passes through the
    joint rather than terminating in it, i.e. a continuous chord."""
    name: str
    axis: tuple
    depth_in: float
    connection_in: float
    through: bool = False


def _convex_hull(points) -> list:
    """Counter-clockwise convex hull (Andrew's monotone chain)."""
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(pts) <= 2:
        return list(pts)

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2:
                (x0, y0), (x1, y1) = out[-2], out[-1]
                if (x1 - x0) * (q[1] - y0) - (y1 - y0) * (q[0] - x0) > 0:
                    break
                out.pop()
            out.append(q)
        return out

    lower, upper = half(pts), half(reversed(pts))
    return lower[:-1] + upper[:-1]


def offset_convex_outward(poly, d: float) -> list:
    """Push every edge of a convex counter-clockwise polygon out by ``d``.

    Corners come out mitred rather than rounded, which is what a sheared
    plate edge actually looks like.
    """
    lines = []
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        L = math.hypot(ex, ey)
        if L < 1e-9:
            continue
        nx, ny = ey / L, -ex / L                 # outward for CCW
        lines.append((nx, ny, nx * x0 + ny * y0 + d))
    pts = []
    m = len(lines)
    for i in range(m):
        a1, b1, c1 = lines[i]
        a2, b2, c2 = lines[(i + 1) % m]
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-9:
            continue
        pts.append(((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det))
    return _convex_hull(pts) if len(pts) >= 3 else list(poly)


def clip_polygon_to_rect(poly, x0: float, y0: float, x1: float,
                         y1: float) -> list:
    """Sutherland-Hodgman clip of a simple polygon to an axis-aligned box."""
    def _clip(pts, keep, cut):
        out = []
        for i, cur in enumerate(pts):
            prv = pts[i - 1]
            kc, kp = keep(cur), keep(prv)
            if kc:
                if not kp:
                    out.append(cut(prv, cur))
                out.append(cur)
            elif kp:
                out.append(cut(prv, cur))
        return out

    def _x(v):
        return lambda a, b: (v, a[1] + (b[1] - a[1]) * (v - a[0]) / (b[0] - a[0])
                             if abs(b[0] - a[0]) > 1e-12 else a[1])

    def _y(v):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (v - a[1]) / (b[1] - a[1])
                             if abs(b[1] - a[1]) > 1e-12 else a[0], v)

    out = list(poly)
    for keep, cut in ((lambda q: q[0] >= x0, _x(x0)),
                      (lambda q: q[0] <= x1, _x(x1)),
                      (lambda q: q[1] >= y0, _y(y0)),
                      (lambda q: q[1] <= y1, _y(y1))):
        if not out:
            return []
        out = _clip(out, keep, cut)
    return out


def gusset_outline_from_members(ends, *, edge_in: float = 2.0,
                                work_point=(0.0, 0.0), fasteners=None,
                                bounds=None) -> list:
    """Build a gusset outline from the members it connects.

    The shape of a gusset is not a free choice and it is not something to
    trace off a drawing: it follows from the members.  Each member end needs
    the plate to reach its **full depth**, and the plate is cut **square to
    that member's own axis** just beyond its last row of fasteners.  Between
    one member's connection and the next the plate runs a **straight slope**
    from corner to corner.  A chord passing through the joint is not cut off
    at all -- the plate simply follows it.

    So each member contributes two corners::

        corner = work_point + (connection + edge) * axis  +/-  depth/2 * normal

    and the outline is those corners taken in angular order about the work
    point.  The square end-cut is the segment between a member's own two
    corners; the slope is the segment between adjacent members' corners.
    Where the members all leave on one side -- an end joint -- the work point
    closes the shape.

    ``edge_in`` is the edge distance carried beyond the connection.

    The result is the convex hull of those corners together with the work
    point -- see the body for why the hull is the right closure and not
    merely a convenience.

    ``fasteners``, if given as the plate's rivet field in plate coordinates,
    also sizes the plate to the field: a 1932 plate edge sits an edge
    distance beyond the outermost fastener, so the field's own hull pushed
    out by ``edge_in`` is a lower bound on the plate.  It matters because the
    reach only sees the rivets inside a member's own depth, and a real
    fastener field spreads wider than that -- without it the outline leaves a
    median 13% of the rivets off the plate, which no gusset does.

    ``bounds``, if given as ``(x0, y0, x1, y1)``, clips the result to the
    plate's overall size.  The rule places each corner where its member needs
    it, which at a tight joint can put a corner past the edge of the plate the
    shop actually cut; the overall width and depth are tabulated in the rating
    and are the one plate dimension that is independently confirmed, so
    clipping to them keeps the shape inside what is known to be true.

    Returns the polygon in plate coordinates (inches), counter-clockwise.
    """
    if len(ends) < 2 and not (fasteners is not None and len(fasteners) >= 3):
        # With fewer than two members and no fastener field there is nothing
        # to build from.  With a field there is: the plate is then just the
        # 1932 edge-distance rule applied to the fasteners, which is what to
        # fall back on at a joint whose members the model does not fully
        # carry -- a sway frame, a lateral connection, a splice.
        return []
    wx, wy = work_point
    corners = []
    for e in ends:
        ax, ay = e.axis
        n = math.hypot(ax, ay)
        if n < 1e-9:
            continue
        ax, ay = ax / n, ay / n
        px, py = -ay, ax                      # normal to the member
        reach = e.connection_in + edge_in
        half = e.depth_in / 2.0
        base = (wx + reach * ax, wy + reach * ay)
        for sgn in (-1.0, 1.0):
            corners.append((base[0] + sgn * half * px,
                            base[1] + sgn * half * py))
    if len(corners) < 3 and not (fasteners is not None
                                 and len(fasteners) >= 3):
        return []
    # angular order about the work point closes the polygon the way the
    # members sit around the joint
    # The plate is convex -- which is what the sheets and the field
    # photographs show, and what the half-plane trace already assumes -- so
    # the outline is the hull of the corners.  Taking the hull rather than
    # the corners in angular order does two things the rule needs:
    #
    # * a member whose connection is short and crowded has both its corners
    #   *inside* its neighbours'.  In angular order the outline dives in to
    #   them and back out, notching a deep V into the middle of the plate.
    #   On the hull the plate simply passes over that member, which is still
    #   covered to its full depth -- Dane's straight slope from one
    #   connection point to the next.
    # * at an end joint every member leaves on the same side, so the corners
    #   span less than a half turn and do not close around the work point.
    #   Including the work point in the hull closes the plate on it there,
    #   and changes nothing at an interior joint, where it falls inside.
    if ends:
        corners = corners + [(wx, wy)]
    if fasteners is not None and len(fasteners):
        field = [(float(f[0]), float(f[1])) for f in fasteners]
        if len(field) >= 3:
            corners += offset_convex_outward(_convex_hull(field), edge_in)
    corners = _convex_hull(corners)
    if bounds is not None:
        corners = _dedupe_polygon(clip_polygon_to_rect(corners, *bounds))
    return corners


def _dedupe_polygon(poly, tol=0.5):
    out = []
    for q in poly:
        if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > tol:
            out.append(q)
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0],
                                   out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def member_ends_at(model: TrussModel, node: TrussNode, connections=None,
                   default_connection_in: float = 30.0) -> list:
    """The :class:`MemberEndAtJoint` records for a panel point.

    Directions come from the model, depths from the members' own built-up
    sections, and connection lengths from ``connections`` -- a mapping of
    member name to inches, which for a rated truss is the rating sheet's own
    tabulated connection length."""
    connections = connections or {}
    out = []
    for m in model.members:
        if m.i == node.id:
            far = model.nodes[m.j].point
        elif m.j == node.id:
            far = model.nodes[m.i].point
        else:
            continue
        dx, dz = far[0] - node.point[0], far[2] - node.point[2]
        n = math.hypot(dx, dz)
        if n < 1e-9:
            continue
        short = m.id.rsplit("-", 1)[-1]
        try:
            depth = builtup.envelope(m.spec)[1]
        except Exception:
            depth = 24.0
        out.append(MemberEndAtJoint(
            short, (dx / n, dz / n), depth,
            float(connections.get(short, default_connection_in)),
            through=m.role.startswith("truss_chord")))
    return out


def review_objects(model: TrussModel, item: ReviewItem, *,
                   margin_in: float = 3.0) -> list:
    """A highlight sleeve around whatever the review item points at.

    A box enveloping the target member -- inflated by ``margin_in`` so it
    reads as a sleeve around it rather than z-fighting with it -- or the
    plate, or a marker at a node.  The item tags ride on it, and the same
    tags are stamped on the target element by :func:`review_element_tags`,
    so the overlay can be isolated *and* the element answers for itself.
    """
    layer = TYPE_LAYER.get(item.kind, LAYER_REVIEW_REPAIRS)
    member = next((m for m in model.members if m.id == item.target), None)
    if member is not None:
        p_i = model.nodes[member.i].point
        p_j = model.nodes[member.j].point
        u, v, w, length = member_frame(p_i, p_j, member.normal)
        b, h = builtup.envelope(member.spec)
        return [EmitObject("prism", layer,
                           _rect_loop(p_i, v, w, 0.0, 0.0,
                                      b + 2 * margin_in, h + 2 * margin_in),
                           dict(item.tags), _scale(u, length))]
    fram = next((f for f in model.framing if f.id == item.target), None)
    if fram is not None:
        p_i = model.nodes[fram.i].point
        p_j = model.nodes[fram.j].point
        u, v, w, length = member_frame(p_i, p_j, fram.normal)
        return [EmitObject("prism", layer,
                           _rect_loop(p_i, v, w, 0.0, 0.0,
                                      fram.width_in + 2 * margin_in,
                                      fram.depth_in + 2 * margin_in),
                           dict(item.tags), _scale(u, length))]
    gus = next((g for g in model.gussets if g.id == item.target), None)
    if gus is not None:
        obj = gusset_objects(model, gus)[0]
        return [EmitObject("prism", layer, obj.points, dict(item.tags),
                           obj.vector)]
    node = model.nodes.get(item.target)
    if node is not None:
        return [EmitObject("point", layer, (node.point,), dict(item.tags))]
    return []


def unresolved_reviews(model: TrussModel) -> list:
    """Review items whose target is not in the model.

    A repair pointing at a member that does not exist is a mapping error
    worth seeing, not something to swallow silently."""
    known = {m.id for m in model.members}
    known |= {f.id for f in model.framing}
    known |= {g.id for g in model.gussets}
    known |= {p.id for p in model.pins}
    known |= set(model.nodes)
    return [i for i in model.reviews if i.target not in known]


def review_element_tags(model: TrussModel) -> dict:
    """``{target bim.id: extra tags}`` -- the review commentary flattened onto
    the elements it refers to, so a member carries its own repair and finding
    history in the file.

    Several items on one element are numbered (``repair.item``,
    ``repair2.item``, ...) rather than overwriting each other; a lower chord
    with pack-rust removal *and* an LC-1 rebuild has to show both."""
    out = {}
    seen = {}
    for item in model.reviews:
        acc = out.setdefault(item.target, {})
        n = seen.get((item.target, item.kind), 0)
        seen[(item.target, item.kind)] = n + 1
        prefix = item.kind if n == 0 else "%s%d" % (item.kind, n + 1)
        for k, v in item.tags.items():
            if k in ("bim.type", "bim.id"):
                continue
            acc[k.replace(item.kind + ".", prefix + ".", 1)] = v
    for target, acc in out.items():
        for kind in ("repair", "finding"):
            c = seen.get((target, kind), 0)
            if c:
                acc["%s.count" % kind] = str(c)
    return out


def panel_point_objects(model: TrussModel, node: TrussNode) -> list:
    """The work-point marker for a panel point."""
    tags = bim.panel_point_tags(node.id, joint=node.joint or node.id,
                                line=node.line, span=node.span,
                                chord=node.chord, pp=node.pp)
    return [EmitObject("point", LAYER_PANEL_POINTS, (node.point,), tags)]


# --------------------------------------------------------------------------- #
# emit
# --------------------------------------------------------------------------- #
def truss_emit(model: TrussModel, *, lod: int = 400, shorten_ft: float = 0.0,
               panel_points: bool = True, framing: bool = True,
               gussets: bool = True, members: bool = True,
               rivets: bool = False, reviews: bool = True,
               pins: bool = True) -> tuple:
    """Every drawable object of ``model`` as neutral ``EmitObject`` records.

    ``lod`` 400 or more draws the built-up members piece by piece; 300 draws
    each as one enveloping box, which is what a whole-bridge file wants.
    The content switches let a caller emit, say, only the gusset plates and
    the panel points for a joint-by-joint review file.  ``rivets`` draws the
    traced rivets as hardware (LOD 500); it is off by default because a whole
    bridge is six figures of them."""
    out = []
    extra = review_element_tags(model) if reviews else {}
    if members:
        for m in model.members:
            objs = member_objects(model, m, lod=lod, shorten_ft=shorten_ft)
            for o in objs:
                o.tags.update(extra.get(m.id, {}))
            out.extend(objs)
    if framing:
        for f in model.framing:
            objs = framing_objects(model, f, lod=lod)
            for o in objs:
                o.tags.update(extra.get(f.id, {}))
            out.extend(objs)
    if gussets:
        for g in model.gussets:
            objs = gusset_objects(model, g)
            for o in objs:
                o.tags.update(extra.get(g.id, {}))
            out.extend(objs)
            if rivets:
                out.extend(gusset_rivet_objects(model, g))
    if pins:
        for p in model.pins:
            objs = pin_objects(model, p)
            for o in objs:
                o.tags.update(extra.get(p.id, {}))
            out.extend(objs)
    if reviews:
        for item in model.reviews:
            out.extend(review_objects(model, item))
    if panel_points:
        for node in model.nodes.values():
            if node.chord in ("U", "L"):
                out.extend(panel_point_objects(model, node))
    return tuple(out)


def model_doc_tags(model: TrussModel, *, lod: int) -> dict:
    """The document-wide record, carried on a ``bim.type = bridge`` marker
    the way ``rhino_bim`` does (standalone ``rhino3dm`` cannot write the
    document string table)."""
    (x0, y0, z0), (x1, y1, z1) = model.bbox()
    tags = {"bim.type": "bridge", "bim.id": model.name,
            "bridge.structure_type": "riveted steel truss",
            "bridge.lod": str(lod),
            "bridge.units": "feet",
            "bridge.length_ft": "%.3f" % (x1 - x0),
            "bridge.width_ft": "%.3f" % (y1 - y0),
            "bridge.height_ft": "%.3f" % (z1 - z0),
            "bridge.panel_points": str(sum(1 for n in model.nodes.values()
                                           if n.chord in ("U", "L"))),
            "bridge.truss_members": str(len(model.members)),
            "bridge.framing_members": str(len(model.framing)),
            "bridge.gusset_plates": str(len(model.gussets)),
            "bridge.review_items": str(len(model.reviews)),
            "bridge.generator": "civilpy.structural.rhino_truss"}
    tags.update(model.doc_tags)
    return tags


def truss_to_3dm(model: TrussModel, path, *, lod: int = 400,
                 mesh: bool = True, version: int = 7, shorten_ft: float = 0.0,
                 **content) -> dict:
    """Bake the truss to a ``.3dm``.

    ``mesh=True`` (the default here, unlike ``rhino_bim``) builds closed
    meshes rather than breps: headless ``rhino3dm`` cannot tessellate a brep,
    so a brep file arrives *empty* in three.js -- and the point of this model
    is that it opens in the asset-management viewer.  Returns per-layer
    object counts."""
    from civilpy.structural.rhino_bim import objects_to_3dm

    objects = truss_emit(model, lod=lod, shorten_ft=shorten_ft, **content)
    doc = EmitObject("point", LAYER_PANEL_POINTS,
                     (model.bbox()[0],), model_doc_tags(model, lod=lod))
    return objects_to_3dm(objects + (doc,), path, version=version, mesh=mesh)


def gusset_joint_placements(joint, node_id: str, *, thickness_in: float = None,
                            half_width_in: float = 9.0, plane_x=(1.0, 0.0, 0.0),
                            normal=(0.0, 1.0, 0.0), rating_rf: float = None,
                            governing: str = "", id_prefix: str = "") -> list:
    """The two :class:`GussetPlacement` records for a
    :class:`~civilpy.structural.gusset_geometry.GussetJoint` -- one plate on
    each face of the member webs, ``half_width_in`` either side of the truss
    line.

    This is the bridge between the failure-plane drawings and the 3-D model:
    a joint parsed off a sheet drops straight onto its panel point."""
    prefix = id_prefix or joint.name
    out = []
    for face, sign, plate in (("inside", -1.0, joint.inside),
                              ("outside", +1.0, joint.outside or joint.inside)):
        if plate is None:
            continue
        members = ",".join(m.name for m in joint.members)
        loss = None
        if getattr(plate.thickness, "patches", None):
            loss = min(p.t_remaining for p in plate.thickness.patches)
        out.append(GussetPlacement(
            id="%s-%s" % (prefix, face), node=node_id,
            outline=tuple(plate.outline), work_point=tuple(joint.work_point),
            thickness_in=thickness_in or plate.t, joint=joint.name, face=face,
            offset_in=sign * half_width_in,
            plane_x=plane_x, normal=normal, members=members,
            t_remaining_in=loss, rating_rf=rating_rf, governing=governing))
    return out
