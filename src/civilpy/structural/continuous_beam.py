#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Continuous-beam analysis for line girders (the offline substitute for a live
MIDAS run when producing dead-load and moving-load moment envelopes).

A prismatic (or piecewise-``EI``) beam on simple supports is solved by the
direct-stiffness / slope-deflection method with the support rotations as the
only unknowns (every support pins the vertical translation).  From the solved
member-end moments the support reactions follow, and the bending moment at any
section is then pure statics.

Moving-load envelopes come from **influence lines**: a unit load is walked
across the span and the moment at the section of interest recorded, giving an
:class:`~civilpy.structural.influence_lines.InfluenceLine` that the existing
``hl93_effect`` / ``maximize_axle_train`` machinery turns into an HL-93 envelope.

Sign convention: downward loads positive; sagging bending moment positive.
Lengths in feet, loads in kips / kip-ft, ``ei`` in consistent units (its
absolute value cancels for statically-determinate reactions but sets the
distribution across an indeterminate beam, so only relative ``ei`` matters)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from civilpy.structural.influence_lines import (
    InfluenceLine, influence_line_from_ordinates,
)


@dataclass
class _UDL:
    w: float
    x0: float
    x1: float


@dataclass
class _Point:
    p: float
    x: float


@dataclass
class ContinuousBeam:
    """A continuous beam defined by its ordered support positions (ft).

    >>> b = ContinuousBeam([0.0, 20.0, 40.0])   # two 20-ft spans
    >>> b.add_udl(2.0)                            # 2 klf everywhere
    >>> round(b.moment_at(20.0), 3)               # interior support: -wL^2/8
    -100.0
    """

    supports: list[float]
    ei: float = 1.0
    _loads: list = field(default_factory=list)

    def __post_init__(self):
        self.supports = [float(s) for s in self.supports]
        if list(self.supports) != sorted(self.supports):
            raise ValueError("support positions must be increasing")
        if len(self.supports) < 2:
            raise ValueError("need at least two supports")

    @property
    def length(self) -> float:
        return self.supports[-1] - self.supports[0]

    # ---- load application --------------------------------------------------
    def add_udl(self, w: float, x0: float | None = None,
                x1: float | None = None) -> "ContinuousBeam":
        """Add a uniform load ``w`` (kip/ft, down +) over ``[x0, x1]`` (default
        the whole beam)."""
        self._loads.append(_UDL(w, self.supports[0] if x0 is None else x0,
                                self.supports[-1] if x1 is None else x1))
        return self

    def add_point(self, p: float, x: float) -> "ContinuousBeam":
        """Add a point load ``p`` (kip, down +) at station ``x`` (ft)."""
        self._loads.append(_Point(p, x))
        return self

    # ---- fixed-end moments -------------------------------------------------
    def _span_fem(self, a: float, b: float, loads) -> tuple[float, float]:
        """Fixed-end moments (M_ab, M_ba) for span ``[a, b]`` under ``loads``,
        sagging-positive member-end-moment convention
        (``FEM_ab = -wL^2/12``, ``FEM_ba = +wL^2/12`` for a full UDL)."""
        span = b - a
        m_ab = m_ba = 0.0
        for ld in loads:
            if isinstance(ld, _UDL):
                lo, hi = max(ld.x0, a), min(ld.x1, b)
                if hi <= lo:
                    continue
                # discretize a partial UDL into point loads (exact enough at
                # the sampling below); a full-span UDL hits the closed form.
                if abs(lo - a) < 1e-9 and abs(hi - b) < 1e-9:
                    m_ab += -ld.w * span ** 2 / 12.0
                    m_ba += ld.w * span ** 2 / 12.0
                else:
                    n = max(2, int((hi - lo) / span * 50) + 2)
                    dx = (hi - lo) / n
                    for i in range(n):
                        xc = lo + (i + 0.5) * dx
                        fab, fba = self._point_fem(xc - a, span, ld.w * dx)
                        m_ab += fab
                        m_ba += fba
            elif isinstance(ld, _Point) and self._in_span(ld.x, a, b):
                fab, fba = self._point_fem(ld.x - a, span, ld.p)
                m_ab += fab
                m_ba += fba
        return m_ab, m_ba

    def _in_span(self, x: float, a: float, b: float) -> bool:
        """Half-open span membership ``[a, b)`` so a point load exactly at an
        interior support is counted once (in the span to its right, where it
        feeds straight into that support's reaction); the last span includes
        its right end."""
        if x < a - 1e-9:
            return False
        if b >= self.supports[-1] - 1e-9:
            return x <= b + 1e-9
        return x < b - 1e-9

    @staticmethod
    def _point_fem(dist: float, span: float, p: float) -> tuple[float, float]:
        """FEM for a point load ``p`` at ``dist`` from the left end of a span of
        length ``span``: ``M_ab = -P a b^2 / L^2``, ``M_ba = +P a^2 b / L^2``."""
        a = min(max(dist, 0.0), span)
        b = span - a
        return (-p * a * b ** 2 / span ** 2, p * a ** 2 * b / span ** 2)

    # ---- solve -------------------------------------------------------------
    def _end_moments(self, loads):
        """Solve support rotations and return per-span (M_left, M_right)
        member-end moments (sagging positive)."""
        n = len(self.supports)
        k = np.zeros((n, n))
        f = np.zeros(n)
        fems = []
        for e in range(n - 1):
            a, b = self.supports[e], self.supports[e + 1]
            span = b - a
            r = 2.0 * self.ei / span
            # slope-deflection rotational stiffness for the span
            k[e, e] += 2.0 * r
            k[e, e + 1] += r
            k[e + 1, e] += r
            k[e + 1, e + 1] += 2.0 * r
            m_ab, m_ba = self._span_fem(a, b, loads)
            fems.append((m_ab, m_ba))
            # nodal equilibrium: sum of member-end moments at a node = 0
            f[e] -= m_ab
            f[e + 1] -= m_ba
        theta = np.linalg.solve(k, f)
        end_moments = []
        for e in range(n - 1):
            a, b = self.supports[e], self.supports[e + 1]
            r = 2.0 * self.ei / (b - a)
            m_ab = r * (2.0 * theta[e] + theta[e + 1]) + fems[e][0]
            m_ba = r * (theta[e] + 2.0 * theta[e + 1]) + fems[e][1]
            end_moments.append((m_ab, m_ba))
        return end_moments

    def reactions(self, loads=None) -> list[float]:
        """Support reactions (kip, up +) under the applied (or supplied) loads."""
        loads = self._loads if loads is None else loads
        ends = self._end_moments(loads)
        n = len(self.supports)
        r = [0.0] * n
        for e in range(n - 1):
            a, b = self.supports[e], self.supports[e + 1]
            span = b - a
            m_ab, m_ba = ends[e]
            # simple-span shear at each end from the span loads, then the
            # end-moment couple (m_ab + m_ba)/L redistributes it.
            w_tot, m_about_a = self._span_load_resultant(a, b, loads)
            # Support bending moments (sagging +) are M_A = m_ab, M_B = -m_ba in
            # the slope-deflection (clockwise-positive) convention, so the end
            # moments add a constant shear (M_B - M_A)/L = -(m_ab + m_ba)/L to
            # the simple-span left reaction.
            v_a = m_about_a_to_shear(w_tot, m_about_a, span) - (m_ab + m_ba) / span
            v_b = w_tot - v_a
            r[e] += v_a
            r[e + 1] += v_b
        return r

    def _span_load_resultant(self, a, b, loads):
        """Total downward load on span ``[a,b]`` and its moment about ``a``."""
        w_tot = 0.0
        m_a = 0.0
        for ld in loads:
            if isinstance(ld, _UDL):
                lo, hi = max(ld.x0, a), min(ld.x1, b)
                if hi <= lo:
                    continue
                w = ld.w * (hi - lo)
                xc = 0.5 * (lo + hi)
                w_tot += w
                m_a += w * (xc - a)
            elif isinstance(ld, _Point) and self._in_span(ld.x, a, b):
                w_tot += ld.p
                m_a += ld.p * (ld.x - a)
        return w_tot, m_a

    def moment_at(self, x: float, loads=None) -> float:
        """Bending moment (kip-ft, sagging +) at station ``x`` by statics from
        the solved reactions and the loads to the left of ``x``."""
        loads = self._loads if loads is None else loads
        r = self.reactions(loads)
        m = 0.0
        for xi, ri in zip(self.supports, r):
            if xi < x - 1e-12:
                m += ri * (x - xi)
        for ld in loads:
            if isinstance(ld, _UDL):
                lo, hi = ld.x0, min(ld.x1, x)
                if hi > lo:
                    w = ld.w * (hi - lo)
                    xc = 0.5 * (lo + hi)
                    m -= w * (x - xc)
            elif isinstance(ld, _Point) and ld.x < x - 1e-12:
                m -= ld.p * (x - ld.x)
        return m

    def shear_at(self, x: float, loads=None) -> float:
        """Shear (kip, left-limit) at station ``x`` by statics: reactions minus
        applied loads to the left of ``x``."""
        loads = self._loads if loads is None else loads
        r = self.reactions(loads)
        v = 0.0
        for xi, ri in zip(self.supports, r):
            if xi < x - 1e-12:
                v += ri
        for ld in loads:
            if isinstance(ld, _UDL):
                lo, hi = ld.x0, min(ld.x1, x)
                if hi > lo:
                    v -= ld.w * (hi - lo)
            elif isinstance(ld, _Point) and ld.x < x - 1e-12:
                v -= ld.p
        return v

    def diagrams(self, xs=None, n: int = 201, loads=None):
        """``(stations, shears, moments)`` at ``xs`` (or ``n`` even stations).

        One reactions solve, then vectorized statics — the fast path for
        diagram sampling and moving-load envelopes.  Shear and moment take
        their left-limit value at a support or point-load station."""
        loads = self._loads if loads is None else loads
        if xs is None:
            xs = np.linspace(self.supports[0], self.supports[-1], n)
        x = np.asarray(xs, dtype=float)
        v = np.zeros_like(x)
        m = np.zeros_like(x)
        for xi, ri in zip(self.supports, self.reactions(loads)):
            left = x > xi + 1e-12
            v += np.where(left, ri, 0.0)
            m += np.where(left, ri * (x - xi), 0.0)
        for ld in loads:
            if isinstance(ld, _UDL):
                c = np.clip(np.minimum(x, ld.x1) - ld.x0, 0.0, None)
                v -= ld.w * c
                m -= ld.w * c * (x - ld.x0 - 0.5 * c)
            elif isinstance(ld, _Point):
                past = x > ld.x + 1e-12
                v -= np.where(past, ld.p, 0.0)
                m -= np.where(past, ld.p * (x - ld.x), 0.0)
        return list(x), v, m

    def moment_diagram(self, n: int = 201, loads=None):
        """``(stations, moments)`` sampled ``n`` points along the beam."""
        xs, _, m = self.diagrams(n=n, loads=loads)
        return xs, list(m)

    def shear_diagram(self, n: int = 201, loads=None):
        """``(stations, shears)`` sampled ``n`` points along the beam."""
        xs, v, _ = self.diagrams(n=n, loads=loads)
        return xs, list(v)

    def deflection_diagram(self, e_ksi: float, i_in4: float, n: int = 1001,
                           loads=None, xs=None):
        """``(stations, deflections)`` — deflection in **inches**, negative =
        downward, for a prismatic section (``e_ksi`` in ksi, ``i_in4`` in in^4).

        The sagging-positive moment diagram (``n`` even samples, or ``xs``)
        is integrated twice as curvature ``M/EI``; the rigid-body line is then
        removed by a least-squares fit through the support stations, so every
        support sits at (numerically) zero deflection."""
        xs, _, m = self.diagrams(xs=xs, n=n, loads=loads)
        x_in = np.asarray(xs) * 12.0
        phi = np.asarray(m) * 12.0 / (e_ksi * i_in4)   # 1/in
        slope = _cumtrapz(phi, x_in)
        v = _cumtrapz(slope, x_in)
        s_in = np.asarray(self.supports) * 12.0
        a_mat = np.vstack([np.ones_like(s_in), s_in]).T
        coef, *_ = np.linalg.lstsq(a_mat, np.interp(s_in, x_in, v), rcond=None)
        return xs, v - (coef[0] + coef[1] * x_in)

    def moment_influence_line(self, x_section: float, *, n: int = 201
                              ) -> InfluenceLine:
        """Influence line for the bending moment at ``x_section``: a unit
        downward load walked across the beam.  Feed the result to
        ``InfluenceLine.hl93_effect`` for the HL-93 live-load envelope."""
        positions = list(np.linspace(self.supports[0], self.supports[-1], n))
        etas = [self.moment_at(x_section, [_Point(1.0, p)]) for p in positions]
        return influence_line_from_ordinates(
            positions, etas, length=self.length,
            label=f"M @ {x_section:.1f}")

    def _span_positions(self, per_span: int) -> np.ndarray:
        """Unit-load positions with every support on the grid."""
        pts = [np.linspace(a, b, per_span + 1)[:-1]
               for a, b in zip(self.supports[:-1], self.supports[1:])]
        return np.append(np.concatenate(pts), self.supports[-1])

    def _influence(self, effect, label: str, per_span: int, at=None) -> InfluenceLine:
        pos = self._span_positions(per_span)
        if at is not None:            # either side of a section: shear jumps there
            eps = 1e-6 * self.length
            pos = np.unique(np.clip(np.append(pos, [at - eps, at + eps]),
                                    self.supports[0], self.supports[-1]))
        il = influence_line_from_ordinates(
            pos - self.supports[0], [effect([_Point(1.0, p)]) for p in pos],
            length=self.length, label=label)
        il.supports = [s - self.supports[0] for s in self.supports]
        return il

    def shear_influence_line(self, x_section: float, *, side: str = "left",
                             per_span: int = 400) -> InfluenceLine:
        """Influence line for the shear at ``x_section``: the left-limit
        (``side="left"``) or the right-limit shear, so a section at a support
        gives the shear in the span on either side of it."""
        dx = 1e-7 * self.length
        x = x_section if side == "left" else x_section + dx
        return self._influence(lambda ld: self.shear_at(x, ld),
                               f"V @ {x_section:.1f} ({side})", per_span, at=x_section)

    def reaction_influence_line(self, support: int, *, per_span: int = 400
                                ) -> InfluenceLine:
        """Influence line for the reaction (up +) at support index ``support``."""
        return self._influence(lambda ld: self.reactions(ld)[support],
                               f"R{support}", per_span)

    def continuous_moment_influence_line(self, x_section: float, *,
                                         per_span: int = 400) -> InfluenceLine:
        """:meth:`moment_influence_line` on the support-aligned grid, carrying
        the span boundaries (``il.supports``) that
        :meth:`InfluenceLine.hs20_44_effect` needs for the second
        concentrated load of a negative-moment lane loading."""
        return self._influence(lambda ld: self.moment_at(x_section, ld),
                               f"M @ {x_section:.1f}", per_span)


@dataclass
class EnvelopeExtreme:
    """One extreme of a moving-load envelope: its value and station (ft)."""

    value: float
    station: float


@dataclass
class MovingLoadEnvelope:
    """Per-station extreme shear and moment from stepping an axle train
    (plus any pattern-placed lane load) across a :class:`ContinuousBeam`.

    Arrays share :attr:`stations`; conventions follow the beam (sagging
    moment positive, left-limit shear).  These are 1D line-girder demands —
    distribution factors and impact are the caller's business.
    """

    stations: np.ndarray
    moment_max: np.ndarray
    moment_min: np.ndarray
    shear_max: np.ndarray
    shear_min: np.ndarray

    def max_positive_moment(self) -> EnvelopeExtreme:
        i = int(np.argmax(self.moment_max))
        return EnvelopeExtreme(float(self.moment_max[i]),
                               float(self.stations[i]))

    def max_negative_moment(self) -> EnvelopeExtreme:
        """Most negative moment (hogging; 0 at midspan stations is normal)."""
        i = int(np.argmin(self.moment_min))
        return EnvelopeExtreme(float(self.moment_min[i]),
                               float(self.stations[i]))

    def max_shear(self) -> EnvelopeExtreme:
        """Largest absolute shear (signed value returned)."""
        hi, lo = np.max(self.shear_max), np.min(self.shear_min)
        if hi >= -lo:
            i = int(np.argmax(self.shear_max))
            return EnvelopeExtreme(float(self.shear_max[i]),
                                   float(self.stations[i]))
        i = int(np.argmin(self.shear_min))
        return EnvelopeExtreme(float(self.shear_min[i]),
                               float(self.stations[i]))

    def plot(self, ax=None):
        """Stacked shear/moment envelope plot; returns the figure."""
        import matplotlib.pyplot as plt

        if ax is None:
            fig, axes = plt.subplots(2, 1, figsize=(9, 5.5), sharex=True)
        else:
            fig, axes = ax.get_figure(), [ax]
        pairs = [(self.shear_max, self.shear_min, "Shear (kip)"),
                 (self.moment_max, self.moment_min, "Moment (kip·ft)")]
        for a, (hi, lo, label) in zip(axes, pairs):
            a.plot(self.stations, hi, "b", lw=1.4)
            a.plot(self.stations, lo, "r", lw=1.4)
            a.fill_between(self.stations, lo, hi, color="b", alpha=0.10)
            a.axhline(0.0, color="k", lw=0.8)
            a.set_ylabel(label)
            a.grid(True, alpha=0.3)
        axes[-1].set_xlabel("Station (ft)")
        return fig


def unit_response_matrices(beam: ContinuousBeam, xs):
    """Shear and moment at every station of ``xs`` for a unit (1 kip) load
    at every position of ``xs``: two ``(len(xs), len(xs))`` arrays whose
    row ``i`` is the beam's response to the unit load at ``xs[i]``.

    Column ``k`` read down the rows is therefore the influence line of the
    effect at station ``xs[k]`` — one stiffness solve per row buys every
    truck, direction, and placement afterwards as a cheap gather-and-sum.
    """
    x = np.asarray(xs, dtype=float)
    v = np.empty((x.size, x.size))
    m = np.empty((x.size, x.size))
    for i, p in enumerate(x):
        _, v[i], m[i] = beam.diagrams(xs=x, loads=[_Point(1.0, p)])
    return v, m


@dataclass
class UnitResponses:
    """The unit-load response matrices of one beam configuration on one
    grid, reusable across every vehicle: build once with
    :meth:`from_beam`, then :meth:`envelope` each truck against it (the
    per-configuration solve dominates; each envelope afterwards is a
    cheap gather-and-sum)."""

    xs: np.ndarray
    shear: np.ndarray    # (n_positions, n_stations)
    moment: np.ndarray

    @classmethod
    def from_beam(cls, beam: ContinuousBeam, step: float = 0.5):
        """Solve the unit-load responses of ``beam`` on a grid of spacing
        ``step`` (ft, snapped so the supports land on grid points)."""
        length = beam.length
        x0 = beam.supports[0]
        n = max(2, int(round(length / step)))
        xs = np.linspace(x0, x0 + length, n + 1)
        return cls(xs, *unit_response_matrices(beam, xs))

    def envelope(self, loads, positions, *, both_directions: bool = True,
                 lane_klf: float = 0.0) -> MovingLoadEnvelope:
        """Envelope one axle train (see :func:`moving_load_envelope` for
        the parameter semantics; placements step at the grid spacing)."""
        xs = self.xs
        x0, x1 = float(xs[0]), float(xs[-1])
        h = float(xs[1] - xs[0])
        loads = np.asarray(loads, dtype=float)
        offsets = np.asarray(positions, dtype=float)
        trains = [(loads, offsets)]
        if both_directions and len(loads) > 1:
            trains.append((loads[::-1], offsets.max() - offsets[::-1]))

        v_max = np.zeros(xs.size)
        v_min = np.zeros(xs.size)
        m_max = np.zeros(xs.size)
        m_min = np.zeros(xs.size)
        starts = np.arange(x0 - offsets.max(), x1 + h / 2, h)
        for ld, offs in trains:
            # (n_starts, n_stations) response accumulated one axle at a
            # time: each axle's global positions pick (interpolated)
            # unit-load rows.
            v_eff = np.zeros((starts.size, xs.size))
            m_eff = np.zeros((starts.size, xs.size))
            for p_axle, off in zip(ld, offs):
                pos = starts + off
                inside = (pos >= x0) & (pos <= x1)
                if not inside.any():
                    continue
                f = (pos[inside] - x0) / h
                i0 = np.minimum(f.astype(int), xs.size - 2)
                w = (f - i0)[:, None]
                v_eff[inside] += p_axle * ((1.0 - w) * self.shear[i0]
                                           + w * self.shear[i0 + 1])
                m_eff[inside] += p_axle * ((1.0 - w) * self.moment[i0]
                                           + w * self.moment[i0 + 1])
            v_max = np.maximum(v_max, v_eff.max(axis=0))
            v_min = np.minimum(v_min, v_eff.min(axis=0))
            m_max = np.maximum(m_max, m_eff.max(axis=0))
            m_min = np.minimum(m_min, m_eff.min(axis=0))

        if lane_klf:
            # Pattern placement per station: integrate the favorable-sign
            # part of that station's influence line (a column of the unit
            # matrices).
            v_max += lane_klf * np.trapezoid(np.clip(self.shear, 0.0, None),
                                             xs, axis=0)
            v_min += lane_klf * np.trapezoid(np.clip(self.shear, None, 0.0),
                                             xs, axis=0)
            m_max += lane_klf * np.trapezoid(np.clip(self.moment, 0.0, None),
                                             xs, axis=0)
            m_min += lane_klf * np.trapezoid(np.clip(self.moment, None, 0.0),
                                             xs, axis=0)

        return MovingLoadEnvelope(xs, m_max, m_min, v_max, v_min)


def moving_load_envelope(beam: ContinuousBeam, loads, positions, *,
                         step: float = 0.5, both_directions: bool = True,
                         lane_klf: float = 0.0) -> MovingLoadEnvelope:
    """Step an axle train across ``beam`` and envelope shear and moment at
    every station.

    ``loads`` (kip) sit at ``positions`` (ft from the first axle) — pass a
    catalog truck as ``*vehicle.train()`` from
    :mod:`civilpy.structural.aashto.vehicles`.  Axles off the beam
    contribute nothing (trains enter and leave the span).  ``step`` sets
    both the station grid and the train-placement increment; axle
    placements between grid points interpolate linearly between unit-load
    rows, so keep ``step`` a divisor of the axle spacings where exactness
    at the peaks matters (the catalog trucks are all on 0.5-ft multiples).

    ``lane_klf`` adds a uniform lane load placed **patterned** per station:
    positive influence regions only for the maxima, negative only for the
    minima — the adverse-placement rule, computed from the same unit-load
    responses.  Impact and distribution factors are deliberately not
    applied here.

    Enveloping several vehicles on the same beam?  Build a
    :class:`UnitResponses` once and call its :meth:`~UnitResponses.envelope`
    per truck — this function rebuilds the unit-load matrices every call.

    >>> b = ContinuousBeam([0.0, 100.0])
    >>> env = moving_load_envelope(b, [8.0, 32.0, 32.0], [0.0, 14.0, 28.0])
    >>> round(env.max_positive_moment().value, 1)   # HS20, 100-ft span
    1523.9
    """
    return UnitResponses.from_beam(beam, step=step).envelope(
        loads, positions, both_directions=both_directions, lane_klf=lane_klf)


def _cumtrapz(y, x):
    """Cumulative trapezoidal integral of ``y`` over ``x``, starting at 0."""
    out = np.zeros_like(y)
    out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))
    return out


def m_about_a_to_shear(w_tot, m_about_a, span):
    """Simple-span left reaction share: ``V_a = w_tot - m_about_a/span`` (the
    part of the load carried by the left end before the end-moment couple)."""
    if span == 0:
        return 0.0
    return w_tot - m_about_a / span
