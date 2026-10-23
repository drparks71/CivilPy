#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""A riveted built-up member as the pieces a shop actually made.

:mod:`civilpy.structural.builtup` turns a plan-sheet spec into the
rectangles of its *bare* section -- web plates, angle legs, cover plates.
That is the section a designer sized, and it is what a stress sheet records.
It is not the member.  The member is that section **plus the lacing that
holds the two webs together, the tie plates that close its ends, and the
rivets through all of it**, and on a truss of this era that additional steel
is not a rounding error: a 2012 rating of a 1930s riveted truss carries a per-member
multiplier on the bare section of 1.06-2.87, median 1.87, covering "lacing,
batten/tie plates, gussets, rivets".

Drawing only the bare section is therefore LOD 300 however finely it is
decomposed -- the fabricated assembly is not represented and cannot be
queried.  This module is the LOD 400 model: every piece is an object with a
size, a length, a position in the member, a catalogue designation where it
has one, and a weight.

Where the values come from
--------------------------
Everything here is meant to be read off the fabrication drawings, and each
value carries a ``source`` saying which.  For the 1930 riveted truss the
module was written against, the shop
``L``-series sheets give a bill per member, e.g. for U11-U12 of span 3::

    2P - 24 x 3/8 x 23-11 1/2        web plates
    4L - 4x4x3/8 x 23-11 1/2         corner angles
    1P - 21 x ... x 3-10             tie plate
    1P - 48 x ... x 3-10             tie plate
    D.L. 2 1/2 x 1/4 ...             double lacing bars

and the title block gives ``RIVETS 1" DIA EXCEPT AS NOTED, HOLES PUNCHED
1 1/8``.  A value that could not be read off a sheet is recorded with a
``source`` that says so, so the model never silently passes off a default as
an as-built dimension.

Angles are matched to the AISC shapes table for their catalogue designation.
Their *area* needs no correction: the sharp-cornered decomposition
``builtup.rects`` uses -- full outstanding leg plus the remaining web leg --
reproduces the catalogue area exactly (L4x4x1/2: 4x0.5 + 3.5x0.5 = 3.75 in^2,
and the table says 3.75), because the fillet and the toe radii very nearly
cancel. What the catalogue adds is the identity and the centroid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from civilpy.structural import builtup

#: Structural steel, lb per foot per square inch of section.
STEEL_LB_PER_FT_IN2 = 490.0 / 144.0


# --------------------------------------------------------------------------- #
# catalogue lookup
# --------------------------------------------------------------------------- #
_ANGLE_CACHE = {}


def angle_designation(leg_a: float, leg_b: float, t: float):
    """``(designation, area_in2, edition)`` for an angle, or ``(None, None,
    None)``.

    Angle sizes are stable across editions, so the oldest edition carrying
    the size is used -- nearest to a 1930 mill order."""
    key = (leg_a, leg_b, t)
    if key in _ANGLE_CACHE:
        return _ANGLE_CACHE[key]
    try:
        import csv
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "res", "aisc_shapes_historic.csv")
        best = None
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("Type") != "L":
                    continue
                d = (row.get("Designation") or "").upper().replace(" ", "")
                want = _angle_label(leg_a, leg_b, t).upper().replace(" ", "")
                if d != want:
                    continue
                try:
                    area = float(row.get("A") or 0.0)
                except ValueError:
                    continue
                cand = (row.get("Designation"), area, row.get("Edition"))
                if best is None or _edition_rank(cand[2]) < _edition_rank(best[2]):
                    best = cand
        _ANGLE_CACHE[key] = best or (None, None, None)
    except Exception:                                # pragma: no cover
        _ANGLE_CACHE[key] = (None, None, None)
    return _ANGLE_CACHE[key]


_EDITION_ORDER = ["ASD5", "ASD6", "ASD7", "ASD8", "ASD9",
                  "LRFD1", "LRFD2", "LRFD3", "13th", "Historic"]


def _edition_rank(ed):
    try:
        return _EDITION_ORDER.index(ed)
    except (ValueError, TypeError):
        return len(_EDITION_ORDER)


def _frac(x: float) -> str:
    """``0.5`` -> ``1/2``, ``0.4375`` -> ``7/16``, ``4.0`` -> ``4``."""
    if abs(x - round(x)) < 1e-9:
        return "%d" % round(x)
    for den in (2, 4, 8, 16, 32):
        num = x * den
        if abs(num - round(num)) < 1e-9:
            n = int(round(num))
            whole, rem = divmod(n, den)
            from math import gcd
            g = gcd(rem, den)
            frac = "%d/%d" % (rem // g, den // g)
            return "%d-%s" % (whole, frac) if whole else frac
    return "%g" % x


def _angle_label(a: float, b: float, t: float) -> str:
    return "L%sX%sX%s" % (_frac(a), _frac(b), _frac(t))


# --------------------------------------------------------------------------- #
# the fabricated pieces
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Piece:
    """One piece of steel in the member.

    ``b_in``/``h_in`` are its rectangle across and through the member
    section, ``y_in``/``z_in`` its centre in that section, and ``length_ft``
    how long it runs.  ``along_ft`` is where it starts along the member (0
    for anything running the full length).  ``normal`` is the section
    direction it is oriented in for pieces that lie in a face rather than
    along the axis -- lacing bars and tie plates."""
    kind: str
    label: str
    b_in: float
    h_in: float
    y_in: float
    z_in: float
    length_ft: float
    along_ft: float = 0.0
    designation: str = ""
    face: str = ""              # "top" / "bottom" / "" for full-length pieces
    angle_deg: float = 0.0      # lacing bar inclination from the member axis
    source: str = ""

    @property
    def area_in2(self) -> float:
        return self.b_in * self.h_in

    @property
    def weight_lb(self) -> float:
        return self.area_in2 * STEEL_LB_PER_FT_IN2 * self.length_ft


@dataclass(frozen=True)
class LacingSpec:
    """The lacing on the open faces of a built-up member.

    ``double`` lacing crosses (an X between each pair of rivet lines);
    single lacing is a zig-zag.  ``inclination_deg`` is measured from the
    member axis."""
    bar_w_in: float
    bar_t_in: float
    double: bool = True
    inclination_deg: float = 45.0
    faces: int = 2
    source: str = ""

    @property
    def label(self) -> str:
        return "PL %s x %s%s" % (_frac(self.bar_w_in), _frac(self.bar_t_in),
                                 " (double)" if self.double else " (single)")


@dataclass(frozen=True)
class TiePlate:
    """A tie / stay / batten plate closing an open face, usually at the ends
    of the member and either side of a connection."""
    width_in: float
    thickness_in: float
    length_ft: float
    face: str = "top"
    at_ft: float = 0.0
    source: str = ""


@dataclass
class LacedMember:
    """A built-up riveted member: the bare section plus what holds it
    together."""
    spec: str
    length_ft: float
    lacing: LacingSpec = None
    tie_plates: tuple = ()
    rivet_dia_in: float = 1.0
    rivet_hole_in: float = 1.125
    source: str = ""

    # -- the bare section --------------------------------------------------
    @property
    def envelope_in(self):
        return builtup.envelope(self.spec)

    def bare_pieces(self) -> list:
        """Web plates, angle legs and cover plates, with catalogue identity
        on the angles."""
        rects, (d, B, tw, angles, covers) = builtup.rects(self.spec)
        labels = builtup.piece_labels(self.spec)
        webs, _covers, ang = builtup.parse(self.spec)
        n_a, la, lb, ta = ang
        desig, _area, _ed = angle_designation(la, lb, ta)
        out = []
        for k, (b, h, y, z) in enumerate(rects):
            name = labels[k] if k < len(labels) else "piece %d" % k
            if "angle" in name:
                kind, label, dn = "angle", _angle_label(la, lb, ta), desig or ""
            elif "cover" in name:
                kind = "cover plate"
                label = "PL %s x %s" % (_frac(_covers[1]), _frac(_covers[2]))
                dn = ""
            else:
                kind = "web plate"
                label = "PL %s x %s" % (_frac(webs[1]), _frac(webs[2]))
                dn = ""
            out.append(Piece(kind, label, b, h, y, z, self.length_ft,
                             designation=dn, source=self.source or "D-sheet spec"))
        return out

    # -- lacing ------------------------------------------------------------
    def lacing_gauge_in(self) -> float:
        """Distance across an open face between the two lacing rivet lines.

        The bars connect the outstanding legs of the corner angles, so the
        gauge is the web spacing less one angle leg either side."""
        _rects, (_d, B, tw, angles, _covers) = builtup.rects(self.spec)
        _n, la, lb, _ta = angles
        leg = min(la, lb)
        return max(B - 2.0 * leg, 2.0)

    def lacing_pieces(self) -> list:
        """One :class:`Piece` per lacing bar.

        Double lacing puts two bars between each pair of rivet points, one
        each way; the longitudinal advance of a bar is
        ``gauge / tan(inclination)``."""
        lac = self.lacing
        if lac is None:
            return []
        _rects, (d, B, _tw, _angles, covers) = builtup.rects(self.spec)
        gauge = self.lacing_gauge_in()
        theta = math.radians(lac.inclination_deg)
        bar_len_ft = (gauge / math.sin(theta)) / 12.0
        advance_in = gauge / math.tan(theta)
        if advance_in <= 0.1:
            return []
        h = d / 2.0                       # the open faces are at +/- d/2
        faces = []
        if lac.faces >= 1:
            faces.append(("bottom", -h))
        if lac.faces >= 2 and not covers:
            faces.append(("top", h))
        elif lac.faces >= 2 and covers:
            # a covered face is closed; the lacing that would have been there
            # is not present
            pass
        out = []
        span_in = self.length_ft * 12.0
        n = int(span_in // advance_in)
        for face, z in faces:
            for i in range(n):
                for sign in ((1, -1) if lac.double else (1,)):
                    out.append(Piece(
                        "lacing bar", lac.label, lac.bar_w_in, lac.bar_t_in,
                        0.0, z, bar_len_ft, along_ft=i * advance_in / 12.0,
                        face=face, angle_deg=lac.inclination_deg * sign,
                        source=lac.source))
        return out

    # -- lacing effect on column strength ------------------------------------
    def connector_spacing_in(self) -> float:
        """Distance ``a`` between lacing connections along one component:
        one bar advance ``gauge / tan(inclination)`` for double lacing (the
        X meets each rivet line every advance), two for single lacing."""
        lac = self.lacing
        if lac is None:
            raise ValueError("no lacing on this member")
        advance = self.lacing_gauge_in() / math.tan(math.radians(lac.inclination_deg))
        return advance if lac.double else 2.0 * advance

    def component_radius_in(self) -> float:
        """Least radius of gyration ``r_i`` of one component -- one web with
        its two angles (the pieces on one side of the section), about its
        own centroidal axis parallel to the depth."""
        rects, _ = builtup.rects(self.spec)
        side = [r for r in rects if r[2] > 0]
        a = sum(b * h for b, h, _, _ in side)
        yc = sum(b * h * y for b, h, y, _ in side) / a
        zc = sum(b * h * z for b, h, _, z in side) / a
        i_y = sum(h * b ** 3 / 12 + b * h * (y - yc) ** 2 for b, h, y, _ in side)
        i_z = sum(b * h ** 3 / 12 + b * h * (z - zc) ** 2 for b, h, _, z in side)
        return math.sqrt(min(i_y, i_z) / a)

    def modified_slenderness(self, kl_over_r: float) -> float:
        """Eq. C6.9.4.3.1-1 for this laced member:
        ``sqrt((KL/r)_o^2 + (a / r_i)^2)`` with ``a`` from the lacing and
        ``r_i`` from one component (see :func:`civilpy.structural.aashto.
        lrfd.steel.modified_slenderness`)."""
        from civilpy.structural.aashto.lrfd.steel import modified_slenderness
        return modified_slenderness(kl_over_r, self.connector_spacing_in(),
                                    self.component_radius_in())

    # -- tie plates --------------------------------------------------------
    def tie_pieces(self) -> list:
        _rects, (d, _B, _tw, _angles, _covers) = builtup.rects(self.spec)
        out = []
        for tp in self.tie_plates:
            z = d / 2.0 if tp.face == "top" else -d / 2.0
            out.append(Piece(
                "tie plate",
                "PL %s x %s" % (_frac(tp.width_in), _frac(tp.thickness_in)),
                tp.width_in, tp.thickness_in, 0.0, z, tp.length_ft,
                along_ft=tp.at_ft, face=tp.face, source=tp.source))
        return out

    # -- the whole member --------------------------------------------------
    def pieces(self) -> list:
        return self.bare_pieces() + self.lacing_pieces() + self.tie_pieces()

    def weight_lb(self) -> float:
        return sum(p.weight_lb for p in self.pieces())

    def bare_weight_lb(self) -> float:
        return sum(p.weight_lb for p in self.bare_pieces())

    def buildup_ratio(self) -> float:
        """Fabricated weight / bare-section weight.

        Comparable with a rating's per-member bump-up *once the gusset,
        splice and rivet steel that the bump-up also carries is accounted for
        separately* -- this ratio covers only what is inside the member."""
        bare = self.bare_weight_lb()
        return self.weight_lb() / bare if bare else 1.0

    def summary(self) -> dict:
        by = {}
        for p in self.pieces():
            rec = by.setdefault(p.kind, {"count": 0, "weight_lb": 0.0,
                                         "label": p.label})
            rec["count"] += 1
            rec["weight_lb"] += p.weight_lb
        for rec in by.values():
            rec["weight_lb"] = round(rec["weight_lb"], 1)
        return {"spec": self.spec, "length_ft": round(self.length_ft, 3),
                "bare_lb": round(self.bare_weight_lb(), 1),
                "fabricated_lb": round(self.weight_lb(), 1),
                "buildup_ratio": round(self.buildup_ratio(), 3),
                "pieces": by}
