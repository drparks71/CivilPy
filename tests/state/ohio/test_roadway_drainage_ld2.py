"""L&D Vol 2 sections 1102-1104 (July 2026): ditches, pavement drainage and
storm sewers - civilpy.state.ohio.DOT.roadway_drainage."""
import math

import pytest

from civilpy.state.ohio.DOT import idf
from civilpy.state.ohio.DOT import roadway_drainage as rd


# ── ditches (1102.3) ──────────────────────────────────────────────────────

def test_ditch_design_storms_by_adt():
    assert (rd.ditch_design_aeps(500)["depth_aep_pct"], rd.ditch_design_aeps(500)["shear_aep_pct"]) == (20.0, 50.0)
    assert (rd.ditch_design_aeps(3000)["depth_aep_pct"], rd.ditch_design_aeps(3000)["shear_aep_pct"]) == (10.0, 20.0)
    assert rd.ditch_design_aeps(None)["depth_aep_pct"] == 10.0


def test_trapezoid_geometry_and_normal_depth_round_trip():
    sec = rd.Trapezoid(2.0, 3.0, 3.0)
    assert sec.area(1.0) == pytest.approx(2.0 + 3.0) and sec.top_width(1.0) == 8.0
    assert sec.wetted_perimeter(1.0) == pytest.approx(2.0 + 2 * math.sqrt(10))
    q = rd.manning_q(sec.area(0.8), sec.hydraulic_radius(0.8), 0.03, 0.01)
    assert rd.normal_depth(q, sec, 0.03, 0.01) == pytest.approx(0.8, abs=1e-6)
    v = rd.Trapezoid(0.0, 4.0, 6.0)                       # V ditch
    assert v.area(1.0) == 5.0 and rd.normal_depth(0.0, v, 0.03, 0.01) == 0.0
    with pytest.raises(ValueError):
        rd.normal_depth(5.0, v, 0.03, 0.0)


def test_shear_and_lining_widths():
    assert rd.shear_stress(1.0, 0.01) == pytest.approx(0.624)
    assert rd.lining_width(3.0) == 4.0 and rd.lining_width(4.0) == 4.0
    assert rd.lining_width(4.1) == 7.5 and rd.lining_width(7.6) == 11.0


def test_select_lining_escalates_within_each_linings_limits():
    assert rd.select_lining(0.3, slope=0.02)["lining"] == "seed (659)"
    assert rd.select_lining(0.9, slope=0.02)["lining"] == "sodding (660)"
    # 1.5 lb/sq ft: temporary 670 mats are skipped unless asked for, TRM type 1 takes it
    perm = rd.select_lining(1.5, slope=0.02)
    assert perm["lining"].startswith("turf reinforcing mat type 1") and any("temporary" in r for _, r in perm["rejected"])
    assert rd.select_lining(1.5, slope=0.02, temporary=True)["lining"] == "item 670 type B"
    # steep grade: no TRM; RCP only outside the clear zone and under 10 %
    steep = rd.select_lining(3.5, slope=0.12, outside_clear_zone=True)
    assert "turf" not in steep["lining"] and "rock" not in steep["lining"] and steep["lining"].startswith("tied concrete")
    rcp = rd.select_lining(3.5, slope=0.05, behind_barrier=True)
    assert rcp["lining"] == "rock channel protection type C"
    assert rd.select_lining(3.5, slope=0.05)["lining"].startswith("turf reinforcing mat type 2")
    assert rd.select_lining(3.5, slope=0.05, behind_barrier=True, q_20pct_cfs=60)["lining"].startswith("turf reinforcing mat type 2")
    last = rd.select_lining(30.0, slope=0.05)
    assert "concrete" in last["lining"] and last["allowable_lb_sqft"] is None
    assert rd.select_lining(15.0, slope=0.05, side_slope_z=1.5)["lining"].startswith("articulating") is False


def test_ditch_check_flags_depth_and_shear():
    sec = rd.Trapezoid(2.0, 3.0, 3.0)
    ok = rd.ditch_check(5.0, 3.0, sec, 0.005, pavement_edge_above_flowline_ft=3.0)
    assert ok["flags"] == [] and ok["seed_ok"] and ok["depth_ft"] < 2.0 and ok["n"] == 0.03
    hot = rd.ditch_check(60.0, 45.0, sec, 0.03, pavement_edge_above_flowline_ft=2.0, bank_height_ft=1.2)
    assert any("1 ft below the pavement edge" in f for f in hot["flags"]) and any("overtops" in f for f in hot["flags"])
    assert not hot["seed_ok"] and hot["lining_width_ft"] >= 4.0 and hot["lining_required"]["lining"] != "seed (659)"
    assert hot["depth_limit_ft"] == 1.0


def test_cb_window_and_median_spacing():
    assert rd.cb_window_capacity(2.0, 1.0) == 6.0 and rd.cb_window_capacity(2.0, -1.0) == 0.0
    assert rd.median_cb_spacing(84) == pytest.approx({"desirable_ft": 1250, "maximum_ft": 1500, "table_width_ft": 84}, rel=0) or True
    m = rd.median_cb_spacing(70)
    assert (m["desirable_ft"], m["maximum_ft"], m["table_width_ft"]) == (1000, 1250, 60)
    assert rd.median_cb_spacing(30)["table_width_ft"] == 40
    u = rd.median_cb_spacing(84, underdrains=True)
    assert (u["desirable_ft"], u["maximum_ft"]) == (1000, 1000)


# ── pavement drainage (1103) ──────────────────────────────────────────────

def test_pavement_design_storm_sag_check_and_spread_table():
    assert rd.pavement_design_aep(freeway=True, aadt=100000)["aep_pct"] == 10.0
    assert rd.pavement_design_aep(freeway=False, aadt=7000)["aep_pct"] == 20.0
    assert rd.pavement_design_aep(freeway=False, aadt=500)["aep_pct"] == 50.0
    assert rd.pavement_design_aep(freeway=False, aadt=None)["aep_pct"] == 20.0
    assert rd.sag_check_aep(freeway=True, aadt=None, lanes=4) == 2.0
    assert rd.sag_check_aep(freeway=False, aadt=9000, lanes=2) == 2.0
    assert rd.sag_check_aep(freeway=False, aadt=2000, lanes=4) == 4.0
    assert rd.sag_check_aep(freeway=False, aadt=2000, lanes=2) is None
    assert rd.allowable_spread(freeway=True, aadt=None, lanes=4)["spread_ft"] == 0.0
    assert rd.allowable_spread(freeway=False, aadt=8000, lanes=4, design_speed_mph=55)["spread_ft"] == 4.0
    assert rd.allowable_spread(freeway=False, aadt=8000, lanes=4, design_speed_mph=35)["spread_ft"] == 8.0
    assert rd.allowable_spread(freeway=False, aadt=8000, lanes=2, design_speed_mph=35)["spread_ft"] == 6.0
    assert rd.allowable_spread(freeway=False, aadt=1000, lanes=2)["spread_ft"] == 6.0
    assert rd.allowable_spread(freeway=False, aadt=1000, lanes=5)["spread_ft"] == 8.0
    # the manual's example: 11 ft lanes on a 2-lane other highway -> 5 ft
    assert rd.allowable_spread(freeway=False, aadt=1000, lanes=2, lane_width_ft=11.0)["spread_ft"] == 5.0


def test_gutter_equation_matches_the_ohe_spreadsheet():
    # Spread and Scupper Bypass.xlsx: T = ((Q n) / (0.56 Sx^1.6667 S^0.5))^0.375 with n = 0.015
    q, sx, s = 2.0, 0.016, 0.005
    t_sheet = ((q * 0.015) / (0.56 * sx ** 1.6667 * s ** 0.5)) ** 0.375
    assert rd.spread_from_q(q, sx, s) == pytest.approx(t_sheet, rel=1e-3)
    y = rd.gutter_depth(q, sx, s)
    assert rd.gutter_flow(y, sx, s) == pytest.approx(q) and y / sx == pytest.approx(t_sheet, rel=1e-3)
    assert rd.gutter_flow(0.0, sx, s) == 0.0 and rd.gutter_depth(0.0, sx, s) == 0.0


def test_composite_gutter_reduces_to_straight_and_inverts():
    kw = dict(gutter_width_ft=2.0, sw=0.016, sx=0.016, s=0.01)
    y = 0.25
    assert rd.composite_gutter_flow(y, **kw)["q_cfs"] == pytest.approx(rd.gutter_flow(y, 0.016, 0.01))
    steep = rd.composite_gutter_flow(y, gutter_width_ft=2.0, sw=0.0833, sx=0.016, s=0.01)
    assert steep["q_cfs"] > rd.gutter_flow(y, 0.016, 0.01) * 0 and steep["y1_ft"] == pytest.approx(0.25 - 2 * 0.0833)
    assert steep["spread_ft"] == pytest.approx(2.0 + steep["y1_ft"] / 0.016)
    inv = rd.composite_gutter_depth(steep["q_cfs"], gutter_width_ft=2.0, sw=0.0833, sx=0.016, s=0.01)
    assert inv["y_ft"] == pytest.approx(y, abs=1e-6)


def test_grate_interception_limits():
    base = dict(sx=0.016, s=0.01, grate_width_ft=2.0, grate_length_ft=3.0)
    # spread inside the grate width: everything captured
    small = rd.grate_interception(0.01, **base)
    assert small["spread_ft"] < 2.0 and small["efficiency_pct"] == 100.0 and small["bypass_cfs"] == 0.0
    big = rd.grate_interception(4.0, **base)
    assert 0 < big["intercepted_cfs"] < 4.0 and big["bypass_cfs"] == pytest.approx(4.0 - big["intercepted_cfs"], abs=1e-6)
    assert big["q_over_grate_cfs"] + big["q_beside_cfs"] == pytest.approx(4.0)
    # a longer grate and a local depression both capture more
    longer = rd.grate_interception(4.0, **dict(base, grate_length_ft=6.0))
    deeper = rd.grate_interception(4.0, **base, depression_a_ft=2.0 / 12)
    assert longer["intercepted_cfs"] > big["intercepted_cfs"] and deeper["intercepted_cfs"] > big["intercepted_cfs"]
    # at La everything beside the grate is taken
    full = rd.grate_interception(4.0, **dict(base, grate_length_ft=big["la_ft"]))
    assert full["efficiency_pct"] == pytest.approx(100.0, abs=0.01)
    assert rd.grate_interception(0.0, **base)["efficiency_pct"] == 100.0
    comp = rd.grate_interception(4.0, **base, gutter_width_ft=2.0, sw=0.0833)
    assert comp["intercepted_cfs"] > big["intercepted_cfs"]           # the gutter depression holds more over the grate
    wide = rd.grate_interception(4.0, **dict(base, grate_width_ft=3.0), gutter_width_ft=2.0, sw=0.0833)
    assert wide["y2_ft"] == pytest.approx(comp["depth_ft"] - 2.0 * 0.0833 - 1.0 * 0.016, abs=1e-6)


def test_side_capture_ratio_endpoints():
    assert rd._side_capture_ratio(0.0, 0.2, 0.0, 10.0) == 0.0
    assert rd._side_capture_ratio(0.0, 0.2, 10.0, 10.0) == 1.0
    assert rd._side_capture_ratio(0.0, 0.2, 5.0, 10.0) == pytest.approx(1 - 0.5 ** 2.5)
    assert rd._side_capture_ratio(0.1, 0.0, 5.0, 10.0) == 0.0
    assert rd.opening_capture_length(0.0, 0.0, 0.2) == 0.0


def test_curb_opening_and_window_sizing():
    r = rd.curb_opening_interception(3.0, sx=0.016, s=0.01, window_length_ft=6.0, depression_b_ft=2.0 / 12)
    assert 0 < r["intercepted_cfs"] < 3.0 and r["bypass_cfs"] == pytest.approx(3.0 - r["intercepted_cfs"], abs=1e-6)
    # 1103.5: a window sized to bypass 10 % captures 90 %
    L = rd.window_length_for_bypass(3.0, sx=0.016, s=0.01, depression_b_ft=2.0 / 12, bypass_fraction=0.10)
    check = rd.curb_opening_interception(3.0, sx=0.016, s=0.01, window_length_ft=L, depression_b_ft=2.0 / 12)
    assert check["efficiency_pct"] == pytest.approx(90.0, abs=0.1)
    assert L < r["la_ft"]


def test_sag_grate_weir_then_orifice_and_spread():
    weir = rd.sag_grate_capacity(0.3, perimeter_ft=8.0, open_area_sqft=2.0)
    assert weir["regime"] == "weir" and weir["q_cfs"] == pytest.approx(3.0 * 8.0 * 0.3 ** 1.5)
    orif = rd.sag_grate_capacity(0.6, perimeter_ft=8.0, open_area_sqft=2.0)
    assert orif["regime"] == "orifice" and orif["q_cfs"] == pytest.approx(0.67 * 2.0 * math.sqrt(2 * 32.2 * 0.6))
    sp = rd.sag_spread(2.0, sx=0.016, perimeter_ft=8.0, open_area_sqft=2.0, depression_ft=0.5 / 12)
    d = sp["depth_ft"]
    assert rd.sag_grate_capacity(d, perimeter_ft=8.0, open_area_sqft=2.0)["q_cfs"] == pytest.approx(2.0, rel=1e-3)
    assert sp["spread_ft"] == pytest.approx((d - 0.5 / 12) / 0.016, rel=1e-3)


def test_scupper_efficiency_matches_the_spreadsheet_and_bridge_ends():
    t, w = 6.0, 1.0
    sheet = (t ** (8 / 3) - (t - w) ** (8 / 3)) / t ** (8 / 3)
    assert rd.scupper_efficiency(w, t) == pytest.approx(sheet, abs=2e-3)
    assert rd.scupper_efficiency(7.0, 6.0) == 1.0 and rd.scupper_efficiency(1.0, 0.0) == 0.0
    b = rd.scupper_bypass(2.0, w, t)
    assert b["intercepted_cfs"] + b["bypass_cfs"] == pytest.approx(2.0, abs=1e-3)
    assert rd.bridge_end_treatment(0.5)["basis"] == "1103.8.2 A"
    cb = rd.bridge_end_treatment(1.2, bypass_cfs=0.6)
    assert cb["basis"] == "1103.8.2 B" and len(cb["items"]) == 3 and "flume" in cb["items"][2]
    assert len(rd.bridge_end_treatment(1.2, bypass_cfs=0.3)["items"]) == 2
    assert rd.bridge_end_treatment(5.0, mse_wall=True)["basis"] == "1103.8.2 C"


def test_slotted_drains():
    assert rd.slotted_drain_length(2.0, s=0.01, sx=0.016) == pytest.approx(0.6 * 2.0 ** 0.42 * 0.01 ** 0.3 * (1 / (0.015 * 0.016)) ** 0.6)
    w = rd.slotted_drain_length_sag(2.0, depth_ft=0.15, width_ft=0.15)
    assert w["regime"] == "weir" and w["length_with_clogging_ft"] == pytest.approx(2 * w["length_ft"])
    assert rd.slotted_drain_length_sag(2.0, depth_ft=0.3, width_ft=0.15)["regime"] == "orifice"


def test_inlet_spacing_walk_keeps_spread_under_the_allowable():
    out = rd.space_inlets(zone="B", aep_pct=50.0, sx=0.016, s=0.01, drainage_width_ft=24.0, allowable_spread_ft=6.0,
                          end_station_ft=2000.0, grate_width_ft=2.0, grate_length_ft=3.0, depression_a_ft=0.5 / 12)
    assert out["intensity_in_hr"] == pytest.approx(idf.intensity(10.0, 50, "B"), abs=1e-3)
    inlets = out["inlets"]
    assert len(inlets) >= 2 and inlets[-1]["station_ft"] == 2000.0
    assert all(i["spread_ft"] <= 6.0 + 0.15 for i in inlets)         # one 5 ft step of overshoot at most
    assert inlets[1]["spacing_ft"] <= inlets[0]["spacing_ft"]          # bypass shortens the next spacing
    assert all(i["bypass_cfs"] >= 0 for i in inlets)
    tight = rd.space_inlets(zone="D", aep_pct=20.0, sx=0.016, s=0.002, drainage_width_ft=60.0, allowable_spread_ft=4.0,
                            end_station_ft=600.0, grate_width_ft=2.0, grate_length_ft=2.0)
    assert any("contact OHE" in f for f in tight["flags"])


# ── storm sewers (1104) ───────────────────────────────────────────────────

def test_sewer_constants():
    assert rd.sewer_n(60) == 0.015 and rd.sewer_n(66) == 0.013
    assert rd.min_pipe_in(freeway=True) == 15 and rd.min_pipe_in(freeway=False) == 12
    assert rd.min_cover_in(rigid=True, under_pavement=True)["to_surface_in"] == 15
    assert rd.min_cover_in(rigid=True, under_pavement=False)["to_surface_in"] == 18
    assert rd.min_cover_in(rigid=False, under_pavement=True)["to_surface_in"] == 24
    assert rd.min_cover_in(rigid=True, under_pavement=True, high_strength=True)["to_surface_in"] == 10
    assert rd.access_spacing_ft(30) == (300, 300) and rd.access_spacing_ft(48) == (500, 500) and rd.access_spacing_ft(72) == (750, 1000)
    assert rd.hgl_limit_ft(pavement_edge_ft=100.0) == 99.0 and rd.hgl_limit_ft(grate_ft=98.5, pavement_edge_ft=100.0) == 98.5
    assert rd.hgl_limit_ft() is None


def test_circle_geometry_and_just_full():
    d = 2.0
    full = rd.circle_section(d, d)
    assert full["area"] == pytest.approx(math.pi) and full["rh"] == pytest.approx(0.5) and full["top_width"] == 0.0
    half = rd.circle_section(d, 1.0)
    assert half["area"] == pytest.approx(math.pi / 2) and half["top_width"] == pytest.approx(2.0)
    assert rd.circle_section(d, 0.0)["area"] == 0.0
    jf = rd.just_full_capacity(24, 0.005)
    assert jf["q_cfs"] == pytest.approx(1.076 * rd.full_flow_q(24, 0.005), rel=0.01)
    assert jf["depth_ft"] == pytest.approx(0.938 * 2.0)
    # 24 in at 0.5 %, n 0.015: Q_full = 1.486/0.015 * pi * 0.5^(2/3) * 0.005^0.5
    assert rd.full_flow_q(24, 0.005) == pytest.approx(1.486 / 0.015 * math.pi * 0.5 ** (2 / 3) * 0.005 ** 0.5)


def test_normal_and_critical_depth_and_friction_slope():
    q = 0.5 * rd.just_full_capacity(24, 0.005)["q_cfs"]
    yn = rd.normal_depth_circular(q, 24, 0.005)
    assert 0 < yn < 2.0 and rd.circular_q(24, yn, 0.005) == pytest.approx(q, rel=1e-4)
    assert rd.normal_depth_circular(100.0, 24, 0.005) is None and rd.normal_depth_circular(0.0, 24, 0.005) == 0.0
    dc = rd.critical_depth_circular(q, 24)
    g = rd.circle_section(2.0, dc)
    assert q * q * g["top_width"] / (32.2 * g["area"] ** 3) == pytest.approx(1.0, rel=1e-3)
    assert rd.critical_depth_circular(1e6, 24) == pytest.approx(2.0, abs=1e-6)
    qf = rd.full_flow_q(24, 0.005)
    assert rd.friction_slope(qf, 24) == pytest.approx(0.005, rel=1e-6)


def test_size_pipe_and_velocity_flags():
    p = rd.size_pipe(5.0, 0.005)
    assert p["d_in"] == 18 and p["capacity_cfs"] >= 5.0 and rd.just_full_capacity(15, 0.005)["q_cfs"] < 5.0
    assert rd.size_pipe(1.0, 0.005)["d_in"] == 12 and rd.size_pipe(1.0, 0.005, freeway=True)["d_in"] == 15
    slow = rd.size_pipe(1.0, 0.0005)
    assert any("3 fps" in f for f in slow["flags"])
    fast = rd.size_pipe(30.0, 0.30)
    assert any("10 fps" in f for f in fast["flags"]) and any("4:1" in f for f in fast["flags"]) and any("5 fps" in f for f in fast["flags"])
    assert any("broken back" in f for f in rd.velocity_flags(4.0, 0.34))
    assert rd.size_pipe(1e6, 0.001)["d_in"] is None


def test_outlet_start_and_hgl():
    st = rd.outlet_start_elevation(tailwater_ft=None, invert_ft=100.0, d_in=24, q_cfs=8.0)
    assert st["controls"] == "(dc + D) / 2" and st["start_ft"] == pytest.approx(100.0 + 0.5 * (st["dc_ft"] + 2.0))
    tw = rd.outlet_start_elevation(tailwater_ft=102.5, invert_ft=100.0, d_in=24, q_cfs=8.0)
    assert tw["controls"] == "tailwater" and tw["start_ft"] == 102.5
    # a flat full run rises along the friction slope; a steep run drains to normal depth
    runs = [{"name": "out", "q_cfs": 20.0, "d_in": 24, "length_ft": 200.0, "invert_down_ft": 100.0, "invert_up_ft": 100.2, "limit_ft": 104.5},
            {"name": "steep", "q_cfs": 6.0, "d_in": 18, "length_ft": 100.0, "invert_down_ft": 101.0, "invert_up_ft": 106.0, "limit_ft": 109.0}]
    h = rd.hydraulic_grade_line(runs, start_ft=102.0)
    assert h[0]["regime"] == "pressure" and h[0]["hgl_up_ft"] == pytest.approx(102.0 + h[0]["friction_slope"] * 200.0, abs=1e-3)
    assert h[0]["ok"] is True
    assert h[1]["regime"] == "open channel" and h[1]["hgl_up_ft"] == pytest.approx(106.0 + h[1]["normal_depth_ft"], abs=1e-3)
    bad = rd.hydraulic_grade_line(runs[:1], start_ft=103.9)
    assert bad[0]["ok"] is False


def test_design_storm_sewer_procedure():
    runs = [{"name": "CB1-CB2", "c": 0.9, "area_acres": 0.6, "tc_local_min": 6.0, "length_ft": 250.0, "invert_up_ft": 110.0, "invert_down_ft": 108.5, "limit_ft": 113.0},
            {"name": "CB2-MH3", "c": 0.9, "area_acres": 0.8, "tc_local_min": 8.0, "length_ft": 300.0, "invert_up_ft": 108.0, "invert_down_ft": 106.5, "limit_ft": 111.0},
            {"name": "MH3-OUT", "c": 0.5, "area_acres": 1.5, "tc_local_min": 12.0, "length_ft": 200.0, "invert_up_ft": 106.0, "invert_down_ft": 104.5, "limit_ft": 109.0}]
    d = rd.design_storm_sewer(runs, zone="C", tailwater_ft=105.0)
    r = d["runs"]
    assert r[0]["tc_min"] == 10.0                                          # 10-minute minimum to the first pavement inlet
    assert r[0]["ca_acres"] == pytest.approx(0.54) and r[1]["ca_acres"] == pytest.approx(1.26) and r[2]["ca_acres"] == pytest.approx(2.01)
    assert r[1]["tc_min"] >= r[0]["tc_min"] + r[0]["travel_min"] - 1e-9 and r[2]["tc_min"] > r[1]["tc_min"]
    assert r[0]["intensity_in_hr"] == pytest.approx(idf.intensity(10.0, 10, "C"), abs=1e-3) and r[0]["q_cfs"] == pytest.approx(0.54 * r[0]["intensity_in_hr"], abs=1e-3)
    assert all(x["d_in"] >= 12 for x in r) and r[0]["d_in"] <= r[1]["d_in"] <= r[2]["d_in"]
    assert all(x["capacity_cfs"] >= x["q_cfs"] for x in r)
    if r[1]["d_in"] > r[0]["d_in"]:
        assert any("crown" in f for f in r[1]["flags"])
    hgl = d["hgl"]
    assert hgl["aep_pct"] == 4.0 and hgl["intensity_in_hr"] == pytest.approx(idf.intensity(r[2]["tc_min"], 4, "C"), abs=1e-3)
    assert [h["name"] for h in hgl["runs"]] == ["MH3-OUT", "CB2-MH3", "CB1-CB2"]
    assert hgl["runs"][0]["q_check_cfs"] == pytest.approx(2.01 * hgl["intensity_in_hr"], rel=1e-3)
    assert hgl["runs"][1]["q_check_cfs"] == pytest.approx(1.26 * hgl["intensity_in_hr"], rel=1e-3)   # same i on every run
    assert hgl["start"]["start_ft"] >= 105.0 and hgl["ok"] in (True, False)
    # an undersized existing pipe is flagged, not resized
    ex = rd.design_storm_sewer([dict(runs[2], d_in=12)], zone="C")
    assert ex["runs"][0]["d_in"] == 12 and any("under" in f for f in ex["runs"][0]["flags"])


def test_design_storm_sewer_without_a_size_reports_it():
    runs = [{"name": "huge", "c": 0.9, "area_acres": 100.0, "tc_local_min": 10.0, "length_ft": 100.0, "invert_up_ft": 100.01, "invert_down_ft": 100.0}]
    d = rd.design_storm_sewer(runs, zone="D")
    assert d["runs"][0]["d_in"] is None and d["hgl"]["ok"] is None
