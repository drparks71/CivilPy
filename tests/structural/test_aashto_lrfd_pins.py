#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Pins, eyebars and pin-connected plates (AASHTO LRFD 6.7.6, 6.8.6, 6.8.7).

Statics are checked as properties over generated packings; the case-study
numbers come from the US 84 Mississippi River Bridge pin and link
replacement (NSBA case study, HNTB/MDOT)."""

import math

import numpy as np
import pytest

from civilpy.structural.aashto.lrfd.pins import (
    Eyebar, Pin, PinAndHanger, PinConnectedPlate, PinPacking, PinPlate,
    eyebar_proportions, eyebar_resistance, min_pin_diameter_for_eyebar,
    pin_actions, pin_bearing, pin_checks, pin_flexure_shear,
    pin_plate_bearing, pin_plate_proportions)


# ── Eq. 6.7.6.2.1-1 and 6.7.6.2.2 ──────────────────────────────────────────


@pytest.mark.parametrize("d,fy,m,v", [(6.0, 36.0, 400.0, 120.0), (10.0625, 50.0, 2500.0, 600.0),
                                      (4.0, 36.0, 0.0, 90.0)])
def test_interaction_terms(d, fy, m, v):
    c = pin_flexure_shear(d, fy, m, v)
    assert c.demand == pytest.approx(6 * m / (d ** 3 * fy) + (2.2 * v / (d ** 2 * fy)) ** 3)
    assert c.capacity == 0.95


def test_interaction_is_symmetric_in_sign():
    assert pin_flexure_shear(6, 36, -300, -100).demand == pin_flexure_shear(6, 36, 300, 100).demand


@pytest.mark.parametrize("t,d,fy", [(0.5, 10.0625, 36.0), (1.25, 8.0, 50.0)])
def test_bearing_coefficient_and_halving(t, d, fy):
    full = pin_bearing(t, d, fy)
    assert full.capacity == pytest.approx(1.5 * t * d * fy)
    half = pin_bearing(t, d, fy, significant_rotation=True)
    assert half.capacity == pytest.approx(0.5 * full.capacity)
    # C6.7.6.2.2: existing pins are evaluated with 1.5 even when they rotate
    assert pin_bearing(t, d, fy, significant_rotation=True,
                       new_design=False).capacity == full.capacity


def test_us84_bearing_halving_matches_the_asd_ratio():
    # case study: AASHTO ASD allowed 0.4 Fy for pins subject to rotation and
    # 0.8 Fy for pins not subject to rotation -- the same halving as C6.7.6.2.2
    ratio = (pin_bearing(1.0, 10.0, 36.0, significant_rotation=True).capacity
             / pin_bearing(1.0, 10.0, 36.0).capacity)
    assert ratio == pytest.approx(0.4 / 0.8)


@pytest.mark.parametrize("fy,b", [(36.0, 10.0), (50.0, 8.0), (70.0, 12.0)])
def test_min_pin_for_eyebar(fy, b):
    need = (0.75 + fy / 400.0) * b
    assert min_pin_diameter_for_eyebar(fy, b, d=need).ok
    assert not min_pin_diameter_for_eyebar(fy, b, d=need * 0.99).ok


# ── statics of the pin ──────────────────────────────────────────────────────


def _random_packing(rng, n_bars):
    pos = np.sort(rng.uniform(-8, 8, n_bars + 2))
    plates = [PinPlate("g0", pos[0], 0.75)]
    for k in range(n_bars):
        f = rng.uniform(-200, 200, 2)
        plates.append(PinPlate(f"b{k}", pos[k + 1], 1.0, force=(f[0], f[1])))
    plates.append(PinPlate("g1", pos[-1], 0.75))
    return plates


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("n_bars", [1, 3, 6])
def test_reactions_close_the_pin(seed, n_bars):
    plates = _random_packing(np.random.default_rng(seed), n_bars)
    a = pin_actions(plates)
    f = np.array(list(a.plate_forces.values()))
    assert f.sum(axis=0) == pytest.approx([0.0, 0.0], abs=1e-9)
    pos = {p.name: p.position for p in plates}
    for k in (0, 1):
        assert sum(a.plate_forces[n][k] * pos[n] for n in pos) == pytest.approx(0.0, abs=1e-6)
    # free ends: no shear or moment beyond the outer plates
    assert a.sections[-1].shear == pytest.approx(0.0, abs=1e-9)
    assert a.sections[-1].moment == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("p,web,t,gap", [(300.0, 1.5, 1.0, 0.25), (180.0, 0.75, 0.75, 0.125)])
def test_pin_and_hanger_moment_is_half_load_times_arm(p, web, t, gap):
    ph = PinAndHanger(hanger_width=12, hanger_t=t, hanger_fy=36, hanger_fu=58,
                      pin_d=6.0, pin_fy=36, hole_d=6.03125, web_t=(web, web),
                      web_fy=36, gap=gap)
    upper, _ = ph.pins()
    a = pin_actions(upper.plates({"hanger": (0.0, -p)}), 6.0, 36.0)
    arm = web / 2 + gap + t / 2
    assert a.max_moment == pytest.approx(p / 2 * arm)
    assert a.plate_forces["web"] == pytest.approx((0.0, p))
    c = ph.checks(p)
    assert c["upper pin flexure + shear"].demand == pytest.approx(
        pin_flexure_shear(6.0, 36.0, p / 2 * arm, p / 2).demand)
    assert c["upper pin bearing web"].capacity == pytest.approx(1.5 * web * 6.0 * 36.0)


def test_frozen_pin_longitudinal_force_adds_vectorially():
    ph = PinAndHanger(hanger_width=12, hanger_t=1.0, hanger_fy=36, hanger_fu=58,
                      pin_d=6.0, pin_fy=36, hole_d=6.03125, web_t=(1.5, 1.5), web_fy=36)
    plain = ph.checks(300.0)["upper pin flexure + shear"]
    frozen = ph.checks(300.0, h_u=100.0)["upper pin flexure + shear"]
    arm = 0.75 + 0.25 + 0.5
    assert frozen.details["Mu"] == pytest.approx(math.hypot(150, 50) * arm)
    assert frozen.demand > plain.demand


def test_us84_eyebar_loads_reach_the_gussets():
    # Table 3 measured link eyebar loads (6 bars) vs the 1940 plans' dead
    # load: the pin hands the bars' total to the two gussets.  U49 sums to
    # its printed 673 k, within 3 % of 655 k as the paper says.  (U29's six
    # bars sum to 664.4 k although the table prints 656.5 k -- one entry is
    # off in the paper -- so it is not used.)
    bars, dl = (135.3, 115.9, 100.2, 102.0, 104.1, 115.7), 655.0
    plates = [PinPlate("inboard gusset", -9.0, 0.5)]
    plates += [PinPlate(f"bar {k + 1}", -6.25 + 2.5 * k, 1.0, force=(0.0, f))
               for k, f in enumerate(bars)]
    plates.append(PinPlate("outboard gusset", 9.0, 0.5))
    a = pin_actions(plates, 10.0625, 36.0)
    total = -(a.plate_forces["inboard gusset"][1] + a.plate_forces["outboard gusset"][1])
    assert total == pytest.approx(673.0, abs=0.25)
    assert abs(total - dl) / dl < 0.03          # "within 3% of the dead loads"
    # the inside bar is the heavier (15 % per the paper): the inboard gusset
    # takes more than half
    assert -a.plate_forces["inboard gusset"][1] > total / 2


# ── eyebars and pin plates ──────────────────────────────────────────────────


def _good_bar(**kw):
    base = dict(b=8.0, t=1.25, head_net_width=11.0, head_beyond_hole=6.5,
                transition_radius=20.0, head_width=18.0, hole_d=8.03125,
                pin_d=8.0, f_y=36.0)
    base.update(kw)
    return Eyebar(**base)


def test_compliant_eyebar_passes_every_rule():
    assert all(c.ok for c in eyebar_proportions(_good_bar()).values())


@pytest.mark.parametrize("change,rule", [
    (dict(t=0.4, b=3.0), "thickness >= 0.5 in"),
    (dict(t=2.25, b=8.0), "thickness <= 2.0 in"),
    (dict(transition_radius=15.0), "transition radius >= head width"),
    (dict(head_net_width=10.0), "net head width >= 1.35 b"),
    (dict(head_beyond_hole=5.5), "head beyond hole >= 0.75 b"),
    (dict(b=10.5, head_net_width=14.5, head_beyond_hole=8.0), "body width <= 8 t"),
    (dict(hole_d=8.0625), "hole <= pin + 1/32 in"),
    (dict(f_y=100.0, t=1.25, hole_d=8.03125), "hole <= 5 t (Fy > 70 ksi)"),
    (dict(hole_on_axis=False), "hole on body axis"),
])
def test_each_eyebar_rule_fails_alone(change, rule):
    res = eyebar_proportions(_good_bar(**change))
    failed = {k for k, c in res.items() if not c.ok}
    assert failed == {rule}


def test_eyebar_body_is_gross_yield():
    c = eyebar_resistance(8.0, 1.25, 36.0, p_u=300.0)
    assert c.capacity == pytest.approx(0.95 * 36.0 * 10.0)
    assert c.article == "6.8.6.1"


def test_pin_plate_bearing_and_proportions():
    assert pin_plate_bearing(1.5, 6.0, 36.0).capacity == pytest.approx(1.5 * 6.0 * 36.0)
    good = PinConnectedPlate(net_area_at_hole=15.0, net_area_beyond_hole=10.0,
                             required_net_area=10.0, t_main=1.0, t_total=1.5,
                             net_width_edge=8.0, required_width=8.0,
                             hole_d=6.03125, pin_d=6.0)
    assert all(c.ok for c in pin_plate_proportions(good).values())
    thin = PinConnectedPlate(net_area_at_hole=13.0, net_area_beyond_hole=9.0,
                             required_net_area=10.0, t_main=0.9, t_total=0.9,
                             net_width_edge=8.0, required_width=7.0,
                             hole_d=6.03125, pin_d=6.0)
    failed = {k for k, c in pin_plate_proportions(thin).items() if not c.ok}
    assert failed == {"net area at hole >= 1.4 required",
                      "net area beyond hole >= required",
                      "combined t >= 0.12 x net edge width"}


# ── pins in a pin-connected truss ──────────────────────────────────────────


def _pin_connected_pratt():
    from civilpy.structural.truss_builder import TrussBridge, TrussSection
    b = TrussBridge([25.0] * 6, height_ft=30.0, width_ft=20.0)
    b.assign_section(type(b.members[0]).__mro__[-2],
                     TrussSection("eyebars", area_in2=20.0, r_in=4.0))
    for p in ("L1", "L2", "L3", "L4", "L5"):
        b.add_panel_load(p, 40.0)
    return b


@pytest.mark.parametrize("node", ["U2", "U3", "U1"])
def test_unloaded_joint_pin_balances_from_member_forces(node):
    # a pin-connected joint with no external load: every packed member's bars
    # on the pin, forces from the truss analysis, must close by themselves
    b = _pin_connected_pratt()
    a = b.analyze(joints="pinned")
    members = [m for m in b.members if node in (m.start, m.end)]
    packing, x = [], -0.5 * (2 * len(members) - 1) * 1.25
    for m in members:
        for half in (0, 1):
            packing.append(PinPacking(f"{m.name} {half}", x, 1.0, member=m, share=0.5))
            x += 1.25
    b.pins[node] = Pin(6.0, 36.0, packing)
    res = b.pin_checks(a)[node]
    assert res["flexure + shear"].demand > 0
    f = a.pin_forces(node)
    assert sum(v[0] for v in f.values()) == pytest.approx(0.0, abs=1e-9)
    assert sum(v[1] for v in f.values()) == pytest.approx(0.0, abs=1e-9)


def test_loaded_joint_needs_a_reaction_plate():
    b = _pin_connected_pratt()
    a = b.analyze(joints="pinned")
    members = [m for m in b.members if "L2" in (m.start, m.end)]
    packing = [PinPacking("floorbeam hanger", 0.0, 1.0)]       # reaction: the panel load
    packing += [PinPacking(m.name, 1.5 * (k + 1), 1.0, member=m) for k, m in enumerate(members)]
    b.pins["L2"] = Pin(6.0, 36.0, packing)
    res = b.pin_checks(a)["L2"]
    assert res["bearing floorbeam hanger"].demand == pytest.approx(40.0)


def test_pin_emits_as_a_cylinder_spanning_the_packing():
    from civilpy.structural import rhino_truss as rt
    from civilpy.structural.rhino_layers import LAYER_TRUSS_PINS
    m = rt.TrussModel("pinned")
    m.add_node(rt.TrussNode("U2", (50.0, 0.0, 30.0), chord="U"))
    pin = Pin(6.0, 36.0, [PinPacking("a", -3.0, 1.0), PinPacking("b", 3.0, 1.0)])
    m.pins.append(rt.PinPlacement("pin-U2", "U2", pin, projection_in=1.0))
    (obj,) = [o for o in rt.truss_emit(m) if o.layer == LAYER_TRUSS_PINS]
    assert obj.kind == "cylinder" and obj.radius_ft == pytest.approx(0.25)
    length_in = math.dist(*obj.points) * 12.0
    assert length_in == pytest.approx(3.5 + 3.5 + 2.0)
    assert obj.tags["bim.type"] == "truss_pin" and obj.tags["pin.diameter_in"] == "6"
