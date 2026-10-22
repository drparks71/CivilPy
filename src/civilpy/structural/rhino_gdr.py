"""Rhino 3D -> girder-line model (the ``gdr.*`` reader, stage **G4**).

Parses a tagged ``.3dm`` authored by the C# ``GirderLines`` / ``GirderShape`` /
``GirderBearing`` commands into the canonical
:class:`~civilpy.structural.structural_model.StructuralModel` hub, following the
girder / field-splice contract in ``docs/Rhino Design Philosophy.md``:

    Geometry carries what is spatial; tags carry what is scalar.

* **Girder lines** are curves tagged ``gdr.kind=girder`` with ``gdr.shape``
  (AISC label, e.g. ``W24X104``), ``gdr.grade`` (default ``Grade 50``), and
  ``gdr.line`` (girder number).  A polyline yields one :class:`Element` per
  segment (a continuous-span chain); each element carries the resolved AISC
  section label and the grade.
* **Bearings** are points tagged ``gdr.kind=support`` with
  ``gdr.fixity=fixed|expansion`` and ``gdr.line``; they become 6-DOF
  :class:`Restraint`\\ s on the nearest node of their girder line.
* **Bridge parameters** live in document user text (``gdr.deck_t``,
  ``gdr.deck_weff``, ``gdr.deck_fc``, ``gdr.ship_max``, ``gdr.bolt_*``) and are
  returned as a :class:`GirderBridge` alongside the hub.

Plane convention: **PLAN** -- X = stations along the bridge, Y = transverse,
Z = up; lengths in feet (``ModelUnitSystem`` honored on read, mirroring
``rhino_stm``).  ``rhino3dm`` is an optional dependency imported lazily.
"""

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

from __future__ import annotations

import math
import uuid
import warnings
from dataclasses import dataclass, field

from civilpy.structural.rhino_layers import (
    LAYER_DISPLAY, LAYER_SPLICES, ensure_layer,
)
from civilpy.structural.rhino_stm import _require_rhino3dm, _unit_to_feet
from civilpy.structural.structural_model import StructuralModel, Units

GTAG = "gdr."  # user-text namespace for the girder pipeline

# gdr.grade -> (Fy, Fu) ksi.  The C# picker offers these names (Gdr.cs
# GradeChoices); they are UI-friendly and do not resolve to civilpy's
# ASTM-named SteelMaterial instances, so the mapping lives here (G1 sign-off
# follow-up #1).  Weathering / HPS grades have no prebuilt SteelMaterial yet.
GRADE_FY_FU: dict[str, tuple[float, float]] = {
    "Grade 36": (36.0, 58.0),
    "Grade 50": (50.0, 65.0),
    "Grade 50W": (50.0, 70.0),
    "HPS 50W": (50.0, 70.0),
    "HPS 70W": (70.0, 85.0),
}
DEFAULT_GRADE = "Grade 50"

# gdr.fixity -> 6-DOF restraint flags, in the PLAN frame (X longitudinal,
# Y transverse, Z vertical).  Bearings restrain translation only (rotations
# free); a fixed bearing holds longitudinal too, an expansion bearing frees it.
FIXITY_DOF: dict[str, dict[str, bool]] = {
    "fixed": {"fix_x": True, "fix_y": True, "fix_z": True},
    "expansion": {"fix_x": False, "fix_y": True, "fix_z": True},
}

# document-level bridge parameters and their units (for the loud-default note)
_DECK_KEYS = {
    "deck_t": "in", "deck_weff": "in", "deck_fc": "ksi",
    "ship_max": "ft", "bolt_dia": "in", "bolt_spec": "-",
    "bolt_hole": "-", "bolt_class": "-",
}
_DECK_DEFAULTS = {
    "deck_fc": 4.0, "ship_max": 100.0, "bolt_dia": 0.875,
    "bolt_spec": "A325", "bolt_hole": "oversize", "bolt_class": "C",
}


@dataclass
class GirderBridge:
    """The canonical hub plus the document-level bridge parameters the girder /
    splice pipeline needs (deck composite section + bolt standard).  Missing
    ``deck_t`` / ``deck_weff`` are ``None`` (a loud warning is issued on read);
    the rest fall back to the ODOT BDM 308.2.2.1.j defaults."""

    model: StructuralModel
    deck_t: float | None = None          # structural slab thickness, in
    deck_weff: float | None = None       # effective flange width, in
    deck_fc: float = 4.0                 # deck concrete strength, ksi
    ship_max: float = 100.0              # max shipping length, ft
    bolt_dia: float = 0.875              # bolt diameter, in
    bolt_spec: str = "A325"
    bolt_hole: str = "oversize"
    bolt_class: str = "C"
    girder_lines: dict[str, list[str]] = field(default_factory=dict)  # line -> element ids


def resolve_shape(label: str):
    """Look up an AISC W-shape by (already-normalized) label via
    ``steel.W``; returns the section or ``None`` (with a warning) if it does not
    resolve.  Import is local so the reader works without the steel db warmed."""
    from civilpy.structural import steel
    try:
        return steel.W(label)
    except Exception as exc:  # pragma: no cover - db-shape specific
        warnings.warn(f"gdr.shape {label!r} did not resolve to an AISC "
                      f"W-shape ({exc}); the element keeps the raw label.")
        return None


def grade_fy_fu(grade: str) -> tuple[float, float]:
    """(Fy, Fu) ksi for a ``gdr.grade`` name; warns + defaults to Grade 50."""
    if grade not in GRADE_FY_FU:
        warnings.warn(f"unknown gdr.grade {grade!r}; assuming {DEFAULT_GRADE}.")
        return GRADE_FY_FU[DEFAULT_GRADE]
    return GRADE_FY_FU[grade]


def _curve_vertices(g, scale):
    """Ordered 3D vertices (scaled to feet) of a line or polyline curve, or
    ``None`` if the geometry is not a readable curve."""
    gtype = type(g).__name__
    pts = []
    if gtype == "PolylineCurve" and hasattr(g, "PointCount"):
        for i in range(g.PointCount):
            p = g.Point(i)
            pts.append((p.X * scale, p.Y * scale, p.Z * scale))
    elif hasattr(g, "PointAtStart") and hasattr(g, "PointAtEnd"):
        a, b = g.PointAtStart, g.PointAtEnd
        pts = [(a.X * scale, a.Y * scale, a.Z * scale),
               (b.X * scale, b.Y * scale, b.Z * scale)]
    else:
        return None
    return pts


def _read_gdr_raw(path):
    """Parse a tagged ``.3dm`` into ``(girders_raw, supports_raw, doc)``.

    * ``girders_raw`` = ``[(vertices, shape, grade, line), ...]`` (feet),
    * ``supports_raw`` = ``[(point, fixity, line), ...]`` (feet),
    * ``doc`` = the document user-text dict (bridge params, raw strings).
    """
    r3 = _require_rhino3dm()
    f = r3.File3dm.Read(str(path))
    if f is None:
        raise FileNotFoundError(f"could not read 3dm file: {path}")
    scale = _unit_to_feet(f)

    girders_raw, supports_raw, doc = [], [], {}
    for obj in f.Objects:
        attrs = obj.Attributes
        if attrs.IsInstanceDefinitionObject:
            continue
        us = dict(attrs.GetUserStrings() or {})
        kind = us.get(GTAG + "kind")
        g = obj.Geometry
        if kind == "bridge":
            # bridge-wide parameters ride on a dedicated marker object's user
            # text -- NOT RhinoDoc.Strings, which rhino3dm cannot read.
            doc.update(us)
            continue
        if kind == "girder":
            verts = _curve_vertices(g, scale)
            if verts is None or len(verts) < 2:
                warnings.warn("gdr.kind=girder object is not a readable "
                              "line/polyline; skipping.")
                continue
            shape = _normalize_shape(us.get(GTAG + "shape", ""))
            grade = us.get(GTAG + "grade", DEFAULT_GRADE)
            line = us.get(GTAG + "line", "")
            girders_raw.append((verts, shape, grade, line))
        elif kind == "support":
            loc = getattr(g, "Location", None)
            if loc is None:
                warnings.warn("gdr.kind=support object is not a point; "
                              "skipping.")
                continue
            pt = (loc.X * scale, loc.Y * scale, loc.Z * scale)
            fixity = us.get(GTAG + "fixity", "fixed")
            supports_raw.append((pt, fixity, us.get(GTAG + "line", "")))

    return girders_raw, supports_raw, doc


def _normalize_shape(label: str) -> str:
    """Match civilpy's ``SteelSection.clean_user_input`` / the C#
    ``Gdr.NormalizeShapeLabel``: strip spaces, uppercase."""
    return label.replace(" ", "").upper()


def _doc_float(doc, key, default=None):
    raw = doc.get(GTAG + key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        warnings.warn(f"{GTAG}{key}={raw!r} is not a number; using {default!r}.")
        return default


def read_girder_model(path, *, tol=0.5) -> GirderBridge:
    """Read a tagged Rhino ``.3dm`` into a :class:`GirderBridge` (the canonical
    hub + bridge parameters).  One :class:`Element` chain per ``gdr.line``;
    ``Element.section`` is the resolved AISC label, ``Element.material`` the
    grade name.  Bearings become 6-DOF restraints on the nearest node of their
    girder line.

    Parameters
    ----------
    path : str
        Path to the ``.3dm`` file.
    tol : float
        Snap tolerance (feet) for attaching a bearing point to a girder node.
    """
    girders_raw, supports_raw, doc = _read_gdr_raw(path)

    model = StructuralModel(units=Units(force="kips", length="ft"))
    girder_lines: dict[str, list[str]] = {}
    # node id by (rounded) coordinate, so shared bearing/girder points coincide
    node_by_xyz: dict[tuple, str] = {}

    def node_at(pt, label=None):
        key = (round(pt[0], 3), round(pt[1], 3), round(pt[2], 3))
        if key not in node_by_xyz:
            node_by_xyz[key] = model.add_node(pt[0], pt[1], pt[2],
                                              label=label).id
        return node_by_xyz[key]

    for verts, shape, grade, line in girders_raw:
        if shape and resolve_shape(shape) is None:
            pass  # warning already issued; keep the raw label on the element
        grade_fy_fu(grade)  # validate / warn early
        ids = []
        prev = node_at(verts[0])
        for v in verts[1:]:
            cur = node_at(v)
            elem = model.add_element(prev, cur, role="girder",
                                     midas_type="BEAM",
                                     section=shape or None, material=grade)
            elem.metadata["gdr.line"] = line
            ids.append(elem.id)
            prev = cur
        girder_lines.setdefault(line or f"_{len(girder_lines)}", []).extend(ids)

    # attach bearings to the nearest existing node (their girder-line
    # end/support).  Girder curves break at shape transitions, not at piers,
    # so an intermediate bearing usually lands mid-element: split that
    # element at the bearing station so the restraint sits on a real node.
    for pt, fixity, line in supports_raw:
        nid = _nearest_node(model, pt, tol)
        if nid is None:
            nid = _split_girder_at(model, girder_lines, pt, tol, line)
        if nid is None:
            warnings.warn(f"gdr.kind=support on line {line!r} at {pt} has no "
                          f"girder node or element within {tol} ft; skipping.")
            continue
        dof = FIXITY_DOF.get(fixity)
        if dof is None:
            warnings.warn(f"unknown gdr.fixity {fixity!r}; treating as fixed.")
            dof = FIXITY_DOF["fixed"]
        model.add_restraint(nid, **dof).preset = fixity

    bridge = _build_bridge(model, doc, girder_lines)
    return bridge


def _nearest_node(model, pt, tol):
    best, bd = None, None
    for node in model.nodes.values():
        d = math.dist((node.x, node.y, node.z), pt)
        if bd is None or d < bd:
            best, bd = node.id, d
    return best if (bd is not None and bd <= tol) else None


def _split_girder_at(model, girder_lines, pt, tol, line):
    """Split the girder element whose axis passes within ``tol`` of ``pt``
    into two elements sharing a new node at the projected point; returns the
    new node id (or ``None`` if no element qualifies).

    Elements on the bearing's own ``gdr.line`` are preferred; the split
    preserves section/material/metadata on both halves and keeps the
    ``girder_lines`` chain ordering (so splice placement still walks the
    line end-to-end)."""
    candidates = girder_lines.get(line) or [
        eid for ids in girder_lines.values() for eid in ids]
    best = None  # (distance, element id, projected point)
    for eid in candidates:
        e = model.elements.get(eid)
        if e is None:
            continue
        a, b = model.nodes[e.node_a], model.nodes[e.node_b]
        ax, bx = (a.x, a.y, a.z), (b.x, b.y, b.z)
        ab = tuple(bx[i] - ax[i] for i in range(3))
        len2 = sum(c * c for c in ab)
        if len2 == 0.0:
            continue
        t = sum((pt[i] - ax[i]) * ab[i] for i in range(3)) / len2
        if t <= 0.0 or t >= 1.0:
            continue  # projects onto an end -- _nearest_node already ruled
        proj = tuple(ax[i] + t * ab[i] for i in range(3))
        d = math.dist(proj, pt)
        if d <= tol and (best is None or d < best[0]):
            best = (d, eid, proj)
    if best is None:
        return None

    _, eid, proj = best
    old = model.elements.pop(eid)
    mid = model.add_node(*proj).id
    halves = []
    for na, nb in ((old.node_a, mid), (mid, old.node_b)):
        e = model.add_element(na, nb, role=old.role,
                              member_type=old.member_type,
                              midas_type=old.midas_type,
                              section=old.section, material=old.material)
        e.metadata.update(old.metadata)
        halves.append(e.id)
    for ids in girder_lines.values():
        if eid in ids:
            i = ids.index(eid)
            ids[i:i + 1] = halves
    return mid


def splice_writeback_tags(design) -> dict:
    """Build the ``gdr.status`` / ``gdr.summary`` / ``gdr.checks`` write-back
    tags (stage **G8**) from a
    :class:`~civilpy.structural.aashto.lrfd.bolted_field_splice.SpliceDesign`.

    ``gdr.checks`` is newline-separated ``article|check|actual|allowable|verdict``
    records -- one row per limit state -- the format the C# ``GirderSplice``
    command renders (NG rows red)."""
    def num(v):
        return "-" if v is None else f"{v:.2f}"

    rows = []
    for c in design.checks:
        verdict = "OK" if c.ok else ("NOTICE" if c.advisory else "NG")
        rows.append(f"{c.article}|{c.name}|{num(c.demand)}|"
                    f"{num(c.factored_capacity)}|{verdict}")
    ng = sum(1 for c in design.checks if not c.ok and not c.advisory)
    status = "OK" if design.ok else "NG"
    summary = (f"{design.top_flange.total_bolts} bolts/flange, "
               f"web {design.web.total_bolts}; {len(design.checks)} checks"
               + (f", {ng} NG" if ng else ", all OK"))
    return {GTAG + "status": status, GTAG + "summary": summary,
            GTAG + "checks": "\n".join(rows)}


def _fmt_num(v) -> str:
    """Format an attribute number: fixed 4 decimals (covers sixteenths),
    trailing zeros trimmed, invariant '.' decimal."""
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return s or "0"


def splice_attribute_tags(design, inp=None) -> dict:
    """Build the ``gdr.splice.*`` *smart-node* attribute tags from a
    :class:`~civilpy.structural.aashto.lrfd.bolted_field_splice.SpliceDesign`.

    These ride on the ``gdr.kind=splice`` marker point next to the
    status/summary/checks write-back, so the marker carries the designed
    splice the way a bearing carries its fixity -- readable in Rhino's
    object properties and by the C# ``GirderSplice`` dialog.  All lengths
    are **inches**; bolt counts are **per side of the joint**.

    Marker-level keys: ``bolt_spec``, ``bolt_dia``, ``hole_type``,
    ``hole_dia``, ``layout`` (``inline``; ``staggered`` reserved -- the
    designer lays out straight rows), ``gap`` (girder end gap), ``method``.

    Per-component keys under ``tf.`` / ``bf.`` / ``web.``: ``bolts``,
    ``rows`` x ``cols`` (the per-side grid), ``pitch`` (along the load
    path), ``gage`` (across it), ``edge``, ``end``, and the plate stack --
    ``plate_t`` / ``plate_w`` / ``plate_l`` where ``plate_l`` always runs
    along the girder axis and ``plate_w`` across it (transverse for flange
    plates, vertical for the paired web plates).  Flanges add the two inner
    plates (``inner_t`` / ``inner_w``) and the joint-straddling spacings
    ``pitch_joint`` (flange, longitudinal) / ``gage_web`` (across the web);
    the web adds ``gage_joint`` (its across-the-gap spacing).

    ``inp`` is the :class:`SpliceInput`; it defaults to ``design.spec``
    (attached by ``design_splice``)."""
    from civilpy.structural.aashto.lrfd.bolted_field_splice import _hole_dia

    if inp is None:
        inp = getattr(design, "spec", None)
    if inp is None:
        raise ValueError("splice_attribute_tags needs the SpliceInput -- pass "
                         "inp= or use a SpliceDesign from design_splice() "
                         "(which sets design.spec).")
    b = inp.bolts
    s = GTAG + "splice."
    tags = {
        s + "bolt_spec": b.bolt_type,
        s + "bolt_dia": _fmt_num(b.diameter),
        s + "hole_type": b.hole_type,
        s + "hole_dia": _fmt_num(_hole_dia(b.diameter, b.hole_type)),
        s + "layout": "inline",
        s + "gap": _fmt_num(inp.girder_gap),
        s + "method": inp.method,
    }
    for comp, plates, part in ((design.top_flange, inp.top_plates, "tf"),
                               (design.bottom_flange, inp.bottom_plates, "bf")):
        p = s + part + "."
        cols = comp.extra.get("cols", comp.total_bolts // max(comp.bolt_rows, 1))
        tags.update({
            p + "bolts": str(comp.total_bolts),
            p + "rows": str(comp.bolt_rows),
            p + "cols": str(cols),
            p + "pitch": _fmt_num(comp.pitch),
            p + "pitch_joint": _fmt_num(comp.pitch_groups),
            p + "gage": _fmt_num(comp.gage_bolts),
            p + "gage_web": _fmt_num(comp.gage_groups),
            p + "edge": _fmt_num(comp.edge),
            p + "end": _fmt_num(comp.end),
            p + "plate_t": _fmt_num(comp.plate_thickness),
            p + "plate_w": _fmt_num(comp.plate_width),
            p + "plate_l": _fmt_num(comp.plate_length),
            p + "inner_t": _fmt_num(plates.inner_thickness),
            p + "inner_w": _fmt_num(plates.inner_width),
        })
    web = design.web
    p = s + "web."
    per_row = web.extra.get("per_row", web.total_bolts // max(web.bolt_rows, 1))
    tags.update({
        p + "bolts": str(web.total_bolts),
        p + "rows": str(per_row),               # bolts down each column
        p + "cols": str(web.bolt_rows),         # columns per side of the joint
        p + "pitch": _fmt_num(web.pitch),       # vertical, within a column
        p + "gage": _fmt_num(web.gage_bolts),   # between columns, along girder
        p + "gage_joint": _fmt_num(web.gage_groups),
        p + "edge": _fmt_num(web.edge),
        p + "end": _fmt_num(web.end),
        p + "plate_t": _fmt_num(web.plate_thickness),
        p + "plate_w": _fmt_num(web.plate_length),   # vertical plate height
        p + "plate_l": _fmt_num(web.plate_width),    # run along the girder
    })
    return tags


def _splice_display_geometry(design, inp):
    """Plate boxes and bolt-axis lines for one designed splice, in the local
    marker frame: origin at the marker (girder line = section centroid at the
    splice CL), X along the girder, Y transverse, Z up -- values in **feet**.

    Display only, same contract as the C# cosmetic sections: the deeper
    side's flange faces are used and fill plates are not drawn.  Returns
    ``(boxes, lines)`` -- boxes as ``(x0, x1, y0, y1, z0, z1)``, bolt axes as
    ``((x, y, z), (x, y, z))`` point pairs."""
    left, right = inp.left, inp.right

    def depth(side):
        return (side.web_depth + side.top_flange.thickness
                + side.bottom_flange.thickness)

    side = left if depth(left) >= depth(right) else right
    d = depth(side)
    tw = max(left.web_thickness, right.web_thickness)
    stick = 0.75  # bolt head/nut stick-out on the axis lines, in
    boxes, lines = [], []

    for comp, plates, sgn in ((design.top_flange, inp.top_plates, 1.0),
                              (design.bottom_flange, inp.bottom_plates, -1.0)):
        flange_t = (side.top_flange if sgn > 0 else side.bottom_flange).thickness
        half_l = comp.plate_length / 2.0
        z_face = sgn * d / 2.0                       # outer face of the flange
        # outer plate, full width across the joint
        z0, z1 = sorted((z_face, z_face + sgn * comp.plate_thickness))
        boxes.append((-half_l, half_l, -comp.plate_width / 2.0,
                      comp.plate_width / 2.0, z0, z1))
        # two inner plates against the inside of the flange, astride the web
        z_in = z_face - sgn * flange_t
        z0, z1 = sorted((z_in, z_in - sgn * plates.inner_thickness))
        for sy in (1.0, -1.0):
            y0, y1 = sorted((sy * tw / 2.0,
                             sy * (tw / 2.0 + plates.inner_width)))
            boxes.append((-half_l, half_l, y0, y1, z0, z1))
        # bolt axes through the stack: cols per side x rows across
        cols = comp.extra.get("cols", comp.total_bolts // max(comp.bolt_rows, 1))
        z_a = z_face - sgn * (flange_t + plates.inner_thickness + stick)
        z_b = z_face + sgn * (comp.plate_thickness + stick)
        for sx in (1.0, -1.0):
            for j in range(cols):
                x = sx * (comp.pitch_groups / 2.0 + j * comp.pitch)
                for sy in (1.0, -1.0):
                    for k in range(max(comp.bolt_rows // 2, 1)):
                        y = sy * (comp.gage_groups / 2.0 + k * comp.gage_bolts)
                        lines.append(((x, y, z_a), (x, y, z_b)))

    # paired web plates, centered on the web depth (mid-height of the web,
    # not the centroid -- they differ on unsymmetric sections)
    web = design.web
    z_mid = -d / 2.0 + side.bottom_flange.thickness + side.web_depth / 2.0
    half_l = web.plate_width / 2.0    # ComponentDesign.plate_width = along girder
    half_h = web.plate_length / 2.0   # ComponentDesign.plate_length = height
    for sy in (1.0, -1.0):
        y0, y1 = sorted((sy * tw / 2.0, sy * (tw / 2.0 + web.plate_thickness)))
        boxes.append((-half_l, half_l, y0, y1, z_mid - half_h, z_mid + half_h))
    per_row = web.extra.get("per_row", web.total_bolts // max(web.bolt_rows, 1))
    y_out = tw / 2.0 + web.plate_thickness + stick
    for sx in (1.0, -1.0):
        for c in range(web.bolt_rows):
            x = sx * (web.gage_groups / 2.0 + c * web.gage_bolts)
            for i in range(per_row):
                z = z_mid + (i - (per_row - 1) / 2.0) * web.pitch
                lines.append(((x, -y_out, z), (x, y_out, z)))

    to_ft = 1.0 / 12.0
    boxes = [tuple(v * to_ft for v in b) for b in boxes]
    lines = [tuple(tuple(v * to_ft for v in p) for p in ln) for ln in lines]
    return boxes, lines


def _box_mesh(r3, x0, x1, y0, y1, z0, z1):
    """An axis-aligned closed box mesh (8 vertices, 6 quads)."""
    m = r3.Mesh()
    for z in (z0, z1):
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            m.Vertices.Add(x, y, z)
    for a, b, c, dd in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.Faces.AddFace(a, b, c, dd)
    m.Normals.ComputeNormals()
    m.Compact()
    return m


def _write_splice_display(f, r3, layer_index, point, design, inp):
    """Bake one splice's plate/bolt display geometry (cosmetic by contract:
    no ``gdr.kind``, so Python readers never see it) at the marker point.
    Returns the number of objects added."""
    boxes, lines = _splice_display_geometry(design, inp)
    x0, y0, z0 = point

    def _attr(color):
        a = r3.ObjectAttributes()
        a.LayerIndex = layer_index
        a.ObjectColor = color
        a.ColorSource = r3.ObjectColorSource.ColorFromObject
        return a

    plate_attr = _attr((110, 125, 140, 255))  # steel gray
    bolt_attr = _attr((45, 45, 50, 255))      # near-black bolt axes
    added = 0
    for xa, xb, ya, yb, za, zb in boxes:
        mesh = _box_mesh(r3, x0 + xa, x0 + xb, y0 + ya, y0 + yb,
                         z0 + za, z0 + zb)
        f.Objects.AddMesh(mesh, plate_attr)
        added += 1
    for (ax, ay, az), (bx, by, bz) in lines:
        pl = r3.Polyline()
        pl.Add(x0 + ax, y0 + ay, z0 + az)
        pl.Add(x0 + bx, y0 + by, z0 + bz)
        f.Objects.AddCurve(pl.ToPolylineCurve(), bolt_attr)
        added += 1
    return added


@dataclass
class SpliceMarker:
    """A designed splice to write back: its station point (feet, PLAN), the
    :class:`SpliceDesign`, the ``gdr.line`` it belongs to, and an optional
    persistent ``gdr.id`` (minted if empty, same identity rule as the C#
    authored tags)."""
    point: tuple            # (x, y, z) in feet
    design: object          # SpliceDesign
    line: str = ""
    id: str = ""            # gdr.id GUID; minted on write when empty


def write_splice_results(out_path, markers, *, unit_system=None,
                         display=True):
    """Author ``gdr.kind=splice`` *smart-node* marker points into a new
    ``.3dm`` for the C# ``GirderSplice`` command.

    Each marker carries the G8 check write-back (``gdr.status`` /
    ``gdr.summary`` / ``gdr.checks``), a persistent ``gdr.id``, and -- when
    the design retains its :class:`SpliceInput` (``design.spec``, set by
    ``design_splice``) -- the full ``gdr.splice.*`` attribute set: bolt spec
    and hole size, per-component bolt grids and spacings, and the three
    plate stacks (see :func:`splice_attribute_tags`).  With ``display=True``
    true-scale plate boxes and bolt-axis lines are baked next to each marker
    on the ``Splice Display`` layer; they carry no ``gdr.kind`` so they stay
    invisible to Python readers, and the C# importer carries them across for
    viewing only.

    ``markers`` is a list of :class:`SpliceMarker`; geometry is written in
    ``unit_system`` (default feet).  Returns the number of markers written.
    """
    r3 = _require_rhino3dm()
    f = r3.File3dm()
    # default to feet so points round-trip 1:1 through _unit_to_feet on read
    f.Settings.ModelUnitSystem = unit_system or r3.UnitSystem.Feet
    lay_marker = ensure_layer(f, LAYER_SPLICES)
    lay_display = ensure_layer(f, LAYER_DISPLAY)
    for m in markers:
        attr = r3.ObjectAttributes()
        attr.LayerIndex = lay_marker
        attr.SetUserString(GTAG + "kind", "splice")
        attr.SetUserString(GTAG + "id", m.id or str(uuid.uuid4()))
        if m.line:
            attr.SetUserString(GTAG + "line", str(m.line))
        for k, v in splice_writeback_tags(m.design).items():
            attr.SetUserString(k, v)
        spec = getattr(m.design, "spec", None)
        if spec is not None:
            for k, v in splice_attribute_tags(m.design, spec).items():
                attr.SetUserString(k, v)
        x, y, z = m.point
        f.Objects.AddPoint(r3.Point3d(x, y, z), attr)
        if display and spec is not None:
            _write_splice_display(f, r3, lay_display, m.point, m.design, spec)
    if not f.Write(str(out_path), 7):
        raise IOError(f"could not write splice results to {out_path}")
    return len(markers)


def read_splice_results(path):
    """Read ``gdr.kind=splice`` markers back from a ``.3dm``: a list of dicts
    with ``point`` (feet), ``line``, ``id``, ``status``, ``summary``,
    ``checks`` (parsed into ``[article, check, actual, allowable, verdict]``
    records), and ``attrs`` -- the ``gdr.splice.*`` smart-node attribute set
    with the prefix stripped and numeric values converted to ``float``
    (e.g. ``attrs["tf.bolts"]``, ``attrs["bolt_dia"]``).  Round-trips
    :func:`write_splice_results` and mirrors what C# reads; display geometry
    (no ``gdr.kind``) is ignored by contract."""
    r3 = _require_rhino3dm()
    f = r3.File3dm.Read(str(path))
    if f is None:
        raise FileNotFoundError(f"could not read 3dm file: {path}")
    scale = _unit_to_feet(f)
    sp = GTAG + "splice."
    out = []
    for obj in f.Objects:
        us = dict(obj.Attributes.GetUserStrings() or {})
        if us.get(GTAG + "kind") != "splice":
            continue
        loc = getattr(obj.Geometry, "Location", None)
        pt = ((loc.X * scale, loc.Y * scale, loc.Z * scale)
              if loc is not None else None)
        raw = us.get(GTAG + "checks", "")
        checks = [r.split("|") for r in raw.splitlines() if r]
        attrs = {}
        for k, v in us.items():
            if not k.startswith(sp):
                continue
            try:
                attrs[k[len(sp):]] = float(v)
            except ValueError:
                attrs[k[len(sp):]] = v
        out.append({
            "point": pt, "line": us.get(GTAG + "line", ""),
            "id": us.get(GTAG + "id", ""),
            "status": us.get(GTAG + "status"),
            "summary": us.get(GTAG + "summary"), "checks": checks,
            "attrs": attrs})
    return out


def _build_bridge(model, doc, girder_lines) -> GirderBridge:
    deck_t = _doc_float(doc, "deck_t")
    deck_weff = _doc_float(doc, "deck_weff")
    if deck_t is None or deck_weff is None:
        warnings.warn(
            "girder model is missing gdr.deck_t and/or gdr.deck_weff -- the "
            "composite deck section cannot be built without them; supply the "
            "structural slab thickness (in) and effective width (in), or fall "
            "back to ODOT BDM defaults downstream (G5).")
    return GirderBridge(
        model=model,
        deck_t=deck_t,
        deck_weff=deck_weff,
        deck_fc=_doc_float(doc, "deck_fc", _DECK_DEFAULTS["deck_fc"]),
        ship_max=_doc_float(doc, "ship_max", _DECK_DEFAULTS["ship_max"]),
        bolt_dia=_doc_float(doc, "bolt_dia", _DECK_DEFAULTS["bolt_dia"]),
        bolt_spec=doc.get(GTAG + "bolt_spec") or _DECK_DEFAULTS["bolt_spec"],
        bolt_hole=doc.get(GTAG + "bolt_hole") or _DECK_DEFAULTS["bolt_hole"],
        bolt_class=doc.get(GTAG + "bolt_class") or _DECK_DEFAULTS["bolt_class"],
        girder_lines=girder_lines,
    )
