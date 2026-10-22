#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT rainfall intensity and the rational method, L&D Vol 2 section 1101
(July 2026; Figure 1101-2 dated July 2022).

The rational method's intensity MUST come from Figure 1101-2's curves
(1101.2.3): four intensity zones A-D across Ohio, each a set of
``i = a / (t + b)^c`` curves (in/hr, t in minutes) per AEP - the constants
printed on the figure's page 3 are :data:`IDF`.  ODOT built the zones from
NOAA Atlas 14 by contouring the 10 %-AEP 60-minute depth, so a site's zone
is taken from that depth (:func:`zone_from_depth`; the breaks are midway
between the zones' own 60-minute 10 % intensities).  Zone A is the lightest
rainfall (north-east / north-west), D the heaviest (south-west).

Time of concentration (1101.2.1): overland flow by the FAA equation
(:func:`overland_flow_minutes`, sheet flow no more than 300 ft) or the
Figure 1101-1 overland flow chart (:func:`overland_flow_chart_minutes`), shallow
concentrated flow at ``V = 3.3 k s^0.5`` (:data:`SHALLOW_K`, Table 1101-1),
then channel / pipe travel at the Manning velocity; a 15-minute minimum to
the first ditch catch basin and 10 minutes to the first pavement inlet
(1104.3.4, 1103.3).  Runoff coefficients: Table 1101-2 (:data:`RUNOFF_C`).

    i = intensity(25.0, 10.0, "B")          # 10 % AEP, 25 min, zone B -> 3.4 in/hr (the figure's example)
    q = rational_q(0.9, i, 2.5)             # cfs for 2.5 acres of pavement
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

#: Figure 1101-2 constants: zone -> AEP percent -> (a, b, c).
IDF = {
    "A": {50: (46.184, 9.000, 0.859), 20: (56.985, 10.250, 0.851), 10: (64.167, 11.000, 0.842),
          4: (66.528, 11.000, 0.811), 2: (65.702, 10.750, 0.782), 1: (64.489, 10.500, 0.754)},
    "B": {50: (47.987, 9.000, 0.859), 20: (60.684, 10.500, 0.858), 10: (73.126, 12.000, 0.863),
          4: (75.841, 12.000, 0.833), 2: (65.621, 10.000, 0.781), 1: (85.047, 13.250, 0.806)},
    "C": {50: (56.299, 10.000, 0.876), 20: (67.933, 11.000, 0.869), 10: (84.550, 13.000, 0.882),
          4: (95.736, 14.000, 0.871), 2: (96.783, 14.000, 0.850), 1: (80.436, 11.500, 0.794)},
    "D": {50: (57.448, 10.000, 0.876), 20: (67.933, 11.000, 0.869), 10: (79.192, 12.000, 0.864),
          4: (87.886, 12.750, 0.849), 2: (95.169, 13.500, 0.839), 1: (91.982, 13.000, 0.810)},
}
ZONES = ("A", "B", "C", "D")
AEPS = (50, 20, 10, 4, 2, 1)
MIN_DURATION_MIN = 5.0
MAX_DURATION_MIN = 180.0

#: Table 1101-1 intercept coefficients for shallow concentrated flow.
SHALLOW_K = {
    "forest with heavy ground litter": 0.076, "minimum tillage cultivation; woodland": 0.152,
    "short grass pasture": 0.213, "cultivated straight row": 0.274, "poor grass; untilled": 0.305,
    "grassed waterways": 0.457, "unpaved area; bare soil": 0.491, "paved area": 0.619,
}

#: Table 1101-2 runoff coefficients (a range where the manual gives one; the higher value for steeper slopes).
RUNOFF_C = {
    "pavement and paved shoulders": (0.9, 0.9), "berms and slopes 4:1 or flatter": (0.5, 0.5),
    "berms and slopes steeper than 4:1": (0.7, 0.7), "residential (single family)": (0.3, 0.5),
    "residential (multi-family)": (0.4, 0.7), "woods": (0.3, 0.3), "cultivated": (0.3, 0.6),
}

MIN_TC_DITCH_MIN = 15.0       # to the first ditch catch basin (1102.3.1, 1104.3.4)
MIN_TC_PAVEMENT_MIN = 10.0    # to the first pavement inlet (1103.3, 1104.3.4)


def _aep_key(aep_pct) -> int:
    key = int(round(float(aep_pct)))
    if key not in AEPS:
        raise ValueError(f"Figure 1101-2 has curves for AEP {AEPS} %, not {aep_pct}")
    return key


def intensity(duration_min: float, aep_pct: float, zone: str) -> float:
    """Rainfall intensity (in/hr) from the zone's IDF curve, Figure 1101-2.
    Durations are clamped to the figure's 5-180 minute range."""
    a, b, c = IDF[zone.strip().upper()][_aep_key(aep_pct)]
    t = min(max(float(duration_min), MIN_DURATION_MIN), MAX_DURATION_MIN)
    return a / (t + b) ** c


def depth_in(duration_min: float, aep_pct: float, zone: str) -> float:
    """Rainfall depth (in) over the duration, from the curve."""
    return intensity(duration_min, aep_pct, zone) * float(duration_min) / 60.0


def zone_depth_breaks() -> list:
    """The 10 %-AEP 60-minute depths that separate the zones: midway
    between neighbouring zones' own curves at that point."""
    d = [depth_in(60.0, 10, z) for z in ZONES]
    return [round((d[i] + d[i + 1]) / 2.0, 4) for i in range(len(ZONES) - 1)]


def zone_from_depth(depth_10pct_60min_in: float) -> str:
    """The intensity zone for a site from its NOAA Atlas 14 10 %-AEP (10-yr)
    60-minute depth - the statistic ODOT contoured to draw the zone map."""
    d = float(depth_10pct_60min_in)
    for z, brk in zip(ZONES, zone_depth_breaks()):
        if d < brk:
            return z
    return ZONES[-1]


def zone_from_atlas14(pf) -> str:
    """The zone from a civilpy ``PrecipFrequency`` table (its depth at the
    1-hour duration and the 10-year return period)."""
    return zone_from_depth(pf.depth(1.0, 10.0))


# ── time of concentration (1101.2.1) ──────────────────────────────────────

def overland_flow_minutes(runoff_c: float, length_ft: float, slope_pct: float) -> float:
    """FAA overland (sheet) flow time: t_o = 1.8 (1.1 - C) L^0.5 / S^(1/3),
    L in ft (no more than 300 ft of sheet flow), S in percent."""
    s = max(float(slope_pct), 0.1)
    return 1.8 * (1.1 - float(runoff_c)) * math.sqrt(float(length_ft)) / s ** (1.0 / 3.0)


def shallow_flow_velocity_fps(surface: str, slope_pct: float) -> float:
    """V = 3.3 k s^0.5 (HDS-2 2.6.2.2), k from Table 1101-1, s in percent."""
    return 3.3 * SHALLOW_K[surface] * math.sqrt(max(float(slope_pct), 0.0))


def travel_minutes(length_ft: float, velocity_fps: float) -> float:
    """t = L / (60 V) for shallow concentrated, channel or pipe flow."""
    return float(length_ft) / (60.0 * max(float(velocity_fps), 1e-6))


def time_of_concentration(*, overland_min: float = 0.0, shallow_min: float = 0.0, channel_min: float = 0.0,
                          first_inlet: str | None = None) -> float:
    """t_c = t_o + t_s + t_d, held to the minimum for the first ditch catch
    basin (15 min) or pavement inlet (10 min) when ``first_inlet`` is
    'ditch' or 'pavement'."""
    tc = float(overland_min) + float(shallow_min) + float(channel_min)
    floor = {"ditch": MIN_TC_DITCH_MIN, "pavement": MIN_TC_PAVEMENT_MIN}.get(first_inlet or "", 0.0)
    return max(tc, floor)


@dataclass(frozen=True)
class OverlandFlowChart:
    """An overland-flow nomograph of the Figure 1101-1 kind: log scales for
    the length of slope, the percent slope and the time, a runoff-coefficient
    scale, and a pivot line.  A straight line from L through C meets the
    pivot line; a line from that point through S meets the time scale.

    Heights are measured up the chart from the L = 10 ft tick, in any one
    unit.  ``pivot_ratio`` is (pivot line - L scale) / (C scale - L scale)
    and ``time_ratio`` is (time scale - pivot line) / (slope scale - pivot
    line), both measured across the chart."""

    length_per_decade: float
    c_heights: tuple                  # ((C, height), ...) ascending in C; linear between
    pivot_ratio: float
    slope_height_1pct: float
    slope_fall_per_decade: float      # the slope scale runs down as the slope grows
    time_ratio: float
    time_height_1min: float
    time_per_decade: float

    def c_height(self, runoff_c: float) -> float:
        pts = sorted(self.c_heights)
        c = float(runoff_c)
        if not pts[0][0] - 1e-9 <= c <= pts[-1][0] + 1e-9:
            raise ValueError(f"the chart's C scale runs {pts[0][0]} to {pts[-1][0]}, not {c}")
        for (c0, h0), (c1, h1) in zip(pts, pts[1:]):
            if c <= c1:
                return h0 + (h1 - h0) * (c - c0) / (c1 - c0)
        return pts[-1][1]

    def minutes(self, runoff_c: float, length_ft: float, slope_pct: float) -> float:
        a = self.length_per_decade * math.log10(float(length_ft) / 10.0)
        pivot = a + (self.c_height(runoff_c) - a) * self.pivot_ratio
        s = self.slope_height_1pct - self.slope_fall_per_decade * math.log10(float(slope_pct))
        e = pivot + (s - pivot) * self.time_ratio
        return 10.0 ** ((e - self.time_height_1min) / self.time_per_decade)


#: Figure 1101-1 (January 2023 drawing of the New Jersey Highway Authority 1957 nomograph), read off the
#: published figure: least-squares log fits of the labelled ticks of each scale and the labelled C ticks,
#: heights in inches as printed.  The redrawn scales are not exactly logarithmic, so a reading off the chart
#: by hand can differ from this by a few percent; the figure's own worked example (200 ft, C 0.50, about
#: 0.2 % slope, 20 minutes) gives 20.0 minutes.
FIGURE_1101_1 = OverlandFlowChart(
    length_per_decade=2.622,
    c_heights=((0.15, 2.244), (0.30, 2.625), (0.50, 3.006), (0.65, 3.423), (0.90, 4.360)),
    pivot_ratio=1.902,
    slope_height_1pct=2.603, slope_fall_per_decade=0.688,
    time_ratio=1.943,
    time_height_1min=-5.224, time_per_decade=6.709,
)


def overland_flow_chart_minutes(runoff_c: float, length_ft: float, slope_pct: float, *,
                                chart: OverlandFlowChart = FIGURE_1101_1) -> float:
    """Overland flow time (min) from the Figure 1101-1 overland flow chart
    (1101.2.1 allows it, a similar chart, or :func:`overland_flow_minutes`).
    ``slope_pct`` in percent; C on the chart's 0.15-0.90 scale.  Pass another
    ``chart`` for a similar nomograph with its own scale geometry."""
    if float(length_ft) <= 0 or float(slope_pct) <= 0:
        return 0.0
    return chart.minutes(runoff_c, length_ft, slope_pct)


def idf_curve(a: float, b: float, c: float) -> Callable[[float], float]:
    """``t -> a / (t + b)^c`` (in/hr, t in minutes) - the form of the
    Figure 1101-2 curves - for curves the figure does not carry (a local
    curve approved by OHE, 1101.2.3).  No duration clamp."""
    return lambda t: a / (float(t) + b) ** c


def intensity_function(zone: str, aep_pct: float) -> Callable[[float], float]:
    """``t -> intensity(t, aep_pct, zone)``: one Figure 1101-2 curve as a
    function of duration, the shape the drainage analyzers take."""
    IDF[zone.strip().upper()][_aep_key(aep_pct)]          # fail now on a bad zone / AEP
    return lambda t: intensity(t, aep_pct, zone)


def weighted_c(areas: list) -> float:
    """Area-weighted runoff coefficient from [(C, acres), ...] (HDS-2 5.3.2)."""
    tot = sum(a for _, a in areas)
    if tot <= 0:
        raise ValueError("no area")
    return sum(c * a for c, a in areas) / tot


def rational_q(runoff_c: float, intensity_in_hr: float, area_acres: float) -> float:
    """Q = C i A (cfs), for drainage areas up to 100 acres (1101.2.1)."""
    if float(area_acres) > 100.0:
        raise ValueError("the rational method is limited to 100 acres (LD2 1101.2.1); use StreamStats / USGS regression")
    return float(runoff_c) * float(intensity_in_hr) * float(area_acres)
