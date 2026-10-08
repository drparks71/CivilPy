#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Culvert hydraulics after FHWA HDS-5 (3rd ed., FHWA-HIF-12-026, 2012).

Analysis of an existing (or trial) culvert crossing: the headwater a
discharge needs, which end controls, the USGS flow type, and how much water
goes over the road.

* **Barrel** - any closed shape described by its inside outline
  (:class:`BarrelShape`: circular, box, ellipse, and the four-radius
  structural-plate shapes), optionally embedded (a bed at ``embedment_ft``
  above the barrel invert, with its own n).  Area, top width and wetted
  perimeter at a depth come from clipping the outline, so the same code
  serves every shape.
* **Inlet control** - HDS-5 Appendix A: unsubmerged Form 1
  (Eq. A.1) or Form 2 (A.2) up to Q/AD^0.5 = 3.5, submerged (A.3) from 4.0,
  a straight line between (the "transition zone" HDS-5 leaves to a drawn
  tangent).  Constants from Tables A.1 / A.2 (:data:`INLETS`), Ke from
  Table C.2.
* **Outlet control** - the backwater method of HDS-5 Sec. 3.1.4: start at
  the outlet at the higher of critical depth and tailwater, step the
  subcritical profile upstream (standard step, averaged friction slope);
  where it reaches the crown the barrel carries a straight full-flow
  hydraulic grade line (Eq. 3.7); headwater = inlet depth plus (1 + Ke)
  velocity heads.  A submerged outlet reproduces Eq. 3.6b exactly.
  ``method="approximate"`` gives the hand method instead (HGL at the
  outlet at max(TW, (dc + D)/2), plus Eq. 3.5 losses).
* **Roadway overtopping** - Eq. 3.9 broad-crested weir over the roadway
  profile, segment by segment (Fig. 3.12A), solved together with the
  culvert flow (:func:`crossing`).  HDS-5 reads Cd from Fig. 3.11; here it
  is one coefficient (default 3.0, deep overtopping of a paved road) and the
  tailwater submergence factor uses Villemonte's equation in place of the
  Fig. 3.11C chart.

Culverts in series (each one's headwater the next one upstream's
tailwater) are :func:`culvert_system`; a performance curve with tailwater
prorated between two discharges is :func:`performance_curve`.

US customary units: ft, ft^2, cfs, ft/s; slopes ft/ft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

G = 32.2
K_MANNING_US = 1.486
QAD_UNSUBMERGED = 3.5     # HDS-5 A.2.1: unsubmerged equations up to Q/AD^0.5 = 3.5
QAD_SUBMERGED = 4.0       # A.2.2: submerged equation from 4.0
INLET_SUBMERGED_HW_D = 1.2  # inlet treated as submerged (USGS types 5/6) above HW/D = 1.2


# ── inlet constants (HDS-5 Tables A.1, A.2, C.2) ───────────────────────────

@dataclass(frozen=True)
class InletConstants:
    """One inlet configuration: Eq. A.1/A.2 form and K, M; Eq. A.3 c, Y;
    slope correction Ks (-0.5, mitered +0.7); entrance loss Ke."""
    label: str
    form: int
    k: float
    m: float
    c: float
    y: float
    ke: float
    ks: float = -0.5


def _i(label, form, k, m, c, y, ke, ks=-0.5):
    return InletConstants(label, form, k, m, c, y, ke, ks)


INLETS: dict[str, InletConstants] = {
    # Table A.1 chart 1-3: circular concrete / CM / beveled ring
    "concrete_pipe_square_headwall": _i("Circular concrete, square edge w/ headwall", 1, 0.0098, 2.0, 0.0398, 0.67, 0.5),
    "concrete_pipe_groove_headwall": _i("Circular concrete, groove end w/ headwall", 1, 0.0018, 2.0, 0.0292, 0.74, 0.2),
    "concrete_pipe_groove_projecting": _i("Circular concrete, groove end projecting", 1, 0.0045, 2.0, 0.0317, 0.69, 0.2),
    "cmp_headwall": _i("Circular CM, headwall", 1, 0.0078, 2.0, 0.0379, 0.69, 0.5),
    "cmp_mitered": _i("Circular CM, mitered to slope", 1, 0.0210, 1.33, 0.0463, 0.75, 0.7, ks=0.7),
    "cmp_projecting": _i("Circular CM, projecting", 1, 0.0340, 1.50, 0.0553, 0.54, 0.9),
    "pipe_beveled_45": _i("Circular, beveled ring 45 deg", 1, 0.0018, 2.50, 0.0300, 0.74, 0.2),
    "pipe_beveled_33_7": _i("Circular, beveled ring 33.7 deg", 1, 0.0018, 2.50, 0.0243, 0.83, 0.2),
    # chart 8: concrete box
    "box_wingwall_30_75": _i("Concrete box, 30-75 deg wingwall flares", 1, 0.026, 1.0, 0.0347, 0.81, 0.4),
    "box_wingwall_90_15": _i("Concrete box, 90 and 15 deg wingwall flares", 1, 0.061, 0.75, 0.0400, 0.80, 0.5),
    "box_wingwall_0": _i("Concrete box, 0 deg wingwall flares (extension of sides)", 1, 0.061, 0.75, 0.0423, 0.82, 0.7),
    # chart 10: box, 90 deg headwall
    "box_headwall_chamfer": _i("Concrete box, 90 deg headwall w/ 3/4 in chamfers", 2, 0.515, 0.667, 0.0375, 0.79, 0.5),
    "box_headwall_bevel_45": _i("Concrete box, 90 deg headwall w/ 45 deg bevels", 2, 0.495, 0.667, 0.0314, 0.82, 0.2),
    # Table A.2: ellipses, pipe-arches, CM arches and boxes
    "ellipse_square_headwall": _i("Horizontal ellipse concrete, square edge w/ headwall", 1, 0.0100, 2.0, 0.0398, 0.67, 0.5),
    "ellipse_groove_headwall": _i("Horizontal ellipse concrete, groove end w/ headwall", 1, 0.0018, 2.5, 0.0292, 0.74, 0.2),
    "ellipse_groove_projecting": _i("Horizontal ellipse concrete, groove end projecting", 1, 0.0045, 2.0, 0.0317, 0.69, 0.2),
    "pipe_arch_headwall": _i("CM pipe arch, 90 deg headwall", 1, 0.0083, 2.0, 0.0379, 0.69, 0.5),
    "pipe_arch_mitered": _i("CM pipe arch, mitered to slope", 1, 0.0300, 1.0, 0.0463, 0.75, 0.7, ks=0.7),
    "pipe_arch_projecting": _i("CM pipe arch, projecting", 1, 0.0340, 1.5, 0.0496, 0.57, 0.9),
    "cm_box_headwall": _i("CM box, 90 deg headwall", 1, 0.0083, 2.0, 0.0379, 0.69, 0.5),
    "cm_box_thin_projecting": _i("CM box, thin wall projecting", 1, 0.0340, 1.5, 0.0496, 0.57, 0.9),
}


# ── barrel geometry ────────────────────────────────────────────────────────

def _clip(poly, y, keep_below):
    """Sutherland-Hodgman clip of a polygon against the line y = const."""
    out = []
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i - 1], poly[i]
        in0 = y0 <= y if keep_below else y0 >= y
        in1 = y1 <= y if keep_below else y1 >= y
        if in1:
            if not in0:
                t = (y - y0) / (y1 - y0)
                out.append((x0 + t * (x1 - x0), y))
            out.append((x1, y1))
        elif in0:
            t = (y - y0) / (y1 - y0)
            out.append((x0 + t * (x1 - x0), y))
    return out


def _area(poly):
    return 0.5 * abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1])))


@dataclass
class Section:
    """Flow geometry at one depth (above the bed)."""
    area: float
    top_width: float
    wall_perimeter: float
    bed_perimeter: float

    @property
    def perimeter(self):
        return self.wall_perimeter + self.bed_perimeter


class BarrelShape:
    """Inside outline of a barrel, invert at y = 0, as (x, y) vertices.

    ``embedment_ft`` puts a bed (soil / streambed material) inside the
    barrel at that height: depths are then measured from the bed, the open
    rise is ``rise - embedment``, and the bed is a separate wetted perimeter
    (its own n in :class:`Culvert`).
    """

    def __init__(self, outline: Sequence[tuple], *, embedment_ft: float = 0.0, name: str = "custom",
                 levels: int = 400):
        pts = [(float(x), float(y)) for x, y in outline]
        y0 = min(p[1] for p in pts)
        self.outline = [(x, y - y0) for x, y in pts]
        self.name = name
        self.full_rise = max(p[1] for p in self.outline)
        self.span = max(p[0] for p in self.outline) - min(p[0] for p in self.outline)
        if not 0.0 <= embedment_ft < self.full_rise:
            raise ValueError("embedment must be below the crown")
        self.embedment = float(embedment_ft)
        self.rise = self.full_rise - self.embedment
        self._open = _clip(self.outline, self.embedment, keep_below=False) if self.embedment else self.outline
        self.full = self._section_exact(self.rise)
        # tabulate once: depth -> (area, top width, wall p, bed p)
        self._levels = levels
        self._tab = [self._section_exact(self.rise * i / levels) for i in range(levels + 1)]

    # exact geometry ------------------------------------------------------
    def _section_exact(self, depth):
        e = self.embedment
        d = min(max(depth, 0.0), self.rise)
        if d <= 0:
            bed = self._width_at(e) if e else 0.0
            return Section(0.0, bed, 0.0, bed if e else 0.0)
        wet = _clip(self._open, e + d, keep_below=True)
        area = _area(wet) if len(wet) >= 3 else 0.0
        top = self._width_at(e + d) if d < self.rise else 0.0
        bed = self._width_at(e) if e else 0.0
        wall = 0.0
        for (x0, y0), (x1, y1) in zip(wet, wet[1:] + wet[:1]):
            seg = math.hypot(x1 - x0, y1 - y0)
            on_top = abs(y0 - (e + d)) < 1e-9 and abs(y1 - (e + d)) < 1e-9 and d < self.rise
            on_bed = e > 0 and abs(y0 - e) < 1e-9 and abs(y1 - e) < 1e-9
            if not on_top and not on_bed:
                wall += seg
        return Section(area, top, wall, bed)

    def _width_at(self, y):
        xs = []
        pts = self.outline
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            if (y0 - y) * (y1 - y) <= 0 and y0 != y1:
                xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
        return (max(xs) - min(xs)) if len(xs) >= 2 else 0.0

    # interpolated geometry ------------------------------------------------
    def section(self, depth: float) -> Section:
        if depth >= self.rise:
            return self.full
        if depth <= 0:
            return self._tab[0]
        f = depth / self.rise * self._levels
        i = min(int(f), self._levels - 1)
        t = f - i
        a, b = self._tab[i], self._tab[i + 1]
        return Section(*(u + t * (v - u) for u, v in ((a.area, b.area), (a.top_width, b.top_width),
                                                      (a.wall_perimeter, b.wall_perimeter),
                                                      (a.bed_perimeter, b.bed_perimeter))))

    # constructors ----------------------------------------------------------
    @classmethod
    def circular(cls, diameter_ft: float, *, segments: int = 96, **kw) -> "BarrelShape":
        r = diameter_ft / 2.0
        pts = [(r * math.sin(2 * math.pi * i / segments), r - r * math.cos(2 * math.pi * i / segments))
               for i in range(segments)]
        return cls(pts, name=f"circular {diameter_ft:g} ft", **kw)

    @classmethod
    def box(cls, span_ft: float, rise_ft: float, **kw) -> "BarrelShape":
        return cls([(0, 0), (span_ft, 0), (span_ft, rise_ft), (0, rise_ft)], name=f"box {span_ft:g}x{rise_ft:g}", **kw)

    @classmethod
    def ellipse(cls, span_ft: float, rise_ft: float, *, segments: int = 96, **kw) -> "BarrelShape":
        a, b = span_ft / 2.0, rise_ft / 2.0
        pts = [(a * math.sin(2 * math.pi * i / segments), b - b * math.cos(2 * math.pi * i / segments))
               for i in range(segments)]
        return cls(pts, name=f"ellipse {span_ft:g}x{rise_ft:g}", **kw)

    @classmethod
    def four_radius(cls, rt_ft: float, rs_ft: float, theta_deg: float, *, segments: int = 24, **kw) -> "BarrelShape":
        """Structural-plate horizontal ellipse: top and bottom arcs of radius
        ``rt`` subtending ``theta`` each, tangent side arcs of radius ``rs``
        subtending ``180 - theta`` each.  Span and rise follow."""
        th = math.radians(theta_deg) / 2.0
        if not (0 < th < math.pi / 2) or rs_ft > rt_ft:
            raise ValueError("need 0 < theta < 180 deg and rs <= rt")
        # side-arc centre relative to the top-arc centre (top centre at x=0)
        sx = (rt_ft - rs_ft) * math.sin(th)
        rise = 2.0 * (rt_ft - (rt_ft - rs_ft) * math.cos(th))
        mid = rise / 2.0
        top_c = (0.0, rise - rt_ft)
        bot_c = (0.0, rt_ft)
        side_cy = mid
        pts = []

        def arc(cx, cy, r, a0, a1):
            for k in range(segments):
                a = a0 + (a1 - a0) * k / segments
                pts.append((cx + r * math.sin(a), cy + r * math.cos(a)))
        # angles measured from +y, clockwise positive: start at the bottom, go counter-clockwise
        arc(bot_c[0], bot_c[1], rt_ft, math.pi, math.pi - th)            # bottom arc, right half
        arc(sx, side_cy, rs_ft, math.pi - th, th)                         # right side arc
        arc(top_c[0], top_c[1], rt_ft, th, -th)                           # top arc
        arc(-sx, side_cy, rs_ft, -th, -(math.pi - th))                    # left side arc
        arc(bot_c[0], bot_c[1], rt_ft, -(math.pi - th), -math.pi)         # bottom arc, left half
        return cls(pts, name=f"four-radius rt={rt_ft:g} rs={rs_ft:g}", **kw)


# ── hydraulics of the barrel ───────────────────────────────────────────────

def composite_n(parts: Iterable[tuple]) -> float:
    """HDS-5 Eq. 3.8: (sum p_i n_i^1.5 / p)^(2/3) over (perimeter, n) parts."""
    parts = [(p, n) for p, n in parts if p > 0]
    p = sum(pi for pi, _ in parts)
    if p <= 0:
        return 0.0
    return (sum(pi * ni ** 1.5 for pi, ni in parts) / p) ** (2.0 / 3.0)


@dataclass
class CulvertResult:
    q_cfs: float                 # per culvert (all barrels)
    headwater_elev: float
    hw_inlet_ft: float           # depth above the inlet bed, inlet control
    hw_outlet_ft: float          # depth above the inlet bed, outlet control
    control: str                 # "inlet" | "outlet"
    flow_type: int               # USGS 1-7
    normal_depth_ft: float
    critical_depth_ft: float
    outlet_depth_ft: float
    outlet_velocity_fps: float
    tailwater_elev: float
    notes: list = field(default_factory=list)


class Culvert:
    """One culvert (``barrels`` identical cells side by side).

    Elevations are of the barrel inverts; with an embedded barrel the flow
    depth is measured from the bed, ``embedment_ft`` above them.
    ``slope_correction=False`` drops the Ks*S term of Eqs. A.1 / A.3 (the
    polynomial fits in culvert software are often made with Ks = 0 and
    applied without it).
    """

    def __init__(self, shape: BarrelShape, *, length_ft: float, inlet_invert: float, outlet_invert: float,
                 n: float, inlet: InletConstants | str, ke: float | None = None, barrels: int = 1,
                 n_bed: float | None = None, name: str = "", slope_correction: bool = True):
        if length_ft <= 0 or barrels < 1 or n <= 0:
            raise ValueError("length, barrels and n must be positive")
        self.shape = shape
        self.length = float(length_ft)
        self.inlet_invert = float(inlet_invert)
        self.outlet_invert = float(outlet_invert)
        self.slope = (self.inlet_invert - self.outlet_invert) / self.length
        self.n_wall = float(n)
        self.n_bed = float(n_bed) if n_bed is not None else float(n)
        self.inlet = INLETS[inlet] if isinstance(inlet, str) else inlet
        self.ke = self.inlet.ke if ke is None else float(ke)
        self.barrels = int(barrels)
        self.name = name or shape.name
        self.slope_correction = bool(slope_correction)
        # conveyance per tabulated depth, so the profile steps interpolate instead of re-deriving n and R
        self._k = [self._conveyance(sec) for sec in shape._tab]
        self._k_full = self._conveyance(shape.full)

    # geometry helpers ---------------------------------------------------
    @property
    def rise(self):
        return self.shape.rise

    @property
    def inlet_bed(self):
        return self.inlet_invert + self.shape.embedment

    @property
    def outlet_bed(self):
        return self.outlet_invert + self.shape.embedment

    def _n(self, s: Section):
        return composite_n([(s.wall_perimeter, self.n_wall), (s.bed_perimeter, self.n_bed)]) or self.n_wall

    def _conveyance(self, s: Section):
        if s.area <= 0 or s.perimeter <= 0:
            return 0.0
        return K_MANNING_US / self._n(s) * s.area * (s.area / s.perimeter) ** (2.0 / 3.0)

    def friction_slope(self, q_barrel, depth):
        if depth >= self.rise:
            k = self._k_full
        else:
            f = max(depth, 0.0) / self.rise * self.shape._levels
            i = min(int(f), self.shape._levels - 1)
            k = self._k[i] + (f - i) * (self._k[i + 1] - self._k[i])
        return math.inf if k <= 0 else (q_barrel / k) ** 2

    def _manning_q(self, depth, slope):
        s = self.shape.section(depth)
        if s.area <= 0 or s.perimeter <= 0 or slope <= 0:
            return 0.0
        return K_MANNING_US / self._n(s) * s.area * (s.area / s.perimeter) ** (2.0 / 3.0) * math.sqrt(slope)

    def critical_depth(self, q_barrel) -> float:
        """Q^2 T = g A^3, capped at the rise (a closed conduit's critical
        depth approaches the crown as the flow grows)."""
        if q_barrel <= 0:
            return 0.0
        d = self.rise

        def froude2(y):
            s = self.shape.section(y)
            return math.inf if s.area <= 0 else q_barrel ** 2 * s.top_width / (G * s.area ** 3)
        lo, hi = 1e-6 * d, d * (1 - 1e-6)
        if froude2(hi) >= 1.0:
            return d
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if froude2(mid) > 1.0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def normal_depth(self, q_barrel) -> float:
        """Manning normal depth; the rise when the flow exceeds the barrel's
        greatest open-channel capacity or the barrel is flat / adverse."""
        if q_barrel <= 0:
            return 0.0
        if self.slope <= 0:
            return self.rise
        ys = [self.rise * i / 200 for i in range(1, 201)]
        qs = [self._manning_q(y, self.slope) for y in ys]
        imax = max(range(len(qs)), key=qs.__getitem__)
        if q_barrel > qs[imax]:
            return self.rise
        lo, hi = 0.0, ys[imax]
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if self._manning_q(mid, self.slope) < q_barrel:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    # inlet control ------------------------------------------------------
    def inlet_control_hw(self, q_barrel) -> float:
        """HDS-5 Eq. A.1 / A.2 / A.3, depth above the inlet bed."""
        if q_barrel <= 0:
            return 0.0
        c = self.inlet
        a, d = self.shape.full.area, self.rise
        qad = q_barrel / (a * math.sqrt(d))
        ks_s = c.ks * self.slope if self.slope_correction else 0.0

        def unsub(x):
            if c.form == 1:
                dc = self.critical_depth(x * a * math.sqrt(d))
                sc = self.shape.section(dc)
                hc = dc + (x * a * math.sqrt(d) / sc.area) ** 2 / (2 * G) if sc.area > 0 else dc
                return hc / d + c.k * x ** c.m + ks_s
            return c.k * x ** c.m

        def sub(x):
            return c.c * x ** 2 + c.y + ks_s

        if qad <= QAD_UNSUBMERGED:
            ratio = unsub(qad)
        elif qad >= QAD_SUBMERGED:
            ratio = sub(qad)
        else:
            t = (qad - QAD_UNSUBMERGED) / (QAD_SUBMERGED - QAD_UNSUBMERGED)
            ratio = (1 - t) * unsub(QAD_UNSUBMERGED) + t * sub(QAD_SUBMERGED)
        return max(ratio * d, 0.0)

    # outlet control -----------------------------------------------------
    def _velocity(self, q_barrel, depth):
        s = self.shape.section(depth)
        return q_barrel / s.area if s.area > 0 else math.inf

    def _specific(self, q_barrel, depth):
        return depth + self._velocity(q_barrel, depth) ** 2 / (2 * G)

    def outlet_control(self, q_barrel, tw_depth, *, steps: int = 40, method: str = "profile"):
        """(depth above the inlet bed, outlet depth, outlet velocity, full
        fraction, notes).  ``tw_depth`` is above the outlet bed.  A depth of
        0 means the subcritical profile cannot reach the inlet (a steep
        barrel: supercritical flow from the inlet, so inlet control)."""
        notes = []
        if q_barrel <= 0:
            return 0.0, max(tw_depth, 0.0), 0.0, 0.0, notes
        d = self.rise
        dc = self.critical_depth(q_barrel)
        y_out = max(tw_depth, dc)
        v_full = q_barrel / self.shape.full.area
        if method == "approximate" or tw_depth >= d:
            ho = tw_depth if tw_depth >= d else max(tw_depth, 0.5 * (dc + d))
            r = self.shape.full.area / self.shape.full.perimeter
            h = (1 + self.ke + 29.0 * self._n(self.shape.full) ** 2 * self.length / r ** 1.33) * v_full ** 2 / (2 * G)
            hw = ho + h - self.length * self.slope
            return hw, min(y_out, d) if tw_depth < d else tw_depth, v_full, 1.0, notes

        dx = self.length / steps
        y = min(y_out, d) if y_out < d else y_out
        full_steps = 0
        for _ in range(steps):
            sf_dn = self.friction_slope(q_barrel, y)
            target = self._specific(q_barrel, y) + 0.5 * sf_dn * dx - self.slope * dx

            def g(yy):
                return self._specific(q_barrel, yy) - 0.5 * self.friction_slope(q_barrel, yy) * dx - target
            if g(dc) > 0:
                # no subcritical depth here: the tailwater's profile ends in a jump inside the barrel and the
                # flow upstream of it is supercritical from the inlet - inlet control (HDS-5 Fig. 3.1A / C)
                notes.append("outlet-control profile ends in a hydraulic jump inside the barrel")
                return 0.0, max(min(y_out, d), 0.0), self._velocity(q_barrel, min(y_out, d)), 0.0, notes
            lo, hi = dc, max(y, dc) + 1.0
            while g(hi) < 0:
                hi = lo + 2 * (hi - lo)
            while hi - lo > 1e-5 * d:
                mid = 0.5 * (lo + hi)
                if g(mid) < 0:
                    lo = mid
                else:
                    hi = mid
            y = 0.5 * (lo + hi)
            if y >= d:
                full_steps += 1
        v_in = self._velocity(q_barrel, y)
        hw = y + (1 + self.ke) * v_in ** 2 / (2 * G)
        y_exit = min(y_out, d) if tw_depth < d else tw_depth
        return hw, y_exit, self._velocity(q_barrel, min(y_exit, d)), full_steps / steps, notes

    # the culvert --------------------------------------------------------
    def _hw_depth(self, q_barrel, tw_depth, method):
        return max(self.inlet_control_hw(q_barrel), self.outlet_control(q_barrel, tw_depth, method=method)[0])

    def headwater(self, q_cfs: float, tailwater_elev: float | None = None, *, method: str = "profile") -> CulvertResult:
        """Headwater for ``q_cfs`` through all barrels; ``tailwater_elev``
        defaults to the outlet bed (free outfall)."""
        q = max(float(q_cfs), 0.0) / self.barrels
        tw = self.outlet_bed if tailwater_elev is None else float(tailwater_elev)
        tw_depth = tw - self.outlet_bed
        hwi = self.inlet_control_hw(q)
        hwo, y_exit, v_exit, full_frac, notes = self.outlet_control(q, tw_depth, method=method)
        dn, dc = self.normal_depth(q), self.critical_depth(q)
        control = "inlet" if hwi >= hwo else "outlet"
        hw = max(hwi, hwo)
        d = self.rise
        inlet_sub = hw > INLET_SUBMERGED_HW_D * d
        if control == "inlet":                  # outlet depth ~ normal depth (HDS-5 3.1.6, conservative velocity)
            flow_type = 5 if inlet_sub else 1
            y_exit = dn
            v_exit = self._velocity(q, max(dn, 1e-6))
        elif tw_depth >= d:
            flow_type = 4
        elif inlet_sub:
            flow_type = 6 if full_frac >= 0.5 else 7
        else:
            flow_type = 2 if tw_depth <= dc else 3
        return CulvertResult(q * self.barrels, self.inlet_bed + hw, hwi, hwo, control, flow_type, dn, dc,
                             y_exit, v_exit, tw, notes)

    def discharge(self, headwater_elev: float, tailwater_elev: float | None = None, *, tol_cfs: float = 0.01,
                  method: str = "profile") -> float:
        """The flow the culvert passes at a headwater (inverse of headwater)."""
        if headwater_elev <= self.inlet_bed:
            return 0.0
        if tailwater_elev is not None and tailwater_elev >= headwater_elev:
            return 0.0
        target = headwater_elev - self.inlet_bed
        tw_depth = (self.outlet_bed if tailwater_elev is None else tailwater_elev) - self.outlet_bed

        def hw(q_all):
            return self._hw_depth(q_all / self.barrels, tw_depth, method)
        lo, hi = 0.0, 1.0
        while hw(hi) < target:
            lo, hi = hi, hi * 2.0
            if hi > 1e7:
                raise ValueError("headwater beyond any plausible culvert flow")
        while hi - lo > max(tol_cfs, 1e-4 * hi):
            mid = 0.5 * (lo + hi)
            if hw(mid) < target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


# ── roadway overtopping and the crossing ───────────────────────────────────

@dataclass
class Roadway:
    """Roadway crest profile (station, elevation) along the road - the
    overflow weir.  ``cd`` is Eq. 3.9's discharge coefficient."""
    stations_ft: Sequence[float]
    elevations_ft: Sequence[float]
    cd: float = 3.0

    def __post_init__(self):
        pts = sorted(zip(map(float, self.stations_ft), map(float, self.elevations_ft)))
        if len(pts) < 2:
            raise ValueError("a roadway profile needs at least 2 points")
        self.stations_ft = [p[0] for p in pts]
        self.elevations_ft = [p[1] for p in pts]

    @property
    def crest_elev(self) -> float:
        return min(self.elevations_ft)

    def overtopping(self, headwater_elev: float, tailwater_elev: float | None = None, *, pieces: int = 20) -> float:
        """Eq. 3.9 summed over short horizontal pieces of the profile; each
        piece reduced for tailwater submergence (Villemonte)."""
        q = 0.0
        pts = list(zip(self.stations_ft, self.elevations_ft))
        for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
            for k in range(pieces):
                t = (k + 0.5) / pieces
                z = z0 + t * (z1 - z0)
                h = headwater_elev - z
                if h <= 0:
                    continue
                kt = 1.0
                if tailwater_elev is not None and tailwater_elev > z:
                    ratio = min((tailwater_elev - z) / h, 1.0)
                    kt = max(1.0 - ratio ** 1.5, 0.0) ** 0.385
                q += self.cd * kt * (x1 - x0) / pieces * h ** 1.5
        return q


@dataclass
class CrossingResult:
    q_total_cfs: float
    headwater_elev: float
    tailwater_elev: float
    culverts: list               # CulvertResult per culvert
    q_overtopping_cfs: float

    @property
    def overtopped(self) -> bool:
        return self.q_overtopping_cfs > 0


def _tailwater(tailwater, q):
    if tailwater is None:
        return None
    return float(tailwater(q)) if callable(tailwater) else float(tailwater)


def crossing(culverts: Sequence[Culvert], q_total_cfs: float, *, tailwater: float | Callable | None = None,
             roadway: Roadway | None = None, tol_ft: float = 0.001, method: str = "profile") -> CrossingResult:
    """Split ``q_total_cfs`` between parallel culverts and the road so all
    share one headwater (HDS-5 Sec. 3.2.3).  ``tailwater`` is an elevation or
    a rating ``q -> elevation`` evaluated at the total flow; ``None`` means a
    free outfall at each culvert."""
    if not culverts and roadway is None:
        raise ValueError("a crossing needs a culvert or a roadway to pass the flow")
    q_total = float(q_total_cfs)
    tw = _tailwater(tailwater, q_total)

    # each culvert's rating (headwater at flows up to the total) once; the
    # headwater search then interpolates, and a short exact search finishes
    ratings = []
    for c in culverts:
        qs = [0.0] + [q_total * f for f in (1e-3, 3e-3, 0.01, 0.02, 0.04)] + [q_total * i / 40 for i in range(3, 41)]
        ratings.append(([c.headwater(q, tw, method=method).headwater_elev if q > 0 else
                         max(c.inlet_bed, tw if tw is not None else -math.inf) for q in qs], qs))

    def rated(hw):
        q = 0.0
        for hws, qs in ratings:
            if hw >= hws[-1]:
                q += qs[-1] * (1.0 + (hw - hws[-1]))         # beyond the table: more than the total
                continue
            for i in range(1, len(hws)):
                if hw < hws[i]:
                    h0, h1 = hws[i - 1], hws[i]
                    q += qs[i - 1] + (qs[i] - qs[i - 1]) * ((hw - h0) / (h1 - h0) if h1 > h0 else 1.0)
                    break
        return q + (roadway.overtopping(hw, tw) if roadway is not None else 0.0)

    def exact(hw):
        q = sum(c.discharge(hw, tw, method=method) for c in culverts)
        return q + (roadway.overtopping(hw, tw) if roadway is not None else 0.0)

    def solve(passed, lo, hi, tol):
        while passed(hi) < q_total:
            hi = lo + 2.0 * (hi - lo)
            if hi - lo > 500:
                raise ValueError("no headwater within 500 ft passes the flow")
        while hi - lo > tol:
            mid = 0.5 * (lo + hi)
            if passed(mid) < q_total:
                lo = mid
            else:
                hi = mid
        return lo, hi

    floor = min([c.inlet_bed for c in culverts] + ([roadway.crest_elev] if roadway is not None else []))
    lo = max(floor, tw if tw is not None else -math.inf)
    lo, hi = solve(rated, lo, lo + 1.0, tol_ft)
    if culverts:
        lo2 = max(lo - 0.05, max(floor, tw if tw is not None else -math.inf))
        while exact(lo2) > q_total and lo2 > floor:
            lo2 = max(lo2 - 0.25, floor)
        _, hi = solve(exact, lo2, hi + 0.05, tol_ft)
    hw = hi
    results = []
    for c in culverts:
        qc = c.discharge(hw, tw, method=method)
        r = c.headwater(qc, tw, method=method)
        r.headwater_elev = hw
        results.append(r)
    q_road = roadway.overtopping(hw, tw) if roadway is not None else 0.0
    return CrossingResult(q_total, hw, tw if tw is not None else float("nan"), results, q_road)


def performance_curve(culvert: Culvert, q_min: float, q_max: float, q_inc: float, *,
                      tw_min: float | None = None, tw_max: float | None = None,
                      method: str = "profile") -> list[CulvertResult]:
    """Headwater from ``q_min`` to ``q_max`` by ``q_inc``; tailwater prorated
    linearly between ``tw_min`` (at q_min) and ``tw_max`` (at q_max)."""
    if q_inc <= 0 or q_max < q_min:
        qs = [q_min] if q_max == q_min else [q_min, q_max]
    else:
        n = int(math.floor((q_max - q_min) / q_inc + 1e-9))
        qs = [q_min + i * q_inc for i in range(n + 1)]
        if qs[-1] < q_max - 1e-9:
            qs.append(q_max)
    out = []
    for q in qs:
        tw = tw_min
        if tw_min is not None and tw_max is not None and q_max > q_min:
            tw = tw_min + (tw_max - tw_min) * (q - q_min) / (q_max - q_min)
        out.append(culvert.headwater(q, tw, method=method))
    return out


def culvert_system(culverts: Sequence[Culvert], q_cfs: float, *, tailwater_elev: float | None = None,
                   method: str = "profile") -> list[CulvertResult]:
    """Culverts in series, listed downstream first: each headwater becomes
    the next culvert's tailwater."""
    out, tw = [], tailwater_elev
    for c in culverts:
        r = c.headwater(q_cfs, tw, method=method)
        out.append(r)
        tw = r.headwater_elev
    return out
