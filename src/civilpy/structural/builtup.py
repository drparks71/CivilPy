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
    "2P14x3/8 1P16x3/8 4L3.5x3.5x3/8 W16"   one cover on top only, webs 16 out-to-out
    "2C15x0.52x3.52x0.65 W16.5"        two channels, toes in, laced both faces
    "I15.86x0.407x8.464x0.645"         one rolled I (a truss vertical of the 1930s)
    "1P16x7/16 4L5x3.5x9/16 W16.375"   ONE web plate with four angles back to back:
                                       the built-up I post / diagonal (W = depth
                                       over the angle backs, the gusset in-to-in)

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
when the angles have 6 in or larger legs both ways -- unless the spec
carries it as ``W16``) and which angle leg is outstanding.  The numbered
shop sheets settle both.

Originally written for a 1932 riveted through-truss
against its D-series member sheets.
"""
from __future__ import annotations

import re
from fractions import Fraction

_TOK = re.compile(r"(\d?)([PLCI])([\d/x.]+)")
_WIDTH = re.compile(r"(?<![\w.])W(\d+(?:\.\d+)?)(?![\w.])")
_BRACKET = re.compile(r"\[([^\]]*)\]")


def parse(spec: str):
    """``(webs, covers, angles)`` from a spec string, each ``None`` if absent.

    ``webs`` and ``covers`` are ``(count, width_or_depth, thickness)``;
    ``angles`` is ``(count, leg_a, leg_b, thickness)``.  The first plate
    group is the webs, a second plate group is the cover plates.

    For a channel or rolled-I member (see :func:`parse_ex`) ``webs`` reports
    the channel / I web as ``(count, depth, thickness)`` so callers that
    only want the web keep working; ``angles`` is then ``None``."""
    x = parse_ex(spec)
    if x["channels"]:
        n, d, tw, _bf, _tf = x["channels"]
        return (n, d, tw), x["covers"], None
    if x["rolled_i"]:
        d, tw, _bf, _tf = x["rolled_i"]
        return (1, d, tw), x["covers"], None
    return x["webs"], x["covers"], x["angles"]


def parse_ex(spec: str) -> dict:
    """Everything the shorthand says, as a dict.

    Beyond the plate-and-angle grammar of :func:`parse` the sheets of the
    1930s describe three more things, and the spec can carry them:

    * ``W16`` -- the out-to-out width of the webs (in), when the shop sheet
      gives it; without it :func:`WIDTH` assumes one from the angle size.
    * ``2C15x0.52x3.52x0.65`` -- two channels (depth, web, flange width,
      flange thickness), webs vertical and toes turned in, the laced
      bottom-chord member of the era.  A following plate group
      (``2P12x7/16``) is web reinforcing plates on the channel webs, not
      covers.
    * ``I15.86x0.407x8.464x0.645`` -- one rolled I (depth, web, flange
      width, flange thickness), the verticals and diagonals of a 1930s
      truss; a plate group on it is likewise web reinforcement.

    A cover-plate group with an **odd** count sits on the top face only
    (``1P16x3/8``: one plate on top, the bottom laced); an even count is
    split top and bottom as before.

    Keys: ``webs``, ``covers``, ``angles``, ``channels``, ``rolled_i``,
    ``reinf``, ``width``."""
    out = dict(webs=None, covers=None, angles=None, channels=None,
               rolled_i=None, reinf=None, width=None)
    # bracketed plate groups are web reinforcing plates on any member kind:
    # "[2P12x7/16]" = one 12 x 7/16 plate on each web; several groups allowed
    reinf = []
    for inner in _BRACKET.findall(spec):
        for n, kind, dims in _TOK.findall(inner):
            if kind == "P":
                vals = [float(Fraction(v)) for v in dims.split("x")]
                reinf.append((int(n) if n else 1, vals[0], vals[1]))
    spec = _BRACKET.sub(" ", spec)
    plates = []
    for n, kind, dims in _TOK.findall(spec):
        vals = [float(Fraction(v)) for v in dims.split("x")]
        n = int(n) if n else 1
        if kind == "P":
            plates.append((n, vals[0], vals[1]))
        elif kind == "L":
            out["angles"] = (n, vals[0], vals[1], vals[2])
        elif kind == "C":
            out["channels"] = (n, vals[0], vals[1], vals[2], vals[3])
        else:
            out["rolled_i"] = (vals[0], vals[1], vals[2], vals[3])
    m = _WIDTH.search(spec)
    if m:
        out["width"] = float(m.group(1))
    if out["channels"] or out["rolled_i"]:
        if plates and not reinf:                 # legacy form: first unbracketed group = reinforcement
            reinf.append(plates.pop(0))
        if plates:
            out["covers"] = plates[0]
    else:
        if plates:
            out["webs"] = plates[0]
        if len(plates) > 1:
            out["covers"] = plates[1]
        if out["webs"] is None or out["angles"] is None:
            raise ValueError("spec %r has no web plates and/or no angles" % spec)
    out["reinf"] = reinf or None
    return out


def WIDTH(angles) -> float:
    """Assumed web out-to-out width (in): 20 for 6 in and larger angles, else 18."""
    _, a, b, _ = angles
    return 20.0 if min(a, b) >= 6 else 18.0


def _cover_stacks(covers):
    """``[(z_sign, thickness)]`` per cover stack: an even count splits top
    and bottom, an odd count is all on top."""
    if not covers:
        return []
    n_c, _w, tc = covers
    if n_c % 2 == 0:
        return [(-1, tc * n_c / 2), (1, tc * n_c / 2)]
    return [(1, tc * n_c)]


def rects(spec: str):
    """``(rectangles, meta)`` for a spec.

    Each rectangle is ``(b_y, h_z, y_c, z_c)`` in inches -- width across,
    depth through, and the centre -- one per web stack, per angle leg, and
    per cover-plate stack.  ``meta`` is ``(d, B, tw, angles, covers)``.

    This is the LOD 400 decomposition: draw one solid per rectangle,
    extruded along the member, and the model shows the actual plates and
    angles a rivet gang put together."""
    x = parse_ex(spec)
    covers = x["covers"]
    R = []
    if x["channels"]:
        n_c, d, tw, bf, tf = x["channels"]
        B = x["width"] if x["width"] else 2 * bf + 10.0
        for s in (-1, 1):
            R.append((tw, d, s * (B / 2 - tw / 2), 0.0))
            for sz in (-1, 1):
                R.append((bf - tw, tf, s * (B / 2 - tw - (bf - tw) / 2),
                          sz * (d / 2 - tf / 2)))
        inner = tw
        for n_r, dr, tr in x["reinf"] or ():
            t = tr * n_r / 2
            for s in (-1, 1):
                R.append((t, dr, s * (B / 2 - inner - t / 2), 0.0))
            inner += t
        angles = None
    elif x["rolled_i"]:
        d, tw, bf, tf = x["rolled_i"]
        B = bf
        R.append((tw, d - 2 * tf, 0.0, 0.0))
        for sz in (-1, 1):
            R.append((bf, tf, 0.0, sz * (d / 2 - tf / 2)))
        inner = tw / 2
        for n_r, dr, tr in x["reinf"] or ():
            t = tr * n_r / 2
            for s in (-1, 1):
                R.append((t, dr, s * (inner + t / 2), 0.0))
            inner += t
        angles = None
    elif x["webs"][0] == 1:
        # ONE web plate with four angles: the built-up I of a 1930s truss post or diagonal ("1 PL 16 x 7/16 +
        # 4 L 5 x 3 1/2 x 9/16, 1'-4 3/8 B-B Ls").  The plate stands at the centre, the angles sit back to back
        # on both faces at the top and bottom edges with the LONGER leg outstanding (the flange), and ``W`` -
        # when given - is the depth over the angle backs (the gusset in-to-in), which may exceed the plate depth
        # when the angle heels project past the plate edge.
        _n, d_p, tw = x["webs"]
        angles = x["angles"]
        n_a, a, b, ta = angles
        horiz, vert = max(a, b), min(a, b)
        d = x["width"] if x["width"] else d_p
        B = tw + 2 * horiz
        R.append((tw, d_p, 0.0, 0.0))
        for sy in (-1, 1):
            for sz in (-1, 1):
                # outstanding leg (the flange), its back on the plate face
                R.append((horiz, ta, sy * (tw / 2 + horiz / 2), sz * (d / 2 - ta / 2)))
                # the leg along the plate, below / above the outstanding leg
                R.append((ta, vert - ta, sy * (tw / 2 + ta / 2), sz * (d / 2 - ta - (vert - ta) / 2)))
        if x["reinf"]:
            raise ValueError("reinforcing plates on a single-web built-up I are not supported: %r" % spec)
    else:
        n_w, d, t_w = x["webs"]
        tw = t_w * n_w / 2                  # total web thickness per side
        angles = x["angles"]
        B = x["width"] if x["width"] else WIDTH(angles)
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
        inner = tw                          # reinforcing plates inside the webs, between the angles
        for n_r, dr, tr in x["reinf"] or ():
            t = tr * n_r / 2
            for s in (-1, 1):
                R.append((t, dr, s * (B / 2 - inner - t / 2), 0.0))
            inner += t
    if covers:
        w = covers[1]
        for sz, tcov in _cover_stacks(covers):
            R.append((w, tcov, 0.0, sz * (d / 2 + tcov / 2)))
    return R, (d, B, tw, angles, covers)


def piece_labels(spec: str) -> list[str]:
    """A name per rectangle from :func:`rects`, in the same order -- so a
    BrIM emit can tag each solid with the piece it represents."""
    x = parse_ex(spec)
    covers = x["covers"]
    out = []
    if x["channels"]:
        n_c, d, tw, bf, tf = x["channels"]
        for s in ("S", "N"):
            out.append("channel C%gx%g web %s" % (d, tw, s))
            for sz in ("bottom", "top"):
                out.append("channel C%gx%g %s %s flange" % (d, tw, s, sz))
        for n_r, dr, tr in x["reinf"] or ():
            out += ["web reinforcing plate %gx%g %s (x%d)" % (dr, tr, s, max(1, n_r // 2))
                    for s in ("S", "N")]
    elif x["rolled_i"]:
        d, tw, bf, tf = x["rolled_i"]
        out.append("rolled I %gx%g web" % (d, bf))
        out += ["rolled I %gx%g %s flange" % (d, bf, sz) for sz in ("bottom", "top")]
        for n_r, dr, tr in x["reinf"] or ():
            out += ["web reinforcing plate %gx%g %s (x%d)" % (dr, tr, s, max(1, n_r // 2))
                    for s in ("S", "N")]
    elif x["webs"][0] == 1:
        n_w, d, t_w = x["webs"]
        n_a, a, b, ta = x["angles"]
        out.append("web plate %gx%g" % (d, t_w))
        for sy in ("S", "N"):
            for sz in ("bottom", "top"):
                out.append("angle L%gx%gx%g %s %s outstanding leg" % (a, b, ta, sy, sz))
                out.append("angle L%gx%gx%g %s %s web leg" % (a, b, ta, sy, sz))
    else:
        n_w, d, t_w = x["webs"]
        n_a, a, b, ta = x["angles"]
        out += ["web plate %gx%g (x%d)" % (d, t_w, max(1, n_w // 2)) for _ in range(2)]
        for sy in ("S", "N"):
            for sz in ("bottom", "top"):
                out.append("angle L%gx%gx%g %s %s outstanding leg" % (a, b, ta, sy, sz))
                out.append("angle L%gx%gx%g %s %s web leg" % (a, b, ta, sy, sz))
        for n_r, dr, tr in x["reinf"] or ():
            out += ["web reinforcing plate %gx%g %s (x%d)" % (dr, tr, s, max(1, n_r // 2))
                    for s in ("S", "N")]
    if covers:
        n_c, w, tc = covers
        for sz, tcov in _cover_stacks(covers):
            out.append("cover plate %gx%g %s (x%d)"
                       % (w, tc, "top" if sz > 0 else "bottom", max(1, round(tcov / tc))))
    return out


def envelope(spec: str) -> tuple[float, float]:
    """``(B, H)`` overall width and depth of the member (in) -- the LOD 300
    box that stands in for the built-up section."""
    _R, (d, B, _tw, _angles, covers) = rects(spec)
    h = d + sum(t for _s, t in _cover_stacks(covers))
    return B, h


def properties(spec: str) -> dict:
    """Exact section properties (inches): ``A``, ``Iy`` (strong, about y),
    ``Iz``, ``J``, ``ASy``, ``ASz``, extreme fibres ``cy_*``/``cz_*``,
    first moments ``Qy``/``Qz`` at the neutral axis, and ``H``/``B``."""
    R, (d, B, tw, angles, covers) = rects(spec)
    x = parse_ex(spec)
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

    stacks = _cover_stacks(covers)
    if len(stacks) == 2 and not x["rolled_i"]:
        # covers top and bottom close the box: thin-walled closed section
        tcov = stacks[0][1]
        am = (B - tw) * (d + tcov)
        J = 4 * am ** 2 / (2 * (d + tcov) / tw + 2 * (B - tw) / tcov)
    else:
        J = sum(max(b, h) * min(b, h) ** 3 / 3 for b, h, _, _ in R)
    if x["rolled_i"]:
        asz = tw * (d - 2 * x["rolled_i"][3])
    elif x["webs"] and x["webs"][0] == 1:
        asz = tw * x["webs"][1]             # the one web plate
    else:
        asz = 2 * tw * d
    for n_r, dr, tr in x["reinf"] or ():
        asz += n_r * dr * tr
    asy = sum(b * h for b, h, _, _ in R) - asz
    return {"A": A, "Iy": Iy, "Iz": Iz, "J": J, "ASy": asy, "ASz": asz,
            "cz_p": zmax, "cz_m": zmin, "cy_p": ymax, "cy_m": ymin,
            "Qy": q_above(), "Qz": q_right(),
            "H": d + sum(t for _s, t in stacks),
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
