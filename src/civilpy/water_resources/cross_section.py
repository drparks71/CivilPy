#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Uniform flow in an irregular (surveyed / LiDAR) cross section.

:class:`IrregularSection` takes station-elevation pairs across the valley and
solves Manning's equation for the water surface that carries a discharge on a
given energy slope (normal depth).  The section is split at the bank
stations into left overbank, main channel and right overbank - the HEC-RAS
default subdivision - and conveyance is computed per subarea from its summed
area and wetted perimeter (channel n inside the banks, overbank n outside).  A water surface above either end of the section is carried
on vertical walls there and flagged (``spills``).

US customary units: feet, ft^2, cfs, ft/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

K_MANNING_US = 1.486


@dataclass
class FlowState:
    wse_ft: float
    depth_ft: float          # above the thalweg
    area_ft2: float
    top_width_ft: float
    velocity_fps: float      # Q / A
    channel_velocity_fps: float   # main-channel slice velocity (Q split by conveyance)
    spills: bool             # water surface above an end of the section


class IrregularSection:
    def __init__(self, stations_ft, elevations_ft, *, n_channel: float = 0.035,
                 n_overbank: float | None = None, bank_stations_ft: tuple | None = None):
        pts = sorted(zip(map(float, stations_ft), map(float, elevations_ft)))
        if len(pts) < 3:
            raise ValueError("a cross section needs at least 3 points")
        self.sta = [p[0] for p in pts]
        self.elev = [p[1] for p in pts]
        self.n_channel = n_channel
        self.n_overbank = n_overbank if n_overbank is not None else n_channel
        self.banks = bank_stations_ft or (self.sta[0], self.sta[-1])
        self.thalweg_ft = min(self.elev)
        self.top_ft = min(self.elev[0], self.elev[-1])

    def _zone(self, x):
        return "L" if x < self.banks[0] else "R" if x > self.banks[1] else "C"

    def _slices(self, wse):
        """(area, wetted perimeter, top width, zone L/C/R) per wetted segment."""
        out = []
        for (x0, z0), (x1, z1) in zip(zip(self.sta, self.elev), zip(self.sta[1:], self.elev[1:])):
            d0, d1 = wse - z0, wse - z1
            if d0 <= 0 and d1 <= 0:
                continue
            if d0 < 0 or d1 < 0:                       # partly wet: cut at the waterline
                t = d0 / (d0 - d1)
                xw = x0 + t * (x1 - x0)
                if d0 < 0:
                    x0, z0, d0 = xw, wse, 0.0
                else:
                    x1, z1, d1 = xw, wse, 0.0
            w = x1 - x0
            out.append((0.5 * (d0 + d1) * w, math.hypot(w, z1 - z0), w, self._zone(0.5 * (x0 + x1))))
        # vertical walls when the water rises above an end point
        for x, z in ((self.sta[0], self.elev[0]), (self.sta[-1], self.elev[-1])):
            if wse > z:
                out.append((0.0, wse - z, 0.0, self._zone(x)))
        return out

    def _subareas(self, wse):
        """{zone: (area, perimeter)} summed over the slices."""
        acc = {}
        for area, perim, _, zone in self._slices(wse):
            a, p = acc.get(zone, (0.0, 0.0))
            acc[zone] = (a + area, p + perim)
        return acc

    def _k(self, zone, area, perim):
        if area <= 0 or perim <= 0:
            return 0.0
        n = self.n_channel if zone == "C" else self.n_overbank
        return K_MANNING_US / n * area * (area / perim) ** (2.0 / 3.0)

    def conveyance(self, wse: float) -> float:
        return sum(self._k(z, a, p) for z, (a, p) in self._subareas(wse).items())

    def discharge(self, wse: float, slope: float) -> float:
        return self.conveyance(wse) * math.sqrt(slope)

    def normal_flow(self, q_cfs: float, slope: float, *, tol_ft: float = 0.001) -> FlowState:
        """Water surface carrying ``q_cfs`` at energy slope ``slope`` (ft/ft)."""
        if q_cfs <= 0 or slope <= 0:
            raise ValueError("discharge and slope must be positive")
        lo, hi = self.thalweg_ft, self.thalweg_ft + 1.0
        while self.discharge(hi, slope) < q_cfs:
            hi = lo + 2.0 * (hi - lo)
            if hi - lo > 1000:
                raise ValueError("no water surface within 1000 ft carries the discharge")
        while hi - lo > tol_ft:
            mid = 0.5 * (lo + hi)
            if self.discharge(mid, slope) < q_cfs:
                lo = mid
            else:
                hi = mid
        wse = hi
        sub = self._subareas(wse)
        area = sum(a for a, _ in sub.values())
        top = sum(s[2] for s in self._slices(wse))
        k_tot = self.conveyance(wse)
        a_ch, p_ch = sub.get("C", (0.0, 0.0))
        k_ch = self._k("C", a_ch, p_ch)
        v_ch = (q_cfs * k_ch / k_tot) / a_ch if a_ch > 0 and k_tot > 0 else q_cfs / area
        return FlowState(wse, wse - self.thalweg_ft, area, top, q_cfs / area, v_ch, wse > self.top_ft)
