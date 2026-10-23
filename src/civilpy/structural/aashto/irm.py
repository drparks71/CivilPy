"""Internal redundancy of mechanically-fastened built-up steel members --
AASHTO Guide Specifications for Internal Redundancy of Mechanically-Fastened
Built-up Steel Members (2018, 2022 interims; "GS"), as implemented by the
NSBA IRM Evaluator v3.2 and explained in the NSBA Implementation Guide
(B010-20, Lloyd, Hebdon and Connor).

A riveted or bolted built-up member is internally redundant (an IRM rather
than a fracture-critical member) when it can lose any one component and
still carry the Redundancy II load with adequate strength and fatigue life;
its hands-on inspection can then follow a *special inspection* interval set
from the faulted-state fatigue life instead of the 24-month FCM interval.

The method, for each hypothetical failed component:

1. **Load factors** -- Redundancy II (GS Table 1.7.1-1): gamma_DC / gamma_DW
   / gamma_LL = 1.05 / 1.05 / 1.30 for members fabricated to the AWS D1.5
   fracture control plan (built 1979 or later), 1.15 / 1.25 / 1.50
   otherwise.  Fatigue: Fatigue II (0.80) truck with the member's impact,
   Fatigue I (1.75) for the infinite-life check.
2. **Faulted strength** (GS 2.2 / 2.1 and 2.3) -- the factored load over the
   remaining net and gross areas (or section moduli) against phi_u Fu and
   phi_y Fy.
3. **Faulted fatigue stress** -- the Fatigue II stress on the remaining
   section amplified for shear lag and local bending (axial: Xi_VL = 1.2,
   Xi_B = 1.04 + 0.3 (1 - N/6) for an exterior plate, GS Table 2.2.1-1;
   the 40-over-fastener rule of GS 2.2.1.1 for connection angles;
   flexural: the cover-plate adjustment beta_AF = 1 + 0.25 (1 + N/4),
   GS Eq. 2.1.2-3).
4. **Fatigue lives** (GS 2.5, MBE 7) -- unfaulted with the fastener detail
   (rivets and punched holes D, drilled bolted B; GS Table 2.5-2),
   faulted with category C (E' for punched holes) from today; Case I(a) /
   I(b) / II by which are infinite.
5. **Total remaining life** (GS Eq. 2.5.3-1) ``N_f = Y_f (1 - N_U / Y_U)``
   and the **special inspection interval** (GS Section 3).

:class:`MultiComponentAxialMember` is the multi-component axial evaluator
(built-up channels, boxes, I-sections; rolled channels with added plates).
Areas follow the evaluator's half-symmetry bookkeeping exactly.

Units: kips, inches, ksi.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field

from civilpy.structural.aashto import mbe_fatigue
from civilpy.structural.aashto.mbe_fatigue import GAMMA_FAT_I, GAMMA_FAT_II, Traffic

SHEAR_LAG_FACTOR = 1.2          # Xi_VL, GS Table 2.2.1-1
PHI_Y = 0.95
PHI_U = 0.80


# ── general provisions ──────────────────────────────────────────────────────


def built_to_fcp(year_built: int, override: bool = False) -> bool:
    """Whether the member is taken as fabricated to the AWS D1.5 fracture
    control plan: built 1979 or later, unless ``override`` says it was not."""
    return year_built >= 1979 and not override


def redundancy_ii_factors(fcp: bool) -> tuple[float, float, float]:
    """``(gamma_DC, gamma_DW, gamma_LL)`` of the Redundancy II load
    combination (GS Table 1.7.1-1)."""
    return (1.05, 1.05, 1.30) if fcp else (1.15, 1.25, 1.50)


def hole_diameter(d_fastener: float) -> float:
    """Standard hole: d + 1/16 in. below 1 in., d + 1/8 in. from 1 in. up
    (as the IRM Evaluator takes it)."""
    return d_fastener + (0.0625 if d_fastener < 1.0 else 0.125)


def unfaulted_category(fastener: str, punched: bool = False) -> str:
    """Fatigue category of the fastened connection in the unfaulted state
    (GS Table 2.5-2): D for rivets and punched holes, B for bolts in
    drilled or subpunched-and-reamed holes."""
    if fastener.lower() == "rivet" or punched:
        return "D"
    return "B"


def faulted_category(punched: bool = False) -> str:
    """Category of the faulted-state detail (GS Table 2.5-2): C, E' with
    holes punched full size."""
    return "E'" if punched else "C"


def bending_factor(n_plates: float) -> float:
    """Local bending amplification Xi_B = 1.04 + 0.3 (1 - N_AX / 6) for the
    failure of an exterior plate (GS Table 2.2.1-1), N_AX the plates in the
    half-symmetry section (webs of a box count 1/2 each)."""
    return 1.04 + 0.3 * (1.0 - n_plates / 6.0) if n_plates else 0.0


def cover_plate_adjustment(n_tension_cover_plates: int) -> float:
    """beta_AF = 1 + 0.25 (1 + N_FL / 4) for the flexural faulted state
    (GS Eq. 2.1.2-3)."""
    return 1.0 + 0.25 * (1.0 + n_tension_cover_plates / 4.0)


def _excel_even(x: float) -> float:
    """Excel ``EVEN``: round away from zero to the next even integer."""
    return 2.0 * math.ceil(x / 2.0 - 1e-12)


def special_inspection_interval(total_life: float, case: str) -> float:
    """Maximum special-inspection interval in years (GS Section 3, Tables
    3.1-1 and 3.1-2 as the evaluator applies them): 10 years for an
    infinite or a 20-year-plus total remaining life; otherwise half the
    life rounded up to an even number of years -- at least 2 for Case I(b),
    and for shorter lives (5 years or less) half the life, at most 2,
    rounded up to the half year."""
    if math.isinf(total_life) or total_life >= 20.0:
        return 10.0
    if case == "I(b)":
        return _excel_even(max(2.0, 0.5 * total_life))
    if total_life > 5.0:
        return _excel_even(0.5 * total_life)
    return math.ceil(min(2.0, 0.5 * total_life) / 0.5 - 1e-12) * 0.5


def fatigue_case(unfaulted_infinite: bool, faulted_infinite: bool) -> str:
    """GS 2.5 case: I(a) both infinite, I(b) infinite unfaulted only, II
    finite unfaulted."""
    if unfaulted_infinite:
        return "I(a)" if faulted_infinite else "I(b)"
    return "II"


def total_remaining_life(faulted_life: float, unfaulted_remaining: float,
                         years_in_service: float) -> float:
    """GS Eq. 2.5.3-1: ``N_f = Y_f (1 - N_U / Y_U)`` with ``Y_U`` the total
    unfaulted life (years in service plus remaining); ``Y_f`` alone when
    the unfaulted life is infinite."""
    if math.isinf(unfaulted_remaining):
        return faulted_life
    y_u = years_in_service + unfaulted_remaining
    return faulted_life * (1.0 - years_in_service / y_u)


# ── multi-component axial members (GS 2.2) ─────────────────────────────────


@dataclass(frozen=True)
class FlangePlate:
    """One plate of the half-symmetry section's flange stack ("flange" in
    the GS sense: the plates the angles connect, e.g. the web plate of a
    built-up channel).  Full-depth plates are PL-0 (innermost), PL-1f,
    PL-2f outward; partial-depth plates PL-1p.. sit between the angle
    legs.  ``holes`` across one transverse section and ``edge_to_hole``
    (distance from the plate edge to the first hole centre) as on the
    evaluator; ``net_strength`` overrides the strength net area for
    staggered holes (s^2/4g, LRFD 6.8.3)."""

    depth: float
    thickness: float
    holes: int = 0
    edge_to_hole: float | None = None
    net_strength: float | None = None


@dataclass(frozen=True)
class Angle:
    """A connection angle (two per half section): gross area, thickness,
    holes through the leg on the flange plate and through the other leg."""

    area: float
    thickness: float
    holes_vertical: int = 1
    holes_horizontal: int = 0


@dataclass(frozen=True)
class RolledChannel:
    """A rolled channel in the half section (with added plates)."""

    area: float
    t_flange: float
    t_web: float
    holes_web: int = 0
    holes_flange: int = 0


@dataclass(frozen=True)
class WebPlate:
    """A continuous top or bottom plate of a box (counts 1/2 in each half)."""

    width: float
    thickness: float
    hand_hole_width: float = 0.0
    holes: int = 0


@dataclass
class IRMResult:
    """Outcome of an IRM evaluation: faulted-state strength stresses per
    failure case and their D/C, the fatigue lives and case, the total
    remaining life and the special-inspection interval."""

    p_u: float
    stresses_net: dict
    stresses_gross: dict
    dc_net: float
    dc_gross: float
    strength_ok: bool
    unfaulted: mbe_fatigue.FatigueLife
    faulted: mbe_fatigue.FatigueLife
    faulted_stress_ranges: dict
    case: str
    total_life: float
    interval: float
    details: dict = field(default_factory=dict)


@dataclass
class MultiComponentAxialMember:
    """A multi-component built-up axial member (GS 2.2) as the IRM
    Multi-Component Evaluator describes it, by its half-symmetry section:

    * ``full_plates`` -- full-depth flange plates, innermost (PL-0) first
      (1 to 3); ``partial_plates`` -- partial-depth plates PL-1p.. (0 to 3)
    * ``angle`` -- the connection angle (two per half) or ``None``
    * ``channel`` -- a rolled channel instead of the plates-and-angles
      channel (``angle`` then ignored)
    * ``web_top`` / ``web_bot`` -- continuous box plates
    * ``i_section`` -- a built-up I: one flange plate with four angles,
      evaluated with the GS 2.2.1.1 angle rule and no plate bending factor

    Loads (kips, unfactored): ``p_dc``, ``p_dw``, ``p_ll`` (with impact) and
    ``p_fat`` (the fatigue truck with impact, before the Fatigue II
    factor)."""

    fy: float
    fu: float
    d_fastener: float
    full_plates: list[FlangePlate]
    partial_plates: list[FlangePlate] = field(default_factory=list)
    angle: Angle | None = None
    channel: RolledChannel | None = None
    web_top: WebPlate | None = None
    web_bot: WebPlate | None = None
    i_section: bool = False
    fastener: str = "rivet"
    punched: bool = False
    shear_lag: float = SHEAR_LAG_FACTOR

    @classmethod
    def from_builtup(cls, spec: str, *, fy: float, fu: float, d_fastener: float,
                     holes_per_web_plate: int = 2, angle_holes: tuple[int, int] = (1, 1),
                     holes_per_cover_plate: int = 2, edge_to_hole: float | None = None,
                     **kwargs) -> "MultiComponentAxialMember":
        """The member a plan-sheet spec describes (:mod:`civilpy.structural.
        builtup`, the shorthand ``"2P24x9/16 4L6x4x3/8"`` the BrIM truss
        model and :class:`~civilpy.structural.laced_member.LacedMember`
        use), in the evaluator's half-symmetry terms: each side's web plates
        are the full-depth "flange" plates (PL-0 innermost), the two angles
        on that side the connection angles, and top/bottom cover plates the
        box's continuous web plates.  Hole counts are per transverse section
        (two rivet lines through each web plate by default); the angle area
        is the catalogue area where :func:`~civilpy.structural.laced_member.
        angle_designation` knows the size, the sharp-cornered area
        otherwise."""
        from civilpy.structural import builtup
        from civilpy.structural.laced_member import angle_designation

        webs, covers, angles = builtup.parse(spec)
        n_w, depth, t_w = webs
        per_side = max(1, int(n_w // 2))
        plates = [FlangePlate(depth, t_w, holes_per_web_plate, edge_to_hole)
                  for _ in range(per_side)]
        _, la, lb, ta = angles
        _, area, _ = angle_designation(la, lb, ta)
        if not area:
            area = la * ta + (lb - ta) * ta
        angle = Angle(area, ta, *angle_holes)
        tops = {}
        if covers:
            n_c, w, tc = covers
            stack = WebPlate(w, tc * n_c / 2.0, holes=holes_per_cover_plate)
            tops = {"web_top": stack, "web_bot": stack}
        return cls(fy=fy, fu=fu, d_fastener=d_fastener, full_plates=plates, angle=angle,
                   **tops, **kwargs)

    # ── areas (half-symmetry bookkeeping of the evaluator) ──────────────

    @property
    def d_hole(self) -> float:
        return hole_diameter(self.d_fastener)

    def _components(self):
        """``{name: (gross, net_fatigue, net_strength)}`` of the half
        section; webs at full value (the halving is applied in the sums)."""
        h = self.d_hole
        out = {}
        names = ("PL-0", "PL-1f", "PL-2f")
        for name, p in zip(names, self.full_plates):
            g = p.depth * p.thickness
            n = g - p.holes * p.thickness * h
            out[name] = (g, n, p.net_strength if p.net_strength is not None else 0.0)
        for k, p in enumerate(self.partial_plates, start=1):
            g = p.depth * p.thickness
            n = g - p.holes * p.thickness * h
            out[f"PL-{k}p"] = (g, n, p.net_strength if p.net_strength is not None else 0.0)
        if self.channel is not None:
            c = self.channel
            g = c.area
            n = g - h * (c.t_flange * c.holes_flange + c.t_web * c.holes_web)
            out["channel"] = (g, n, 0.0)
        elif self.angle is not None:
            a = self.angle
            g = 2.0 * a.area
            n = g - (a.holes_vertical + a.holes_horizontal) * 2.0 * a.thickness * h
            out["angles"] = (g, n, 0.0)
        for name, w in (("web top", self.web_top), ("web bot", self.web_bot)):
            if w is not None:
                g = w.width * w.thickness
                n = g - w.hand_hole_width * w.thickness - w.thickness * h * w.holes
                out[name] = (g, n, 0.0)
        return out

    def _half(self, comps, k):
        webs = sum(v[k] for n, v in comps.items() if n.startswith("web"))
        rest = sum(v[k] for n, v in comps.items() if not n.startswith("web"))
        return rest + 0.5 * webs

    def areas(self) -> dict:
        """Unfaulted half and full gross / net areas."""
        c = self._components()
        ag_h, an_h = self._half(c, 0), self._half(c, 1)
        if self.i_section:
            extra_g = c.get("angles", (0, 0, 0))[0]
            extra_n = c.get("angles", (0, 0, 0))[1]
            return {"Ag_half": ag_h, "An_half": an_h,
                    "Ag": ag_h + extra_g, "An": an_h + extra_n}
        return {"Ag_half": ag_h, "An_half": an_h, "Ag": 2 * ag_h, "An": 2 * an_h}

    def plate_count(self) -> float:
        """N_AX: flange plates in the half section (+1 for a rolled
        channel) plus 1/2 per box web."""
        n_web = (0.5 if self.web_top is not None else 0.0) + (0.5 if self.web_bot is not None else 0.0)
        n_fl = len(self.full_plates) + len(self.partial_plates) + (1 if self.channel is not None else 0)
        return n_web + n_fl

    def bending_factor(self) -> float:
        return 1.0 if self.i_section else bending_factor(self.plate_count())

    def failure_cases(self) -> dict:
        """Faulted half-section areas per failure case, as the evaluator
        enumerates them: ``{case: {"An_half", "An", "Ag_half",
        "An_str_half", "An_str", "exterior"}}`` -- PL-0, PL-1f, PL-2f,
        PL-2p, PL-3p, the rolled channel and the larger box web.
        ``exterior`` marks the outermost plate (bending factor applies)."""
        c = self._components()
        an_h, ag_h = self._half(c, 1), self._half(c, 0)
        a = self.areas()
        str_h = self._half(c, 2)
        n_full, n_part = len(self.full_plates), len(self.partial_plates)
        out = {}

        def add(case, comp, exterior, i_sec_full_double=False):
            g, n, s = c[comp]
            f_an_h = an_h - n
            f_ag_h = ag_h - g
            if comp.startswith("web"):
                f_an_h, f_ag_h = an_h - 0.5 * n, ag_h - 0.5 * g
            if self.i_section and case == "PL-0":
                f_an = 2 * f_an_h
            elif comp.startswith("web"):
                f_an = 2 * f_an_h
            else:
                f_an = 2 * f_an_h + n
            # strength net areas (staggered-hole overrides where given)
            f_str_h = f_an_h if s == 0 else str_h - s
            if comp.startswith("web"):
                f_str_h = f_an_h if c[comp][2] == 0 else str_h
            if self.i_section and case == "PL-0":
                f_str = 2 * f_str_h
            elif s == 0:
                f_str = f_an
            else:
                f_str = 2 * f_str_h + s
            out[case] = {"An_half": f_an_h, "An": f_an, "Ag_half": f_ag_h,
                         "An_str_half": f_str_h, "An_str": f_str,
                         "exterior": exterior}

        if n_full >= 1:
            add("PL-0", "PL-0", n_full == 1 and not self.i_section)
        if n_full >= 2:
            add("PL-1f", "PL-1f", n_full == 2)
        if n_full >= 3:
            add("PL-2f", "PL-2f", n_full == 3)
        if n_part >= 2:
            add("PL-2p", "PL-2p", n_part == 2)
        if n_part >= 3:
            add("PL-3p", "PL-3p", n_part == 3)
        if self.channel is not None:
            add("channel", "channel", True)
        webs = [k for k in ("web top", "web bot") if k in c]
        if webs:
            add("web", max(webs, key=lambda k: c[k][1]), True)
        out["_unfaulted"] = a
        return out

    def angle_rule_required(self) -> bool:
        """GS 2.2.1.1: check the connection-angle failure (the
        40-over-fastener rule) for a built-up I, or for a built-up channel
        with one full-depth plate whose two angles have 1.3 times its gross
        area or more."""
        if self.angle is None or self.channel is not None:
            return False
        if self.i_section:
            return True
        if len(self.full_plates) >= 2:
            return False
        return 2.0 * self.angle.area >= 1.3 * self.full_plates[0].depth * self.full_plates[0].thickness

    # ── evaluation ──────────────────────────────────────────────────────

    def evaluate(self, *, p_dc: float, p_ll: float, p_fat: float,
                 traffic: Traffic, p_dw: float = 0.0,
                 fcp_override: bool = False, r_s: float = 1.0,
                 r_r: float = 1.0) -> IRMResult:
        """GS 1.7 / 2.2 / 2.3 / 2.5 / 3 for this member."""
        fcp = built_to_fcp(traffic.year_built, fcp_override)
        g_dc, g_dw, g_ll = redundancy_ii_factors(fcp)
        p_u = g_dc * p_dc + g_dw * p_dw + g_ll * p_ll
        p_fat2 = p_fat * GAMMA_FAT_II
        cases = self.failure_cases()
        unf = cases.pop("_unfaulted")
        fn, fg = {}, {}
        for name, k in cases.items():
            if k["An_str_half"] > 0:
                area = k["An_str"] if (self.i_section and name == "PL-0") else k["An_str_half"]
                fn[name] = 0.5 * p_u / area
            if k["Ag_half"] > 0:
                if self.i_section and name == "PL-0":
                    ag_full = 2 * k["Ag_half"]
                    fg[name] = 0.5 * p_u / ag_full
                else:
                    fg[name] = 0.5 * p_u / k["Ag_half"]
        f_un, f_ug = PHI_U * self.fu, PHI_Y * self.fy
        dc_n = max(fn.values()) / f_un if fn else 0.0
        dc_g = max(fg.values()) / f_ug if fg else 0.0

        # fatigue: unfaulted
        df_unf = p_fat2 / unf["An"]
        cat_u = unfaulted_category(self.fastener, self.punched)
        unfaulted = mbe_fatigue.evaluate(df_unf, cat_u, traffic, r_s=r_s, r_r=r_r)
        # faulted stress ranges (GS Eq. 2.2.1-1 with Xi_VL and Xi_B)
        xi_b = self.bending_factor()
        ranges = {}
        for name, k in cases.items():
            if k["An_half"] <= 0:
                continue
            amp = self.shear_lag * (xi_b if k["exterior"] else 1.0)
            ranges[name] = amp * 0.5 * p_fat2 / k["An_half"]
        if self.angle_rule_required():
            p_angle = (0.5 * 2.0 * self.angle.area / unf["Ag"]) * p_fat2
            pl0 = self.full_plates[0]
            ranges["angle (40-over-fastener)"] = (p_fat2 / unf["An"]
                                                  + 0.4 * p_angle / (pl0.thickness * pl0.edge_to_hole))
        df_f = max(ranges.values())
        cat_f = faulted_category(self.punched)
        faulted = mbe_fatigue.evaluate(df_f, cat_f, traffic, r_s=r_s, r_r=r_r, consumed=0.0)
        case = fatigue_case(unfaulted.infinite, faulted.infinite)
        years = traffic.year_current - traffic.year_built
        nf = total_remaining_life(faulted.remaining_years, unfaulted.remaining_years, years)
        return IRMResult(
            p_u=p_u, stresses_net=fn, stresses_gross=fg, dc_net=dc_n, dc_gross=dc_g,
            strength_ok=dc_n <= 1.0 and dc_g <= 1.0, unfaulted=unfaulted,
            faulted=faulted, faulted_stress_ranges=ranges, case=case, total_life=nf,
            interval=special_inspection_interval(nf, case),
            details={"fcp": fcp, "gammas": (g_dc, g_dw, g_ll), "P_FAT_II": p_fat2,
                     "Xi_B": xi_b, "N_AX": self.plate_count(), "areas": unf,
                     "angle_rule": self.angle_rule_required()})


# ── flexural members (GS 2.1) ───────────────────────────────────────────────


@dataclass(frozen=True)
class FlangeAngle:
    """A flange angle pair's catalogue properties (one angle): gross area,
    thickness, moment of inertia about the horizontal axis (the axis
    parallel to the flange, for the orientation used) and the distance
    from the outer horizontal leg face to that axis; fastener holes
    through the vertical leg (into the web, at ``web_hole_offsets`` from
    the outer face) and through the horizontal leg (into the flange)."""

    area: float
    thickness: float
    i_horizontal: float
    y_bar: float
    web_hole_offsets: tuple = (6.0,)
    flange_holes: int = 1


@dataclass
class FlexuralMember:
    """A riveted or bolted built-up I-girder for the IRM flexural
    evaluation (GS 2.1): web plate ``web_depth`` x ``web_t`` between
    flange angles ``depth_angles`` out to out, with cover plates on each
    flange (outermost first, as the evaluator numbers them), optionally
    composite with a deck (effective width ``b_eff``, thickness ``t_slab``,
    haunch ``b_haunch`` x ``t_haunch``, modular ratio ``n``).

    Coordinates follow the evaluator: y = 0 at the outer face of the
    tension-flange angles, tension cover plates below, the web centred in
    ``depth_angles``, compression angles and plates above.  Fastener holes
    are deducted piece by piece (angle legs, each cover plate, the web) for
    the net section.  Negative-moment regions use the noncomposite section
    (deck reinforcement ignored)."""

    fy: float
    fu: float
    d_fastener: float
    web_depth: float
    web_t: float
    depth_angles: float
    tension_plates: list[tuple[float, float]]          # (width, t), outermost first
    compression_plates: list[tuple[float, float]]
    tension_angle: FlangeAngle
    compression_angle: FlangeAngle
    composite: bool = False
    negative_moment: bool = False
    b_eff: float = 0.0
    t_slab: float = 0.0
    n: float = 8.0
    b_haunch: float = 0.0
    t_haunch: float = 0.0
    include_haunch: bool = True
    compression_flange_welded: bool = False
    extra_tension_flange_holes: int = 0
    extra_compression_flange_holes: int = 0
    fastener: str = "rivet"
    punched: bool = False
    transverse: bool = False
    #: reproduce the IRM Flexural Evaluator's net moment of inertia, which
    #: takes the gross pieces about the *gross* centroid and the holes about
    #: the *net* centroid -- it drops A_g (y_g - y_n)^2, a slightly low
    #: (conservative) net section modulus.  Off by default.
    nsba_net_inertia: bool = False

    @property
    def d_hole(self) -> float:
        return hole_diameter(self.d_fastener)

    def _pieces(self, failed: int | None = None, composite: bool = True):
        """``[(A, Io, y)]`` gross pieces and ``[(A, Io, y)]`` hole
        deductions (negative areas).  ``failed`` removes tension cover
        plate number ``failed`` (1 = outermost)."""
        d, h = self.depth_angles, self.d_hole
        ta, ca = self.tension_angle, self.compression_angle
        gross, holes = [], []
        # tension cover plates, outermost first: plate k sits below plates k+1..N
        t_plates = self.tension_plates
        n_t = len(t_plates)
        for k, (b, t) in enumerate(t_plates, start=1):
            below = sum(tt for _, tt in t_plates[k:])
            y = -below - t / 2.0
            if failed == k:
                continue
            gross.append((b * t, b * t ** 3 / 12.0, y))
            n_h = 2 * ta.flange_holes + self.extra_tension_flange_holes
            if n_h:
                holes.append((-n_h * h * t, -n_h * h * t ** 3 / 12.0, y))
        # compression cover plates above the angles, outermost first
        c_plates = self.compression_plates
        for k, (b, t) in enumerate(c_plates, start=1):
            below = sum(tt for _, tt in c_plates[k:])
            y = d + below + t / 2.0
            gross.append((b * t, b * t ** 3 / 12.0, y))
            n_h = 2 * ca.flange_holes + self.extra_compression_flange_holes
            if n_h:
                holes.append((-n_h * h * t, -n_h * h * t ** 3 / 12.0, y))
        # angles and their horizontal-leg holes
        gross.append((2 * ta.area, 2 * ta.i_horizontal, ta.y_bar))
        gross.append((2 * ca.area, 2 * ca.i_horizontal, d - ca.y_bar))
        if ta.flange_holes:
            a = -2 * ta.flange_holes * h * ta.thickness
            holes.append((a, a * ta.thickness ** 2 / 12.0, ta.thickness / 2.0))
        if ca.flange_holes:
            a = -2 * ca.flange_holes * h * ca.thickness
            holes.append((a, a * ca.thickness ** 2 / 12.0, d - ca.thickness / 2.0))
        # web and the holes through web + both vertical angle legs
        gross.append((self.web_depth * self.web_t, self.web_t * self.web_depth ** 3 / 12.0, d / 2.0))
        for off in ta.web_hole_offsets:
            w = 2 * ta.thickness + self.web_t
            holes.append((-h * w, -w * h ** 3 / 12.0, off))
        if not self.compression_flange_welded:
            for off in ca.web_hole_offsets:
                w = 2 * ca.thickness + self.web_t
                holes.append((-h * w, -w * h ** 3 / 12.0, d - off))
        # deck (short-term transformed), positive moment only
        if composite and self.composite and not self.negative_moment:
            top = d + sum(t for _, t in c_plates)
            if self.include_haunch and self.b_haunch and self.t_haunch:
                bh = self.b_haunch / self.n
                gross.append((bh * self.t_haunch, bh * self.t_haunch ** 3 / 12.0,
                              top + self.t_haunch / 2.0))
            bd = self.b_eff / self.n
            # the slab sits on the haunch whether or not its area is counted
            gross.append((bd * self.t_slab, bd * self.t_slab ** 3 / 12.0,
                          top + self.t_haunch + self.t_slab / 2.0))
        return gross, holes

    def section(self, *, net: bool, faulted: int | None = None,
                composite: bool = True) -> dict:
        """``{"A", "y", "I", "c", "S"}`` about the horizontal centroidal
        axis; ``c`` and ``S`` to the extreme tension fiber (the outer face
        of the outermost remaining tension cover plate)."""
        gross, holes = self._pieces(faulted, composite)
        pieces = gross + (holes if net else [])
        a = sum(p[0] for p in pieces)
        y = sum(p[0] * p[2] for p in pieces) / a
        i = sum(p[1] + p[0] * (p[2] - y) ** 2 for p in pieces)
        if net and self.nsba_net_inertia:
            a_g = sum(p[0] for p in gross)
            y_g = sum(p[0] * p[2] for p in gross) / a_g
            i = (sum(p[1] + p[0] * (p[2] - y_g) ** 2 for p in gross)
                 + sum(p[1] + p[0] * (p[2] - y) ** 2 for p in holes))
        plates = [t for k, (_, t) in enumerate(self.tension_plates, start=1) if k != faulted]
        bottom = 0.0
        outer = next((k for k in range(1, len(self.tension_plates) + 1) if k != faulted), None)
        if outer is not None:
            # outer face of the outermost remaining plate
            bottom = -sum(t for _, t in self.tension_plates[outer - 1:])
        c = y - bottom
        return {"A": a, "y": y, "I": i, "c": c, "S": i / c}

    def evaluate(self, *, m_dc1: float, m_ll: float, m_fat: float,
                 traffic: Traffic, m_dc2: float = 0.0, m_dw: float = 0.0,
                 failed_plate: int = 1, fcp_override: bool = False,
                 r_s: float = 1.0, r_r: float = 1.0,
                 consumed_year_offset: float = 0.01) -> IRMResult:
        """GS 1.7 / 2.1 / 2.3 / 2.5 / 3 for one cross section; moments in
        kip-ft (tension in the plates evaluated), ``m_fat`` the fatigue
        truck moment with impact before the Fatigue II factor.

        ``consumed_year_offset`` reproduces the evaluator's 0.01-year shift
        in the consumed-cycle growth exponent (MBE Eq. 7.2.5.1-3)."""
        fcp = built_to_fcp(traffic.year_built, fcp_override)
        g_dc, g_dw, g_ll = redundancy_ii_factors(fcp)
        comp = self.composite and not self.negative_moment
        s_afn_nc = self.section(net=True, faulted=failed_plate, composite=False)["S"]
        s_afg_nc = self.section(net=False, faulted=failed_plate, composite=False)["S"]
        if comp:
            s_afn_c = self.section(net=True, faulted=failed_plate)["S"]
            s_afg_c = self.section(net=False, faulted=failed_plate)["S"]
        else:
            s_afn_c, s_afg_c = s_afn_nc, s_afg_nc
        m_dead = g_dc * (m_dc1 + m_dc2) * 12.0
        m_rest = (g_dw * m_dw + g_ll * m_ll) * 12.0
        f_afn = m_dead / s_afn_nc + m_rest / s_afn_c
        f_afg = m_dead / s_afg_nc + m_rest / s_afg_c
        dc_n, dc_g = f_afn / (PHI_U * self.fu), f_afg / (PHI_Y * self.fy)
        m_fat2 = m_fat * GAMMA_FAT_II * 12.0
        s_n = self.section(net=True, composite=comp)["S"]
        df_unf = m_fat2 / s_n
        r_p = 1.0 if self.transverse else None
        cat_u = unfaulted_category(self.fastener, self.punched)
        consumed = mbe_fatigue.consumed_cycles(traffic, consumed_year_offset)
        unfaulted = mbe_fatigue.evaluate(df_unf, cat_u, traffic, r_s=r_s, r_p=r_p,
                                         r_r=r_r, consumed=consumed)
        beta = cover_plate_adjustment(len(self.tension_plates))
        df_f = beta * m_fat2 / s_afn_c
        faulted = mbe_fatigue.evaluate(df_f, faulted_category(self.punched), traffic,
                                       r_s=r_s, r_p=r_p, r_r=r_r, consumed=0.0)
        case = fatigue_case(unfaulted.infinite, faulted.infinite)
        years = traffic.year_current - traffic.year_built
        nf = total_remaining_life(faulted.remaining_years, unfaulted.remaining_years, years)
        return IRMResult(
            p_u=(m_dead + m_rest) / 12.0, stresses_net={"f_AFN": f_afn},
            stresses_gross={"f_AFG": f_afg}, dc_net=dc_n, dc_gross=dc_g,
            strength_ok=dc_n <= 1.0 and dc_g <= 1.0, unfaulted=unfaulted,
            faulted=faulted, faulted_stress_ranges={f"PL-{failed_plate}": df_f},
            case=case, total_life=nf, interval=special_inspection_interval(nf, case),
            details={"fcp": fcp, "gammas": (g_dc, g_dw, g_ll), "beta_AF": beta,
                     "S_AFN_NC": s_afn_nc, "S_AFG_NC": s_afg_nc, "S_AFN_COMP": s_afn_c,
                     "S_AFG_COMP": s_afg_c, "S_N": s_n, "composite": comp})


# ── two-component axial members (GS 2.2.2, 2022 interims) ──────────────────

TWO_COMPONENT_SHEAR_LAG = 1.3      # Xi_VL for two angles


def two_angle_bending_factor(i_l: float) -> float:
    """Xi_B for a two-angle member as the IRM Two-Component Evaluator
    computes it, ``1.2 + 0.15 (2 + I_L / 11)`` with ``I_L`` the moment of
    inertia of the intact angle (in.^4) -- transcribed from the evaluator;
    the 2022 GS text was not available to confirm it."""
    return 1.2 + 0.15 * (2.0 + i_l / 11.0)


def channel_additional_moment(p_u: float, *, d_ch: float, e: float, continuous: bool,
                              laced: bool, n_stay_pairs: int = 0, panel_length: float = 0.0,
                              lattice_spacing: float = 0.0, lattice_factor: float = 1.0,
                              nsba_stay_plate_form: bool = True) -> float:
    """Additional moment M_AF (kip-in.) in the surviving channel of a
    two-channel member (GS 2.2.2.3.2 to 2.2.2.3.5), as the evaluator
    implements them:

    * continuous, laced: ``min[(Pu L_PL d + 28 Pu e g S)/(1180 g S), 0.15 Pu e]``
    * continuous, stay-plated: ``(Pu N_SP d + 6 Pu e) / 240``
    * non-continuous, laced: ``(Pu L_PL d + 40 Pu e g S) / (1100 g S)``
    * non-continuous, stay-plated: ``min[Pu N_SP d + (2 Pu e)/44, 0.35 Pu e]``
      -- the evaluator's operator precedence; ``nsba_stay_plate_form=False``
      uses ``(Pu N_SP d + 2 Pu e)/44``, the form the other three cases
      suggest was intended.

    ``g`` is the lattice-bar configuration factor (0.5 or 1.0), ``S`` the
    lattice-bar spacing, ``L_PL`` the panel length, ``N_SP`` the number of
    stay-plate pairs, ``e`` the eccentricity and ``d`` the channel depth."""
    if continuous and laced:
        return min((p_u * panel_length * d_ch + 28 * p_u * e * lattice_factor * lattice_spacing)
                   / (1180 * lattice_factor * lattice_spacing), 0.15 * p_u * e)
    if continuous:
        return (p_u * n_stay_pairs * d_ch + 6 * p_u * e) / 240.0
    if laced:
        return ((p_u * panel_length * d_ch + 40 * p_u * e * lattice_factor * lattice_spacing)
                / (1100 * lattice_factor * lattice_spacing))
    first = (p_u * n_stay_pairs * d_ch + (2 * p_u * e) / 44.0 if nsba_stay_plate_form
             else (p_u * n_stay_pairs * d_ch + 2 * p_u * e) / 44.0)
    return min(first, 0.35 * p_u * e)


@dataclass
class TwoComponentAxialMember:
    """A two-component axial truss member (GS 2.2.2): two angles, or two
    rolled channels joined by lacing or stay plates.  For angles give
    ``angle`` and ``i_intact``; for channels give ``channel``,
    ``channel_depth``, ``c`` (centroid to the stress surface), ``i_y`` (of
    one channel), ``e`` (eccentricity), the lacing or stay-plate data and
    whether the member is continuous.

    The evaluator's channel stress adds ``M_AF c / I_y`` with M_AF from
    the *strength* (Redundancy II) load in the fatigue check too
    (``fatigue_moment_from_strength_load``); set it False to scale M_AF to
    the fatigue load instead (M_AF is linear in P)."""

    fy: float
    fu: float
    d_fastener: float
    angle: Angle | None = None
    i_intact: float = 0.0
    channel: RolledChannel | None = None
    channel_depth: float = 0.0
    c: float = 0.0
    i_y: float = 0.0
    e: float = 0.0
    continuous: bool = True
    laced: bool = False
    n_stay_pairs: int = 0
    panel_length: float = 0.0
    lattice_spacing: float = 0.0
    lattice_factor: float = 1.0
    fastener: str = "rivet"
    punched: bool = False
    net_strength: float | None = None          # staggered-hole net area of one component
    fatigue_moment_from_strength_load: bool = True
    nsba_stay_plate_form: bool = True

    @property
    def d_hole(self) -> float:
        return hole_diameter(self.d_fastener)

    def component(self) -> tuple[float, float]:
        """Gross and net area of one component."""
        h = self.d_hole
        if self.channel is not None:
            c = self.channel
            return c.area, c.area - h * (c.t_flange * c.holes_flange + c.t_web * c.holes_web)
        a = self.angle
        return a.area, a.area - (a.holes_vertical + a.holes_horizontal) * a.thickness * h

    def m_af(self, p: float) -> float:
        if self.channel is None:
            return 0.0
        return channel_additional_moment(
            p, d_ch=self.channel_depth, e=self.e, continuous=self.continuous, laced=self.laced,
            n_stay_pairs=self.n_stay_pairs, panel_length=self.panel_length,
            lattice_spacing=self.lattice_spacing, lattice_factor=self.lattice_factor,
            nsba_stay_plate_form=self.nsba_stay_plate_form)

    def evaluate(self, *, p_dc: float, p_ll: float, p_fat: float, traffic: Traffic,
                 p_dw: float = 0.0, fcp_override: bool = False, r_s: float = 1.0,
                 r_r: float = 1.0) -> IRMResult:
        fcp = built_to_fcp(traffic.year_built, fcp_override)
        g_dc, g_dw, g_ll = redundancy_ii_factors(fcp)
        p_u = g_dc * p_dc + g_dw * p_dw + g_ll * p_ll
        p_fat2 = p_fat * GAMMA_FAT_II
        a_g, a_n = self.component()
        a_n_str = self.net_strength if self.net_strength else a_n
        # the surviving component carries everything
        if self.channel is None:
            fn, fg = p_u / a_n_str, p_u / a_g
        else:
            bend = self.m_af(p_u) * self.c / self.i_y
            fn, fg = p_u / a_n_str + bend, p_u / a_g + bend
        dc_n, dc_g = fn / (PHI_U * self.fu), fg / (PHI_Y * self.fy)
        df_unf = p_fat2 / (2.0 * a_n)
        unfaulted = mbe_fatigue.evaluate(df_unf, unfaulted_category(self.fastener, self.punched),
                                         traffic, r_s=r_s, r_r=r_r)
        if self.channel is None:
            xi_b = two_angle_bending_factor(self.i_intact)
            df_f = TWO_COMPONENT_SHEAR_LAG * xi_b * p_fat2 / a_n
        else:
            xi_b = None
            m = self.m_af(p_u) if self.fatigue_moment_from_strength_load else self.m_af(p_fat2)
            df_f = p_fat2 / a_n + m * self.c / self.i_y
        faulted = mbe_fatigue.evaluate(df_f, faulted_category(self.punched), traffic,
                                       r_s=r_s, r_r=r_r, consumed=0.0)
        case = fatigue_case(unfaulted.infinite, faulted.infinite)
        years = traffic.year_current - traffic.year_built
        nf = total_remaining_life(faulted.remaining_years, unfaulted.remaining_years, years)
        return IRMResult(
            p_u=p_u, stresses_net={"surviving": fn}, stresses_gross={"surviving": fg},
            dc_net=dc_n, dc_gross=dc_g, strength_ok=dc_n <= 1.0 and dc_g <= 1.0,
            unfaulted=unfaulted, faulted=faulted, faulted_stress_ranges={"component": df_f},
            case=case, total_life=nf, interval=special_inspection_interval(nf, case),
            details={"fcp": fcp, "gammas": (g_dc, g_dw, g_ll), "Xi_B": xi_b,
                     "M_AF": self.m_af(p_u), "P_FAT_II": p_fat2})
