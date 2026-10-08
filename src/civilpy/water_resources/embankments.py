#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Embankments and the openings LiDAR cannot see, on a bare-earth grid.

A bare-earth DEM shows the top of a road, railroad, levee or farm berm but
not the pipes through it, so a hydraulic model built straight from LiDAR
treats every embankment as solid.  Two screens on a regular grid:

* :func:`embankments` - narrow raised linear features (white top-hat: the
  ground minus its morphological opening with a disk ``max_width_ft``
  across; connected, elongated, at least ``min_height_ft`` high).  Each
  gets a crest elevation, height, width and length, and is labelled a
  ``wall`` when it is too narrow for an earth embankment (a floodwall or
  retaining wall), an ``embankment`` when it has a flat crest (a road, rail
  bed or levee crown) and a ``ridge`` when its top is rounded (most likely
  natural ground) - geometry only; the grid cannot tell whether any of
  them is permeable.
* :func:`hidden_openings` - "digital dams": closed depressions (priority
  flood, Barnes et al. 2014) that would fill against an embankment while
  ground lower than the depression's bottom lies just across it.  Real
  terrain rarely makes that shape; a pipe through the fill usually does.
  Each candidate is the shortest straight crossing from the depression to
  that lower ground (at most ``max_breach_ft`` long, over a crest at least
  ``min_embankment_ft`` above the bottom), with the ponded volume the
  solid-embankment model would store behind it.

Candidates are leads to check against inventories, imagery or the field,
not findings.  The grid is ``z[row, col]`` at ``x = x0 + col * cell``,
``y = y0 + row * cell`` (NaN = no data); units are feet.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

WALL_MAX_WIDTH_FT = 6.0     # narrower than this at half height: a wall, not an earth fill
FLAT_CREST_GRADE = 0.08     # crest cells flatter than this count toward the crest width
MIN_CREST_WIDTH_FT = 8.0    # a flat top at least this wide: a built fill, not a rounded natural ridge


@dataclass
class DemGrid:
    z: np.ndarray
    cell_ft: float
    x0: float = 0.0
    y0: float = 0.0

    def xy(self, row, col):
        return self.x0 + col * self.cell_ft, self.y0 + row * self.cell_ft

    @classmethod
    def from_points(cls, pts, cell_ft: float = 5.0, *, fill_gaps_cells: int = 2) -> "DemGrid":
        """Grid (N, 3) points by their lowest return per cell; holes up to
        ``fill_gaps_cells`` wide take the mean of their neighbours."""
        from scipy import ndimage

        pts = np.asarray(pts, float)
        x0, y0 = pts[:, 0].min(), pts[:, 1].min()
        col = np.floor((pts[:, 0] - x0) / cell_ft).astype(int)
        row = np.floor((pts[:, 1] - y0) / cell_ft).astype(int)
        z = np.full((row.max() + 1, col.max() + 1), np.inf)
        np.minimum.at(z, (row, col), pts[:, 2])
        z[np.isinf(z)] = np.nan
        for _ in range(fill_gaps_cells):
            hole = np.isnan(z)
            if not hole.any():
                break
            filled = np.where(hole, 0.0, z)
            k = np.ones((3, 3))
            s = ndimage.convolve(filled, k, mode="constant")
            n = ndimage.convolve((~hole).astype(float), k, mode="constant")
            z = np.where(hole & (n >= 3), s / np.maximum(n, 1), z)
        return cls(z, cell_ft, x0 + cell_ft / 2, y0 + cell_ft / 2)


# ── priority flood ─────────────────────────────────────────────────────────

_N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def priority_flood(z: np.ndarray, *, outlets: str = "lowest", outlet_tol_ft: float = 0.5) -> np.ndarray:
    """Depression-filled surface: every cell raised to the lowest level at
    which water could leave the grid.

    ``outlets="lowest"`` (a valley reach): water leaves only where the
    boundary is lowest (within ``outlet_tol_ft``) - the downstream channel.
    The upstream channel and the valley sides also cross the boundary, but
    the ground keeps rising beyond them, so they are not ways out.
    ``outlets="edges"``: anywhere on the boundary.  No-data cells (a deck
    shadow, a gap) are transparent: water passes them at the level it
    arrives with, so they neither drain nor dam."""
    nr, nc = z.shape
    nodata = np.isnan(z)
    zz = np.where(nodata, -np.inf, z)
    filled = zz.copy()
    done = np.zeros(z.shape, bool)
    edge = np.zeros(z.shape, bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    edge &= ~nodata
    if outlets == "lowest" and edge.any():
        edge &= zz <= zz[edge].min() + outlet_tol_ft
    elif outlets != "edges":
        raise ValueError("outlets is 'lowest' or 'edges'")
    heap = [(zz[r, c], r, c) for r, c in zip(*np.nonzero(edge))]
    heapq.heapify(heap)
    done[edge] = True
    while heap:
        h, r, c = heapq.heappop(heap)
        for dr, dc in _N8:
            rr, cc = r + dr, c + dc
            if 0 <= rr < nr and 0 <= cc < nc and not done[rr, cc]:
                done[rr, cc] = True
                filled[rr, cc] = max(zz[rr, cc], h)
                heapq.heappush(heap, (filled[rr, cc], rr, cc))
    return np.where(nodata, np.nan, filled)


@dataclass
class Depression:
    label: int
    cells: np.ndarray            # (k, 2) row, col
    bottom_elev: float
    spill_elev: float
    area_ft2: float
    volume_ft3: float
    flat_bottom: bool            # bottom flat over many cells: a flight-day water surface (pond)

    @property
    def depth_ft(self):
        return self.spill_elev - self.bottom_elev


def depressions(grid: DemGrid, *, min_depth_ft: float = 1.0, min_area_ft2: float = 200.0,
                filled: np.ndarray | None = None) -> list[Depression]:
    from scipy import ndimage

    z = grid.z
    filled = priority_flood(z) if filled is None else filled
    depth = np.where(np.isnan(z) | np.isnan(filled), 0.0, filled - z)
    lab, n = ndimage.label(depth > 1e-3, structure=np.ones((3, 3)))
    out = []
    a_cell = grid.cell_ft ** 2
    for k in range(1, n + 1):
        cells = np.argwhere(lab == k)
        d = depth[cells[:, 0], cells[:, 1]]
        if d.max() < min_depth_ft or len(cells) * a_cell < min_area_ft2:
            continue
        zz = z[cells[:, 0], cells[:, 1]]
        bottom = float(zz.min())
        flat = int((zz <= bottom + 0.1).sum()) * a_cell >= 400.0
        out.append(Depression(k, cells, bottom, float(filled[cells[0, 0], cells[0, 1]]),
                              len(cells) * a_cell, float(d.sum() * a_cell), flat))
    return out


# ── embankments ────────────────────────────────────────────────────────────

@dataclass
class Embankment:
    cells: np.ndarray
    crest_elev: float            # median of the ridge line
    height_ft: float             # 90th-percentile rise above the ground either side
    width_ft: float              # mean width at half height
    length_ft: float
    axis: tuple                  # unit vector along the feature
    centre: tuple                # x, y
    kind: str                    # "embankment" (flat crest) | "wall" (too thin for earth) | "ridge" (rounded: natural?)
    crest_width_ft: float = 0.0  # flat (<= FLAT_CREST_GRADE) top width


def _disk(radius_cells):
    r = max(int(radius_cells), 1)
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def embankments(grid: DemGrid, *, max_width_ft: float = 80.0, min_height_ft: float = 2.0,
                min_length_ft: float = 100.0, min_elongation: float = 3.0) -> list[Embankment]:
    from scipy import ndimage

    z = grid.z
    hole = np.isnan(z)
    zf = np.where(hole, np.nanmin(z), z)
    rise = zf - ndimage.grey_opening(zf, footprint=_disk(max_width_ft / 2 / grid.cell_ft))
    rise[hole] = 0.0
    gy, gx = np.gradient(zf, grid.cell_ft)
    grad = np.hypot(gx, gy)
    grad[hole] = np.inf
    lab, n = ndimage.label(rise >= min_height_ft / 2, structure=np.ones((3, 3)))
    out = []
    for k in range(1, n + 1):
        cells = np.argwhere(lab == k)
        if len(cells) < 3:
            continue
        hts = rise[cells[:, 0], cells[:, 1]]
        height = float(np.percentile(hts, 90))
        if height < min_height_ft:
            continue
        xy = np.column_stack(grid.xy(cells[:, 0], cells[:, 1]))
        cen = xy.mean(axis=0)
        w, v = np.linalg.eigh(np.cov((xy - cen).T))
        major = v[:, 1]
        along = (xy - cen) @ major
        length = float(along.max() - along.min()) + grid.cell_ft
        width = len(cells) * grid.cell_ft ** 2 / length
        if length < min_length_ft or length / max(width, grid.cell_ft) < min_elongation:
            continue
        top = cells[hts >= np.percentile(hts, 75)]
        crest = float(np.median(z[top[:, 0], top[:, 1]]))
        # a built fill has a flat top (road, rail bed, levee crown); a natural spur is rounded
        upper = (hts >= 0.7 * height) & (grad[cells[:, 0], cells[:, 1]] <= FLAT_CREST_GRADE)
        crest_w = float(upper.sum()) * grid.cell_ft ** 2 / length
        if width < WALL_MAX_WIDTH_FT:
            kind = "wall"
        elif crest_w >= MIN_CREST_WIDTH_FT:
            kind = "embankment"
        else:
            kind = "ridge"
        out.append(Embankment(cells, crest, height, width, length, (float(major[0]), float(major[1])),
                              (float(cen[0]), float(cen[1])), kind, crest_w))
    return out


# ── openings the grid cannot see ───────────────────────────────────────────

@dataclass
class OpeningCandidate:
    depression: Depression
    upstream_xy: tuple           # depression-side end of the crossing
    downstream_xy: tuple         # lower-ground end
    upstream_elev: float         # depression bottom
    downstream_elev: float
    crest_elev: float            # highest ground on the crossing
    length_ft: float
    ponded_volume_ft3: float     # what a solid-embankment model stores behind it

    @property
    def fill_height_ft(self):
        return self.crest_elev - self.upstream_elev

    @property
    def midpoint(self):
        return tuple(0.5 * (a + b) for a, b in zip(self.upstream_xy, self.downstream_xy))


def _profile_max(grid, p, q, step):
    n = max(int(math.hypot(q[0] - p[0], q[1] - p[1]) / step), 2)
    rr = np.linspace(p[0], q[0], n + 1).round().astype(int)
    cc = np.linspace(p[1], q[1], n + 1).round().astype(int)
    vals = grid.z[rr, cc]
    return float(np.nanmax(vals)) if np.isfinite(vals).any() else math.nan


def hidden_openings(grid: DemGrid, *, max_breach_ft: float = 150.0, min_depth_ft: float = 1.0,
                    min_area_ft2: float = 200.0, min_drop_ft: float = 0.25, min_embankment_ft: float = 1.5,
                    filled: np.ndarray | None = None) -> list[OpeningCandidate]:
    """Depressions held by an embankment with lower ground just across it,
    largest ponded volume first."""
    from scipy import ndimage

    z = grid.z
    filled = priority_flood(z) if filled is None else filled
    found = []
    for dep in depressions(grid, min_depth_ft=min_depth_ft, min_area_ft2=min_area_ft2, filled=filled):
        mask = np.zeros(z.shape, bool)
        mask[dep.cells[:, 0], dep.cells[:, 1]] = True
        dist, (ir, ic) = ndimage.distance_transform_edt(~mask, return_indices=True)
        dist *= grid.cell_ft
        target = (~mask) & np.isfinite(z) & (z < dep.bottom_elev - min_drop_ft) & (dist <= max_breach_ft)
        if not target.any():
            continue
        order = np.argsort(dist[target])
        tr, tc = np.nonzero(target)
        for idx in order[:200]:
            r, c = tr[idx], tc[idx]
            src = (ir[r, c], ic[r, c])
            crest = _profile_max(grid, src, (r, c), 0.5)
            if not math.isfinite(crest) or crest - dep.bottom_elev < min_embankment_ft:
                continue
            found.append(OpeningCandidate(dep, grid.xy(*src), grid.xy(r, c), dep.bottom_elev, float(z[r, c]),
                                          crest, float(dist[r, c]), dep.volume_ft3))
            break
    return sorted(found, key=lambda o: -o.ponded_volume_ft3)
