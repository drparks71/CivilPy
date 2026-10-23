"""Heat curving of horizontally curved I-girders -- the minimum radius of
AASHTO *LRFD Steel Bridge Fabrication Specification* (1st Ed.) Article
14.3.2.2, as the NSBA Heat Curve Evaluator (v2.01) and its flowcharts lay
it out.

For each prismatic section (top flange, web, bottom flange, each with its
yield strength) of a field section:

* **14.3.2.2.2 cross-section criteria** -- ``Psi = (b_nf t_nf + b t_f + D
  t_w) / (b_nf t_nf + b t_f)`` <= 2.0 (Eq. -1), ``Psi_f = b_nf t_nf / (b
  t_f)`` >= 0.20 (Eq. -2), the narrower flange no thicker than the wider
  one; the radius may not be less than 150 ft, or 1,000 ft with a flange
  thicker than 3 in. or wider than 30 in.
* **14.3.2.2.3** (doubly symmetric): ``R = 0.0365 b (D/t_w)^2 / Psi`` (in.)
  when ``D/t_w > 592 / sqrt(F_yw)`` (Eq. -1), else ``R = 12,800 b / (F_y
  Psi)`` (Eq. -2).
* **14.3.2.2.4** (singly symmetric, ``Psi >= 1.46`` and ``Psi_f <
  Psi_fo``, ``Psi_fo = 0.68 Psi - 0.79``): ``R = [1.43 Psi (1 - Psi_f /
  Psi_fo)^2 + 1] 12,800 b / (F_y Psi)``; the 14.3.2.2.3 radii also apply.
* **14.3.2.2.5** (hybrid, ``eta_f = F_yfw / F_yf``, ``eta_w = F_yw /
  F_yf``): with ``eta_f < 1`` the web must match the weaker flange
  (``eta_w = eta_f``) and the stronger flange be the wider; then
  ``R = [1.43 (1 - Psi_f sqrt(eta_f) / Psi_fo)^2 Psi + 1] 12,800 b / (F_yf
  Psi)`` (Eq. -3) where ``Psi_fo >= 0.20 sqrt(eta_f)`` and ``Psi_f <
  Psi_fo / sqrt(eta_f)``, with the 14.3.2.2.3 radii.  With ``eta_f = 1``
  (flanges of one grade, a weaker web) the section goes to 14.3.2.2.3 or
  14.3.2.2.4 like a homogeneous one.

``workbook=True`` reproduces the v2.01 spreadsheet where it departs from
its own flowchart: its hybrid limit rows ("eta_w = eta_f and eta_f < 1",
"b_yf >= b_yfw and eta_f < 1") return NG whenever ``eta_f = 1``, so every
hybrid with equal flange grades comes out "cannot be heat curved", and it
also evaluates Eq. 14.3.2.2.5-3 for them; and with flanges of equal width
it takes both flange thicknesses from the top flange.

Units: inches, ksi; radii returned in feet.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plate:
    """A flange or web plate: width (web: depth) and thickness, in., and
    its yield strength, ksi."""

    width: float
    thickness: float
    fy: float

    @property
    def area(self) -> float:
        return self.width * self.thickness


@dataclass
class HeatCurveResult:
    """Minimum radius for heat curving (ft) or ``None`` when the section
    cannot be heat curved, with the governing article, the reasons and the
    intermediate values."""

    r_min: float | None
    radii: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    values: dict = field(default_factory=dict)

    @property
    def permitted(self) -> bool:
        return self.r_min is not None

    def allows(self, radius_ft: float) -> bool:
        """Heat curving permitted at the girder's centerline radius."""
        return self.permitted and radius_ft >= self.r_min


def psi(b_nf, t_nf, b, t_f, d, t_w) -> float:
    """Psi (Eq. 14.3.2.2.2-1): total area over flange area."""
    flanges = b_nf * t_nf + b * t_f
    return (flanges + d * t_w) / flanges


def psi_f(b_nf, t_nf, b, t_f) -> float:
    """Psi_f (Eq. 14.3.2.2.2-2): narrower over wider flange area, <= 1."""
    return min(b_nf * t_nf / (b * t_f), 1.0)


def psi_fo(psi_value: float) -> float:
    """Psi_fo = 0.68 Psi - 0.79 (Eq. 14.3.2.2.4-2)."""
    return 0.68 * psi_value - 0.79


def _radius_3(b, d, t_w, f_yw, psi_value) -> tuple[str, float]:
    """14.3.2.2.3: (equation, radius in ft)."""
    if d / t_w > 592.0 / math.sqrt(f_yw):
        return "14.3.2.2.3-1", 0.0365 * (b / psi_value) * (d / t_w) ** 2 / 12.0
    return "14.3.2.2.3-2", 12_800.0 * b / (f_yw * psi_value) / 12.0


def _radius_4(b, f_y, psi_value, psi_f_value, psi_fo_value) -> float:
    return ((1.43 * psi_value * (1.0 - psi_f_value / psi_fo_value) ** 2 + 1.0)
            * 12_800.0 / 12.0 * b / (f_y * psi_value))


def _radius_5(b, f_yf, psi_value, psi_f_value, psi_fo_value, eta_f) -> float:
    return ((1.43 * (1.0 - psi_f_value * math.sqrt(eta_f) / psi_fo_value) ** 2 * psi_value + 1.0)
            * 12_800.0 / 12.0 * b / (f_yf * psi_value))


def minimum_radius(top: Plate, web: Plate, bottom: Plate, *, workbook: bool = False
                   ) -> HeatCurveResult:
    """Minimum radius for heat curving one prismatic section (14.3.2.2)."""
    if top.width != bottom.width:
        wide, narrow = (top, bottom) if top.width > bottom.width else (bottom, top)
    else:                                  # equal widths: the larger area is "wider"
        wide, narrow = (top, bottom) if top.area >= bottom.area else (bottom, top)
    b, t_f, b_nf, t_nf = wide.width, wide.thickness, narrow.width, narrow.thickness
    if workbook and top.width == bottom.width:
        t_f = t_nf = top.thickness         # v2.01 reads both thicknesses off the top flange
    d, t_w, f_yw = web.width, web.thickness, web.fy
    p = psi(b_nf, t_nf, b, t_f, d, t_w)
    pf = psi_f(b_nf, t_nf, b, t_f)
    pfo = psi_fo(p)
    out = HeatCurveResult(None, values={"Psi": p, "Psi_f": pf, "Psi_fo": pfo, "b": b,
                                        "t_f": t_f, "b_nf": b_nf, "t_nf": t_nf})

    # 14.3.2.2.2
    if p > 2.0:
        out.reasons.append("Psi > 2.0 (14.3.2.2.2-1)")
    if pf < 0.20:
        out.reasons.append("Psi_f < 0.20 (14.3.2.2.2-2)")
    if t_nf > t_f:
        out.reasons.append("narrower flange thicker than the wider (14.3.2.2.2)")
    r_floor = 1000.0 if (t_f > 3.0 or b > 30.0) else 150.0
    out.radii["14.3.2.2.2"] = r_floor

    hybrid = max(top.fy, bottom.fy) > f_yw
    doubly = pf == 1.0
    eq3, r3 = _radius_3(b, d, t_w, f_yw, p)
    singly_4 = (not doubly) and p >= 1.46 and pf < pfo

    if not hybrid:
        out.radii[eq3] = r3
        if singly_4:
            out.radii["14.3.2.2.4-1"] = _radius_4(b, f_yw, p, pf, pfo)
    else:
        f_yf, f_yfw = max(top.fy, bottom.fy), min(top.fy, bottom.fy)
        b_yf = top.width if top.fy >= bottom.fy else bottom.width
        b_yfw = top.width if top.fy < bottom.fy else bottom.width
        if top.fy == bottom.fy:
            b_yf = b_yfw = top.width
        eta_f, eta_w = f_yfw / f_yf, f_yw / f_yf
        out.values.update({"eta_f": eta_f, "eta_w": eta_w})
        if eta_w > eta_f:
            out.reasons.append("eta_w > eta_f (14.3.2.2.5)")
        if eta_f < 1.0 or workbook:
            if not (eta_f < 1.0 and eta_w == eta_f):
                out.reasons.append("eta_w must equal eta_f < 1 (14.3.2.2.5)")
            if not (eta_f < 1.0 and b_yf >= b_yfw):
                out.reasons.append("the stronger flange must be the wider, eta_f < 1 (14.3.2.2.5)")
        if eta_f < 1.0 or (eta_f == 1.0 and eta_w < 1.0):
            out.radii[eq3] = r3
        if eta_f == 1.0 and eta_w < 1.0 and singly_4:
            out.radii["14.3.2.2.4-1"] = _radius_4(b, f_yw, p, pf, pfo)
        if (eta_f < 1.0 or workbook) and pfo >= 0.20 * math.sqrt(eta_f) \
                and pf < pfo / math.sqrt(eta_f):
            out.radii["14.3.2.2.5-3"] = _radius_5(b, f_yf, p, pf, pfo, eta_f)

    if out.reasons:
        return out
    out.r_min = max(out.radii.values())
    out.values["governing"] = max(out.radii, key=out.radii.get)
    return out


def field_section(sections, radius_ft: float, *, workbook: bool = False) -> dict:
    """Every prismatic section of a field section (``(top, web, bottom)``
    plate triples) against the girder centerline radius: heat curving is
    permitted only when every section can be heat curved at that radius."""
    results = [minimum_radius(*s, workbook=workbook) for s in sections]
    permitted = all(r.permitted for r in results) and \
        radius_ft >= max(r.r_min for r in results if r.permitted) if results else False
    return {"permitted": bool(permitted), "sections": results,
            "status": "CAN BE HEAT CURVED" if permitted else "CANNOT BE HEAT CURVED"}
