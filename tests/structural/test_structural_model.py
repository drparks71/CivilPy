#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Unit tests for the canonical ``StructuralModel`` hub.

Pure data structure -- no optional dependencies, nothing to skip.
"""

import pytest

from civilpy.structural.structural_model import (
    DOF_NAMES,
    MEMBER_TYPES,
    SUPPORT_PRESETS,
    Element,
    Load,
    LoadCase,
    Node,
    Restraint,
    Result,
    StructuralModel,
    Units,
)


def _example_1():
    """FHWA-NHI-17-071 Example 1 topology, expressed in the hub (feet)."""
    m = StructuralModel()
    coords = {"A": (0, 0), "B": (4.5, 0), "C": (27, 0),
              "D": (4.5, 16 / 3), "E": (9, 16 / 3), "F": (18, 16 / 3)}
    nodes = {label: m.add_node(x, y, label=label) for label, (x, y) in coords.items()}
    m.add_restraint(nodes["A"].id, preset="pin")
    m.add_restraint(nodes["C"].id, preset="roller-v")
    m.add_load(nodes["E"].id, fy=-600)
    m.add_load(nodes["F"].id, fy=-600)
    for a, b in [("A", "B"), ("A", "D"), ("B", "C"), ("B", "D"), ("D", "E"),
                 ("B", "E"), ("E", "F"), ("C", "F"), ("C", "E")]:
        m.add_element(nodes[a].id, nodes[b].id)
    return m, nodes


class TestNode:
    def test_defaults_and_id(self):
        n = Node(1.0, 2.0)
        assert n.coords == (1.0, 2.0, 0.0)
        assert n.label is None
        assert isinstance(n.id, str) and len(n.id) > 0

    def test_ids_are_unique(self):
        assert Node(0, 0).id != Node(0, 0).id


class TestRestraint:
    def test_preset_constraint_strings(self):
        # 7-char DX DY DZ RX RY RZ RW, '1' = fixed
        assert Restraint.from_preset("n", "pin").to_constraint_string() == "1100000"
        assert Restraint.from_preset("n", "roller-v").to_constraint_string() == "0100000"
        assert Restraint.from_preset("n", "roller-h").to_constraint_string() == "1000000"
        assert Restraint.from_preset("n", "fixed").to_constraint_string() == "1100010"
        assert Restraint.from_preset("n", "custom").to_constraint_string() == "0000000"

    def test_to_2d_projection(self):
        assert Restraint.from_preset("n", "pin").to_2d() == (True, True)
        assert Restraint.from_preset("n", "roller-v").to_2d() == (False, True)
        assert Restraint.from_preset("n", "roller-h").to_2d() == (True, False)

    def test_flags_order_matches_dof_names(self):
        r = Restraint("n", fix_x=True, fix_rz=True)
        flags = dict(zip(DOF_NAMES, r.flags()))
        assert flags == {"x": True, "y": False, "z": False,
                         "rx": False, "ry": False, "rz": True}

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError):
            Restraint.from_preset("n", "bogus")


class TestElement:
    def test_member_type_default_is_auto(self):
        assert Element("a", "b").member_type == "auto"
        assert set(MEMBER_TYPES) == {"auto", "tie", "strut", "beam"}

    def test_invalid_member_type_raises(self):
        with pytest.raises(ValueError):
            Element("a", "b", member_type="cable")

    def test_overrides(self):
        e = Element("a", "b", member_type="tie", midas_type="TENS", role="diagonal")
        assert (e.member_type, e.midas_type, e.role) == ("tie", "TENS", "diagonal")


class TestLoadsAndCases:
    def test_load_force_vector_and_default_case(self):
        load = Load("n", fy=-600)
        assert load.force == (0.0, -600.0, 0.0)
        assert load.case == "default"

    def test_add_load_registers_case(self):
        m = StructuralModel()
        n = m.add_node(0, 0)
        m.add_load(n.id, fy=-10, case="DL")
        assert "DL" in m.load_cases
        assert isinstance(m.load_cases["DL"], LoadCase)

    def test_loads_in_case_grouping(self):
        m = StructuralModel()
        n = m.add_node(0, 0)
        m.add_load(n.id, fy=-10, case="DL")
        m.add_load(n.id, fy=-5, case="LL")
        m.add_load(n.id, fx=2, case="LL")
        assert len(m.loads_in_case("DL")) == 1
        assert len(m.loads_in_case("LL")) == 2
        assert m.cases() == ["DL", "LL"]


class TestModelBuilders:
    def test_add_element_validates_node_ids(self):
        m = StructuralModel()
        a = m.add_node(0, 0)
        with pytest.raises(KeyError):
            m.add_element(a.id, "does-not-exist")

    def test_restraint_explicit_flags_override_preset(self):
        m = StructuralModel()
        a = m.add_node(0, 0)
        # pin preset then force fix_z too (custom-ish 3D pin)
        r = m.add_restraint(a.id, preset="pin", fix_z=True)
        assert r.flags() == (True, True, True, False, False, False)
        assert r.preset == "pin"

    def test_node_by_label(self):
        m, nodes = _example_1()
        assert m.node_by_label("E").id == nodes["E"].id
        with pytest.raises(KeyError):
            m.node_by_label("Z")

    def test_units_default_kips_ft(self):
        assert StructuralModel().units == Units()
        assert (Units().force, Units().length) == ("kips", "ft")

    def test_explicit_ids_preserved(self):
        m = StructuralModel()
        a = m.add_node(0, 0, id="node-A")
        b = m.add_node(1, 0, id="node-B")
        e = m.add_element(a.id, b.id, id="elem-1")
        assert a.id == "node-A" and e.id == "elem-1"
        assert "node-B" in m.nodes


class TestIntegrityCheck:
    def test_clean_model_has_no_problems(self):
        m, _ = _example_1()
        assert m.check() == []

    def test_unsupported_model_flagged_as_mechanism(self):
        m = StructuralModel()
        a = m.add_node(0, 0)
        b = m.add_node(1, 0)
        m.add_element(a.id, b.id)
        assert any("mechanism" in p for p in m.check())

    def test_dangling_node_named(self):
        m, nodes = _example_1()
        lonely = m.add_node(99, 99, label="Z")  # connected to nothing
        problems = m.check()
        assert any("Z" in p and "not connected" in p for p in problems)

    def test_coincident_element_nodes_flagged(self):
        m = StructuralModel()
        a = m.add_node(0, 0)
        b = m.add_node(0, 0)  # same coords, different id
        m.add_restraint(a.id, preset="pin")
        m.add_element(a.id, b.id)
        assert any("coincident" in p for p in m.check())


class TestResult:
    def test_result_defaults(self):
        r = Result()
        assert r.case == "default"
        assert r.element_forces == {} and r.reactions == {}

    def test_result_holds_forces_and_reactions(self):
        r = Result(case="DL", element_forces={"e1": 1012.5},
                   reactions={"nA": (0, 600, 0, 0, 0, 0)})
        assert r.element_forces["e1"] == pytest.approx(1012.5)
        assert r.reactions["nA"][1] == pytest.approx(600)


def test_repr_is_informative():
    m, _ = _example_1()
    text = repr(m)
    assert "6 nodes" in text and "9 elements" in text and "2 loads" in text


class TestFrameSchema:
    @pytest.mark.parametrize("bad", [("00000", "000000"), ("000002", "000000"),
                                     ("000000",)])
    def test_release_flags_validated(self, bad):
        from civilpy.structural.structural_model import Element
        with pytest.raises(ValueError):
            Element("a", "b", releases=bad)

    def test_strain_and_body_force_register_cases(self):
        m = StructuralModel()
        a, b = m.add_node(0, 0), m.add_node(1, 0)
        e = m.add_element(a.id, b.id)
        m.add_element_strain(e.id, 1e-4, case="camber")
        m.add_body_force("SW")
        assert {"camber", "SW"} <= set(m.cases())
        with pytest.raises(KeyError):
            m.add_element_strain("nope", 1e-4)

    def test_material_shear_modulus_default(self):
        from civilpy.structural.structural_model import MaterialProperties
        assert MaterialProperties(e=29000.0, poisson=0.3).shear_modulus == pytest.approx(29000 / 2.6)
        assert MaterialProperties(e=29000.0, g=11200.0).shear_modulus == 11200.0
