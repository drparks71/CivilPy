#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""HDS-5 culvert analysis: geometry against closed forms, the inlet / outlet
control equations against hand evaluation, and the crossing solver's
conservation and monotonicity.  Synthetic culverts only."""

import math

import pytest

from civilpy.water_resources import culvert as cv

SHAPES = {
    "circle 3": lambda **kw: cv.BarrelShape.circular(3.0, **kw),
    "circle 6": lambda **kw: cv.BarrelShape.circular(6.0, **kw),
    "box 8x5": lambda **kw: cv.BarrelShape.box(8.0, 5.0, **kw),
    "ellipse 5x3": lambda **kw: cv.BarrelShape.ellipse(5.0, 3.2, **kw),
    "four-radius": lambda **kw: cv.BarrelShape.four_radius(12.0, 4.0, 80.0, **kw),
}
INLET_FOR = {"circle 3": "concrete_pipe_square_headwall", "circle 6": "cmp_projecting", "box 8x5": "box_wingwall_30_75",
             "ellipse 5x3": "ellipse_groove_headwall", "four-radius": "pipe_arch_mitered"}


def make(shape="circle 3", *, length=120.0, slope=0.005, n=0.013, embed=0.0, n_bed=None, barrels=1, inlet=None):
    s = SHAPES[shape](embedment_ft=embed)
    return cv.Culvert(s, length_ft=length, inlet_invert=100.0, outlet_invert=100.0 - slope * length, n=n,
                      inlet=inlet or INLET_FOR[shape], barrels=barrels, n_bed=n_bed)


def capacity_q(c, ratio):
    """A discharge with Q/AD^0.5 = ratio (per barrel x barrels)."""
    return ratio * c.shape.full.area * math.sqrt(c.rise) * c.barrels


# ── geometry ──────────────────────────────────────────────────────────────

class TestGeometry:
    @pytest.mark.parametrize("d", [1.5, 3.0, 7.0])
    def test_circle_full_and_partial(self, d):
        s = cv.BarrelShape.circular(d, segments=360)
        assert s.full.area == pytest.approx(math.pi * d * d / 4, rel=1e-3)
        assert s.full.perimeter == pytest.approx(math.pi * d, rel=1e-3)
        for frac in (0.2, 0.5, 0.8):
            y, r = frac * d, d / 2
            th = 2 * math.acos((r - y) / r)
            sec = s.section(y)
            assert sec.area == pytest.approx(r * r * (th - math.sin(th)) / 2, rel=5e-3)
            assert sec.top_width == pytest.approx(2 * math.sqrt(y * (d - y)), rel=5e-3)
            assert sec.perimeter == pytest.approx(r * th, rel=5e-3)

    @pytest.mark.parametrize("b,h", [(4, 3), (10, 6), (12, 12)])
    def test_box(self, b, h):
        s = cv.BarrelShape.box(b, h)
        for y in (0.3 * h, 0.7 * h):
            sec = s.section(y)
            assert sec.area == pytest.approx(b * y, rel=1e-3)
            assert sec.top_width == pytest.approx(b)
            assert sec.perimeter == pytest.approx(b + 2 * y, rel=1e-3)
        assert s.full.perimeter == pytest.approx(2 * (b + h))

    @pytest.mark.parametrize("a,b", [(6, 4), (4, 6)])
    def test_ellipse_area(self, a, b):
        s = cv.BarrelShape.ellipse(a, b, segments=360)
        assert s.full.area == pytest.approx(math.pi * a * b / 4, rel=1e-3)
        assert (s.span, s.rise) == (pytest.approx(a), pytest.approx(b))

    def test_four_radius_with_equal_radii_is_a_circle(self):
        s = cv.BarrelShape.four_radius(3.0, 3.0, 70.0, segments=90)
        assert s.span == pytest.approx(6.0, rel=1e-3)
        assert s.rise == pytest.approx(6.0, rel=1e-3)
        assert s.full.area == pytest.approx(math.pi * 9, rel=2e-3)

    @pytest.mark.parametrize("rt,rs,theta", [(12, 4, 80), (17, 4.5, 80), (9, 3, 60)])
    def test_four_radius_is_wider_than_tall_and_closed(self, rt, rs, theta):
        s = cv.BarrelShape.four_radius(rt, rs, theta)
        assert s.span > s.rise
        assert s.full.area < s.span * s.rise
        assert s.full.area > math.pi * s.span * s.rise / 4 * 0.95

    @pytest.mark.parametrize("shape", ["circle 6", "box 8x5", "ellipse 5x3"])
    @pytest.mark.parametrize("frac", [0.1, 0.3, 0.5])
    def test_embedment_bed_is_the_chord(self, shape, frac):
        full = SHAPES[shape]()
        s = SHAPES[shape](embedment_ft=frac * full.full_rise)
        assert s.rise == pytest.approx(full.full_rise * (1 - frac))
        assert s.section(0.5 * s.rise).bed_perimeter == pytest.approx(full._width_at(frac * full.full_rise), rel=1e-6)
        assert s.full.area == pytest.approx(full.full.area - full.section(frac * full.full_rise).area, rel=5e-3)

    @pytest.mark.parametrize("shape", list(SHAPES))
    def test_area_and_perimeter_grow_with_depth(self, shape):
        s = SHAPES[shape]()
        ys = [s.rise * i / 40 for i in range(41)]
        areas = [s.section(y).area for y in ys]
        perims = [s.section(y).perimeter for y in ys]
        assert all(b >= a for a, b in zip(areas, areas[1:]))
        assert all(b >= a - 1e-9 for a, b in zip(perims, perims[1:]))

    def test_embedment_must_be_below_crown(self):
        with pytest.raises(ValueError):
            cv.BarrelShape.circular(3.0, embedment_ft=3.0)


class TestCompositeN:
    def test_hds5_example(self):
        p = math.pi * 6
        assert cv.composite_n([(0.6 * p, 0.026), (0.4 * p, 0.013)]) == pytest.approx(0.021, abs=5e-4)

    @pytest.mark.parametrize("n1,n2,w", [(0.012, 0.03, 0.2), (0.024, 0.05, 0.5), (0.013, 0.013, 0.7)])
    def test_between_the_parts(self, n1, n2, w):
        nc = cv.composite_n([(w, n1), (1 - w, n2)])
        assert min(n1, n2) - 1e-12 <= nc <= max(n1, n2) + 1e-12

    def test_embedded_bed_raises_n(self):
        smooth = make("circle 6", n=0.012, embed=1.2, n_bed=0.035)
        plain = make("circle 6", n=0.012, embed=1.2)
        y = 0.5 * smooth.rise
        assert smooth.friction_slope(30, y) > plain.friction_slope(30, y)


# ── barrel depths ─────────────────────────────────────────────────────────

class TestDepths:
    @pytest.mark.parametrize("q", [5, 20, 60])
    def test_box_critical_depth_closed_form(self, q):
        c = make("box 8x5")
        dc = (q ** 2 / (cv.G * 8.0 ** 2)) ** (1 / 3)
        assert c.critical_depth(q) == pytest.approx(min(dc, 5.0), rel=1e-3)

    @pytest.mark.parametrize("shape", list(SHAPES))
    @pytest.mark.parametrize("ratio", [0.5, 1.5, 3.0])
    def test_froude_one_at_critical(self, shape, ratio):
        c = make(shape)
        q = capacity_q(c, ratio)
        dc = c.critical_depth(q)
        if dc < c.rise * 0.999:
            s = c.shape.section(dc)
            assert q ** 2 * s.top_width / (cv.G * s.area ** 3) == pytest.approx(1.0, rel=2e-2)

    @pytest.mark.parametrize("shape", list(SHAPES))
    @pytest.mark.parametrize("slope", [0.002, 0.01, 0.04])
    def test_normal_depth_carries_q(self, shape, slope):
        c = make(shape, slope=slope)
        q = capacity_q(c, 1.0)
        yn = c.normal_depth(q)
        if yn < c.rise:
            assert c._manning_q(yn, c.slope) == pytest.approx(q, rel=1e-3)

    def test_normal_depth_full_when_flat(self):
        c = make("circle 3", slope=0.0)
        assert c.normal_depth(10) == c.rise


# ── inlet control ─────────────────────────────────────────────────────────

class TestInletControl:
    @pytest.mark.parametrize("key", list(cv.INLETS))
    def test_submerged_equation_by_hand(self, key):
        shape = "box 8x5" if key.startswith(("box", "cm_box")) else "circle 6"
        c = make(shape, inlet=key)
        k = cv.INLETS[key]
        x = 5.0
        hw = c.inlet_control_hw(capacity_q(c, x))
        assert hw == pytest.approx((k.c * x * x + k.y + k.ks * c.slope) * c.rise, rel=1e-9)

    @pytest.mark.parametrize("key", list(cv.INLETS))
    def test_monotone_and_continuous(self, key):
        shape = "box 8x5" if key.startswith(("box", "cm_box")) else "circle 6"
        c = make(shape, inlet=key)
        ratios = [0.2 + 0.05 * i for i in range(120)]
        hws = [c.inlet_control_hw(capacity_q(c, r)) for r in ratios]
        assert all(b >= a - 1e-9 for a, b in zip(hws, hws[1:]))
        jumps = [b - a for a, b in zip(hws, hws[1:])]
        assert max(jumps) < 0.25 * c.rise      # no step at 3.5 or 4.0

    def test_form_two_by_hand(self):
        c = make("box 8x5", inlet="box_headwall_chamfer")
        k = cv.INLETS["box_headwall_chamfer"]
        x = 2.0
        assert c.inlet_control_hw(capacity_q(c, x)) == pytest.approx(k.k * x ** k.m * c.rise)

    @pytest.mark.parametrize("key", ["concrete_pipe_square_headwall", "cmp_mitered"])
    def test_slope_correction_is_ks_s(self, key):
        on = make("circle 6", slope=0.03, inlet=key)
        off = cv.Culvert(on.shape, length_ft=on.length, inlet_invert=on.inlet_invert, outlet_invert=on.outlet_invert,
                         n=on.n_wall, inlet=key, slope_correction=False)
        for ratio in (1.0, 5.0):
            q = capacity_q(on, ratio)
            assert on.inlet_control_hw(q) - off.inlet_control_hw(q) == pytest.approx(
                cv.INLETS[key].ks * on.slope * on.rise, abs=1e-9)

    def test_better_inlet_lowers_headwater(self):
        sq = make("circle 3", inlet="concrete_pipe_square_headwall")
        bev = make("circle 3", inlet="pipe_beveled_33_7")
        q = capacity_q(sq, 5.0)
        assert bev.inlet_control_hw(q) < sq.inlet_control_hw(q)


# ── outlet control ────────────────────────────────────────────────────────

class TestOutletControl:
    @pytest.mark.parametrize("shape", list(SHAPES))
    @pytest.mark.parametrize("ratio", [1.0, 3.0, 6.0])
    def test_submerged_outlet_is_eq_3_6b(self, shape, ratio):
        c = make(shape, length=200.0, slope=0.004, n=0.024)
        q = capacity_q(c, ratio)
        tw = c.outlet_bed + c.rise + 0.7
        hwo = c.headwater(q, tw).hw_outlet_ft
        a, p = c.shape.full.area, c.shape.full.perimeter
        v = q / a
        h = (1 + c.ke + 29.0 * c._n(c.shape.full) ** 2 * c.length / (a / p) ** 1.33) * v * v / (2 * cv.G)
        assert hwo == pytest.approx((tw - c.outlet_bed) + h - c.length * c.slope, rel=1e-9)

    @pytest.mark.parametrize("shape", list(SHAPES))
    def test_profile_agrees_with_approximation_when_running_full(self, shape):
        c = make(shape, length=250.0, slope=0.002, n=0.024)
        q = capacity_q(c, 4.5)
        prof = c.outlet_control(q, 0.0)[0]
        approx = c.outlet_control(q, 0.0, method="approximate")[0]
        assert prof > 0.75 * c.rise
        assert prof == pytest.approx(approx, rel=0.1)

    def test_zero_flow_pools_at_tailwater(self):
        c = make("circle 6", slope=0.005)
        tw = c.inlet_bed + 1.0
        assert c.headwater(0.01, tw).headwater_elev == pytest.approx(tw, abs=0.01)

    def test_steep_barrel_free_outfall_is_inlet_control(self):
        c = make("circle 3", slope=0.03, n=0.012)
        for ratio in (0.5, 1.5, 3.0):
            r = c.headwater(capacity_q(c, ratio))
            assert r.control == "inlet" and r.flow_type in (1, 5)

    def test_rougher_and_longer_raise_outlet_headwater(self):
        base = make("circle 6", length=200, slope=0.001, n=0.012)
        q = capacity_q(base, 4.0)
        h0 = base.headwater(q).hw_outlet_ft
        assert h0 > 0
        assert make("circle 6", length=200, slope=0.001, n=0.024).headwater(q).hw_outlet_ft > h0
        assert make("circle 6", length=400, slope=0.001, n=0.012).headwater(q).hw_outlet_ft > h0


# ── the culvert ───────────────────────────────────────────────────────────

class TestCulvert:
    @pytest.mark.parametrize("shape", list(SHAPES))
    @pytest.mark.parametrize("slope", [0.001, 0.01, 0.03])
    def test_headwater_monotone_in_q_and_tailwater(self, shape, slope):
        c = make(shape, slope=slope)
        qs = [capacity_q(c, r) for r in (0.3, 1, 2, 3, 4, 5, 6)]
        hws = [c.headwater(q).headwater_elev for q in qs]
        assert all(b > a for a, b in zip(hws, hws[1:]))
        q = qs[3]
        tws = [c.outlet_bed + f * c.rise for f in (0, 0.5, 1.0, 1.5)]
        hw_tw = [c.headwater(q, tw).headwater_elev for tw in tws]
        assert all(b >= a - 1e-6 for a, b in zip(hw_tw, hw_tw[1:]))

    @pytest.mark.parametrize("shape", list(SHAPES))
    @pytest.mark.parametrize("ratio", [0.8, 2.5, 5.0])
    def test_discharge_inverts_headwater(self, shape, ratio):
        c = make(shape)
        q = capacity_q(c, ratio)
        hw = c.headwater(q).headwater_elev
        assert c.discharge(hw) == pytest.approx(q, rel=2e-3)

    @pytest.mark.parametrize("n", [2, 3])
    def test_barrels_split_the_flow(self, n):
        one = make("box 8x5")
        many = make("box 8x5", barrels=n)
        q = capacity_q(one, 3.0)
        assert many.headwater(n * q).headwater_elev == pytest.approx(one.headwater(q).headwater_elev)

    def test_flow_types(self):
        c = make("circle 6", length=300, slope=0.001, n=0.024)
        assert c.headwater(capacity_q(c, 0.8)).flow_type == 2
        assert c.headwater(capacity_q(c, 5.0), c.outlet_bed + 7.0).flow_type == 4
        assert c.headwater(capacity_q(c, 5.0)).flow_type in (6, 7)


# ── roadway and crossing ──────────────────────────────────────────────────

ROAD = cv.Roadway([0, 150, 300], [108.0, 106.0, 108.0])


class TestCrossing:
    def test_weir_by_hand_flat_crest(self):
        road = cv.Roadway([0, 100], [50.0, 50.0], cd=3.0)
        assert road.overtopping(51.5) == pytest.approx(3.0 * 100 * 1.5 ** 1.5)
        assert road.overtopping(49.9) == 0.0

    def test_submergence_reduces_overtopping(self):
        free = ROAD.overtopping(107.5)
        assert ROAD.overtopping(107.5, 106.5) < free
        assert ROAD.overtopping(107.5, 107.5) == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.parametrize("q", [20, 150, 400, 900])
    def test_conservation(self, q):
        c = make("circle 3")
        x = cv.crossing([c], q, roadway=ROAD)
        assert sum(r.q_cfs for r in x.culverts) + x.q_overtopping_cfs == pytest.approx(q, rel=5e-3)
        assert x.overtopped == (x.headwater_elev > ROAD.crest_elev + 1e-3)

    def test_no_road_matches_the_culvert(self):
        c = make("circle 6")
        q = capacity_q(c, 3.0)
        assert cv.crossing([c], q).headwater_elev == pytest.approx(c.headwater(q).headwater_elev, abs=0.01)

    @pytest.mark.parametrize("q", [100, 300, 700])
    def test_each_extra_opening_lowers_headwater(self, q):
        """The permeability question: a solid embankment, one culvert, two."""
        main = make("circle 3")
        relief = make("circle 3", length=90)
        solid = cv.crossing([], q, roadway=ROAD).headwater_elev
        one = cv.crossing([main], q, roadway=ROAD).headwater_elev
        two = cv.crossing([main, relief], q, roadway=ROAD).headwater_elev
        assert solid >= one >= two

    def test_tailwater_rating_is_used(self):
        c = make("circle 6", slope=0.001, n=0.024)
        q = capacity_q(c, 3.0)
        low = cv.crossing([c], q, tailwater=c.outlet_bed).headwater_elev
        high = cv.crossing([c], q, tailwater=lambda qq: c.outlet_bed + 7.0).headwater_elev
        assert high > low

    def test_needs_an_opening_or_a_road(self):
        with pytest.raises(ValueError):
            cv.crossing([], 100)


class TestCurvesAndSystems:
    def test_performance_curve_prorates_tailwater(self):
        c = make("circle 6")
        rows = cv.performance_curve(c, 50, 150, 25, tw_min=100.0, tw_max=104.0)
        assert [round(r.q_cfs) for r in rows] == [50, 75, 100, 125, 150]
        assert rows[0].tailwater_elev == pytest.approx(100.0)
        assert rows[-1].tailwater_elev == pytest.approx(104.0)
        assert rows[2].tailwater_elev == pytest.approx(102.0)

    def test_system_passes_headwater_upstream(self):
        down = make("circle 6")
        up = cv.Culvert(cv.BarrelShape.circular(6.0), length_ft=80, inlet_invert=101.0, outlet_invert=100.8,
                        n=0.013, inlet="concrete_pipe_square_headwall")
        rows = cv.culvert_system([down, up], 150.0, tailwater_elev=99.0)
        assert rows[1].tailwater_elev == pytest.approx(rows[0].headwater_elev)
        assert rows[1].headwater_elev >= up.headwater(150.0).headwater_elev - 1e-6
