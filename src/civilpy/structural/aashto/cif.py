"""Screening steel bridge details for susceptibility to constraint-induced
fracture (CIF) -- the "CIF Evaluation Scorecard" of the NSBA *Guide to
Evaluating Details for Susceptibility to Constraint-Induced Fracture*
(B304, 2023, rev. 2024; from FHWA-HIF-21-046, Coletti et al. 2021).

CIF needs three conditions together, each scored for the area of interest:

1. **Tensile stress** (including residual stress): 1.0 in a zone of net
   applied tension or stress reversal, 0.0 in permanent compression.
2. **Constraint** preventing local yielding: 1.0 where three or more welded
   steel elements intersect, roughly orthogonally, *without* a proper
   constraint-relief gap; 0.5 where two intersect, or three or more *with*
   a proper gap; 0.0 with no intersecting welded elements.
3. **Planar discontinuity** (crack- or notch-like) approximately
   *perpendicular* to the primary tensile stress: 1.0; parallel, or none:
   0.0.

The total is screened (B304 4.1): new designs are HIGH at 2.5 or more;
existing structures are HIGH at 3.0 and MAY be high at 2.5 (further
evaluation or a conservative retrofit), LOW at 2.0 or less.

Whether a constraint-relief gap is "proper" is a judgment the guide leaves
qualitative (it rejects the old 1/4 in. weld-toe-gap rule as insufficient
on its own); pass ``relief_gap=None`` when it is not settled and the
scorecard returns the range the guide reports (e.g. 1.5 to 2.0).
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

from dataclasses import dataclass

NEW_DESIGN_HIGH = 2.5
EXISTING_HIGH = 3.0
EXISTING_MAY_BE_HIGH = 2.5


def stress_score(stress: str) -> float:
    """Condition 1: ``"tension"`` or ``"reversal"`` -> 1.0,
    ``"compression"`` (permanent) -> 0.0."""
    s = stress.lower()
    if s in ("tension", "reversal", "stress reversal"):
        return 1.0
    if s in ("compression", "permanent compression"):
        return 0.0
    raise ValueError(f"stress must be tension, reversal or compression, not {stress!r}")


def constraint_score(intersecting_elements: int, relief_gap: bool | None = False) -> tuple[float, float]:
    """Condition 2 as ``(low, high)``: no intersecting welded elements 0.0;
    two 0.5; three or more 1.0 without a proper constraint-relief gap and
    0.5 with one (``relief_gap=None``: not settled, 0.5 to 1.0)."""
    if intersecting_elements < 2:
        return 0.0, 0.0
    if intersecting_elements == 2:
        return 0.5, 0.5
    if relief_gap is None:
        return 0.5, 1.0
    return (0.5, 0.5) if relief_gap else (1.0, 1.0)


def planar_score(planar: str | None) -> float:
    """Condition 3: ``"perpendicular"`` -> 1.0, ``"parallel"`` or None
    (no planar discontinuity) -> 0.0."""
    if planar is None or planar.lower() in ("parallel", "none", "not present"):
        return 0.0
    if planar.lower() == "perpendicular":
        return 1.0
    raise ValueError(f"planar must be perpendicular, parallel or None, not {planar!r}")


def classify(total: float, *, existing: bool) -> str:
    """``"high"``, ``"may be high"`` (existing structures at 2.5) or
    ``"low"`` (B304 4.1)."""
    if existing:
        if total >= EXISTING_HIGH:
            return "high"
        if total >= EXISTING_MAY_BE_HIGH:
            return "may be high"
        return "low"
    return "high" if total >= NEW_DESIGN_HIGH else "low"


@dataclass(frozen=True)
class CIFDetail:
    """One detail (area of interest) for the scorecard: the stress state,
    how many welded steel elements intersect there, whether a proper
    constraint-relief gap is provided (None: not settled) and the
    orientation of any planar discontinuity."""

    name: str
    stress: str
    intersecting_elements: int
    planar: str | None = None
    relief_gap: bool | None = False

    def scorecard(self, *, existing: bool = True) -> dict:
        s1 = stress_score(self.stress)
        c_lo, c_hi = constraint_score(self.intersecting_elements, self.relief_gap)
        s3 = planar_score(self.planar)
        lo, hi = s1 + c_lo + s3, s1 + c_hi + s3
        return {"detail": self.name, "tensile/residual stress": s1,
                "degree of constraint": (c_lo, c_hi) if c_lo != c_hi else c_lo,
                "planar discontinuity": s3, "total": (lo, hi) if lo != hi else lo,
                "susceptibility": (classify(lo, existing=existing), classify(hi, existing=existing))
                if lo != hi else classify(lo, existing=existing),
                "existing": existing}


def screen(details, *, existing: bool = True) -> list[dict]:
    """Scorecards for many details, worst first (by the upper total)."""
    cards = [d.scorecard(existing=existing) for d in details]

    def upper(c):
        t = c["total"]
        return t[1] if isinstance(t, tuple) else t

    return sorted(cards, key=upper, reverse=True)
