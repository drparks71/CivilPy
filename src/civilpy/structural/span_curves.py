"""Preliminary-design span curves: structural steel weight per square foot of
deck and girder / superstructure depth against span length, by number of
spans and girder spacing -- the lookup behind a structure type study or a
conceptual cost estimate.

The curves themselves are data the caller supplies (digitized design aids
such as the NSBA *Steel Span Weight Curves* and *Steel Plate Girder
Span-to-Depth Ratios*), in a neutral schema:

* weight: ``{curve name: {"span_ft": [...], "psf": [...]}}`` with names
  ``"<span class> — <spacing class>"``, span class one of ``Single Span``,
  ``Two Span``, ``Three or More Spans`` and spacing class ``All Girder
  Spacing``, ``7 ft to 9 ft Girder Spacing``, ``9 ft to 11 ft Girder
  Spacing``, ``11 ft and Greater Girder Spacing``;
* depth: ``{curve name: {"span_ft": [...], "girder_in": [...],
  "total_in": [...]}}`` keyed by the number of spans in the name
  (``Single-span``, ``Two-span``, ``Three-span``, ``Four-span``).

Lookups interpolate linearly along the curve, use the maximum span of a
continuous unit (as both aids direct) and report whether the span is
inside the plotted range; outside it they return ``None`` unless
``extrapolate=True`` (end slope).
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SPAN_CLASSES = {1: "Single Span", 2: "Two Span", 3: "Three or More Spans"}
DEPTH_CLASSES = {1: "Single-span", 2: "Two-span", 3: "Three-span", 4: "Four-span"}


def spacing_class(spacing_ft: float | None) -> str:
    """The girder-spacing band of the weight curves (``All`` when unknown
    or below 7 ft)."""
    if spacing_ft is None or spacing_ft < 7.0:
        return "All Girder Spacing"
    if spacing_ft < 9.0:
        return "7 ft to 9 ft Girder Spacing"
    if spacing_ft < 11.0:
        return "9 ft to 11 ft Girder Spacing"
    return "11 ft and Greater Girder Spacing"


def _interp(xs, ys, x, extrapolate):
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if xs[0] <= x <= xs[-1]:
        return float(np.interp(x, xs, ys)), True
    if not extrapolate:
        return None, False
    i = (0, 1) if x < xs[0] else (-2, -1)
    slope = (ys[i[1]] - ys[i[0]]) / (xs[i[1]] - xs[i[0]])
    x0, y0 = (xs[0], ys[0]) if x < xs[0] else (xs[-1], ys[-1])
    return float(y0 + slope * (x - x0)), False


def _load(curves):
    if isinstance(curves, (str, Path)):
        return json.loads(Path(curves).read_text(encoding="utf-8"))
    return dict(curves)


@dataclass
class SpanWeightCurves:
    """Steel weight (psf of deck) by span class and girder spacing."""

    curves: dict

    @classmethod
    def load(cls, curves) -> "SpanWeightCurves":
        return cls(_load(curves))

    def curve_name(self, n_spans: int, spacing_ft: float | None = None) -> str:
        span = SPAN_CLASSES[min(max(int(n_spans), 1), 3)]
        name = f"{span} — {spacing_class(spacing_ft)}"
        return name if name in self.curves else f"{span} — All Girder Spacing"

    def psf(self, spans_ft, spacing_ft: float | None = None, *,
            extrapolate: bool = False) -> dict:
        """Steel weight for a unit of ``spans_ft`` (one value or the span
        list; the maximum span governs): ``{"psf", "curve", "in_range"}``.
        A spacing band whose curve does not reach the span falls back to the
        all-spacing curve."""
        spans = [spans_ft] if np.ndim(spans_ft) == 0 else list(spans_ft)
        l_max = max(spans)
        name = self.curve_name(len(spans), spacing_ft)
        c = self.curves[name]
        value, ok = _interp(c["span_ft"], c["psf"], l_max, False)
        if value is None and "All Girder Spacing" not in name:
            name = self.curve_name(len(spans), None)
            c = self.curves[name]
            value, ok = _interp(c["span_ft"], c["psf"], l_max, False)
        if value is None:
            value, ok = _interp(c["span_ft"], c["psf"], l_max, extrapolate)
        return {"psf": value, "curve": name, "in_range": ok, "span_ft": l_max}


@dataclass
class SpanDepthCurves:
    """Girder and total superstructure depth (in.) by number of spans."""

    curves: dict

    @classmethod
    def load(cls, curves) -> "SpanDepthCurves":
        return cls(_load(curves))

    def curve_name(self, n_spans: int) -> str:
        key = DEPTH_CLASSES[min(max(int(n_spans), 1), 4)]
        return next(n for n in self.curves if n.startswith(key))

    def depth(self, spans_ft, *, extrapolate: bool = False) -> dict:
        """Depths for a unit of ``spans_ft`` (the maximum span governs):
        ``{"girder_in", "total_in", "curve", "in_range"}``."""
        spans = [spans_ft] if np.ndim(spans_ft) == 0 else list(spans_ft)
        l_max = max(spans)
        name = self.curve_name(len(spans))
        c = self.curves[name]
        girder, ok = _interp(c["span_ft"], c["girder_in"], l_max, extrapolate)
        total, _ = _interp(c["span_ft"], c["total_in"], l_max, extrapolate)
        return {"girder_in": girder, "total_in": total, "curve": name, "in_range": ok,
                "span_ft": l_max}
