#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT culvert sizing, L&D Vol 2 1105 / 1006 (July 2026): the smallest
standard conduit, in the manual's order of shapes, whose headwater meets the
1006.2 controls - what the CDSS culvert module searches for.

1105.1: check a single round pipe first; where cover or discharge rules it
out, single-cell elliptical concrete, then metal pipe-arch, then a precast
box (three-sided structures are site-specific and left to the designer); a
single cell is preferred, two at most (1105.6.2).  1006.2.1: the design-storm
headwater stays below the lowest of (A) 1 or 2 ft under the near low
pavement edge and (B) 2 ft above the inlet crown (4 ft in a deep ravine, C);
1006.2.2: the 1 % headwater depth is at most twice the rise.  Hydraulics by
FHWA HDS-5 (:mod:`civilpy.water_resources.culvert`), n of 1105.5.5 (smooth
pipe 0.012, CMP by Figure 1105-2), ke of Table 1105-2, tailwater as 1105.6.1
(given, or the ``(dc + D) / 2`` rule when a high tailwater would otherwise
drive the size).

The catalog carries round concrete to 120 in, ASTM C507 horizontal ellipses,
the corrugated steel pipe-arches of the OHE Durability Design spreadsheet's
pipe charts, and precast boxes 3-14 ft spans x 2-12 ft rises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from civilpy.water_resources import culvert as cv

from . import drainage as ld2

SMOOTH_N = 0.012                     # 1105.5.5 smooth flow pipe
CMP_1IN_PAVED_N = 0.020              # 1105.5.5 field-paved 1 in corrugations
STRUCTURAL_PLATE_N = 0.026           # 1105.5.5 field-paved structural plate
KE = {"concrete": 0.2, "cmp_full_headwall_beveled": 0.25, "cmp": 0.9}   # Table 1105-2
MAX_CELLS = 2                        # 1105.6.2

#: Figure 1105-2 Manning's n for CMP by diameter (in): 2-2/3 x 1/2 in corrugations (15-72 in) and the two
#: larger-corrugation columns (60-120 in); interpolated by equivalent diameter.
CMP_N_SMALL = {15: 0.0250, 18: 0.0249, 21: 0.0248, 24: 0.0247, 30: 0.0244, 36: 0.0241, 42: 0.0237, 48: 0.0235, 54: 0.0233,
               60: 0.0232, 66: 0.0231, 72: 0.0229}
CMP_N_LARGE = {60: 0.0332, 66: 0.0330, 72: 0.0327, 78: 0.0325, 84: 0.0323, 90: 0.0321, 96: 0.0320, 102: 0.0318, 108: 0.0317,
               114: 0.0315, 120: 0.0314}


def cmp_n(equivalent_diameter_in: float, *, corrugation: str = "2-2/3x1/2") -> float:
    tab = CMP_N_SMALL if corrugation == "2-2/3x1/2" else CMP_N_LARGE
    keys = sorted(tab)
    d = float(equivalent_diameter_in)
    if d <= keys[0]:
        return tab[keys[0]]
    if d >= keys[-1]:
        return tab[keys[-1]]
    for a, b in zip(keys, keys[1:]):
        if a <= d <= b:
            return tab[a] + (tab[b] - tab[a]) * (d - a) / (b - a)
    return tab[keys[-1]]


@dataclass(frozen=True)
class Conduit:
    family: str          # round | ellipse | pipe_arch | box
    label: str
    span_ft: float
    rise_ft: float
    n: float
    inlet: str           # civilpy.water_resources.culvert.INLETS key
    ke: float

    @property
    def area_sqft(self) -> float:
        if self.family == "round":
            return math.pi * self.span_ft ** 2 / 4.0
        if self.family in ("ellipse", "pipe_arch"):
            return math.pi * self.span_ft * self.rise_ft / 4.0
        return self.span_ft * self.rise_ft

    def shape(self) -> cv.BarrelShape:
        if self.family == "round":
            return cv.BarrelShape.circular(self.span_ft)
        if self.family in ("ellipse", "pipe_arch"):
            return cv.BarrelShape.ellipse(self.span_ft, self.rise_ft)
        return cv.BarrelShape.box(self.span_ft, self.rise_ft)


ROUND_IN = (12, 15, 18, 21, 24, 27, 30, 33, 36, 42, 48, 54, 60, 66, 72, 78, 84, 90, 96, 102, 108, 114, 120)
#: ASTM C507 horizontal elliptical concrete pipe (rise x span, in).
ELLIPSE_IN = ((14, 23), (19, 30), (22, 34), (24, 38), (27, 42), (29, 45), (32, 49), (34, 53), (38, 60), (43, 68), (48, 76),
              (53, 83), (58, 91), (63, 98), (68, 106), (72, 113), (77, 121), (82, 128), (87, 136), (92, 143), (97, 151),
              (106, 166), (116, 180))
#: Corrugated steel pipe-arch (span x rise, in) - OHE Durability Design "Steel Pipe Charts": 2-2/3 x 1/2 in, then 3 x 1 / 5 x 1 in.
PIPE_ARCH_SMALL_IN = ((17, 13), (21, 15), (24, 18), (28, 20), (35, 24), (42, 29), (49, 33), (57, 38), (64, 43), (71, 47), (77, 52), (83, 57))
PIPE_ARCH_LARGE_IN = ((40, 31), (46, 36), (53, 41), (60, 46), (66, 51), (73, 55), (81, 59), (87, 63), (95, 67), (103, 71), (112, 75),
                      (117, 79), (128, 83), (137, 87), (142, 91))
BOX_SPANS_FT = tuple(range(3, 15))
BOX_RISES_FT = tuple(range(2, 13))


def catalog(families=("round", "ellipse", "pipe_arch", "box")) -> list:
    """Conduits in the 1105.1 order, each family by rising area."""
    out = []
    if "round" in families:
        out += [Conduit("round", f"{d} in RCP", d / 12.0, d / 12.0, SMOOTH_N, "concrete_pipe_groove_headwall", KE["concrete"]) for d in ROUND_IN]
    if "ellipse" in families:
        out += [Conduit("ellipse", f"{r} x {s} in HE RCP", s / 12.0, r / 12.0, SMOOTH_N, "ellipse_groove_headwall", KE["concrete"])
                for r, s in ELLIPSE_IN]
    if "pipe_arch" in families:
        for s, r in PIPE_ARCH_SMALL_IN:
            de = math.sqrt(4.0 * (math.pi * s * r / 4.0) / math.pi)
            out.append(Conduit("pipe_arch", f"{s} x {r} in CSP arch (2-2/3 x 1/2)", s / 12.0, r / 12.0, cmp_n(de), "pipe_arch_headwall", KE["cmp"]))
        for s, r in PIPE_ARCH_LARGE_IN:
            de = math.sqrt(s * r)
            out.append(Conduit("pipe_arch", f"{s} x {r} in CSP arch (3 x 1)", s / 12.0, r / 12.0, cmp_n(de, corrugation="3x1"),
                               "pipe_arch_headwall", KE["cmp"]))
    if "box" in families:
        boxes = [Conduit("box", f"{s} x {r} ft box", float(s), float(r), SMOOTH_N, "box_wingwall_30_75", 0.4)
                 for s in BOX_SPANS_FT for r in BOX_RISES_FT if r <= s + 2]
        out += sorted(boxes, key=lambda c: (c.area_sqft, c.rise_ft))
    return out


def half_dc_d_tailwater(culvert: cv.Culvert, q_barrel: float) -> float:
    """1105.6.1: TW = (dc + D) / 2 above the outlet invert."""
    return culvert.outlet_invert + 0.5 * (culvert.critical_depth(q_barrel) + culvert.rise)


def size_culvert(*, q_design_cfs: float, q_check_1pct_cfs: float | None, inlet_invert_ft: float, outlet_invert_ft: float,
                 length_ft: float, pavement_low_edge_ft: float, drainage_area_acres: float, tailwater=None,
                 tailwater_1pct=None, max_rise_ft: float | None = None, deep_ravine: bool = False, bikeway: bool = False,
                 families=("round", "ellipse", "pipe_arch", "box"), max_cells: int = MAX_CELLS, method: str = "approximate",
                 min_cover_ft: float = 1.0, conduits=None) -> dict:
    """The first conduit (1105.1 order, one cell before two) whose design
    headwater meets 1006.2.1 and whose 1 % headwater depth is at most twice
    the rise (1006.2.2).  ``tailwater`` is an elevation, a rating
    ``q -> elevation``, ``None`` (free outfall) or ``"half_dc_d"`` (1105.6.1).
    ``max_rise_ft`` caps the rise (road over the culvert - inlet invert -
    cover).  Returns the selection, the first passing size per family (so
    the designer sees the shapes side by side) and the controls applied.
    ``conduits`` replaces the built-in :func:`catalog` with another list of
    :class:`Conduit` (an agency catalog), kept in its given order."""
    tried, per_family, selected = 0, {}, None
    cat = list(conduits) if conduits is not None else catalog(families)
    for cells in range(1, max_cells + 1):
        for c in cat:
            if c.family in per_family and cells == 1:
                continue
            if max_rise_ft is not None and c.rise_ft + min_cover_ft > max_rise_ft:
                continue
            tried += 1
            culvert = cv.Culvert(c.shape(), length_ft=length_ft, inlet_invert=inlet_invert_ft, outlet_invert=outlet_invert_ft,
                                 n=c.n, inlet=c.inlet, ke=c.ke, barrels=cells, name=c.label)
            tw = half_dc_d_tailwater(culvert, q_design_cfs / cells) if tailwater == "half_dc_d" else tailwater
            r = culvert.headwater(q_design_cfs, cv._tailwater(tw, q_design_cfs), method=method)
            controls = ld2.culvert_headwater_controls(pavement_low_edge_ft=pavement_low_edge_ft, inlet_crown_ft=inlet_invert_ft + c.rise_ft,
                                                      drainage_area_acres=drainage_area_acres, deep_ravine=deep_ravine, bikeway=bikeway,
                                                      rise_ft=c.rise_ft)
            ok_design = r.headwater_elev <= controls["design"]["allowable_ft"] + 1e-6
            row = {"conduit": c.label, "family": c.family, "cells": cells, "span_ft": c.span_ft, "rise_ft": c.rise_ft, "n": c.n, "ke": c.ke,
                   "inlet": culvert.inlet.label, "headwater_ft": round(r.headwater_elev, 2), "allowable_ft": controls["design"]["allowable_ft"],
                   "controls": controls["design"]["controls"], "control": r.control, "outlet_velocity_fps": round(r.outlet_velocity_fps, 2),
                   "design_ok": ok_design, "check_ok": None}
            if ok_design and q_check_1pct_cfs:
                tw1 = half_dc_d_tailwater(culvert, q_check_1pct_cfs / cells) if tailwater == "half_dc_d" else (tailwater_1pct or tailwater)
                r1 = culvert.headwater(q_check_1pct_cfs, cv._tailwater(tw1, q_check_1pct_cfs), method=method)
                depth = r1.headwater_elev - inlet_invert_ft
                row.update(headwater_1pct_ft=round(r1.headwater_elev, 2), depth_1pct_ft=round(depth, 2), max_1pct_depth_ft=round(2 * c.rise_ft, 2),
                           check_ok=depth <= 2 * c.rise_ft + 1e-6)
            passes = ok_design and row["check_ok"] is not False
            if passes and c.family not in per_family:
                per_family[c.family] = row
                if selected is None:
                    selected = row
        if selected is not None and cells == 1:
            break
    notes = ["shapes in the 1105.1 order: round, horizontal ellipse, pipe-arch, box; three-sided structures are not catalogued",
             "a single cell is preferred, two at most (1105.6.2); two cells are tried only when no single cell passes",
             "the 1 % Flood Hazard Evaluation (1005.2.1) and the bankfull / AOP checks of 1105.2 are separate",
             f"HDS-5 {method} outlet control; headwall inlets (Table 1105-2 ke)"]
    if tailwater == "half_dc_d":
        notes.append("tailwater (dc + D) / 2 (1105.6.1 high-tailwater rule)")
    return {"selected": selected, "per_family": per_family, "tried": tried, "basis": "1105.1 / 1006.2.1 / 1006.2.2",
            "edition": ld2.LD2_EDITION, "notes": notes}
