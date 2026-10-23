"""Influence lines for statically determinate beams (overhangs allowed),
with axle-train stepping for moving-load maxima — the classic line-girder
approach, so ordinates can be compared against any rating software.

Conventions follow :mod:`civilpy.structural.beam_bending`: kips/ft, plots
accept ``ax=None`` and return the figure.  Unit load is 1 kip downward;
sign conventions are the usual ones (positive reaction up, positive
moment sagging, shear by the left-segment rule).

Examples
--------
>>> il = InfluenceLine.moment(span=20, section=10)   # midspan moment
>>> round(il.eta(10), 4)                             # peak = L/4
5.0
>>> peak = il.maximize_axle_train([32, 32, 8], [0, 14, 28])
>>> round(peak.value, 1)                             # one axle fits the peak
160.0
>>> round(il.uniform_load_effect(0.64), 1)           # 0.64 klf lane load
32.0
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

from dataclasses import dataclass

import numpy as np


def influence_line_from_ordinates(positions, etas, length=None, label=""):
    """Build an :class:`InfluenceLine` from sampled ordinates.

    ``positions`` (ft, ascending) and ``etas`` are paired samples of an
    influence line obtained from *any* source — a MIDAS unit-load analysis, a
    finite-element model, or measured data — letting the full axle-train
    machinery (:meth:`InfluenceLine.maximize_axle_train`,
    :meth:`~InfluenceLine.hl93_effect`, :meth:`~InfluenceLine.uniform_load_effect`)
    run permit and rating trucks against a real structure rather than only the
    closed-form prismatic cases.

    The line is reconstructed by **linear interpolation** between samples
    (``numpy.interp``); load positions off the sampled range contribute zero.
    Accuracy is therefore limited by the sample spacing — and, because an
    influence line presumes **linear superposition**, by how linear the source
    structure is (see the walkthrough notes on nonlinear bridges).

    ``length`` defaults to the largest position.
    """
    pos = np.asarray(positions, dtype=float)
    eta = np.asarray(etas, dtype=float)
    if pos.ndim != 1 or pos.shape != eta.shape:
        raise ValueError("positions and etas must be 1-D arrays of equal length")
    if pos.size < 2:
        raise ValueError("need at least two samples to interpolate an influence line")
    order = np.argsort(pos)
    pos, eta = pos[order], eta[order]
    span = float(length) if length is not None else float(pos[-1])
    # Off-span positions contribute nothing (left/right fill values = 0.0).
    return InfluenceLine(lambda x: np.interp(x, pos, eta, left=0.0, right=0.0),
                         length=span, label=label, vectorized=True)


def influence_line_from_midas(midas, element, cases, *, component="Moment-y",
                              part="Part I", length=None, label="", unit=None):
    """Assemble an :class:`InfluenceLine` for one beam-element force effect from
    a set of **unit-load analysis cases** already solved in a MIDAS model.

    ``cases`` is an ordered iterable of ``(position_ft, load_case_name)`` pairs,
    one per unit-load (1 kip) position along the lane. This reads
    ``midas.beam_forces([element], …)`` once for all the cases, takes
    ``component`` (e.g. ``"Moment-y"`` / ``"Shear-z"``) at the given ``part``
    (``"Part I"`` or ``"Part J"``) of ``element`` under each case, and returns
    the interpolated influence line — ready for
    :meth:`InfluenceLine.maximize_axle_train` permit runs.

    This does **not** create or modify load cases; it reads the response of unit
    cases you (or a generator) set up, so it stays side-effect free and works
    against whatever load-application scheme the model uses. Reactions and
    displacements follow the same pattern via ``MidasCivil.result_table``.
    """
    from civilpy.structural.midas import parse_result_table

    cases = list(cases)
    names = [name for _, name in cases]
    rows = parse_result_table(midas.beam_forces([int(element)], names, unit=unit))

    # Index the response: load case name -> component value for our element/part.
    target = str(int(element))
    by_case = {}
    for r in rows:
        if str(r.get("Elem")).strip() != target:
            continue
        if part and str(r.get("Part", part)).strip() != part:
            continue
        try:
            by_case[str(r.get("Load")).strip()] = float(r.get(component))
        except (TypeError, ValueError):
            continue

    positions, etas = [], []
    for pos, name in cases:
        if name in by_case:
            positions.append(float(pos))
            etas.append(by_case[name])
    if len(positions) < 2:
        raise ValueError(
            f"resolved {len(positions)} ordinate(s) for element {element} "
            f"component {component!r} — check the case names, element id, and part")
    return influence_line_from_ordinates(
        positions, etas, length=length,
        label=label or f"elem {element} {component}")


@dataclass
class TrainResult:
    """Extreme effect of an axle train on an influence line."""

    value: float
    position: float  # location of the train's first axle (ft)
    reversed_train: bool


class InfluenceLine:
    """Influence line for one effect (reaction, shear, or moment at a
    section) on a beam with a pin at ``support_a`` and roller at
    ``support_b``; the beam runs from 0 to ``length`` (defaults to
    ``support_b``), so overhangs come from supports inside the ends."""

    def __init__(self, eta, length: float, label: str = "",
                 vectorized: bool = False):
        # ``vectorized``: ``eta`` already maps arrays to arrays (np.interp),
        # so skip the element-by-element np.vectorize wrapper
        self._eta = eta if vectorized else np.vectorize(eta, otypes=[float])
        self.length = float(length)
        self.label = label

    def eta(self, x):
        """Ordinate(s) at unit-load position(s) ``x``: a float for scalar
        input, an array for array input."""
        out = self._eta(x)
        return float(out) if np.ndim(x) == 0 else np.asarray(out, dtype=float)

    # ── Constructors for the classic effects ─────────────────────────────

    @classmethod
    def reaction(cls, span: float, support: str = "A",
                 support_a: float = 0.0, support_b: float | None = None,
                 length: float | None = None):
        """IL for a vertical reaction.  ``span`` is shorthand for supports
        at 0 and ``span``; or place them with ``support_a``/``support_b``."""
        a, b = support_a, span if support_b is None else support_b
        total = b if length is None else length

        def eta(x):
            r_a = (b - x) / (b - a)
            return r_a if support.upper() == "A" else 1.0 - r_a

        return cls(eta, total, f"Reaction {support.upper()}")

    @classmethod
    def shear(cls, span: float, section: float,
              support_a: float = 0.0, support_b: float | None = None,
              length: float | None = None):
        """IL for shear at ``section`` (left-segment sign convention)."""
        a, b = support_a, span if support_b is None else support_b
        total = b if length is None else length
        c = section

        def eta(x):
            r_a = (b - x) / (b - a)
            v = (r_a if a < c else 0.0) - (1.0 if x < c else 0.0)
            return v

        return cls(eta, total, f"Shear at x={section:g}")

    @classmethod
    def moment(cls, span: float, section: float,
               support_a: float = 0.0, support_b: float | None = None,
               length: float | None = None):
        """IL for bending moment at ``section``."""
        a, b = support_a, span if support_b is None else support_b
        total = b if length is None else length
        c = section

        def eta(x):
            r_a = (b - x) / (b - a)
            m = r_a * (c - a) - (c - x if x < c else 0.0)
            return m

        return cls(eta, total, f"Moment at x={section:g}")

    # ── Two-span continuous beams (Müller-Breslau) ───────────────────────

    @staticmethod
    def _two_span_redundant(spans):
        """Middle-reaction influence function for a prismatic two-span
        continuous beam by the force method (the exact Müller-Breslau
        shape: the deflected shape of the released simple beam scaled by
        the deflection at B).

        Releasing the middle support leaves a simple beam of length
        L1 + L2; eta_RB(u) = delta(B, u) / delta(B, B), with the
        simple-beam deflection formula (EI cancels).
        """
        l1, l2 = (float(s) for s in spans)
        total = l1 + l2

        def deflection_at(v, u):
            # simple beam 0..total, deflection at v due to unit load at u
            if v > u:
                v, u = total - v, total - u
            b = total - u
            return b * v * (total**2 - b**2 - v**2) / (6.0 * total)

        d_bb = deflection_at(l1, l1)

        def r_b(u):
            return deflection_at(l1, u) / d_bb

        return l1, l2, total, r_b

    @classmethod
    def two_span_reaction(cls, spans, support: str = "B"):
        """IL for a reaction of a two-span continuous beam with supports
        A-B-C and (possibly unequal) ``spans`` = (L1, L2).  The middle
        reaction's IL is the Müller-Breslau deflected shape of the
        beam with support B released."""
        l1, l2, total, r_b = cls._two_span_redundant(spans)

        def eta(u):
            if support.upper() == "B":
                return r_b(u)
            r_a = ((total - u) - r_b(u) * l2) / total
            if support.upper() == "A":
                return r_a
            return 1.0 - r_a - r_b(u)

        return cls(eta, total,
                   f"Reaction {support.upper()} (2-span {l1:g}+{l2:g})")

    @classmethod
    def two_span_shear(cls, spans, section: float):
        """IL for shear at ``section`` (ft from A) of a two-span
        continuous beam, left-segment sign convention."""
        l1, l2, total, r_b = cls._two_span_redundant(spans)
        c = float(section)

        def eta(u):
            r_a = ((total - u) - r_b(u) * l2) / total
            v = r_a
            if l1 < c:
                v += r_b(u)
            if u < c:
                v -= 1.0
            return v

        return cls(eta, total, f"Shear at x={section:g} (2-span)")

    @classmethod
    def two_span_moment(cls, spans, section: float):
        """IL for bending moment at ``section`` (ft from A) of a
        two-span continuous beam.  ``section = L1`` gives the classic
        negative-moment IL over the middle support."""
        l1, l2, total, r_b = cls._two_span_redundant(spans)
        c = float(section)

        def eta(u):
            r_a = ((total - u) - r_b(u) * l2) / total
            m = r_a * c
            if c > l1:
                m += r_b(u) * (c - l1)
            if u < c:
                m -= c - u
            return m

        return cls(eta, total, f"Moment at x={section:g} (2-span)")

    # ── Load effects ──────────────────────────────────────────────────────

    def ordinates(self, n: int = 1001):
        x = np.linspace(0.0, self.length, n)
        return x, self.eta(x)

    def uniform_load_effect(self, w: float, positive_only: bool = True,
                            n: int = 2001) -> float:
        """Effect of a uniform load ``w`` (klf): w times the influence-line
        area — positive regions only by default, the way lane load is
        placed to maximize."""
        x, y = self.ordinates(n)
        if positive_only:
            y = np.clip(y, 0.0, None)
        return w * float(np.trapezoid(y, x))

    def maximize_axle_train(self, loads, positions, step: float = 0.05,
                            both_directions: bool = True,
                            sign: float = 1.0) -> TrainResult:
        """Step an axle train across the beam and return the extreme
        effect.  ``loads`` (kips) sit at ``positions`` (ft, from the first
        axle); axles off the beam contribute nothing.  ``sign=-1`` finds
        the most negative effect instead."""
        loads = np.asarray(loads, dtype=float)
        offsets = np.asarray(positions, dtype=float)
        candidates = [(offsets, False)]
        if both_directions:
            candidates.append((offsets.max() - offsets[::-1], True))

        best = TrainResult(value=-np.inf, position=0.0, reversed_train=False)
        starts = np.arange(-offsets.max(), self.length + step, step)
        for offs, rev in candidates:
            ld = loads[::-1] if rev else loads
            xs = starts[:, None] + offs[None, :]
            mask = (xs >= 0.0) & (xs <= self.length)
            etas = np.where(mask, self.eta(np.clip(xs, 0.0, self.length)), 0.0)
            effect = sign * (etas * ld[None, :]).sum(axis=1)
            effect[~mask.any(axis=1)] = -np.inf
            k = int(np.argmax(effect))
            if effect[k] > best.value:
                best = TrainResult(float(effect[k]), float(starts[k]), rev)
        return TrainResult(sign * best.value, best.position,
                           best.reversed_train)

    def hl93_effect(self, im: float = 0.33, lane_klf: float = 0.64,
                    rear_spacings=(14.0, 30.0), sign: float = 1.0,
                    dual_truck: bool | str = False, dual_gap_step: float = 1.0,
                    dual_tandem: bool = True) -> dict:
        """Governing HL-93 effect on this line (3.6.1.3): design truck
        (rear-axle spacing swept) with dynamic load allowance, plus lane
        load on the positive regions.  Returns the pieces and the total.
        ``sign=-1`` gives the most negative effect instead (truck and
        tandem placed for the minimum, lane load on the negative
        regions) -- e.g. compression in a truss web member.

        ``dual_truck`` also tries the 3.6.1.3.1 loading for negative moment
        between points of contraflexure and for interior-pier reactions:
        90 % of two design trucks (14 ft rear axles) at least 50 ft apart,
        lead axle of one to rear axle of the other (the gap swept in
        ``dual_gap_step``), plus 90 % of the lane load; the larger governs
        (``details["dual_truck_governs"]``).  ``dual_truck="contraflexure"``
        applies it only where the article does, between the points of
        contraflexure under a uniform load on all spans: sections whose
        line integrates to a negative effect, for the negative extreme (pass
        ``True`` for an interior-pier reaction).  With it, ``dual_tandem``
        adds the C3.6.1.3.1 dual tandem: 100 % of two design tandems spaced
        26-40 ft centre to centre, with the dynamic load allowance, plus
        100 % of the lane load (as LRFD Simon does by default)."""
        sign = 1.0 if sign >= 0 else -1.0
        best_truck = max(
            (self.maximize_axle_train([8.0, 32.0, 32.0], [0.0, 14.0, 14.0 + s],
                                      sign=sign)
             for s in rear_spacings),
            key=lambda r: sign * r.value,
        )
        tandem = self.maximize_axle_train([25.0, 25.0], [0.0, 4.0], sign=sign)
        truck = max(best_truck, tandem, key=lambda r: sign * r.value)
        if sign > 0:
            lane = self.uniform_load_effect(lane_klf)
        else:
            x, y = self.ordinates(2001)
            lane = lane_klf * float(np.trapezoid(np.clip(y, None, 0.0), x))
        total = truck.value * (1.0 + im) + lane
        out = {
            "truck": truck.value,
            "tandem_governs": truck is tandem,
            "lane": lane,
            "total": total,
            "position": truck.position,
        }
        if dual_truck == "contraflexure":
            x, y = self.ordinates(2001)
            area = float(np.trapezoid(y, x))
            dual_truck = sign < 0 and area < 0.0
            out["in_negative_region"] = bool(area < 0.0)
        if dual_truck:
            pair = max((self.maximize_axle_train(
                [8.0, 32.0, 32.0, 8.0, 32.0, 32.0],
                [0.0, 14.0, 28.0, 28.0 + g, 42.0 + g, 56.0 + g], sign=sign)
                for g in np.arange(50.0, max(self.length, 50.0) + 1e-9, dual_gap_step)),
                key=lambda r: sign * r.value)
            dual = 0.9 * (pair.value * (1.0 + im) + lane)
            out["dual_truck"] = dual
            out["dual_truck_governs"] = sign * dual > sign * total
            if out["dual_truck_governs"]:
                out["total"] = dual
            if dual_tandem:
                tandems = max((self.maximize_axle_train(
                    [25.0, 25.0, 25.0, 25.0], [0.0, 4.0, g, g + 4.0], sign=sign)
                    for g in np.arange(26.0, 40.0 + 1e-9, 0.5)), key=lambda r: sign * r.value)
                dual_t = tandems.value * (1.0 + im) + lane
                out["dual_tandem"] = dual_t
                out["dual_tandem_governs"] = sign * dual_t > sign * out["total"]
                if out["dual_tandem_governs"]:
                    out["total"] = dual_t
                    out["dual_truck_governs"] = False
        return out

    def hs20_44_effect(self, sign: float = 1.0, concentrated: str = "moment",
                       second_concentrated: bool = False,
                       rear_spacings=np.arange(14.0, 30.01, 0.5),
                       lane_klf: float = 0.64, step: float = 0.05) -> dict:
        """Governing HS20-44 effect on this line, AASHTO Standard
        Specifications 3.7 / 3.11 (the AASHO HS20-44 loading of older
        designs): the HS20 truck (8-32-32 kip, rear axle spacing swept over
        14-30 ft) or the lane loading -- 0.64 klf on the regions of the
        wanted sign plus one concentrated load, 18 kip for moment or 26 kip
        for shear and reactions (``concentrated``), at the extreme ordinate.
        ``second_concentrated`` adds the second 18 kip load of 3.11.3 in one
        other span for negative moment in continuous spans (needs
        ``self.supports``, as the :class:`ContinuousBeam` influence lines
        carry).  No impact; one lane.  ``step`` is the truck stepping
        increment (ft); a shear line jumps at its section, so a fine step
        puts an axle on the jump.  Returns truck, lane and the governing
        value."""
        sign = 1.0 if sign >= 0 else -1.0
        truck = max((self.maximize_axle_train([8.0, 32.0, 32.0], [0.0, 14.0, 14.0 + s],
                                              step=step, sign=sign) for s in rear_spacings),
                    key=lambda r: sign * r.value)
        x, y = self.ordinates(4001)
        part = np.clip(sign * y, 0.0, None)
        p = 18.0 if concentrated == "moment" else 26.0
        lane = lane_klf * float(np.trapezoid(part, x)) + p * float(part.max())
        if second_concentrated:
            supports = getattr(self, "supports", None)
            if supports is None:
                raise ValueError("second_concentrated needs span boundaries (il.supports)")
            k = int(np.argmax(part))
            peaks = []
            for a, b in zip(supports[:-1], supports[1:]):
                inside = (x >= a) & (x <= b)
                if not (a <= x[k] <= b):
                    peaks.append(float(part[inside].max()))
            lane += p * max(peaks, default=0.0)
        lane *= sign
        governing = truck.value if sign * truck.value >= sign * lane else lane
        return {"truck": truck.value, "lane": lane, "total": governing,
                "lane_governs": governing == lane}

    # ── Visualization ─────────────────────────────────────────────────────

    def plot(self, ax=None, n: int = 1001, axle_train=None):
        """Plot the influence line (positive area shaded), optionally with
        an axle train drawn at its governing position."""
        if ax is None:
            import matplotlib.pyplot as plt  # only the plot path needs it — this module is
            # imported by server-side rating screens where pyplot must not load
            ax = plt.figure(figsize=(8, 3.2)).add_subplot(1, 1, 1)
        x, y = self.ordinates(n)
        ax.plot(x, y, "b", lw=1.6)
        ax.fill_between(x, y, 0.0, where=y > 0, color="b", alpha=0.15)
        ax.fill_between(x, y, 0.0, where=y < 0, color="r", alpha=0.15)
        ax.axhline(0.0, color="k", lw=0.8)
        peak_i = int(np.argmax(np.abs(y)))
        ax.annotate(f"{y[peak_i]:.4g}", (x[peak_i], y[peak_i]),
                    textcoords="offset points", xytext=(5, 5))
        if axle_train is not None:
            loads, positions = axle_train
            res = self.maximize_axle_train(loads, positions)
            offs = np.asarray(positions, dtype=float)
            if res.reversed_train:
                offs = offs.max() - offs[::-1]
                loads = list(loads)[::-1]
            top = max(y.max(), 0.0) * 1.35 + 1e-9
            for p, off in zip(loads, offs):
                xa = res.position + off
                if 0.0 <= xa <= self.length:
                    ax.annotate("", xy=(xa, 0.0), xytext=(xa, top),
                                arrowprops=dict(arrowstyle="-|>", color="g"))
                    ax.annotate(f"{p:g}", (xa, top),
                                textcoords="offset points", xytext=(2, 2),
                                color="g", fontsize=8)
        ax.set_xlabel("Unit load position (ft)")
        ax.set_ylabel(r"$\eta$")
        ax.set_title(f"Influence line — {self.label}")
        ax.grid(True, alpha=0.3)
        return ax.get_figure()
