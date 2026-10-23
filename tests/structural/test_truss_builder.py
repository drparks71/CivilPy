#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Tests for the object-oriented truss bridge builder."""

import math

import numpy as np

import matplotlib
import pytest

matplotlib.use("Agg")

from civilpy.structural.truss_builder import (
    TrussBridge, TrussSection, Deck, LaneLine,
    TopChord, BottomChord, EndPost, Vertical, Hanger, Diagonal, Counter,
    Floorbeam, Stringer, LateralBrace, Strut,
)


def six_panel_pratt(**kwargs):
    defaults = dict(panel_lengths_ft=[25.0] * 6, height_ft=30.0,
                    width_ft=20.0, pattern="pratt")
    defaults.update(kwargs)
    return TrussBridge(**defaults)


# ── Geometry ───────────────────────────────────────────────────────────────


def test_nonuniform_panels_set_node_stations():
    b = TrussBridge([18.0, 26.0, 31.0, 25.0], height_ft=28.0)
    assert b.span_ft == 100.0
    assert b.nodes["L2"] == (44.0, 0.0)
    assert b.nodes["L3"] == (75.0, 0.0)


def test_asymmetric_polygonal_top_chord():
    b = TrussBridge([20, 25, 30, 25], heights_ft=[None, 22, 30, 26, None])
    assert b.nodes["U1"] == (20.0, 22.0)
    assert b.nodes["U3"] == (75.0, 26.0)
    assert "U0" not in b.nodes and "U4" not in b.nodes


def test_through_pratt_member_inventory():
    b = six_panel_pratt()
    roles = {}
    for m in b.members:
        roles[m.role] = roles.get(m.role, 0) + 1
    assert roles == {"Bottom Chord": 6, "Top Chord": 4, "End Post": 2,
                     "Vertical": 5, "Diagonal": 4}
    # diagonals descend toward midspan (Pratt) and are typed tension
    diag_keys = {m.key for m in b.members if m.role == "Diagonal"}
    assert diag_keys == {("U1", "L2"), ("U2", "L3"),
                         ("U4", "L3"), ("U5", "L4")}
    assert all(m.expected == "tension" for m in b.members
               if m.role == "Diagonal")


def test_deck_truss_keeps_full_top_chord():
    b = TrussBridge([20] * 4, height_ft=24.0, deck_level="top")
    assert "U0" in b.nodes and "U4" in b.nodes
    assert {fb.point for fb in b.floorbeams} == {f"U{i}" for i in range(5)}


def test_warren_needs_even_panel_count():
    with pytest.raises(ValueError, match="even panel count"):
        TrussBridge([20] * 5, height_ft=25.0, pattern="warren")


def test_warren_solves():
    b = TrussBridge([20] * 6, height_ft=25.0, pattern="warren")
    assert "U2" not in b.nodes and "U3" in b.nodes
    b.set_deck(Deck(width_ft=18.0))
    forces = b.solve()
    assert forces[("L2", "L3")] > 0


def test_custom_pattern_and_member_add_remove():
    b = TrussBridge([20] * 4, height_ft=25.0, pattern=None)
    # only chords generated; the through-truss tops survive for a custom web
    assert all(m.role in ("Bottom Chord", "Top Chord") for m in b.members)
    b.add(Diagonal("L0", "U1"))
    with pytest.raises(KeyError):
        b.add(Diagonal("L0", "U9"))
    b.remove("L0", "U1")
    with pytest.raises(KeyError):
        b.member("L0", "U1")


# ── Load path: deck → stringers → floorbeams → panel points ───────────────


def test_stringer_tributary_widths_cover_deck():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=24.0, thickness_in=9.0,
                    wearing_surface_psf=30.0),
               stringer_offsets_ft=[-9.0, -3.0, 3.0, 9.0])
    loads = b.stringer_line_loads("total")
    w = b.deck_area_load_ksf()
    assert w == pytest.approx(9.0 / 12 * 0.150 + 0.030)
    assert sum(loads.values()) == pytest.approx(w * 24.0)
    # edge stringers carry the overhang out to the deck edge
    assert loads[-9.0] == pytest.approx(w * 6.0)
    assert loads[-3.0] == pytest.approx(w * 6.0)


def test_floorbeam_loads_follow_nonuniform_panels():
    b = TrussBridge([18.0, 30.0, 30.0, 22.0], height_ft=28.0)
    b.set_deck(Deck(width_ft=20.0), stringer_offsets_ft=[-5.0, 5.0])
    p1 = sum(b.floorbeam_point_loads(1).values())
    p2 = sum(b.floorbeam_point_loads(2).values())
    w_total = b.deck_area_load_ksf() * 20.0
    assert p1 == pytest.approx(w_total * (18.0 + 30.0) / 2.0)
    assert p2 == pytest.approx(w_total * 30.0)


def test_centered_deck_loads_planes_equally():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0))
    near = b.panel_point_loads("near")
    far = b.panel_point_loads("far")
    assert near == pytest.approx(far)
    total = b.deck_area_load_ksf() * 20.0 * b.span_ft
    assert sum(near.values()) + sum(far.values()) == pytest.approx(total)


def test_offset_deck_loads_planes_unequally_but_conserves_total():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=18.0, offset_ft=3.0))
    near = sum(b.panel_point_loads("near").values())
    far = sum(b.panel_point_loads("far").values())
    assert far > near
    total = b.deck_area_load_ksf() * 18.0 * b.span_ft
    assert near + far == pytest.approx(total)
    # statics about the near plane: far reaction * width = sum(P * lever)
    lever = 3.0 + 10.0      # deck resultant sits 13 ft from the near plane
    assert far == pytest.approx(total * lever / 20.0)


def test_extra_panel_load_applies_per_plane():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0))
    base = b.panel_point_loads("near")["L3"]
    b.add_panel_load("L3", 12.0)
    assert b.panel_point_loads("near")["L3"] == pytest.approx(base + 12.0)


# ── Analysis ───────────────────────────────────────────────────────────────


def test_member_forces_match_method_of_sections():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0))
    forces = b.solve("near")
    loads = b.panel_point_loads("near")
    total = sum(loads.values())
    r_left = total / 2.0
    # cut through panel 3 (between L2 and L3): bottom chord force =
    # moment about U2 (x = 50 ft) / depth, ignoring the end-point load
    # that passes straight into the support
    m_u2 = (r_left - loads["L0"]) * 50.0 - loads["L1"] * 25.0
    assert forces[("L2", "L3")] == pytest.approx(m_u2 / 30.0)
    # symmetric structure: mirrored members carry equal force
    assert forces[("L0", "L1")] == pytest.approx(forces[("L5", "L6")])
    assert forces[("U1", "L2")] == pytest.approx(forces[("U5", "L4")])
    # role expectations hold under gravity load
    assert forces[("U2", "U3")] < 0
    assert forces[("L0", "U1")] < 0          # end post in compression
    assert forces[("U1", "L2")] > 0          # Pratt diagonal in tension


def test_governing_forces_take_heavier_plane():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=18.0, offset_ft=4.0))
    far = b.solve("far")
    gov = b.member_forces()
    bc = b.member("L2", "L3")
    assert gov[bc] == pytest.approx(far[bc.key])


def test_capacity_checks_route_by_force_sign():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0, thickness_in=9.0))
    b.assign_section(BottomChord, TrussSection(
        "BC", area_in2=14.0, net_area_in2=12.0, fy_ksi=50, fu_ksi=65))
    b.assign_section(TopChord, TrussSection("TC", area_in2=18.0, r_in=3.1))
    b.assign_section(EndPost, TrussSection("EP", area_in2=16.0, r_in=2.9))
    checks = b.capacity_checks()
    bc = checks["Bottom Chord L2-L3"]
    assert bc.article == "6.8.2.1"
    assert bc.demand == pytest.approx(b.member_forces()[b.member("L2", "L3")])
    tc = checks["Top Chord U2-U3"]
    assert tc.article == "6.9.4.1.1"
    assert tc.demand > 0
    kl_r = tc.details.get("KL/r", None)
    if kl_r is not None:
        assert kl_r == pytest.approx(25.0 * 12.0 / 3.1)
    # diagonals have no section: skipped, not crashed
    assert not any(name.startswith("Diagonal") for name in checks)


def test_compression_member_without_r_raises():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0))
    b.assign_section(TopChord, TrussSection("TC", area_in2=18.0))
    with pytest.raises(ValueError, match="r_in"):
        b.capacity_checks()


# ── Visualization smoke tests ──────────────────────────────────────────────


def test_plots_return_figures():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0))
    b.add_lane(LaneLine("EB", offset_ft=-5.0))
    for fig in (b.plot_elevation(), b.plot_forces(),
                b.plot_cross_section()):
        assert fig is not None
        matplotlib.pyplot.close(fig)


def test_plot_3d_draws_every_exported_element():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=20.0))
    b.add_lane(LaneLine("EB", offset_ft=-5.0))
    fig = b.plot_3d()
    ax = fig.axes[0]
    n_elems = len(b.midas_payloads()["ELEM"])
    # one 3-D line per element, plus deck outline and one lane line
    assert len(ax.lines) == n_elems + 2
    assert ax.name == "3d"
    matplotlib.pyplot.close(fig)


# ── MIDAS export ───────────────────────────────────────────────────────────


def exported_bridge():
    b = six_panel_pratt()
    b.set_deck(Deck(width_ft=22.0, thickness_in=8.0,
                    wearing_surface_psf=25.0),
               stringer_offsets_ft=[-8.0, -3.0, 3.0, 8.0])
    b.add_lane(LaneLine("EB", offset_ft=-5.0))
    b.add_lane(LaneLine("WB", offset_ft=5.0))
    b.assign_section(BottomChord, TrussSection("BC", area_in2=14.0))
    return b


def test_midas_payload_tables_and_units():
    p = exported_bridge().midas_payloads()
    assert list(p)[:2] == ["UNIT", "MATL"]
    for table in ("SECT", "NODE", "ELEM", "CONS", "GRUP", "STLD",
                  "BMLD", "LLAN"):
        assert table in p
    assert p["UNIT"]["1"]["FORCE"] == "KIPS"
    assert p["UNIT"]["1"]["DIST"] == "FT"


def test_midas_nodes_cover_planes_and_stringer_crossings():
    b = exported_bridge()
    p = b.midas_payloads()
    # 12 elevation nodes per plane + 4 stringer crossings per floorbeam
    assert len(p["NODE"]) == 2 * len(b.nodes) + 4 * len(b.floorbeams)
    ys = {round(n["Y"], 3) for n in p["NODE"].values()}
    assert {-10.0, 10.0, -8.0, -3.0, 3.0, 8.0} <= ys


def test_midas_element_types_follow_component_roles():
    b = exported_bridge()
    b.add(Counter("U3", "L2"))
    b.add(LateralBrace("U1", "U2'"))
    p = b.midas_payloads()
    elems = p["ELEM"]
    groups = {g["NAME"]: g["E_LIST"] for g in p["GRUP"].values()}
    for name, expected_type in (("Bottom Chord", "BEAM"),
                                ("Diagonal", "TRUSS"),
                                ("Counter", "TENS"),
                                ("Stringer", "BEAM"),
                                ("Floorbeam", "BEAM"),
                                ("Lateral Brace", "TRUSS")):
        assert groups[name], name
        for eid in groups[name]:
            assert elems[str(eid)]["TYPE"] == expected_type, name
    # both planes get the elevation members
    assert len(groups["Bottom Chord"]) == 12
    # stringers: 4 lines x 6 panels
    assert len(groups["Stringer"]) == 24
    # floorbeams subdivide at the 4 stringer crossings: 5 segments x 7
    assert len(groups["Floorbeam"]) == 35


def test_midas_supports_pin_and_roller():
    b = exported_bridge()
    p = b.midas_payloads()
    constraints = sorted(s["ITEMS"][0]["CONSTRAINT"]
                         for s in p["CONS"].values())
    assert constraints == ["0110000", "0110000", "1110000", "1110000"]


def test_midas_deck_loads_land_on_stringers():
    b = exported_bridge()
    p = b.midas_payloads()
    stringer_ids = set()
    for g in p["GRUP"].values():
        if g["NAME"] == "Stringer":
            stringer_ids = set(g["E_LIST"])
    assert set(int(i) for i in p["BMLD"]) == stringer_ids
    item = next(iter(p["BMLD"].values()))["ITEMS"][0]
    assert item["LCNAME"] in ("DC", "DW")
    assert item["DIRECTION"] == "GZ"
    assert item["P"][0] < 0                  # gravity acts downward
    case_names = {i["LCNAME"] for body in p["BMLD"].values()
                  for i in body["ITEMS"]}
    assert case_names == {"DC", "DW"}
    assert {c["NAME"] for c in p["STLD"].values()} == {"DC", "DW"}


def test_midas_lanes_ride_nearest_stringer_with_eccentricity():
    b = exported_bridge()
    p = b.midas_payloads()
    lanes = {v["COMMON"]["LL_NAME"]: v for v in p["LLAN"].values()}
    # EB lane at -5 ft: nearest stringer line is -3 ft, ecc = -2 ft
    assert lanes["EB"]["LANE_ITEMS"][0]["ECC"] == pytest.approx(-2.0)
    assert lanes["WB"]["LANE_ITEMS"][0]["ECC"] == pytest.approx(2.0)
    assert len(lanes["EB"]["LANE_ITEMS"]) == 6   # one per panel
    elems = p["ELEM"]
    for item in lanes["EB"]["LANE_ITEMS"]:
        assert elems[str(item["ELEM"])]["TYPE"] == "BEAM"


def test_midas_sections_preserve_axial_area():
    b = exported_bridge()
    p = b.midas_payloads()
    by_name = {s["SECT_NAME"]: s for s in p["SECT"].values()}
    side = by_name["BC"]["SECT_BEFORE"]["SECT_I"]["vSIZE"][0]
    assert (side * 12.0) ** 2 == pytest.approx(14.0, rel=1e-4)
    assert "PLACEHOLDER-1ft-SQ" in by_name


def test_to_midas_sends_in_order_and_reports_errors():
    b = exported_bridge()

    class FakeMidas:
        def __init__(self):
            self.calls = []

        def put_db(self, table, assign):
            self.calls.append(table)
            if table == "GRUP":
                raise RuntimeError("bad group keys")

    fake = FakeMidas()
    report = b.to_midas(fake)
    assert fake.calls[:5] == ["UNIT", "MATL", "SECT", "NODE", "ELEM"]
    assert report["GRUP"] == {"error": "bad group keys"}
    assert report["NODE"]["sent"] == len(b.midas_payloads()["NODE"])
    # one error does not stop later tables
    assert "LLAN" in report and "sent" in report["LLAN"]


# ── G13.2 analysis: joint fixity, camber, influence lines ──────────────────

from civilpy.structural.influence_lines import InfluenceLine          # noqa: E402

SEC_A = TrussSection("built-up", area_in2=30.0, r_in=5.0, i_in4=900.0,
                     depth_in=16.0)

LAYOUTS = {
    "pratt6": dict(panel_lengths_ft=[25.0] * 6, height_ft=30.0, pattern="pratt"),
    "pratt_uneven": dict(panel_lengths_ft=[22.0, 28.0, 28.0, 22.0],
                         heights_ft=[None, 24.0, 27.0, 24.0, None], pattern="pratt"),
    "howe8": dict(panel_lengths_ft=[20.0] * 8, height_ft=24.0, pattern="howe"),
    "warren6": dict(panel_lengths_ft=[18.0] * 6, height_ft=20.0, pattern="warren"),
    "deck_pratt": dict(panel_lengths_ft=[20.0] * 6, heights_ft=[22.0] * 7,
                       pattern="pratt", deck_level="top"),
}


def _loaded(name, deck=True):
    b = TrussBridge(width_ft=20.0, **LAYOUTS[name])
    b.assign_section(type(b.members[0]).__mro__[-2], SEC_A)     # every Member
    if deck:
        b.set_deck(Deck(width_ft=18.0, thickness_in=8.0, wearing_surface_psf=25))
    for point in [fb.point for fb in b.floorbeams][1:-1]:
        b.add_panel_load(point, 6.0)
    return b


@pytest.mark.parametrize("name", LAYOUTS)
def test_pinned_frame_analysis_equals_method_of_joints(name):
    b = _loaded(name)
    statics = b.solve()
    a = b.analyze(joints="pinned")
    for m in b.members:
        assert a.axial(m) == pytest.approx(statics[m.key], abs=1e-6)
        assert a.end_moments(m) == (pytest.approx(0.0), pytest.approx(0.0))


@pytest.mark.parametrize("name", LAYOUTS)
def test_rigid_joints_change_axial_little_but_add_secondary_moments(name):
    b = _loaded(name)
    pinned, rigid = b.analyze(joints="pinned"), b.analyze(joints="rigid")
    peak = max(abs(pinned.axial(m)) for m in b.members)
    assert max(abs(rigid.axial(m) - pinned.axial(m)) for m in b.members) < 0.05 * peak
    assert max(rigid.secondary_stress_ksi(m) for m in b.members) > 0.0


@pytest.mark.parametrize("name", LAYOUTS)
def test_camber_for_the_load_case_removes_moments_and_deflections(name):
    # G13.2 4.1.2: members fabricated -PL/AE for total dead load, then that
    # load brings the truss to its geometric profile with no secondary moments
    b = _loaded(name)
    a = b.analyze(joints="rigid", camber_case="total")
    assert max(abs(v) for m in b.members for v in a.end_moments(m)) < 1e-6
    assert max(abs(c) for n in b.nodes for c in a.deflection_in(n)) < 1e-9
    plain = b.analyze(joints="rigid")
    assert max(abs(plain.deflection_in(n)[1]) for n in b.nodes) > 0.01


def test_camber_length_changes_sign_and_size():
    b = _loaded("pratt6")
    dl = b.camber_length_changes("total")
    forces = b.analyze(joints="pinned").forces
    for m, d in dl.items():
        want = -forces[m] * b.member_length_ft(m) * 12.0 / (SEC_A.area_in2 * 29000.0)
        assert d == pytest.approx(want)
        assert (d > 0) == (forces[m] < 0) or abs(forces[m]) < 1e-9


def test_staged_pinned_dead_load_locks_in_no_moment():
    b = _loaded("pratt6")
    staged = b.staged_analysis([("dc", "pinned"), ("dw", "rigid")])
    rigid_dw = b.analyze(case="dw", joints="rigid")
    for m in b.members:
        assert staged.end_moments(m)[0] == pytest.approx(rigid_dw.end_moments(m)[0], abs=1e-9)
        total = b.analyze(case="dc", joints="pinned").axial(m) + rigid_dw.axial(m)
        assert staged.axial(m) == pytest.approx(total, abs=1e-9)


def test_secondary_stress_screen_exempts_slender_members():
    b = _loaded("pratt6")
    slender = TrussSection("slender", area_in2=30.0, r_in=5.0, i_in4=900.0, depth_in=12.0)
    stubby = TrussSection("stubby", area_in2=30.0, r_in=5.0, i_in4=900.0, depth_in=40.0)
    b.assign_section(Diagonal, slender)          # 12 in / 469 in < 1/10
    b.assign_section(Vertical, stubby)           # 40 in / 360 in > 1/10
    checks = b.secondary_stress_checks(case="total")
    a = b.analyze(joints="rigid")
    for m in b.members:
        c = checks[m.name]
        assert c.advisory and c.article == "6.14.2.3"
        if isinstance(m, Diagonal):
            assert c.demand is None and "exempt" in c.details
        elif isinstance(m, Vertical):
            assert c.demand == pytest.approx(a.secondary_stress_ksi(m))
            assert c.capacity == (4.0 if a.axial(m) >= 0 else 3.0)


@pytest.mark.parametrize("panels", [4, 6, 8])
def test_chord_influence_lines_are_beam_moment_over_depth(panels):
    # parallel-chord Pratt, method of sections: bottom chord L_p-L_p+1 =
    # M(x at U_p) / h left of midspan; top chord U_p-U_p+1 = -M(x at L_p+1) / h
    panel, h = 20.0, 25.0
    b = TrussBridge([panel] * panels, height_ft=h, width_ft=18.0)
    b.assign_section(type(b.members[0]).__mro__[-2], SEC_A)
    ils = b.influence_lines()
    span = panel * panels
    xs = np.linspace(0, span, 37)
    for p in range(1, panels // 2):
        il = ils[b.member(f"L{p}", f"L{p + 1}")]
        beam = InfluenceLine.moment(span, p * panel)
        assert il.eta(xs) == pytest.approx(beam.eta(xs) / h, abs=1e-9)
        top = ils[b.member(f"U{p}", f"U{p + 1}")]
        beam = InfluenceLine.moment(span, (p + 1) * panel)
        assert top.eta(xs) == pytest.approx(-beam.eta(xs) / h, abs=1e-9)


def test_live_load_envelope_one_lane_equals_share_times_hl93():
    b = TrussBridge([25.0] * 6, height_ft=30.0, width_ft=24.0)
    b.assign_section(type(b.members[0]).__mro__[-2], SEC_A)
    b.add_lane(LaneLine("1", offset_ft=-4.0))
    share = b.lane_fractions("near")["1"]
    assert share == pytest.approx(0.5 + 4.0 / 24.0)
    env = b.live_load_envelope("near")
    ils = b.influence_lines("near")
    for m, (tmax, cmax) in env.items():
        pos = ils[m].hl93_effect()["total"]
        neg = ils[m].hl93_effect(sign=-1)["total"]
        assert tmax == pytest.approx(max(0.0, 1.2 * share * pos))
        assert cmax == pytest.approx(min(0.0, 1.2 * share * neg))


def test_live_load_envelope_takes_governing_lane_count():
    b = TrussBridge([25.0] * 6, height_ft=30.0, width_ft=36.0)
    b.assign_section(type(b.members[0]).__mro__[-2], SEC_A)
    for k, y in enumerate((-12.0, 0.0, 12.0)):
        b.add_lane(LaneLine(str(k), offset_ft=y))
    shares = sorted(b.lane_fractions("near").values(), reverse=True)
    m = b.member("L2", "L3")
    pos = b.influence_lines()[m].hl93_effect()["total"]
    best = max(f * sum(shares[:k]) * pos for k, f in ((1, 1.2), (2, 1.0), (3, 0.85)))
    assert b.live_load_envelope()[m][0] == pytest.approx(best)


@pytest.mark.parametrize("spans,coeffs", [
    ((20.0, 20.0), (0.375, 1.25, 0.375)),
    ((20.0, 20.0, 20.0), (0.4, 1.1, 1.1, 0.4)),
])
def test_continuous_stringers_give_continuous_beam_reactions(spans, coeffs):
    b = TrussBridge(list(spans), height_ft=20.0, width_ft=20.0, pattern=None)
    b.set_deck(Deck(width_ft=20.0, thickness_in=8.0), stringer_offsets_ft=[0.0],
               stringer_continuity="continuous")
    w = b.stringer_line_loads()[0.0]
    for k, c in enumerate(coeffs):
        assert b.floorbeam_point_loads(k)[0.0] == pytest.approx(c * w * spans[0])


def test_rigid_analysis_needs_inertia():
    b = TrussBridge([25.0] * 4, height_ft=25.0, width_ft=20.0)
    b.assign_section(type(b.members[0]).__mro__[-2],
                     TrussSection("no I", area_in2=20.0, r_in=4.0))
    with pytest.raises(ValueError, match="i_in4"):
        b.analyze(joints="rigid")
