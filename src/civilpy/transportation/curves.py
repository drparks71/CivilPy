"""Roadway geometric design: vertical (parabolic) and horizontal
(circular) curves with the standard plan/profile sketches.

Vertical curves use the equal-tangent parabola: elevations from the
grades and curve length, ``K = L/|A|``, and the high/low point where the
grade passes through zero.  Horizontal curves use the arc definition:
T, L, C, E, M from radius and deflection angle, plus the point-mass
superelevation relation e + f = V^2/(15 R).

US units: feet, percent grades, mph, degrees.

Examples
--------
A 600-ft crest curve, +3% to -2%, PVI at sta 25+00 el 482.00:

>>> vc = VerticalCurve(g1_pct=3.0, g2_pct=-2.0, length_ft=600.0,
...                    pvi_station_ft=2500.0, pvi_elevation_ft=482.0)
>>> round(vc.k_value, 0)
120.0
>>> round(vc.elevation_at(vc.bvc_station), 2)   # BVC elevation
473.0
>>> sta, el = vc.high_low_point()
>>> station_str(sta), round(el, 2)
('25+60.00', 478.4)

>>> hc = HorizontalCurve(radius_ft=1145.92, delta_deg=24.0,
...                      pi_station_ft=11500.0)
>>> round(hc.tangent_ft, 1), round(hc.length_ft, 1)
(243.6, 480.0)
>>> round(hc.degree_of_curve_deg, 1)
5.0
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math

import numpy as np

# matplotlib is imported lazily inside the plot() methods below: it is a heavy,
# display-only dependency, and importing it eagerly here would break the
# station/offset placement contract (Alignment -> curves) in environments that
# ship numpy but not matplotlib -- notably Rhino 8's bundled CPython, where the
# Grasshopper components run. See docs/Rhino Design Philosophy.md.


def station_str(station_ft: float) -> str:
    """Format feet as a roadway station: 2560.0 -> '25+60.00'."""
    whole = int(station_ft // 100.0)
    return f"{whole}+{station_ft - 100.0 * whole:05.2f}"


class VerticalCurve:
    """Equal-tangent parabolic vertical curve between grades ``g1_pct``
    and ``g2_pct`` (percent, signed), centered on the PVI."""

    def __init__(self, g1_pct: float, g2_pct: float, length_ft: float,
                 pvi_station_ft: float = 0.0,
                 pvi_elevation_ft: float = 0.0):
        self.g1 = float(g1_pct)
        self.g2 = float(g2_pct)
        self.length = float(length_ft)
        self.pvi_station = float(pvi_station_ft)
        self.pvi_elevation = float(pvi_elevation_ft)

    @property
    def a_pct(self) -> float:
        """Algebraic grade difference A = g2 - g1 (percent); negative
        for a crest, positive for a sag."""
        return self.g2 - self.g1

    @property
    def is_crest(self) -> bool:
        return self.a_pct < 0.0

    @property
    def k_value(self) -> float:
        """``K = L/|A|`` — feet of curve per percent grade change."""
        return self.length / abs(self.a_pct)

    @property
    def bvc_station(self) -> float:
        return self.pvi_station - self.length / 2.0

    @property
    def evc_station(self) -> float:
        return self.pvi_station + self.length / 2.0

    @property
    def bvc_elevation(self) -> float:
        return self.pvi_elevation - self.g1 / 100.0 * self.length / 2.0

    @property
    def evc_elevation(self) -> float:
        return self.pvi_elevation + self.g2 / 100.0 * self.length / 2.0

    def elevation_at(self, station_ft: float) -> float:
        """Profile elevation: on the tangents outside BVC/EVC, on the
        parabola between them."""
        if station_ft <= self.bvc_station:
            return (self.pvi_elevation
                    + self.g1 / 100.0 * (station_ft - self.pvi_station))
        if station_ft >= self.evc_station:
            return (self.pvi_elevation
                    + self.g2 / 100.0 * (station_ft - self.pvi_station))
        x = station_ft - self.bvc_station
        return (self.bvc_elevation + self.g1 / 100.0 * x
                + self.a_pct / 100.0 * x**2 / (2.0 * self.length))

    def grade_at(self, station_ft: float) -> float:
        """Instantaneous grade (percent) along the curve."""
        if station_ft <= self.bvc_station:
            return self.g1
        if station_ft >= self.evc_station:
            return self.g2
        x = station_ft - self.bvc_station
        return self.g1 + self.a_pct * x / self.length

    def high_low_point(self) -> tuple[float, float] | None:
        """(station, elevation) of the curve's high (crest) or low (sag)
        point — ``None`` when the grades don't change sign."""
        if self.g1 * self.g2 > 0.0:
            return None
        x = -self.g1 * self.length / self.a_pct
        if not 0.0 <= x <= self.length:
            return None
        sta = self.bvc_station + x
        return sta, self.elevation_at(sta)

    def external_distance(self) -> float:
        """Offset from the PVI to the curve, e = A*L/800 (ft)."""
        return abs(self.a_pct) * self.length / 800.0

    def plot(self, ax=None, n: int = 200):
        """Profile view: tangents dashed, curve solid, BVC/PVI/EVC and
        the high/low point labeled with stations.  Returns the figure."""
        import matplotlib.pyplot as plt
        if ax is None:
            ax = plt.figure(figsize=(9, 5)).add_subplot(1, 1, 1)
        pad = 0.25 * self.length
        sta = np.linspace(self.bvc_station - pad, self.evc_station + pad, n)
        ax.plot(sta, [self.elevation_at(s) for s in sta], "b-", lw=2.0,
                label="profile")
        for s0, e0, s1, e1 in (
                (self.bvc_station - pad,
                 self.elevation_at(self.bvc_station - pad),
                 self.pvi_station, self.pvi_elevation),
                (self.pvi_station, self.pvi_elevation,
                 self.evc_station + pad,
                 self.elevation_at(self.evc_station + pad))):
            ax.plot([s0, s1], [e0, e1], "0.6", ls="--", lw=1.0)
        for name, s, e in (("BVC", self.bvc_station, self.bvc_elevation),
                           ("PVI", self.pvi_station, self.pvi_elevation),
                           ("EVC", self.evc_station, self.evc_elevation)):
            ax.plot(s, e, "ko", ms=5)
            ax.annotate(f"{name}\n{station_str(s)}", (s, e),
                        textcoords="offset points", xytext=(4, 6),
                        fontsize=8)
        hl = self.high_low_point()
        if hl:
            ax.plot(*hl, "r^", ms=9)
            ax.annotate(f"{'high' if self.is_crest else 'low'} point\n"
                        f"{station_str(hl[0])}, el {hl[1]:.2f}", hl,
                        textcoords="offset points", xytext=(6, -22),
                        fontsize=8, color="r")
        ax.set_xlabel("Station (ft)")
        ax.set_ylabel("Elevation (ft)")
        ax.set_title(f"Vertical Curve — g1 = {self.g1:+g}%, "
                     f"g2 = {self.g2:+g}%, L = {self.length:g} ft, "
                     f"K = {self.k_value:.0f}")
        ax.grid(True, alpha=0.3)
        return ax.get_figure()


class HorizontalCurve:
    """Simple circular curve (arc definition) with deflection angle
    ``delta_deg`` between tangents."""

    def __init__(self, radius_ft: float, delta_deg: float,
                 pi_station_ft: float = 0.0):
        self.radius = float(radius_ft)
        self.delta = math.radians(float(delta_deg))
        self.pi_station = float(pi_station_ft)

    @property
    def tangent_ft(self) -> float:
        """T = R tan(delta/2)."""
        return self.radius * math.tan(self.delta / 2.0)

    @property
    def length_ft(self) -> float:
        """Arc length L = R*delta."""
        return self.radius * self.delta

    @property
    def chord_ft(self) -> float:
        """Long chord C = 2R sin(delta/2)."""
        return 2.0 * self.radius * math.sin(self.delta / 2.0)

    @property
    def external_ft(self) -> float:
        """E = R (sec(delta/2) - 1), PI to curve midpoint."""
        return self.radius * (1.0 / math.cos(self.delta / 2.0) - 1.0)

    @property
    def middle_ordinate_ft(self) -> float:
        """M = R (1 - cos(delta/2)), chord to curve midpoint."""
        return self.radius * (1.0 - math.cos(self.delta / 2.0))

    @property
    def degree_of_curve_deg(self) -> float:
        """Arc-definition degree of curve, D = 100 ft / R in degrees."""
        return math.degrees(100.0 / self.radius)

    @property
    def pc_station(self) -> float:
        return self.pi_station - self.tangent_ft

    @property
    def pt_station(self) -> float:
        """PT runs along the arc: PC + L (not PI + T)."""
        return self.pc_station + self.length_ft

    def side_friction_demand(self, speed_mph: float,
                             superelevation: float) -> float:
        """Friction factor the curve demands at ``speed_mph`` with
        cross slope ``superelevation`` (ft/ft):
        f = V^2/(15 R) - e."""
        return speed_mph**2 / (15.0 * self.radius) - superelevation

    @staticmethod
    def min_radius(speed_mph: float, e_max: float, f_max: float) -> float:
        """Point-mass minimum radius R = V^2 / (15 (e + f))."""
        return speed_mph**2 / (15.0 * (e_max + f_max))

    def plot(self, ax=None, n: int = 200):
        """Plan view with the back tangent entering along +x: tangents
        dashed to the PI, the curve arc, and PC/PI/PT labeled with their
        stations.  Returns the figure."""
        import matplotlib.pyplot as plt
        if ax is None:
            ax = plt.figure(figsize=(8, 6)).add_subplot(1, 1, 1)
        t = self.tangent_ft
        # PC at the origin, back tangent along +x, curve turning left
        pc = np.array([0.0, 0.0])
        pi = np.array([t, 0.0])
        center = np.array([0.0, self.radius])
        angles = np.linspace(-math.pi / 2.0,
                             -math.pi / 2.0 + self.delta, n)
        arc = center + self.radius * np.column_stack(
            (np.cos(angles), np.sin(angles)))
        pt = arc[-1]
        fwd = pi + t * np.array([math.cos(self.delta),
                                 math.sin(self.delta)])
        ax.plot([pc[0] - 0.5 * t, pi[0]], [0.0, 0.0], "0.6", ls="--",
                lw=1.0)
        ax.plot([pi[0], fwd[0]], [pi[1], fwd[1]], "0.6", ls="--", lw=1.0)
        ax.plot(arc[:, 0], arc[:, 1], "b-", lw=2.2, label="curve")
        mid = center + self.radius * np.array(
            [math.cos(-math.pi / 2.0 + self.delta / 2.0),
             math.sin(-math.pi / 2.0 + self.delta / 2.0)])
        ax.plot([pi[0], mid[0]], [pi[1], mid[1]], "g:", lw=1.0)
        ax.annotate(f"E = {self.external_ft:.2f} ft",
                    ((pi[0] + mid[0]) / 2.0, (pi[1] + mid[1]) / 2.0),
                    textcoords="offset points", xytext=(4, 2), fontsize=8,
                    color="g")
        for name, pt_xy, sta in (("PC", pc, self.pc_station),
                                 ("PI", pi, self.pi_station),
                                 ("PT", pt, self.pt_station)):
            ax.plot(*pt_xy, "ko", ms=5)
            ax.annotate(f"{name} {station_str(sta)}", pt_xy,
                        textcoords="offset points", xytext=(5, -12),
                        fontsize=8)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel("(ft)")
        ax.set_ylabel("(ft)")
        ax.set_title(f"Horizontal Curve — R = {self.radius:g} ft, "
                     f"$\\Delta$ = {math.degrees(self.delta):g}°, "
                     f"D = {self.degree_of_curve_deg:.2f}°")
        ax.grid(True, alpha=0.3)
        return ax.get_figure()


class UnsymmetricalVerticalCurve(VerticalCurve):
    """Unsymmetrical (unequal-tangent) parabolic vertical curve: ``left_length_ft``
    from the BVC to the PVI station and ``right_length_ft`` from there to the
    EVC.  Two parabolas meet at the PVI station (the CVC) with a common
    tangent; with equal halves it is the :class:`VerticalCurve` parabola.

    With ``A = g2 - g1`` (decimal) the offset from the PVI down to the curve
    is ``A L1 L2 / (2 (L1 + L2))`` and the two parabolas have rates
    ``A L2 / (2 L1 (L1 + L2))`` and ``A L1 / (2 L2 (L1 + L2))``; ``length`` is
    ``L1 + L2`` and ``k_value`` uses it."""

    def __init__(self, g1_pct: float, g2_pct: float, left_length_ft: float, right_length_ft: float,
                 pvi_station_ft: float = 0.0, pvi_elevation_ft: float = 0.0):
        if left_length_ft <= 0.0 or right_length_ft <= 0.0:
            raise ValueError("both halves of an unsymmetrical vertical curve must be positive")
        super().__init__(g1_pct, g2_pct, float(left_length_ft) + float(right_length_ft),
                         pvi_station_ft, pvi_elevation_ft)
        self.left_length = float(left_length_ft)
        self.right_length = float(right_length_ft)

    @property
    def _a(self) -> float:
        return self.a_pct / 100.0

    @property
    def bvc_station(self) -> float:
        return self.pvi_station - self.left_length

    @property
    def evc_station(self) -> float:
        return self.pvi_station + self.right_length

    @property
    def bvc_elevation(self) -> float:
        return self.pvi_elevation - self.g1 / 100.0 * self.left_length

    @property
    def evc_elevation(self) -> float:
        return self.pvi_elevation + self.g2 / 100.0 * self.right_length

    @property
    def cvc_elevation(self) -> float:
        """Elevation on the curve at the PVI station (where the two parabolas meet)."""
        return self.pvi_elevation + self._a * self.left_length * self.right_length / (2.0 * self.length)

    @property
    def _rate_left(self) -> float:
        return self._a * self.right_length / (2.0 * self.left_length * self.length)

    @property
    def _rate_right(self) -> float:
        return self._a * self.left_length / (2.0 * self.right_length * self.length)

    def elevation_at(self, station_ft: float) -> float:
        if station_ft <= self.bvc_station:
            return self.pvi_elevation + self.g1 / 100.0 * (station_ft - self.pvi_station)
        if station_ft >= self.evc_station:
            return self.pvi_elevation + self.g2 / 100.0 * (station_ft - self.pvi_station)
        if station_ft <= self.pvi_station:
            x = station_ft - self.bvc_station
            return self.bvc_elevation + self.g1 / 100.0 * x + self._rate_left * x ** 2
        u = self.evc_station - station_ft
        return self.evc_elevation - self.g2 / 100.0 * u + self._rate_right * u ** 2

    def grade_at(self, station_ft: float) -> float:
        if station_ft <= self.bvc_station:
            return self.g1
        if station_ft >= self.evc_station:
            return self.g2
        if station_ft <= self.pvi_station:
            return self.g1 + 200.0 * self._rate_left * (station_ft - self.bvc_station)
        return self.g2 - 200.0 * self._rate_right * (self.evc_station - station_ft)

    def high_low_point(self) -> tuple[float, float] | None:
        if self.g1 * self.g2 > 0.0:
            return None
        g_cvc = self.g1 + 200.0 * self._rate_left * self.left_length          # grade at the CVC (percent)
        if self.g1 * g_cvc <= 0.0:                                             # turns on the left parabola
            x = -self.g1 / (200.0 * self._rate_left)
            sta = self.bvc_station + x
        else:                                                                  # turns on the right parabola
            u = self.g2 / (200.0 * self._rate_right)
            sta = self.evc_station - u
        return sta, self.elevation_at(sta)
