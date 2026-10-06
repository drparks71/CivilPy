#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Staged-construction load helpers (``civilpy.structural.construction_staging``).

The hub model and the bridge layout are replaced by small stubs that expose
only what the module reads (``model.elements`` with ``role`` / ``metadata`` /
``id``, ``model.add_beam_load``, ``layout.inputs.girder_spacing_ft`` /
``girder_count``, ``layout.deck.thickness_in``), and every test asserts the
load payloads the module hands the model.  Reference values: AASHTO LRFD
3.6.1.1.2 multiple presence (Table 3.6.1.1.2-1), 3.6.1.2.4 lane load
(0.64 klf), 3.6.1.1.1 number of design lanes, and the transverse lever rule.
"""

import pytest

from civilpy.structural.bridge_layout import CONCRETE_UNIT_WT_KCF
from civilpy.structural.construction_staging import (
    LANE_LOAD_KLF,
    MULTIPLE_PRESENCE,
    PORTABLE_BARRIERS,
    PortableBarrier,
    RoadwayLanes,
    _girder_offsets,
    add_barrier_dead_load,
    add_closure_pour_load,
    add_design_lane_load,
    add_lane_load,
    add_line_load_at_offset,
    closure_pour_line_load_plf,
    design_lanes,
    girder_elements,
    lanes_over_girders,
    multiple_presence,
    portable_barrier,
)


# ── stubs ──────────────────────────────────────────────────────────────────

class _Elem:
    def __init__(self, eid, role, line=None):
        self.id = eid
        self.role = role
        self.metadata = {} if line is None else {"gdr.line": str(line)}


class _Model:
    """Just enough of the hub model: an element dict and a load recorder."""

    def __init__(self, girder_lines, per_line=2):
        self.elements = {}
        for g in girder_lines:
            for k in range(per_line):
                eid = f"G{g}-{k}"
                self.elements[eid] = _Elem(eid, "girder", g)
        self.elements["D1"] = _Elem("D1", "deck", 1)          # not a girder
        self.elements["X1"] = _Elem("X1", "girder")           # girder w/o a line
        self.calls = []

    def add_beam_load(self, element_id, w, *, case):
        self.calls.append((element_id, w, case))

    def total_by_case(self, case):
        return sum(w for _, w, c in self.calls if c == case)


class _Inputs:
    def __init__(self, girder_count, girder_spacing_ft):
        self.girder_count = girder_count
        self.girder_spacing_ft = girder_spacing_ft


class _Deck:
    def __init__(self, thickness_in):
        self.thickness_in = thickness_in


class _Layout:
    def __init__(self, girder_count=4, spacing=8.0, deck_in=9.0):
        self.inputs = _Inputs(girder_count, spacing)
        self.deck = _Deck(deck_in)


@pytest.fixture
def layout():
    return _Layout(girder_count=4, spacing=8.0, deck_in=9.0)


@pytest.fixture
def model():
    return _Model([1, 2, 3, 4])


# ── multiple presence / barrier catalog ────────────────────────────────────

@pytest.mark.parametrize("n, m", [(1, 1.20), (2, 1.00), (3, 0.85), (4, 0.65), (7, 0.65)])
def test_multiple_presence_table_3_6_1_1_2_1(n, m):
    assert multiple_presence(n) == m


def test_multiple_presence_zero_lanes_falls_back_to_single_lane_factor():
    assert 0 not in MULTIPLE_PRESENCE
    assert multiple_presence(0) == 1.20


def test_portable_barrier_catalog():
    b = portable_barrier()
    assert isinstance(b, PortableBarrier)
    assert b.designation == "PCB-32" and b.height_in == 32.0
    assert b.weight_plf == 470.0 and b.anchored is True
    assert portable_barrier("PCB-42").weight_plf == 650.0
    jersey = portable_barrier("JERSEY-PORTABLE")
    assert jersey.anchored is False and jersey.weight_plf == 400.0
    assert set(PORTABLE_BARRIERS) == {"PCB-32", "PCB-42", "JERSEY-PORTABLE"}


def test_portable_barrier_unknown_designation():
    with pytest.raises(ValueError) as ei:
        portable_barrier("PCB-99")
    assert "PCB-99" in str(ei.value) and "PCB-32" in str(ei.value)


# ── girder helpers ─────────────────────────────────────────────────────────

def test_girder_elements_filters_by_role_and_line(model):
    assert [e.id for e in girder_elements(model, 2)] == ["G2-0", "G2-1"]
    assert girder_elements(model, 1) == [model.elements["G1-0"], model.elements["G1-1"]]
    assert girder_elements(model, 9) == []


def test_girder_offsets_from_spacing(layout):
    assert _girder_offsets(layout) == [0.0, 8.0, 16.0, 24.0]
    assert _girder_offsets(_Layout(girder_count=1, spacing=12.0)) == [0.0]


# ── lever rule line load ───────────────────────────────────────────────────

def test_line_load_midway_splits_equally(model, layout):
    applied = add_line_load_at_offset(model, layout, 4.0, 1000.0, case="T")
    assert applied == {1: -0.5, 2: -0.5}
    assert model.calls == [("G1-0", -0.5, "T"), ("G1-1", -0.5, "T"),
                           ("G2-0", -0.5, "T"), ("G2-1", -0.5, "T")]


def test_line_load_inverse_distance_shares(model, layout):
    # 6 ft from girder 1 of an 8 ft bay: 25 % to girder 1, 75 % to girder 2
    applied = add_line_load_at_offset(model, layout, 6.0, 400.0, case="T")
    assert applied[1] == pytest.approx(-0.1)
    assert applied[2] == pytest.approx(-0.3)
    assert sum(applied.values()) == pytest.approx(-0.4)
    # interior bay: 18 ft sits 2 ft past girder 3 (16 ft)
    applied = add_line_load_at_offset(_Model([1, 2, 3, 4]), layout, 18.0, 800.0, case="T")
    assert applied == pytest.approx({3: -0.6, 4: -0.2})


def test_line_load_outboard_of_a_fascia_girder_goes_fully_to_it(layout):
    m = _Model([1, 2, 3, 4])
    assert add_line_load_at_offset(m, layout, -3.0, 500.0, case="T") == {1: -0.5}
    assert add_line_load_at_offset(m, layout, 30.0, 500.0, case="T") == {4: -0.5}
    assert add_line_load_at_offset(m, layout, 24.0, 500.0, case="T") == {4: -0.5}
    assert add_line_load_at_offset(m, layout, 0.0, 500.0, case="T") == {1: -0.5}


def test_line_load_exactly_on_an_interior_girder_line(model, layout):
    # the neighbour would get a 0 share: it is dropped, not recorded as 0
    applied = add_line_load_at_offset(model, layout, 8.0, 1000.0, case="T")
    assert applied == {2: -1.0}
    assert {c[0][:2] for c in model.calls} == {"G2"}


def test_line_load_sign_convention(model, layout):
    down = add_line_load_at_offset(model, layout, 4.0, -1000.0, case="T")
    assert down == {1: -0.5, 2: -0.5}                         # downward = negative GZ
    up = add_line_load_at_offset(_Model([1, 2]), layout, 4.0, 1000.0, case="T", downward=False)
    assert up == {1: 0.5, 2: 0.5}


def test_line_load_skips_girders_absent_from_a_phase_model(layout):
    stage1 = _Model([1, 3, 4])                                 # girder 2 not built yet
    applied = add_line_load_at_offset(stage1, layout, 4.0, 1000.0, case="T")
    assert applied == {1: -0.5}                                # girder 2's half is dropped
    assert all(eid.startswith("G1") for eid, _, _ in stage1.calls)


# ── lanes over a girder subset ─────────────────────────────────────────────

def test_lanes_over_girders_as_many_12ft_lanes_as_fit(layout):
    # girders 1-4 span 24 ft -> two 12 ft lanes centred on 12 ft
    assert lanes_over_girders(layout, [1, 2, 3, 4]) == [6.0, 18.0]
    assert lanes_over_girders(layout, [4, 1, 3]) == [6.0, 18.0]     # order-free


def test_lanes_over_girders_explicit_count_and_minimum_one_lane(layout):
    assert lanes_over_girders(layout, [1, 2, 3, 4], n_lanes=1) == [12.0]
    assert lanes_over_girders(layout, [1, 2, 3, 4], n_lanes=3) == [0.0, 12.0, 24.0]
    # girders 1-2 span only 8 ft: still one lane, centred at 4 ft
    assert lanes_over_girders(layout, [1, 2]) == [4.0]
    assert lanes_over_girders(layout, [3]) == [16.0]


def test_lanes_over_girders_custom_lane_width(layout):
    assert lanes_over_girders(layout, [1, 2, 3, 4], lane_width_ft=10.0) == [7.0, 17.0]


def test_add_lane_load_uses_hl93_lane_load_per_lane(model, layout):
    assert LANE_LOAD_KLF == 0.64
    total = add_lane_load(model, layout, [4.0])
    assert total == pytest.approx({1: -0.32, 2: -0.32})
    assert {c[2] for c in model.calls} == {"MOT-LANE"}


def test_add_lane_load_two_lanes_sum_and_custom_case(layout):
    m = _Model([1, 2, 3, 4])
    total = add_lane_load(m, layout, [4.0, 20.0], case="STG2", lane_load_klf=0.5)
    assert total == pytest.approx({1: -0.25, 2: -0.25, 3: -0.25, 4: -0.25})
    assert sum(total.values()) == pytest.approx(-1.0)
    assert m.total_by_case("STG2") == pytest.approx(-2.0)      # two elements per line


# ── design lanes ───────────────────────────────────────────────────────────

def test_design_lanes_defaults_centre_on_girder_group(layout):
    lanes = design_lanes(layout, roadway_width_ft=30.0)
    assert isinstance(lanes, RoadwayLanes)
    assert lanes.cl_offset == 12.0                          # (4-1)*8/2
    assert lanes.n_lanes == 2                               # int(30/12), LRFD 3.6.1.1.1
    assert lanes.lane_width_ft == 12.0 and lanes.roadway_width_ft == 30.0
    assert lanes.lane_edges == (0.0, 12.0, 24.0)
    assert lanes.lane_centers == (6.0, 18.0)
    assert lanes.curb_lines == (-3.0, 27.0)


def test_design_lanes_explicit_centreline_count_and_width(layout):
    lanes = design_lanes(layout, roadway_width_ft=24.0, lane_width_ft=11.0,
                         cl_offset=10.0, n_lanes=1)
    assert lanes.lane_edges == (4.5, 15.5)
    assert lanes.lane_centers == (10.0,)
    assert lanes.curb_lines == (-2.0, 22.0)


def test_design_lanes_at_least_one_lane(layout):
    assert design_lanes(layout, roadway_width_ft=11.0).n_lanes == 1
    assert design_lanes(layout, roadway_width_ft=47.9).n_lanes == 3


def test_add_design_lane_load_all_lanes_with_multiple_presence(model, layout):
    lanes = design_lanes(layout, roadway_width_ft=30.0)   # centres 6, 18
    total = add_design_lane_load(model, layout, lanes)
    # two lanes -> m = 1.0; lane at 6 ft: 25/75 to girders 1/2, lane at 18 ft: 75/25 to 3/4
    assert total == pytest.approx({1: -0.16, 2: -0.48, 3: -0.48, 4: -0.16})
    assert sum(total.values()) == pytest.approx(-2 * 0.64)
    assert {c[2] for c in model.calls} == {"LL-LANE"}


def test_add_design_lane_load_single_lane_m_1_20(layout):
    lanes = design_lanes(layout, roadway_width_ft=30.0)
    one = add_design_lane_load(_Model([1, 2, 3, 4]), layout, lanes, n_loaded=1)
    assert one == pytest.approx({1: -0.16 * 1.2, 2: -0.48 * 1.2})
    bare = add_design_lane_load(_Model([1, 2, 3, 4]), layout, lanes, n_loaded=1,
                                apply_multiple_presence=False, case="X")
    assert bare == pytest.approx({1: -0.16, 2: -0.48})


def test_add_design_lane_load_clamps_n_loaded(layout):
    lanes = design_lanes(layout, roadway_width_ft=30.0)
    m = _Model([1, 2, 3, 4])
    total = add_design_lane_load(m, layout, lanes, n_loaded=5)
    assert sum(total.values()) == pytest.approx(-2 * 0.64)      # only 2 lanes exist


# ── temporary barrier dead load ────────────────────────────────────────────

def test_barrier_dead_load_on_the_fascia(model, layout):
    applied = add_barrier_dead_load(model, layout, 0.0)
    assert applied == {1: -0.470}
    assert {c[2] for c in model.calls} == {"PCB"}
    heavy = add_barrier_dead_load(_Model([1, 2]), layout, 4.0, designation="PCB-42", case="TB")
    assert heavy == pytest.approx({1: -0.325, 2: -0.325})


# ── closure pour ───────────────────────────────────────────────────────────

def test_closure_pour_line_load_from_deck_thickness(layout):
    # 0.150 kcf * 1000 * (9/12 ft) * 2 ft = 225 plf
    assert CONCRETE_UNIT_WT_KCF == 0.150
    assert closure_pour_line_load_plf(layout) == pytest.approx(225.0)
    assert closure_pour_line_load_plf(layout, closure_width_ft=3.0) == pytest.approx(337.5)
    assert closure_pour_line_load_plf(layout, wet_factor=1.1) == pytest.approx(247.5)


def test_add_closure_pour_load_half_strip_on_edge_girder(model, layout):
    w = add_closure_pour_load(model, layout, 4)
    assert w == pytest.approx(-0.1125)                       # 225 plf * 0.5 / 1000
    assert model.calls == [("G4-0", pytest.approx(-0.1125), "CLOSURE"),
                           ("G4-1", pytest.approx(-0.1125), "CLOSURE")]
    full = add_closure_pour_load(_Model([1]), layout, 1, share=1.0, case="CP")
    assert full == pytest.approx(-0.225)


def test_add_closure_pour_load_requires_the_girder_in_the_phase(layout):
    with pytest.raises(ValueError, match="girder line 2"):
        add_closure_pour_load(_Model([1, 3]), layout, 2)
