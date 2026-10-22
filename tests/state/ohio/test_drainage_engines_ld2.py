"""Property tests of the drainage engines shared by ODOT's drainage tools:
the Figure 1101-1 chart, the inlet run, the storm sewer and ditch options,
and the culvert design table / overflow helpers."""
import math

import pytest

from civilpy.state.ohio.DOT import culvert_design as cd
from civilpy.state.ohio.DOT import idf
from civilpy.state.ohio.DOT import roadway_drainage as rd


# ── Figure 1101-1 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("c", [0.15, 0.3, 0.5, 0.65, 0.9])
@pytest.mark.parametrize("slope", [0.2, 1.0, 5.0])
def test_overland_chart_moves_the_right_way(c, slope):
    t = [idf.overland_flow_chart_minutes(c, L, slope) for L in (20, 50, 100, 300, 1000)]
    assert all(b > a for a, b in zip(t, t[1:]))                         # longer slope, longer time
    assert idf.overland_flow_chart_minutes(c, 100, slope * 2) < idf.overland_flow_chart_minutes(c, 100, slope)
    if c < 0.9:
        assert idf.overland_flow_chart_minutes(c + 0.05, 100, slope) < idf.overland_flow_chart_minutes(c, 100, slope)


def test_overland_chart_reproduces_its_worked_example_and_bounds():
    assert idf.overland_flow_chart_minutes(0.5, 200, 0.2) == pytest.approx(20.0, rel=0.03)
    with pytest.raises(ValueError):
        idf.overland_flow_chart_minutes(0.95, 100, 1.0)
    assert idf.overland_flow_chart_minutes(0.5, 0, 1.0) == 0.0


@pytest.mark.parametrize("ratio", [1.8, 2.0, 2.2])
def test_overland_chart_geometry_is_a_parameter(ratio):
    """A nomograph with the slope scale midway (time_ratio 2) gives time height = 2 S - pivot."""
    ch = idf.OverlandFlowChart(length_per_decade=1.0, c_heights=((0.1, 1.0), (0.9, 2.0)), pivot_ratio=ratio,
                               slope_height_1pct=1.5, slope_fall_per_decade=0.5, time_ratio=2.0, time_height_1min=-3.0,
                               time_per_decade=2.0)
    a = math.log10(100 / 10.0)
    pivot = a + (ch.c_height(0.5) - a) * ratio
    e = 2 * 1.5 - pivot
    assert ch.minutes(0.5, 100, 1.0) == pytest.approx(10 ** ((e + 3.0) / 2.0))


@pytest.mark.parametrize("zone", idf.ZONES)
@pytest.mark.parametrize("aep", [50, 10, 1])
def test_intensity_function_is_the_figure_curve(zone, aep):
    f = idf.intensity_function(zone, aep)
    a, b, c = idf.IDF[zone][aep]
    for t in (10, 30, 90):
        assert f(t) == pytest.approx(idf.intensity(t, aep, zone))
        assert idf.idf_curve(a, b, c)(t) == pytest.approx(idf.intensity(t, aep, zone))


# ── gutters and openings ──────────────────────────────────────────────────
@pytest.mark.parametrize("w,sw,sx", [(2.0, 0.0833, 0.016), (1.5, 0.06, 0.02)])
def test_composite_area_is_continuous_and_reduces_to_straight(w, sw, sx):
    edge = w * sw
    below = rd.composite_gutter_area(edge - 1e-9, gutter_width_ft=w, sw=sw, sx=sx)
    above = rd.composite_gutter_area(edge + 1e-9, gutter_width_ft=w, sw=sw, sx=sx)
    assert below == pytest.approx(above, rel=1e-6)
    assert rd.composite_gutter_area(0.3, gutter_width_ft=w, sw=sx, sx=sx) == pytest.approx(rd.gutter_area(0.3, sx))
    q, a = 2.0, rd.gutter_area(0.25, sx)
    assert rd.gutter_travel_minutes(300, q, a) == pytest.approx(300 / (0.75 * q / a) / 60)


@pytest.mark.parametrize("a", [0.0, 0.04, 0.17])
@pytest.mark.parametrize("y", [0.05, 0.2])
def test_capture_fraction_floor_and_length(a, y):
    q = 1.0
    la = rd.opening_capture_length(q, a, y)
    assert la == pytest.approx(q / rd.capture_per_foot(a, y))
    f = [rd.side_capture_fraction(a, y, L, la) for L in (0.1 * la, 0.5 * la, la)]
    assert f[0] < f[1] < f[2] == 1.0
    assert rd.side_capture_fraction(a, y, 1e-6 * la, la, min_fraction=0.1) == pytest.approx(0.1)


@pytest.mark.parametrize("q", [0.2, 2.0, 8.0, 30.0])
def test_sag_depth_regimes_are_continuous(q):
    weir = lambda y: 3.0 * 6.0 * y ** 1.5
    orifice = lambda y: 0.67 * 2.0 * math.sqrt(64.4 * y)
    r = rd.sag_depth(q, weir_q=weir, orifice_q=orifice, weir_limit_ft=0.4, orifice_from_ft=1.4)
    d = r["depth_ft"]
    if r["regime"] == "weir":
        assert weir(d) == pytest.approx(q, rel=1e-5) and d <= 0.4
    elif r["regime"] == "orifice":
        assert orifice(d) == pytest.approx(q, rel=1e-5) and d >= 1.4
    else:
        assert 0.4 <= d <= 1.4
    bigger = rd.sag_depth(q * 1.1, weir_q=weir, orifice_q=orifice, weir_limit_ft=0.4, orifice_from_ft=1.4)
    assert bigger["depth_ft"] >= d


# ── the inlet run ─────────────────────────────────────────────────────────
CB = rd.InletBasin("grate", grate_width_ft=1.4, length_ft=2.5, open_area_sqft=1.45)
WINDOW = rd.InletBasin("window", length_ft=6.0, window_height_ft=1 / 3)


def _run(basin, *, composite=False, q=None, length=150.0, s=0.01):
    el = {"s": s, "sx": 0.016, "c": 0.9, "area_acres": 0.2, "basin": basin, "depression_ft": 0.04, "overland": None}
    if composite:
        el.update(sw=0.0833, gutter_width_ft=2.0)
    if q:
        el["q_cfs"] = q
    els = [{"kind": "start", "station_ft": 0.0}]
    for k in range(1, 4):
        els.append(dict(el, kind="inlet", station_ft=k * length, overland={"c": 0.9, "length_ft": 40.0, "slope_pct": 2.0}))
    return els


@pytest.mark.parametrize("basin", [CB, WINDOW])
@pytest.mark.parametrize("composite", [False, True])
@pytest.mark.parametrize("zone", ["A", "D"])
def test_inlet_run_conserves_flow_and_is_time_consistent(basin, composite, zone):
    i = idf.intensity_function(zone, 20)
    res = rd.analyze_inlet_run(_run(basin, composite=composite), intensity=i)
    rows = [r for r in res["rows"] if r["kind"] != "start"]
    bypass = 0.0
    for r in rows:
        assert r["bypass_in_cfs"] == pytest.approx(bypass)
        assert r["intercepted_cfs"] + r["bypass_cfs"] == pytest.approx(r["q_cfs"])
        assert r["q_cfs"] == pytest.approx(0.9 * 0.2 * i(r["time_min"]) + bypass)
        assert r["time_min"] >= 10.0 - 1e-9
        if r["tc_min"] + r["gutter_time_min"] >= 10.0:                    # the loop closed on its own time
            assert r["time_min"] == pytest.approx(r["tc_min"] + r["gutter_time_min"])
        if not r["composite"]:
            assert r["depth_ft"] == pytest.approx(rd.gutter_depth(r["q_cfs"], 0.0833 if composite else 0.016, 0.01,
                                                                  rd.GUTTER_N), rel=1e-5)
        else:
            assert r["spread_ft"] >= 2.0
        bypass = r["bypass_cfs"]


def test_a_longer_window_lets_less_by_and_entered_flow_skips_rain():
    short = rd.analyze_inlet_run(_run(WINDOW), intensity=idf.intensity_function("C", 10))
    long_ = rd.analyze_inlet_run(_run(rd.InletBasin("w", length_ft=12.0, window_height_ft=1 / 3)),
                                 intensity=idf.intensity_function("C", 10))
    assert long_["rows"][1]["bypass_cfs"] <= short["rows"][1]["bypass_cfs"]
    fixed = rd.analyze_inlet_run(_run(WINDOW, q=1.5), intensity=lambda t: 1e6)
    assert fixed["rows"][1]["q_cfs"] == pytest.approx(1.5) and fixed["rows"][1]["intensity_in_hr"] is None


@pytest.mark.parametrize("basin", [CB, WINDOW, rd.CB_6])
def test_sag_takes_both_sides(basin):
    side = {"s": 0.005, "sx": 0.016, "c": 0.9, "area_acres": 0.3, "tc_min": 10.0, "basin": basin, "depression_ft": 0.04}
    els = [{"kind": "start", "station_ft": 0.0}, dict(side, kind="sag_side", station_ft=200.0),
           {"kind": "start", "station_ft": 400.0}, dict(side, kind="sag", station_ft=200.0, gutter_length_ft=200.0)]
    res = rd.analyze_inlet_run(els, intensity=idf.intensity_function("B", 4))
    a, b = res["rows"][1], res["rows"][3]
    assert a["intercepted_cfs"] is None
    assert b["sag"]["total_cfs"] == pytest.approx(a["q_cfs"] + b["q_cfs"])
    assert b["sag"]["depth_ft"] > 0 and b["sag"]["spread_ft"] >= 0


# ── storm sewer options ───────────────────────────────────────────────────
def _chain(crowns=False, d_in=None):
    runs = []
    top = 112.0
    for k, (L, a) in enumerate([(200.0, 0.8), (250.0, 1.0), (180.0, 1.4)]):
        r = {"name": f"R{k}", "areas": [(a, 0.8)], "tc_local_min": 10.0, "length_ft": L}
        if crowns:
            r.update(crown_up_ft=top, crown_down_ft=top - 0.006 * L)
        else:
            r.update(invert_up_ft=top, invert_down_ft=top - 0.006 * L)
        if d_in:
            r["d_in"] = d_in
        runs.append(r)
        top -= 0.006 * L + 0.2
    return runs


@pytest.mark.parametrize("zone", ["A", "D"])
def test_storm_sewer_options(zone):
    sizes = tuple(range(12, 30, 3)) + tuple(range(30, 241, 6))
    i, i4 = idf.intensity_function(zone, 10), idf.intensity_function(zone, 4)
    by_zone = rd.design_storm_sewer(_chain(), zone=zone)
    by_fn = rd.design_storm_sewer(_chain(), intensity=i, check_intensity=i4)
    assert [x["q_cfs"] for x in by_zone["runs"]] == [x["q_cfs"] for x in by_fn["runs"]]
    d = rd.design_storm_sewer(_chain(crowns=True), zone=zone, sizes=sizes, start_at_upstream_size=True, round_output=False)
    prev = 0
    for r, src in zip(d["runs"], _chain(crowns=True)):
        assert r["d_in"] in sizes and r["d_in"] >= prev                 # never smaller than the pipe coming in
        assert r["invert_up_ft"] == pytest.approx(src["crown_up_ft"] - r["d_in"] / 12.0)
        assert r["capacity_cfs"] >= r["q_cfs"]
        prev = r["d_in"]
    held = rd.design_storm_sewer(_chain(d_in=10), zone=zone)
    assert all(r["d_in"] == 10 for r in held["runs"])
    assert all(any("below the 12 in minimum" in f for f in r["flags"]) for r in held["runs"])
    ohe = rd.design_storm_sewer(_chain(), zone=zone, tailwater_ft=110.5)
    old = rd.design_storm_sewer(_chain(), zone=zone, tailwater_ft=110.5, hgl_method="cdss")
    for a, b in zip(ohe["hgl"]["runs"], old["hgl"]["runs"]):
        assert a["hgl_down_ft"] >= b["hgl_down_ft"] - 1e-3              # the OHE rule never lowers a junction


@pytest.mark.parametrize("d", [12, 24, 48])
def test_full_q_ratio_switches_velocity_to_full_pipe(d):
    s = 0.004
    qf = rd.full_flow_q(d, s)
    a_full = math.pi * (d / 24) ** 2
    assert rd.mean_velocity(1.065 * qf, d, s, full_q_ratio=1.064) == pytest.approx(1.065 * qf / a_full)
    assert rd.mean_velocity(1.065 * qf, d, s) > 1.065 * qf / a_full                 # part full without the switch
    assert rd.flow_depth(1.065 * qf, d, s, full_q_ratio=1.064) == pytest.approx(d / 12)


# ── ditch options ─────────────────────────────────────────────────────────
PROG = [{"name": "seed", "n": 0.030, "allowable_lb_sqft": 0.4}, {"name": "mat", "n": 0.040, "allowable_lb_sqft": 2.0},
        {"name": "rcp", "n": 0.060, "allowable_lb_sqft": 6.0}]


@pytest.mark.parametrize("slope", [0.004, 0.03, 0.08])
@pytest.mark.parametrize("section", [None, rd.CircularChannel(3.0)])
def test_ditch_progression(slope, section):
    reach = {"length_ft": 300.0, "slope": slope, "c": 0.5, "area_acres": 4.0, "bottom_ft": 2.0, "z_left": 4.0, "z_right": 4.0}
    if section:
        reach["section"] = section
    res = rd.analyze_ditch([reach, dict(reach)], intensity={"shear": idf.intensity_function("B", 20),
                                                            "depth": idf.intensity_function("B", 10)},
                           progression=PROG, start_min=15.0)
    prev_time = {"shear": 15.0, "depth": 15.0}
    for r in res["reaches"]:
        trials = r["storms"]["shear_trials"]
        names = [t["lining"] for t in trials]
        assert names == [p["name"] for p in PROG[:len(names)]]
        for t, p in zip(trials[:-1], PROG):
            assert t["shear_lb_sqft"] > p["allowable_lb_sqft"]               # moved on only when it failed
        final = next(p for p in PROG if p["name"] == r["lining"])
        assert trials[-1]["shear_lb_sqft"] <= final["allowable_lb_sqft"] or final is PROG[-1]
        assert r["storms"]["depth"]["n"] == max(final["n"], rd.CDSS_DEPTH_N)
        for k in ("shear", "depth"):
            assert r["storms"][k]["start_min"] == pytest.approx(prev_time[k])
            prev_time[k] = r["storms"][k]["time_min"]


@pytest.mark.parametrize("r", [0.5, 2.0])
def test_circular_channel_geometry(r):
    ch = rd.CircularChannel(r)
    assert ch.area(2 * r) == pytest.approx(math.pi * r * r, rel=1e-6)
    assert ch.top_width(r) == pytest.approx(2 * r)
    assert ch.hydraulic_radius(r) == pytest.approx(r / 2)


# ── culvert design table and overflow ─────────────────────────────────────
def test_first_passing_tries_every_single_cell_first():
    assert cd.first_passing(5, lambda k, b: b == 2 or k == 4) == (4, 1)
    assert cd.first_passing(5, lambda k, b: b == 2 and k == 1) == (1, 2)
    assert cd.first_passing(3, lambda k, b: False) is None


@pytest.mark.parametrize("chosen,n", [(0, 5), (2, 5), (4, 5)])
def test_design_table_rows(chosen, n):
    rows = cd.design_table(n, chosen, lambda j, q: {"hw": j * q}, q_design_cfs=10.0, q_flood_cfs=15.0)
    codes = [r["code"] for r in rows]
    for tag in ("D", "F"):
        assert tag in codes
        assert (f"{tag}-1" in codes) == (chosen >= 1) and (f"{tag}-2" in codes) == (chosen >= 2)
        assert (f"{tag}+1" in codes) == (chosen + 1 < n)
    assert all(r["hw"] == r["size_index"] * r["q_cfs"] for r in rows)


@pytest.mark.parametrize("q", [50.0, 120.0, 300.0])
def test_overflow_is_what_the_culvert_cannot_pass(q):
    hw = lambda qq: 100.0 + 0.05 * qq                    # a rating: elevation rises with discharge
    over = cd.overflow_discharge(hw, q, 105.0)
    assert over == pytest.approx(max(q - 100.0, 0.0), abs=0.02)
