#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``odot`` leftovers: TIMS epoch-year edge values, tiff join/split error
paths, and ``odot photos`` against a mocked AssetWise client (the real
one needs ~/secrets.json and the network; neither is allowed here)."""

import csv
from pathlib import Path

import pytest

from civilpy.cli.batch import execute
from civilpy.cli.commands.odot import _epoch_ms_year


def _flat(capsys):
    return " ".join(capsys.readouterr().out.split())


# ── _epoch_ms_year ────────────────────────────────────────────────────────

def test_epoch_year_none_and_garbage():
    assert _epoch_ms_year(None) is None
    assert _epoch_ms_year("1959") == "1959"           # not a number: passthrough
    assert _epoch_ms_year(-347155200000) == "1959"
    assert _epoch_ms_year(0) == "1970"


# ── tiff-join ─────────────────────────────────────────────────────────────

@pytest.fixture()
def sheets(tmp_path):
    pytest.importorskip("tifftools")
    from PIL import Image

    folder = tmp_path / "sheets"
    folder.mkdir()
    for i in (1, 2):
        Image.new("RGB", (20, 10), (i * 50, 0, 0)).save(folder / f"s_{i}.tif")
    return folder


def test_join_not_a_folder(tmp_path, capsys):
    pytest.importorskip("tifftools")
    assert execute(["odot", "tiff-join", str(tmp_path / "nope")]) == 2
    assert "not a folder" in _flat(capsys)


def test_join_folder_without_tifs(tmp_path, capsys):
    pytest.importorskip("tifftools")
    (tmp_path / "a.png").write_bytes(b"x")
    assert execute(["odot", "tiff-join", str(tmp_path)]) == 2
    assert "no .tif files in" in _flat(capsys)


def test_join_skips_bad_pages_and_defaults_dest(sheets, capsys):
    from PIL import Image

    (sheets / "s_0.tif").write_bytes(b"not a tiff at all")
    assert execute(["odot", "tiff-join", str(sheets)]) == 0
    out = _flat(capsys)
    assert "skipped s_0.tif" in out
    joined = sheets.parent / "sheets.tiff"
    assert joined.exists()
    with Image.open(joined) as img:
        assert getattr(img, "n_frames", 1) == 2


def test_join_only_bad_pages(tmp_path, capsys):
    pytest.importorskip("tifftools")
    (tmp_path / "bad.tif").write_bytes(b"not a tiff at all")
    assert execute(["odot", "tiff-join", str(tmp_path)]) == 2
    assert "no readable tiff pages found" in _flat(capsys)


# ── tiff-split ────────────────────────────────────────────────────────────

def test_split_missing_file(tmp_path, capsys):
    pytest.importorskip("tifftools")
    assert execute(["odot", "tiff-split", str(tmp_path / "nope.tif")]) == 2
    assert "no such file" in _flat(capsys)


def test_split_unreadable_file(tmp_path, capsys):
    pytest.importorskip("tifftools")
    p = tmp_path / "bad.tif"
    p.write_bytes(b"not a tiff at all")
    assert execute(["odot", "tiff-split", str(p)]) == 2
    assert "could not read bad.tif" in _flat(capsys)


def test_split_file_without_pages(tmp_path, capsys):
    """A valid little-endian header followed by garbage parses to zero IFDs."""
    pytest.importorskip("tifftools")
    p = tmp_path / "hollow.tif"
    p.write_bytes(b"II*\x00garbage")
    assert execute(["odot", "tiff-split", str(p)]) == 2
    assert "hollow.tif holds no pages" in _flat(capsys)


def test_split_defaults_dest_next_to_file(sheets, capsys):
    from PIL import Image

    assert execute(["odot", "tiff-split", str(sheets / "s_1.tif")]) == 0
    pages = sheets / "s_1_pages"
    assert [p.name for p in pages.iterdir()] == ["s_1_p001.tif"]
    with Image.open(pages / "s_1_p001.tif") as img:
        assert img.size == (20, 10)


# ── odot photos (AssetWise) ───────────────────────────────────────────────

@pytest.fixture()
def assetwise(monkeypatch):
    """Fake client + downloader; records what the command passed in."""
    import civilpy.state.ohio.DOT.assetwise_client as client_mod
    import civilpy.state.ohio.DOT.assetwise_files as files_mod

    calls = {}

    class FakeClient:
        def __init__(self):
            calls["client"] = self

    def dump(sfn_or_as_id, folder, *, photos_only, flat, client, progress=None):
        calls["args"] = dict(sfn=sfn_or_as_id, folder=folder,
                             photos_only=photos_only, flat=flat, client=client)
        for name in ("a.jpg", "b.jpg"):
            progress(name)
        return {"as_id": 77, "listed": 2, "written": 2, "skipped": 0,
                "failed": 0, "files": ["a.jpg", "b.jpg"]}

    monkeypatch.setattr(client_mod, "AssetWiseClient", FakeClient)
    monkeypatch.setattr(files_mod, "dump_inspection_files", dump)
    return calls


def test_photos_downloads_into_the_given_folder(assetwise, tmp_path, capsys):
    dest = tmp_path / "pics"
    report = tmp_path / "report.csv"
    assert execute(["odot", "photos", " 1801503 ", "--folder", str(dest),
                    "--all-files", "--flat", "-o", str(report)]) == 0
    args = assetwise["args"]
    assert args["sfn"] == "1801503"            # whitespace stripped
    assert args["folder"] == dest
    assert args["photos_only"] is False and args["flat"] is True
    assert args["client"] is assetwise["client"]
    assert "AssetWise files for 1801503" in _flat(capsys)
    with open(report, newline="") as fh:
        rows = {r["Item"]: r["Value"] for r in csv.DictReader(fh)}
    assert rows == {"as_id": "77", "listed": "2", "written": "2", "skipped": "0",
                    "failed": "0", "folder": str(dest)}


def test_photos_default_folder_is_temp_under_home(assetwise, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert execute(["odot", "photos", "1801503"]) == 0
    args = assetwise["args"]
    assert args["folder"] == tmp_path / "TEMP" / "1801503"
    assert args["photos_only"] is True and args["flat"] is False


def test_photos_without_credentials(monkeypatch, capsys):
    import civilpy.state.ohio.DOT.assetwise_client as client_mod

    def no_secrets():
        raise FileNotFoundError("~/secrets.json")

    monkeypatch.setattr(client_mod, "AssetWiseClient", no_secrets)
    assert execute(["odot", "photos", "1801503"]) == 2
    assert "AssetWise credentials not found" in _flat(capsys)


def test_photos_unknown_sfn(assetwise, monkeypatch, tmp_path, capsys):
    import civilpy.state.ohio.DOT.assetwise_files as files_mod

    def lookup_fails(*a, **k):
        raise LookupError("no asset with SFN 0000000")

    monkeypatch.setattr(files_mod, "dump_inspection_files", lookup_fails)
    assert execute(["odot", "photos", "0000000", "--folder", str(tmp_path)]) == 2
    assert "no asset with SFN 0000000" in _flat(capsys)
