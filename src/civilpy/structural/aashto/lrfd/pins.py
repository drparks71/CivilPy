"""Pins, eyebars and pin-connected plates -- AASHTO LRFD 6.7.6, 6.8.6, 6.8.7.

The checks a pin-connected truss joint or a pin-and-hanger needs:

* :func:`pin_flexure_shear` -- Eq. 6.7.6.2.1-1 interaction of moment and
  shear taken at the *same* section along the pin
* :func:`pin_bearing` -- Eq. 6.7.6.2.2-1/-2, ``(R_pB)n = 1.5 t D Fy`` (the
  coefficient may be halved for *new* pins with significant rotation,
  C6.7.6.2.2; never for the evaluation of existing pins)
* :func:`min_pin_diameter_for_eyebar` -- Eq. 6.7.6.3-1
* :func:`eyebar_resistance` / :func:`eyebar_proportions` -- 6.8.6.1 / 6.8.6.2
* :func:`pin_plate_bearing` / :func:`pin_plate_proportions` -- 6.8.7.2 / 6.8.7.3

and :func:`pin_actions`, the statics of the pin itself: the plates bearing on
it (eyebars, gussets, hanger plates, pin plates) apply in-plane forces at
their centerlines along the pin axis, and the shear and moment at every
section follow from equilibrium.  Forces may act in two directions (a truss
joint pulls the pin every which way), so shear and moment are combined
vectorially, and the interaction is evaluated at every section so that
Mu and Vu come from the same place as 6.7.6.2.1 requires.

Units: kips and inches; Fy in ksi.

Examples
--------
A 6 in. pin, Fy = 36 ksi, two 1 in. eyebars pulling 150 kips each, held by
two 3/4 in. gusset plates (centerlines 2.5 in. outboard of the bars):

>>> plates = [PinPlate("gusset W", -3.375, 0.75, fy=36.0),
...           PinPlate("bar 1", -1.0, 1.0, fy=36.0, force=(150.0, 0.0)),
...           PinPlate("bar 2", 1.0, 1.0, fy=36.0, force=(150.0, 0.0)),
...           PinPlate("gusset E", 3.375, 0.75, fy=36.0)]
>>> a = pin_actions(plates)          # gussets take the balance by statics
>>> round(a.plate_forces["gusset W"][0], 1)
-150.0
>>> round(a.max_moment, 1)            # 150 k x 2.375 in lever
356.2
>>> c = pin_flexure_shear(6.0, 36.0, a.governing.moment, a.governing.shear)
>>> round(c.demand, 3)             # 6(356.25)/(6^3 36) + (2.2(150)/(6^2 36))^3
0.291
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field

from civilpy.structural.aashto.lrfd.core import CheckResult, article
from civilpy.structural.aashto.lrfd.steel import tension_member_resistance

#: 6.5.4.2 resistance factors used here
PHI_F = 1.00        # flexure
PHI_V = 1.00        # shear
PHI_B = 1.00        # bearing on pins in reamed, drilled or bored holes


# ── Pin resistance ────────────────────────────────────────────────────────────


@article("6.7.6.2.1", "Pin Combined Flexure and Shear")
def pin_flexure_shear(d: float, f_y: float, m_u: float, v_u: float,
                      phi_f: float = PHI_F, phi_v: float = PHI_V) -> CheckResult:
    """Eq. 6.7.6.2.1-1: ``6.0 Mu / (phi_f D^3 Fy) + (2.2 Vu / (phi_v D^2
    Fy))^3 <= 0.95`` with Mu (kip-in.) and Vu (kip) at the same section.
    ``capacity`` is the 0.95 limit and ``demand`` the left-hand side."""
    flex = 6.0 * abs(m_u) / (phi_f * d ** 3 * f_y)
    shear = (2.2 * abs(v_u) / (phi_v * d ** 2 * f_y)) ** 3
    return CheckResult(
        article="6.7.6.2.1", name="Pin Combined Flexure and Shear",
        capacity=0.95, demand=flex + shear,
        details={"D": d, "Fy": f_y, "Mu": m_u, "Vu": v_u,
                 "flexure term": flex, "shear term": shear,
                 "phi_f": phi_f, "phi_v": phi_v})


@article("6.7.6.2.2", "Pin Bearing")
def pin_bearing(t: float, d: float, f_y: float, p_u: float | None = None, *,
                significant_rotation: bool = False, new_design: bool = True,
                phi_b: float = PHI_B) -> CheckResult:
    """Eq. 6.7.6.2.2: ``(R_pB)r = phi_b 1.5 t D Fy`` for a plate of
    thickness ``t`` (Fy of the plate) bearing on a pin of diameter ``D``.
    For new pins with significant rotation (rockers, hinges) the 1.5 may be
    halved to 0.75 (C6.7.6.2.2); for the evaluation of existing pins it is
    not halved, so ``new_design=False`` keeps 1.5 regardless."""
    coef = 0.75 if (significant_rotation and new_design) else 1.5
    nominal = coef * t * d * f_y
    return CheckResult(
        article="6.7.6.2.2", name="Pin Bearing", capacity=nominal,
        demand=None if p_u is None else abs(p_u), phi=phi_b,
        details={"t": t, "D": d, "Fy": f_y, "coefficient": coef,
                 "(RpB)n": nominal})


@article("6.7.6.3", "Minimum Size Pin for Eyebars")
def min_pin_diameter_for_eyebar(f_y: float, b: float,
                                d: float | None = None) -> CheckResult:
    """Eq. 6.7.6.3-1: ``D >= (3/4 + Fy/400) b`` with Fy of the eyebar and
    ``b`` the width of its body.  ``capacity`` is the pin diameter given
    (when ``d`` is passed) and ``demand`` the minimum."""
    d_min = (0.75 + f_y / 400.0) * b
    return CheckResult(
        article="6.7.6.3", name="Minimum Size Pin for Eyebars",
        capacity=d if d is not None else d_min, demand=d_min if d is not None else None,
        details={"D_min": d_min, "Fy": f_y, "b": b})


# ── Eyebars ───────────────────────────────────────────────────────────────────


@article("6.8.6.1", "Eyebar Factored Resistance")
def eyebar_resistance(b: float, t: float, f_y: float,
                      p_u: float | None = None) -> CheckResult:
    """6.8.6.1: the body's yield resistance, Eq. 6.8.2.1-1 on ``b t``
    (rupture, Eq. 6.8.2.1-2, does not control because the head is at least
    1.35 times the body -- C6.8.6.1; :func:`eyebar_proportions` checks that)."""
    r = tension_member_resistance(a_g=b * t, f_y=f_y, p_u=p_u)
    r.article, r.name = "6.8.6.1", "Eyebar Factored Resistance"
    r.details.update({"b": b, "t": t})
    return r


@dataclass(frozen=True)
class Eyebar:
    """Eyebar geometry (inches): body width ``b`` and thickness ``t``, the
    net head width across the pin hole (both sides of the hole together),
    the net head dimension beyond the hole along the bar, the transition
    radius between head and body, the head width at the hole centerline,
    the hole diameter and the pin diameter.  ``hole_on_axis`` records that
    the hole is centred on the body's axis."""

    b: float
    t: float
    head_net_width: float
    head_beyond_hole: float
    transition_radius: float
    head_width: float
    hole_d: float
    pin_d: float
    f_y: float = 36.0
    hole_on_axis: bool = True
    required_b: float | None = None     # width the force needs; defaults to b


def eyebar_proportions(e: Eyebar) -> dict[str, CheckResult]:
    """6.8.6.2 proportion limits, one :class:`CheckResult` each (``capacity``
    the limit, ``demand`` the bar's value, oriented so ratio >= 1 passes)."""
    req_b = e.required_b if e.required_b is not None else e.b
    out = {}

    def rule(key, limit, value, *, upper=False, **details):
        # upper limits: pass when value <= limit; lower: value >= limit
        cap, dem = (limit, value) if upper else (value, limit)
        out[key] = CheckResult("6.8.6.2", f"Eyebar {key}", capacity=cap,
                               demand=dem, details={"limit": limit,
                                                    "value": value, **details})

    rule("thickness >= 0.5 in", 0.5, e.t)
    rule("thickness <= 2.0 in", 2.0, e.t, upper=True)
    rule("transition radius >= head width", e.head_width, e.transition_radius)
    rule("net head width >= 1.35 b", 1.35 * req_b, e.head_net_width)
    rule("head beyond hole >= 0.75 b", 0.75 * req_b, e.head_beyond_hole)
    rule("body width <= 8 t", 8.0 * e.t, e.b, upper=True)
    rule("hole <= pin + 1/32 in", e.pin_d + 0.03125, e.hole_d, upper=True)
    if e.f_y > 70.0:
        rule("hole <= 5 t (Fy > 70 ksi)", 5.0 * e.t, e.hole_d, upper=True)
    out["hole on body axis"] = CheckResult(
        "6.8.6.2", "Eyebar hole on body axis", capacity=1.0,
        demand=1.0 if e.hole_on_axis else math.inf,
        details={"hole_on_axis": e.hole_on_axis})
    return out


# ── Pin-connected plates ──────────────────────────────────────────────────────


@article("6.8.7.2", "Pin Plate Bearing")
def pin_plate_bearing(t: float, d: float, f_y: float, p_u: float | None = None,
                      phi_b: float = PHI_B) -> CheckResult:
    """Eq. 6.8.7.2-1: ``Pr = phi_b Ab Fy`` on the projected bearing area
    ``Ab = t D`` of the plate (or the main plate plus its pin plates)."""
    a_b = t * d
    return CheckResult("6.8.7.2", "Pin Plate Bearing", capacity=a_b * f_y,
                       demand=None if p_u is None else abs(p_u), phi=phi_b,
                       details={"Ab": a_b, "Fy": f_y, "t": t, "D": d})


@dataclass(frozen=True)
class PinConnectedPlate:
    """A pin-connected main plate with optional pin plates (inches):
    ``net_area_at_hole`` is the combined net area across the pin-hole
    centerline, ``net_area_beyond_hole`` the combined net area beyond the
    hole along the plate, ``required_net_area`` the net area the force
    needs away from the hole, ``t_main`` / ``t_total`` the main plate and
    combined thicknesses, ``net_width_edge`` the net width from the hole
    edge to the plate edge, ``required_width`` the main plate width the
    force needs away from the hole."""

    net_area_at_hole: float
    net_area_beyond_hole: float
    required_net_area: float
    t_main: float
    t_total: float
    net_width_edge: float
    required_width: float
    hole_d: float
    pin_d: float
    f_y: float = 36.0
    hole_on_axis: bool = True


def pin_plate_proportions(p: PinConnectedPlate) -> dict[str, CheckResult]:
    """6.8.7.3 proportion limits for pin-connected plates."""
    out = {}

    def rule(key, limit, value, *, upper=False):
        cap, dem = (limit, value) if upper else (value, limit)
        out[key] = CheckResult("6.8.7.3", f"Pin plate {key}", capacity=cap,
                               demand=dem, details={"limit": limit, "value": value})

    rule("net area at hole >= 1.4 required", 1.4 * p.required_net_area, p.net_area_at_hole)
    rule("net area beyond hole >= required", p.required_net_area, p.net_area_beyond_hole)
    rule("hole <= pin + 1/32 in", p.pin_d + 0.03125, p.hole_d, upper=True)
    if p.f_y > 70.0:
        rule("hole <= 5 x combined t (Fy > 70 ksi)", 5.0 * p.t_total, p.hole_d, upper=True)
    rule("combined t >= 0.12 x net edge width", 0.12 * p.net_width_edge, p.t_total)
    rule("main plate t >= 0.12 x required width", 0.12 * p.required_width, p.t_main)
    out["hole on plate axis"] = CheckResult(
        "6.8.7.3", "Pin plate hole on plate axis", capacity=1.0,
        demand=1.0 if p.hole_on_axis else math.inf)
    return out


# ── Statics of the pin ────────────────────────────────────────────────────────


@dataclass
class PinPlate:
    """A plate bearing on a pin: its centerline position along the pin
    axis (inches), thickness, yield strength and the in-plane force it
    applies *to the pin* ``(fx, fy)`` in kips (e.g. an eyebar pulling away
    from the joint pulls the pin toward the bar).  ``force=None`` marks a
    reaction plate (a gusset or web plate) whose force is solved by
    statics -- two at most, the pin then a simple beam between them."""

    name: str
    position: float
    thickness: float
    fy: float = 36.0
    force: tuple[float, float] | None = None


@dataclass
class PinSection:
    """Shear (kips) and moment (kip-in.) at one section along the pin."""

    position: float
    shear: float
    moment: float
    shear_xy: tuple[float, float] = (0.0, 0.0)
    moment_xy: tuple[float, float] = (0.0, 0.0)


@dataclass
class PinActions:
    """Result of :func:`pin_actions`: the force every plate puts on the pin
    (reactions solved), the shear/moment at every section between plates
    and either side of each, and the section that governs Eq. 6.7.6.2.1-1
    (when a diameter and Fy were given; else the peak-moment section)."""

    plate_forces: dict[str, tuple[float, float]]
    sections: list[PinSection] = field(default_factory=list)
    governing: PinSection | None = None

    @property
    def max_moment(self) -> float:
        return max(s.moment for s in self.sections)

    @property
    def max_shear(self) -> float:
        return max(s.shear for s in self.sections)


def pin_actions(plates, d: float | None = None, f_y: float | None = None,
                tol: float = 1e-9) -> PinActions:
    """Shear and moment along a pin loaded by ``plates``
    (:class:`PinPlate`), each force applied at the plate centerline.

    Up to two plates may have ``force=None``; their forces come from
    equilibrium of the pin (moment about one, then force balance).  With
    all forces given they must already balance.  Shear and moment are
    computed at both faces of every plate in each of the two in-plane
    directions and combined as vectors; with ``d`` and ``f_y`` the
    section maximizing the Eq. 6.7.6.2.1-1 left side governs (same-section
    Mu and Vu), otherwise the largest moment."""
    plates = sorted(plates, key=lambda p: p.position)
    unknown = [p for p in plates if p.force is None]
    known = [p for p in plates if p.force is not None]
    if len(unknown) > 2:
        raise ValueError("at most two reaction plates (force=None)")
    forces = {p.name: tuple(map(float, p.force)) for p in known}
    sx = sum(f[0] for f in forces.values())
    sy = sum(f[1] for f in forces.values())
    if len(unknown) == 2:
        a, b = unknown
        span = b.position - a.position
        if abs(span) <= tol:
            raise ValueError("reaction plates at the same position")
        # moments about plate a in each direction
        mx = sum(forces[p.name][0] * (p.position - a.position) for p in known)
        my = sum(forces[p.name][1] * (p.position - a.position) for p in known)
        fb = (-mx / span, -my / span)
        forces[b.name] = fb
        forces[a.name] = (-sx - fb[0], -sy - fb[1])
    elif len(unknown) == 1:
        forces[unknown[0].name] = (-sx, -sy)
    else:
        if abs(sx) > 1e-6 * max(1.0, max(abs(f[0]) for f in forces.values())) or \
                abs(sy) > 1e-6 * max(1.0, max(abs(f[1]) for f in forces.values())):
            raise ValueError(f"plate forces do not balance: ({sx:g}, {sy:g}) kips")

    sections = []
    vx = vy = mx = my = 0.0
    prev = plates[0].position
    for k, p in enumerate(plates):
        # moment grows over the gap from the previous plate at the running shear
        gap = p.position - prev
        mx += vx * gap
        my += vy * gap
        if k:
            sections.append(PinSection(p.position - 0.0, math.hypot(vx, vy),
                                       math.hypot(mx, my), (vx, vy), (mx, my)))
        fx, fy_ = forces[p.name]
        vx += fx
        vy += fy_
        sections.append(PinSection(p.position, math.hypot(vx, vy),
                                   math.hypot(mx, my), (vx, vy), (mx, my)))
        prev = p.position
    if d and f_y:
        gov = max(sections, key=lambda s: pin_flexure_shear(d, f_y, s.moment, s.shear).demand)
    else:
        gov = max(sections, key=lambda s: (s.moment, s.shear))
    return PinActions(forces, sections, gov)


def pin_checks(plates, d: float, f_y_pin: float, *,
               significant_rotation: bool = False,
               new_design: bool = False) -> dict[str, CheckResult]:
    """Everything a pin needs from the plates on it: the 6.7.6.2.1
    interaction at the governing section and 6.7.6.2.2 bearing for every
    plate (its own thickness and Fy against the force it puts on the pin).
    Defaults to the evaluation of an existing pin (``new_design=False``)."""
    a = pin_actions(plates, d, f_y_pin)
    out = {"flexure + shear": pin_flexure_shear(d, f_y_pin, a.governing.moment,
                                                a.governing.shear)}
    out["flexure + shear"].details["position"] = a.governing.position
    for p in plates:
        f = a.plate_forces[p.name]
        out[f"bearing {p.name}"] = pin_bearing(
            p.thickness, d, p.fy, math.hypot(*f),
            significant_rotation=significant_rotation, new_design=new_design)
    return out


# ── Shared pin object for truss joints and pin-and-hanger details ────────────


@dataclass
class PinPacking:
    """One plate in a pin's packing: ``member`` is the object whose force
    the plate carries (a truss :class:`~civilpy.structural.truss_builder.
    Member`, a hanger, any hashable key) and ``share`` its fraction (two
    eyebars of one member take 0.5 each); ``member=None`` is a reaction
    plate (gusset, web or pin plate) solved by statics."""

    name: str
    position: float
    thickness: float
    fy: float = 36.0
    member: object = None
    share: float = 1.0


@dataclass
class Pin:
    """A pin with its packing -- the single object a pin-connected truss
    joint, a pin-and-hanger, the BrIM model and the rating all refer to.
    ``diameter`` (in.) and ``fy`` (ksi) are the pin's own."""

    diameter: float
    fy: float
    packing: list[PinPacking] = field(default_factory=list)
    name: str = ""

    def plates(self, member_forces: dict) -> list[PinPlate]:
        """:class:`PinPlate` list with each packed member's force on the
        pin (``member_forces[member]`` is the ``(fx, fy)`` that member
        applies to the pin) times its share."""
        out = []
        for p in self.packing:
            if p.member is None:
                force = None
            else:
                fx, fy_ = member_forces[p.member]
                force = (p.share * fx, p.share * fy_)
            out.append(PinPlate(p.name, p.position, p.thickness, p.fy, force))
        return out

    def checks(self, member_forces: dict, *, significant_rotation: bool = False,
               new_design: bool = False) -> dict[str, CheckResult]:
        """:func:`pin_checks` with this pin's diameter, Fy and packing."""
        return pin_checks(self.plates(member_forces), self.diameter, self.fy,
                          significant_rotation=significant_rotation,
                          new_design=new_design)


@dataclass
class PinAndHanger:
    """A girder pin-and-hanger: two hanger plates (one each side of the
    web) on an upper pin through the cantilever-girder web and a lower pin
    through the suspended-girder web.  Inches / ksi.

    ``web_t`` is the web plus any pin plates bearing on each pin (upper,
    lower); ``gap`` the clear space between web and hanger;
    ``hole_d`` the hanger hole; ``edge_net_width`` the net hanger width
    from hole edge to plate edge on one side and ``beyond_hole`` the net
    length of hanger beyond the hole."""

    hanger_width: float
    hanger_t: float
    hanger_fy: float
    hanger_fu: float
    pin_d: float
    pin_fy: float
    hole_d: float
    web_t: tuple[float, float]
    web_fy: float
    gap: float = 0.25
    edge_net_width: float | None = None
    beyond_hole: float | None = None

    def pins(self) -> tuple[Pin, Pin]:
        """The upper and lower :class:`Pin` with their packing: hangers at
        +/- (web/2 + gap + t/2), the web (reaction plate) at the centre."""
        out = []
        for k, label in enumerate(("upper", "lower")):
            arm = self.web_t[k] / 2 + self.gap + self.hanger_t / 2
            out.append(Pin(self.pin_d, self.pin_fy, [
                PinPacking("hanger near", -arm, self.hanger_t, self.hanger_fy, "hanger", 0.5),
                PinPacking("web", 0.0, self.web_t[k], self.web_fy),
                PinPacking("hanger far", arm, self.hanger_t, self.hanger_fy, "hanger", 0.5),
            ], name=f"{label} pin"))
        return tuple(out)

    def checks(self, p_u: float, h_u: float = 0.0, *,
               new_design: bool = False) -> dict[str, CheckResult]:
        """Strength checks for a factored hanger force ``p_u`` (kips, both
        plates together) and an optional longitudinal force ``h_u`` (a
        frozen pin): hanger tension (6.8.2.1 on the gross body and on the
        net section through the hole, 6.8.7.1), pin flexure + shear and
        bearing on hangers and webs (6.7.6.2), hanger bearing as a pin
        plate (6.8.7.2) and the 6.8.7.3 proportions (when the net widths
        are given)."""
        a_g = self.hanger_width * self.hanger_t
        a_n = (self.hanger_width - self.hole_d) * self.hanger_t
        out = {"hanger tension": tension_member_resistance(
            a_g=2 * a_g, f_y=self.hanger_fy, a_n=2 * a_n, f_u=self.hanger_fu, p_u=p_u)}
        out["hanger tension"].article = "6.8.7.1"
        for pin in self.pins():
            # hanger pulls the upper pin down and the lower pin up
            sign = -1.0 if pin.name.startswith("upper") else 1.0
            res = pin.checks({"hanger": (h_u, sign * p_u)}, new_design=new_design)
            for key, c in res.items():
                out[f"{pin.name} {key}"] = c
        out["hanger bearing (pin plate)"] = pin_plate_bearing(
            self.hanger_t, self.pin_d, self.hanger_fy, math.hypot(p_u, h_u) / 2)
        if self.edge_net_width is not None and self.beyond_hole is not None:
            req = abs(p_u) / 2 / (0.95 * self.hanger_fy)
            props = pin_plate_proportions(PinConnectedPlate(
                net_area_at_hole=a_n, net_area_beyond_hole=self.beyond_hole * self.hanger_t,
                required_net_area=req, t_main=self.hanger_t, t_total=self.hanger_t,
                net_width_edge=self.edge_net_width, required_width=req / self.hanger_t,
                hole_d=self.hole_d, pin_d=self.pin_d, f_y=self.hanger_fy))
            out.update({f"hanger {k}": v for k, v in props.items()})
        return out
