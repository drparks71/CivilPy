#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""IFC writer edge paths built from hand-made :class:`EmitObject` records.

tests/structural/test_ifc_emit.py drives the writer through a truss
model; this file pokes the writer's own branches directly: the vector
helpers, degenerate prisms and cylinders, closed-vs-open loops, the
non-solid point/polyline → ``IfcAnnotation`` path, un-namespaced tags,
the ``annotations=False`` filter, and the missing-dependency error."""

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.util.element as ue                            # noqa: E402

from civilpy.structural import ifc_emit                           # noqa: E402
from civilpy.structural.ifc_emit import (                         # noqa: E402
    FT_TO_M, _Writer, _cross, _dot, _norm, _sub, _unit, objects_to_ifc,
)
from civilpy.structural.rhino_bim import EmitObject               # noqa: E402

SQUARE = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0))


def prism(tags, points=SQUARE, vector=(0.0, 0.0, 1.0)):
    return EmitObject("prism", "Deck", points, tags, vector)


def write(tmp_path, objects, **kw):
    p = tmp_path / "t.ifc"
    counts = objects_to_ifc(objects, p, **kw)
    return ifcopenshell.open(str(p)), counts


# ── vector helpers ────────────────────────────────────────────────────────

def test_vector_helpers():
    assert _sub((3, 2, 1), (1, 1, 1)) == (2, 1, 0)
    assert _dot((1, 2, 3), (4, 5, 6)) == 32
    assert _cross((1, 0, 0), (0, 1, 0)) == (0, 0, 1)
    assert _norm((3, 4, 0)) == 5.0
    assert _unit((0, 0, 2)) == (0.0, 0.0, 1.0)
    with pytest.raises(ValueError, match="zero-length"):
        _unit((0.0, 0.0, 0.0))


def test_missing_dependency_is_an_import_error(monkeypatch, tmp_path):
    def gone():
        raise ImportError("ifcopenshell is required for IFC export")

    monkeypatch.setattr(ifc_emit, "_require", gone)
    with pytest.raises(ImportError, match="ifcopenshell is required"):
        objects_to_ifc((), tmp_path / "x.ifc")
    assert not (tmp_path / "x.ifc").exists()


# ── degenerate geometry ───────────────────────────────────────────────────

def test_prism_whose_points_lie_along_the_extrusion_is_dropped(tmp_path):
    collinear = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 2.0))
    f, counts = write(tmp_path, (prism({"bim.type": "deck", "bim.id": "d"},
                                       points=collinear),))
    assert counts == {}
    assert len(f.by_type("IfcSlab")) == 0
    assert len(f.by_type("IfcRelContainedInSpatialStructure")) == 0


def test_prism_with_too_few_points_is_dropped(tmp_path):
    f, counts = write(tmp_path, (prism({"bim.type": "deck", "bim.id": "d"},
                                       points=SQUARE[:2]),))
    assert counts == {}


def test_closed_loop_is_not_closed_twice(tmp_path):
    closed = SQUARE + (SQUARE[0],)
    f_open, _ = write(tmp_path, (prism({"bim.type": "deck", "bim.id": "o"}),))
    poly_open = f_open.by_type("IfcSlab")[0].Representation.Representations[0] \
        .Items[0].SweptArea.OuterCurve
    assert len(poly_open.Points) == 5          # 4 corners + closing point

    f_closed, _ = write(tmp_path, (prism({"bim.type": "deck", "bim.id": "c"},
                                         points=closed),))
    poly_closed = f_closed.by_type("IfcSlab")[0].Representation.Representations[0] \
        .Items[0].SweptArea.OuterCurve
    assert len(poly_closed.Points) == 5        # already closed: left alone
    assert poly_closed.Points[0].Coordinates == poly_closed.Points[-1].Coordinates


def test_prism_profile_is_in_metres_and_extruded_along_its_vector(tmp_path):
    f, counts = write(tmp_path, (prism({"bim.type": "deck", "bim.id": "d"},
                                       vector=(0.0, 0.0, 0.5)),))
    assert counts == {"deck": 1}
    slab = f.by_type("IfcSlab")[0]
    assert slab.PredefinedType == "FLOOR"
    solid = slab.Representation.Representations[0].Items[0]
    assert solid.Depth == pytest.approx(0.5 * FT_TO_M)
    assert solid.Position.Axis.DirectionRatios == (0.0, 0.0, 1.0)
    xs = [p.Coordinates[0] for p in solid.SweptArea.OuterCurve.Points]
    assert max(xs) == pytest.approx(2.0 * FT_TO_M)


@pytest.mark.parametrize("points, radius", [
    (((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), 0.5),   # zero length
    (((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), 0.0),   # zero radius
    (((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), None),  # no radius at all
])
def test_degenerate_cylinders_are_dropped(tmp_path, points, radius):
    obj = EmitObject("cylinder", "Rivets", points, {"bim.type": "rivet", "bim.id": "r"},
                     radius_ft=radius)
    f, counts = write(tmp_path, (obj,))
    assert counts == {}
    assert len(f.by_type("IfcMechanicalFastener")) == 0


def test_vertical_cylinder_picks_a_non_parallel_reference(tmp_path):
    """The reference axis flips when the cylinder runs along Z."""
    up = EmitObject("cylinder", "R", ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                    {"bim.type": "rivet", "bim.id": "up"}, radius_ft=0.1)
    flat = EmitObject("cylinder", "R", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                      {"bim.type": "rivet", "bim.id": "flat"}, radius_ft=0.1)
    f, counts = write(tmp_path, (up, flat))
    assert counts == {"rivet": 2}
    by_name = {e.Name: e for e in f.by_type("IfcMechanicalFastener")}
    for name, axis in (("up", (0.0, 0.0, 1.0)), ("flat", (1.0, 0.0, 0.0))):
        pos = by_name[name].Representation.Representations[0].Items[0].Position
        assert pos.Axis.DirectionRatios == pytest.approx(axis)
        # RefDirection is perpendicular to the axis
        assert _dot(pos.Axis.DirectionRatios, pos.RefDirection.DirectionRatios) \
            == pytest.approx(0.0)


# ── non-solid records ─────────────────────────────────────────────────────

def test_polyline_becomes_a_curve_annotation(tmp_path):
    line = EmitObject("polyline", "Centerlines",
                      ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 5.0, 0.0)),
                      {"bim.type": "truss_chord_top", "bim.id": "CL-1"})
    f, counts = write(tmp_path, (line,))
    assert counts == {"truss_chord_top": 1}
    assert len(f.by_type("IfcMember")) == 0     # a polyline never becomes a solid
    (ann,) = f.by_type("IfcAnnotation")
    assert ann.Name == "CL-1"
    rep = ann.Representation.Representations[0]
    assert rep.RepresentationType == "Curve3D"
    pts = [p.Coordinates for p in rep.Items[0].Points]
    assert len(pts) == 3
    assert pts[1] == pytest.approx((10.0 * FT_TO_M, 0.0, 0.0))
    (rel,) = f.by_type("IfcRelContainedInSpatialStructure")
    assert rel.RelatedElements[0] is ann or rel.RelatedElements[0].id() == ann.id()


def test_single_point_polyline_is_an_annotation_without_geometry(tmp_path):
    line = EmitObject("polyline", "L", ((0.0, 0.0, 0.0),),
                      {"bim.type": "panel_point", "bim.id": "P"})
    f, counts = write(tmp_path, (line,))
    assert counts == {"panel_point": 1}
    (ann,) = f.by_type("IfcAnnotation")
    assert ann.Representation is None


def test_point_becomes_an_annotation_without_geometry(tmp_path):
    pt = EmitObject("point", "Panel Points", ((1.0, 2.0, 3.0),),
                    {"bim.type": "panel_point", "bim.id": "U1"})
    f, counts = write(tmp_path, (pt,))
    assert counts == {"panel_point": 1}
    (ann,) = f.by_type("IfcAnnotation")
    assert ann.Name == "U1" and ann.Representation is None
    assert ann.Description == "panel_point"


def test_annotations_false_drops_points_and_polylines_only(tmp_path):
    objs = (
        prism({"bim.type": "deck", "bim.id": "d"}),
        EmitObject("point", "P", ((0.0, 0.0, 0.0),), {"bim.type": "panel_point", "bim.id": "p"}),
        EmitObject("polyline", "L", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                   {"bim.type": "panel_point", "bim.id": "l"}),
    )
    f, counts = write(tmp_path, objs, annotations=False)
    assert counts == {"deck": 1}
    assert len(f.by_type("IfcAnnotation")) == 0
    assert len(f.by_type("IfcSlab")) == 1


# ── naming, tags and the container ────────────────────────────────────────

def test_untyped_and_unnamespaced_tags(tmp_path):
    obj = prism({"bim.id": "X-1", "note": "field verify", "mat.fy_ksi": "36"})
    f, counts = write(tmp_path, (obj,))
    assert counts == {"untyped": 1}
    (proxy,) = f.by_type("IfcBuildingElementProxy")
    assert proxy.Name == "X-1"
    assert proxy.Description is None
    psets = ue.get_psets(proxy)
    assert psets["CivilPy_other"]["note"] == "field verify"
    assert psets["CivilPy_mat"]["fy_ksi"] == "36"
    assert "CivilPy_bim" not in psets or "id" in psets["CivilPy_bim"]


@pytest.mark.xfail(strict=True, reason=(
    "BUG: ifc_emit._Writer.add reads obj.name as the fallback element name "
    "(ifc_emit.py:324) but EmitObject has no 'name' field, so any record "
    "without a bim.id tag raises AttributeError instead of being named by "
    "its bim.type"))
def test_record_without_bim_id_is_named_by_its_type(tmp_path):
    f, counts = write(tmp_path, (prism({"bim.type": "deck"}),))
    assert counts == {"deck": 1}
    assert f.by_type("IfcSlab")[0].Name == "deck"


def test_description_joins_the_descriptive_tags():
    assert _Writer._description({"truss.piece": "U0U1", "gusset.face": "out"},
                                "gusset_plate") == "gusset_plate | U0U1 | out"
    assert _Writer._description({}, "") is None


def test_header_identity_and_schema(tmp_path):
    f, _ = write(tmp_path, (prism({"bim.type": "deck", "bim.id": "d"}),),
                 name="SR 4", project="PID 1", site="Delaware", author="dp",
                 organization="D6")
    assert f.by_type("IfcProject")[0].Name == "PID 1"
    assert f.by_type("IfcSite")[0].Name == "Delaware"
    assert f.by_type("IfcBuilding")[0].Name == "SR 4"
    assert f.by_type("IfcPerson")[0].FamilyName == "dp"
    assert f.by_type("IfcOrganization")[0].Name == "D6"
    assert {u.Name for u in f.by_type("IfcSIUnit")} == {"METRE", "SQUARE_METRE", "CUBIC_METRE"}


def test_solids_and_annotations_are_contained_separately(tmp_path):
    objs = (prism({"bim.type": "deck", "bim.id": "d"}),
            EmitObject("point", "P", ((0.0, 0.0, 0.0),),
                       {"bim.type": "panel_point", "bim.id": "p"}))
    f, _ = write(tmp_path, objs)
    rels = f.by_type("IfcRelContainedInSpatialStructure")
    assert len(rels) == 2
    kinds = sorted(r.RelatedElements[0].is_a() for r in rels)
    assert kinds == ["IfcAnnotation", "IfcSlab"]
    assert all(r.RelatingStructure.is_a("IfcBuilding") for r in rels)


def test_unsupported_kind_is_dropped(tmp_path):
    """A mesh record has no IFC mapping yet: skipped, not mis-written."""
    mesh = EmitObject("mesh", "M", SQUARE, {"bim.type": "deck", "bim.id": "m"},
                      faces=((0, 1, 2, 3),))
    f, counts = write(tmp_path, (mesh,))
    assert counts == {}
    assert len(f.by_type("IfcProduct")) == 2   # just the site and the building
