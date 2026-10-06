#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.DOT.odot_concrete_slab_generator`.

Covers the ODOT standard slab-bridge lookup (``get_deck_parameters``) against
the values tabulated in :mod:`civilpy.state.ohio.DOT.bridge`, the ACI 318-14
hook geometry (Table 25.3.2 bend diameters, 25.3.1 hook extensions), and the
A-bar generator both outside Rhino (returns ``None``) and against a stub
``Rhino.Geometry`` namespace so the hook/leg/arc coordinates can be checked
by hand.
"""

import json
import math
import sys
import types

import pytest

from civilpy.state.ohio.DOT import odot_concrete_slab_generator as gen
from civilpy.state.ohio.DOT.bridge import continuous_concrete_slab, simple_concrete_slab


# --------------------------------------------------------------------------- #
# get_deck_parameters
# --------------------------------------------------------------------------- #

class TestGetDeckParametersSimple:
    def test_11ft_simple_over_side_drainage_matches_table(self):
        p = gen.get_deck_parameters(11)
        assert p["bridge_type"] == "simple"
        assert p["edge_type"] == "over_side_drainage"
        assert p["span_length"] == 11
        assert p["thickness"] == 11.25
        assert p["top_cover"] == 2.0  # module's general ODOT top cover
        # Main bars: #7 @ 6" transverse, #5 @ 12" B, #5 @ 10" M, #5 @ 12" N
        assert (p["a_bar_size"], p["a_bar_spacing"]) == (7, 6)
        assert (p["b_bar_size"], p["b_bar_spacing"]) == (5, 12)
        assert (p["m_bar_size"], p["m_bar_spacing"]) == (5, 10)
        assert (p["n_bar_size"], p["n_bar_spacing"]) == (5, 12)
        # Edge (over-the-side drainage) column of the table
        assert p["edge_d"] == 20.0
        assert p["edge_x"] == 45
        assert (p["d_bar_size"], p["d_bar_num"]) == (7, 8)
        # Parapet-only bars are absent for a drainage edge -> default 0
        assert (p["e_bar_size"], p["e_bar_num"]) == (0, 0)

    def test_11ft_simple_parapet_edge(self):
        p = gen.get_deck_parameters(11, over_side_drainage=False)
        assert p["edge_type"] == "parapet"
        assert p["edge_d"] == 18.0
        assert p["edge_x"] == 57
        assert (p["e_bar_size"], p["e_bar_num"]) == (7, 8)
        assert (p["d_bar_size"], p["d_bar_num"]) == (0, 0)

    def test_38ft_simple_is_last_row(self):
        p = gen.get_deck_parameters(38, over_side_drainage=False)
        assert p["thickness"] == 26.0
        assert (p["a_bar_size"], p["a_bar_spacing"]) == (10, 7)
        assert p["edge_x"] == 63
        assert (p["e_bar_size"], p["e_bar_num"]) == (10, 12)

    def test_simple_has_no_continuous_only_keys(self):
        p = gen.get_deck_parameters(20)
        for key in ("a_bar_a", "a_bar_length", "u_bar_lap", "c_bar_size",
                    "f_bar_size", "m_bar_no"):
            assert key not in p

    @pytest.mark.parametrize("span", sorted(simple_concrete_slab))
    def test_every_simple_row_round_trips(self, span):
        row = simple_concrete_slab[span]
        p = gen.get_deck_parameters(span)
        assert p["thickness"] == row["thickness"]
        assert p["a_bar_size"] == row["a_bar"]["size"]
        assert p["n_bar_spacing"] == row["n_bar"]["spacing"]
        assert p["edge_d"] == row["over_side_drainage"]["d"]

    def test_out_of_range_span_lists_available_range(self):
        with pytest.raises(ValueError, match=r"Span length 10 ft not available\. Available spans: 11-38 ft"):
            gen.get_deck_parameters(10)
        with pytest.raises(ValueError, match="39"):
            gen.get_deck_parameters(39)


class TestGetDeckParametersContinuous:
    def test_14ft_continuous_over_side_drainage(self):
        p = gen.get_deck_parameters(14, continuous_span=True)
        assert p["bridge_type"] == "continuous"
        assert p["thickness"] == 11
        assert (p["a_bar_size"], p["a_bar_spacing"]) == (8, 7)
        assert p["a_bar_a"] == 16.583
        assert p["a_bar_length"] == 17.5
        assert p["b_bar_length"] == 21.5
        assert (p["m_bar_size"], p["m_bar_spacing"], p["m_bar_no"]) == (4, 12, 47)
        assert (p["n_bar_size"], p["n_bar_spacing"], p["n_bar_no"]) == (6, 15, 47)
        assert (p["c_bar_size"], p["c_bar_spacing"], p["c_bar_length"]) == (5, 7, 7.5)
        assert (p["d_bar_size"], p["d_bar_spacing"], p["d_bar_length"]) == (8, 7, 21.167)
        assert (p["e_bar_size"], p["e_bar_spacing"], p["e_bar_length"]) == (0, 0, 0.0)
        assert p["u_bar_lap"] == 78
        assert (p["edge_d"], p["edge_x"]) == (20, 45)
        # F..K edge bars
        assert (p["f_bar_size"], p["f_bar_no"], p["f_bar_length"]) == (8, 7, 17.5)
        assert p["f_bar_f"] == 16.583
        assert (p["g_bar_size"], p["g_bar_no"], p["g_bar_length"]) == (8, 7, 21.5)
        assert (p["h_bar_size"], p["h_bar_no"], p["h_bar_length"]) == (5, 7, 7.5)
        assert (p["j_bar_size"], p["j_bar_no"], p["j_bar_length"]) == (8, 7, 21.167)
        assert (p["k_bar_size"], p["k_bar_no"], p["k_bar_length"]) == (0, 0, 0)

    def test_14ft_continuous_parapet_edge_differs_only_in_edge_block(self):
        d = gen.get_deck_parameters(14, continuous_span=True, over_side_drainage=True)
        p = gen.get_deck_parameters(14, continuous_span=True, over_side_drainage=False)
        assert p["edge_type"] == "parapet"
        assert (p["edge_d"], p["edge_x"]) == (18, 60)
        assert p["f_bar_no"] == 9 and d["f_bar_no"] == 7
        assert p["j_bar_no"] == 7  # j count is the same in both columns for 14 ft
        for key in ("thickness", "a_bar_a", "u_bar_lap", "m_bar_no", "c_bar_length"):
            assert p[key] == d[key]

    def test_46ft_continuous_is_last_row(self):
        p = gen.get_deck_parameters(46, continuous_span=True, over_side_drainage=False)
        assert p["thickness"] == 27
        assert p["a_bar_a"] == 49.083
        assert p["u_bar_lap"] == 244
        assert p["edge_x"] == 69
        assert (p["k_bar_size"], p["k_bar_no"], p["k_bar_length"]) == (5, 15, 20.667)
        assert p["m_bar_no"] == 151

    def test_f_bar_f_only_emitted_for_f_bar(self):
        p = gen.get_deck_parameters(20, continuous_span=True)
        assert "f_bar_f" in p
        for letter in "ghjk":
            assert f"{letter}_bar_f" not in p

    def test_continuous_range_error_message(self):
        with pytest.raises(ValueError, match="Available spans: 14-46 ft"):
            gen.get_deck_parameters(13, continuous_span=True)

    @pytest.mark.parametrize("span", sorted(continuous_concrete_slab))
    def test_every_continuous_row_round_trips(self, span):
        row = continuous_concrete_slab[span]
        p = gen.get_deck_parameters(span, continuous_span=True)
        assert p["thickness"] == row["thickness"]
        assert p["u_bar_lap"] == row["u_bar_lap"]
        assert p["f_bar_f"] == row["over_side_drainage"]["f_bar"]["f"]
        assert p["a_bar_a"] == row["a_bar"]["a"]


# --------------------------------------------------------------------------- #
# print_parameters
# --------------------------------------------------------------------------- #

def test_print_parameters_formats_header_and_bars(capsys):
    gen.print_parameters(gen.get_deck_parameters(11))
    out = capsys.readouterr().out
    assert "Bridge Deck Parameters - SIMPLE SPAN" in out
    assert "Edge Type: Over Side Drainage" in out
    assert "Span Length:              11 ft" in out
    assert "Deck Thickness:           11.25 in" in out
    assert "Concrete Cover:           2.0 in" in out
    assert 'Transverse (A) Bar:     #7 @ 6" o.c.' in out
    assert 'Transverse (B) Bar:     #5 @ 12" o.c.' in out
    assert 'Longitudinal (M) Bar:   #5 @ 10" o.c.' in out
    assert 'Longitudinal (N) Bar:   #5 @ 12" o.c.' in out
    assert out.count("=" * 60) == 3


def test_print_parameters_continuous_parapet_header(capsys):
    gen.print_parameters(gen.get_deck_parameters(20, True, False))
    out = capsys.readouterr().out
    assert "CONTINUOUS SPAN" in out
    assert "Edge Type: Parapet" in out


# --------------------------------------------------------------------------- #
# get_aci_bend_radius
# --------------------------------------------------------------------------- #

class TestAciBendRadius:
    """ACI 318-14 Table 25.3.2 groups bars #3-#8 (6db), #9-#11 (8db), #14/#18 (10db)."""

    def test_centerline_is_inside_radius_plus_half_bar(self):
        # #8: db = 1.0"; inside value 6db = 6.0; centerline = 6.0 + 0.5
        assert gen.get_aci_bend_radius(8) == pytest.approx(6.5)
        # #9: db = 1.125"; 8db = 9.0; + 0.5625
        assert gen.get_aci_bend_radius(9) == pytest.approx(9.5625)
        # #14: db = 1.75"; 10db = 17.5; + 0.875
        assert gen.get_aci_bend_radius(14) == pytest.approx(18.375)

    @pytest.mark.parametrize("size, mult", [
        (3, 6), (5, 6), (8, 6), (9, 8), (11, 8), (14, 10), (18, 10),
        (2, 6),   # below #3 falls back to the small-bar multiplier
        (12, 6),  # non-standard sizes between groups also fall back
    ])
    def test_group_multiplier(self, size, mult):
        db = size / 8.0
        assert gen.get_aci_bend_radius(size) == pytest.approx(mult * db + 0.5 * db)

    def test_monotonic_in_bar_size(self):
        radii = [gen.get_aci_bend_radius(s) for s in (3, 4, 5, 6, 7, 8, 9, 10, 11)]
        assert radii == sorted(radii)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: ACI 318-14 Table 25.3.2 tabulates minimum inside bend *diameters* "
        "(6db for #3-#8) but get_aci_bend_radius uses 6db as the inside *radius*; "
        "centerline radius for a #8 should be 3.0 + 0.5 = 3.5 in, not 6.5 in"))
    def test_aci_table_values_are_diameters_not_radii(self):
        assert gen.get_aci_bend_radius(8) == pytest.approx(3.5)
        assert gen.get_aci_bend_radius(9) == pytest.approx(4.5 + 0.5625)
        assert gen.get_aci_bend_radius(14) == pytest.approx(8.75 + 0.875)


# --------------------------------------------------------------------------- #
# generate_a_bars  -- outside Rhino
# --------------------------------------------------------------------------- #

@pytest.fixture
def no_rhino(monkeypatch):
    """Guarantee ``import Rhino.Geometry`` raises ImportError."""
    monkeypatch.setitem(sys.modules, "Rhino", None)
    monkeypatch.delitem(sys.modules, "Rhino.Geometry", raising=False)


def test_generate_a_bars_returns_none_without_rhino(no_rhino, capsys):
    # #7 in a 20" slab: hook top = 1.9375 + 2*5.6875 = 13.3125 < 18.0 -> no warning
    assert gen.generate_a_bars(20, 7, 6, 20.0) is None
    assert capsys.readouterr().out == ""


def test_hook_clearance_warning_when_hook_exceeds_top_cover(no_rhino, capsys):
    # #10 (8db group) in an 11.25" slab: r = 8*1.25 + 0.625 = 10.625;
    # elev = 1.5 + 0.625 = 2.125; hook top = 2.125 + 2*10.625 = 23.375
    # > 11.25 - 2.0 = 9.25 -> warn
    gen.generate_a_bars(11, 10, 7, 11.25)
    out = capsys.readouterr().out
    assert 'A-Bar 180-deg hook top (23.38")' in out
    assert 'clearance ends at 9.25" from bottom' in out
    assert 'in 11.25" slab' in out


def test_no_warning_when_hook_fits(no_rhino, capsys):
    # #4 in a 26" slab: r = 3.0 + 0.25 = 3.25; elev = 1.75; top = 8.25 < 24
    gen.generate_a_bars(38, 4, 6, 26.0)
    assert capsys.readouterr().out == ""


def test_warning_uses_supplied_covers(no_rhino, capsys):
    # #5: r = 3.75 + 0.3125 = 4.0625; elev = 1.0 + 0.3125 = 1.3125; top = 9.4375
    # slab clear = 10.0 - 1.0 = 9.0 -> warn (would not warn with 2.0" bot cover? no: elev 2.3125 -> 10.4375)
    gen.generate_a_bars(12, 5, 6, 10.0, bot_cover=1.0, top_cover=1.0)
    out = capsys.readouterr().out
    assert 'hook top (9.44")' in out and 'ends at 9.00"' in out


# --------------------------------------------------------------------------- #
# generate_a_bars  -- with a stub Rhino.Geometry
# --------------------------------------------------------------------------- #

class _Pt:
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def xyz(self):
        return (self.X, self.Y, self.Z)


class _Vec(_Pt):
    pass


class _Line:
    kind = "line"
    IsValid = True

    def __init__(self, a, b):
        self.a, self.b = a, b

    def length(self):
        return math.dist(self.a.xyz(), self.b.xyz())


class _Plane:
    def __init__(self, origin, xaxis, yaxis):
        self.origin, self.xaxis, self.yaxis = origin, xaxis, yaxis


class _Nurbs:
    kind = "arc"
    IsValid = True

    def __init__(self, arc):
        self.arc = arc


class _Arc:
    def __init__(self, plane, radius, angle):
        self.plane, self.radius, self.angle = plane, radius, angle

    def ToNurbsCurve(self):
        return _Nurbs(self)

    def start(self):
        o, x = self.plane.origin, self.plane.xaxis
        return (o.X + self.radius * x.X, o.Y + self.radius * x.Y, o.Z + self.radius * x.Z)

    def end(self):
        # quarter arc: end = center + r * yaxis
        o, y = self.plane.origin, self.plane.yaxis
        return (o.X + self.radius * y.X, o.Y + self.radius * y.Y, o.Z + self.radius * y.Z)


class _PolyCurve:
    def __init__(self):
        self.segments = []

    def Append(self, c):
        self.segments.append(c)


@pytest.fixture
def stub_rhino(monkeypatch):
    rg = types.ModuleType("Rhino.Geometry")
    rg.Point3d, rg.Vector3d, rg.LineCurve = _Pt, _Vec, _Line
    rg.Plane, rg.Arc, rg.PolyCurve = _Plane, _Arc, _PolyCurve
    rhino = types.ModuleType("Rhino")
    rhino.Geometry = rg
    monkeypatch.setitem(sys.modules, "Rhino", rhino)
    monkeypatch.setitem(sys.modules, "Rhino.Geometry", rg)
    return rg


def _bars_by_y(curves):
    out = {}
    for c in curves:
        y = c.a.Y if c.kind == "line" else c.arc.plane.origin.Y
        out.setdefault(y, []).append(c)
    return out


def test_bar_count_and_spacing(stub_rhino):
    # 24 ft deck = 288 in; #7 @ 6" -> int(288/6) + 1 = 49 bars at y = 0, 6, ..., 288
    curves = gen.generate_a_bars(20, 7, 6, 14.0, deck_width=24.0)
    by_y = _bars_by_y(curves)
    assert len(by_y) == 49
    assert sorted(by_y) == [6.0 * i for i in range(49)]
    # 10 ft deck @ 7": int(120/7) + 1 = 18
    assert len(_bars_by_y(gen.generate_a_bars(20, 8, 7, 14.0, deck_width=10.0))) == 18


def test_single_bar_hook_geometry_hand_check(stub_rhino):
    """#7 bar, 20 ft span, 1.5" bottom cover.

    db = 0.875; r(centerline) = 6*0.875 + 0.4375 = 5.6875
    z (bar centerline) = 1.5 + 0.4375 = 1.9375;  L = 240
    hook extension = max(4*0.875, 2.5) = 3.5
    """
    r, z, L, ext = 5.6875, 1.9375, 240.0, 3.5
    curves = gen.generate_a_bars(20, 7, 6, 14.0, deck_width=0.0)  # one bar at y = 0
    assert len(_bars_by_y(curves)) == 1
    lines = [c for c in curves if c.kind == "line"]
    arcs = [c.arc for c in curves if c.kind == "arc"]

    # Four quarter arcs of the centerline radius
    assert len(arcs) == 4
    assert all(a.radius == pytest.approx(r) and a.angle == pytest.approx(math.pi / 2) for a in arcs)
    centers = sorted(a.plane.origin.xyz() for a in arcs)
    assert centers == [(r, 0.0, z + r), (r, 0.0, z + r), (L - r, 0.0, z + r), (L - r, 0.0, z + r)]

    endpoints = {tuple(round(v, 6) for v in c.a.xyz()) + tuple(round(v, 6) for v in c.b.xyz())
                 for c in lines}
    # Bottom straight runs between the two bottom arcs at the bar centerline
    assert (r, 0.0, z, L - r, 0.0, z) in endpoints
    # Vertical legs, one each end, from arc center height down to the bar centerline
    assert (r, 0.0, z + r, r, 0.0, z) in endpoints
    assert (L - r, 0.0, z + r, L - r, 0.0, z) in endpoints
    # Hook returns sit at z + 2r (top of the "U") and run toward mid-span by `ext`
    assert (ext, 0.0, z + 2 * r, r, 0.0, z + 2 * r) in endpoints
    assert (L - r, 0.0, z + 2 * r, L - ext, 0.0, z + 2 * r) in endpoints
    # Top of the U sits 2r above the bar centerline for every arc end
    assert max(c.a.Z for c in lines) == pytest.approx(z + 2 * r)


def test_arc_quadrants_connect_legs_and_returns(stub_rhino):
    r, z, L = 5.6875, 1.9375, 240.0
    curves = gen.generate_a_bars(20, 7, 6, 14.0, deck_width=0.0)
    arcs = [c.arc for c in curves if c.kind == "arc"]
    starts = sorted(a.start() for a in arcs)
    ends = sorted(a.end() for a in arcs)
    # Left arcs start on the x = 0 face, right arcs on x = L; ends land on the
    # vertical-leg x (= r or L - r) at the top (z + 2r) or bottom (z) of the U.
    assert starts == [(0.0, 0.0, z + r), (0.0, 0.0, z + r), (L, 0.0, z + r), (L, 0.0, z + r)]
    assert ends == [(r, 0.0, z), (r, 0.0, z + 2 * r), (L - r, 0.0, z), (L - r, 0.0, z + 2 * r)]


def test_hook_extension_floor_is_2_5_inches(stub_rhino):
    # #4: 4db = 2.0 < 2.5 -> extension 2.5 (ACI 318-14 25.3.1 180-deg hook)
    r = 6 * 0.5 + 0.25
    z = 1.5 + 0.25
    curves = gen.generate_a_bars(10, 4, 6, 12.0, deck_width=0.0)
    tops = [c for c in curves if c.kind == "line" and c.a.Z == pytest.approx(z + 2 * r)]
    xs = sorted({round(c.a.X, 6) for c in tops} | {round(c.b.X, 6) for c in tops})
    assert 2.5 in xs and 120.0 - 2.5 in xs


def test_bars_follow_deck_width_and_spacing_in_y(stub_rhino):
    curves = gen.generate_a_bars(15, 6, 8, 12.0, deck_width=2.0)  # 24 in / 8 -> 4 bars
    ys = sorted(_bars_by_y(curves))
    assert ys == [0.0, 8.0, 16.0, 24.0]
    # every segment of a given bar shares that bar's y
    for y, segs in _bars_by_y(curves).items():
        for c in segs:
            if c.kind == "line":
                assert c.a.Y == c.b.Y == y


def test_rhino_runtime_error_is_reported_and_returns_none(stub_rhino, capsys):
    class Boom(_PolyCurve):
        def Append(self, c):
            raise RuntimeError("segment rejected")

    stub_rhino.PolyCurve = Boom
    assert gen.generate_a_bars(20, 7, 6, 14.0, deck_width=0.0) is None
    out = capsys.readouterr().out
    assert "Error in generate_a_bars: segment rejected" in out
    assert "Traceback" in out


# --------------------------------------------------------------------------- #
# __main__ block (Grasshopper / PyCharm entry)
# --------------------------------------------------------------------------- #

def _run_main(init=None):
    import runpy
    import warnings
    with warnings.catch_warnings():
        # runpy warns that the module is already imported; that is intended here
        warnings.simplefilter("ignore", RuntimeWarning)
        return runpy.run_module("civilpy.state.ohio.DOT.odot_concrete_slab_generator",
                                init_globals=init or {}, run_name="__main__")


def test_main_defaults_to_20ft_simple_and_prints_summary(no_rhino, capsys):
    ns = _run_main()
    out = capsys.readouterr().out
    assert ns["span_length"] == 20 and ns["continuous_span"] is False
    assert ns["over_side_drainage"] is True and ns["deck_width"] == 24.0
    assert ns["out"] == "Bridge Deck Parameters - SIMPLE SPAN - Over Side Drainage"
    assert "Span Length:              20 ft" in out
    assert ns["a_bars"] is None  # not in Rhino
    assert ns["top_cover"] == 2.5 and ns["bot_cover"] == 1.5
    rebar = json.loads(ns["rebar_details"])
    assert rebar["a_bar"] == {"size": simple_concrete_slab[20]["a_bar"]["size"],
                              "spacing": simple_concrete_slab[20]["a_bar"]["spacing"]}
    assert rebar["c_bar"] == {"size": 0, "spacing": 0, "length": 0}  # simple span: no C bars
    assert rebar["edge_d"] == simple_concrete_slab[20]["over_side_drainage"]["d"]
    cont = json.loads(ns["continuous_variables"])
    assert cont == {"a_bar_a": 0, "a_bar_length": 0, "b_bar_length": 0, "m_bar_no": 0,
                    "n_bar_no": 0, "f_bar_f": 0, "u_bar_lap": 0}


def test_main_grasshopper_inputs_and_json_output(no_rhino, capsys):
    ns = _run_main({"span_length": 14, "continuous_span": True,
                    "over_side_drainage": False, "deck_width": 10.0, "output_json": True})
    out = capsys.readouterr().out
    params = json.loads(ns["out"])
    assert params == json.loads(ns["all_parameters"])
    assert params["bridge_type"] == "continuous" and params["edge_type"] == "parapet"
    assert params["thickness"] == 11
    assert json.loads(out.strip().splitlines()[-1]) == params  # JSON printed for Grasshopper
    cont = json.loads(ns["continuous_variables"])
    assert cont == {"a_bar_a": 16.583, "a_bar_length": 17.5, "b_bar_length": 21.5,
                    "m_bar_no": 47, "n_bar_no": 47, "f_bar_f": 16.583, "u_bar_lap": 78}
    rebar = json.loads(ns["rebar_details"])
    assert rebar["f_bar"] == {"size": 8, "no": 9, "length": 17.5}
    assert rebar["k_bar"] == {"size": 0, "no": 0, "length": 0}
    assert rebar["edge_x"] == 60


def test_main_reports_value_error_on_stderr(no_rhino, capsys):
    ns = _run_main({"span_length": 5})
    err = capsys.readouterr().err
    assert ns["out"].startswith("Error: Span length 5 ft not available")
    assert "Error: Span length 5 ft not available" in err


def test_main_reports_unexpected_error_with_traceback(no_rhino, capsys):
    ns = _run_main({"span_length": 20, "deck_width": "wide"})  # str * float -> TypeError
    captured = capsys.readouterr()
    assert ns["out"].startswith("Unexpected error:")
    assert "Unexpected error:" in captured.err
    assert "Traceback" in captured.out
