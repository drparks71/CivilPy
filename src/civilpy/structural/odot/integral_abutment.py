#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT ICD-1-20 / ICD-2-18 - Integral Construction Details for steel beam
and girder bridges (ICD-1-20) and prestressed I-beam bridges (ICD-2-18) on
flexible abutments.

The integral abutment of the sheets: a **3'-0" pile cap** (substructure,
Class QC1) on a **single row of piles** centred under the bearings (piles
embedded 2'-0" into the cap), a **3'-0" end diaphragm** (superstructure,
Class QC2) cast around the beam ends on elastomeric bearing assemblies,
protruding 1'-6" past each edge of deck under the railing, with a 6"
approach-slab seat along its back face; **turned-back wingwalls** 2'-6"
long behind a 2" PEJF at each diaphragm end; porous backfill and a 6"
perforated pipe behind the cap; 2H:1V slope protection in front.

What is cataloged (sheet 4 General Notes, revisions 01-21-2022 /
01-19-2024): the limits (tangent or curved alignment, skew <= 30 deg, the
maximum permissible expansion length by skew and beam material, pile
spacing between 3 pile diameters and 8'-0", at least 4 piles, cap height
<= 7'-6", no settlement concerns), the allowable pile sizes with their
minimum friction lengths in clay and sand, the design data, and the
reinforcing steel list (bar marks, types and the fixed legs).  The sheet's
own caution applies: *treat the dimensions, construction joints and
reinforcing as minimum values and perform a complete design*.

:func:`layout_integral_abutment` returns the drawable subset in a local
frame - ``x`` along the abutment (right positive), ``y`` toward higher
stations (the roadway), ``z`` up from the bridge seat (top of cap) - the
same ``x + y tan(skew)`` shear as the other substructure sheets, so a
skewed abutment's ends come out parallel to the roadway.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SCD = "ICD-1-20"
SCD_PS = "ICD-2-18"
REVISION = "01-19-2024"
REVISION_PS = "01-19-2024"

Point = tuple[float, float, float]

# ── fixed dimensions (ft unless noted) ───────────────────────────────────
CAP_WIDTH_FT = 3.0                     # SECTION D-D: 1'-6" each side of the bearing / pile line
CAP_HEIGHT_MIN_FT = 3.0                # SECTION D-D / E-E
CAP_HEIGHT_MAX_FT = 7.5                # General Notes: "shall not exceed 7'-6""
PILE_EMBED_FT = 2.0                    # SECTION D-D: 2'-0" into the cap
DIAPHRAGM_THICKNESS_FT = 3.0           # BRIDGE LIMITS 3'-0" (back face to front face)
DIAPHRAGM_PROTRUSION_FT = 1.5          # SECTION A-A: 1'-6" past the edge of deck under the railing
APPROACH_SEAT_WIDTH_FT = 1.0           # SECTION D-D: 1'-0" ledge behind the bearing line
APPROACH_SEAT_DEPTH_IN = 6.0           # "6" APPROACH SLAB SEAT"; height H matches the approach slab
WINGWALL_LENGTH_FT = 2.5               # PART PLAN: 2'-6" turned back along the roadway
WINGWALL_THICKNESS_FT = 1.5            # SECTION E-E
WINGWALL_JOINT_IN = 2.0                # 2" PEJF between the diaphragm end and the wingwall
APPROACH_JOINT_IN = 1.0                # 1" PEJF at the approach slab
NEOPRENE_SHEET_WIDTH_FT = 3.0          # 3' wide, centred on the joint
RAILING_TRANSITION_FT = 14.0           # 14'-0" railing transition
EMBANKMENT_SLOPE = 2.0                 # 2H:1V or flatter
SLOPE_COVER_MIN_IN = 6.0               # 6" min from the top of slope to the cap
EMBANKMENT_MIN_FT = 4.0                # 4'-0" min along the slope
PS_BEAM_EMBED_MIN_FT = 1.0 + 8.0 / 12.0   # ICD-2-18: 1'-8" minimum beam embedment in the diaphragm
PS_LEVEL_SEAT_FT = 3.0                 # ICD-2-18: 3'-0" level seat

MAX_SKEW_DEG = 30.0
MIN_PILES = 4
MAX_PILE_SPACING_FT = 8.0
MIN_PILE_SPACING_DIAMETERS = 3.0

# maximum permissible expansion length (ft) at 0 and 30 deg skew; straight-line between
EXPANSION_LENGTH_FT = {"steel": (267.0, 133.0), "ps_i": (333.0, 166.5)}

CONCRETE_SUPERSTRUCTURE_KSI = 4.5      # Class QC2 (diaphragm)
CONCRETE_SUBSTRUCTURE_KSI = 4.0        # Class QC1 (pile cap)
REBAR_YIELD_KSI = 60.0
STEEL_PILE_YIELD_KSI = 50.0            # ASTM A572
DESIGN_LOADING = "HL-93; FWS 0.060 ksf"


@dataclass(frozen=True)
class PileRow:
    """One line of the sheet's pile table: minimum friction pile length (ft)."""
    size: str
    min_length_clay_ft: float
    min_length_sand_ft: float
    diameter_in: float          # HP: diagonal between flange tips (General Notes); CIP: nominal


def _hp_diagonal(d_in: float, bf_in: float) -> float:
    return math.hypot(d_in, bf_in)


PILE_TABLE: dict[str, PileRow] = {
    "HP10X42": PileRow("HP10X42", 30.0, 25.0, _hp_diagonal(9.70, 10.1)),
    "HP12X53": PileRow("HP12X53", 35.0, 25.0, _hp_diagonal(11.8, 12.0)),
    "HP14X73": PileRow("HP14X73", 40.0, 30.0, _hp_diagonal(13.6, 14.6)),
    "12IN_CIP": PileRow("12IN_CIP", 45.0, 30.0, 12.0),
    "14IN_CIP": PileRow("14IN_CIP", 50.0, 35.0, 14.0),
}


@dataclass(frozen=True)
class RebarMark:
    mark: str
    bend_type: int
    length: str          # "*" = varies
    a: str
    b: str
    c: str = ""


# sheet 4 REINFORCING STEEL LIST (ICD-1-20)
REBAR_LIST: tuple[RebarMark, ...] = (
    RebarMark("A401", 3, "9'-6\"", "2'-6\"", "2'-0\""),
    RebarMark("A501", 1, "*", "2'-8\"", "*"),
    RebarMark("A502", 1, "*", "2'-2\"", "*"),
    RebarMark("A503", 1, "SERIES *", "2'-2\"", "SERIES *"),
    RebarMark("A504", 1, "*", "2'-2\"", "*"),
    RebarMark("A505", 1, "*", "2'-2\"", "*"),
    RebarMark("A506", 19, "*", "*", "", "*"),
    RebarMark("A601", 26, "*", "", ""),
    RebarMark("D401", 1, "8'-1\"", "1'-4\"", "3'-6\""),
    RebarMark("D501", 1, "*", "2'-8\"", "*"),
    RebarMark("D502", 2, "*", "2'-2\"", "*"),
    RebarMark("D801", 18, "*", "", ""),
)
MIN_SIDE_FACE_BARS = "5-#6 each side face of the pile cap, spacing <= 1'-0\""
MIN_LAP_LENGTH_FT = 2.0 + 5.0 / 12.0   # #5 vertical bars in diaphragm and pile cap: 2'-5"


def rebar_mark(mark: str) -> RebarMark:
    for r in REBAR_LIST:
        if r.mark == mark:
            return r
    raise KeyError(f"{SCD} has no bar mark {mark!r}")


def _norm(size: str) -> str:
    return size.upper().replace('"', "IN").replace("_", "").replace(" ", "").replace("-", "")


def pile_row(size: str) -> PileRow:
    """The table line for ``"HP12X53"`` / ``"HP12x53"`` / ``'12" CIP'`` / ``"12IN_CIP"``."""
    key = _norm(size)
    for name, row in PILE_TABLE.items():
        if _norm(name) == key:
            return row
    raise KeyError(f"{SCD} allows piles {sorted(PILE_TABLE)}; {size!r} needs Department approval")


def min_pile_length_ft(size: str, soil: str = "clay") -> float:
    """Minimum friction pile length from the sheet's table."""
    row = pile_row(size)
    if soil not in ("clay", "sand"):
        raise ValueError("soil must be 'clay' or 'sand'")
    return row.min_length_clay_ft if soil == "clay" else row.min_length_sand_ft


def max_expansion_length_ft(skew_deg: float, beam_type: str = "steel") -> float:
    """Maximum permissible expansion length, straight-line between the 0 and
    30 deg values (2/3 of the movement assumed in one direction)."""
    if beam_type not in EXPANSION_LENGTH_FT:
        raise ValueError("beam_type must be 'steel' (ICD-1-20) or 'ps_i' (ICD-2-18)")
    s = abs(skew_deg)
    if s > MAX_SKEW_DEG + 1e-9:
        raise ValueError(f"integral abutments are limited to {MAX_SKEW_DEG:g} deg skew; {skew_deg:g} deg exceeds it")
    lo, hi = EXPANSION_LENGTH_FT[beam_type]
    return lo + (hi - lo) * s / MAX_SKEW_DEG


def min_pile_spacing_ft(size: str) -> float:
    return MIN_PILE_SPACING_DIAMETERS * pile_row(size).diameter_in / 12.0


# ── input / layout ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntegralAbutmentInput:
    """Project-supplied dimensions.  ``width_ft`` is the deck out-to-out at
    the abutment (the diaphragm protrudes 1'-6" past each edge);
    ``diaphragm_height_ft`` runs from the bridge seat (top of cap) to the
    top of deck; ``cap_height_ft`` from the seat down to the cap bottom."""
    width_ft: float
    skew_deg: float
    n_piles: int
    pile_spacing_ft: float
    cap_height_ft: float
    diaphragm_height_ft: float
    pile_size: str = "HP12X53"
    beam_type: str = "steel"                  # "steel" | "ps_i"
    approach_slab_thickness_in: float = 15.0  # H of the seat matches the approach slab (AS-1-15)
    wingwall_height_ft: float | None = None   # default: the diaphragm height


@dataclass(frozen=True)
class IntegralAbutmentLayout:
    inputs: IntegralAbutmentInput
    pile_row: PileRow
    length_ft: float                                   # cap / diaphragm length along the abutment
    cap_outline: tuple[Point, Point, Point, Point]     # plan at the seat (z = 0), extrudes down cap_height_ft
    pile_points: tuple[Point, ...]                     # at the pile tops, z = -cap_height + PILE_EMBED
    diaphragm_outline: tuple[Point, Point, Point, Point]   # plan at the seat, extrudes up diaphragm_height_ft
    seat_notch: tuple[Point, Point, Point, Point]      # approach slab seat (plan), depth approach_slab_thickness
    wingwall_left: tuple[Point, Point, Point, Point]   # vertical quads (outside face), from the seat up
    wingwall_right: tuple[Point, Point, Point, Point]
    max_expansion_length_ft: float
    min_pile_length_ft: float
    notes: tuple[str, ...] = field(default_factory=tuple)


def layout_integral_abutment(inp: IntegralAbutmentInput) -> IntegralAbutmentLayout:
    """The drawable subset of ICD-1-20 / ICD-2-18 in the local frame.

    Raises ``ValueError`` for a non-positive width / spacing / height,
    fewer than :data:`MIN_PILES`, a pile spacing outside 3 diameters ..
    8'-0", a cap height outside 3'-0" .. 7'-6", a skew over 30 deg, or an
    unknown beam type; ``KeyError`` for a pile size not in the table."""
    for name in ("width_ft", "pile_spacing_ft", "cap_height_ft", "diaphragm_height_ft"):
        if getattr(inp, name) <= 0.0:
            raise ValueError(f"IntegralAbutmentInput.{name} must be positive")
    if inp.n_piles < MIN_PILES:
        raise ValueError(f"integral abutments are supported on at least {MIN_PILES} piles")
    row = pile_row(inp.pile_size)
    s_min = min_pile_spacing_ft(inp.pile_size)
    if inp.pile_spacing_ft > MAX_PILE_SPACING_FT + 1e-9 or inp.pile_spacing_ft < s_min - 1e-9:
        raise ValueError(f"pile spacing must be between 3 diameters ({s_min:.2f} ft for {row.size}) and "
                         f"{MAX_PILE_SPACING_FT:g} ft; got {inp.pile_spacing_ft:g}")
    if not CAP_HEIGHT_MIN_FT - 1e-9 <= inp.cap_height_ft <= CAP_HEIGHT_MAX_FT + 1e-9:
        raise ValueError(f"cap height must be {CAP_HEIGHT_MIN_FT:g} .. {CAP_HEIGHT_MAX_FT:g} ft")
    expansion = max_expansion_length_ft(inp.skew_deg, inp.beam_type)   # validates skew and beam type

    tan_skew = math.tan(math.radians(inp.skew_deg))
    L = inp.width_ft + 2.0 * DIAPHRAGM_PROTRUSION_FT
    half_l, half_w = L / 2.0, CAP_WIDTH_FT / 2.0

    def pt(x: float, y: float, z: float) -> Point:
        return (x + y * tan_skew, y, z)

    cap = (pt(-half_l, -half_w, 0.0), pt(half_l, -half_w, 0.0), pt(half_l, half_w, 0.0), pt(-half_l, half_w, 0.0))
    span = (inp.n_piles - 1) * inp.pile_spacing_ft
    if span > L - 2.0 * 1.0:
        raise ValueError(f"{inp.n_piles} piles at {inp.pile_spacing_ft:g} ft do not fit a {L:.2f} ft cap")
    z_pile = -inp.cap_height_ft + PILE_EMBED_FT
    piles = tuple(pt(-span / 2.0 + i * inp.pile_spacing_ft, 0.0, z_pile) for i in range(inp.n_piles))
    # the diaphragm sits on the cap, same plan (BRIDGE LIMITS 3'-0")
    diaphragm = cap
    # approach slab seat: a ledge APPROACH_SEAT_WIDTH wide along the back (low-station) face
    seat = (pt(-half_l, -half_w, inp.diaphragm_height_ft), pt(half_l, -half_w, inp.diaphragm_height_ft),
            pt(half_l, -half_w + APPROACH_SEAT_WIDTH_FT, inp.diaphragm_height_ft),
            pt(-half_l, -half_w + APPROACH_SEAT_WIDTH_FT, inp.diaphragm_height_ft))
    h_w = inp.wingwall_height_ft if inp.wingwall_height_ft is not None else inp.diaphragm_height_ft
    joint = WINGWALL_JOINT_IN / 12.0
    # wingwalls turn back along the roadway (toward lower stations) from behind the diaphragm ends
    def wing(sign: float):
        x = sign * (half_l + joint)
        # PART PLAN: the 2'-6" wingwall starts at the back face of the diaphragm (approach side) and runs
        # toward the bridge alongside the diaphragm end, the 2" PEJF between them
        return (pt(x, -half_w, 0.0), pt(x, -half_w, h_w), pt(x, -half_w + WINGWALL_LENGTH_FT, h_w),
                pt(x, -half_w + WINGWALL_LENGTH_FT, 0.0))
    scd = SCD_PS if inp.beam_type == "ps_i" else SCD
    notes = (
        f"{scd} integral abutment: cap {L:.2f} x {CAP_WIDTH_FT:g} ft x {inp.cap_height_ft:g} ft deep on "
        f"{inp.n_piles} {row.size} piles @ {inp.pile_spacing_ft:g} ft (single row, embedded {PILE_EMBED_FT:g} ft), "
        f"diaphragm {DIAPHRAGM_THICKNESS_FT:g} ft thick x {inp.diaphragm_height_ft:g} ft, skew {inp.skew_deg:g} deg",
        f"Limits: skew <= {MAX_SKEW_DEG:g} deg; max expansion length {expansion:.0f} ft at this skew "
        f"({inp.beam_type}); pile spacing {s_min:.2f}-{MAX_PILE_SPACING_FT:g} ft; >= {MIN_PILES} piles; "
        f"cap height <= {CAP_HEIGHT_MAX_FT:g} ft; not where settlement is a concern",
        f"Minimum friction pile length {row.size}: clay {row.min_length_clay_ft:g} ft, sand {row.min_length_sand_ft:g} ft; "
        "shorter needs calculations (BDM 305.3.5.7 for refusal on bedrock)",
        "Sheet dimensions and reinforcing are minimum values - perform a complete design; do not reference the "
        "SCD in the contract plans.  Not modeled: elastomeric bearing assembly, vent holes, neoprene sheeting, "
        "PEJF, porous backfill and pipes, slope protection, reinforcing (see REBAR_LIST).",
    )
    return IntegralAbutmentLayout(inputs=inp, pile_row=row, length_ft=L, cap_outline=cap, pile_points=piles,
                                  diaphragm_outline=diaphragm, seat_notch=seat, wingwall_left=wing(-1.0),
                                  wingwall_right=wing(1.0), max_expansion_length_ft=expansion,
                                  min_pile_length_ft=row.min_length_clay_ft, notes=notes)
