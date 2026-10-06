#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""IFC backend: the format the model leaves in.

The point of IFC over DWG / STEP / STL is that it carries the engineering
with the geometry, so these tests are mostly about the tags surviving --
a plate that arrives in OpenBridge Modeler without its remaining thickness
and its rating factor is just a lump."""
import math

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.util.element as ue                          # noqa: E402

from civilpy.structural import bim                              # noqa: E402
from civilpy.structural import rhino_truss as rt                # noqa: E402
from civilpy.structural.ifc_emit import FT_TO_M, objects_to_ifc  # noqa: E402
from civilpy.structural.rhino_bim import EmitObject             # noqa: E402


def panel_truss():
    m = rt.TrussModel("test truss")
    y = 36.5
    for i, x in enumerate((0.0, 24.0, 48.0)):
        m.add_node(rt.TrussNode("U%d" % i, (x, y, 120.0), line="ON", span="5",
                                chord="U", pp=i, joint="1100%d" % i))
        m.add_node(rt.TrussNode("L%d" % i, (x, y, 95.0), line="ON", span="5",
                                chord="L", pp=i, joint="1200%d" % i))
    for i in (0, 1):
        m.members.append(rt.TrussMember("U%dU%d" % (i, i + 1), "U%d" % i,
                                        "U%d" % (i + 1), "2P24x9/16 4L4x4x3/8",
                                        role="truss_chord_top", line="ON", span="5"))
        m.members.append(rt.TrussMember("L%dL%d" % (i, i + 1), "L%d" % i,
                                        "L%d" % (i + 1), "2P24x9/16 4L4x4x3/8",
                                        role="truss_chord_bottom", line="ON", span="5"))
    m.members.append(rt.TrussMember("U0L1", "U0", "L1", "2P18x7/16 4L4x4x3/8",
                                    role="truss_diagonal", line="ON", span="5"))
    m.gussets.append(rt.GussetPlacement(
        "11000-out", "U0", ((0.0, 0.0), (55.0, 0.0), (55.0, 76.0), (0.0, 76.0)),
        work_point=(27.5, 64.0), thickness_in=0.625, joint="11000",
        t_remaining_in=0.5, rating_rf=0.985, governing="rivet shear"))
    return m


def write(tmp_path, model, **kw):
    p = tmp_path / "m.ifc"
    counts = objects_to_ifc(rt.truss_emit(model, lod=300), p,
                            name="test bridge", **kw)
    return ifcopenshell.open(str(p)), counts, p


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #
def test_ifc4_uses_a_building_and_ifc4x3_a_bridge(tmp_path):
    m = panel_truss()
    f4, _c, _p = write(tmp_path, m, schema="IFC4")
    assert f4.schema == "IFC4"
    assert [b.Name for b in f4.by_type("IfcBuilding")] == ["test bridge"]

    p = tmp_path / "x3.ifc"
    objects_to_ifc(rt.truss_emit(m, lod=300), p, schema="IFC4X3_ADD2",
                   name="test bridge")
    f3 = ifcopenshell.open(str(p))
    assert f3.schema == "IFC4X3"
    assert [b.Name for b in f3.by_type("IfcBridge")] == ["test bridge"]


def test_each_bim_type_becomes_the_right_ifc_class(tmp_path):
    f, counts, _p = write(tmp_path, panel_truss())
    names = {e.is_a() for e in f.by_type("IfcProduct")}
    assert {"IfcMember", "IfcPlate"} <= names
    chords = [e for e in f.by_type("IfcMember") if e.PredefinedType == "CHORD"]
    braces = [e for e in f.by_type("IfcMember") if e.PredefinedType == "BRACE"]
    assert len(chords) == 4 and len(braces) == 1
    assert len(f.by_type("IfcPlate")) == 1
    assert counts["truss_chord_top"] == 2
    assert counts["gusset_plate"] == 1


def test_elements_are_named_by_bim_id_and_placed_in_the_container(tmp_path):
    f, _c, _p = write(tmp_path, panel_truss())
    assert {e.Name for e in f.by_type("IfcPlate")} == {"11000-out"}
    rel = f.by_type("IfcRelContainedInSpatialStructure")
    contained = {e.Name for r in rel for e in r.RelatedElements}
    assert "11000-out" in contained and "U0U1" in contained


# --------------------------------------------------------------------------- #
# the engineering survives
# --------------------------------------------------------------------------- #
def test_a_gusset_plate_carries_its_engineering(tmp_path):
    """The whole argument for IFC over a mesh exchange."""
    f, _c, _p = write(tmp_path, panel_truss())
    plate = f.by_type("IfcPlate")[0]
    psets = ue.get_psets(plate)
    assert set(psets) >= {"CivilPy_bim", "CivilPy_gusset", "CivilPy_mat",
                          "CivilPy_pay"}
    g = psets["CivilPy_gusset"]
    assert g["joint"] == "11000"
    assert float(g["t_remaining_in"]) == 0.5
    assert float(g["loss_in"]) == pytest.approx(0.125)
    assert float(g["rf"]) == pytest.approx(0.985)
    assert g["governing"] == "rivet shear"
    assert float(psets["CivilPy_mat"]["fy_ksi"]) == 45.0
    assert psets["CivilPy_pay"]["item"] == "513E10220"


def test_tag_namespaces_become_separate_property_sets(tmp_path):
    f, _c, _p = write(tmp_path, panel_truss())
    member = [e for e in f.by_type("IfcMember") if e.Name == "U0U1"][0]
    psets = ue.get_psets(member)
    assert psets["CivilPy_bim"]["type"] == "truss_chord_top"
    assert psets["CivilPy_truss"]["spec"] == "2P24x9/16 4L4x4x3/8"
    assert "fy_ksi" in psets["CivilPy_mat"]
    # namespaces must not bleed into each other
    assert "spec" not in psets["CivilPy_bim"]


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def test_geometry_is_a_swept_solid_in_metres(tmp_path):
    """IFC is authored in metres; the emit is feet."""
    f, _c, _p = write(tmp_path, panel_truss())
    member = [e for e in f.by_type("IfcMember") if e.Name == "U0U1"][0]
    rep = member.Representation.Representations[0]
    assert rep.RepresentationType == "SweptSolid"
    solid = rep.Items[0]
    assert solid.is_a("IfcExtrudedAreaSolid")
    assert solid.Depth == pytest.approx(24.0 * FT_TO_M)      # 24 ft panel
    assert f.by_type("IfcSIUnit")[0].Name == "METRE"


def test_a_cylinder_becomes_a_circular_extrusion(tmp_path):
    m = panel_truss()
    m.gussets[0] = rt.GussetPlacement(
        **{**m.gussets[0].__dict__,
           "rivets": ((10.0, 60.0), (13.0, 60.0)), "rivet_diameter_in": 1.0})
    p = tmp_path / "r.ifc"
    counts = objects_to_ifc(rt.truss_emit(m, lod=300, rivets=True), p)
    f = ifcopenshell.open(str(p))
    assert counts["rivet"] == 2
    riv = f.by_type("IfcMechanicalFastener")
    assert len(riv) == 2
    solid = riv[0].Representation.Representations[0].Items[0]
    assert solid.SweptArea.is_a("IfcCircleProfileDef")
    assert solid.SweptArea.Radius == pytest.approx(0.5 / 12.0 * FT_TO_M)


def test_annotations_can_be_dropped(tmp_path):
    """Marker points read as clutter in most importers."""
    m = panel_truss()
    with_ann = tmp_path / "a.ifc"
    without = tmp_path / "b.ifc"
    objects_to_ifc(rt.truss_emit(m, lod=300), with_ann, annotations=True)
    objects_to_ifc(rt.truss_emit(m, lod=300), without, annotations=False)
    assert len(ifcopenshell.open(str(with_ann)).by_type("IfcAnnotation")) == 6
    assert list(ifcopenshell.open(str(without)).by_type("IfcAnnotation")) == []


def test_degenerate_geometry_is_skipped_not_written(tmp_path):
    objs = (EmitObject("prism", "L", ((0, 0, 0), (1, 0, 0), (1, 1, 0)),
                       {"bim.type": "deck", "bim.id": "flat"}, (0.0, 0.0, 0.0)),)
    p = tmp_path / "d.ifc"
    counts = objects_to_ifc(objs, p)
    assert counts == {}
    assert list(ifcopenshell.open(str(p)).by_type("IfcSlab")) == []


# --------------------------------------------------------------------------- #
# the review overlay
# --------------------------------------------------------------------------- #
def test_a_repair_reaches_ifc_both_as_an_overlay_and_on_its_target(tmp_path):
    """A reviewer must be able to isolate the proposed work *and* pick a
    member and see what is being done to it."""
    m = panel_truss()
    m.reviews.append(rt.ReviewItem(
        "RPR-1", "repair", "L0L1",
        bim.repair_tags("RPR-1", item="LC-1", target="L0L1",
                        sheet="94-105/247", plan_set="Stage 2")))
    f, counts, _p = write(tmp_path, m)
    assert counts["repair"] == 1

    overlay = f.by_type("IfcBuildingElementProxy")
    assert [o.Name for o in overlay] == ["RPR-1"]
    assert ue.get_psets(overlay[0])["CivilPy_repair"]["item"] == "LC-1"

    target = [e for e in f.by_type("IfcMember") if e.Name == "L0L1"][0]
    ps = ue.get_psets(target)["CivilPy_repair"]
    assert ps["item"] == "LC-1" and ps["count"] == "1"
    # and an untouched member says nothing about repairs
    other = [e for e in f.by_type("IfcMember") if e.Name == "U0U1"][0]
    assert "CivilPy_repair" not in ue.get_psets(other)


def test_two_repairs_on_one_member_are_both_kept(tmp_path):
    """A lower chord with pack-rust removal AND an LC-1 rebuild has to show
    both, not the last one written."""
    m = panel_truss()
    for k, item in enumerate(("LC-1", "PR-272"), 1):
        m.reviews.append(rt.ReviewItem(
            "RPR-%d" % k, "repair", "L0L1",
            bim.repair_tags("RPR-%d" % k, item=item, target="L0L1")))
    f, _c, _p = write(tmp_path, m)
    ps = ue.get_psets([e for e in f.by_type("IfcMember") if e.Name == "L0L1"][0])
    assert ps["CivilPy_repair"]["item"] == "LC-1"
    assert ps["CivilPy_repair2"]["item"] == "PR-272"
    assert ps["CivilPy_repair"]["count"] == "2"


def test_findings_and_repairs_land_on_different_layers_and_types(tmp_path):
    m = panel_truss()
    m.reviews.append(rt.ReviewItem(
        "RPR-1", "repair", "L0L1", bim.repair_tags("RPR-1", item="LC-1",
                                                   target="L0L1")))
    m.reviews.append(rt.ReviewItem(
        "FND-1", "finding", "L0L1",
        bim.finding_tags("FND-1", target="L0L1", year="2025",
                         summary="section loss at the bottom flange")))
    objs = rt.truss_emit(m, lod=300)
    layers = {o.tags.get("bim.type"): o.layer for o in objs
              if o.tags.get("bim.type") in ("repair", "finding")}
    assert layers["repair"] == "Review::Proposed Repairs"
    assert layers["finding"] == "Review::Inspection Findings"

    f, _c, _p = write(tmp_path, m)
    target = [e for e in f.by_type("IfcMember") if e.Name == "L0L1"][0]
    ps = ue.get_psets(target)
    assert ps["CivilPy_repair"]["item"] == "LC-1"
    assert ps["CivilPy_finding"]["year"] == "2025"
    assert "section loss" in ps["CivilPy_finding"]["summary"]


def test_a_review_item_pointing_nowhere_is_reported(tmp_path):
    """A repair whose target is not in the model is a mapping error worth
    seeing, not something to swallow."""
    m = panel_truss()
    m.reviews.append(rt.ReviewItem(
        "RPR-1", "repair", "9-ON-L99L100",
        bim.repair_tags("RPR-1", item="LC-1", target="9-ON-L99L100")))
    assert [i.id for i in rt.unresolved_reviews(m)] == ["RPR-1"]
    assert rt.review_objects(m, m.reviews[0]) == []

    m.reviews.append(rt.ReviewItem(
        "RPR-2", "repair", "L0L1", bim.repair_tags("RPR-2", item="LC-1",
                                                   target="L0L1")))
    assert [i.id for i in rt.unresolved_reviews(m)] == ["RPR-1"]


def test_the_repair_sleeve_wraps_its_member(tmp_path):
    m = panel_truss()
    m.reviews.append(rt.ReviewItem(
        "RPR-1", "repair", "L0L1", bim.repair_tags("RPR-1", item="LC-1",
                                                   target="L0L1")))
    sleeve = rt.review_objects(m, m.reviews[0], margin_in=3.0)[0]
    target = next(x for x in m.members if x.id == "L0L1")
    member = rt.member_objects(m, target, lod=300)[0]
    sw = max(p[1] for p in sleeve.points) - min(p[1] for p in sleeve.points)
    mw = max(p[1] for p in member.points) - min(p[1] for p in member.points)
    assert sw == pytest.approx(mw + 6.0 / 12.0)         # +3 in each side
    assert rt._norm(sleeve.vector) == pytest.approx(rt._norm(member.vector))
