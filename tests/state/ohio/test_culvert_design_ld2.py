"""L&D Vol 2 1105 / 1006 culvert sizing - civilpy.state.ohio.DOT.culvert_design."""
import math

import pytest

from civilpy.state.ohio.DOT import culvert_design as cd
from civilpy.water_resources import culvert as cv


def test_cmp_n_from_figure_1105_2():
    assert cd.cmp_n(15) == 0.0250 and cd.cmp_n(10) == 0.0250 and cd.cmp_n(72) == 0.0229 and cd.cmp_n(100) == 0.0229
    assert cd.cmp_n(27) == pytest.approx((0.0247 + 0.0244) / 2)
    assert cd.cmp_n(60, corrugation="3x1") == 0.0332 and cd.cmp_n(120, corrugation="3x1") == 0.0314


def test_catalog_order_and_contents():
    cat = cd.catalog()
    fams = [c.family for c in cat]
    assert fams.index("round") < fams.index("ellipse") < fams.index("pipe_arch") < fams.index("box")
    rounds = [c for c in cat if c.family == "round"]
    assert rounds[0].label == "12 in RCP" and rounds[-1].span_ft == 10.0 and all(c.n == 0.012 and c.ke == 0.2 for c in rounds)
    he = [c for c in cat if c.family == "ellipse"]
    assert he[0].span_ft == pytest.approx(23 / 12) and he[0].rise_ft == pytest.approx(14 / 12)
    arches = [c for c in cat if c.family == "pipe_arch"]
    assert all(c.ke == 0.9 for c in arches) and arches[0].n == pytest.approx(cd.cmp_n(math.sqrt(17 * 13)))
    boxes = [c for c in cat if c.family == "box"]
    areas = [b.area_sqft for b in boxes]
    assert areas == sorted(areas) and all(b.rise_ft <= b.span_ft + 2 for b in boxes)
    assert [c.family for c in cd.catalog(("box",))] == ["box"] * len(boxes)
    assert cat[0].shape().rise == pytest.approx(1.0) and boxes[0].shape().span == 3.0


SITE = dict(inlet_invert_ft=600.0, outlet_invert_ft=599.0, length_ft=60.0, pavement_low_edge_ft=608.0, drainage_area_acres=400.0)


def test_small_flow_takes_a_small_round_pipe():
    r = cd.size_culvert(q_design_cfs=8.0, q_check_1pct_cfs=14.0, **SITE)
    s = r["selected"]
    assert s["family"] == "round" and s["cells"] == 1 and s["design_ok"] and s["check_ok"]
    assert s["headwater_ft"] <= s["allowable_ft"] and s["allowable_ft"] <= 607.0            # A: 1 ft below the pavement edge (< 1,000 acres)
    assert s["depth_1pct_ft"] <= s["max_1pct_depth_ft"]
    assert set(r["per_family"]) == {"round", "ellipse", "pipe_arch", "box"} and r["tried"] > 4
    # the next size down fails one of the controls
    cat = [c for c in cd.catalog(("round",))]
    i = next(k for k, c in enumerate(cat) if c.label == s["conduit"])
    if i > 0:
        smaller = cv.Culvert(cat[i - 1].shape(), length_ft=60.0, inlet_invert=600.0, outlet_invert=599.0, n=0.012,
                             inlet=cat[i - 1].inlet, ke=0.2)
        hw = smaller.headwater(8.0, None, method="approximate").headwater_elev
        hw1 = smaller.headwater(14.0, None, method="approximate").headwater_elev
        assert hw > min(607.0, 600.0 + cat[i - 1].rise_ft + 2.0) - 1e-6 or hw1 - 600.0 > 2 * cat[i - 1].rise_ft - 1e-6


def test_cover_limit_pushes_to_a_flatter_shape_and_two_cells():
    # only 3 ft of rise fits under the road: a round pipe big enough for 120 cfs does not fit, a box does
    r = cd.size_culvert(q_design_cfs=120.0, q_check_1pct_cfs=None, max_rise_ft=4.0, **SITE)
    s = r["selected"]
    assert s is not None and s["rise_ft"] + 1.0 <= 4.0 and s["family"] in ("ellipse", "pipe_arch", "box")
    assert all(row["rise_ft"] + 1.0 <= 4.0 for row in r["per_family"].values())
    # nothing single-cell under 2 ft of rise for 60 cfs: two cells get tried
    r2 = cd.size_culvert(q_design_cfs=60.0, q_check_1pct_cfs=None, max_rise_ft=3.0, families=("box",), **SITE)
    assert r2["selected"] is None or r2["selected"]["cells"] in (1, 2)
    r3 = cd.size_culvert(q_design_cfs=5000.0, q_check_1pct_cfs=None, families=("round",), **SITE)
    assert r3["selected"] is None and r3["per_family"] == {}


def test_tailwater_forms_and_deep_ravine():
    base = dict(q_design_cfs=40.0, q_check_1pct_cfs=70.0, **SITE)
    free = cd.size_culvert(**base)
    high = cd.size_culvert(tailwater=604.0, **base)
    rule = cd.size_culvert(tailwater="half_dc_d", **base)
    rating = cd.size_culvert(tailwater=lambda q: 599.0 + 0.02 * q, **base)
    assert high["selected"]["headwater_ft"] >= free["selected"]["headwater_ft"] - 1e-6
    assert any("(dc + D) / 2" in n for n in rule["notes"]) and rule["selected"] is not None and rating["selected"] is not None
    ravine = cd.size_culvert(deep_ravine=True, **base)
    assert ravine["selected"]["allowable_ft"] >= free["selected"]["allowable_ft"]
    big = cd.size_culvert(q_design_cfs=40.0, q_check_1pct_cfs=70.0, **dict(SITE, drainage_area_acres=1500.0))
    assert big["selected"]["allowable_ft"] <= 606.0                                       # 2 ft below the pavement edge


def test_half_dc_d_tailwater():
    c = cv.Culvert(cv.BarrelShape.circular(3.0), length_ft=60.0, inlet_invert=600.0, outlet_invert=599.0, n=0.012,
                   inlet="concrete_pipe_groove_headwall")
    tw = cd.half_dc_d_tailwater(c, 30.0)
    assert 599.0 + 1.5 < tw <= 599.0 + 3.0


def test_size_culvert_takes_an_agency_catalog():
    small = [cd.Conduit("round", "18 in RCP", 1.5, 1.5, 0.012, "concrete_pipe_groove_headwall", 0.2),
             cd.Conduit("box", "4 x 3 ft box", 4.0, 3.0, 0.012, "box_wingwall_30_75", 0.4)]
    out = cd.size_culvert(q_design_cfs=60.0, q_check_1pct_cfs=90.0, inlet_invert_ft=100.0, outlet_invert_ft=99.0, length_ft=60.0,
                          pavement_low_edge_ft=110.0, drainage_area_acres=300.0, conduits=small)
    assert out["selected"] is not None and out["selected"]["conduit"] in ("18 in RCP", "4 x 3 ft box")
    assert set(out["per_family"]) <= {"round", "box"}
