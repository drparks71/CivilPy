#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""Riveted built-up members: parse a plan-sheet spec into real pieces.

Truss members of the riveted era are not rolled shapes -- they are a
handful of flat plates and angles stitched together with rivets and
lacing, and the old plan sheets describe them in a shorthand that names
every piece::

    "2P24x9/16 4L6x4x3/8"              2 web plates 24 x 9/16, 4 corner angles
    "4P24x1/2 2P16x7/16 4L4x4x1/2"     2 plates per web, 2 cover PLs, 4 angles

This module turns that shorthand back into geometry: :func:`rects` gives
the rectangles the section is actually made of, which is what a LOD 400
model draws (one solid per plate and per angle leg) and what
:func:`properties` integrates for exact section properties.

Section axes (inches, origin at the section centre)::

    y   across the width  (web-to-web; the bridge-transverse direction
        for a truss member, since the webs are parallel to the truss plane)
    z   through the depth (in the truss plane, perpendicular to the member)

* **web plates** -- vertical, depth ``d``, ``n/2`` plates of thickness ``t``
  stacked on each side, outer faces :func:`WIDTH` apart
* **angles** -- one at each of the four corners, heel against the inside
  face of the web at the top/bottom edge; the longer leg is taken as the
  outstanding (horizontal) leg pointing inward and the shorter leg lies
  along the web
* **cover plates** (when present) -- ``n/2`` top and bottom, width ``w``,
  sitting on the angle legs between the webs

Every piece is a rectangle, so area, first and second moments and the
centroid are exact for sharp-cornered angles (the fillet and the rivet
holes are not modelled).  Torsion ignores the lacing: ``J = sum b t^3/3``
for the open section, or the thin-walled closed-section formula when
cover plates close the box top *and* bottom.  Shear areas: ``ASz`` is the
web area, ``ASy`` the angle horizontal legs plus covers.

Two dimensions are assumptions, not sheet values, and they move only the
weak-axis numbers: the web out-to-out width (:func:`WIDTH`, 18 in, or 20 in
when the angles have 6 in or larger legs both ways) and which angle leg is
outstanding.  The numbered shop sheets settle both.

Originally written for a 1932 riveted through-truss
against its D-series member sheets.
"""
from __future__ import annotations

import re
from fractions import Fraction

_TOK = re.compile(r"(\d)([PL])([\d/x]+)")


def parse(spec: str):
    """``(webs, covers, angles)`` from a spec string, each ``None`` if absent.

    ``webs`` and ``covers`` are ``(count, width_or_depth, thickness)``;
    ``angles`` is ``(count, leg_a, leg_b, thickness)``.  The first plate
    group is the webs, a second plate group is the cover plates."""
    webs = covers = angles = None
    for n, kind, dims in _TOK.findall(spec):
        vals = [float(Fraction(v)) for v in dims.split("x")]
        n = int(n)
        if kind == "P":
            if webs is None:
                webs = (n, vals[0], vals[1])
            else:
                covers = (n, vals[0], vals[1])
        else:
            angles = (n, vals[0], vals[1], vals[2])
    if webs is None or angles is None:
        raise ValueError("spec %r has no web plates and/or no angles" % spec)
    return webs, covers, angles


def WIDTH(angles) -> float:
    """Assumed web out-to-out width (in): 20 for 6 in and larger angles, else 18."""
    _, a, b, _ = angles
    return 20.0 if min(a, b) >= 6 else 18.0


def rects(spec: str):
    """``(rectangles, meta)`` for a spec.

    Each rectangle is ``(b_y, h_z, y_c, z_c)`` in inches -- width across,
    depth through, and the centre -- one per web stack, per angle leg, and
    per cover-plate stack.  ``meta`` is ``(d, B, tw, angles, covers)``.

    This is the LOD 400 decomposition: draw one solid per rectangle,
    extruded along the member, and the model shows the actual plates and
    angles a rivet gang put together."""
    webs, covers, angles = parse(spec)
    n_w, d, t_w = webs
    tw = t_w * n_w / 2                  # total web thickness per side
    B = WIDTH(angles)
    R = []
    for s in (-1, 1):
        R.append((tw, d, s * (B / 2 - tw / 2), 0.0))
    n_a, a, b, ta = angles
    horiz, vert = max(a, b), min(a, b)
    yin = B / 2 - tw                    # inside face of web
    for sy in (-1, 1):
        for sz in (-1, 1):
            # horizontal (outstanding) leg, full length, along the top/bottom edge
            R.append((horiz, ta, sy * (yin - horiz / 2), sz * (d / 2 - ta / 2)))
            # vertical leg along the web, below/above the horizontal leg
            R.append((ta, vert - ta, sy * (yin - ta / 2),
                      sz * (d / 2 - ta - (vert - ta) / 2)))
    if covers:
        n_c, w, tc = covers
        tcov = tc * n_c / 2
        for sz in (-1, 1):
            R.append((w, tcov, 0.0, sz * (d / 2 + tcov / 2)))
    return R, (d, B, tw, angles, covers)


def piece_labels(spec: str) -> list[str]:
    """A name per rectangle from :func:`rects`, in the same order -- so a
    BrIM emit can tag each solid with the piece it represents."""
    webs, covers, angles = parse(spec)
    n_w, d, t_w = webs
    n_a, a, b, ta = angles
    horiz, vert = max(a, b), min(a, b)
    out = ["web plate %gx%g (x%d)" % (d, t_w, max(1, n_w // 2)) for _ in range(2)]
    for sy in ("S", "N"):
        for sz in ("bottom", "top"):
            out.append("angle L%gx%gx%g %s %s outstanding leg" % (a, b, ta, sy, sz))
            out.append("angle L%gx%gx%g %s %s web leg" % (a, b, ta, sy, sz))
    if covers:
        n_c, w, tc = covers
        for sz in ("bottom", "top"):
            out.append("cover plate %gx%g %s (x%d)" % (w, tc, sz, max(1, n_c // 2)))
    return out


def envelope(spec: str) -> tuple[float, float]:
    """``(B, H)`` overall width and depth of the member (in) -- the LOD 300
    box that stands in for the built-up section."""
    _R, (d, B, _tw, _angles, covers) = rects(spec)
    h = d + (2 * covers[2] * covers[0] / 2 if covers else 0.0)
    return B, h


def properties(spec: str) -> dict:
    """Exact section properties (inches): ``A``, ``Iy`` (strong, about y),
    ``Iz``, ``J``, ``ASy``, ``ASz``, extreme fibres ``cy_*``/``cz_*``,
    first moments ``Qy``/``Qz`` at the neutral axis, and ``H``/``B``."""
    R, (d, B, tw, angles, covers) = rects(spec)
    A = sum(b * h for b, h, _, _ in R)
    yc = sum(b * h * y for b, h, y, _ in R) / A
    zc = sum(b * h * z for b, h, _, z in R) / A
    Iy = sum(b * h ** 3 / 12 + b * h * (z - zc) ** 2 for b, h, _, z in R)
    Iz = sum(h * b ** 3 / 12 + b * h * (y - yc) ** 2 for b, h, y, _ in R)
    zmax = max(z + h / 2 for _, h, _, z in R) - zc
    zmin = zc - min(z - h / 2 for _, h, _, z in R)
    ymax = max(y + b / 2 for b, _, y, _ in R) - yc
    ymin = yc - min(y - b / 2 for b, _, y, _ in R)

    def q_above():
        q = 0.0
        for b, h, _y, z in R:
            top, bot = z + h / 2, z - h / 2
            if top <= zc:
                continue
            lo = max(bot, zc)
            q += b * (top - lo) * ((top + lo) / 2 - zc)
        return q

    def q_right():
        q = 0.0
        for b, h, y, _z in R:
            rt, lt = y + b / 2, y - b / 2
            if rt <= yc:
                continue
            lo = max(lt, yc)
            q += h * (rt - lo) * ((rt + lo) / 2 - yc)
        return q

    if covers:
        n_c, w, tc = covers
        tcov = tc * n_c / 2
        am = (B - tw) * (d + tcov)
        J = 4 * am ** 2 / (2 * (d + tcov) / tw + 2 * (B - tw) / tcov)
    else:
        J = sum(max(b, h) * min(b, h) ** 3 / 3 for b, h, _, _ in R)
    asz = 2 * tw * d
    asy = sum(b * h for b, h, _, _ in R) - asz
    return {"A": A, "Iy": Iy, "Iz": Iz, "J": J, "ASy": asy, "ASz": asz,
            "cz_p": zmax, "cz_m": zmin, "cy_p": ymax, "cy_m": ymin,
            "Qy": q_above(), "Qz": q_right(),
            "H": d + (2 * covers[2] * covers[0] / 2 if covers else 0),
            "B": B, "tw": tw, "d": d}


def rect_properties(rects) -> dict:
    """``A``, ``Iy`` (about y), ``Iz``, open-section ``J`` and the extents
    ``H`` (along z) / ``B`` (along y) of any set of ``(b_y, h_z, y_c, z_c)``
    rectangles, inches -- the same integration as :func:`properties` for
    sections that are not a plan-sheet spec (a rolled or welded I)."""
    R = [r for r in rects if r[0] > 0 and r[1] > 0]
    A = sum(b * h for b, h, _, _ in R)
    yc = sum(b * h * y for b, h, y, _ in R) / A
    zc = sum(b * h * z for b, h, _, z in R) / A
    Iy = sum(b * h ** 3 / 12 + b * h * (z - zc) ** 2 for b, h, _, z in R)
    Iz = sum(h * b ** 3 / 12 + b * h * (y - yc) ** 2 for b, h, y, _ in R)
    J = sum(max(b, h) * min(b, h) ** 3 / 3 for b, h, _, _ in R)
    H = max(z + h / 2 for _, h, _, z in R) - min(z - h / 2 for _, h, _, z in R)
    B = max(y + b / 2 for b, _, y, _ in R) - min(y - b / 2 for b, _, y, _ in R)
    return {"A": A, "Iy": Iy, "Iz": Iz, "J": J, "H": H, "B": B}


#: Structural-steel unit weight, lb/ft^3.
STEEL_PCF = 490.0


def weight_plf(spec: str) -> float:
    """Steel weight of the bare section, lb/ft (no lacing, rivets or gussets)."""
    return properties(spec)["A"] / 144.0 * STEEL_PCF
