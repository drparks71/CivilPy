"""Stage-by-stage fallback solver: single stage = plain solve, later-added
members start unstressed, a removed prop hands its reaction back so the
final state equals the never-propped structure, removed elements release
their forces."""
import pytest

from civilpy.structural import frame_analysis as fa
from civilpy.structural.construction_sequence import (BoundaryActivation, ConstructionSequence, ElementActivation,
                                                      ElementDeactivation, LoadActivation, Stage)
from civilpy.structural.staged_analysis import staged_solve
from civilpy.structural.structural_model import MaterialProperties, SectionProperties, StructuralModel


FIXED = dict(fix_x=True, fix_y=True, fix_z=True, fix_rx=True, fix_ry=True, fix_rz=True)   # full 3-D fixity


def _props(m):
    m.material_properties["steel"] = MaterialProperties(e=29000 * 144, poisson=0.3, density=0.490)
    m.section_properties["W"] = SectionProperties(area=0.1, iy=0.05, iz=0.05, j=0.01, asy=0.0, asz=0.0)


def _beam(elements, x=10.0):
    """Nodes 0..n along X, beam elements between them."""
    m = StructuralModel()
    _props(m)
    nodes = [m.add_node(k * x, 0, 0, id=f"n{k}") for k in range(elements + 1)]
    els = [m.add_element(f"n{k}", f"n{k + 1}", midas_type="BEAM", section="W", material="steel", id=f"e{k}")
           for k in range(elements)]
    return m, nodes, els


def test_single_stage_matches_plain_solve():
    m, _, els = _beam(2)
    m.add_restraint("n0", **FIXED)
    m.add_beam_load("e0", -1.0, case="dead", group="DL")
    m.add_beam_load("e1", -1.0, case="dead", group="DL")
    m.set_group(["e0", "e1"], "Beam")
    seq = ConstructionSequence([Stage("All", 1, activate=[ElementActivation("Beam")], loads=[LoadActivation("DL")])])
    plain = fa.solve(m, ["dead"], store=False)["dead"]
    staged = staged_solve(m, seq)
    final = staged.final()
    for eid in ("e0", "e1"):
        assert final.end_forces[eid] == pytest.approx(plain.end_forces[eid], abs=1e-9)
    assert final.displacements["n2"] == pytest.approx(plain.displacements["n2"], abs=1e-12)
    assert staged.approximate is True


def test_member_added_later_starts_unstressed():
    m, _, _ = _beam(2)
    m.add_restraint("n0", **FIXED)
    m.add_beam_load("e0", -1.0, case="dead", group="DL1")
    m.set_group(["e0"], "First"); m.set_group(["e1"], "Second")
    seq = ConstructionSequence([Stage("S1", 1, activate=[ElementActivation("First")], loads=[LoadActivation("DL1")]),
                                Stage("S2", 1, activate=[ElementActivation("Second")])])
    res = staged_solve(m, seq)
    s1, s2 = res.stages
    assert "e1" not in s1.cumulative.end_forces
    assert all(abs(v) < 1e-12 for v in s2.cumulative.end_forces["e1"])          # nothing loads it
    assert s2.cumulative.end_forces["e0"] == pytest.approx(s1.cumulative.end_forces["e0"])
    assert res.element_history("e1")[0][1] is None


def test_removed_prop_returns_its_reaction():
    """Cantilever loaded while propped at the tip, prop removed: the final
    moments / deflection equal the never-propped cantilever (linear elastic)."""
    m, _, _ = _beam(2)
    m.add_restraint("n0", **FIXED)
    m.add_restraint("n2", fix_z=True)                       # the temporary prop
    for e in ("e0", "e1"):
        m.add_beam_load(e, -2.0, case="dead", group="DL")
    m.set_group(["e0", "e1"], "Beam")
    seq = ConstructionSequence(
        [Stage("Propped", 1, activate=[ElementActivation("Beam")], boundaries=[BoundaryActivation("Prop", "ORIGINAL")],
               loads=[LoadActivation("DL")]),
         Stage("Prop out", 1, remove_boundaries=["Prop"])],
        boundary_groups=["Prop"])
    res = staged_solve(m, seq, restraint_groups={"Prop": ["n2"]})
    # reference: never propped
    ref = StructuralModel(); _props(ref)
    for k in range(3):
        ref.add_node(k * 10.0, 0, 0, id=f"n{k}")
    for k in range(2):
        ref.add_element(f"n{k}", f"n{k + 1}", midas_type="BEAM", section="W", material="steel", id=f"e{k}")
        ref.add_beam_load(f"e{k}", -2.0, case="dead")
    ref.add_restraint("n0", **FIXED)
    plain = fa.solve(ref, ["dead"], store=False)["dead"]
    propped, final = res.stages[0].cumulative, res.final()
    assert abs(propped.displacements["n2"][2]) < 1e-9                              # held while propped
    assert final.displacements["n2"][2] == pytest.approx(plain.displacements["n2"][2], rel=1e-6)
    assert final.end_forces["e0"][4] == pytest.approx(plain.end_forces["e0"][4], rel=1e-6)   # root moment
    assert "n2" not in final.reactions


def test_removed_element_releases_its_force():
    """Two-bar hanger: a temporary tie removed hands its force to the beam."""
    m, _, _ = _beam(1)
    m.add_restraint("n0", **FIXED)
    top = m.add_node(10.0, 0, 10.0, id="top")
    m.add_restraint("top", fix_x=True, fix_y=True, fix_z=True)
    m.add_element("n1", "top", midas_type="TRUSS", section="W", material="steel", id="tie")
    m.add_load("n1", fz=-5.0, case="dead", group="P")
    m.set_group(["e0"], "Beam"); m.set_group(["tie"], "Tie")
    seq = ConstructionSequence([
        Stage("Tied", 1, activate=[ElementActivation("Beam"), ElementActivation("Tie")], loads=[LoadActivation("P")]),
        Stage("Tie cut", 1, deactivate=[ElementDeactivation("Tie")])])
    res = staged_solve(m, seq)
    tied = res.stages[0].cumulative
    assert tied.element_forces["tie"] > 0                                        # the tie carried part of P
    final = res.final()
    ref, _, _ = _beam(1)
    ref.add_restraint("n0", **FIXED)
    ref.add_load("n1", fz=-5.0, case="dead")
    plain = fa.solve(ref, ["dead"], store=False)["dead"]
    assert final.end_forces["e0"] == pytest.approx(plain.end_forces["e0"], abs=1e-9)
    assert final.displacements["n1"][2] == pytest.approx(plain.displacements["n1"][2], rel=1e-6)
    assert "tie" not in final.end_forces and res.stages[1].removed_elements == ["tie"]


def test_self_weight_only_on_newly_activated_elements():
    m, _, _ = _beam(2)
    m.add_restraint("n0", **FIXED)
    m.add_body_force("SW", group="SW")
    m.set_group(["e0"], "A"); m.set_group(["e1"], "B")
    seq = ConstructionSequence([Stage("S1", 1, activate=[ElementActivation("A")], loads=[LoadActivation("SW")]),
                                Stage("S2", 1, activate=[ElementActivation("B")])])
    res = staged_solve(m, seq)
    w = 0.490 * 0.1                                                              # kip/ft
    # stage 1: root moment w L^2 / 2 on the 10 ft cantilever; stage 2 adds the second span's weight
    m1 = abs(res.stages[0].cumulative.end_forces["e0"][4]); m2 = abs(res.stages[1].cumulative.end_forces["e0"][4])
    assert m1 == pytest.approx(w * 10 ** 2 / 2, rel=1e-6)
    assert m2 == pytest.approx(w * 20 ** 2 / 2, rel=1e-6)
    inc2 = res.stages[1].increment
    assert abs(inc2.end_forces["e0"][4]) == pytest.approx(w * 20 ** 2 / 2 - w * 10 ** 2 / 2, rel=1e-6)
