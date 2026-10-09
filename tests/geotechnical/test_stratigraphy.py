"""Strata correlation between borings: synthetic sites built from known
layer surfaces (planes with random dips, random pinch-outs, borings stopping
at random depths) must come back as the same layer sequence, honour every
boring exactly, never cross, and give closed solids."""
import random

import numpy as np
import pytest

from civilpy.geotech import stratigraphy as st
from civilpy.geotech.boring import Borehole, Layer

GROUP_CLASS = {"granular": "A-1-b", "silt": "A-4a", "clay": "A-6a", "rock": "SHALE", "topsoil": "TOPSOIL"}


def site(rng, n_holes=5):
    """Holes through a sequence of layers whose bottoms are tilted planes."""
    seq = ["topsoil"] + rng.sample(["granular", "silt", "clay"], 3) + ["rock"]
    planes = []
    z = 700.0
    for _ in seq:
        z -= rng.uniform(4, 12)
        planes.append((z, rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03)))
    pinch = {(h, k) for h in range(n_holes) for k in range(1, len(seq) - 1) if rng.random() < 0.2}
    holes, xy = [], []
    for h in range(n_holes):
        x, y = rng.uniform(-80, 80), rng.uniform(-30, 30)
        ground = 700.0 + 0.01 * x
        depth, layers = 0.0, []
        for k, g in enumerate(seq):
            z0, ax, ay = planes[k]
            bottom_elev = z0 + ax * x + ay * y
            if (h, k) in pinch:
                continue
            d_bot = ground - bottom_elev
            if d_bot <= depth + 0.5:
                continue
            system = "ROCK" if g == "rock" else "SOIL"
            layers.append(Layer(depth, d_bot, system=system, classification=GROUP_CLASS[g]))
            depth = d_bot
        stop = depth if rng.random() < 0.6 else layers[-1].depth_top_ft + 2.0   # some stop early in the last layer
        layers[-1] = Layer(layers[-1].depth_top_ft, stop, system=layers[-1].system,
                           classification=layers[-1].classification)
        holes.append(Borehole(boring_id=f"B-{h}", ground_elevation_ft=ground, layers=layers, total_depth_ft=stop))
        xy.append((x, y))
    return seq, holes, xy


@pytest.mark.parametrize("seed", range(25))
def test_correlation_recovers_the_sequence_and_honours_every_boring(seed):
    rng = random.Random(seed)
    seq, holes, xy = site(rng)
    cols = [st.column(h, x, y) for h, (x, y) in zip(holes, xy)]
    units = st.correlate(cols)
    # each group of the true sequence appears once, in order (nothing invented or split)
    groups = [u.group for u in units]
    assert groups == [g for g in seq if g in groups]
    for c in cols:                                                 # every interval is in exactly one unit, in order
        mine = [u for u in units if c.id in u.members]
        assert [u.members[c.id] for u in mine] == c.intervals

    gx, gy = st.model_grid((0.0, 0.0), (1.0, 0.0), 100.0, 40.0, cell_ft=5.0)
    gx = np.concatenate([gx.ravel(), [c.x for c in cols]]).reshape(1, -1)   # the borings sit on grid nodes
    gy = np.concatenate([gy.ravel(), [c.y for c in cols]]).reshape(1, -1)
    surfs = st.surfaces(units, cols, gx, gy)
    assert np.all(np.diff(surfs, axis=0) <= 1e-9)                 # boundaries never cross
    assert np.all(surfs[-1] >= min(c.bottom_elev_ft for c in cols) - 1e-9)
    table = st.thickness_table(units, cols)
    for n, c in enumerate(cols):
        j = gx.shape[1] - len(cols) + n
        z = surfs[0, 0, j]
        assert z == pytest.approx(c.ground_elev_ft)
        for k, t in enumerate(table[c.id]):
            if t is None:
                break
            assert z - surfs[k + 1, 0, j] == pytest.approx(t, abs=1e-6)   # logged (or zero) thickness kept
            z = surfs[k + 1, 0, j]


@pytest.mark.parametrize("seed", range(8))
def test_solids_are_closed(seed):
    rng = random.Random(seed)
    seq, holes, xy = site(rng)
    cols = [st.column(h, x, y) for h, (x, y) in zip(holes, xy)]
    units = st.correlate(cols)
    gx, gy = st.model_grid((0.0, 0.0), (0.6, 0.8), 60.0, 25.0, cell_ft=10.0)
    surfs = st.surfaces(units, cols, gx, gy, ground=lambda x, y: 702.0 + 0 * x)
    for solid in st.unit_solids(surfs, gx, gy):
        if solid is None:
            continue
        verts, faces = solid
        edges = {}
        for f in faces:
            for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                edges[(a, b)] = edges.get((a, b), 0) + 1
        # closed and consistently oriented: every directed edge once, and its reverse once
        assert all(n == 1 for n in edges.values())
        assert all((b, a) in edges for (a, b) in edges)


@pytest.mark.parametrize("cls,desc,system,kind", [
    ("A-1-a", None, "SOIL", "gravel"), ("A-1-b", None, "SOIL", "sand"), ("A-3", None, "SOIL", "sand"),
    ("A-2-4", "SANDY GRAVEL", "SOIL", "gravel"), ("A-2-6", "GRAVEL AND SAND", "SOIL", "sand"),
    ("A-4a", None, "SOIL", "silt"), ("A-7-6", None, "SOIL", "clay"), ("A-8", None, "SOIL", "organic"),
    ("SHALE", None, "ROCK", "shale"), ("LIMESTONE", None, "ROCK", "limestone"),
    (None, "SANDSTONE, GRAY", "ROCK", "sandstone"), ("TOPSOIL", None, "SOIL", "topsoil"),
])
def test_layer_kind(cls, desc, system, kind):
    assert st.layer_kind(Layer(0, 1, system=system, classification=cls, description=desc)) == kind
    assert kind in st.KIND_STYLES


@pytest.mark.parametrize("seed", range(8))
def test_a_channel_cuts_the_layers_off_instead_of_dragging_them_down(seed):
    """Lowering the ground in a band (a channel) changes the layers only
    where they now stand above it; elsewhere they are the same."""
    rng = random.Random(seed)
    seq, holes, xy = site(rng)
    cols = [st.column(h, x, y) for h, (x, y) in zip(holes, xy)]
    units = st.correlate(cols)
    gx, gy = st.model_grid((0.0, 0.0), (1.0, 0.0), 100.0, 40.0, cell_ft=5.0)
    flat = st.surfaces(units, cols, gx, gy, ground=lambda x, y: 701.0 + 0 * x)
    depth = rng.uniform(5, 20)
    cut = st.surfaces(units, cols, gx, gy, ground=lambda x, y: np.where(np.abs(x) < 20, 701.0 - depth, 701.0))
    ground = np.where(np.abs(gx) < 20, 701.0 - depth, 701.0)
    assert np.all(cut <= np.maximum(ground, cut[-1]) + 1e-9)
    outside = np.abs(gx) >= 20
    assert np.allclose(cut[:, outside], flat[:, outside])
    assert np.allclose(cut[1:], np.minimum(flat[1:], np.maximum(ground, cut[-1])))
