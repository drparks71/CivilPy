#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT SICD-1-21 - Semi-Integral Construction Details for steel beam and
girder bridges on rigid abutments, with the SICD-2-14 semi-integral
abutment diaphragm guide.

The semi-integral abutment of the sheet: a **rigid abutment** (substructure)
- a 2'-0" stem on a 3'-0" deep footing, 6'-0" wide on two rows of piles
(SECTION C-C / D-D on piles) or 4'-0" wide on 3'-0" drilled shafts - whose
top is the bridge seat; the superstructure's **3'-0" end diaphragm** cast
around the beam ends sits on elastomeric bearing assemblies 9" above the
seat (expanded polystyrene filler or removable forms keep the clearance),
protruding 1'-6" past the edge of deck under the railing with a 6"
approach-slab seat along its back; **turned-back wingwalls** 2'-6" long
behind a 2" PEJF; neoprene sheeting 3' wide on the joint; a 3" minimum
clearance between the neoprene and the finished ground; guide pedestals
per SICD-2-14 (ITEM 511, each) keep the diaphragm aligned.

:func:`layout_semi_integral_abutment` returns the drawable subset in the
same local frame as :mod:`~civilpy.structural.odot.integral_abutment`
(``x`` along the abutment, ``y`` toward higher stations, ``z`` up from the
bridge seat).  The sheet's reinforcing (A501 .. A803, D801) is minimum and
not modeled; the sheet's own caution: provide a complete design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SCD = "SICD-1-21"
REVISION = "01-19-2024"
SCD_GUIDE = "SICD-2-14"

Point = tuple[float, float, float]

STEM_THICKNESS_FT = 2.0                # SECTION C-C: 2'-0" at the seat
FOOTING_DEPTH_FT = 3.0                 # 3'-0"
FOOTING_WIDTH_PILES_FT = 6.0           # on piles: 6'-0" (4 x 1'-6")
FOOTING_WIDTH_SHAFTS_FT = 4.0          # on drilled shafts: 4'-0"
PILE_ROW_OFFSET_FT = 1.5               # two pile rows at 1'-6" either side of the bearing line
PILE_EMBED_FT = 1.0                    # 1'-0" into the footing
SHAFT_DIAMETER_FT = 3.0                # 3'-0" dia shown
DIAPHRAGM_THICKNESS_FT = 3.0           # bridge limit 3'-0"
DIAPHRAGM_PROTRUSION_FT = 1.5          # 1'-6" past the edge of deck
DIAPHRAGM_CLEARANCE_IN = 9.0           # seat to the bottom of the diaphragm (bearing assembly + filler)
APPROACH_SEAT_WIDTH_FT = 1.0
APPROACH_SEAT_DEPTH_IN = 6.0
WINGWALL_LENGTH_FT = 2.5
WINGWALL_THICKNESS_FT = 1.5
WINGWALL_JOINT_IN = 2.0
NEOPRENE_SHEET_WIDTH_FT = 3.0
NEOPRENE_GROUND_CLEARANCE_IN = 3.0     # min 3" between the neoprene and finished ground
GROUND_CLEARANCE_MIN_IN = 6.0          # 6" min under the diaphragm
RAILING_TRANSITION_FT = 14.0
EMBANKMENT_SLOPE = 2.0
EMBANKMENT_MIN_FT = 4.0
MAX_PILE_SPACING_FT = 8.0              # sheet 4/5: 8'-0" maximum
GUIDE_PAY_ITEM = ("511", "EACH", "SEMI-INTEGRAL DIAPHRAGM GUIDE")
GUIDE_RUB_PLATE = "13 gage stainless steel (minimum), Type 304, both sides of the guide"

FOUNDATIONS = ("piles", "shafts")


@dataclass(frozen=True)
class SemiIntegralAbutmentInput:
    """``width_ft`` is the deck out-to-out; ``stem_height_ft`` from the top of
    footing to the bridge seat; ``diaphragm_height_ft`` from the bottom of the
    diaphragm to the top of deck; ``n_supports`` / ``support_spacing_ft`` are
    the piles per row (two rows) or the drilled shafts (one row)."""
    width_ft: float
    skew_deg: float
    stem_height_ft: float
    diaphragm_height_ft: float
    n_supports: int
    support_spacing_ft: float
    foundation: str = "piles"
    pile_size: str = "HP12X53"
    guides: int = 2                           # SICD-2-14 diaphragm guides per abutment
    wingwall_height_ft: float | None = None


@dataclass(frozen=True)
class SemiIntegralAbutmentLayout:
    inputs: SemiIntegralAbutmentInput
    length_ft: float
    stem_outline: tuple[Point, Point, Point, Point]        # plan at the seat (z = 0), extrudes down stem_height_ft
    footing_outline: tuple[Point, Point, Point, Point]     # plan at the footing bottom, extrudes up FOOTING_DEPTH
    support_points: tuple[Point, ...]                      # pile tops (two rows) or shaft tops
    diaphragm_outline: tuple[Point, Point, Point, Point]   # plan at the diaphragm bottom (z = clearance)
    diaphragm_bottom_ft: float
    seat_notch: tuple[Point, Point, Point, Point]
    wingwall_left: tuple[Point, Point, Point, Point]
    wingwall_right: tuple[Point, Point, Point, Point]
    guide_points: tuple[Point, ...]                        # SICD-2-14 guides on the seat
    notes: tuple[str, ...] = field(default_factory=tuple)


def layout_semi_integral_abutment(inp: SemiIntegralAbutmentInput) -> SemiIntegralAbutmentLayout:
    """Raises ``ValueError`` for a non-positive dimension, an unknown
    foundation, fewer than 2 supports, or a support spacing over 8'-0"."""
    for name in ("width_ft", "stem_height_ft", "diaphragm_height_ft", "support_spacing_ft"):
        if getattr(inp, name) <= 0.0:
            raise ValueError(f"SemiIntegralAbutmentInput.{name} must be positive")
    if inp.foundation not in FOUNDATIONS:
        raise ValueError(f"foundation must be one of {FOUNDATIONS}")
    if inp.n_supports < 2:
        raise ValueError("at least 2 supports per row")
    if inp.support_spacing_ft > MAX_PILE_SPACING_FT + 1e-9:
        raise ValueError(f"support spacing is {MAX_PILE_SPACING_FT:g} ft maximum")

    tan_skew = math.tan(math.radians(inp.skew_deg))
    L = inp.width_ft + 2.0 * DIAPHRAGM_PROTRUSION_FT
    half_l = L / 2.0

    def pt(x: float, y: float, z: float) -> Point:
        return (x + y * tan_skew, y, z)

    def rect(half_w: float, z: float):
        return (pt(-half_l, -half_w, z), pt(half_l, -half_w, z), pt(half_l, half_w, z), pt(-half_l, half_w, z))

    stem = rect(STEM_THICKNESS_FT / 2.0, 0.0)
    z_ftg_bottom = -inp.stem_height_ft - FOOTING_DEPTH_FT
    ftg_w = FOOTING_WIDTH_PILES_FT if inp.foundation == "piles" else FOOTING_WIDTH_SHAFTS_FT
    footing = rect(ftg_w / 2.0, z_ftg_bottom)
    span = (inp.n_supports - 1) * inp.support_spacing_ft
    if span > L - 2.0:
        raise ValueError(f"{inp.n_supports} supports at {inp.support_spacing_ft:g} ft do not fit a {L:.2f} ft abutment")
    xs = [-span / 2.0 + i * inp.support_spacing_ft for i in range(inp.n_supports)]
    if inp.foundation == "piles":
        z_top = z_ftg_bottom + PILE_EMBED_FT
        supports = tuple(pt(x, y, z_top) for y in (-PILE_ROW_OFFSET_FT, PILE_ROW_OFFSET_FT) for x in xs)
    else:
        supports = tuple(pt(x, 0.0, z_ftg_bottom) for x in xs)
    z_dia = DIAPHRAGM_CLEARANCE_IN / 12.0
    diaphragm = rect(DIAPHRAGM_THICKNESS_FT / 2.0, z_dia)
    z_top = z_dia + inp.diaphragm_height_ft
    half_w = DIAPHRAGM_THICKNESS_FT / 2.0
    seat = (pt(-half_l, -half_w, z_top), pt(half_l, -half_w, z_top),
            pt(half_l, -half_w + APPROACH_SEAT_WIDTH_FT, z_top), pt(-half_l, -half_w + APPROACH_SEAT_WIDTH_FT, z_top))
    h_w = inp.wingwall_height_ft if inp.wingwall_height_ft is not None else z_top
    joint = WINGWALL_JOINT_IN / 12.0

    def wing(sign: float):
        x = sign * (half_l + joint)
        # PART PLAN: the 2'-6" wingwall starts at the back face of the diaphragm (approach side) and runs
        # toward the bridge alongside the diaphragm end, the 2" PEJF between them
        return (pt(x, -half_w, 0.0), pt(x, -half_w, h_w), pt(x, -half_w + WINGWALL_LENGTH_FT, h_w),
                pt(x, -half_w + WINGWALL_LENGTH_FT, 0.0))

    n_g = max(int(inp.guides), 0)
    guides = tuple(pt(-half_l + L * (i + 1) / (n_g + 1), 0.0, 0.0) for i in range(n_g))
    notes = (
        f"{SCD} semi-integral abutment: stem {L:.2f} x {STEM_THICKNESS_FT:g} ft x {inp.stem_height_ft:g} ft on a "
        f"{ftg_w:g} x {FOOTING_DEPTH_FT:g} ft footing ({inp.foundation}: {len(supports)} supports), diaphragm "
        f"{DIAPHRAGM_THICKNESS_FT:g} ft thick x {inp.diaphragm_height_ft:g} ft seated {DIAPHRAGM_CLEARANCE_IN:g} in "
        f"above the seat, skew {inp.skew_deg:g} deg, {n_g} {SCD_GUIDE} guides",
        "Diaphragm guides are paid as ITEM 511 EACH (SICD-2-14); their concrete and steel are not in the plan "
        "quantities.  Elastomeric bearing assemblies per C&MS 516, galvanized; expanded polystyrene filler forms the "
        "clearance and is paid with the superstructure concrete.",
        "Sheet dimensions and reinforcing are minimum values - perform a complete design.  Not modeled: bearings, "
        "neoprene sheeting, PEJF, porous backfill and pipes, slope protection, reinforcing.",
    )
    return SemiIntegralAbutmentLayout(inputs=inp, length_ft=L, stem_outline=stem, footing_outline=footing,
                                      support_points=supports, diaphragm_outline=diaphragm, diaphragm_bottom_ft=z_dia,
                                      seat_notch=seat, wingwall_left=wing(-1.0), wingwall_right=wing(1.0),
                                      guide_points=guides, notes=notes)
