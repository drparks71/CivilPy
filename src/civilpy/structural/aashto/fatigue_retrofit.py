"""Fatigue crack repair and retrofit of steel bridges: what a retrofit does
to a detail's AASHTO fatigue category, how big a crack-arrest hole must be,
and the remaining life of the retrofitted detail.

Sources (NSBA library): AASHTO/NSBA G14.1-2021 *Guidelines for Addressing
Fatigue Cracking and Fracture in Steel Bridges* ("G14.1") and the FHWA
*Manual for Repair and Retrofit of Fatigue Cracks in Steel Bridges*
("Repair Manual").

* :data:`RETROFITS` / :func:`retrofit_category` -- the category a detail
  reaches after a retrofit, each entry citing its source passage.
  Improvements counted "by categories" step along the unprimed ladder
  A-B-C-D-E-E' (G14.1: hammer peening E -> D is one category, UIT E -> C
  two, E' -> C three).
* :func:`crack_arrest_hole_diameter` -- Repair Manual Figs. 18-20: the hole
  radius rho with ``dK / sqrt(rho) <= 4 sqrt(Fy)`` (ksi), ``dK = S_r sqrt(pi
  a)`` (center crack), so ``D = 2 rho = S_r^2 pi a / (8 Fy)``, at least
  1.0 in., 25 % larger for an edge crack.  (The Manual's Fig. 20 prints
  ``S_r`` unsquared; its own Fig. 18 and SI Fig. 21 need the square.)
* :func:`drilled_holes_suffice_for_web_gap` -- the Lehigh criterion for
  distortion-induced web-gap cracks (Repair Manual).
* :func:`retrofitted_life` -- MBE Section 7 life of the retrofitted detail
  through :mod:`civilpy.structural.aashto.mbe_fatigue`, starting from "day
  one" (G14.1 3.3: the day the hole is drilled starts the hole's life).

Units: ksi, inches.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass

from civilpy.structural.aashto import mbe_fatigue

#: the unprimed ladder improvements are counted on (G14.1 4.1.2)
LADDER = ("A", "B", "C", "D", "E", "E'")
#: where the primed categories sit on that ladder
_ON_LADDER = {"A": 0, "B": 1, "B'": 1, "C": 2, "C'": 2, "D": 3, "E": 4, "E'": 5}


@dataclass(frozen=True)
class Retrofit:
    """One retrofit: either a resulting ``category`` or an ``improvement``
    (ladder steps), the ``best`` it can reach, conditions and the source."""

    description: str
    category: str | None = None
    improvement: int = 0
    best: str | None = None
    load_induced_only: bool = False
    source: str = ""


RETROFITS = {
    "drilled_hole": Retrofit(
        "open hole drilled per the guidelines (crack arrest, plug-weld removal)", category="C",
        source="G14.1 3.3 (Fisher et al. 1987, Brown et al. 2007); LRFD design takes D"),
    "drilled_hole_poor": Retrofit(
        "drilled hole not made to the recommended procedure", category="D",
        source="G14.1 3.3: less than C but not less than D"),
    "drilled_hole_bolted": Retrofit(
        "drilled hole with a fully pretensioned F3125 bolt and F436 washers both sides",
        category="B", load_induced_only=True,
        source="G14.1 3.3 / 4.7; not for distortion-induced cracks (adds stiffness)"),
    "hammer_peening": Retrofit(
        "hammer peening of the weld toe under dead load", improvement=1,
        source="G14.1 4.1.2 (E -> D)"),
    "uit": Retrofit(
        "ultrasonic impact treatment of the weld toe under dead load", improvement=2,
        best="C", source="G14.1 4.1.2 (E -> C)"),
    "uit_cover_plate": Retrofit(
        "ultrasonic impact treatment of a cover-plate end weld under dead load", category="C",
        source="G14.1 3.5.4 (Roy et al. 2003: E' cover plate treated under dead load -> C)"),
    "gta_remelt_or_peen_cover_plate": Retrofit(
        "GTA remelt or peening of cover-plate end welds (Yellow Mill Pond)", category="C",
        source="Repair Manual (E' -> C, 56 million truck passages)"),
    "bolted_splice": Retrofit(
        "bolted splice plates across a cracked or cover-plated flange", category="B",
        source="G14.1 4.1.2; Repair Manual (Purdue tests, severed-flange design, slip critical)"),
    "bolted_doubler": Retrofit(
        "high-strength bolted doubler or connection", category="B", source="Repair Manual"),
    "welded_doubler": Retrofit(
        "welded doubler", category="E", source="Repair Manual: E or worse -- bolt doublers"),
    "radius_gusset_termination": Retrofit(
        "2 in. (or larger) radius cut at a fillet-welded gusset termination", category="D",
        best="D", source="G14.1 (E -> D; never better than D for fillet-welded gussets)"),
    "web_isolation_holes": Retrofit(
        "web plate isolation holes at a weld termination", category="C",
        source="G14.1 4.4.2.3 (E -> about C)"),
    "backing_bar_transition": Retrofit(
        "gradual transition cut at a backing-bar termination", category="C",
        source="G14.1 (E/E' -> about C, by radius)"),
    "grind_groove_weld": Retrofit(
        "transverse groove weld reinforcement ground flush (after NDT)", category="B",
        source="G14.1 4.6.2.1 (C -> B)"),
}


def improve(category: str, steps: int, best: str | None = None) -> str:
    """``category`` moved ``steps`` up the unprimed ladder, capped at
    ``best``."""
    i = max(0, _ON_LADDER[category] - steps)
    if best is not None:
        i = max(i, _ON_LADDER[best])
    return LADDER[i]


def retrofit_category(original: str, retrofit: str, *,
                      distortion_induced: bool = False) -> tuple[str, Retrofit]:
    """``(category after, Retrofit)``: a retrofit with a fixed resulting
    category never makes a detail worse than it was; ``load_induced_only``
    retrofits (the pretensioned bolt in a drilled hole) are refused for
    distortion-induced cracking, where the hole's flexibility is the point."""
    r = RETROFITS[retrofit]
    if distortion_induced and r.load_induced_only:
        raise ValueError(f"{retrofit}: not for distortion-induced cracks ({r.source})")
    if r.category is not None:
        new = r.category
        if _ON_LADDER[new] > _ON_LADDER[original]:
            new = original                     # a retrofit does not downgrade
    else:
        new = improve(original, r.improvement, r.best)
    return new, r


def crack_arrest_hole_diameter(stress_range: float, half_crack: float, fy: float, *,
                               edge_crack: bool = False, minimum: float = 1.0) -> float:
    """Hole diameter (in.) that arrests a crack of half-length ``half_crack``
    (in.) under nominal stress range ``stress_range`` (ksi) in steel of
    yield ``fy`` (ksi): ``S_r^2 pi a / (8 F_y)`` from ``dK / sqrt(rho) <= 4
    sqrt(F_y)`` with the center-cracked plate ``dK = S_r sqrt(pi a)``; not
    less than ``minimum`` (1.0 in.), and 25 % larger for an edge crack
    (Repair Manual Figs. 18-20)."""
    d = stress_range ** 2 * math.pi * half_crack / (8.0 * fy)
    if edge_crack:
        d *= 1.25
    return max(d, minimum)


def drilled_holes_suffice_for_web_gap(in_plane_bending: float, out_of_plane_range: float,
                                      *, skewed: bool = False) -> bool:
    """Whether drilled holes alone can stop a distortion-induced web-gap
    crack (Lehigh, Repair Manual): in-plane bending stress below 6 ksi and
    out-of-plane stress range below 15 ksi, and not on a skewed bridge."""
    return in_plane_bending < 6.0 and out_of_plane_range < 15.0 and not skewed


def retrofitted_life(stress_range: float, original: str, retrofit: str,
                     traffic: mbe_fatigue.Traffic, *, distortion_induced: bool = False,
                     **kw) -> mbe_fatigue.FatigueLife:
    """MBE Section 7 life of the detail after ``retrofit``, from the day of
    the retrofit (no cycles consumed by the new detail)."""
    category, _ = retrofit_category(original, retrofit, distortion_induced=distortion_induced)
    return mbe_fatigue.evaluate(stress_range, category, traffic, consumed=0.0, **kw)
