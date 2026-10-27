#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Steel Composite Girder Bridge wizard (All Frame / Composite Steel I) as
pure ``/db`` payload builders for MIDAS Civil NX.

The Civil NX wizard has no API route, so a scripted build has to emit the
same model the wizard would: girders on a curved, superelevated, skewed
layout, transverse dummy deck beams, cross frames hung off rigid links,
bearing elastic links to a pier-cap/column substructure, the deck-pour
construction stages, and the load/lane/vehicle set.  Everything here is a
pure function of :class:`WizardInputs` and returns ``{id: {...}}`` *assign*
dictionaries keyed by table, ready for
``MidasCivil.put_db(table, assign)`` in :data:`TABLE_ORDER`.

What the wizard generates (Civil NX 2025 v2.1, three-span curved tutorial:
5 girders, 60+96+60 ft, R = 450 ft, skews 12/19/29.3/34.3 deg, 4/6/4
bracing divisions, 3 ft deck strips) -- **verified 2026-09-15 by exporting
the wizard's model through the API and diffing it against :func:`build`**
(``tests/structural/data/midas_wizard_three_span_curved.json.gz`` is that
export; the test suite reproduces it node for node and element for
element):

===========================  ======================================================
Wizard object                Here
===========================  ======================================================
Reference lines              **Every** line the wizard draws is a straight line
                             in plan through the reference point at its station,
                             skewed by :func:`skew_at` -- the support skews
                             interpolated linearly along each span.  Deck strips
                             at every ``deck_strip_spacing`` from 0 to the end,
                             bracing lines, splices, 10th points and supports
                             all follow this rule, so lines at the same station
                             coincide (strips at 0/60/156/216 *are* the
                             supports) and nothing else merges.
Girder elements              :func:`girder_lines` -- 89 nodes per girder = 73
(group "Girder", 440,        strips + 11 bracing lines + 4 splices + 8 non-strip
sections *Steel girder-1_1*  10th points + 4 supports - 4 coincidences.  The
/ *-2_1*)                    wizard copies the user's composite sections into
                             "_1" working copies and assigns those; the copies
                             are byte-identical apart from float noise, so this
                             builder assigns the originals.
Transverse deck strips       :func:`deck_strips` -- one element per girder bay,
(group "Dummy Beam", 730,    **three per overhang** (deck edge, half the barrier,
section GirderWizRect-       the barrier, then the fascia girder) = 10 per line;
angle_<id>, "Dummy           "Dummy Beam-D1"/"-D2" split on whether the line's
Material")                   station falls in a negative-moment zone (430/300).
"Dummy Beam2" (168,          :func:`edge_beams` -- a 1 mm-square dummy chain
1 mm square section)         along each deck edge with a node wherever a strip,
                             splice, 10th-point or support line meets the edge
                             (85 nodes / 84 elements per edge).
Cross frames (group          :func:`cross_frames` -- **V pointing down**: one top
"Bracing", 268; 112 truss)   chord per bay, bottom chord split at a mid-bay apex,
                             two truss diagonals from the top-chord ends to the
                             apex.  Chord ends are rigid slaves of the girder
                             node ("GirderRigid Link", 1.25 / 3.375 ft below the
                             deck for the positive section).  The abutment
                             diaphragms (W12x40 / C15x33.9) are TRUSS elements.
                             The group's node list also carries the 20 bearing
                             seats.
Bearings                     :func:`substructure` -- a seat node at the bottom
(20 elastic links)           flange, rigid-slaved to the girder node, then the
                             elastic link ("GirderElastic Link", shear on, local
                             axis at the support line's global angle) down
                             ``link_length`` to the support node.
Substructure (groups         Pier cap along the skewed support line through the
"Substructure" 2 columns,    five support nodes with its tips **on the deck-edge
"Coping" 14 = 7 per cap)     lines**, one zero-length element at the column
                             node (two coincident nodes), column to a fixed base
                             ``pier_height`` below the support node; abutment
                             support nodes fixed 1111110.
Elevation                    :func:`deck_elevation` -- profile on the reference
                             line (the tutorial is a -5 % / -8 % crest over 50 ft
                             from station 0, ``vertical_curve``) plus the bank
                             rotation **about the reference line**.  The few
                             nodes ahead of station 0 on the skewed first
                             abutment sit ~0.2 ft above the g1 tangent -- a
                             wizard quirk left alone.
Tapered Group                NOT created by the wizard (tutorial p.44 step) --
                             :func:`post_wizard_tapered_groups`.
Composite Section for C.S.   Created by the wizard with h = v/s = 0 and ages 0 --
                             analysis refuses until :func:`post_wizard_cscs`
                             rewrites it with the real values.
===========================  ======================================================

Verification checklist status (2026-09-15, live session):

1. Exported and diffed -- done; every difference above was resolved in the
   builder, not the test.  Remaining: the sub-0.25 ft elevation quirk ahead
   of the first abutment.
2. Cross-frame arrangement and rigid-link DOF (111111) -- confirmed.
3. "_1" section copies byte-identical, nothing references the originals --
   confirmed.
4. ``SAVEAS``/tracer behaviour -- not re-checked this session.

Live-verified schema notes are kept with :mod:`civilpy.structural.midas`;
the ones specific to this wizard are in the function docstrings below.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from civilpy.structural.construction_sequence import (
    AnalysisControl,
    BoundaryActivation,
    CompositePart,
    CompositeSection,
    ConstructionSequence,
    ElementActivation,
    ErectionLoad,
    LoadActivation,
    Stage,
)


# ------------------------------------------------------------------ inputs
@dataclass
class GirderPlates:
    """Steel I-girder plates in inches: web ``hw x tw``, top flange
    ``b1 x tf1``, bottom flange ``b2 x tf2`` (composite Steel-I Type1 vSIZE
    order is ``[Hw, tw, B1, tf1, B2, tf2]``)."""
    hw: float = 36.0
    tw: float = 0.5
    b1: float = 14.0
    tf1: float = 0.75
    b2: float = 14.0
    tf2: float = 0.75

    @property
    def depth_in(self) -> float:
        return self.hw + self.tf1 + self.tf2

    def vsize(self, scale: float = 1.0) -> list[float]:
        return [v * scale for v in (self.hw, self.tw, self.b1, self.tf1, self.b2, self.tf2)]


@dataclass
class WizardInputs:
    """The wizard's four tabs.  Lengths in feet unless the name says inches;
    stations are measured along the reference line."""
    # Layout
    spans: Sequence[float] = (60.0, 96.0, 60.0)
    radius: float = 450.0                       # convex: circle centre to the right
    skews_deg: Sequence[float] = (12.0, 19.0, 29.3, 34.3)
    deck_width: float = 30.0
    layout_offset: float = -7.0                 # reference line -> deck centre (negative = left)
    superelevation: float = -0.052              # bank rotation, constant here
    profile: Sequence[tuple[float, float]] = ((0.0, 0.0), (216.0, 0.0))   # (station, elevation) polyline
    # Parabolic vertical curve (g1, g2, length, PVC station, PVC elevation)
    # on the reference line; when set it replaces ``profile``.  The tutorial
    # runs a -5 % to -8 % crest over 50 ft from station 0 (recovered
    # 2026-09-15 from the exported wizard model to <0.03 ft everywhere past
    # the PVC; the few nodes ahead of station 0 on the skewed abutment sit
    # ~0.2 ft higher than the g1 tangent, a wizard quirk not reproduced).
    vertical_curve: tuple[float, float, float, float, float] | None = (-0.05, -0.08, 50.0, 0.0, 0.0)
    # Section
    girder_offsets: Sequence[float] = (-19.0, -13.0, -7.0, -1.0, 5.0)
    deck_thickness_in: float = 8.0
    haunch_in: float = 1.0
    deck_strip_spacing: float = 3.0
    bracing_divisions: Sequence[int] = (4, 6, 4)
    splices: Sequence[float] = (35.0, 80.5, 135.5, 181.0)     # section change stations
    positive_plates: GirderPlates = field(default_factory=GirderPlates)
    negative_plates: GirderPlates = field(default_factory=lambda: GirderPlates(tf1=1.25, tf2=1.625))
    negative_zones: Sequence[tuple[float, float]] = ((35.0, 80.5), (135.5, 181.0))
    gap_top: float = 0.5                        # chord end to top flange, ft
    gap_bottom: float = 0.5
    diaphragm_gap: Sequence[float] = (1.3125, 1.0208)          # abutment 1 (W12x40), abutment 2 (C15x33.9)
    pier_cap_length: float = 30.0
    pier_heights: Sequence[float] = (18.75, 17.25)
    link_length: float = 1.0
    link_stiffness: float = 1.0e10
    # Load
    barrier_widths: Sequence[float] = (1.5, 13.5, 0.0, 13.5, 1.5)   # b1..b5
    wet_concrete_kcf: float = 0.15
    barrier_klf: float = 0.14
    wearing_kcf: float = 0.14
    wearing_thickness: float = 0.26
    lane_centres_from_left_edge: Sequence[float] = (9.5, 21.5)
    impact_pct: int = 33
    # ids
    matl_steel: int = 1
    matl_deck: int = 2
    matl_pier: int = 3
    matl_dummy: int = 4
    sect_chord: int = 1
    sect_brace: int = 2
    sect_girder_pos: int = 3
    sect_girder_neg: int = 4
    sect_cap: int = 5
    sect_column: int = 6
    sect_diaphragm: Sequence[int] = (7, 8)
    sect_strip: int = 9
    sect_edge: int = 10                         # 1 mm square for the deck-edge dummy beams

    @property
    def support_stations(self) -> list[float]:
        s, out = 0.0, [0.0]
        for L in self.spans:
            s += L
            out.append(s)
        return out

    @property
    def deck_edges(self) -> tuple[float, float]:
        c = self.layout_offset
        return c - self.deck_width / 2, c + self.deck_width / 2


# --------------------------------------------------------------- geometry
def _z_ref(w: WizardInputs, s: float) -> float:
    if w.vertical_curve:
        g1, g2, L, s0, z0 = w.vertical_curve
        x = s - s0
        if x <= 0:
            return z0 + g1 * x
        if x < L:
            return z0 + g1 * x + (g2 - g1) / (2 * L) * x * x
        return z0 + g1 * L + (g2 - g1) / 2 * L + g2 * (x - L)
    pts = list(w.profile)
    if s <= pts[0][0]:
        (s0, z0), (s1, z1) = pts[0], pts[1]
    elif s >= pts[-1][0]:
        (s0, z0), (s1, z1) = pts[-2], pts[-1]
    else:
        for (s0, z0), (s1, z1) in zip(pts, pts[1:]):
            if s0 <= s <= s1:
                break
    return z0 + (z1 - z0) * (s - s0) / (s1 - s0)


def deck_elevation(w: WizardInputs, s: float, offset: float) -> float:
    """Deck-top elevation at reference station ``s`` and lateral ``offset``:
    profile grade on the reference line plus the bank rotation **about the
    reference line** (verified 2026-09-15: the wizard puts z = 0.052 x 22 at
    the outer edge of the flat tutorial, i.e. the pivot is offset 0, not the
    deck centre)."""
    return _z_ref(w, s) + w.superelevation * offset


def plan_xy(w: WizardInputs, theta: float, offset: float) -> tuple[float, float]:
    """Plan coordinates on the line at lateral ``offset`` for central angle
    ``theta``.  Convex layout: circle centre at ``(0, -R)``, travel starts at
    the origin heading +x, positive offset (right) is toward the centre."""
    r = w.radius - offset
    return r * math.sin(theta), -w.radius + r * math.cos(theta)


def skew_at(w: WizardInputs, s: float) -> float:
    """Skew (degrees) of the wizard's reference line through station ``s``:
    the support skews, interpolated linearly along each span.  **Every**
    line the wizard draws -- deck strips, bracing lines, splices, 10th
    points, supports -- is a straight line in plan through the reference
    point at ``s`` with this angle (verified 2026-09-15 against the
    exported tutorial model: strip skews run 11.65 deg at station 0 to
    33.3 deg at 216, and the bracing/splice/10th-point lines coincide with
    strips wherever the stations coincide, which only skewed lines do)."""
    S, A = w.support_stations, list(w.skews_deg)
    if s <= S[0]:
        return A[0]
    if s >= S[-1]:
        return A[-1]
    for (s0, a0), (s1, a1) in zip(zip(S, A), zip(S[1:], A[1:])):
        if s0 <= s <= s1:
            return a0 + (a1 - a0) * (s - s0) / (s1 - s0)
    return A[-1]


def line_theta(w: WizardInputs, s: float, offset: float, skew_deg: float | None = None) -> float:
    """Central angle where the skewed straight line through reference
    station ``s`` (angle ``skew_deg``, default :func:`skew_at`) crosses the
    curve at lateral ``offset``.  Positive offset (toward the centre) lands
    *ahead* of ``s`` for positive skew."""
    R = w.radius
    th0 = s / R
    a = math.radians(skew_at(w, s) if skew_deg is None else skew_deg)
    r = R - offset
    t = R * math.cos(a) - math.sqrt(max(R * R * math.cos(a) ** 2 - R * R + r * r, 0.0))
    px, py = plan_xy(w, th0, 0.0)
    qx, qy = px - t * math.sin(th0 - a), py - t * math.cos(th0 - a)
    return math.atan2(qx, qy + R)


def support_theta(w: WizardInputs, k: int, offset: float) -> float:
    """Central angle where skewed support line ``k`` crosses the line at
    ``offset`` (skew rotates the radial line about the reference point)."""
    return line_theta(w, w.support_stations[k], offset, w.skews_deg[k])


def girder_section_at(w: WizardInputs, s: float) -> int:
    return w.sect_girder_neg if any(a <= s < b for a, b in w.negative_zones) else w.sect_girder_pos


def deck_segment(w: WizardInputs, s: float) -> int:
    edges = [-1e9, *w.splices, 1e9]
    for i, (a, b) in enumerate(zip(edges, edges[1:]), 1):
        if a <= s < b:
            return i
    return len(edges) - 1


class _Mesh:
    """Node/element accumulator with tags, so groups can be derived."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.elems: dict[str, dict] = {}
        self.groups: dict[str, dict[str, set]] = defaultdict(lambda: {"N": set(), "E": set()})
        self.tags: dict[tuple, tuple] = {}
        self._n = self._e = 0

    def node(self, x, y, z, tag=None) -> int:
        self._n += 1
        self.nodes[str(self._n)] = {"X": round(x, 6), "Y": round(y, 6), "Z": round(z, 6)}
        if tag:
            self.tags[("N", self._n)] = tag
        return self._n

    def elem(self, n1, n2, sect, matl, etype="BEAM", group=None, tag=None) -> int:
        self._e += 1
        self.elems[str(self._e)] = {"TYPE": etype, "MATL": matl, "SECT": sect, "NODE": [n1, n2], "ANGLE": 0}
        if tag:
            self.tags[("E", self._e)] = tag
        if group:
            self.groups[group]["E"].add(self._e)
            self.groups[group]["N"].update((n1, n2))
        return self._e

    def xyz(self, n) -> tuple[float, float, float]:
        d = self.nodes[str(n)]
        return d["X"], d["Y"], d["Z"]


def reference_stations(w: WizardInputs) -> tuple[list[float], list[float], list[float]]:
    """(deck-strip stations, bracing-line stations, 10th-point stations)."""
    S = w.support_stations
    strips, s = [], 0.0
    while s <= S[-1] + 1e-6:
        strips.append(round(s, 4))
        s += w.deck_strip_spacing
    braces = [round(S[k] + w.spans[k] * j / n, 4) for k, n in enumerate(w.bracing_divisions) for j in range(1, n)]
    tenth = [round(S[k] + w.spans[k] * j / 10, 4) for k in range(len(w.spans)) for j in range(1, 10)]
    return strips, braces, tenth


def girder_lines(w: WizardInputs, m: _Mesh, merge_tol_ft: float = 0.01) -> dict:
    """Girder nodes/elements.  Node keys are ``("S", k)`` for the support
    crossings and ``("L", station)`` for every other reference line (deck
    strips, bracing, splices, 10th points -- all skewed per
    :func:`skew_at`).  A line that lands within ``merge_tol_ft`` of another
    point on a girder is merged into it: the strips at the abutment and pier
    stations *are* the support lines (same pivot, same skew), which is how
    the wizard gets 89 nodes per girder from 73 strips + 11 bracing lines +
    4 splices + 8 non-strip 10th points + 4 supports."""
    strips, braces, tenth = reference_stations(w)
    stations = sorted(set(strips) | set(braces) | set(w.splices) | set(tenth))
    R = w.radius
    gnodes, chains, elems = {}, {}, {}
    for i, o in enumerate(w.girder_offsets):
        pts = {("S", k): support_theta(w, k, o) for k in range(len(w.support_stations))}
        lo, hi = pts[("S", 0)], pts[("S", len(w.support_stations) - 1)]
        tol = merge_tol_ft / (R - o)
        alias = {}
        for st in stations:
            th = line_theta(w, st, o)
            near = [key for key, t in pts.items() if abs(th - t) <= tol]
            if near:
                alias[("L", st)] = near[0]
            elif lo < th < hi:
                pts[("L", st)] = th
        chain = []
        for key, th in sorted(pts.items(), key=lambda kv: kv[1]):
            x, y = plan_xy(w, th, o)
            n = m.node(x, y, deck_elevation(w, th * R, o), ("G", i, key))
            gnodes[(i, key)] = n
            chain.append((th, n))
        for key, target in alias.items():
            gnodes[(i, key)] = gnodes[(i, target)]
        chains[i] = chain
        elems[i] = []
        for (t1, n1), (t2, n2) in zip(chain, chain[1:]):
            smid = (t1 + t2) / 2 * R
            elems[i].append(m.elem(n1, n2, girder_section_at(w, smid), w.matl_steel, group="Girder", tag=("GIRDER", i, smid)))
    return {"nodes": gnodes, "chains": chains, "elems": elems}


def deck_strips(w: WizardInputs, m: _Mesh, g: dict) -> dict:
    """Transverse dummy deck beams, wizard style (verified 2026-09-15): on
    every deck-spacing line (skewed, :func:`skew_at`), one element per
    girder bay and **three per overhang** -- deck edge, half the barrier
    width, the barrier width, then the fascia girder -- so five girders
    give 10 elements per line and 73 lines give 730.  Group "Dummy Beam";
    the pour-stage groups "Dummy Beam-D1" / "Dummy Beam-D2" split on
    whether the line's reference station falls in a negative-moment zone.
    Returns ``{(side, station): edge node}`` for :func:`edge_beams`."""
    strips, _, _ = reference_stations(w)
    left, right = w.deck_edges
    b_left, b_right = w.barrier_widths[0], w.barrier_widths[-1]
    edges = {}
    for st in strips:
        line = [(i, g["nodes"][(i, ("L", st))]) for i in range(len(w.girder_offsets)) if (i, ("L", st)) in g["nodes"]]
        if len(line) < 2:
            continue
        pour = "Dummy Beam-D2" if any(a <= st < b for a, b in w.negative_zones) else "Dummy Beam-D1"

        def strip(n1, n2):
            e = m.elem(n1, n2, w.sect_strip, w.matl_dummy, group="Dummy Beam", tag=("STRIP", st))
            m.groups[pour]["E"].add(e)
            m.groups[pour]["N"].update((n1, n2))

        def at(offset):
            th = line_theta(w, st, offset)
            x, y = plan_xy(w, th, offset)
            return m.node(x, y, deck_elevation(w, th * w.radius, offset), ("DECK", st, offset))

        def overhang(edge, barrier, girder_node, side):
            sign = 1 if side == "left" else -1
            stops = [edge]
            if barrier > 0:
                stops += [edge + sign * barrier / 2, edge + sign * barrier]
            nodes = [at(o) for o in stops]
            edges[(side, st)] = nodes[0]
            chain = nodes + [girder_node] if side == "left" else [girder_node] + nodes[::-1]
            for n1, n2 in zip(chain, chain[1:]):
                strip(n1, n2)

        if line[0][0] == 0:
            overhang(left, b_left, line[0][1], "left")
        for (_, n1), (_, n2) in zip(line, line[1:]):
            strip(n1, n2)
        if line[-1][0] == len(w.girder_offsets) - 1:
            overhang(right, b_right, line[-1][1], "right")
    return edges


def edge_beams(w: WizardInputs, m: _Mesh, edges: dict) -> None:
    """The wizard's "Dummy Beam2" family (verified 2026-09-15): one chain of
    1 mm-square dummy beams along each deck edge, with a node wherever a
    deck strip, splice, 10th-point or support line meets the edge (bracing
    lines stop at the fascia girder and add nothing).  Strip nodes are
    shared with the transverse strips; the other crossings are new nodes.
    For the tutorial that is 85 nodes and 84 elements per edge."""
    strips, _, tenth = reference_stations(w)
    left, right = w.deck_edges
    extra = sorted(set(w.splices) | set(tenth) | set(w.support_stations))
    for side, offset in (("left", left), ("right", right)):
        pts = {}
        for st in strips:
            if (side, st) in edges:
                pts[line_theta(w, st, offset)] = edges[(side, st)]
        thetas = sorted(pts)
        tol = 0.25 / (w.radius - offset)
        for st in extra:
            th = line_theta(w, st, offset)
            if any(abs(th - t) <= tol for t in thetas):
                continue
            x, y = plan_xy(w, th, offset)
            pts[th] = m.node(x, y, deck_elevation(w, th * w.radius, offset), ("EDGE", st, offset))
            thetas.append(th)
        chain = [pts[t] for t in sorted(pts)]
        for n1, n2 in zip(chain, chain[1:]):
            m.elem(n1, n2, w.sect_edge, w.matl_dummy, group="Dummy Beam2", tag=("EDGE", side))


def cross_frames(w: WizardInputs, m: _Mesh, g: dict) -> dict[int, list[int]]:
    """Intermediate V-braces on the bracing lines and at the interior
    supports, single-beam diaphragms at the abutments.  Returns
    ``{girder node: [slave nodes]}`` for the rigid links."""
    _, braces, _ = reference_stations(w)
    rigid: dict[int, list[int]] = defaultdict(list)
    slab = (w.deck_thickness_in + w.haunch_in) / 12
    ng = len(w.girder_offsets)

    def depth_at(s):
        p = w.negative_plates if girder_section_at(w, s) == w.sect_girder_neg else w.positive_plates
        return p.depth_in / 12

    def vbrace(keys, s_ref):
        d = depth_at(s_ref)
        top, bot = [], []
        for i in range(ng):
            n = g["nodes"][(i, keys[i])]
            x, y, z = m.xyz(n)
            t = m.node(x, y, z - slab - w.gap_top)
            b = m.node(x, y, z - slab - d + w.gap_bottom)
            rigid[n] += [t, b]
            top.append(t)
            bot.append(b)
        # verified 2026-09-15: the wizard's V points DOWN -- one top chord
        # per bay, the bottom chord split at a mid-bay apex, and the two
        # truss diagonals run from the top-chord ends down to that apex
        for i in range(ng - 1):
            (x1, y1, z1), (x2, y2, z2) = m.xyz(bot[i]), m.xyz(bot[i + 1])
            apex = m.node((x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2, ("APEX", s_ref, i))
            m.elem(top[i], top[i + 1], w.sect_chord, w.matl_steel, group="Bracing", tag=("XF", s_ref))
            m.elem(bot[i], apex, w.sect_chord, w.matl_steel, group="Bracing", tag=("XF", s_ref))
            m.elem(apex, bot[i + 1], w.sect_chord, w.matl_steel, group="Bracing", tag=("XF", s_ref))
            m.elem(top[i], apex, w.sect_brace, w.matl_steel, "TRUSS", group="Bracing", tag=("XF", s_ref))
            m.elem(top[i + 1], apex, w.sect_brace, w.matl_steel, "TRUSS", group="Bracing", tag=("XF", s_ref))

    def diaphragm(keys, sect, gap):
        ns = []
        for i in range(ng):
            n = g["nodes"][(i, keys[i])]
            x, y, z = m.xyz(n)
            dn = m.node(x, y, z - slab - gap)
            rigid[n].append(dn)
            ns.append(dn)
        for i in range(ng - 1):
            m.elem(ns[i], ns[i + 1], sect, w.matl_steel, "TRUSS", group="Bracing", tag=("DIA", sect))

    for st in braces:
        vbrace([("L", st)] * ng, st)
    last = len(w.support_stations) - 1
    diaphragm([("S", 0)] * ng, w.sect_diaphragm[0], w.diaphragm_gap[0])
    for k in range(1, last):
        vbrace([("S", k)] * ng, w.support_stations[k])
    diaphragm([("S", last)] * ng, w.sect_diaphragm[1], w.diaphragm_gap[1])
    return dict(rigid)


def substructure(w: WizardInputs, m: _Mesh, g: dict) -> dict:
    """Bearing seats, abutment supports, pier caps and columns.

    Seats sit ``link_length`` below the bottom flange under each girder
    support node; abutment seats are fixed (1111110).  The pier cap runs
    along the skew line through its five seats with ``(cap_length - width)/2``
    tips, **seven elements per cap including a zero-length one at the column
    node** (the wizard's artifact -- the cap chain and the column share the
    column-top position through two coincident nodes); column to a fixed
    base ``pier_height`` below.  Returns links, supports and the cap element
    lists for the tapered groups."""
    slab = (w.deck_thickness_in + w.haunch_in) / 12
    elinks, cons, caps, col_base, seats, rigid_seats = {}, {}, {}, {}, {}, {}
    ng, last = len(w.girder_offsets), len(w.support_stations) - 1
    centre_i = min(range(ng), key=lambda i: abs(w.girder_offsets[i] - w.layout_offset))
    for k in range(last + 1):
        p = w.negative_plates if girder_section_at(w, w.support_stations[k]) == w.sect_girder_neg else w.positive_plates
        d = p.depth_in / 12
        bb = []
        # the wizard's bearing (verified 2026-09-15): a seat node at the
        # bottom flange, rigid-linked to the girder node, and the elastic
        # link from that seat down ``link_length`` to the support node; the
        # link's local axis follows the skewed support line in plan
        angle = math.degrees(w.support_stations[k] / w.radius) - w.skews_deg[k]
        for i in range(ng):
            n = g["nodes"][(i, ("S", k))]
            x, y, z = m.xyz(n)
            seat = m.node(x, y, z - slab - d, ("SEAT", k, i))
            rigid_seats.setdefault(n, []).append(seat)
            b = m.node(x, y, z - slab - d - w.link_length, ("BRG", k, i))
            bb.append(b)
            K = w.link_stiffness
            elinks[str(len(elinks) + 1)] = {"NODE": [seat, b], "LINK": "GEN", "ANGLE": angle, "R_S": [False] * 6,
                                            "SDR": [K, K, K, 0, 0, 0], "bSHEAR": True, "DR": [0.5, 0.5],
                                            "BNGR_NAME": "GirderElastic Link"}
        seats[k] = bb
        if k in (0, last):
            for b in bb:
                cons[str(b)] = {"ITEMS": [{"ID": 1, "GROUP_NAME": "SubstructureSupport", "CONSTRAINT": "1111110"}]}
            continue
        # the tips sit on the deck-edge lines (verified 2026-09-15: the
        # wizard's cap reaches offsets -22 / +8, the deck edges, not
        # (cap_length - seat spread) / 2 past the fascia seats); z follows
        # the seat line extrapolated
        (x1, y1, z1), (x5, y5, z5) = m.xyz(bb[0]), m.xyz(bb[-1])
        o1, o5 = w.girder_offsets[0], w.girder_offsets[-1]
        left, right = w.deck_edges

        def tip(offset):
            th = support_theta(w, k, offset)
            x, y = plan_xy(w, th, offset)
            z = z1 + (z5 - z1) * (offset - o1) / (o5 - o1)
            return m.node(x, y, z, ("CAPTIP", k, offset))
        tip_l, tip_r = tip(left), tip(right)
        xc, yc, zc = m.xyz(bb[centre_i])
        col_top = m.node(xc, yc, zc)                          # coincident with the seat (wizard artifact)
        chain = [tip_l, *bb[:centre_i + 1], col_top, *bb[centre_i + 1:], tip_r]
        caps[k] = [m.elem(a, b, w.sect_cap, w.matl_pier, group="Coping", tag=("CAP", k)) for a, b in zip(chain, chain[1:])]
        base = m.node(xc, yc, zc - w.pier_heights[k - 1], ("COLBASE", k))
        m.elem(base, col_top, w.sect_column, w.matl_pier, group="Substructure", tag=("COL", k))
        cons[str(base)] = {"ITEMS": [{"ID": 1, "GROUP_NAME": "SubstructureSupport", "CONSTRAINT": "1111110"}]}
        col_base[k] = base
    for k, bb in seats.items():
        m.groups["Substructure" if k in (0, last) else "Coping"]["N"].update(bb)
    for k in (0, last):
        for i in range(ng):
            m.groups["Substructure"]["N"].update(rigid_seats[g["nodes"][(i, ("S", k))]])
    return {"ELNK": elinks, "CONS": cons, "caps": caps, "col_base": col_base, "seats": seats,
            "rigid_seats": rigid_seats}


def tenth_point_groups(w: WizardInputs, m: _Mesh, g: dict) -> dict[str, dict]:
    """The wizard's ten "10th Point Girder-n-i/j" output groups: for every
    girder, the elements whose i-end (or j-end) sits on a 10th-point line.
    Returns ``{name: {"N": set, "E": set}}``."""
    _, _, tenth = reference_stations(w)
    keys = {("L", st) for st in tenth} | {("S", k) for k in range(len(w.support_stations))}
    out = {}
    for i, chain in g["chains"].items():
        marks = {n for (gi, key), n in g["nodes"].items() if gi == i and key in keys}
        ei, ej = set(), set()
        for e in g["elems"][i]:
            n1, n2 = m.elems[str(e)]["NODE"]
            if n1 in marks:
                ei.add(e)
            if n2 in marks:
                ej.add(e)
        out[f"10th Point Girder-{i + 1}-i"] = {"E": ei, "N": {n for e in ei for n in m.elems[str(e)]["NODE"]}}
        out[f"10th Point Girder-{i + 1}-j"] = {"E": ej, "N": {n for e in ej for n in m.elems[str(e)]["NODE"]}}
    return out


# ------------------------------------------------------------- properties
def property_tables(w: WizardInputs, *, fc_deck_psi=4000.0, fc_pier_psi=3500.0, length_unit_ft=True) -> dict:
    """MATL/TDMT/TDME/TMAT/SECT for the tutorial set.  ``length_unit_ft``
    scales the inch inputs to the model unit; pass False to push the
    property tables while the session is in lbf/in as the guide does.

    Live-verified strings: ``ASTM(S)``/``A572-50``, ``ASTM(RC)``/``Grade
    C4000``; DB sections ``AISC``+``L4x4x5/8``, ``AISC10(US)``+``W12X40``;
    the TD-material link table is ``TMAT``; tapered user sections need
    ``TYPE`` 2 (``TYPE`` 3 is stored as calculated properties and the solver
    then refuses tapered groups); ``OFFSET_PT`` ``"CT"`` = centre-top."""
    L = 1 / 12 if length_unit_ft else 1.0            # inch -> model length
    F = 144.0 if length_unit_ft else 1.0             # psi  -> model stress (ksf via /1000 below)
    Ec_psi = 33000 * 0.145 ** 1.5 * math.sqrt(fc_deck_psi / 1000) * 1000
    E_dummy = Ec_psi * F / (1000 if length_unit_ft else 1)   # ksf or psi
    fc_d = fc_deck_psi * F / (1000 if length_unit_ft else 1)
    fc_p = fc_pier_psi * F / (1000 if length_unit_ft else 1)
    matl = {
        str(w.matl_steel): {"TYPE": "STEEL", "NAME": "A572-50", "DAMP_RAT": 0.02,
                            "PARAM": [{"P_TYPE": 1, "STANDARD": "ASTM(S)", "CODE": "", "DB": "A572-50"}]},
        str(w.matl_deck): {"TYPE": "CONC", "NAME": "Grade C4000", "DAMP_RAT": 0.05,
                           "PARAM": [{"P_TYPE": 1, "STANDARD": "ASTM(RC)", "CODE": "", "DB": "Grade C4000"}]},
        str(w.matl_pier): {"TYPE": "CONC", "NAME": "Grade C3500", "DAMP_RAT": 0.05,
                           "PARAM": [{"P_TYPE": 1, "STANDARD": "ASTM(RC)", "CODE": "", "DB": "Grade C3500"}]},
        str(w.matl_dummy): {"TYPE": "USER", "NAME": "Dummy Material", "DAMP_RAT": 0.05, "bMASS_DENS": False,
                            "PARAM": [{"P_TYPE": 2, "ELAST": E_dummy, "POISN": 0.2, "THERMAL": 5.5e-6, "DEN": 0.0, "MASS": 0.0}]},
    }
    tdmt = {"1": {"NAME": "C4000 C&S", "CODE": "AASHTO", "STR": fc_d, "HU": 70, "VOL": 1.0 * L, "AGE": 3, "bEXPOSE": False},
            "2": {"NAME": "C3500 C&S", "CODE": "AASHTO", "STR": fc_p, "HU": 70, "VOL": 1.0 * L, "AGE": 3, "bEXPOSE": False}}
    tdme = {"1": {"NAME": "C4000 Comp", "TYPE": "CODE", "CODENAME": "ACI", "STRENGTH": fc_d, "A": 4, "B": 0.85},
            "2": {"NAME": "C3500 Comp", "TYPE": "CODE", "CODENAME": "ACI", "STRENGTH": fc_p, "A": 4, "B": 0.85}}
    tmat = {str(w.matl_deck): {"TDMT_NAME": "C4000 C&S", "TDME_NAME": "C4000 Comp"},
            str(w.matl_pier): {"TDMT_NAME": "C3500 C&S", "TDME_NAME": "C3500 Comp"}}

    def before(shape, **kw):
        d = {"OFFSET_PT": "CC", "OFFSET_CENTER": 0, "USER_OFFSET_REF": 0, "HORZ_OFFSET_OPT": 0,
             "USERDEF_OFFSET_YI": 0, "VERT_OFFSET_OPT": 0, "USERDEF_OFFSET_ZI": 0,
             "USE_SHEAR_DEFORM": True, "USE_WARPING_EFFECT": False, "SHAPE": shape}
        d.update(kw)
        return d

    def db(name, shape, dbname, sname):
        return {"SECTTYPE": "DBUSER", "SECT_NAME": name,
                "SECT_BEFORE": before(shape, DATATYPE=1, SECT_I={"DB_NAME": dbname, "SECT_NAME": sname})}

    stiff = {"POSITION": 0, "REFERENCE_OF_D": 0, "STIFF_CNT": [2, 2, 0, 0],
             "STIFF_SHAPE": [{"NAME": "Long Stiffener", "SHAPE_TYPE": 0, "SIZE": [3.6 * L, 0.9 * L, 0, 0, 0, 0, 0, 0]}],
             "STIFF_LEFT": [{"SPACING": 12 * L, "SHAPE": 0, "USE_CALC": False}] * 2,
             "STIFF_RIGHT": [{"SPACING": 12 * L, "SHAPE": 0, "USE_CALC": False}] * 2}

    def composite(name, plates: GirderPlates):
        return {"SECTTYPE": "COMPOSITE", "SECT_NAME": name,
                "SECT_BEFORE": dict(before("I", OFFSET_PT="CT"), SECT_I={"vSIZE": plates.vsize(L), "STIFFENER": stiff},
                                    MATL_ELAST=29.0e6 / Ec_psi, MATL_DENS=0.490 / 0.150, MATL_POIS_S=0.3,
                                    MATL_POIS_C=0.2, MATL_THERMAL=1.3, USE_MULTI_ELAST=False,
                                    LONGTERM_ESEC=0, SHRINK_ESEC=0),
                "SECT_AFTER": {"SLAB": [72 * L, w.deck_thickness_in * L, w.haunch_in * L]}}

    sect = {
        str(w.sect_chord): db("L4x4x5/8", "L", "AISC", "L4x4x5/8"),
        str(w.sect_brace): db("L4x4x1/2", "L", "AISC", "L4x4x1/2"),
        str(w.sect_girder_pos): composite("Steel girder-1", w.positive_plates),
        str(w.sect_girder_neg): composite("Steel girder-2", w.negative_plates),
        str(w.sect_cap): {"SECTTYPE": "TAPERED", "SECT_NAME": "Pier cap",
                          "SECT_BEFORE": dict(before("SB", OFFSET_PT="CT", USER_OFFSET_REF=1), USERDEF_OFFSET_YJ=0,
                                              USERDEF_OFFSET_ZJ=0, TYPE=2,
                                              SECT_I={"vSIZE": [48 * L, 54 * L, 0, 0, 0, 0, 0, 0]},
                                              SECT_J={"vSIZE": [75 * L, 54 * L, 0, 0, 0, 0, 0, 0]}, Y_VAR=1, Z_VAR=1)},
        str(w.sect_column): {"SECTTYPE": "DBUSER", "SECT_NAME": "Pier",
                             "SECT_BEFORE": before("SB", DATATYPE=2, SECT_I={"vSIZE": [48 * L, 78 * L, 0, 0, 0, 0, 0, 0, 0, 0]})},
        str(w.sect_diaphragm[0]): db("W12x40", "H", "AISC10(US)", "W12X40"),
        str(w.sect_diaphragm[1]): db("C15x33.9", "C", "AISC10(US)", "C15X33.9"),
        str(w.sect_strip): {"SECTTYPE": "DBUSER", "SECT_NAME": f"GirderWizRectangle_{w.sect_strip}",
                            "SECT_BEFORE": before("SB", OFFSET_PT="CT", DATATYPE=2,
                                                  SECT_I={"vSIZE": [w.deck_thickness_in * L, w.deck_strip_spacing * 12 * L,
                                                                    0, 0, 0, 0, 0, 0, 0, 0]})},
        # deck-edge dummy beams: a 1 mm square (the wizard's exact value)
        str(w.sect_edge): {"SECTTYPE": "DBUSER", "SECT_NAME": f"GirderWizRectangle_{w.sect_edge}",
                           "SECT_BEFORE": before("SB", OFFSET_PT="CT", DATATYPE=2,
                                                 SECT_I={"vSIZE": [0.0032808398950131224 * (12 * L),
                                                                   0.0032808398950131224 * (12 * L), 0, 0, 0, 0, 0, 0, 0, 0]})},
    }
    return {"MATL": matl, "TDMT": tdmt, "TDME": tdme, "TMAT": tmat, "SECT": sect}


# ------------------------------------------------------------------ loads
def load_tables(w: WizardInputs, m: _Mesh, g: dict) -> dict:
    """Static cases / groups / self weight / beam loads.  Wet concrete =
    deck thickness x tributary width (equal to all girders), barrier on the
    exterior girders, wearing surface by roadway tributary width."""
    stld = {"1": {"NAME": "Self Weight", "TYPE": "D", "DESC": ""},
            "2": {"NAME": "Wet Concrete", "TYPE": "D", "DESC": ""},
            "3": {"NAME": "Barrier", "TYPE": "DC", "DESC": ""},
            "4": {"NAME": "Wearing Surface", "TYPE": "DW", "DESC": ""}}
    ldgr = {str(i + 1): {"NAME": n} for i, n in enumerate(["SW", "WetConc D1", "WetConc D2", "DC2", "DW"])}
    bodf = {"1": {"LCNAME": "Self Weight", "GROUP_NAME": "SW", "FV": [0, 0, -1]}}
    offs = list(w.girder_offsets)
    spacing = (offs[-1] - offs[0]) / (len(offs) - 1)
    w_wet = w.wet_concrete_kcf * w.deck_thickness_in / 12 * spacing
    left, right = w.deck_edges
    road_l, road_r = left + w.barrier_widths[0], right - w.barrier_widths[-1]
    trib = []
    for i, o in enumerate(offs):
        lo = road_l if i == 0 else (offs[i - 1] + o) / 2
        hi = road_r if i == len(offs) - 1 else (o + offs[i + 1]) / 2
        trib.append(hi - lo)
    w_ws = [w.wearing_kcf * w.wearing_thickness * t for t in trib]

    def item(i, lc, grp, q):
        return {"ID": i, "LCNAME": lc, "GROUP_NAME": grp, "CMD": "BEAM", "TYPE": "UNILOAD", "DIRECTION": "GZ",
                "USE_PROJECTION": False, "USE_ECCEN": False, "D": [0, 1, 0, 0], "P": [-q, -q, 0, 0]}

    bmld = {}
    for i, elems in g["elems"].items():
        for e in elems:
            smid = m.tags[("E", e)][2]
            grp = "WetConc D2" if girder_section_at(w, smid) == w.sect_girder_neg else "WetConc D1"
            items = [item(1, "Wet Concrete", grp, w_wet), item(2, "Wearing Surface", "DW", w_ws[i])]
            if i in (0, len(offs) - 1):
                items.append(item(3, "Barrier", "DC2", w.barrier_klf))
            bmld[str(e)] = {"ITEMS": items}
    return {"STLD": stld, "LDGR": ldgr, "BODF": bodf, "BMLD": bmld}


def moving_load_tables(w: WizardInputs, g: dict, sub: dict) -> dict:
    """AASHTO LRFD HL-93 (truck + tandem, independent), two line lanes riding
    the girders nearest the lane centres (ECC in local y, positive left),
    influence-line control, reaction nodes at the column bases.

    Live: LLAN items need ``CENT_F`` in (0, 1); ``MLSP`` (lane support
    negative moment) rejects every key form on 2025 v2.1 -- GUI step."""
    left, _ = w.deck_edges
    offs = list(w.girder_offsets)
    llan = {}
    for j, d in enumerate(w.lane_centres_from_left_edge, 1):
        centre = left + d
        gi = min(range(len(offs)), key=lambda i: abs(offs[i] - centre))
        ecc = -(centre - offs[gi])
        llan[str(j)] = {"COMMON": {"LL_NAME": f"Lane{j}", "LOAD_DIST": "LANE", "GROUP_NAME": "", "SKEW_START": 0,
                                   "SKEW_END": 0, "MOVING": "BOTH", "WHEEL_SPACE": 6.0, "WIDTH": 12.0,
                                   "OPT_AUTO_LANE": False, "ALLOW_WIDTH": 12.0},
                        "LANE_ITEMS": [{"ELEM": e, "ECC": round(ecc, 3), "SPAN_START": False, "CENT_F": 0.5}
                                       for e in g["elems"][gi]]}
    veh = lambda n: {"MVLD_CODE": 2, "VEHICLE_LOAD_NAME": n, "VEHICLE_LOAD_NUM": 1, "VEHICLE_TYPE_NAME": n,
                     "STANDARD_CODE": "AASHTO-LRFD", "VEH_DEFAULT": {"DYN_LOAD_ALLOWANCE": w.impact_pct, "CENT_F": False}}
    lanes = [f"Lane{j}" for j in range(1, len(llan) + 1)]
    subs = [{"VEHICLE_TYPE": "VL", "VEHICLE_NAME": v, "SCALE_FACTOR": 1, "MIN_LOADED_LANE": 0,
             "MAX_LOADED_LANE": len(lanes), "LANE_NAMES": lanes} for v in ("HL-93TDM", "HL-93TRK")]
    return {"MVCD": {"1": {"CODE": "AASHTO LRFD"}},
            "MVHL": {"1": veh("HL-93TDM"), "2": veh("HL-93TRK")},
            "LLAN": llan,
            "MVLD": {"1": {"LCNAME": "MLC", "DESC": "", "TYPE": 0,
                           "DEFAULT": {"SCALE_FACTORS": [1.2, 1.0, 0.85, 0.65, 0.65, 0.65], "COMB_OPTION": "INDEPENDENT",
                                       "LANE_FACTOR_TYPE": 1, "SUB_LOAD_DATAS": subs}}},
            "MVCT": {"1": {"METHOD": "EXACT", "POINT": "INF", "iIGP": 0, "iIGPN": 3, "PLATE": "NODAL", "bSTRCALC": True,
                           "bCONCURRENT": True, "bCONCLINK": True, "FRAME": "AXIAL", "bCSTRCALC": True,
                           "bREAC": True, "bRG": False, "RGN": "", "bDISP": True, "bDG": False, "DGN": "",
                           "bFM": True, "bFG": False, "FGN": "", "bL": True, "bLG": False, "LGN": ""}},
            "MLSR": {str(n): {"NODE": 0} for n in sub["col_base"].values()}}


# ------------------------------------------------------ construction stages
STAGE_DURATIONS = (("Stage1", 10), ("Stage2", 10), ("Stage3-1", 10), ("Stage3-2", 0),
                   ("Stage3-3", 10), ("Stage3-4", 0), ("Stage4", 10), ("Stage5", 10000))


def wizard_sequence() -> ConstructionSequence:
    """The wizard's stages as a :class:`ConstructionSequence`: substructure
    first, girders + bracing with the bearings at DEFORMED position,
    positive-zone pour as load then composite, negative-zone pour then
    composite, after-composite loads, long-term.  Erection Load 1 = DC after
    (Barrier), Erection Load 2 = DW (Wearing Surface); accumulative,
    creep+shrinkage with strength variation.

    Stage1 activates ``"SubstructureSupport"`` -- the group the ``CONS`` rows
    and ``BNGR`` carry.  Until 2026-10-26 it named ``"Support"``, a group the
    model does not have, which the sequence validation now catches."""
    pour = (("Stage3-1", "Stage3-2", "WetConc D1", "Dummy Beam-D1"),
            ("Stage3-3", "Stage3-4", "WetConc D2", "Dummy Beam-D2"))
    days = dict(STAGE_DURATIONS)
    stages = [
        Stage("Stage1", days["Stage1"],
              activate=[ElementActivation("Substructure", 28), ElementActivation("Coping", 28)],
              boundaries=[BoundaryActivation("SubstructureSupport", "ORIGINAL")], loads=[LoadActivation("SW")]),
        Stage("Stage2", days["Stage2"],
              activate=[ElementActivation("Girder", 0), ElementActivation("Bracing", 0)],
              boundaries=[BoundaryActivation("GirderElastic Link", "DEFORMED"),
                          BoundaryActivation("GirderRigid Link", "DEFORMED")]),
    ]
    for wet_stage, hard_stage, load, deck in pour:
        stages.append(Stage(wet_stage, days[wet_stage], loads=[LoadActivation(load)]))
        stages.append(Stage(hard_stage, days[hard_stage], activate=[ElementActivation(deck, 1)],
                            remove_loads=[LoadActivation(load)]))
    stages += [Stage("Stage4", days["Stage4"], loads=[LoadActivation("DC2"), LoadActivation("DW")]),
               Stage("Stage5", days["Stage5"])]
    control = AnalysisControl(erection_loads=[ErectionLoad("Erection Load 1", "DC", ("Barrier",)),
                                              ErectionLoad("Erection Load 2", "DW", ("Wearing Surface",))])
    return ConstructionSequence(stages, boundary_groups=["SubstructureSupport", "GirderElastic Link",
                                                         "GirderRigid Link"], control=control)


def construction_stages() -> dict:
    """BNGR/STAG/STCT for :func:`wizard_sequence`."""
    return wizard_sequence().to_midas()


# ------------------------------------------------ post-wizard tutorial steps
def post_wizard_cscs(w: WizardInputs, *, pos_section: int, neg_section: int, deck_material: int | None = None,
                     slab_h: float | None = None, steel_h: float = 0.05) -> dict:
    """Composite Section for Construction Stage (tutorial p.59).  The wizard
    creates the two rows with ``PARTINFO_H = PARTINFO_VS = 0`` and ages 0 and
    the solver then stops with *"v/s for each Part ... must be greater than
    0"*; this is the ``CSCS`` body with element age 1 d, material age 28 d
    and h = v/s (slab default 2A/u of ``72 x t`` in, model length unit ft).
    ``TYPE`` ``"NORMAL"`` is what the wizard writes."""
    t = w.deck_thickness_in
    h_slab = slab_h if slab_h is not None else (2 * 72 * t / (2 * (72 + t))) / 12
    mat = str(deck_material or w.matl_deck)

    def parts(stage):
        return [CompositePart(1, "ELEM", age=1, h=steel_h, vs=steel_h),
                CompositePart(2, "MATL", age=28, h=h_slab, vs=h_slab, material=mat, composite_stage=stage)]

    return {"1": CompositeSection(pos_section, "Stage2", parts("Stage3-2")).to_midas(),
            "2": CompositeSection(neg_section, "Stage2", parts("Stage3-4")).to_midas()}


def post_wizard_tapered_groups(cap_elements: dict[int, list[int]]) -> dict:
    """Tapered Group per pier cap (tutorial p.44): one linear/linear group over
    the whole cap chain.  The wizard does not create these, so without them
    every cap element tapers 48->75 on its own (sawtooth)."""
    return {str(i): {"NAME": f"Pier Cap - {i}", "ELEMLIST": list(els), "ZVAR": "LINEAR", "YVAR": "LINEAR"}
            for i, (k, els) in enumerate(sorted(cap_elements.items()), 1)}


def span_information(girder_chains: dict[int, list[int]], girder_elems: dict[int, list[int]],
                     support_nodes: Iterable[int], elems: dict[str, dict]) -> dict:
    """Composite Option > Span Information (tutorial p.47): one entry per girder
    per span, elements between consecutive support nodes, first element
    Support = I (or J when the element runs the other way), last = J, inner
    direction (-) local y, assignment by selection, span by element length.
    ``support_nodes`` are the girder-side bearing nodes (find them through
    ELNK, or through RIGD when the wizard hangs the link off a slave node)."""
    sup = set(support_nodes)
    out, k = {}, 0
    for gi in sorted(girder_chains):
        nodes, els = girder_chains[gi], girder_elems[gi]
        idx = [i for i, n in enumerate(nodes) if n in sup]
        for s in range(len(idx) - 1):
            k += 1
            run = els[idx[s]:idx[s + 1]]
            n_first, n_last = nodes[idx[s]], nodes[idx[s + 1]]
            items = []
            for j, e in enumerate(run):
                a, b = elems[str(e)]["NODE"][:2]
                flag = 0
                if j == 0:
                    flag = 1 if a == n_first else 2
                if j == len(run) - 1:
                    flag = 2 if b == n_last else 1
                items.append({"ELEM_KEY": e, "SUPPORT": flag})
            out[str(k)] = {"NAME": f"G{gi + 1}_Span {s + 1}", "bEXACTSPAN": False, "DIRECTION": 0, "SECTTYPE": 0,
                           "SPAN_BASE_ITEMS": items}
    return out


# ----------------------------------------------------------------- driver
TABLE_ORDER = ("UNIT", "MATL", "TDMT", "TDME", "TMAT", "SECT", "NODE", "ELEM", "TSGR", "GRUP", "BNGR", "CONS",
               "ELNK", "RIGD", "STLD", "LDGR", "BODF", "BMLD", "MVCD", "MVHL", "LLAN", "MVLD", "MVCT", "MLSR",
               "STAG", "STCT", "CSCS", "SPAN")
"""Push order that satisfies every cross-reference (groups before stages,
load groups before beam loads, lanes before moving load cases, ...)."""


def build(w: WizardInputs | None = None) -> tuple[dict, dict]:
    """Whole wizard-equivalent model.  Returns ``(payload, info)``:
    ``payload`` is ``{table: assign}`` for :data:`TABLE_ORDER` (kips/ft,
    ``UNIT`` included), ``info`` carries the girder chains/elements, support
    nodes, cap elements and column bases for post-processing."""
    w = w or WizardInputs()
    m = _Mesh()
    g = girder_lines(w, m)
    edges = deck_strips(w, m, g)
    edge_beams(w, m, edges)
    rigid = cross_frames(w, m, g)
    sub = substructure(w, m, g)
    for n, seats in sub["rigid_seats"].items():
        rigid.setdefault(n, []).extend(seats)
        m.groups["Bracing"]["N"].update(seats)          # the wizard lists the seats here too
    tenth = tenth_point_groups(w, m, g)
    groups = {}
    for name in ["Substructure", "Coping", "Bracing", "Girder", "Dummy Beam", "Dummy Beam2",
                 "Dummy Beam-D1", "Dummy Beam-D2"]:
        groups[name] = m.groups[name]
    groups.update(tenth)
    grup = {str(i + 1): {"NAME": n, "P_TYPE": 0, "N_LIST": sorted(v["N"]), "E_LIST": sorted(v["E"])}
            for i, (n, v) in enumerate(groups.items())}
    rigd = {str(n): {"ITEMS": [{"ID": 1, "GROUP_NAME": "GirderRigid Link", "DOF": 111111, "S_NODE": s}]} for n, s in rigid.items()}
    payload = {"UNIT": {"1": {"FORCE": "KIPS", "DIST": "FT", "HEAT": "BTU", "TEMPER": "F"}}}
    payload.update(property_tables(w))
    payload.update({"NODE": m.nodes, "ELEM": m.elems, "TSGR": post_wizard_tapered_groups(sub["caps"]), "GRUP": grup,
                    "CONS": sub["CONS"], "ELNK": sub["ELNK"], "RIGD": rigd})
    payload.update(load_tables(w, m, g))
    payload.update(moving_load_tables(w, g, sub))
    payload.update(construction_stages())
    payload["CSCS"] = post_wizard_cscs(w, pos_section=w.sect_girder_pos, neg_section=w.sect_girder_neg)
    support_nodes = [g["nodes"][(i, ("S", k))] for i in range(len(w.girder_offsets)) for k in range(len(w.support_stations))]
    chains = {i: [n for _, n in ch] for i, ch in g["chains"].items()}
    payload["SPAN"] = span_information(chains, g["elems"], support_nodes, m.elems)
    info = {"girder_chains": chains, "girder_elems": g["elems"], "support_nodes": support_nodes,
            "cap_elements": sub["caps"], "col_base": sub["col_base"], "seats": sub["seats"], "tags": m.tags}
    return payload, info


def push(client, payload: dict, *, chunk: int = 1500, tables: Sequence[str] = TABLE_ORDER) -> dict[str, str]:
    """Push ``payload`` in :data:`TABLE_ORDER` with ``client.put_db``; returns
    ``{table: "ok" | error}``.  Re-analyse afterwards: any ``/db`` write (and
    ``doc/SAVEAS``) discards existing results."""
    status = {}
    for table in tables:
        body = payload.get(table)
        if not body:
            continue
        items = list(body.items())
        try:
            for i in range(0, len(items), chunk):
                client.put_db(table, dict(items[i:i + chunk]))
            status[table] = "ok"
        except Exception as exc:  # noqa: BLE001 - report and continue
            status[table] = f"FAILED {exc}"
    return status
