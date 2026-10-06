#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Workspace loading by extension and ``--boring`` resolution.

Covers the branches tests/cli/test_shell.py leaves alone: the table,
terrain and 3dm loaders (optional deps are faked through
``session.require``), the ``as <name>`` rule for multi-object files, and
every failure path of :meth:`Workspace.resolve_boring`.
"""

import types

import pytest

from civilpy.cli import session
from civilpy.cli.registry import CliError
from civilpy.cli.session import CliContext, LoadedObject, Workspace

from tests.geotechnical.test_boring import DIGGS_FIXTURE

SECOND_HOLE = """
  <samplingFeature>
    <Borehole gml:id="Borehole_B-002">
      <gml:name>B-002</gml:name>
      <totalMeasuredDepth uom="ft">5</totalMeasuredDepth>
    </Borehole>
  </samplingFeature>
"""

TWO_HOLE_FIXTURE = DIGGS_FIXTURE.replace(
    "</samplingFeature>", "</samplingFeature>" + SECOND_HOLE, 1)

NO_HOLE_FIXTURE = DIGGS_FIXTURE[:DIGGS_FIXTURE.index("<samplingFeature>")] + \
    DIGGS_FIXTURE[DIGGS_FIXTURE.index("</samplingFeature>") + len("</samplingFeature>"):]


@pytest.fixture()
def ws():
    return Workspace()


# ── dispatch on extension ─────────────────────────────────────────────────

def test_missing_file_is_a_cli_error(ws, tmp_path):
    with pytest.raises(CliError, match="no such file"):
        ws.load(str(tmp_path / "ghost.xml"))


def test_unknown_extension_lists_the_known_ones(ws, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("x")
    with pytest.raises(CliError, match=r"don't know how to load '.txt'.*\.3dm"):
        ws.load(str(p))


def test_csv_loads_as_a_table_named_by_stem(ws, tmp_path):
    p = tmp_path / "piles.csv"
    p.write_text("pile,length_ft\nP1,40\nP2,45\n")
    (lo,) = ws.load(str(p))
    assert lo.kind == "table"
    assert lo.name == "piles"
    assert lo.summary == "2 rows × 2 columns"
    assert list(lo.obj.columns) == ["pile", "length_ft"]
    assert lo.source == str(p)
    assert ws.objects["piles"] is lo


def test_xlsx_loads_as_a_table_and_as_name_renames(ws, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "book.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.active.append([1, 2])
    wb.active.append([3, 4])
    wb.active.append([5, 6])
    wb.save(p)
    (lo,) = ws.load(str(p), name="rows")
    assert lo.kind == "table" and lo.name == "rows"
    assert lo.summary == "3 rows × 2 columns"
    assert "rows" in ws.objects and "book" not in ws.objects


def test_las_loads_a_terrain(ws, tmp_path, monkeypatch):
    from civilpy.transportation.terrain import Terrain

    p = tmp_path / "ground.las"
    p.write_bytes(b"LASF")
    seen = {}
    monkeypatch.setattr(session, "require",
                        lambda module, extra: seen.setdefault("req", (module, extra)))
    sentinel = object()
    monkeypatch.setattr(Terrain, "from_las",
                        classmethod(lambda cls, path: seen.setdefault("path", path) and sentinel))
    (lo,) = ws.load(str(p))
    assert seen["req"] == ("laspy", "geo")
    assert seen["path"] == p
    assert lo.kind == "terrain" and lo.obj is sentinel
    assert lo.name == "ground" and lo.summary == "LiDAR TIN surface"


def _fake_rhino3dm(model):
    class File3dm:
        read_paths = []

        @staticmethod
        def Read(path):
            File3dm.read_paths.append(path)
            return model

    return types.SimpleNamespace(File3dm=File3dm)


def test_3dm_loads_a_rhino_model(ws, tmp_path, monkeypatch):
    p = tmp_path / "bridge.3dm"
    p.write_bytes(b"3D Geometry File Format")
    model = types.SimpleNamespace(Objects=[1, 2, 3], Layers=[1])
    fake = _fake_rhino3dm(model)
    monkeypatch.setattr(session, "require", lambda module, extra: fake)
    (lo,) = ws.load(str(p))
    assert fake.File3dm.read_paths == [str(p)]
    assert lo.kind == "3dm" and lo.obj is model
    assert lo.summary == "3 objects, 1 layers"


def test_3dm_unreadable_is_a_cli_error(ws, tmp_path, monkeypatch):
    p = tmp_path / "broken.3dm"
    p.write_bytes(b"nope")
    monkeypatch.setattr(session, "require",
                        lambda module, extra: _fake_rhino3dm(None))
    with pytest.raises(CliError, match="could not read broken.3dm"):
        ws.load(str(p))
    assert ws.objects == {}


def test_missing_extra_hint_reaches_the_loader(ws, tmp_path, monkeypatch):
    """``require`` raising (laspy not installed) aborts the load cleanly."""
    p = tmp_path / "ground.las"
    p.write_bytes(b"LASF")

    def missing(module, extra):
        raise CliError(f"this command needs the '{extra}' extra (missing module: {module})")

    monkeypatch.setattr(session, "require", missing)
    with pytest.raises(CliError, match="needs the 'geo' extra"):
        ws.load(str(p))
    assert ws.objects == {}


# ── DIGGS specifics ───────────────────────────────────────────────────────

def test_diggs_with_two_holes_loads_both(ws, tmp_path):
    p = tmp_path / "site.xml"
    p.write_text(TWO_HOLE_FIXTURE)
    loaded = ws.load(str(p))
    assert [lo.name for lo in loaded] == ["B-001-0-21", "B-002"]
    assert loaded[0].summary == "7.5 ft, 1 SPT, 1 gradations, 1 samples"
    assert loaded[1].summary == "5 ft, 0 SPT, 0 gradations, 0 samples"
    assert set(ws.objects) == {"B-001-0-21", "B-002"}


def test_diggs_without_depth_says_so(ws, tmp_path):
    p = tmp_path / "site.xml"
    p.write_text(TWO_HOLE_FIXTURE.replace(
        '<totalMeasuredDepth uom="ft">5</totalMeasuredDepth>', ""))
    loaded = ws.load(str(p))
    assert loaded[1].summary.startswith("depth unknown")


def test_as_name_refused_for_multi_object_files(ws, tmp_path):
    p = tmp_path / "site.xml"
    p.write_text(TWO_HOLE_FIXTURE)
    with pytest.raises(CliError, match="holds 2 objects"):
        ws.load(str(p), name="one")
    assert ws.objects == {}


def test_diggs_with_no_boreholes(ws, tmp_path):
    p = tmp_path / "empty.xml"
    p.write_text(NO_HOLE_FIXTURE)
    with pytest.raises(CliError, match="empty.xml: no boreholes found"):
        ws.load(str(p))


# ── resolve_boring ────────────────────────────────────────────────────────

def test_resolve_loaded_boring_by_name(ws, tmp_path):
    p = tmp_path / "B-001.xml"
    p.write_text(DIGGS_FIXTURE)
    (lo,) = ws.load(str(p), name="b1")
    assert ws.resolve_boring("b1") is lo.obj


def test_resolve_rejects_a_loaded_non_boring(ws, tmp_path):
    p = tmp_path / "piles.csv"
    p.write_text("a\n1\n")
    ws.load(str(p))
    with pytest.raises(CliError, match="'piles' is a loaded table, not a boring"):
        ws.resolve_boring("piles")


def test_resolve_single_hole_path_loads_implicitly(ws, tmp_path):
    p = tmp_path / "B-001.xml"
    p.write_text(DIGGS_FIXTURE)
    hole = ws.resolve_boring(str(p))
    assert hole.boring_id == "B-001-0-21"
    assert ws.objects == {}  # implicit loads do not enter the workspace


def test_resolve_multi_hole_path_names_the_holes(ws, tmp_path):
    p = tmp_path / "site.xml"
    p.write_text(TWO_HOLE_FIXTURE)
    with pytest.raises(CliError, match=r"site.xml holds several holes \(B-001-0-21, B-002\)"):
        ws.resolve_boring(str(p))


def test_resolve_unknown_reference(ws):
    with pytest.raises(CliError, match="neither a loaded boring nor a DIGGS file path"):
        ws.resolve_boring("nothing-here")


def test_context_defaults():
    ctx = CliContext()
    assert ctx.interactive is False
    assert isinstance(ctx.workspace, Workspace)
    assert ctx.workspace.objects == {} and ctx.workspace.log == []
    lo = LoadedObject("n", "table", None, "src", "s")
    assert (lo.name, lo.kind, lo.source, lo.summary) == ("n", "table", "src", "s")
