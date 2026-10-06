#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Substructure reactions from a solved grillage (``civilpy.structural.substructure``).

The MIDAS client is a ``MagicMock`` whose ``result_table`` returns canned
``{"Reaction": {"HEAD": [...], "DATA": [...]}}`` responses, and the hub model
/ layout are small stubs exposing ``nodes`` (insertion-ordered, with
``coords``), ``restraints`` and ``inputs.spans_ft``.  The tests pin the exact
MIDAS request payload (table type, components, node keys, ``(ST)`` /
``(CB)`` suffix), the per-node parsing, the nearest-support-line binning,
and the AASHTO LRFD Table 3.4.1-1 Strength I / Service I factored sums.
"""

from unittest.mock import MagicMock

import pytest

from civilpy.structural.substructure import (
    COMPONENTS,
    DEFAULT_COMBOS,
    LOAD_TYPE,
    SubstructureUnit,
    _midas_node_ids,
    design_reactions,
    fetch_support_reactions,
    group_support_reactions,
    restrained_node_midas_ids,
    substructure_reaction_report,
    substructure_units,
)

HEAD = ["Node", *COMPONENTS]


# ── stubs ──────────────────────────────────────────────────────────────────

class _Node:
    def __init__(self, x, y=0.0, z=0.0):
        self.coords = (x, y, z)


class _Model:
    def __init__(self, nodes, restraints):
        self.nodes = dict(nodes)                 # insertion order = MIDAS id order
        self.restraints = {nid: object() for nid in restraints}


class _Layout:
    def __init__(self, spans):
        self.inputs = MagicMock(spans_ft=tuple(spans))


def _two_span():
    """Two 100 ft spans, two girder lines: bearings at x = 0, 100, 200 plus an
    unrestrained mid-span node (hub id "m") that must never be fetched."""
    nodes = {"a1": _Node(0.0, 0.0), "a2": _Node(0.0, 8.0),
             "m": _Node(50.0, 0.0),
             "p1": _Node(100.0, 0.0), "p2": _Node(100.0, 8.0),
             "b1": _Node(200.0, 0.0), "b2": _Node(200.0, 8.0)}
    model = _Model(nodes, ["a1", "a2", "p1", "p2", "b1", "b2"])
    return model, _Layout([100.0, 100.0])


def _resp(rows):
    return {"Reaction": {"HEAD": HEAD, "DATA": rows}}


# ── units / ids ────────────────────────────────────────────────────────────

def test_substructure_units_naming_and_stations():
    units = substructure_units(_Layout([80.0, 120.0, 80.0]))
    assert units == [SubstructureUnit(0, "Abutment 1", 0.0),
                     SubstructureUnit(1, "Pier 2", 80.0),
                     SubstructureUnit(2, "Pier 3", 200.0),
                     SubstructureUnit(3, "Abutment 2", 280.0)]
    assert [u.name for u in substructure_units(_Layout([60.0]))] == ["Abutment 1", "Abutment 2"]


def test_midas_node_ids_follow_insertion_order():
    model, _ = _two_span()
    assert _midas_node_ids(model) == {"a1": 1, "a2": 2, "m": 3, "p1": 4,
                                      "p2": 5, "b1": 6, "b2": 7}
    assert restrained_node_midas_ids(model) == [1, 2, 4, 5, 6, 7]


def test_restrained_ids_skip_restraints_on_missing_nodes():
    model = _Model({"n1": _Node(0.0)}, ["n1", "ghost"])
    assert restrained_node_midas_ids(model) == [1]


# ── fetch_support_reactions ────────────────────────────────────────────────

def test_fetch_support_reactions_request_payload_and_parsing():
    model, _ = _two_span()
    midas = MagicMock()
    midas.result_table.side_effect = [
        _resp([["1", "0", "0", "100", "0", "0", "0"],
               ["2", "1.5", "-2", "110.25", "0", "3", "0"]]),
        _resp([["1", "0", "0", "40", "0", "0", "0"]]),
    ]
    out = fetch_support_reactions(midas, model, ["DC1", "LL-LANE"])

    assert midas.result_table.call_count == 2
    first = midas.result_table.call_args_list[0]
    assert first.args == ("Reaction",)
    assert first.kwargs == {"table_type": "REACTIONG",
                            "components": ["Node", "FX", "FY", "FZ", "MX", "MY", "MZ"],
                            "node_elems": {"KEYS": [1, 2, 4, 5, 6, 7]},
                            "load_case_names": ["DC1(ST)"]}
    assert midas.result_table.call_args_list[1].kwargs["load_case_names"] == ["LL-LANE(ST)"]

    assert out == {"DC1": {1: (0.0, 0.0, 100.0, 0.0, 0.0, 0.0),
                           2: (1.5, -2.0, 110.25, 0.0, 3.0, 0.0)},
                   "LL-LANE": {1: (0.0, 0.0, 40.0, 0.0, 0.0, 0.0)}}
    assert all(isinstance(v, float) for v in out["DC1"][2])


def test_fetch_support_reactions_combination_suffix_and_dirty_rows():
    model, _ = _two_span()
    midas = MagicMock()
    midas.result_table.return_value = _resp([
        ["", "0", "0", "1", "0", "0", "0"],              # blank node id -> skipped
        ["abc", "0", "0", "1", "0", "0", "0"],           # junk node id -> skipped
        [None, "0", "0", "1", "0", "0", "0"],            # missing -> skipped
        ["4", "", None, "55", "0", "0", "0"],            # blank components -> 0.0
    ])
    out = fetch_support_reactions(midas, model, ["Strength I"], suffix="(CB)")
    assert midas.result_table.call_args.kwargs["load_case_names"] == ["Strength I(CB)"]
    assert out == {"Strength I": {4: (0.0, 0.0, 55.0, 0.0, 0.0, 0.0)}}


def test_fetch_support_reactions_empty_table_and_no_cases():
    model, _ = _two_span()
    midas = MagicMock()
    midas.result_table.return_value = {"Reaction": {"HEAD": HEAD, "DATA": []}}
    assert fetch_support_reactions(midas, model, ["DW"]) == {"DW": {}}
    midas.result_table.reset_mock()
    assert fetch_support_reactions(midas, model, []) == {}
    midas.result_table.assert_not_called()


# ── group_support_reactions ────────────────────────────────────────────────

def test_group_sums_nodes_onto_the_nearest_support_line():
    model, layout = _two_span()
    raw = {"DC1": {1: (1.0, 0.0, 100.0, 0.0, 0.0, 0.0),
                   2: (0.5, 0.0, 110.0, 0.0, 0.0, 0.0),
                   4: (0.0, 2.0, 300.0, 0.0, 0.0, 0.0),
                   5: (0.0, 1.0, 310.0, 0.0, 0.0, 0.0),
                   6: (0.0, 0.0, 100.0, 1.0, 0.0, 0.0),
                   7: (0.0, 0.0, 100.0, -1.0, 0.0, 0.0)},
           "LL-LANE": {4: (0.0, 0.0, 80.0, 0.0, 0.0, 5.0)}}
    g = group_support_reactions(model, layout, raw)
    assert set(g) == {"Abutment 1", "Pier 2", "Abutment 2"}
    assert g["Abutment 1"] == {"DC1": (1.5, 0.0, 210.0, 0.0, 0.0, 0.0)}
    assert g["Pier 2"] == {"DC1": (0.0, 3.0, 610.0, 0.0, 0.0, 0.0),
                           "LL-LANE": (0.0, 0.0, 80.0, 0.0, 0.0, 5.0)}
    assert g["Abutment 2"] == {"DC1": (0.0, 0.0, 200.0, 0.0, 0.0, 0.0)}
    # the FZ total over all units is the total applied load
    assert sum(v["DC1"][2] for v in g.values()) == 1020.0


def test_group_bins_off_station_nodes_to_the_nearest_unit_and_ignores_unknown_ids():
    nodes = {"n1": _Node(0.0), "n2": _Node(101.5), "n3": _Node(199.0), "n4": _Node(50.0)}
    model = _Model(nodes, list(nodes))
    layout = _Layout([100.0, 100.0])
    raw = {"DW": {2: (0.0, 0.0, 10.0, 0.0, 0.0, 0.0),      # 101.5 -> Pier 2
                  3: (0.0, 0.0, 20.0, 0.0, 0.0, 0.0),      # 199 -> Abutment 2
                  4: (0.0, 0.0, 7.0, 0.0, 0.0, 0.0),       # 50: tie -> earliest unit
                  99: (0.0, 0.0, 999.0, 0.0, 0.0, 0.0)}}   # not a hub node -> dropped
    g = group_support_reactions(model, layout, raw)
    assert g["Pier 2"] == {"DW": (0.0, 0.0, 10.0, 0.0, 0.0, 0.0)}
    assert g["Abutment 2"] == {"DW": (0.0, 0.0, 20.0, 0.0, 0.0, 0.0)}
    assert g["Abutment 1"] == {"DW": (0.0, 0.0, 7.0, 0.0, 0.0, 0.0)}
    assert 999.0 not in [c[2] for u in g.values() for c in u.values()]


def test_group_with_no_reactions_lists_every_unit_empty():
    model, layout = _two_span()
    assert group_support_reactions(model, layout, {}) == {
        "Abutment 1": {}, "Pier 2": {}, "Abutment 2": {}}
    assert group_support_reactions(model, layout, {"DC1": {}}) == {
        "Abutment 1": {}, "Pier 2": {}, "Abutment 2": {}}


# ── design_reactions ───────────────────────────────────────────────────────

def test_load_type_map_and_default_combos_are_lrfd_table_3_4_1_1():
    assert LOAD_TYPE == {"DC1": "DC", "DC2": "DC", "DW": "DW", "LL-LANE": "LL",
                         "MOT-LANE": "LL", "PCB": "DC", "CLOSURE": "DC"}
    assert DEFAULT_COMBOS["Strength I"] == {"DC": 1.25, "DW": 1.50, "LL": 1.75}
    assert DEFAULT_COMBOS["Service I"] == {"DC": 1.00, "DW": 1.00, "LL": 1.00}


def test_design_reactions_strength_i_and_service_i():
    grouped = {"Abutment 1": {"DC1": (2.0, 0.0, 100.0, 0.0, 0.0, 0.0),
                              "DC2": (0.0, 0.0, 10.0, 0.0, 0.0, 0.0),
                              "DW": (0.0, 0.0, 20.0, 0.0, 0.0, 0.0),
                              "LL-LANE": (0.0, 4.0, 40.0, 0.0, 0.0, 0.0),
                              "PCB": (0.0, 0.0, 6.0, 0.0, 0.0, 0.0),
                              "MYSTERY": (0.0, 0.0, 4.0, 0.0, 0.0, 1.0)},   # unknown -> DC
               "Abutment 2": {}}
    d = design_reactions(grouped)
    assert set(d) == {"Abutment 1", "Abutment 2"}
    s1 = d["Abutment 1"]["Strength I"]
    # FZ: 1.25*(100+10+6+4) + 1.5*20 + 1.75*40 = 150 + 30 + 70
    assert s1 == pytest.approx((2.5, 7.0, 250.0, 0.0, 0.0, 1.25))
    assert d["Abutment 1"]["Service I"] == pytest.approx((2.0, 4.0, 180.0, 0.0, 0.0, 1.0))
    assert d["Abutment 2"] == {"Strength I": (0.0,) * 6, "Service I": (0.0,) * 6}


def test_design_reactions_custom_combos_and_missing_factor_is_zero():
    grouped = {"Pier 2": {"DC1": (0.0, 0.0, 100.0, 0.0, 0.0, 0.0),
                          "LL-LANE": (0.0, 0.0, 40.0, 0.0, 0.0, 0.0)}}
    d = design_reactions(grouped, combos={"DC only": {"DC": 1.5},
                                          "Strength IV": {"DC": 1.50, "DW": 1.50}})
    assert d == {"Pier 2": {"DC only": (0.0, 0.0, 150.0, 0.0, 0.0, 0.0),
                            "Strength IV": (0.0, 0.0, 150.0, 0.0, 0.0, 0.0)}}
    assert "Strength I" not in d["Pier 2"]


# ── end-to-end report on a fake solved model ───────────────────────────────

def test_substructure_reaction_report_fetches_groups_and_combines():
    model, layout = _two_span()
    midas = MagicMock()

    def table(name, **kw):
        case = kw["load_case_names"][0]
        fz = {"DC1(ST)": 100.0, "LL-LANE(ST)": 40.0}[case]
        return _resp([[str(k), "0", "0", str(fz), "0", "0", "0"]
                      for k in kw["node_elems"]["KEYS"]])

    midas.result_table.side_effect = table
    rep = substructure_reaction_report(midas, model, layout, ["DC1", "LL-LANE"])
    assert set(rep) == {"by_case", "design", "units"}
    assert rep["units"] == ["Abutment 1", "Pier 2", "Abutment 2"]
    assert rep["by_case"]["Pier 2"]["DC1"][2] == 200.0            # two bearings
    assert rep["by_case"]["Pier 2"]["LL-LANE"][2] == 80.0
    assert rep["design"]["Pier 2"]["Strength I"][2] == pytest.approx(1.25 * 200 + 1.75 * 80)
    assert rep["design"]["Abutment 1"]["Service I"][2] == pytest.approx(280.0)
    assert midas.result_table.call_count == 2
    rep2 = substructure_reaction_report(midas, model, layout, ["DC1"],
                                        combos={"Service I": {"DC": 1.0}})
    assert rep2["design"]["Abutment 2"] == {"Service I": (0.0, 0.0, 200.0, 0.0, 0.0, 0.0)}
