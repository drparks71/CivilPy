#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Embankment and hidden-opening screens on synthetic valleys: a sloping
floodplain with a channel, crossed by a road fill (solid, or cut by an
opening), a thin wall, or nothing."""

import math

import numpy as np
import pytest

from civilpy.water_resources import embankments as em

CELL = 5.0
N = 120                       # 600 ft square


def valley(*, angle_deg=0.0, fill_height=6.0, crest_ft=30.0, side=2.0, opening_ft=0.0, wall=False,
           fall=0.004, channel_depth=4.0):
    """Valley falling toward -y, channel along x = 300; a fill across the
    valley at y = 300, rotated by ``angle_deg``; ``opening_ft`` cuts the fill
    over the channel (a bridge)."""
    yy, xx = np.mgrid[0:N, 0:N] * CELL
    xc, yc = 300.0, 300.0
    z = 100.0 + fall * yy + 0.01 * np.abs(xx - xc)
    z -= channel_depth * np.clip(1 - np.abs(xx - xc) / 20.0, 0, 1)
    a = math.radians(angle_deg)
    u = -(xx - xc) * math.sin(a) + (yy - yc) * math.cos(a)      # distance across the fill
    v = (xx - xc) * math.cos(a) + (yy - yc) * math.sin(a)       # along it
    top = 100.0 + fall * yc + fill_height
    if wall:
        prism = np.where(np.abs(u) <= 2.0, top, -np.inf)
    else:
        half = crest_ft / 2
        prism = top - np.clip(np.abs(u) - half, 0, None) / side
    if opening_ft:
        prism = np.where(np.abs(v) <= opening_ft / 2, -np.inf, prism)
    return em.DemGrid(np.maximum(z, prism), CELL)


class TestPriorityFlood:
    def test_bowl_fills_to_its_rim(self):
        yy, xx = np.mgrid[0:40, 0:40]
        z = 10.0 + 0.02 * ((xx - 20) ** 2 + (yy - 20) ** 2)
        f = em.priority_flood(z, outlets="edges")
        assert (f >= z - 1e-12).all()
        rim = min(z[0, :].min(), z[-1, :].min(), z[:, 0].min(), z[:, -1].min())
        assert f[20, 20] == pytest.approx(rim)              # the lowest point of the rim

    @pytest.mark.parametrize("outlets", ["edges", "lowest"])
    def test_filled_surface_drains(self, outlets):
        rng = np.random.default_rng(3)
        z = rng.random((30, 30)) * 5
        f = em.priority_flood(z, outlets=outlets)
        assert (f >= z - 1e-12).all()
        # every interior cell has a neighbour no higher than itself (a way out)
        for r in range(1, 29):
            for c in range(1, 29):
                assert f[r - 1:r + 2, c - 1:c + 2].min() <= f[r, c] + 1e-12

    def test_only_the_lowest_edge_drains_a_valley(self):
        g = valley(fill_height=6.0)
        edges = em.priority_flood(g.z, outlets="edges")
        lowest = em.priority_flood(g.z, outlets="lowest")
        assert (lowest >= edges - 1e-12).all()
        assert (lowest - g.z).sum() > (edges - g.z).sum()

    def test_nodata_is_transparent(self):
        z = np.full((20, 20), 10.0)
        z[:, 10] = 4.0                                   # a channel from the top edge down to the bottom edge
        z[0, 10] = 3.0
        z[8:12, 10] = np.nan                             # a deck shadow over it
        f = em.priority_flood(z)
        assert f[15, 10] == pytest.approx(4.0)           # neither dammed nor drained by the gap
        assert np.isnan(f[9, 10])


class TestEmbankments:
    @pytest.mark.parametrize("angle", [0.0, 25.0, 60.0])
    @pytest.mark.parametrize("height", [4.0, 8.0])
    def test_road_fill_found(self, angle, height):
        g = valley(angle_deg=angle, fill_height=height)
        found = em.embankments(g)
        assert found
        e = max(found, key=lambda e: e.length_ft)
        assert e.kind == "embankment"
        assert e.length_ft > 400
        assert e.height_ft == pytest.approx(height, abs=1.5)
        axis_deg = math.degrees(math.atan2(e.axis[1], e.axis[0])) % 180
        assert min(abs(axis_deg - angle), 180 - abs(axis_deg - angle)) < 5

    def test_thin_wall_is_a_wall(self):
        found = em.embankments(valley(wall=True, fill_height=5.0))
        assert found and max(found, key=lambda e: e.length_ft).kind == "wall"

    def test_rounded_spur_is_a_ridge(self):
        yy, xx = np.mgrid[0:N, 0:N] * CELL
        z = 100.0 + 0.004 * yy + 8.0 * np.exp(-((yy - 300.0) / 18.0) ** 2)
        found = em.embankments(em.DemGrid(z, CELL))
        assert found and max(found, key=lambda e: e.length_ft).kind == "ridge"

    @pytest.mark.parametrize("crest", [20.0, 30.0])        # >= ~3 cells: narrower crests read as rounded
    def test_flat_crest_width(self, crest):
        e = max(em.embankments(valley(crest_ft=crest, fill_height=6.0)), key=lambda e: e.length_ft)
        assert e.kind == "embankment"
        assert crest - 3 * CELL <= e.crest_width_ft <= crest + CELL      # edge cells read as slope

    def test_open_valley_has_none(self):
        assert em.embankments(valley(fill_height=0.0)) == []


class TestHiddenOpenings:
    @pytest.mark.parametrize("angle", [0.0, 30.0])
    @pytest.mark.parametrize("height", [5.0, 10.0])
    def test_solid_fill_across_channel_is_a_candidate(self, angle, height):
        g = valley(angle_deg=angle, fill_height=height)
        cands = em.hidden_openings(g)
        assert cands
        c = cands[0]
        # the crossing is over the fill, near the channel, about as long as the fill is wide
        mx, my = c.midpoint
        assert abs(mx - 300) < 60 and abs(my - 300) < 60
        base = 30.0 + 2 * 2.0 * height
        assert c.length_ft <= base + 4 * CELL
        assert c.crest_elev == pytest.approx(100 + 0.004 * 300 + height, abs=0.5)
        assert c.downstream_elev < c.upstream_elev
        assert c.ponded_volume_ft3 > 0

    def test_opening_through_fill_leaves_nothing_to_find(self):
        assert em.hidden_openings(valley(opening_ft=40.0)) == []

    def test_breach_longer_than_limit_is_not_reported(self):
        g = valley(fill_height=10.0, crest_ft=120.0)
        assert em.hidden_openings(g, max_breach_ft=100.0) == []
        assert em.hidden_openings(g, max_breach_ft=250.0)

    def test_bigger_fill_ponds_more(self):
        lo = em.hidden_openings(valley(fill_height=5.0))[0].ponded_volume_ft3
        hi = em.hidden_openings(valley(fill_height=10.0))[0].ponded_volume_ft3
        assert hi > lo


class TestGrid:
    def test_from_points_roundtrip(self):
        rng = np.random.default_rng(0)
        xy = rng.random((20000, 2)) * 200
        pts = np.column_stack([xy, 50 + 0.1 * xy[:, 0]])
        g = em.DemGrid.from_points(pts, 5.0)
        r, c = 20, 20
        x, y = g.xy(r, c)
        assert g.z[r, c] == pytest.approx(50 + 0.1 * x, abs=0.6)
        assert np.isfinite(g.z).mean() > 0.95
