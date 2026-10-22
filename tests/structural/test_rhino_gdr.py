#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""The ``gdr.*`` reader.  Authors a small tagged ``.3dm`` (two girder
lines with bearings and the document-level bridge parameters, exactly what the
C# GirderLines/GirderShape/GirderBearing commands stamp) and reads it back into
the canonical hub, mirroring the round-trip style of ``test_rhino_stm``."""

import warnings

import pytest

rhino3dm = pytest.importorskip("rhino3dm")

from civilpy.structural.rhino_gdr import GTAG, read_girder_model


def _tag(obj_attr, **kv):
    for k, v in kv.items():
        obj_attr.SetUserString(GTAG + k, str(v))


def _author_bridge(path):
    """A 2-girder, 2-span continuous frame in PLAN (feet): girders run along X
    at Y = 0 and 8 ft, supported at X = 0, 60, 120 ft (fixed at the pier)."""
    f = rhino3dm.File3dm()
    f.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Feet

    stations = [0.0, 60.0, 120.0]
    for line_no, y in ((1, 0.0), (2, 8.0)):
        # one polyline girder line per girder, spanning both spans
        pl = rhino3dm.Polyline()
        for x in stations:
            pl.Add(x, y, 0.0)
        crv = pl.ToPolylineCurve()
        ga = rhino3dm.ObjectAttributes()
        shape = "w24x104" if line_no == 1 else "W24 X 104"  # normalizer test
        _tag(ga, kind="girder", shape=shape, grade="Grade 50", line=line_no)
        f.Objects.AddCurve(crv, ga)
        # bearings: expansion at the abutments, fixed at the interior pier
        for x, fixity in ((0.0, "expansion"), (60.0, "fixed"),
                          (120.0, "expansion")):
            ba = rhino3dm.ObjectAttributes()
            _tag(ba, kind="support", fixity=fixity, line=line_no)
            f.Objects.AddPoint(rhino3dm.Point3d(x, y, 0.0), ba)

    # bridge-wide parameters ride on a gdr.kind=bridge marker object's user
    # text (rhino3dm cannot read RhinoDoc.Strings).
    da = rhino3dm.ObjectAttributes()
    _tag(da, kind="bridge", deck_t="7.5", deck_weff="84", deck_fc="4.5",
         ship_max="100", bolt_dia="0.875", bolt_spec="A325",
         bolt_hole="oversize", bolt_class="C")
    f.Objects.AddPoint(rhino3dm.Point3d(0.0, -4.0, 0.0), da)

    assert f.Write(str(path), 7)


@pytest.fixture
def bridge(tmp_path):
    p = tmp_path / "gdr_bridge.3dm"
    _author_bridge(p)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # AISC-db lookups, etc.
        return read_girder_model(str(p))


class TestGdrReader:
    def test_two_girder_lines(self, bridge):
        assert set(bridge.girder_lines) == {"1", "2"}
        # each girder line spans 2 segments (3 stations -> 2 elements)
        assert all(len(ids) == 2 for ids in bridge.girder_lines.values())
        assert len(bridge.model.elements) == 4

    def test_section_and_grade_on_elements(self, bridge):
        for elem in bridge.model.elements.values():
            assert elem.section == "W24X104"      # normalized both spellings
            assert elem.material == "Grade 50"
            assert elem.role == "girder"
            assert elem.midas_type == "BEAM"

    def test_line_metadata_preserved(self, bridge):
        lines = {e.metadata.get("gdr.line") for e in bridge.model.elements.values()}
        assert lines == {"1", "2"}

    def test_bearings_become_restraints(self, bridge):
        # 3 bearings x 2 lines = 6, but the two lines' ends are distinct nodes
        assert len(bridge.model.restraints) == 6
        presets = sorted(r.preset for r in bridge.model.restraints.values())
        assert presets == ["expansion", "expansion", "expansion",
                            "expansion", "fixed", "fixed"]

    def test_fixed_vs_expansion_dof(self, bridge):
        fixed = [r for r in bridge.model.restraints.values()
                 if r.preset == "fixed"]
        expansion = [r for r in bridge.model.restraints.values()
                     if r.preset == "expansion"]
        for r in fixed:                       # holds longitudinal (X)
            assert (r.fix_x, r.fix_y, r.fix_z) == (True, True, True)
        for r in expansion:                   # frees longitudinal (X)
            assert (r.fix_x, r.fix_y, r.fix_z) == (False, True, True)

    def test_bridge_parameters(self, bridge):
        assert bridge.deck_t == pytest.approx(7.5)
        assert bridge.deck_weff == pytest.approx(84.0)
        assert bridge.deck_fc == pytest.approx(4.5)
        assert bridge.ship_max == pytest.approx(100.0)
        assert (bridge.bolt_spec, bridge.bolt_hole, bridge.bolt_class) == (
            "A325", "oversize", "C")

    def test_geometry_in_feet(self, bridge):
        xs = sorted({round(n.x, 3) for n in bridge.model.nodes.values()})
        assert xs == [0.0, 60.0, 120.0]
        ys = sorted({round(n.y, 3) for n in bridge.model.nodes.values()})
        assert ys == [0.0, 8.0]


class TestSpliceWriteBack:
    """G8 -- write a designed splice's status/summary/checks back to a .3dm and
    read them back (the round-trip the C# GirderSplice command consumes)."""

    def _design(self):
        from civilpy.structural.aashto.lrfd import (
            design_rolled_splice, SpliceLoads, BoltSpec, PlatePair, WebPlate,
        )
        loads = SpliceLoads(dc1_m=20.0, dc2_m=5.0, dw_m=8.0,
                            ll_pos_m=280.0, ll_neg_m=-160.0, ll_neg_v=-30.0)
        plates = PlatePair("Grade 50", 0.5, 5.0, 0.5, 12.5, 2)
        return design_rolled_splice(
            "W24X131", "W24X104", loads, deck_thickness=8.0,
            deck_eff_width=96.0, rebar_area=6.0,
            bolts=BoltSpec("A325", 0.875, flange_threads_excluded=False,
                           web_threads_excluded=False, surface_class="C",
                           hole_type="oversize"),
            top_plates=plates, bottom_plates=plates,
            web_plate=WebPlate("Grade 50", 0.5, 2),
            top_flange_rows=2, bottom_flange_rows=2, web_rows=4,
            bolt_spacing=3.0, flange_edge=1.5, flange_end=1.5,
            web_edge=1.5, web_end=1.5, design_year=2016)

    def test_tags_and_roundtrip(self, tmp_path):
        from civilpy.structural.rhino_gdr import (
            splice_writeback_tags, write_splice_results, read_splice_results,
            SpliceMarker, GTAG,
        )
        design = self._design()
        tags = splice_writeback_tags(design)
        assert tags[GTAG + "status"] == "OK"           # synthetic splice passes
        assert "10 bolts/flange" in tags[GTAG + "summary"]
        # every checks row is a 5-field article|check|actual|allowable|verdict
        rows = tags[GTAG + "checks"].splitlines()
        assert rows and all(len(r.split("|")) == 5 for r in rows)

        p = tmp_path / "splice_results.3dm"
        n = write_splice_results(p, [
            SpliceMarker(point=(100.0, 0.0, 0.0), design=design, line="1")])
        assert n == 1
        got = read_splice_results(str(p))
        assert len(got) == 1
        m = got[0]
        assert m["status"] == "OK" and m["line"] == "1"
        assert m["point"][0] == pytest.approx(100.0)
        assert all(len(rec) == 5 for rec in m["checks"])
        assert all(rec[4] in ("OK", "NG", "NOTICE") for rec in m["checks"])
        # a smart-node marker minted a persistent gdr.id
        assert m["id"]

    def test_smart_node_attributes(self, tmp_path):
        """The gdr.splice.* attribute set round-trips: bolt spec, per-component
        grids, and the three plate stacks all land on the marker and read back
        as the same numbers the SpliceDesign carries."""
        from civilpy.structural.rhino_gdr import (
            splice_attribute_tags, write_splice_results, read_splice_results,
            SpliceMarker, GTAG,
        )
        design = self._design()
        assert design.spec is not None      # design_splice attached the input

        tags = splice_attribute_tags(design)
        # marker-level bolt spec mirrors the input
        assert tags[GTAG + "splice.bolt_spec"] == "A325"
        assert tags[GTAG + "splice.bolt_dia"] == "0.875"
        assert tags[GTAG + "splice.hole_type"] == "oversize"
        # every component carries a bolt count and a plate stack
        for part in ("tf", "bf", "web"):
            assert int(tags[f"{GTAG}splice.{part}.bolts"]) > 0
            assert float(tags[f"{GTAG}splice.{part}.plate_t"]) > 0

        p = tmp_path / "smart_splice.3dm"
        # display geometry is baked but only the marker carries gdr.kind
        write_splice_results(p, [
            SpliceMarker(point=(100.0, 0.0, 0.0), design=design, line="1",
                         id="fixed-guid-123")], display=True)
        got = read_splice_results(str(p))
        assert len(got) == 1                 # display objects are not markers
        a = got[0]
        assert a["id"] == "fixed-guid-123"   # a supplied id is preserved
        attrs = a["attrs"]
        # numeric attrs parse to float; the web bolt count matches the design
        assert attrs["web.bolts"] == float(design.web.total_bolts)
        assert attrs["tf.bolts"] == float(design.top_flange.total_bolts)
        assert attrs["bolt_dia"] == pytest.approx(0.875)
        assert attrs["bolt_spec"] == "A325"  # non-numeric stays a string

    def test_display_geometry_object_count(self, tmp_path):
        """With display=True the file holds the marker plus baked plate meshes
        and bolt-axis curves; disabling it writes the marker alone."""
        from civilpy.structural.rhino_gdr import (
            write_splice_results, SpliceMarker,
        )
        design = self._design()
        p_on = tmp_path / "disp_on.3dm"
        p_off = tmp_path / "disp_off.3dm"
        write_splice_results(p_on, [
            SpliceMarker(point=(0.0, 0.0, 0.0), design=design, line="1")],
            display=True)
        write_splice_results(p_off, [
            SpliceMarker(point=(0.0, 0.0, 0.0), design=design, line="1")],
            display=False)
        f_on = rhino3dm.File3dm.Read(str(p_on))
        f_off = rhino3dm.File3dm.Read(str(p_off))
        assert len(list(f_off.Objects)) == 1
        assert len(list(f_on.Objects)) > 1   # plates + bolt axes were baked


def test_missing_deck_params_warn(tmp_path):
    """Absent gdr.deck_t / gdr.deck_weff must warn loudly."""
    f = rhino3dm.File3dm()
    f.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Feet
    pl = rhino3dm.Polyline()
    pl.Add(0.0, 0.0, 0.0)
    pl.Add(60.0, 0.0, 0.0)
    ga = rhino3dm.ObjectAttributes()
    _tag(ga, kind="girder", shape="W24X104", grade="Grade 50", line=1)
    f.Objects.AddCurve(pl.ToPolylineCurve(), ga)
    p = tmp_path / "no_deck.3dm"
    assert f.Write(str(p), 7)

    with pytest.warns(UserWarning, match="deck_t"):
        b = read_girder_model(str(p))
    assert b.deck_t is None and b.deck_weff is None
    assert b.deck_fc == pytest.approx(4.0)   # falls back to the BDM default


def _author_midspan_bearing_bridge(path):
    """One girder line whose curves break at SHAPE TRANSITIONS (x = 45), not
    at the pier: the interior bearing at x = 60 lands mid-element, the way
    real authored bridges arrive."""
    f = rhino3dm.File3dm()
    f.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Feet
    for x0, x1, shape in ((0.0, 45.0, "W24X104"), (45.0, 120.0, "W24X131")):
        pl = rhino3dm.Polyline()
        pl.Add(x0, 0.0, 0.0)
        pl.Add(x1, 0.0, 0.0)
        ga = rhino3dm.ObjectAttributes()
        _tag(ga, kind="girder", shape=shape, grade="Grade 50", line=1)
        f.Objects.AddCurve(pl.ToPolylineCurve(), ga)
    for x, fixity in ((0.0, "expansion"), (60.0, "fixed"),
                      (120.0, "expansion")):
        ba = rhino3dm.ObjectAttributes()
        _tag(ba, kind="support", fixity=fixity, line=1)
        f.Objects.AddPoint(rhino3dm.Point3d(x, 0.0, 0.0), ba)
    da = rhino3dm.ObjectAttributes()
    _tag(da, kind="bridge", deck_t="7.5", deck_weff="84")
    f.Objects.AddPoint(rhino3dm.Point3d(0.0, -4.0, 0.0), da)
    assert f.Write(str(path), 7)


class TestMidElementBearing:
    @pytest.fixture
    def bridge(self, tmp_path):
        p = tmp_path / "midspan_bearing.3dm"
        _author_midspan_bearing_bridge(p)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return read_girder_model(str(p))

    def test_all_bearings_restrained(self, bridge):
        m = bridge.model
        xs = sorted(m.nodes[nid].x for nid in m.restraints)
        assert xs == pytest.approx([0.0, 60.0, 120.0])

    def test_element_split_at_bearing(self, bridge):
        m = bridge.model
        chain = bridge.girder_lines["1"]
        assert len(chain) == 3  # 2 authored curves -> 3 after the split
        spans = [(m.nodes[m.elements[e].node_a].x,
                  m.nodes[m.elements[e].node_b].x) for e in chain]
        assert spans == [pytest.approx((0.0, 45.0)),
                         pytest.approx((45.0, 60.0)),
                         pytest.approx((60.0, 120.0))]

    def test_split_halves_keep_section_and_metadata(self, bridge):
        m = bridge.model
        chain = bridge.girder_lines["1"]
        sections = [m.elements[e].section for e in chain]
        assert sections == ["W24X104", "W24X131", "W24X131"]
        assert all(m.elements[e].metadata.get("gdr.line") == "1"
                   for e in chain)
