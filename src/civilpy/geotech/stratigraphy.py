#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Correlate the strata of neighbouring borings into continuous layers and
build them as surfaces and closed solids.

The engineer's usual sketch between borings, done the same way every time:

1. **Columns** - each boring's logged layers (:class:`~civilpy.geotech.boring.Borehole`)
   merged into intervals of one material group (granular, silt, clay,
   organic, rock, topsoil, pavement); each interval keeps the detailed kinds
   logged in it (gravel / sand, shale / limestone, ...) by thickness.
2. **Correlation** (:func:`correlate`) - the columns are aligned into one
   stratigraphic sequence: an interval joins a unit of the same group in
   another boring when they sit in the same order and at similar
   elevations; a unit missing from a boring between two it does have is a
   pinch-out there (zero thickness); a unit below where a boring stopped is
   unknown there, not absent.  Order-preserving alignment (the edit-distance
   recursion) against a growing master sequence, cost = elevation
   difference of the matched mid-points, a fixed cost for a unit one boring
   has and another does not.
3. **Surfaces** (:func:`surfaces`) - each boundary's elevation interpolated
   over a grid (inverse distance, exact at the borings; a pinch-out is a
   boundary equal to the one above), kept in order, the deepest unit run
   down to the model base, and everything cut off by the ground on top (a
   supplied ground function, e.g. LiDAR, else the collars) - so a channel
   or a cut truncates the layers instead of dragging them down.
4. **Solids** (:func:`unit_solids`) - a closed triangle mesh per unit (top,
   bottom and sides of the grid), ready for a CAD model, where cutting a
   section shows each unit's fill.

:data:`KIND_STYLES` gives each detailed kind a colour and a fill pattern in
the spirit of boring-log graphic legends (circles for gravel, dots for sand,
dashes for silt, lines for clay, brick for limestone, ...); the pattern
names are generic, the CAD writer maps them to its own hatches.

Assumptions (state them on any drawing): layers are correlated by material
group only - two clays at similar elevations are taken as one layer; the
geometry between borings is interpolated, not observed; nothing is
extrapolated beyond the model area.  Units in feet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from civilpy.geotech.boring import Borehole, Layer

#: detailed kind -> (RGB, pattern, name)
KIND_STYLES: dict[str, tuple[tuple[int, int, int], str, str]] = {
    "pavement": ((90, 90, 90), "solid", "pavement / base"),
    "topsoil": ((110, 80, 50), "grass", "topsoil"),
    "fill": ((170, 140, 110), "cross", "fill"),
    "gravel": ((214, 170, 60), "circles", "gravel"),
    "sand": ((236, 208, 120), "dots", "sand"),
    "silt": ((176, 196, 120), "dashes", "silt"),
    "clay": ((150, 120, 170), "lines", "clay"),
    "organic": ((70, 60, 45), "swamp", "organic / peat"),
    "shale": ((105, 120, 140), "laminated", "shale"),
    "claystone": ((120, 110, 140), "laminated", "claystone / mudstone"),
    "siltstone": ((130, 140, 125), "laminated_dots", "siltstone"),
    "sandstone": ((200, 170, 110), "dots_dense", "sandstone"),
    "limestone": ((170, 185, 200), "brick", "limestone"),
    "dolomite": ((175, 165, 195), "brick_diagonal", "dolomite"),
    "coal": ((30, 30, 30), "solid", "coal"),
    "rock": ((120, 135, 155), "brick", "rock"),
    "unknown": ((200, 200, 200), "none", "not classified"),
}

MATCH_SCALE_FT = 10.0      # elevation difference that costs as much as one gap
GAP_COST = 1.5             # a unit one boring has and the other does not


def layer_kind(layer: Layer) -> str:
    """Detailed kind for the fill: gravel / sand inside granular, the rock
    name inside rock, else the material group."""
    g = layer.group
    text = " ".join([layer.classification or "", layer.description or ""]
                    + [str(c) for c in layer.constituents]).upper()
    if g == "rock":
        for name, kind in (("COAL", "coal"), ("LIMESTONE", "limestone"), ("DOLOMITE", "dolomite"),
                           ("SANDSTONE", "sandstone"), ("SILTSTONE", "siltstone"), ("CLAYSTONE", "claystone"),
                           ("MUDSTONE", "claystone"), ("SHALE", "shale")):
            if name in text:
                return kind
        return "rock"
    if g == "granular":
        c = (layer.classification or "").upper().replace(" ", "")
        if c.startswith("A-1-A"):
            return "gravel"
        if c.startswith(("A-1-B", "A-3")):
            return "sand"
        words = text.replace(",", " ").split(" WITH ")[0].split()
        head = [w for w in words if w in ("GRAVEL", "SAND")]
        return "gravel" if head and head[-1] == "GRAVEL" else "sand"
    if "FILL" in text and g not in ("pavement", "topsoil"):
        return "fill" if g == "unknown" else g
    return g if g in KIND_STYLES else "unknown"


# ── columns ──────────────────────────────────────────────────────────────────

@dataclass
class Interval:
    group: str
    top_elev_ft: float
    bottom_elev_ft: float
    kinds: dict = field(default_factory=dict)      # kind -> logged thickness ft
    labels: list = field(default_factory=list)     # layer labels as logged

    @property
    def mid_ft(self) -> float:
        return 0.5 * (self.top_elev_ft + self.bottom_elev_ft)

    @property
    def thickness_ft(self) -> float:
        return self.top_elev_ft - self.bottom_elev_ft


@dataclass
class Column:
    """One boring placed in the model: ``x``, ``y`` in the model's plane."""
    id: str
    x: float
    y: float
    ground_elev_ft: float
    bottom_elev_ft: float                          # where the log stops
    intervals: list[Interval]


def column(hole: Borehole, x: float, y: float) -> Column | None:
    """A boring as merged intervals (None without a collar elevation or layers)."""
    if hole.ground_elevation_ft is None or not hole.layers:
        return None
    z0 = float(hole.ground_elevation_ft)
    out: list[Interval] = []
    for lay in sorted(hole.layers, key=lambda l: l.depth_top_ft):
        if lay.depth_bottom_ft <= lay.depth_top_ft:
            continue
        top, bot, g, kind = z0 - lay.depth_top_ft, z0 - lay.depth_bottom_ft, lay.group, layer_kind(lay)
        if out and out[-1].group == g and abs(out[-1].bottom_elev_ft - top) < 0.5:
            iv = out[-1]
            iv.bottom_elev_ft = bot
        else:
            iv = Interval(g, top, bot)
            out.append(iv)
        iv.kinds[kind] = iv.kinds.get(kind, 0.0) + (top - bot)
        if lay.label not in iv.labels:
            iv.labels.append(lay.label)
    if not out:
        return None
    bottom = z0 - float(hole.total_depth_ft) if hole.total_depth_ft else out[-1].bottom_elev_ft
    return Column(hole.boring_id, float(x), float(y), z0, min(bottom, out[-1].bottom_elev_ft), out)


# ── correlation ──────────────────────────────────────────────────────────────

@dataclass
class Unit:
    """One correlated layer: the interval each boring has of it."""
    group: str
    members: dict = field(default_factory=dict)    # column id -> Interval

    @property
    def mid_ft(self) -> float:
        return float(np.mean([iv.mid_ft for iv in self.members.values()]))

    @property
    def kind(self) -> str:
        """The kind logged thickest across the borings."""
        tally: dict[str, float] = {}
        for iv in self.members.values():
            for k, t in iv.kinds.items():
                tally[k] = tally.get(k, 0.0) + t
        return max(tally, key=tally.get) if tally else self.group

    @property
    def labels(self) -> list[str]:
        seen: list[str] = []
        for iv in self.members.values():
            for lab in iv.labels:
                if lab not in seen:
                    seen.append(lab)
        return seen

    @property
    def name(self) -> str:
        return KIND_STYLES.get(self.kind, KIND_STYLES["unknown"])[2]


def _align(units: list[Unit], ivs: list[Interval]):
    """Order-preserving alignment of a column's intervals to the master units.
    Returns [(unit index or None, interval index or None)] in order."""
    n, m = len(units), len(ivs)
    INF = math.inf
    cost = np.full((n + 1, m + 1), INF)
    back = np.zeros((n + 1, m + 1), dtype=int)       # 0 diag, 1 skip unit, 2 new unit
    cost[0, 0] = 0.0
    mids = [u.mid_ft for u in units]
    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i, j]
            if c == INF:
                continue
            if i < n and j < m and units[i].group == ivs[j].group:
                d = c + abs(mids[i] - ivs[j].mid_ft) / MATCH_SCALE_FT
                if d < cost[i + 1, j + 1]:
                    cost[i + 1, j + 1], back[i + 1, j + 1] = d, 0
            if i < n and c + GAP_COST < cost[i + 1, j]:
                cost[i + 1, j], back[i + 1, j] = c + GAP_COST, 1
            if j < m and c + GAP_COST < cost[i, j + 1]:
                cost[i, j + 1], back[i, j + 1] = c + GAP_COST, 2
    path, i, j = [], n, m
    while i or j:
        b = back[i, j]
        if b == 0:
            path.append((i - 1, j - 1)); i, j = i - 1, j - 1
        elif b == 1:
            path.append((i - 1, None)); i -= 1
        else:
            path.append((None, j - 1)); j -= 1
    return path[::-1]


def correlate(columns: list[Column]) -> list[Unit]:
    """Columns -> correlated units, top to bottom.  The column with the most
    intervals seeds the sequence; the others join nearest first."""
    cols = [c for c in columns if c.intervals]
    if not cols:
        return []
    seed = max(cols, key=lambda c: (len(c.intervals), -c.bottom_elev_ft))
    units = [Unit(iv.group, {seed.id: iv}) for iv in seed.intervals]
    rest = sorted((c for c in cols if c is not seed), key=lambda c: math.hypot(c.x - seed.x, c.y - seed.y))
    for col in rest:
        merged: list[Unit] = []
        for ui, vi in _align(units, col.intervals):
            if ui is not None:
                u = units[ui]
                if vi is not None:
                    u.members[col.id] = col.intervals[vi]
                merged.append(u)
            else:
                merged.append(Unit(col.intervals[vi].group, {col.id: col.intervals[vi]}))
        units = merged
    return units


# ── surfaces and solids ──────────────────────────────────────────────────────

def thickness_table(units: list[Unit], columns: list[Column]) -> dict[str, list[float | None]]:
    """Per column, each unit's thickness: the logged thickness, 0 where the
    unit pinches out between layers the boring does have, None where the
    boring stopped above it - and None for the unit a boring stopped in
    (its true bottom is deeper than the log)."""
    out = {}
    for col in columns:
        idx = [k for k, u in enumerate(units) if col.id in u.members]
        if not idx:
            continue
        last = idx[-1]
        row: list[float | None] = []
        for k, u in enumerate(units):
            if k > last:
                row.append(None)
            elif col.id in u.members:
                row.append(None if k == last else u.members[col.id].thickness_ft)
            else:
                row.append(0.0)                              # logged through without it: pinched out here
        out[col.id] = row
    return out


def _idw(xy: np.ndarray, values: np.ndarray, gx: np.ndarray, gy: np.ndarray, power: float = 2.0) -> np.ndarray:
    d2 = (gx[..., None] - xy[:, 0]) ** 2 + (gy[..., None] - xy[:, 1]) ** 2
    exact = d2 < 1e-6
    w = 1.0 / np.maximum(d2, 1e-6) ** (power / 2.0)
    out = (w * values).sum(-1) / w.sum(-1)
    hit = exact.any(-1)
    if hit.any():
        out[hit] = values[np.argmax(exact[hit], axis=-1)]
    return out


def boundary_table(units: list[Unit], columns: list[Column]) -> dict[str, list[float | None]]:
    """Per column, the elevation of the bottom of each unit: logged, equal to
    the boundary above where the unit pinches out, None below where the
    boring stopped (and for the unit it stopped in)."""
    out = {}
    for col, row in thickness_table(units, columns).items():
        c = next(x for x in columns if x.id == col)
        z, elev = c.ground_elev_ft, []
        for t in row:
            if t is None:
                elev.append(None)
                z = None
                continue
            z = None if z is None else z - t
            elev.append(z)
        out[col] = elev
    return out


def surfaces(units: list[Unit], columns: list[Column], gx: np.ndarray, gy: np.ndarray, *,
             ground=None, base_elev_ft: float | None = None, power: float = 2.0) -> np.ndarray:
    """Boundary elevations on the grid ``gx``, ``gy`` (same shape): index 0 the
    ground, index k the bottom of unit k-1; shape (len(units) + 1, *gx.shape).
    Each boundary is interpolated as an elevation from the borings that log
    it, kept below the one above, and cut off at the ground (``ground(gx,
    gy)``, else the collars interpolated) and the base (default: the deepest
    log)."""
    cols = [c for c in columns if any(c.id in u.members for u in units)]
    xy = np.array([[c.x, c.y] for c in cols], float)
    collars = _idw(xy, np.array([c.ground_elev_ft for c in cols]), gx, gy, power)
    top = np.asarray(ground(gx, gy), float) if ground is not None else collars
    base = min(c.bottom_elev_ft for c in cols) if base_elev_ft is None else base_elev_ft
    table = boundary_table(units, cols)
    raw = [collars]
    for k in range(len(units)):
        known = [(c, table[c.id][k]) for c in cols if table[c.id][k] is not None]
        if k == len(units) - 1 or not known:
            nxt = np.full(gx.shape, base, float)            # the deepest unit (or one no boring got through) runs to the base
        else:
            nxt = _idw(np.array([[c.x, c.y] for c, _ in known]), np.array([v for _, v in known]), gx, gy, power)
        raw.append(np.maximum(np.minimum(nxt, raw[-1]), base))
    out = [np.maximum(top, base)] + [np.minimum(r, np.maximum(top, base)) for r in raw[1:]]
    return np.array(out)


def unit_solids(surfs: np.ndarray, gx: np.ndarray, gy: np.ndarray, *, min_thickness_ft: float = 0.05):
    """A closed triangle mesh per unit between consecutive surfaces:
    [(vertices (N, 3), faces (M, 3)) or None where the unit is thinner than
    ``min_thickness_ft`` everywhere]."""
    ny, nx = gx.shape
    out = []
    for k in range(len(surfs) - 1):
        top, bot = surfs[k], surfs[k + 1]
        if float((top - bot).max()) < min_thickness_ft:
            out.append(None)
            continue
        vt = np.column_stack([gx.ravel(), gy.ravel(), top.ravel()])
        vb = np.column_stack([gx.ravel(), gy.ravel(), bot.ravel()])
        verts = np.vstack([vt, vb])
        nb = nx * ny
        faces = []
        for j in range(ny - 1):
            for i in range(nx - 1):
                a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i
                faces += [(a, b, c), (a, c, d)]                                   # top, normals up
                faces += [(a + nb, c + nb, b + nb), (a + nb, d + nb, c + nb)]     # bottom, normals down
        ring = ([i for i in range(nx)] + [j * nx + nx - 1 for j in range(1, ny)]
                + [(ny - 1) * nx + i for i in range(nx - 2, -1, -1)] + [j * nx for j in range(ny - 2, 0, -1)])
        for p, q in zip(ring, ring[1:] + ring[:1]):                             # sides, normals out
            faces += [(p, p + nb, q + nb), (p, q + nb, q)]
        out.append((verts, np.array(faces, dtype=int)))
    return out


def model_grid(center_xy, along, half_length_ft: float, half_width_ft: float, cell_ft: float = 5.0):
    """A grid over a rectangle centred on ``center_xy`` with its long side
    along the unit vector ``along``; returns (gx, gy) in the same plane."""
    a = np.asarray(along, float)
    a = a / np.linalg.norm(a)
    n = np.array([-a[1], a[0]])
    s = np.linspace(-half_length_ft, half_length_ft, max(2, int(round(2 * half_length_ft / cell_ft)) + 1))
    t = np.linspace(-half_width_ft, half_width_ft, max(2, int(round(2 * half_width_ft / cell_ft)) + 1))
    S, T = np.meshgrid(s, t)
    return center_xy[0] + S * a[0] + T * n[0], center_xy[1] + S * a[1] + T * n[1]
