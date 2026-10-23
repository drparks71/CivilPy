"""Object-oriented truss bridge builder: typed components, semantic deck
and lane definitions, plane-truss analysis, AASHTO capacity checks, and
direct MIDAS Civil NX API export.

The builder generates a complete truss bridge from panel geometry that
may be fully non-uniform — every panel length and every panel-point
height is independent, so real (often asymmetric) bridges can be modeled
exactly.  Components are *typed* (:class:`TopChord`, :class:`Diagonal`,
:class:`Floorbeam`, :class:`Stringer`, ...) so loads, capacity checks,
and the exported analysis model all know what each piece is.

The load path is resolved semantically: a :class:`Deck` (with an
optional centerline offset for asymmetric roadways) sheds area load to
the stringer lines by tributary width, stringers deliver reactions to
the floorbeams, and each floorbeam distributes to the two truss planes
by statics — so an off-center deck correctly loads one truss harder than
the other.  :class:`LaneLine` objects place vehicle lanes by transverse
offset; on export they become MIDAS traffic line lanes riding the
nearest stringer elements with the exact eccentricity.

Conventions match :mod:`civilpy.structural.beam_bending`: kips and feet,
plot methods take an optional ``ax`` and return the figure.

Examples
--------
A 100-ft through Pratt truss with non-uniform panels and a polygonal
(Parker-style) top chord:

>>> bridge = TrussBridge(panel_lengths_ft=[22, 28, 28, 22],
...                      heights_ft=[None, 24, 27, 24, None],
...                      width_ft=18.0)
>>> bridge.nodes["U2"]
(50.0, 27.0)
>>> _ = bridge.set_deck(Deck(width_ft=16.0, thickness_in=8.0))
>>> forces = bridge.solve()
>>> forces[("L1", "L2")] > 0          # bottom chord in tension
True
>>> forces[("U1", "U2")] < 0          # top chord in compression
True
>>> r = bridge.reactions()
>>> total = bridge.deck_area_load_ksf() * 16.0 * 100.0
>>> abs(sum(v[1] for v in r.values()) - total / 2.0) < 1e-6
True
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field

import matplotlib.pyplot as plt

from civilpy.structural.truss import Truss
from civilpy.structural.midas_models import (
    STEEL_PROPS,
    steel_material_block,
    unit_block,
)
from civilpy.structural.aashto.lrfd.steel import (
    tension_member_resistance,
    compression_member_resistance,
)
from civilpy.structural.aashto.lrfd.core import CheckResult
from civilpy.structural import frame_analysis
from civilpy.structural.influence_lines import (
    InfluenceLine,
    influence_line_from_ordinates,
)


# ── Sections, deck, and lanes ──────────────────────────────────────────────


@dataclass
class TrussSection:
    """Axial-member section for capacity checks and export.

    ``r_in`` is the governing radius of gyration (needed only for
    compression checks); ``net_area_in2`` enables the rupture check on
    tension members.  ``i_in4`` (moment of inertia for bending in the plane
    of the truss) and ``depth_in`` (member width measured in that plane)
    are needed only for rigid-joint analysis and secondary stresses
    (:meth:`TrussBridge.analyze`, G13.2 Art. 3.5.10).
    """

    name: str
    area_in2: float
    fy_ksi: float = 50.0
    fu_ksi: float = 65.0
    r_in: float | None = None
    net_area_in2: float | None = None
    shear_lag_u: float = 1.0
    i_in4: float | None = None
    depth_in: float | None = None
    e_ksi: float = 29000.0


@dataclass
class Deck:
    """Semantic deck definition: geometry plus the loads it generates.

    ``offset_ft`` shifts the deck centerline transversely (positive
    toward the +y truss plane) so asymmetric roadways shed more load to
    one truss.  Deck self weight is DC; ``wearing_surface_psf`` is DW.
    """

    width_ft: float
    thickness_in: float = 8.0
    unit_weight_pcf: float = 150.0
    wearing_surface_psf: float = 0.0
    offset_ft: float = 0.0

    @property
    def dc_ksf(self) -> float:
        return self.thickness_in / 12.0 * self.unit_weight_pcf / 1000.0

    @property
    def dw_ksf(self) -> float:
        return self.wearing_surface_psf / 1000.0

    @property
    def edges_ft(self) -> tuple[float, float]:
        half = self.width_ft / 2.0
        return self.offset_ft - half, self.offset_ft + half


@dataclass
class LaneLine:
    """A vehicle lane line at a transverse offset from the bridge
    centerline (feet, positive toward the +y truss plane)."""

    name: str
    offset_ft: float
    width_ft: float = 12.0
    wheel_space_ft: float = 6.0


# ── Typed structural components ────────────────────────────────────────────


class Member:
    """A typed truss-bridge component between two named nodes.

    ``expected`` records the gravity-load behavior the type implies
    (tension/compression/flexure) and routes :meth:`TrussBridge.
    capacity_checks` to the matching AASHTO check.  ``midas_type`` is the
    element type used on API export (BEAM, TRUSS, or TENS for
    tension-only members such as counters).
    """

    role = "Member"
    midas_type = "TRUSS"
    expected: str | None = None

    def __init__(self, start: str, end: str,
                 section: TrussSection | None = None,
                 midas_type: str | None = None):
        self.start = start
        self.end = end
        self.section = section
        if midas_type is not None:
            self.midas_type = midas_type

    @property
    def key(self) -> tuple[str, str]:
        return (self.start, self.end)

    @property
    def name(self) -> str:
        return f"{self.role} {self.start}-{self.end}"

    def __repr__(self):
        return f"<{type(self).__name__} {self.start}-{self.end}>"


class TopChord(Member):
    role = "Top Chord"
    midas_type = "BEAM"
    expected = "compression"


class BottomChord(Member):
    role = "Bottom Chord"
    midas_type = "BEAM"
    expected = "tension"


class EndPost(Member):
    role = "End Post"
    midas_type = "BEAM"
    expected = "compression"


class Vertical(Member):
    role = "Vertical"
    expected = "compression"


Post = Vertical


class Hanger(Vertical):
    role = "Hanger"
    expected = "tension"


class Diagonal(Member):
    role = "Diagonal"
    expected = "tension"


class Counter(Diagonal):
    """Tension-only counter diagonal (TENS element on export).  Counters
    make the plane truss statically indeterminate, so add them to
    MIDAS-bound models only."""

    role = "Counter"
    midas_type = "TENS"


class Floorbeam(Member):
    """Transverse floor member at a panel point, spanning between the
    two truss planes.  ``start``/``end`` name the deck-level panel-point
    node; the export expands it across the bridge width."""

    role = "Floorbeam"
    midas_type = "BEAM"
    expected = "flexure"

    def __init__(self, point: str, section: TrussSection | None = None):
        super().__init__(point, point, section)
        self.point = point

    @property
    def name(self) -> str:
        return f"Floorbeam @ {self.point}"

    def __repr__(self):
        return f"<Floorbeam @ {self.point}>"


class Stringer(Member):
    """A longitudinal stringer line at a transverse offset, bearing on
    every floorbeam.  One object represents the whole line; the export
    breaks it into one element per panel."""

    role = "Stringer"
    midas_type = "BEAM"
    expected = "flexure"

    def __init__(self, offset_ft: float,
                 section: TrussSection | None = None):
        super().__init__(f"S@{offset_ft:g}", f"S@{offset_ft:g}", section)
        self.offset_ft = float(offset_ft)

    @property
    def name(self) -> str:
        return f"Stringer @ {self.offset_ft:g} ft"

    def __repr__(self):
        return f"<Stringer @ {self.offset_ft:g} ft>"


class LateralBrace(Member):
    """Cross-frame/lateral member added manually between any two 3-D
    node names (use the prime suffix for far-plane nodes, e.g.
    ``LateralBrace("U1", "U2'")``)."""

    role = "Lateral Brace"


class Strut(Member):
    """Transverse strut tying the two truss planes at a panel point away
    from the deck (e.g. top struts on a through truss)."""

    role = "Strut"
    midas_type = "BEAM"
    expected = "compression"

    def __init__(self, point: str, section: TrussSection | None = None):
        super().__init__(point, point, section)
        self.point = point

    @property
    def name(self) -> str:
        return f"Strut @ {self.point}"


# ── The builder ────────────────────────────────────────────────────────────


class TrussBridge:
    """Build an analysis-ready truss bridge from panel geometry.

    Parameters
    ----------
    panel_lengths_ft : list of float
        Length of every panel — non-uniform spacing is fully supported.
    height_ft : float, optional
        Uniform truss depth.  For a through truss (``deck_level=
        "bottom"``) the end panel points get no top node, producing
        inclined end posts; for a deck truss the top chord runs full
        length.
    heights_ft : list of float or None, optional
        Explicit depth at *every* panel point (``len(panel_lengths_ft)
        + 1`` entries) for polygonal and asymmetric chords; ``None`` or
        ``0`` means no top node there.  Overrides ``height_ft``.
    width_ft : float
        Center-to-center spacing of the two truss planes.
    pattern : {"pratt", "howe", "warren", None}
        Web layout generated automatically.  ``None`` builds chords and
        end posts only, for fully custom webs via :meth:`add`.
        ``"warren"`` (with verticals) needs an even panel count.
    deck_level : {"bottom", "top"}
        Chord carrying the floor system — through truss or deck truss.
    """

    def __init__(self, panel_lengths_ft, height_ft: float | None = None, *,
                 heights_ft=None, width_ft: float = 20.0,
                 pattern: str | None = "pratt",
                 deck_level: str = "bottom"):
        self.panel_lengths = [float(p) for p in panel_lengths_ft]
        if not self.panel_lengths or min(self.panel_lengths) <= 0:
            raise ValueError("panel_lengths_ft must be positive lengths")
        if deck_level not in ("bottom", "top"):
            raise ValueError("deck_level must be 'bottom' or 'top'")
        self.width_ft = float(width_ft)
        self.deck_level = deck_level
        self.pattern = pattern

        n = self.n_panels = len(self.panel_lengths)
        self.panel_x = [0.0]
        for p in self.panel_lengths:
            self.panel_x.append(self.panel_x[-1] + p)
        self.span_ft = self.panel_x[-1]

        self._scalar_height = heights_ft is None
        self.heights = self._resolve_heights(height_ft, heights_ft, n)
        if deck_level == "top" and any(h is None for h in self.heights):
            raise ValueError("a deck truss needs a top node at every "
                             "panel point — give explicit heights_ft")

        # 2-D elevation nodes shared by both planes: {name: (x, y)}
        self.nodes: dict[str, tuple[float, float]] = {}
        for i, x in enumerate(self.panel_x):
            self.nodes[f"L{i}"] = (x, 0.0)
            if self.heights[i] is not None:
                self.nodes[f"U{i}"] = (x, self.heights[i])

        self.members: list[Member] = []
        self.floorbeams: list[Floorbeam] = []
        self.struts: list[Strut] = []
        self.stringers: list[Stringer] = []
        self.laterals: list[LateralBrace] = []
        self.deck: Deck | None = None
        self.lanes: list[LaneLine] = []
        self.extra_panel_loads: dict[str, float] = {}
        self._plane_trusses: dict[str, Truss] = {}
        #: pins at pin-connected panel points, ``{node: Pin}``
        #: (:class:`civilpy.structural.aashto.lrfd.pins.Pin`, packing keyed
        #: by this bridge's typed members)
        self.pins: dict = {}

        self._generate_chords()
        if pattern is not None:
            self._generate_web(pattern)
        self._generate_floor_system()

    # ── Geometry generation ────────────────────────────────────────────

    @staticmethod
    def _resolve_heights(height_ft, heights_ft, n):
        if heights_ft is not None:
            if len(heights_ft) != n + 1:
                raise ValueError(f"heights_ft needs {n + 1} entries "
                                 f"(one per panel point), got {len(heights_ft)}")
            return [None if not h else float(h) for h in heights_ft]
        if height_ft is None:
            raise ValueError("give height_ft or heights_ft")
        return [float(height_ft)] * (n + 1)

    def _top_exists(self, i: int) -> bool:
        return f"U{i}" in self.nodes

    def _generate_chords(self):
        n = self.n_panels
        if self.deck_level == "bottom" and self.pattern is not None:
            # classic through truss: drop the end top nodes so the first
            # web member is the inclined end post (unless heights_ft
            # explicitly kept them)
            for i in (0, n):
                if (self.heights[i] is not None
                        and self.pattern in ("pratt", "howe")
                        and f"U{i}" in self.nodes
                        and self._given_heights_scalar):
                    del self.nodes[f"U{i}"]
                    self.heights[i] = None
        for i in range(n):
            self.members.append(BottomChord(f"L{i}", f"L{i + 1}"))
        tops = [i for i in range(n + 1) if self._top_exists(i)]
        for a, b in zip(tops, tops[1:]):
            self.members.append(TopChord(f"U{a}", f"U{b}"))

    @property
    def _given_heights_scalar(self):
        # set in __init__ before _generate_chords runs (see below)
        return getattr(self, "_scalar_height", False)

    def _generate_web(self, pattern: str):
        n = self.n_panels
        mid = self.span_ft / 2.0
        if pattern in ("pratt", "howe"):
            if not self._top_exists(0):
                self.members.append(EndPost("L0", "U1"))
            else:
                self.members.append(EndPost("L0", "U0"))
            if not self._top_exists(n):
                self.members.append(EndPost(f"L{n}", f"U{n - 1}"))
            else:
                self.members.append(EndPost(f"L{n}", f"U{n}"))
            for i in range(1, n):
                if self._top_exists(i):
                    vert = Hanger if pattern == "howe" else Vertical
                    self.members.append(vert(f"U{i}", f"L{i}"))
            first = 0 if self._top_exists(0) else 1
            last = n if self._top_exists(n) else n - 1
            for p in range(first, last):
                if not (self._top_exists(p) and self._top_exists(p + 1)):
                    continue
                center = (self.panel_x[p] + self.panel_x[p + 1]) / 2.0
                left_half = center <= mid
                if pattern == "pratt":
                    d = (Diagonal(f"U{p}", f"L{p + 1}") if left_half
                         else Diagonal(f"U{p + 1}", f"L{p}"))
                    d.expected = "tension"
                else:                                   # howe
                    d = (Diagonal(f"L{p}", f"U{p + 1}") if left_half
                         else Diagonal(f"L{p + 1}", f"U{p}"))
                    d.expected = "compression"
                self.members.append(d)
        elif pattern == "warren":
            if n % 2:
                raise ValueError("warren pattern needs an even panel count")
            # top nodes at odd panel points only
            for i in range(n + 1):
                if self._top_exists(i) and i % 2 == 0:
                    del self.nodes[f"U{i}"]
                    self.heights[i] = None
            self.members = [m for m in self.members
                            if not isinstance(m, TopChord)]
            tops = [i for i in range(n + 1) if self._top_exists(i)]
            for a, b in zip(tops, tops[1:]):
                self.members.append(TopChord(f"U{a}", f"U{b}"))
            self.members.append(EndPost("L0", "U1"))
            self.members.append(EndPost(f"L{n}", f"U{n - 1}"))
            for i in range(1, n - 1):
                if i % 2:
                    self.members.append(Vertical(f"U{i}", f"L{i}"))
                    if i + 1 <= n:
                        d = Diagonal(f"U{i}", f"L{i + 1}")
                        d.expected = None
                        self.members.append(d)
                        if i + 2 <= n - 1:
                            d2 = Diagonal(f"L{i + 1}", f"U{i + 2}")
                            d2.expected = None
                            self.members.append(d2)
            if n - 1 >= 1:
                self.members.append(Vertical(f"U{n - 1}", f"L{n - 1}"))
        else:
            raise ValueError(f"unknown pattern {pattern!r}")

    def _generate_floor_system(self):
        deck_letter = "L" if self.deck_level == "bottom" else "U"
        for i in range(self.n_panels + 1):
            point = f"{deck_letter}{i}"
            if point in self.nodes:
                self.floorbeams.append(Floorbeam(point))
        # tie the opposite chord's panel points together for 3-D stability
        other = "U" if self.deck_level == "bottom" else "L"
        for i in range(self.n_panels + 1):
            point = f"{other}{i}"
            if point in self.nodes:
                self.struts.append(Strut(point))

    # ── Model building API ─────────────────────────────────────────────

    def add(self, member: Member):
        """Add a custom typed member.  Plane members (chords, web) use
        2-D node names; :class:`LateralBrace` may cross planes with the
        prime suffix."""
        if isinstance(member, LateralBrace):
            self.laterals.append(member)
        elif isinstance(member, Stringer):
            self.stringers.append(member)
        elif isinstance(member, Floorbeam):
            self.floorbeams.append(member)
        elif isinstance(member, Strut):
            self.struts.append(member)
        else:
            for node in (member.start, member.end):
                if node not in self.nodes:
                    raise KeyError(f"node {node!r} not defined")
            self.members.append(member)
        self._plane_trusses.clear()
        return member

    def remove(self, start: str, end: str):
        """Remove the plane member between two nodes (either order)."""
        for m in list(self.members):
            if {m.start, m.end} == {start, end}:
                self.members.remove(m)
                self._plane_trusses.clear()
                return m
        raise KeyError(f"no member between {start} and {end}")

    def member(self, start: str, end: str) -> Member:
        for m in self.members:
            if {m.start, m.end} == {start, end}:
                return m
        raise KeyError(f"no member between {start} and {end}")

    def set_deck(self, deck: Deck, stringer_offsets_ft=None,
                 max_stringer_spacing_ft: float = 8.0,
                 stringer_continuity: str = "simple"):
        """Attach the deck and lay out stringer lines.

        Without explicit offsets, stringers are spaced evenly across the
        deck width (edge lines at the deck edges) at no more than
        ``max_stringer_spacing_ft``.  ``stringer_continuity`` is
        ``"simple"`` (stringers span floorbeam to floorbeam, the usual
        clip-angle framing) or ``"continuous"`` (stringers run over the
        floorbeams, G13.2 Art. 3.5.2.2), which changes the floorbeam
        reactions.
        """
        if stringer_continuity not in ("simple", "continuous"):
            raise ValueError("stringer_continuity must be 'simple' or "
                             "'continuous'")
        self.stringer_continuity = stringer_continuity
        self.deck = deck
        if stringer_offsets_ft is None:
            lo, hi = deck.edges_ft
            n_lines = max(2, math.ceil(deck.width_ft
                                       / max_stringer_spacing_ft) + 1)
            step = (hi - lo) / (n_lines - 1)
            stringer_offsets_ft = [lo + i * step for i in range(n_lines)]
        self.stringers = [Stringer(off) for off in
                          sorted(float(o) for o in stringer_offsets_ft)]
        self._plane_trusses.clear()
        return self

    def add_lane(self, lane: LaneLine):
        self.lanes.append(lane)
        return lane

    def add_panel_load(self, node: str, p_kips: float):
        """Extra vertical load (positive down, kips) applied to a panel
        point of *each* truss plane — e.g. utilities or sidewalk."""
        if node not in self.nodes:
            raise KeyError(f"node {node!r} not defined")
        self.extra_panel_loads[node] = (
            self.extra_panel_loads.get(node, 0.0) + float(p_kips))
        self._plane_trusses.clear()

    def assign_section(self, member_type: type, section: TrussSection):
        """Assign a section to every member of a typed class (subclasses
        included): ``bridge.assign_section(Diagonal, TrussSection(...))``."""
        for group in (self.members, self.floorbeams, self.struts,
                      self.stringers, self.laterals):
            for m in group:
                if isinstance(m, member_type):
                    m.section = section
        return self

    # ── Load path: deck → stringers → floorbeams → panel points ───────

    def deck_area_load_ksf(self, case: str = "total") -> float:
        """Deck area load in ksf: ``"dc"`` (self weight), ``"dw"``
        (wearing surface), or ``"total"``."""
        if self.deck is None:
            return 0.0
        return {"dc": self.deck.dc_ksf, "dw": self.deck.dw_ksf,
                "total": self.deck.dc_ksf + self.deck.dw_ksf}[case.lower()]

    def stringer_line_loads(self, case: str = "total") -> dict[float, float]:
        """Uniform load on each stringer line (klf, positive down) from
        the deck by tributary width, keyed by stringer offset."""
        if self.deck is None or not self.stringers:
            return {s.offset_ft: 0.0 for s in self.stringers}
        w = self.deck_area_load_ksf(case)
        lo, hi = self.deck.edges_ft
        offs = [s.offset_ft for s in self.stringers]
        loads = {}
        for i, y in enumerate(offs):
            left = lo if i == 0 else (offs[i - 1] + y) / 2.0
            right = hi if i == len(offs) - 1 else (y + offs[i + 1]) / 2.0
            trib = max(0.0, min(right, hi) - max(left, lo))
            loads[y] = w * trib
        return loads

    def floorbeam_point_loads(self, index: int,
                              case: str = "total") -> dict[float, float]:
        """Concentrated loads (kips, positive down) the stringers drop on
        floorbeam ``index``, keyed by transverse offset.  Simple-span
        stringers give each floorbeam half of each adjacent panel;
        continuous stringers give the reactions of a prismatic continuous
        beam over all floorbeams (G13.2 Art. 3.5.2.2)."""
        line = self.stringer_line_loads(case)
        if getattr(self, "stringer_continuity", "simple") == "continuous":
            r = _continuous_unit_reactions(tuple(self.panel_lengths))
            return {y: w * r[index] for y, w in line.items()}
        trib_len = 0.0
        if index > 0:
            trib_len += self.panel_lengths[index - 1] / 2.0
        if index < self.n_panels:
            trib_len += self.panel_lengths[index] / 2.0
        return {y: w * trib_len for y, w in line.items()}

    def panel_point_loads(self, plane: str = "near",
                          case: str = "total") -> dict[str, float]:
        """Vertical load (kips, positive down) at each deck-level panel
        point of one truss plane, from floorbeam statics.  ``plane`` is
        ``"near"`` (y = -width/2) or ``"far"`` (+width/2); an off-center
        deck loads the planes unequally."""
        if plane not in ("near", "far"):
            raise ValueError("plane must be 'near' or 'far'")
        half_w = self.width_ft / 2.0
        loads: dict[str, float] = {}
        for fb in self.floorbeams:
            idx = int(fb.point[1:])
            total, far_share = 0.0, 0.0
            for y, p in self.floorbeam_point_loads(idx, case).items():
                total += p
                far_share += p * (y + half_w) / self.width_ft
            share = far_share if plane == "far" else total - far_share
            loads[fb.point] = share + self.extra_panel_loads.get(fb.point, 0.0)
        for node, p in self.extra_panel_loads.items():
            loads.setdefault(node, p)
        return loads

    # ── Analysis ───────────────────────────────────────────────────────

    def plane_truss(self, plane: str = "near",
                    case: str = "total") -> Truss:
        """The 2-D :class:`~civilpy.structural.truss.Truss` for one
        plane, loaded at the deck-level panel points; pin at L0, roller
        at the far bottom chord end."""
        key = f"{plane}:{case}"
        if key in self._plane_trusses:
            return self._plane_trusses[key]
        t = Truss()
        for name, (x, y) in self.nodes.items():
            t.add_node(name, x, y)
        for m in self.members:
            t.add_member(m.start, m.end)
        t.add_support("L0", fix_x=True, fix_y=True)
        t.add_support(f"L{self.n_panels}", fix_y=True)
        for node, p in self.panel_point_loads(plane, case).items():
            if p:
                t.add_load(node, fy=-p)
        self._plane_trusses[key] = t
        return t

    def solve(self, plane: str = "near",
              case: str = "total") -> dict[tuple[str, str], float]:
        """Member forces (kips, tension positive) for one truss plane."""
        return self.plane_truss(plane, case).solve()

    def reactions(self, plane: str = "near",
                  case: str = "total") -> dict[str, list[float]]:
        t = self.plane_truss(plane, case)
        if t.reactions is None:
            t.solve()
        return t.reactions

    def member_forces(self, case: str = "total") -> dict[Member, float]:
        """Governing (largest-magnitude) force per typed member across
        both truss planes."""
        near = self.solve("near", case)
        far = self.solve("far", case)
        forces = {}
        for m in self.members:
            f_near, f_far = near[m.key], far[m.key]
            forces[m] = f_near if abs(f_near) >= abs(f_far) else f_far
        return forces

    def member_length_ft(self, m: Member) -> float:
        if isinstance(m, (Floorbeam, Strut)):
            return self.width_ft
        (xa, ya), (xb, yb) = self.nodes[m.start], self.nodes[m.end]
        return math.hypot(xb - xa, yb - ya)

    def capacity_checks(self, case: str = "total", k_factor: float = 1.0,
                        design_year: int | None = None) -> dict[str, object]:
        """AASHTO LRFD axial checks for every plane member with a
        section: tension members through 6.8.2.1 (yield/rupture) and
        compression members through 6.9.4.1.1 (column buckling with
        KL/r from the member's own length).  Returns
        ``{member.name: CheckResult}``; members without sections are
        skipped."""
        results = {}
        for m, force in self.member_forces(case).items():
            sec = m.section
            if sec is None:
                continue
            if force >= 0:
                results[m.name] = tension_member_resistance(
                    a_g=sec.area_in2, f_y=sec.fy_ksi,
                    a_n=sec.net_area_in2, f_u=sec.fu_ksi,
                    u_shear_lag=sec.shear_lag_u, p_u=force,
                )
            else:
                if sec.r_in is None:
                    raise ValueError(
                        f"{m.name} is in compression — its TrussSection "
                        f"needs r_in for the KL/r check")
                kl_over_r = (k_factor * self.member_length_ft(m) * 12.0
                             / sec.r_in)
                results[m.name] = compression_member_resistance(
                    a_g=sec.area_in2, f_y=sec.fy_ksi,
                    kl_over_r=kl_over_r, p_u=-force,
                    design_year=design_year,
                )
        return results

    # ── G13.2 analysis: joint fixity, camber, secondary stresses ──────

    def _deck_points(self) -> list[str]:
        return [fb.point for fb in self.floorbeams]

    def to_structural_model(self, plane: str = "near", case: str = "total",
                            *, joints: str = "pinned",
                            unit_loads: bool = False):
        """One truss plane as a :class:`~civilpy.structural.structural_model.
        StructuralModel` hub in the global X-Z plane (x along the span, z
        up; kips / ft), for :mod:`civilpy.structural.frame_analysis`.

        ``joints="pinned"`` makes every member an axial-only ``TRUSS``
        element; ``"rigid"`` makes them ``BEAM`` elements continuous
        through the joints, so truss distortion produces the secondary
        moments of G13.2 Art. 3.5.10 (every member then needs
        ``TrussSection.i_in4``).  Nodes and elements are named as in the
        bridge (``"L2"``, ``"U1-L2"``); each element carries its typed
        member in ``metadata["member"]``.  Supports are a pin at L0 and a
        roller at the far bottom-chord end; out-of-plane DOFs are held.
        The deck-level panel-point loads of ``case`` go in that case, or
        with ``unit_loads`` one 1-kip case per deck panel point
        (``"unit L3"``) for influence lines.
        """
        from civilpy.structural.structural_model import (
            MaterialProperties, SectionProperties, StructuralModel, Units)

        if joints not in ("pinned", "rigid"):
            raise ValueError("joints must be 'pinned' or 'rigid'")
        missing = [m.name for m in self.members if m.section is None]
        if missing:
            raise ValueError(f"frame analysis needs a TrussSection on every "
                             f"member; none on {missing[:4]}")
        hub = StructuralModel(units=Units(force="kips", length="ft"))
        labels: dict[int, str] = {}
        for m in self.members:
            sec = m.section
            if id(sec) in labels:
                continue
            if joints == "rigid" and sec.i_in4 is None:
                raise ValueError(f"rigid joints need TrussSection.i_in4 "
                                 f"({sec.name!r})")
            label = sec.name if sec.name not in labels.values() \
                else f"{sec.name} #{len(labels) + 1}"
            labels[id(sec)] = label
            i_ft4 = (sec.i_in4 or 0.0) / 12.0 ** 4
            hub.section_properties[label] = SectionProperties(
                area=sec.area_in2 / 144.0, iy=i_ft4, iz=i_ft4, j=i_ft4,
                depth=(sec.depth_in or 0.0) / 12.0)
            mat = f"E {sec.e_ksi:g} ksi"
            hub.material_properties.setdefault(
                mat, MaterialProperties(e=sec.e_ksi * 144.0))
        for name, (x, y) in self.nodes.items():
            hub.add_node(x, 0.0, y, label=name, id=name)
        for m in self.members:
            e = hub.add_element(m.start, m.end, id=f"{m.start}-{m.end}",
                                role=m.role.lower().replace(" ", "_"),
                                midas_type="TRUSS" if joints == "pinned" else "BEAM",
                                section=labels[id(m.section)],
                                material=f"E {m.section.e_ksi:g} ksi")
            e.metadata["member"] = m
        last = f"L{self.n_panels}"
        for name in self.nodes:
            hub.add_restraint(name, fix_x=name == "L0",
                              fix_y=True, fix_z=name in ("L0", last),
                              fix_rx=True, fix_rz=True)
        if unit_loads:
            for point in self._deck_points():
                hub.add_load(point, fz=-1.0, case=f"unit {point}")
        else:
            for node, p in self.panel_point_loads(plane, case).items():
                if p:
                    hub.add_load(node, fz=-p, case=case)
        return hub

    def analyze(self, plane: str = "near", case: str = "total", *,
                joints: str = "rigid", camber_case: str | None = None
                ) -> "TrussAnalysis":
        """Stiffness analysis of one truss plane (G13.2 Art. 3.5.1/3.5.10).

        With ``camber_case`` the members are fabricated to the
        G13.2 Art. 4.1.2 camber of that case (:meth:`camber_strains`) and
        the strain case is added: under that load the panel points return
        to the geometric profile and the dead-load secondary moments
        vanish, which is why trusses are cambered for total dead load."""
        hub = self.to_structural_model(plane, case, joints=joints)
        if camber_case is not None:
            for m, eps in self.camber_strains(camber_case, plane).items():
                hub.add_element_strain(f"{m.start}-{m.end}", eps, case="camber")
        res = frame_analysis.solve(hub)
        cases = [case] + (["camber"] if camber_case is not None else [])
        result = frame_analysis.combine(res, {c: 1.0 for c in cases if c in res},
                                        name=case)
        return TrussAnalysis(self, plane, joints, hub, result)

    def camber_strains(self, case: str = "dc", plane: str = "near"
                       ) -> dict[Member, float]:
        """Fabrication strain per member that cambers the truss for
        ``case`` (G13.2 Art. 4.1.2): compression members are made longer by
        their shortening, tension members shorter by their elongation,
        ``strain = -P / (A E)`` from a pin-jointed analysis."""
        pinned = self.analyze(plane, case, joints="pinned")
        return {m: -pinned.axial(m) / (m.section.area_in2 * m.section.e_ksi)
                for m in self.members}

    def camber_length_changes(self, case: str = "dc", plane: str = "near"
                              ) -> dict[Member, float]:
        """Fabricated-length change per member in inches (positive =
        longer than the geometric length), ``-PL / AE`` (G13.2 4.1.2)."""
        return {m: eps * self.member_length_ft(m) * 12.0
                for m, eps in self.camber_strains(case, plane).items()}

    def staged_analysis(self, stages, plane: str = "near") -> "TrussAnalysis":
        """Superpose load stages applied to different structures -- the
        locked-in forces of G13.2 Art. 3.6.1.7 / 4.1.1.  ``stages`` is a
        list of ``(case, joints)`` (e.g. ``[("dc", "pinned"),
        ("dw", "rigid")]`` for dead load placed while the joints are still
        pinned on erection pins and the rest after the connections are
        bolted).  Returns the summed forces and moments."""
        results, hub = {}, None
        for k, (case, joints) in enumerate(stages):
            a = self.analyze(plane, case, joints=joints)
            results[f"{k}:{case}"] = a.result
            hub = a.model
        total = frame_analysis.combine(results, {c: 1.0 for c in results},
                                       name="staged")
        return TrussAnalysis(self, plane, "staged", hub, total)

    def secondary_stress_checks(self, plane: str = "near",
                                case: str = "total", *,
                                camber_case: str | None = None,
                                tension_limit_ksi: float = 4.0,
                                compression_limit_ksi: float = 3.0
                                ) -> dict[str, CheckResult]:
        """Service-level secondary stresses from a rigid-joint analysis,
        screened per G13.2 Art. 3.5.10: members whose width in the plane
        of distortion is under 1/10 of their length need not be checked
        (LRFD 6.14.2.3); otherwise the bending stress M c / I is compared
        with 4 ksi in tension members and 3 ksi in compression members
        (Std. Spec. 10.16.3, Nair 1988), above which the excess is to be
        treated as a primary stress.  The checks are advisory."""
        a = self.analyze(plane, case, joints="rigid", camber_case=camber_case)
        out = {}
        for m in self.members:
            sec = m.section
            length_in = self.member_length_ft(m) * 12.0
            ratio = (sec.depth_in or 0.0) / length_in
            force = a.axial(m)
            limit = tension_limit_ksi if force >= 0 else compression_limit_ksi
            details = {"P": force, "M_i": a.end_moments(m)[0],
                       "M_j": a.end_moments(m)[1], "width/length": ratio}
            if not sec.depth_in:
                raise ValueError(f"{m.name}: secondary stresses need "
                                 f"TrussSection.depth_in")
            if ratio < 0.1:
                details["exempt"] = "width < L/10 (6.14.2.3)"
                demand = None
            else:
                demand = a.secondary_stress_ksi(m)
            out[m.name] = CheckResult("6.14.2.3", "truss secondary stress",
                                      capacity=limit, demand=demand,
                                      details=details, advisory=True)
        return out

    def pin_checks(self, analysis: "TrussAnalysis", *,
                   significant_rotation: bool = False,
                   new_design: bool = False) -> dict[str, dict]:
        """6.7.6.2 checks of every pin in :attr:`pins` under the member
        forces of ``analysis`` (factored, if the analysis was): each packed
        member pulls the pin toward its far end with its share of the
        axial force.  Returns ``{node: {check: CheckResult}}``."""
        return {node: pin.checks(analysis.pin_forces(node),
                                 significant_rotation=significant_rotation,
                                 new_design=new_design)
                for node, pin in self.pins.items()}

    def influence_lines(self, plane: str = "near", *,
                        joints: str = "pinned") -> dict[Member, InfluenceLine]:
        """Axial-force influence line of every member for a unit load
        moving along the deck of one truss plane (G13.2 Art. 2.2.3, static
        method): one unit-load analysis per deck panel point, ordinates
        joined by straight lines -- exact when the stringers are simply
        supported between floorbeams.  Members need sections (the frame
        solver also handles statically indeterminate trusses)."""
        hub = self.to_structural_model(plane, joints=joints, unit_loads=True)
        res = frame_analysis.solve(hub, store=False)
        points = self._deck_points()
        xs = [self.nodes[p][0] for p in points]
        out = {}
        for m in self.members:
            eid = f"{m.start}-{m.end}"
            etas = [res[f"unit {p}"].element_forces[eid] for p in points]
            out[m] = influence_line_from_ordinates(xs, etas, length=self.span_ft,
                                                   label=m.name)
        return out

    def lane_fractions(self, plane: str = "near") -> dict[str, float]:
        """Share of each lane's load carried by one truss plane, by
        floorbeam statics on the lane's two wheel lines (the lever rule
        through stringers and floorbeams is linear in offset)."""
        half = self.width_ft / 2.0
        out = {}
        for lane in self.lanes:
            far = sum((lane.offset_ft + d + half) / self.width_ft
                      for d in (-lane.wheel_space_ft / 2.0,
                                lane.wheel_space_ft / 2.0)) / 2.0
            out[lane.name] = far if plane == "far" else 1.0 - far
        return out

    def live_load_envelope(self, plane: str = "near", *, im: float = 0.33,
                           lane_klf: float = 0.64,
                           multiple_presence=(1.20, 1.00, 0.85, 0.65),
                           joints: str = "pinned"
                           ) -> dict[Member, tuple[float, float]]:
        """HL-93 member-force envelope ``{member: (max tension, max
        compression)}`` in kips for one plane: each lane's truck/tandem
        (with IM) plus lane load is placed on the member's influence line
        for the extreme of each sign, scaled by the lane's plane share
        (:meth:`lane_fractions`), and the governing number of loaded
        lanes is taken with the 3.6.1.1.2 multiple-presence factors.
        Needs at least one :class:`LaneLine`."""
        if not self.lanes:
            raise ValueError("add LaneLine objects first (add_lane)")
        shares = list(self.lane_fractions(plane).values())
        out = {}
        for m, il in self.influence_lines(plane, joints=joints).items():
            pos = il.hl93_effect(im=im, lane_klf=lane_klf)["total"]
            neg = il.hl93_effect(im=im, lane_klf=lane_klf, sign=-1.0)["total"]
            env = []
            for want in (1.0, -1.0):
                contrib = sorted(
                    (s * (pos if s * want > 0 else neg) for s in shares),
                    key=lambda v: -want * v)
                best, run = 0.0, 0.0
                for k, c in enumerate(contrib, start=1):
                    run += c
                    mpf = multiple_presence[min(k, len(multiple_presence)) - 1]
                    if want * mpf * run > want * best:
                        best = mpf * run
                env.append(best)
            out[m] = (env[0], env[1])
        return out

    # ── Visualization ──────────────────────────────────────────────────

    _ROLE_COLORS = {
        "Top Chord": "tab:blue", "Bottom Chord": "tab:red",
        "End Post": "tab:purple", "Vertical": "tab:green",
        "Hanger": "tab:olive", "Diagonal": "tab:orange",
        "Counter": "tab:brown", "Floorbeam": "tab:cyan",
        "Stringer": "tab:pink", "Strut": "tab:gray",
        "Lateral Brace": "gold",
    }

    def plot_elevation(self, ax=None):
        """Elevation of the truss colored by member type, with the deck
        level and panel points marked.  Returns the figure."""
        if ax is None:
            ax = plt.figure(figsize=(10, 4)).add_subplot(1, 1, 1)
        seen = set()
        for m in self.members:
            (xa, ya), (xb, yb) = self.nodes[m.start], self.nodes[m.end]
            color = self._ROLE_COLORS.get(m.role, "k")
            ax.plot([xa, xb], [ya, yb], color=color, lw=2.5,
                    label=m.role if m.role not in seen else None,
                    solid_capstyle="round", zorder=2)
            seen.add(m.role)
        for name, (x, y) in self.nodes.items():
            ax.plot(x, y, "ko", ms=4, zorder=3)
            ax.annotate(name, (x, y), textcoords="offset points",
                        xytext=(-4, 6), fontsize=8)
        if self.deck is not None:
            y_deck = 0.0 if self.deck_level == "bottom" else None
            if y_deck is not None:
                ax.axhline(y_deck, color="0.6", lw=6, alpha=0.35, zorder=1,
                           label="Deck")
        ax.legend(loc="upper right", fontsize=8, ncols=2)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel("Station (ft)")
        ax.set_ylabel("Elevation (ft)")
        ax.set_title(f"Truss Elevation — {self.span_ft:g} ft, "
                     f"{self.n_panels} panels")
        ax.grid(True, alpha=0.25)
        return ax.get_figure()

    def plot_forces(self, plane: str = "near", case: str = "total",
                    ax=None):
        """Solved member-force diagram (tension red, compression blue)
        for one truss plane; see :meth:`Truss.plot`."""
        return self.plane_truss(plane, case).plot(ax=ax)

    def plot_cross_section(self, ax=None):
        """Transverse section at a floorbeam: truss planes, floorbeam,
        stringers, deck, and lane positions.  Returns the figure."""
        if ax is None:
            ax = plt.figure(figsize=(8, 4)).add_subplot(1, 1, 1)
        half_w = self.width_ft / 2.0
        heights = [h for h in self.heights if h]
        h = max(heights) if heights else 10.0
        z_deck = 0.0 if self.deck_level == "bottom" else h
        for y in (-half_w, half_w):
            ax.plot([y, y], [0, h], "k-", lw=3)
        ax.plot([-half_w, half_w], [z_deck, z_deck], "tab:green", lw=2.5,
                label="Floorbeam")
        for s in self.stringers:
            ax.plot(s.offset_ft, z_deck + 0.4, "s", ms=9,
                    color="tab:orange",
                    label="Stringer" if s is self.stringers[0] else None)
        if self.deck is not None:
            lo, hi = self.deck.edges_ft
            t = self.deck.thickness_in / 12.0
            ax.fill_between([lo, hi], z_deck + 0.8, z_deck + 0.8 + t,
                            color="0.7", label="Deck")
        for lane in self.lanes:
            ax.annotate("", xy=(lane.offset_ft, z_deck + 3.5),
                        xytext=(lane.offset_ft, z_deck + 5.5),
                        arrowprops=dict(arrowstyle="-|>", color="tab:red",
                                        lw=2))
            ax.annotate(lane.name, (lane.offset_ft, z_deck + 5.7),
                        ha="center", color="tab:red", fontsize=9)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel("Transverse offset (ft)")
        ax.set_ylabel("Elevation (ft)")
        ax.set_title("Cross Section at Floorbeam")
        ax.grid(True, alpha=0.25)
        return ax.get_figure()

    def plot_3d(self, ax=None, show_lanes: bool = True,
                elev: float = 22.0, azim: float = -60.0):
        """Isometric wireframe of the complete 3-D model, drawn from the
        same node/element tables :meth:`midas_payloads` exports — so the
        picture is exactly what a ``to_midas()`` call will build: both
        truss planes, floorbeams (split at stringer crossings),
        stringers, struts, and any laterals, colored by component type,
        with lane lines and the deck outline overlaid.  Returns the
        figure."""
        payloads = self.midas_payloads()
        nodes = {int(i): (n["X"], n["Y"], n["Z"])
                 for i, n in payloads["NODE"].items()}
        role_of = {eid: g["NAME"] for g in payloads["GRUP"].values()
                   for eid in g["E_LIST"]}

        if ax is None:
            ax = plt.figure(figsize=(11, 7)).add_subplot(projection="3d")
        seen = set()
        for eid_str, elem in payloads["ELEM"].items():
            role = role_of.get(int(eid_str), "Member")
            (xa, ya, za), (xb, yb, zb) = (nodes[n] for n in elem["NODE"])
            ax.plot([xa, xb], [ya, yb], [za, zb],
                    color=self._ROLE_COLORS.get(role, "k"),
                    lw=2.0 if role in ("Top Chord", "Bottom Chord",
                                       "End Post") else 1.2,
                    label=role if role not in seen else None)
            seen.add(role)

        z_deck = 0.0 if self.deck_level == "bottom" else None
        if self.deck is not None and z_deck is not None:
            lo, hi = self.deck.edges_ft
            xs = [0.0, self.span_ft, self.span_ft, 0.0, 0.0]
            ys = [lo, lo, hi, hi, lo]
            ax.plot(xs, ys, [z_deck + 0.5] * 5, color="0.6", ls="--",
                    lw=1.0, label="Deck edge")
        if show_lanes and z_deck is not None:
            for lane in self.lanes:
                ax.plot([0.0, self.span_ft], [lane.offset_ft] * 2,
                        [z_deck + 0.5] * 2, color="tab:red", ls=":",
                        lw=1.8, label=f"Lane {lane.name}")

        heights = [h for h in self.heights if h]
        h_max = max(heights) if heights else 10.0
        ax.set_box_aspect((self.span_ft,
                           max(self.width_ft * 2.0, self.span_ft / 4.0),
                           max(h_max * 1.5, self.span_ft / 6.0)))
        ax.set_xlabel("Station (ft)")
        ax.set_ylabel("Transverse (ft)")
        ax.set_zlabel("Elevation (ft)")
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(f"3-D Model — {self.span_ft:g} ft span, "
                     f"{len(payloads['ELEM'])} elements as exported")
        ax.legend(loc="upper left", fontsize=8, ncols=2)
        return ax.get_figure()

    # ── MIDAS Civil NX export ──────────────────────────────────────────

    # E [ksf], Poisson, thermal [1/°F], weight density [kcf] in the
    # KIPS/FT unit system the export sets (E = 29,000 ksi).
    _STEEL_PROPS = STEEL_PROPS          # shared with the hub serializer (S4)

    def _node_3d(self, name: str, plane: int) -> tuple[float, float, float]:
        x, z = self.nodes[name]
        y = -self.width_ft / 2.0 if plane == 0 else self.width_ft / 2.0
        return x, y, z

    def _deck_z(self, point: str) -> float:
        return self.nodes[point][1]

    def midas_payloads(self, node_start: int = 1,
                       elem_start: int = 1) -> dict[str, dict]:
        """Build every ``PUT /db/*`` Assign body for the full 3-D model.

        Returns ``{table: assign}`` in send order: UNIT, MATL, SECT,
        NODE, ELEM, CONS, GRUP (structure groups named by component
        type), STLD (DC/DW cases), BMLD (deck load on the stringers),
        and LLAN (traffic line lanes riding the nearest stringer line).

        Load paths stay semantic in the export: deck weight lands on
        stringer elements as beam loads, lanes reference stringer
        elements with their true eccentricity, and every element belongs
        to a group named for its component type.  Field layouts for
        GRUP/STLD/BMLD follow the MIDAS API manual but are unverified
        against a live Civil NX session — check the send report's errors
        first when debugging.
        """
        node_ids: dict[tuple, int] = {}
        nodes: dict[str, dict] = {}

        def node_id(key, x, y, z):
            if key not in node_ids:
                node_ids[key] = node_start + len(node_ids)
                nodes[str(node_ids[key])] = {
                    "X": round(x, 6), "Y": round(y, 6), "Z": round(z, 6)}
            return node_ids[key]

        for plane in (0, 1):
            for name in self.nodes:
                node_id(("P", plane, name), *self._node_3d(name, plane))
        stringer_offsets = [s.offset_ft for s in self.stringers]
        for fb in self.floorbeams:
            x, z = self.nodes[fb.point][0], self._deck_z(fb.point)
            for off in stringer_offsets:
                if abs(abs(off) - self.width_ft / 2.0) < 1e-9:
                    continue        # stringer rides the truss plane node
                node_id(("S", fb.point, off), x, off, z)

        def resolve(key_or_name):
            """3-D node id from a 2-D plane key or a primed name."""
            return node_ids[key_or_name]

        # sections: dedupe by name; placeholder for members without one
        sections: dict[str, dict] = {}
        section_ids: dict[str, int] = {}

        def section_id(sec: TrussSection | None) -> int:
            name = sec.name if sec else "PLACEHOLDER-1ft-SQ"
            if name not in section_ids:
                side_ft = (math.sqrt(sec.area_in2) / 12.0 if sec else 1.0)
                section_ids[name] = len(section_ids) + 1
                # equal-area square so axial stiffness is exact; swap to
                # the real shape inside Civil NX for flexural members
                sections[str(section_ids[name])] = {
                    "SECTTYPE": "DBUSER",
                    "SECT_NAME": name,
                    "SECT_BEFORE": {
                        "SHAPE": "SB", "DATATYPE": 2,
                        "SECT_I": {"vSIZE": [round(side_ft, 6),
                                             round(side_ft, 6)]},
                    },
                }
            return section_ids[name]

        elements: dict[str, dict] = {}
        groups: dict[str, list[int]] = {}
        stringer_elems: dict[float, list[int]] = {o: [] for o
                                                  in stringer_offsets}
        next_elem = elem_start

        def add_elem(n_i, n_j, member: Member, role=None):
            nonlocal next_elem
            elements[str(next_elem)] = {
                "TYPE": member.midas_type,
                "MATL": 1,
                "SECT": section_id(member.section),
                "NODE": [n_i, n_j],
                "ANGLE": 0,
            }
            groups.setdefault(role or member.role, []).append(next_elem)
            next_elem += 1
            return next_elem - 1

        for plane in (0, 1):
            for m in self.members:
                add_elem(resolve(("P", plane, m.start)),
                         resolve(("P", plane, m.end)), m)
        for fb in self.floorbeams:
            chain = [(-self.width_ft / 2.0, resolve(("P", 0, fb.point)))]
            for off in stringer_offsets:
                if ("S", fb.point, off) in node_ids:
                    chain.append((off, resolve(("S", fb.point, off))))
            chain.append((self.width_ft / 2.0, resolve(("P", 1, fb.point))))
            chain.sort()
            for (_, ni), (_, nj) in zip(chain, chain[1:]):
                add_elem(ni, nj, fb)
        for st in self.struts:
            add_elem(resolve(("P", 0, st.point)),
                     resolve(("P", 1, st.point)), st)
        deck_letter = "L" if self.deck_level == "bottom" else "U"
        deck_points = [fb.point for fb in self.floorbeams]
        for s in self.stringers:
            off = s.offset_ft
            on_plane = abs(abs(off) - self.width_ft / 2.0) < 1e-9
            plane = 0 if off < 0 else 1
            line_nodes = []
            for point in deck_points:
                key = (("P", plane, point) if on_plane
                       else ("S", point, off))
                line_nodes.append(node_ids[key])
            for ni, nj in zip(line_nodes, line_nodes[1:]):
                eid = add_elem(ni, nj, s)
                stringer_elems[off].append(eid)
        for lat in self.laterals:
            def lat_node(name):
                plane = 1 if name.endswith("'") else 0
                return resolve(("P", plane, name.rstrip("'")))
            add_elem(lat_node(lat.start), lat_node(lat.end), lat)

        # supports: pin at L0 (both planes), transverse+vertical at Ln
        supports = {}
        for plane in (0, 1):
            supports[str(resolve(("P", plane, "L0")))] = {
                "ITEMS": [{"ID": 1, "CONSTRAINT": "1110000"}]}
            supports[str(resolve(("P", plane, f"L{self.n_panels}")))] = {
                "ITEMS": [{"ID": 1, "CONSTRAINT": "0110000"}]}

        group_assign = {
            str(i + 1): {"NAME": role, "P_TYPE": 0,
                         "E_LIST": elems, "N_LIST": []}
            for i, (role, elems) in enumerate(sorted(groups.items()))
        }

        static_loads = {
            "1": {"NAME": "DC", "TYPE": "USER",
                  "DESC": "deck + component dead load"},
            "2": {"NAME": "DW", "TYPE": "USER",
                  "DESC": "wearing surface"},
        }

        beam_loads: dict[str, dict] = {}
        if self.deck is not None:
            dc = self.stringer_line_loads("dc")
            dw = self.stringer_line_loads("dw")
            for off, elems in stringer_elems.items():
                items = []
                for lcname, w in (("DC", dc.get(off, 0.0)),
                                  ("DW", dw.get(off, 0.0))):
                    if w <= 0:
                        continue
                    items.append({
                        "ID": len(items) + 1, "LCNAME": lcname,
                        "GROUP_NAME": "", "CMD": "BEAM",
                        "TYPE": "UNILOAD", "DIRECTION": "GZ",
                        "USE_PROJECTION": False, "USE_ECCEN": False,
                        "D": [0, 1, 0, 0],
                        "P": [-w, -w, 0, 0],
                    })
                if items:
                    for eid in elems:
                        beam_loads[str(eid)] = {"ITEMS": items}

        lanes_assign: dict[str, dict] = {}
        for li, lane in enumerate(self.lanes, start=1):
            if not stringer_offsets:
                break
            ref = min(stringer_offsets,
                      key=lambda o: abs(o - lane.offset_ft))
            ecc = round(lane.offset_ft - ref, 6)
            lanes_assign[str(li)] = {
                "COMMON": {
                    "LL_NAME": lane.name, "LOAD_DIST": "LANE",
                    "MOVING": "BOTH",
                    "WHEEL_SPACE": lane.wheel_space_ft,
                    "WIDTH": lane.width_ft,
                    "OPT_AUTO_LANE": False,
                    "ALLOW_WIDTH": lane.width_ft,
                    "SKEW_START": 0.0, "SKEW_END": 0.0,
                },
                "LANE_ITEMS": [{"ELEM": e, "ECC": ecc,
                                "ECCEN_VERT_LOAD": 0.0}
                               for e in stringer_elems[ref]],
            }

        payloads = {
            "UNIT": unit_block(),
            "MATL": steel_material_block("A709-50", props=self._STEEL_PROPS),
            "SECT": sections,
            "NODE": nodes,
            "ELEM": elements,
            "CONS": supports,
            "GRUP": group_assign,
            "STLD": static_loads,
        }
        if beam_loads:
            payloads["BMLD"] = beam_loads
        if lanes_assign:
            payloads["LLAN"] = lanes_assign
        return payloads

    def to_midas(self, midas=None, **client_kwargs) -> dict:
        """Send the model to a live Civil NX session through
        :class:`civilpy.structural.midas.MidasCivil` (created from
        ``~/secrets.json`` when not given).  Sends each table in order
        and keeps going on errors; returns ``{table: {"sent": n} |
        {"error": message}}`` so a single bad table is visible without
        losing the rest of the model."""
        if midas is None:
            from civilpy.structural.midas import MidasCivil
            midas = MidasCivil(**client_kwargs)
        report = {}
        for table, assign in self.midas_payloads().items():
            try:
                midas.put_db(table, assign)
                report[table] = {"sent": len(assign)}
            except Exception as exc:        # MidasApiError, transport
                report[table] = {"error": str(exc)}
        return report

    def __repr__(self):
        return (f"<TrussBridge {self.span_ft:g} ft, {self.n_panels} panels, "
                f"{len(self.members)} members/plane, "
                f"{len(self.stringers)} stringer lines>")


def _continuous_unit_reactions(spans: tuple) -> list[float]:
    """Support reactions of a prismatic continuous beam over ``spans``
    under a 1 klf uniform load (kips per support), by
    :mod:`~civilpy.structural.frame_analysis`."""
    return list(_CONT_CACHE.setdefault(spans, _solve_continuous(spans)))


_CONT_CACHE: dict = {}


def _solve_continuous(spans):
    from civilpy.structural.structural_model import (
        MaterialProperties, SectionProperties, StructuralModel)

    hub = StructuralModel()
    hub.section_properties["s"] = SectionProperties(area=1.0, iy=1.0, iz=1.0, j=1.0)
    hub.material_properties["m"] = MaterialProperties(e=1.0e4)
    xs = [0.0]
    for sp_ in spans:
        xs.append(xs[-1] + sp_)
    ids = [hub.add_node(x, 0.0, 0.0, id=f"n{k}").id for k, x in enumerate(xs)]
    for a, b in zip(ids, ids[1:]):
        e = hub.add_element(a, b, midas_type="BEAM", section="s")
        hub.add_beam_load(e.id, -1.0)
    for k, nid in enumerate(ids):
        hub.add_restraint(nid, fix_x=k == 0, fix_y=True, fix_z=True,
                          fix_rx=True, fix_rz=True)
    res = frame_analysis.solve(hub, store=False)["default"]
    return tuple(res.reactions[nid][2] for nid in ids)


@dataclass
class TrussAnalysis:
    """Results of :meth:`TrussBridge.analyze` for one truss plane: the hub
    model that was solved and its :class:`~civilpy.structural.
    structural_model.Result`, read back by typed member.  Forces in kips
    (tension positive), moments in kip-ft, deflections in inches."""

    bridge: TrussBridge
    plane: str
    joints: str
    model: object
    result: object

    @staticmethod
    def _eid(m: Member) -> str:
        return f"{m.start}-{m.end}"

    def axial(self, m: Member) -> float:
        return self.result.element_forces[self._eid(m)]

    @property
    def forces(self) -> dict[Member, float]:
        return {m: self.axial(m) for m in self.bridge.members}

    def end_moments(self, m: Member) -> tuple[float, float]:
        """In-plane end moments ``(M_i, M_j)`` (kip-ft, beam sign
        convention); zero for pinned joints."""
        return frame_analysis.end_moments(self.result, self._eid(m), "y")

    def secondary_stress_ksi(self, m: Member) -> float:
        """Largest end bending stress ``M c / I`` with ``c = depth / 2``."""
        sec = m.section
        if not (sec.i_in4 and sec.depth_in):
            raise ValueError(f"{m.name}: needs TrussSection.i_in4 and depth_in")
        moment = max(abs(v) for v in self.end_moments(m)) * 12.0
        return moment * (sec.depth_in / 2.0) / sec.i_in4

    def pin_forces(self, node: str) -> dict[Member, tuple[float, float]]:
        """In-plane force each member framing into ``node`` applies to the
        joint's pin, ``(fx, fz)`` kips: the axial force (tension positive)
        along the unit vector from the node toward the member's far end."""
        x0, z0 = self.bridge.nodes[node]
        out = {}
        for m in self.bridge.members:
            if node not in (m.start, m.end):
                continue
            far = m.end if m.start == node else m.start
            x1, z1 = self.bridge.nodes[far]
            length = math.hypot(x1 - x0, z1 - z0)
            n = self.axial(m)
            out[m] = (n * (x1 - x0) / length, n * (z1 - z0) / length)
        return out

    def deflection_in(self, node: str) -> tuple[float, float]:
        """Panel-point displacement ``(dx, dz)`` in inches."""
        d = self.result.displacements[node]
        return d[0] * 12.0, d[2] * 12.0
