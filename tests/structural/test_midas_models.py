#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#  SPDX-License-Identifier: MIT

"""MIDAS advanced-model payload builders
(civilpy.structural.midas_models): curved girders, bifurcated girders,
abutment connections, and nodal soil springs."""

import math

import pytest

from civilpy.structural import midas_models as mm


# ---------------------------------------------------------------- curved

def test_circular_curve_nodes_geometry():
    assign, grid = mm.circular_curve_nodes(
        radius=500.0, central_angle_deg=30.0, n_segments=8,
        girder_offsets=[0.0, 24.0])
    assert len(assign) == 2 * 9
    # station 0 of girder 0 is on the +Y axis at the inner radius
    n0 = assign[str(grid[(0, 0)])]
    assert n0["X"] == pytest.approx(0.0)
    assert n0["Y"] == pytest.approx(500.0)
    # outer girder rides radius 524
    outer = assign[str(grid[(1, 0)])]
    assert outer["Y"] == pytest.approx(524.0)


def test_curved_girder_model_element_counts():
    model = mm.curved_girder_model(
        radius=500.0, central_angle_deg=30.0, n_segments=8,
        girder_offsets=[0.0, 8.0, 16.0, 24.0], diaphragm_sect=2)
    assert len(model["NODE"]) == 36
    # 4*8 girder beams + 3*9 diaphragms
    assert len(model["ELEM"]) == 32 + 27
    assert model["meta"]["arc_length"] == pytest.approx(500.0 * math.radians(30.0))


def test_curved_girder_model_no_diaphragms():
    model = mm.curved_girder_model(
        radius=300.0, central_angle_deg=20.0, n_segments=4,
        girder_offsets=[0.0, 10.0])
    assert len(model["ELEM"]) == 2 * 4   # girder beams only


# ---------------------------------------------------------------- bifurcated

def test_bifurcated_girder_model():
    bif = mm.bifurcated_girder_model(
        stem_length=80.0, stem_segments=8,
        branches=[{"length": 60.0, "end_offset": -15.0, "segments": 6},
                  {"length": 60.0, "end_offset": 15.0, "segments": 6}])
    assert bif["gore_node"] == 9
    assert len(bif["NODE"]) == 9 + 6 + 6
    assert len(bif["ELEM"]) == 8 + 6 + 6
    assert len(bif["branch_end_nodes"]) == 2
    end1 = bif["NODE"][str(bif["branch_end_nodes"][0])]
    assert end1["X"] == pytest.approx(140.0)
    assert end1["Y"] == pytest.approx(-15.0)


def test_bifurcated_branches_share_gore():
    bif = mm.bifurcated_girder_model(
        stem_length=40.0, stem_segments=4,
        branches=[{"length": 30.0, "end_offset": -10.0, "segments": 3},
                  {"length": 30.0, "end_offset": 10.0, "segments": 3}])
    gore = bif["gore_node"]
    # first element of each branch starts at the gore node
    first_branch_elems = [e for e in bif["ELEM"].values()
                          if e["NODE"][0] == gore]
    assert len(first_branch_elems) == 2


# ---------------------------------------------------------------- abutments

def test_integral_abutment_rigid_link():
    out = mm.abutment_connection("integral", girder_end_nodes=[1, 10, 19, 28],
                                 seat_node=100)
    link = out["RIGD"]["100"]["ITEMS"][0]
    assert link["DOF"] == 111111
    assert link["S_NODE"] == [1, 10, 19, 28]


def test_semi_integral_abutment_bearings():
    out = mm.abutment_connection("semi-integral", girder_end_nodes=[1, 2],
                                 seat_node=100)
    assert len(out["ELNK"]) == 2
    sdr = out["ELNK"]["1"]["SDR"]
    assert sdr[2] > 1e6        # stiff vertical
    assert sdr[0] < 100.0      # free longitudinal


def test_semi_integral_custom_bearing_stiffness():
    out = mm.abutment_connection("semi-integral", girder_end_nodes=[5],
                                 seat_node=9, bearing_stiffness=[1, 2, 3, 4, 5, 6])
    assert out["ELNK"]["1"]["SDR"] == [1, 2, 3, 4, 5, 6]
    assert out["ELNK"]["1"]["NODE"] == [5, 9]


def test_abutment_connection_unknown_kind():
    with pytest.raises(ValueError):
        mm.abutment_connection("floating", girder_end_nodes=[1], seat_node=2)


# ---------------------------------------------------------------- springs

def test_soil_spring_supports_body():
    body = mm.soil_spring_supports({201: [10, 10, 50, 0, 0, 0],
                                    202: [12, 12, 60, 0, 0, 0]})
    assert set(body) == {"201", "202"}
    item = body["201"]["ITEMS"][0]
    assert item["TYPE"] == "LINEAR"
    assert item["SDR"] == [10, 10, 50, 0, 0, 0]


def test_soil_spring_supports_validates_vector_length():
    with pytest.raises(ValueError):
        mm.soil_spring_supports({1: [1, 2, 3]})


def test_lb_per_in_to_kip_per_ft():
    assert mm.lb_per_in_to_kip_per_ft(1000.0) == pytest.approx(12.0)


# ------------------------------------------------- shared encoders (S4)

def test_unit_block_defaults_kips_ft():
    u = mm.unit_block()
    assert u["1"] == {"FORCE": "KIPS", "DIST": "FT",
                      "HEAT": "BTU", "TEMPER": "F"}


def test_unit_block_for_maps_hub_labels():
    from civilpy.structural.structural_model import Units
    assert mm.unit_block_for(Units(force="kips", length="ft"))["1"]["FORCE"] == "KIPS"
    metric = mm.unit_block_for(Units(force="kN", length="m"))["1"]
    assert (metric["FORCE"], metric["DIST"]) == ("KN", "M")


def test_steel_material_block_shape():
    m = mm.steel_material_block("A709-50")["1"]
    assert m["TYPE"] == "USER" and m["NAME"] == "A709-50"
    assert m["PARAM"][0]["ELAST"] == mm.STEEL_PROPS["ELAST"]


def test_constraint_assign_wraps_flag_string():
    body = mm.constraint_assign({3: "1100000"})
    assert body["3"]["ITEMS"][0]["CONSTRAINT"] == "1100000"


# ------------------------------------------------- hub serializer (S4)

def _hub_truss():
    """A 3-node truss with a pin, a vertical roller, and a 600-kip load."""
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a = m.add_node(0, 0, 0, label="A")
    b = m.add_node(8, 0, 0, label="B")
    c = m.add_node(4, 0, 4, label="C")
    for ni, nj in [(a, b), (b, c), (a, c)]:
        m.add_element(ni.id, nj.id)
    m.add_restraint(a.id, preset="pin")
    m.add_restraint(b.id, preset="roller-v")
    m.add_load(c.id, fz=-600)
    return m, {"A": a.id, "B": b.id, "C": c.id}


def test_midas_payloads_table_set_and_order():
    m, _ = _hub_truss()
    p = mm.midas_payloads(m)
    assert list(p) == ["UNIT", "MATL", "SECT", "NODE", "ELEM", "CONS",
                       "STLD", "CNLD"]
    assert len(p["NODE"]) == 3
    assert len(p["ELEM"]) == 3


def test_midas_payloads_nodes_carry_3d_coords():
    m, _ = _hub_truss()
    p = mm.midas_payloads(m)
    zs = {n["Z"] for n in p["NODE"].values()}
    assert 4.0 in zs                      # out-of-plane / height survives


def test_midas_payloads_constraints_from_full_6dof():
    m, _ = _hub_truss()
    p = mm.midas_payloads(m)
    constraints = sorted(s["ITEMS"][0]["CONSTRAINT"]
                         for s in p["CONS"].values())
    assert constraints == ["0100000", "1100000"]   # roller-v, pin


def test_midas_payloads_fixed_support_keeps_moment_dof():
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a = m.add_node(0, 0, 0)
    b = m.add_node(10, 0, 0)
    m.add_element(a.id, b.id)
    m.add_restraint(a.id, preset="fixed")
    p = mm.midas_payloads(m)
    assert p["CONS"][str(1)]["ITEMS"][0]["CONSTRAINT"] == "1100010"


def test_midas_payloads_load_lands_in_cnld_and_stld():
    m, ids = _hub_truss()
    p = mm.midas_payloads(m)
    assert {c["NAME"] for c in p["STLD"].values()} == {"default"}
    item = next(iter(p["CNLD"].values()))["ITEMS"][0]
    assert item["FZ"] == pytest.approx(-600.0)
    assert item["LCNAME"] == "default"


def test_midas_payloads_element_references_section_and_material():
    m, _ = _hub_truss()
    p = mm.midas_payloads(m)
    elem = next(iter(p["ELEM"].values()))
    assert elem["SECT"] == 1 and elem["MATL"] == 1
    assert "1" in p["SECT"] and "1" in p["MATL"]
    # no element carries a real gdr.shape label -- placeholder square, not
    # a rolled shape.
    assert p["SECT"]["1"]["SECT_BEFORE"]["SHAPE"] == "SB"


def test_midas_payloads_uses_real_shape_per_element():
    """A girder-line hub with real AISC labels gets a real SECT per shape
    (SHAPE="H") -- not the generic placeholder square. Regression test for
    the box-beam-looking generic section that shipped when midas_payloads
    always emitted a single placeholder regardless of elem.section."""
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a = m.add_node(0, 0, 0)
    b = m.add_node(30, 0, 0)
    c = m.add_node(60, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", section="W24X104",
                  material="Grade 50")
    m.add_element(b.id, c.id, midas_type="BEAM", section="W24X131",
                  material="Grade 50")

    p = mm.midas_payloads(m)
    assert len(p["SECT"]) == 2
    for body in p["SECT"].values():
        assert body["SECT_BEFORE"]["SHAPE"] == "H"
    names = {body["SECT_NAME"] for body in p["SECT"].values()}
    assert names == {"W24X104", "W24X131"}
    elems = list(p["ELEM"].values())
    assert elems[0]["SECT"] != elems[1]["SECT"]
    assert len(p["MATL"]) == 1   # both elements share "Grade 50"


def test_midas_payloads_sect_matches_model_length_unit():
    """SECT dimensions must be expressed in the model's own units.length --
    MIDAS applies one DIST unit to the whole model (NODE coordinates AND
    section dimensions). Regression test for the bug where rolled_i_section_
    block always sent inches while a feet model's UNIT table declared FT,
    silently scaling every section 12x into a huge, self-intersecting box
    that swallowed the girder spacing. Only applies to the db_name=None
    (built-up/historic, user-input dimensions) fallback -- by default
    sections reference the AISC db directly and carry no dimensions at all."""
    from civilpy.structural import steel
    from civilpy.structural.structural_model import StructuralModel, Units

    m = StructuralModel(units=Units(force="kips", length="ft"))
    a = m.add_node(0, 0, 0)
    b = m.add_node(30, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", section="W24X104")

    p = mm.midas_payloads(m, db_name=None)
    sid = next(iter(p["SECT"]))
    h_ft = p["SECT"][sid]["SECT_BEFORE"]["SECT_I"]["vSIZE"][0]
    expected_ft = steel.W("W24X104").depth.to("ft").magnitude
    assert h_ft == pytest.approx(expected_ft, abs=1e-6)
    # a W24 depth in inches (~24) would be a dead giveaway of the old bug
    assert h_ft < 5.0


def test_midas_payloads_sect_references_aisc_db_by_default():
    from civilpy.structural.structural_model import StructuralModel, Units

    m = StructuralModel(units=Units(force="kips", length="ft"))
    a = m.add_node(0, 0, 0)
    b = m.add_node(30, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", section="W24X104")

    p = mm.midas_payloads(m)
    sid = next(iter(p["SECT"]))
    before = p["SECT"][sid]["SECT_BEFORE"]
    assert before["DATATYPE"] == 1
    assert before["SECT_I"] == {"DB_NAME": "AISC10(US)",
                                 "SECT_NAME": "W24X104"}


def test_hub_section_material_blocks_length_unit_override():
    from civilpy.structural.structural_model import StructuralModel, Units

    m = StructuralModel(units=Units(force="kips", length="ft"))
    a = m.add_node(0, 0, 0)
    b = m.add_node(30, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", section="W24X104")

    blocks_ft = mm.hub_section_material_blocks(m, db_name=None)
    blocks_in = mm.hub_section_material_blocks(m, db_name=None,
                                                length_unit="in")
    h_ft = blocks_ft["SECT"]["1"]["SECT_BEFORE"]["SECT_I"]["vSIZE"][0]
    h_in = blocks_in["SECT"]["1"]["SECT_BEFORE"]["SECT_I"]["vSIZE"][0]
    assert h_in == pytest.approx(h_ft * 12.0, rel=1e-4)


def test_midas_payloads_mixed_labeled_and_unlabeled_elements():
    """An element with no section label still gets a valid (placeholder)
    SECT id distinct from the real per-shape ids, rather than crashing or
    silently sharing a real shape's section."""
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a = m.add_node(0, 0, 0)
    b = m.add_node(30, 0, 0)
    c = m.add_node(60, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", section="W24X104")
    m.add_element(b.id, c.id, midas_type="BEAM")   # no shape label

    p = mm.midas_payloads(m)
    assert len(p["SECT"]) == 2   # 1 real shape + 1 placeholder
    elems = list(p["ELEM"].values())
    labeled_sect, unlabeled_sect = elems[0]["SECT"], elems[1]["SECT"]
    assert labeled_sect != unlabeled_sect
    assert p["SECT"][str(labeled_sect)]["SECT_BEFORE"]["SHAPE"] == "H"
    assert p["SECT"][str(unlabeled_sect)]["SECT_BEFORE"]["SHAPE"] == "SB"


def test_push_midas_reports_per_table():
    """push_midas reports {table: {"sent": n}} against a fake client,
    mirroring TrussBridge.to_midas (no live session)."""
    m, _ = _hub_truss()

    class FakeMidas:
        def __init__(self):
            self.calls = []

        def put_db(self, table, assign):
            self.calls.append(table)
            return {"ok": True}

    fake = FakeMidas()
    report = mm.push_midas(m, midas=fake)
    assert fake.calls == list(mm.midas_payloads(m))
    assert report["NODE"] == {"sent": 3}
    assert report["CONS"] == {"sent": 2}


def test_push_midas_keeps_going_on_table_error():
    m, _ = _hub_truss()

    class FlakyMidas:
        def put_db(self, table, assign):
            if table == "CONS":
                raise RuntimeError("CONS rejected")
            return {}

    report = mm.push_midas(m, midas=FlakyMidas())
    assert "error" in report["CONS"]
    assert report["NODE"] == {"sent": 3}     # other tables still sent


class TestLoadOhVehicles:
    """The ODOT BDM Section 908 vehicle loader."""

    class _FakeClient:
        def __init__(self, existing=None):
            self.existing = dict(existing or {})
            self.deleted, self.put = [], None

        def request(self, method, command, body=None, **kw):
            if method == "GET":
                return {"MVHL": self.existing}
            if method == "DELETE":
                self.deleted.append(command.rsplit("/", 1)[-1])
                return {}
            self.put = body
            self.existing = {
                k: {"VEHICLE_LOAD_NAME": v.get("VEHICLE_LOAD_NAME")}
                for k, v in body["Assign"].items()}
            return {}

    def _load(self, **kw):
        from civilpy.structural.midas_models import load_oh_vehicles
        c = self._FakeClient()
        return c, load_oh_vehicles(c, **kw)

    def test_loads_exactly_the_bdm_set(self):
        from civilpy.structural.aashto.vehicles import BDM_908_RATING_LOADS
        c, out = self._load(include_design=False)
        names = set(out["pushed"].values())
        assert names == set(BDM_908_RATING_LOADS)

    def test_excludes_vehicles_the_bdm_does_not_specify(self):
        c, out = self._load()
        names = set(out["pushed"].values())
        for unused in ("AASHTO National Rating Load", "4F1", "AML",
                       "H15-44", "HS-25"):
            assert unused not in names

    def test_design_loads_always_go_in_as_db_records(self):
        """HL-93 must be pushed even with ``use_standard_db=False``.

        LRFD 3.6.1.3.1 superimposes the 0.640 klf design lane ON the truck
        (or tandem); a user-defined "Truck/Lane" record takes the ENVELOPE
        of the two instead, so a hand-written HL-93 is low by the whole
        lane component.  Only the code-driven DB entry combines them --
        which is why these four are DB records whatever the flag says.
        Previously the flag skipped them entirely and a rating ran with no
        design load at all.
        """
        for db in (False, True):
            c, out = self._load(include_design=True, use_standard_db=db)
            pushed = set(out["pushed"].values())
            assert {"HL-93 truck", "HL-93 tandem"} <= pushed, db
            assert "HL-93 truck" in out["standard_db"]
            assert set(out["design_loads"]) >= {"HL-93 truck", "HL-93 tandem"}

    def test_design_loads_can_be_declined(self):
        c, out = self._load(include_design=False)
        assert "HL-93 truck" not in out["pushed"].values()

    def test_defaults_to_user_defined_with_explicit_axles(self):
        c, out = self._load(include_design=False)
        assert out["standard_db"] == []
        assert out["im_applied"] is False        # IM dropped on user records
        body = c.put["Assign"]["1"]
        assert body["USER_LOAD_TYPE"] == "Truck/Lane"
        assert body["LOAD_ITEMS"]

    def test_permit_loads_are_user_defined_even_in_db_mode(self):
        c, out = self._load(include_design=False, use_standard_db=True)
        assert set(out["user_defined"]) == {"S-PL60T", "S-PL65T"}

    def test_replace_clears_existing_first(self):
        from civilpy.structural.midas_models import load_oh_vehicles
        c = self._FakeClient({"1": {}, "2": {}, "3": {}})
        load_oh_vehicles(c, replace=True, include_design=False)
        assert c.deleted == ["3", "2", "1"]

    def test_lane_load_gets_no_impact_bdm_924_4_c(self):
        """BDM 924.4.C: no dynamic load allowance on the lane portion."""
        c, out = self._load(include_design=True, use_standard_db=True)
        by_name = {v["VEHICLE_LOAD_NAME"]: v
                   for v in c.put["Assign"].values()}
        assert by_name["HS20-44 lane"]["VEH_DEFAULT"]["DYN_LOAD_ALLOWANCE"] == 0.0
        assert by_name["HL-93 truck"]["VEH_DEFAULT"]["DYN_LOAD_ALLOWANCE"] == 33.0
        assert by_name["HL-93 tandem"]["VEH_DEFAULT"]["DYN_LOAD_ALLOWANCE"] == 33.0


class TestConcreteSectionDispatch:
    """A concrete girder must not leave as an AISC database lookup.

    Before this dispatch existed, a box beam labelled ``"CB27-48"`` was
    exported as ``DATATYPE: 1`` into ``AISC10(US)`` -- a name that
    database does not contain -- with A709 steel at 490 pcf.  MIDAS
    stored it without complaint, so every analysis ran on a section that
    was not there.
    """

    def _hub(self):
        from civilpy.structural.box_beam_pipeline import (
            structural_model_from_box)

        return structural_model_from_box("CB27-48", 70.0, 3, mesh_ft=0)

    def test_box_girder_exports_as_a_psc_value_section(self):
        from civilpy.structural.midas_models import midas_payloads

        p = midas_payloads(self._hub())
        box = next(v for v in p["SECT"].values()
                   if v["SECT_NAME"] == "CB27-48")
        assert box["SECTTYPE"] == "PSC"
        assert box["SECT_BEFORE"]["SHAPE"] == "VALU"
        assert "DB_NAME" not in str(box)
        key = next(v for v in p["SECT"].values()
                   if v["SECT_NAME"] == "KEY-CB27-48")
        assert key["SECT_BEFORE"]["SHAPE"] == "VALU"

    def test_concrete_members_get_concrete_not_steel(self):
        from civilpy.structural.midas_models import midas_payloads

        p = midas_payloads(self._hub())
        by_name = {m["NAME"]: m["PARAM"][0] for m in p["MATL"].values()}
        for name in ("PS-5500psi", "GROUT-5000psi", "Deck-4500psi"):
            assert by_name[name]["DEN"] == pytest.approx(0.150)
            assert by_name[name]["ELAST"] < 1_000_000    # ksf, not steel

    def test_tie_rods_are_steel_and_round(self):
        """PSBD-1-25 sheet 1: a 1 in ASTM A307 rod.  Modelling it as
        5500 psi concrete gave it roughly a seventh of the right axial
        stiffness and a density it does not have."""
        from civilpy.structural.midas_models import midas_payloads

        hub = self._hub()
        p = midas_payloads(hub)
        rod = next(m for m in p["MATL"].values() if m["NAME"] == "A307-rod")
        assert rod["PARAM"][0]["ELAST"] == pytest.approx(4_176_000.0)  # ksf
        assert rod["PARAM"][0]["DEN"] == pytest.approx(0.490)
        sect = next(s for s in p["SECT"].values()
                    if s["SECT_NAME"] == "ROD-1in")
        assert sect["SECT_BEFORE"]["SHAPE"] == "SR"      # solid round, not SB
        assert sect["SECT_BEFORE"]["SECT_I"]["vSIZE"] == pytest.approx([1 / 12], abs=1e-6)
        rods = [e for e in hub.elements.values() if e.role == "tie-rod"]
        assert rods and all(e.material == "A307-rod" for e in rods)

    def test_lane_lines_are_weightless_dummies(self):
        from civilpy.structural.midas_models import DUMMY_PROPS, midas_payloads

        p = midas_payloads(self._hub())
        dummy = next(m for m in p["MATL"].values() if m["NAME"] == "DUMMY")
        assert dummy["PARAM"][0]["DEN"] == 0.0
        assert dummy["PARAM"][0]["ELAST"] == DUMMY_PROPS["ELAST"]

    def test_solid_and_open_cells_are_separate_sections(self):
        """The void stops at the end blocks and the diaphragms."""
        from civilpy.structural.midas_models import midas_payloads

        p = midas_payloads(self._hub())
        names = {s["SECT_NAME"] for s in p["SECT"].values()}
        assert {"CB27-48", "CB27-48-SOLID"} <= names
        solid = next(s for s in p["SECT"].values()
                     if s["SECT_NAME"] == "CB27-48-SOLID")
        assert "INNER_POLYGON" not in solid["SECT_BEFORE"]["SECT_I"]
        open_ = next(s for s in p["SECT"].values()
                     if s["SECT_NAME"] == "CB27-48")
        assert "INNER_POLYGON" in open_["SECT_BEFORE"]["SECT_I"]

    def test_section_coordinates_use_the_model_length_unit(self):
        """The hub is in feet; a 48 in box must go out as 4 ft."""
        from civilpy.structural.midas_models import midas_payloads

        p = midas_payloads(self._hub())
        box = next(v for v in p["SECT"].values()
                   if v["SECT_NAME"] == "CB27-48")
        assert box["SECT_BEFORE"]["SECT_I"]["vSIZE"][:2] == [2.25, 4.0]

    def test_material_blocks_rescale_with_the_length_unit(self):
        from civilpy.structural.midas_models import (
            concrete_material_block, steel_material_block)

        ksf = concrete_material_block(fc_psi=4500)["1"]["PARAM"][0]
        ksi = concrete_material_block(fc_psi=4500,
                                      length_unit="in")["1"]["PARAM"][0]
        assert ksi["ELAST"] == pytest.approx(ksf["ELAST"] / 144.0, rel=1e-6)
        assert ksi["DEN"] == pytest.approx(ksf["DEN"] / 1728.0, rel=1e-6)
        s = steel_material_block(length_unit="in")["1"]["PARAM"][0]
        assert s["ELAST"] == pytest.approx(29000.0, rel=1e-3)

    def test_unknown_length_unit_is_refused(self):
        from civilpy.structural.midas_models import concrete_material_block

        with pytest.raises(ValueError, match="unsupported model length unit"):
            concrete_material_block(length_unit="cubit")


@pytest.mark.parametrize("rel", [("000011", "000000"), ("000000", "000110"),
                                 ("100000", "000011")])
def test_midas_payloads_releases_and_beta(rel):
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a, b = m.add_node(0, 0, 0), m.add_node(10, 0, 0)
    m.add_element(a.id, b.id, midas_type="BEAM", releases=rel, beta_deg=35.0)
    m.add_restraint(a.id, preset="fixed")
    p = mm.midas_payloads(m)
    assert p["ELEM"]["1"]["ANGLE"] == 35.0
    item = p["FRLS"]["1"]["ITEMS"][0]
    assert (item["FLAG_I"], item["FLAG_J"]) == (rel[0] + "0", rel[1] + "0")
    assert list(p).index("FRLS") == list(p).index("ELEM") + 1


def test_midas_payloads_no_frls_without_releases():
    m, _ = _hub_truss()
    assert "FRLS" not in mm.midas_payloads(m)


@pytest.mark.parametrize("start,end", [(0.0, 1.0), (0.25, 0.75)])
def test_midas_payloads_partial_and_point_beam_loads(start, end):
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a, b = m.add_node(0, 0, 0), m.add_node(10, 0, 0)
    e = m.add_element(a.id, b.id, midas_type="BEAM")
    m.add_restraint(a.id, preset="fixed")
    m.add_beam_load(e.id, -1.0, start=start, end=end)
    m.add_beam_load(e.id, -5.0, kind="point", start=0.4)
    items = mm.midas_payloads(m)["BMLD"]["1"]["ITEMS"]
    assert (items[0]["TYPE"], items[0]["D"][:2]) == ("UNILOAD", [start, end])
    assert (items[1]["TYPE"], items[1]["D"][0], items[1]["P"][0]) == ("CONLOAD", 0.4, -5.0)


# ── groups, load groups, self weight (construction stages) ───────────────────

def _grouped_frame():
    from civilpy.structural.structural_model import StructuralModel
    m = StructuralModel()
    a = m.add_node(0, 0, 0)
    b = m.add_node(10, 0, 0)
    c = m.add_node(20, 0, 0)
    g1 = m.add_element(a.id, b.id, midas_type="BEAM")
    g2 = m.add_element(b.id, c.id, midas_type="BEAM")
    m.set_group([g1.id], "Girder")
    m.set_group([g2.id], "Girder-2")
    m.add_restraint(a.id, preset="pin")
    m.add_body_force("Self Weight", group="SW")
    m.add_beam_load(g1.id, -0.5, case="Wet Concrete", group="WetConc D1")
    m.add_load(c.id, fz=-10, case="Barrier", group="DC2")
    return m, (a, b, c), (g1, g2)


def test_midas_payloads_emits_grup_with_elements_and_their_nodes():
    m, (a, b, c), (g1, g2) = _grouped_frame()
    p = mm.midas_payloads(m)
    assert list(p).index("GRUP") == list(p).index("ELEM") + 1
    rows = {r["NAME"]: r for r in p["GRUP"].values()}
    assert rows["Girder"]["E_LIST"] == [1] and rows["Girder"]["N_LIST"] == [1, 2]
    assert rows["Girder-2"]["E_LIST"] == [2] and rows["Girder-2"]["N_LIST"] == [2, 3]
    assert m.element_groups() == {"Girder": [g1.id], "Girder-2": [g2.id]}


def test_midas_payloads_load_groups_and_body_force():
    m, _, _ = _grouped_frame()
    p = mm.midas_payloads(m)
    order = list(p)
    assert order.index("STLD") < order.index("LDGR") < order.index("BODF") < order.index("CNLD") < order.index("BMLD")
    assert [r["NAME"] for r in p["LDGR"].values()] == ["DC2", "WetConc D1", "SW"]
    assert p["BODF"] == {"1": {"LCNAME": "Self Weight", "GROUP_NAME": "SW", "FV": [0.0, 0.0, -1.0]}}
    # a body-force-only case still gets its STLD row (MIDAS refuses a BODF naming an unknown case)
    assert "Self Weight" in {c["NAME"] for c in p["STLD"].values()}
    item = next(iter(p["BMLD"].values()))["ITEMS"][0]
    assert item["GROUP_NAME"] == "WetConc D1"
    assert next(iter(p["CNLD"].values()))["ITEMS"][0]["GROUP_NAME"] == "DC2"


def test_midas_payloads_without_groups_is_unchanged():
    m, _ = _hub_truss()
    p = mm.midas_payloads(m)
    assert "GRUP" not in p and "LDGR" not in p and "BODF" not in p


def test_time_dependent_material_blocks_shapes_and_units():
    t = mm.time_dependent_material_blocks("C4500", matl_id=3, fc_psi=4500, humidity_pct=70, v_s_in=4.2,
                                          curing_age_days=3, tdmt_id=2, tdme_id=2)
    tdmt = t["TDMT"]["2"]; tdme = t["TDME"]["2"]
    assert tdmt["CODE"] == "AASHTO" and tdmt["STR"] == pytest.approx(4500 * 144 / 1000)   # ksf
    assert tdmt["VOL"] == pytest.approx(4.2 / 12) and tdmt["HU"] == 70 and tdmt["AGE"] == 3
    assert tdme["CODENAME"] == "ACI" and (tdme["A"], tdme["B"]) == (4.0, 0.85)
    assert t["TMAT"] == {"3": {"TDMT_NAME": "C4500 C&S", "TDME_NAME": "C4500 Comp"}}
    inch = mm.time_dependent_material_blocks("C4500", matl_id=3, fc_psi=4500, force_unit="LBF", length_unit="in")
    assert inch["TDMT"]["1"]["STR"] == pytest.approx(4500) and inch["TDMT"]["1"]["VOL"] == pytest.approx(3.5)
    with pytest.raises(ValueError):
        mm.time_dependent_material_blocks("x", matl_id=1, fc_psi=4000, force_unit="KN")
