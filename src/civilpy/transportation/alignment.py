"""Composed roadway alignment: a chained horizontal geometry (tangents and
circular curves) with a vertical profile, exposing the station/offset
placement contract every bridge object is located by.

This is the native placement object for the bridge/analysis pipeline.  The
individual curve primitives live in :mod:`civilpy.transportation.curves`
(``HorizontalCurve``, ``VerticalCurve``); this module chains them head to
tail so a component can ask for a 3D point at ``(station, offset)``.

Conventions
-----------
* Plan coordinates are ``(x=East, y=North)`` in feet.
* Bearings are **azimuths in degrees, clockwise from North (+y)**; the unit
  direction of increasing station is ``d = (sin az, cos az)``.
* **Positive offset is to the right** of the direction of increasing station
  (``r = (cos az, -sin az)``), matching the usual roadway right-is-positive
  offset sense.
* Elevation comes from the vertical profile; when a profile is omitted the
  alignment is flat at ``z = 0``.

Horizontal elements are :class:`Tangent`, :class:`Curve` (circular arc) and
:class:`Spiral` (clothoid: curvature varies linearly with length, for
entering, exiting and compound transitions).

**Stationing.**  Every geometry method takes the *continuous* station
``start_station + distance along the alignment``.  Plans may carry
**station equations** (``station_equations=[(back, ahead), ...]``, each at a
point on the alignment); :meth:`Alignment.display_station` and
:meth:`Alignment.continuous_station` convert between the two.

**Cross slope.**  ``superelevation=[(station, left_pct, right_pct), ...]`` is
interpolated linearly by :meth:`Alignment.cross_slope_at` (positive = rising
away from the centerline).  It is only applied to offset elevations when
``point_at(..., apply_cross_slope=True)`` is asked for, so existing callers
keep centerline-profile elevations.  Runoff/runout design rules are not
modeled; the table is whatever the design says.

Examples
--------
A tangent, a 500-ft-radius curve turning right through 30 deg, then a tangent,
starting at the origin headed due north, stationed from 10+00:

>>> from civilpy.transportation.curves import HorizontalCurve
>>> al = Alignment(
...     start_point=(0.0, 0.0), start_bearing_deg=0.0, start_station_ft=1000.0,
...     elements=[Tangent(200.0),
...               Curve(radius_ft=500.0, delta_deg=30.0, direction="R"),
...               Tangent(200.0)])
>>> round(al.length_ft, 3)
661.799
>>> x, y, z = al.point_at(1000.0, 0.0)          # start, on centerline
>>> round(x, 6), round(y, 6), round(z, 6)
(0.0, 0.0, 0.0)
>>> round(al.bearing_at(1100.0), 6)             # still on first tangent
0.0
>>> x, y, _ = al.point_at(1100.0, 25.0)         # 25 ft right of a north tangent
>>> round(x, 6), round(y, 6)
(25.0, 100.0)
>>> sta, off = al.station_offset_of((25.0, 100.0))
>>> round(sta, 6), round(off, 6)
(1100.0, 25.0)
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass

from civilpy.transportation.curves import HorizontalCurve, station_str
from typing import Literal


def _dir(az_deg: float) -> tuple[float, float]:
    """Unit vector of increasing station for azimuth ``az_deg`` (cw from N)."""
    a = math.radians(az_deg)
    return math.sin(a), math.cos(a)


def _right(az_deg: float) -> tuple[float, float]:
    """Unit vector to the right of the direction of increasing station."""
    a = math.radians(az_deg)
    return math.cos(a), -math.sin(a)


@dataclass
class Tangent:
    """A straight run of length ``length_ft`` along the current bearing."""

    length_ft: float

    @property
    def length(self) -> float:
        return float(self.length_ft)


@dataclass
class Curve:
    """A circular arc of ``radius_ft`` sweeping ``delta_deg`` to the left
    (``direction='L'``) or right (``direction='R'``)."""

    radius_ft: float
    delta_deg: float
    #: Turn direction looking up-station: ``"R"`` (right) or ``"L"``.
    direction: Literal["R", "L"] = "R"

    def __post_init__(self):
        d = str(self.direction).upper()
        if d not in ("L", "R"):
            raise ValueError("direction must be 'L' or 'R'")
        self.direction = d
        if self.radius_ft <= 0.0:
            raise ValueError("radius_ft must be positive")
        if self.delta_deg <= 0.0:
            raise ValueError("delta_deg must be positive")

    @property
    def sign(self) -> int:
        """+1 for a right turn (azimuth increases), -1 for a left turn."""
        return 1 if self.direction == "R" else -1

    @property
    def hcurve(self) -> HorizontalCurve:
        """The underlying :class:`HorizontalCurve` (for T, L, D, E, M)."""
        return HorizontalCurve(self.radius_ft, self.delta_deg)

    @property
    def length(self) -> float:
        """Arc length ``R * delta``."""
        return self.radius_ft * math.radians(self.delta_deg)


@dataclass
class Spiral:
    """A clothoid transition of ``length_ft`` whose radius runs from
    ``radius_start_ft`` to ``radius_end_ft`` (``math.inf`` = tangent), turning
    ``direction`` ('R' or 'L').

    Curvature ``1/R`` varies linearly with length, so an entering spiral is
    ``Spiral(L, math.inf, R)``, an exiting spiral ``Spiral(L, R, math.inf)``
    and a compound transition ``Spiral(L, R1, R2)``.  Both radii may not be
    infinite.
    """

    length_ft: float
    radius_start_ft: float = math.inf
    radius_end_ft: float = math.inf
    #: Turn direction looking up-station: ``"R"`` (right) or ``"L"``.
    direction: Literal["R", "L"] = "R"

    def __post_init__(self):
        d = str(self.direction).upper()
        if d not in ("L", "R"):
            raise ValueError("direction must be 'L' or 'R'")
        self.direction = d
        if self.length_ft <= 0.0:
            raise ValueError("length_ft must be positive")
        for r in (self.radius_start_ft, self.radius_end_ft):
            if r <= 0.0:
                raise ValueError("radii must be positive (math.inf for a tangent)")
        if math.isinf(self.radius_start_ft) and math.isinf(self.radius_end_ft):
            raise ValueError("a spiral needs at least one finite radius")

    @property
    def sign(self) -> int:
        return 1 if self.direction == "R" else -1

    @property
    def length(self) -> float:
        return float(self.length_ft)

    @property
    def k0(self) -> float:
        """Curvature (1/ft) at the start."""
        return 0.0 if math.isinf(self.radius_start_ft) else 1.0 / self.radius_start_ft

    @property
    def k1(self) -> float:
        """Curvature (1/ft) at the end."""
        return 0.0 if math.isinf(self.radius_end_ft) else 1.0 / self.radius_end_ft

    def turn_rad(self, s: float) -> float:
        """Unsigned heading change (radians) over the first ``s`` feet."""
        return self.k0 * s + (self.k1 - self.k0) * s * s / (2.0 * self.length)

    @property
    def delta_deg(self) -> float:
        """Total (unsigned) deflection of the spiral, degrees."""
        return math.degrees(self.turn_rad(self.length))


# 16-point Gauss-Legendre nodes/weights on [-1, 1]: exact for polynomials of
# degree 31, so a clothoid's (sin, cos) of a quadratic heading integrates to
# ~1e-12 relative for any practical spiral in one pass.
_GL_X, _GL_W = None, None


def _gauss_legendre():
    global _GL_X, _GL_W
    if _GL_X is None:
        import numpy as np

        _GL_X, _GL_W = np.polynomial.legendre.leggauss(16)
    return _GL_X, _GL_W


def _spiral_offset(el: "Spiral", az0_deg: float, s: float) -> tuple[float, float]:
    """Plan displacement (dx, dy) after ``s`` feet of spiral ``el`` from
    azimuth ``az0_deg``: the integral of the unit direction over [0, s]."""
    if s <= 0.0:
        return 0.0, 0.0
    xs, ws = _gauss_legendre()
    a0 = math.radians(az0_deg)
    n = max(1, int(math.ceil(s / 500.0)))      # split very long spirals
    h = s / n
    dx = dy = 0.0
    for k in range(n):
        lo = k * h
        for x, w in zip(xs, ws):
            t = lo + (x + 1.0) * h / 2.0
            a = a0 + el.sign * el.turn_rad(t)
            dx += w * math.sin(a) * h / 2.0
            dy += w * math.cos(a) * h / 2.0
    return dx, dy


@dataclass
class VerticalProfile:
    """Elevation as a function of station from a list of PVIs.

    ``pvis`` is an ordered list of ``(station_ft, elevation_ft, curve_len_ft)``
    or, for an unsymmetrical curve, ``(station_ft, elevation_ft, len_in_ft,
    len_out_ft)``.  The first and last entries are the profile ends and should
    use ``curve_len_ft = 0``.  Between consecutive PVIs the grade is straight;
    interior PVIs with a non-zero curve length carry a parabola (an
    equal-tangent :class:`~civilpy.transportation.curves.VerticalCurve`, or an
    :class:`~civilpy.transportation.curves.UnsymmetricalVerticalCurve` when the
    two halves differ).  After construction ``pvis`` always holds 3-tuples with
    the total curve length; ``pvi_lengths`` holds each PVI's ``(len_in,
    len_out)`` so writers can tell the two kinds apart."""

    pvis: list[tuple[float, ...]]

    def __post_init__(self):
        from civilpy.transportation.curves import UnsymmetricalVerticalCurve, VerticalCurve

        pv, halves = [], []
        for p in self.pvis:
            if len(p) == 4:
                s, e, l_in, l_out = (float(v) for v in p)
                if (l_in > 0.0) != (l_out > 0.0):
                    raise ValueError("an unsymmetrical curve needs both halves positive")
                pv.append((s, e, l_in + l_out))
                halves.append((l_in, l_out))
            else:
                s, e, L = (float(v) for v in p)
                pv.append((s, e, L))
                halves.append((L / 2.0, L / 2.0))
        if len(pv) < 2:
            raise ValueError("a profile needs at least two PVIs (the ends)")
        self.pvis = pv
        self.pvi_lengths = halves
        self._grades = []                       # grade (%) of each PVI->PVI leg
        for (s0, e0, _), (s1, e1, _) in zip(pv, pv[1:]):
            if s1 <= s0:
                raise ValueError("PVI stations must strictly increase")
            self._grades.append((e1 - e0) / (s1 - s0) * 100.0)
        self._curves = []                       # (bvc, evc, VerticalCurve)
        for i in range(1, len(pv) - 1):
            L = pv[i][2]
            if L <= 0.0:
                continue
            l_in, l_out = halves[i]
            if abs(l_in - l_out) > 1e-9:
                vc = UnsymmetricalVerticalCurve(self._grades[i - 1], self._grades[i], l_in, l_out,
                                                pvi_station_ft=pv[i][0], pvi_elevation_ft=pv[i][1])
            else:
                vc = VerticalCurve(self._grades[i - 1], self._grades[i], L,
                                   pvi_station_ft=pv[i][0], pvi_elevation_ft=pv[i][1])
            self._curves.append((vc.bvc_station, vc.evc_station, vc))

    def elevation_at(self, station_ft: float) -> float:
        for bvc, evc, vc in self._curves:
            if bvc <= station_ft <= evc:
                return vc.elevation_at(station_ft)
        pv = self.pvis
        if station_ft <= pv[0][0]:
            return pv[0][1] + self._grades[0] / 100.0 * (station_ft - pv[0][0])
        if station_ft >= pv[-1][0]:
            return pv[-1][1] + self._grades[-1] / 100.0 * (station_ft - pv[-1][0])
        for i in range(len(pv) - 1):
            if pv[i][0] <= station_ft <= pv[i + 1][0]:
                return pv[i][1] + self._grades[i] / 100.0 * (station_ft - pv[i][0])
        return pv[-1][1]                         # unreachable given the bounds


class Alignment:
    """A chained horizontal alignment with an optional vertical profile.

    Parameters
    ----------
    start_point : (float, float)
        Plan ``(x, y)`` of the alignment start, feet.
    start_bearing_deg : float
        Azimuth of increasing station at the start (deg, cw from North).
    elements : list[Tangent | Curve | Spiral]
        Ordered horizontal elements laid head to tail.
    profile : VerticalProfile, optional
        Vertical profile; when omitted the alignment is flat at ``z = 0``.
    start_station_ft : float
        Station value at ``start_point``.
    station_equations : list[(back_ft, ahead_ft)], optional
        Station equations in order along the alignment.  ``back`` is the
        displayed station arriving at the equation point, ``ahead`` the
        displayed station leaving it.
    superelevation : list[(station_ft, left_pct, right_pct)], optional
        Cross slopes by continuous station, interpolated linearly.
    """

    def __init__(self, start_point: tuple[float, float],
                 start_bearing_deg: float,
                 elements: list,
                 profile: VerticalProfile | None = None,
                 start_station_ft: float = 0.0,
                 station_equations: list[tuple[float, float]] | None = None,
                 superelevation: list[tuple[float, float, float]] | None = None):
        self.start_point = (float(start_point[0]), float(start_point[1]))
        self.start_bearing = float(start_bearing_deg)
        self.elements = list(elements)
        self.profile = profile
        self.start_station = float(start_station_ft)
        self.station_equations = [(float(b), float(a)) for b, a in (station_equations or [])]
        self.superelevation = sorted((float(s), float(lft), float(rt))
                                     for s, lft, rt in (superelevation or []))
        self._segments = self._build()
        self._equation_table = self._build_equations()

    # -- construction from survey points -----------------------------------

    @classmethod
    def between_points(cls, p0: tuple[float, float], p1: tuple[float, float],
                       *, start_station_ft: float = 0.0,
                       radius_ft: float | None = None,
                       direction: Literal["R", "L"] = "R",
                       start_elev_ft: float | None = None,
                       end_elev_ft: float | None = None,
                       terrain=None) -> "Alignment":
        """Build an alignment between two plan points, deriving bearing, length,
        and grade -- the conceptual-design workflow where you can't drape an
        alignment on the ground but can pick two endpoints and a curvature.

        With no ``radius_ft`` the horizontal alignment is a single tangent from
        ``p0`` to ``p1`` (bearing = the azimuth p0->p1, length = the distance).
        Give ``radius_ft`` and the two points are joined by one circular arc of
        that radius turning ``direction`` ("R"/"L"); the required deflection and
        start bearing are back-computed from the chord.

        Grade comes from the endpoint elevations: pass ``start_elev_ft`` /
        ``end_elev_ft`` directly, or a ``terrain`` (anything with
        ``elevation_at(x, y)``) to sample the ground at each point.  When no
        elevations are available the alignment is flat (z = 0).  The profile is
        a single straight grade; add crest/sag :class:`VerticalProfile` PVIs
        later for a real vertical curve.
        """
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
        dx, dy = x1 - x0, y1 - y0
        chord = math.hypot(dx, dy)
        if chord <= 0.0:
            raise ValueError("p0 and p1 must be distinct points")
        az_chord = math.degrees(math.atan2(dx, dy))   # cw from North

        if radius_ft is None:
            start_bearing = az_chord
            elements: list = [Tangent(chord)]
            length = chord
        else:
            if radius_ft < chord / 2.0:
                raise ValueError(
                    f"radius {radius_ft} ft is too small to join points "
                    f"{chord:.2f} ft apart (min {chord / 2.0:.2f} ft)")
            d = str(direction).upper()
            sign = 1 if d == "R" else -1
            delta = math.degrees(2.0 * math.asin(chord / (2.0 * radius_ft)))
            start_bearing = az_chord - sign * delta / 2.0
            elements = [Curve(radius_ft=radius_ft, delta_deg=delta, direction=d)]
            length = radius_ft * math.radians(delta)

        # Vertical profile from endpoint elevations (terrain-sampled if given).
        if terrain is not None:
            if start_elev_ft is None:
                start_elev_ft = terrain.elevation_at(x0, y0)
            if end_elev_ft is None:
                end_elev_ft = terrain.elevation_at(x1, y1)
        profile = None
        if start_elev_ft is not None and end_elev_ft is not None:
            end_station = start_station_ft + length
            profile = VerticalProfile([
                (start_station_ft, float(start_elev_ft), 0.0),
                (end_station, float(end_elev_ft), 0.0)])

        return cls((x0, y0), start_bearing, elements, profile=profile,
                   start_station_ft=start_station_ft)

    # -- geometry table ----------------------------------------------------

    def _build(self) -> list[dict]:
        """Precompute per-element start position/bearing/station."""
        segs = []
        x, y = self.start_point
        az = self.start_bearing
        s0 = self.start_station
        for el in self.elements:
            seg = {"el": el, "x0": x, "y0": y, "az0": az,
                   "s0": s0, "s1": s0 + el.length}
            if isinstance(el, Tangent):
                dx, dy = _dir(az)
                x, y = x + dx * el.length, y + dy * el.length
            elif isinstance(el, Curve):
                cx, cy = self._center(x, y, az, el)
                seg["cx"], seg["cy"] = cx, cy
                az = az + el.sign * el.delta_deg
                x, y = self._arc_point(cx, cy, az, el)
            elif isinstance(el, Spiral):
                dx, dy = _spiral_offset(el, az, el.length)
                x, y = x + dx, y + dy
                az = az + el.sign * el.delta_deg
            else:
                raise TypeError(f"unknown alignment element: {el!r}")
            seg["x1"], seg["y1"], seg["az1"] = x, y, az
            segs.append(seg)
            s0 = seg["s1"]
        return segs

    @staticmethod
    def _center(x: float, y: float, az: float, el: "Curve") -> tuple[float, float]:
        rx, ry = _right(az)
        return (x + el.sign * el.radius_ft * rx,
                y + el.sign * el.radius_ft * ry)

    @staticmethod
    def _arc_point(cx: float, cy: float, az: float,
                   el: "Curve") -> tuple[float, float]:
        rx, ry = _right(az)
        return (cx - el.sign * el.radius_ft * rx,
                cy - el.sign * el.radius_ft * ry)

    @property
    def length_ft(self) -> float:
        return sum(el.length for el in self.elements)

    @property
    def end_station(self) -> float:
        return self.start_station + self.length_ft

    # -- forward: station -> geometry -------------------------------------

    def _seg_at(self, station_ft: float) -> dict:
        for seg in self._segments:
            if seg["s0"] <= station_ft <= seg["s1"]:
                return seg
        if station_ft < self._segments[0]["s0"]:
            return self._segments[0]
        return self._segments[-1]

    def _on_point(self, station_ft: float) -> tuple[float, float, float]:
        """Centerline (x, y, bearing) at ``station_ft`` (extrapolates the end
        tangents past the alignment ends)."""
        seg = self._seg_at(station_ft)
        s = station_ft - seg["s0"]
        el = seg["el"]
        if isinstance(el, Tangent):
            dx, dy = _dir(seg["az0"])
            return seg["x0"] + dx * s, seg["y0"] + dy * s, seg["az0"]
        if isinstance(el, Spiral):
            if s >= el.length:                     # extrapolate past the end on its tangent
                dx, dy = _dir(seg["az1"])
                over = s - el.length
                return seg["x1"] + dx * over, seg["y1"] + dy * over, seg["az1"]
            if s <= 0.0:
                dx, dy = _dir(seg["az0"])
                return seg["x0"] + dx * s, seg["y0"] + dy * s, seg["az0"]
            dx, dy = _spiral_offset(el, seg["az0"], s)
            return (seg["x0"] + dx, seg["y0"] + dy,
                    seg["az0"] + el.sign * math.degrees(el.turn_rad(s)))
        az = seg["az0"] + el.sign * math.degrees(s / el.radius_ft)
        px, py = self._arc_point(seg["cx"], seg["cy"], az, el)
        return px, py, az

    def bearing_at(self, station_ft: float) -> float:
        """Azimuth (deg, cw from North) of increasing station at ``station``."""
        return self._on_point(station_ft)[2] % 360.0

    def elevation_at(self, station_ft: float) -> float:
        """Profile elevation at ``station`` (``0.0`` with no profile)."""
        if self.profile is None:
            return 0.0
        return self.profile.elevation_at(station_ft)

    def point_at(self, station_ft: float,
                 offset_ft: float = 0.0,
                 apply_cross_slope: bool = False) -> tuple[float, float, float]:
        """3D point at ``(station, offset)``.  Positive offset is to the right
        of increasing station; elevation is the centerline profile elevation,
        plus the cross slope on that side when ``apply_cross_slope``."""
        x, y, az = self._on_point(station_ft)
        rx, ry = _right(az)
        z = self.elevation_at(station_ft)
        if apply_cross_slope and offset_ft:
            left, right = self.cross_slope_at(station_ft)
            z += abs(offset_ft) * (right if offset_ft > 0 else left) / 100.0
        return (x + rx * offset_ft, y + ry * offset_ft, z)

    def cross_slope_at(self, station_ft: float) -> tuple[float, float]:
        """(left_pct, right_pct) at ``station`` from the superelevation table
        (linear between entries, held flat past the ends; (0, 0) when empty)."""
        tab = self.superelevation
        if not tab:
            return 0.0, 0.0
        if station_ft <= tab[0][0]:
            return tab[0][1], tab[0][2]
        if station_ft >= tab[-1][0]:
            return tab[-1][1], tab[-1][2]
        for (s0, l0, r0), (s1, l1, r1) in zip(tab, tab[1:]):
            if s0 <= station_ft <= s1:
                f = 0.0 if s1 == s0 else (station_ft - s0) / (s1 - s0)
                return l0 + f * (l1 - l0), r0 + f * (r1 - r0)
        return tab[-1][1], tab[-1][2]

    # -- station equations -------------------------------------------------

    def _build_equations(self) -> list[tuple[float, float, float]]:
        """[(continuous_start, display_start, display_end)] per stationing region."""
        regions = []
        cont = self.start_station
        disp = self.start_station
        for back, ahead in self.station_equations:
            if back < disp:
                raise ValueError(f"station equation back {back} precedes the region start {disp}")
            cont_eq = cont + (back - disp)
            regions.append((cont, disp, back))
            cont, disp = cont_eq, ahead
        regions.append((cont, disp, disp + (self.end_station - cont)))
        return regions

    def display_station(self, station_ft: float) -> tuple[float, int]:
        """(displayed station, region index) for a continuous station.

        Region 0 runs from the start to the first equation, region ``i`` from
        equation ``i`` onward.  At an equation point the ahead region wins."""
        regions = self._equation_table
        for i in range(len(regions) - 1, -1, -1):
            c0, d0, _ = regions[i]
            if station_ft >= c0 or i == 0:
                return d0 + (station_ft - c0), i
        return station_ft, 0                         # unreachable

    def continuous_station(self, display_ft: float, region: int | None = None) -> float:
        """Continuous station for a displayed station.

        With overlapping stationing a displayed value can occur in several
        regions; pass ``region`` then (``ValueError`` if ambiguous or absent)."""
        regions = self._equation_table
        if region is not None:
            c0, d0, _ = regions[region]
            return c0 + (display_ft - d0)
        hits = [c0 + (display_ft - d0) for c0, d0, d1 in regions if d0 <= display_ft <= d1]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ValueError(f"displayed station {display_ft} is not on this alignment")
        raise ValueError(f"displayed station {display_ft} occurs in {len(hits)} regions; pass region=")

    def frame_at(self, station_ft: float) -> dict:
        """Local frame at ``station``: ``point`` (x, y, z), unit ``tangent``
        and unit ``right`` (both plan) for sweeping templates."""
        x, y, az = self._on_point(station_ft)
        return {"point": (x, y, self.elevation_at(station_ft)),
                "tangent": _dir(az), "right": _right(az),
                "bearing_deg": az % 360.0}

    # -- inverse: point -> station/offset ---------------------------------

    def station_offset_of(self, point: tuple[float, float]) -> tuple[float, float]:
        """Nearest ``(station, offset)`` for a plan ``point`` (x, y).

        Offset is signed (right positive).  Ties resolve to the earliest
        station."""
        qx, qy = float(point[0]), float(point[1])
        best = None
        for seg in self._segments:
            st = self._closest_on_segment(seg, qx, qy)
            if st is None:
                continue
            station, dist = st
            if best is None or dist < best[1] - 1e-9:
                best = (station, dist)
        if best is None:
            best = (self.start_station, 0.0)
        station = best[0]
        x, y, az = self._on_point(station)
        rx, ry = _right(az)
        offset = (qx - x) * rx + (qy - y) * ry
        return station, offset

    def _closest_on_segment(self, seg: dict, qx: float,
                            qy: float) -> tuple[float, float] | None:
        el = seg["el"]
        if isinstance(el, Tangent):
            dx, dy = _dir(seg["az0"])
            t = (qx - seg["x0"]) * dx + (qy - seg["y0"]) * dy
            t = max(0.0, min(el.length, t))
            fx, fy = seg["x0"] + dx * t, seg["y0"] + dy * t
            return seg["s0"] + t, math.hypot(qx - fx, qy - fy)
        if isinstance(el, Spiral):
            return self._closest_on_spiral(seg, qx, qy)
        # arc: measure angular progress in the travel direction, then test the
        # interior projection and both endpoints and keep the nearest.
        cx, cy = seg["cx"], seg["cy"]
        a0 = math.atan2(seg["y0"] - cy, seg["x0"] - cx)
        ang = math.atan2(qy - cy, qx - cx)
        swept = math.radians(el.delta_deg)          # total swept angle (>0)
        # the center-angle advances by -sign as station increases
        prog = (-el.sign * (ang - a0)) % (2.0 * math.pi)
        cand_s = [0.0, el.length]
        if prog <= swept:
            cand_s.append(prog * el.radius_ft)
        best = None
        for s in cand_s:
            px, py, _ = self._on_point(seg["s0"] + s)
            dist = math.hypot(qx - px, qy - py)
            if best is None or dist < best[1]:
                best = (seg["s0"] + s, dist)
        return best

    def _closest_on_spiral(self, seg: dict, qx: float, qy: float) -> tuple[float, float]:
        """Nearest point on a spiral: coarse sampling, then golden-section refine."""
        el = seg["el"]

        def dist(s):
            px, py, _ = self._on_point(seg["s0"] + s)
            return math.hypot(qx - px, qy - py)

        n = 64
        samples = [el.length * i / n for i in range(n + 1)]
        i_best = min(range(n + 1), key=lambda i: dist(samples[i]))
        lo = samples[max(0, i_best - 1)]
        hi = samples[min(n, i_best + 1)]
        g = (math.sqrt(5.0) - 1.0) / 2.0
        a, b = lo, hi
        c, d = b - g * (b - a), a + g * (b - a)
        for _ in range(80):
            if dist(c) < dist(d):
                b = d
            else:
                a = c
            c, d = b - g * (b - a), a + g * (b - a)
        s = (a + b) / 2.0
        return seg["s0"] + s, dist(s)

    def __repr__(self):
        return (f"Alignment(start_sta={station_str(self.start_station)}, "
                f"len={self.length_ft:.2f} ft, "
                f"{len(self.elements)} elements)")
