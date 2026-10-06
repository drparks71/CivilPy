#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``photos`` failure and skip paths: bad inputs, corrupt files reported
as notes rather than aborting a batch, the spreadsheet rules of
``rename`` (explicit --excel, relative paths, blank rows, missing sources,
--keep-existing), and the two reasons ``stamp`` skips a photo."""

import pytest

from civilpy.cli.batch import execute
from civilpy.cli.commands.photos import _dest_folder, _gps_decimal


@pytest.fixture()
def good_jpg(tmp_path):
    from PIL import Image

    folder = tmp_path / "photos"
    folder.mkdir()
    exif = Image.Exif()
    exif[306] = "2026:06:01 10:30:00"
    p = folder / "IMG_1.jpg"
    Image.new("RGB", (64, 48), (10, 20, 30)).save(p, exif=exif)
    return p


@pytest.fixture()
def second_jpg(good_jpg):
    from PIL import Image

    exif = Image.Exif()
    exif[306] = "2026:06:02 11:00:00"
    p = good_jpg.parent / "IMG_2.jpg"
    Image.new("RGB", (64, 48), (30, 20, 10)).save(p, exif=exif)
    return p


@pytest.fixture()
def corrupt_jpg(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir(exist_ok=True)
    p = folder / "bad.jpg"
    p.write_bytes(b"\xff\xd8not really a jpeg")
    return p


def _flat(capsys):
    return " ".join(capsys.readouterr().out.split())


# ── _photo_files ──────────────────────────────────────────────────────────

def test_exif_missing_path(tmp_path, capsys):
    assert execute(["photos", "exif", str(tmp_path / "nope.jpg")]) == 2
    assert "no such file or folder" in _flat(capsys)


def test_exif_rejects_non_photo_file(tmp_path, capsys):
    p = tmp_path / "notes.txt"
    p.write_text("x")
    assert execute(["photos", "exif", str(p)]) == 2
    assert "notes.txt is not a recognized photo type" in _flat(capsys)


def test_exif_folder_without_photos(tmp_path, capsys):
    (tmp_path / "readme.md").write_text("x")
    assert execute(["photos", "exif", str(tmp_path)]) == 2
    assert "no photos under" in _flat(capsys)


def test_exif_corrupt_file_is_a_note(good_jpg, corrupt_jpg, capsys):
    assert execute(["photos", "exif", str(good_jpg.parent)]) == 0
    out = _flat(capsys)
    assert "unreadable: bad.jpg" in out
    assert "IMG_1.jpg" in out and "2026:06:01" in out


def test_exif_only_corrupt_files(corrupt_jpg, capsys):
    assert execute(["photos", "exif", str(corrupt_jpg.parent)]) == 2
    assert "no readable photos found" in _flat(capsys)


def test_gps_decimal_handles_garbage():
    assert _gps_decimal({}) == (None, None)
    assert _gps_decimal({"GPSLatitude": (1,), "GPSLongitude": (2, 3, 4)}) == (None, None)
    lat, lon = _gps_decimal({"GPSLatitude": (39, 30, 0), "GPSLatitudeRef": "S",
                             "GPSLongitude": (82, 0, 0)})
    assert lat == -39.5 and lon == 82.0  # no lon ref: east assumed


def test_dest_folder_defaults_next_to_the_input(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    assert _dest_folder(None, str(img), "Out") == tmp_path / "Out"
    assert (tmp_path / "Out").is_dir()
    assert _dest_folder(None, str(tmp_path), "Out2") == tmp_path / "Out2"
    explicit = tmp_path / "elsewhere"
    assert _dest_folder(str(explicit), str(img), "Out") == explicit
    assert explicit.is_dir()


# ── rename ────────────────────────────────────────────────────────────────

def _plan(path, rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(path)
    return path


def test_rename_not_a_folder(tmp_path, capsys):
    assert execute(["photos", "rename", str(tmp_path / "nope")]) == 2
    assert "not a folder" in _flat(capsys)


def test_rename_without_spreadsheet(good_jpg, capsys):
    assert execute(["photos", "rename", str(good_jpg.parent)]) == 2
    assert "no rename spreadsheet found" in _flat(capsys)


def test_rename_explicit_excel_missing(good_jpg, tmp_path, capsys):
    assert execute(["photos", "rename", str(good_jpg.parent),
                    "--excel", str(tmp_path / "ghost.xlsx")]) == 2
    assert "no such file" in _flat(capsys)


def test_rename_single_column_plan(good_jpg, tmp_path, capsys):
    plan = _plan(tmp_path / "plan.xlsx", [[str(good_jpg)]])
    assert execute(["photos", "rename", str(good_jpg.parent),
                    "--excel", str(plan)]) == 2
    assert "expected current path in column A" in _flat(capsys)


def test_rename_skips_blank_and_missing_rows_and_keeps_existing(good_jpg, tmp_path, capsys):
    folder = good_jpg.parent
    plan = _plan(tmp_path / "plan.xlsx", [
        ["IMG_1.jpg", "Pier 2 / East"],       # relative to the folder
        [None, "orphan name"],                # blank cell
        ["missing.jpg", "ghost"],             # source does not exist
    ])
    assert execute(["photos", "rename", str(folder), "--excel", str(plan),
                    "--keep-existing"]) == 0
    out = _flat(capsys)
    assert "skipped row with empty cell" in out
    assert "skipped missing source" in out
    renamed = folder / "Renamed_Photos"
    assert sorted(p.name for p in renamed.iterdir()) == ["pier-2-east-img_1.jpg"]
    assert good_jpg.exists()  # copied, not moved


def test_rename_nothing_renamed(good_jpg, tmp_path, capsys):
    plan = _plan(tmp_path / "plan.xlsx", [["missing.jpg", "x"]])
    assert execute(["photos", "rename", str(good_jpg.parent),
                    "--excel", str(plan)]) == 2
    assert "no photos renamed" in _flat(capsys)


def test_rename_ignores_excel_lock_files(good_jpg, tmp_path, capsys):
    folder = good_jpg.parent
    (folder / "~$plan.xlsx").write_bytes(b"lock")
    _plan(folder / "plan.xlsx", [[str(good_jpg), "deck"]])
    assert execute(["photos", "rename", str(folder)]) == 0
    assert (folder / "Renamed_Photos" / "deck.jpg").exists()


# ── resize ────────────────────────────────────────────────────────────────

def test_resize_corrupt_file_is_skipped(good_jpg, corrupt_jpg, tmp_path, capsys):
    dest = tmp_path / "out"
    assert execute(["photos", "resize", str(good_jpg.parent), "--width", "32",
                    "--height", "32", "--dest", str(dest)]) == 0
    out = _flat(capsys)
    assert "skipped bad.jpg" in out
    assert "64×48" in out and "32×32" in out
    assert sorted(p.name for p in dest.iterdir()) == ["IMG_1.jpg"]


def test_resize_nothing_resized(corrupt_jpg, capsys):
    assert execute(["photos", "resize", str(corrupt_jpg)]) == 2
    assert "no photos resized" in _flat(capsys)


# ── stamp ─────────────────────────────────────────────────────────────────

def test_stamp_corrupt_file_counts_as_no_timestamp(good_jpg, corrupt_jpg, capsys):
    assert execute(["photos", "stamp", str(good_jpg.parent)]) == 0
    out = _flat(capsys)
    assert "skipped bad.jpg: no EXIF timestamp" in out
    stamped = good_jpg.parent / "Stamped_Photos"
    assert sorted(p.name for p in stamped.iterdir()) == ["IMG_1.jpg"]


def test_stamp_nothing_to_stamp(corrupt_jpg, capsys):
    assert execute(["photos", "stamp", str(corrupt_jpg)]) == 2
    assert "no photos stamped" in _flat(capsys)


def test_stamp_reports_draw_failures(good_jpg, second_jpg, monkeypatch, capsys):
    import civilpy.general.photos as photos

    real = photos.add_timestamp

    def flaky(img, date):
        return None if img.filename.endswith("IMG_1.jpg") else real(img, date)

    monkeypatch.setattr(photos, "add_timestamp", flaky)
    assert execute(["photos", "stamp", str(good_jpg.parent)]) == 0
    out = _flat(capsys)
    assert "skipped IMG_1.jpg: could not draw timestamp" in out
    stamped = good_jpg.parent / "Stamped_Photos"
    assert sorted(p.name for p in stamped.iterdir()) == ["IMG_2.jpg"]


def test_stamp_writes_to_dest_with_date(good_jpg, tmp_path, capsys):
    dest = tmp_path / "stamped"
    assert execute(["photos", "stamp", str(good_jpg), "--dest", str(dest)]) == 0
    out = _flat(capsys)
    assert "06/01/2026 10:30" in out
    assert (dest / "IMG_1.jpg").exists()
