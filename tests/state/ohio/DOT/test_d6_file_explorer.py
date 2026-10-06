#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.DOT.D6_file_explorer`.

The listbox filter (extension + case-insensitive substring, files only) and
the image preview scaling are exercised with real files under ``tmp_path``;
the FreeSimpleGUI elements are ``MagicMock`` stand-ins so no window is ever
created. ``main()`` is driven by replacing the module's ``sg`` namespace with
a mock whose ``Window.read`` replays a scripted event sequence.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("FreeSimpleGUI")      # the gui extra; not installed in CI
from PIL import Image

from civilpy.state.ohio.DOT import D6_file_explorer as d6

EXTS = (".png", ".gif", ".jpg", ".tif")


@pytest.fixture
def plan_dir(tmp_path):
    for name in ("Site_Plan.png", "GENERAL_PLAN.JPG", "notes.txt", "elev.tif", "cross.gif"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "folder.png").mkdir()  # a directory with an image suffix
    return tmp_path


# --------------------------------------------------------------------------- #
# update_listbox
# --------------------------------------------------------------------------- #

def test_listbox_filters_by_extension_and_skips_directories(plan_dir):
    lb = MagicMock()
    d6.update_listbox(lb, str(plan_dir), EXTS, "")
    (shown,), _ = lb.update.call_args
    assert sorted(p.name for p in shown) == ["GENERAL_PLAN.JPG", "Site_Plan.png", "cross.gif", "elev.tif"]
    assert all(isinstance(p, Path) for p in shown)  # D6 explorer lists full Paths


def test_listbox_substring_filter_is_case_insensitive(plan_dir):
    lb = MagicMock()
    d6.update_listbox(lb, str(plan_dir), EXTS, "PLAN")
    (shown,), _ = lb.update.call_args
    assert sorted(p.name for p in shown) == ["GENERAL_PLAN.JPG", "Site_Plan.png"]


def test_listbox_single_extension(plan_dir):
    lb = MagicMock()
    d6.update_listbox(lb, str(plan_dir), (".tif",), "")
    assert [p.name for p in lb.update.call_args.args[0]] == ["elev.tif"]


@pytest.mark.parametrize("folder", ["", "/definitely/not/here"])
def test_listbox_empty_for_blank_or_missing_folder(folder):
    lb = MagicMock()
    d6.update_listbox(lb, folder, EXTS, "")
    lb.update.assert_called_once_with([])


# --------------------------------------------------------------------------- #
# update_image
# --------------------------------------------------------------------------- #

def test_preview_size_constant():
    assert d6.size_of_image == (700, 600) and (d6.w, d6.h) == (700, 600)


def test_small_image_is_passed_by_filename(tmp_path):
    p = tmp_path / "small.png"
    Image.new("RGB", (700, 600)).save(p)  # exactly fits: scale == 1
    el = MagicMock()
    d6.update_image(el, p)
    el.update.assert_called_once_with(filename=p)


@pytest.mark.xfail(strict=True, reason=(
    "BUG: update_image resizes with Image.CUBIC, which Pillow removed in 10.0 "
    "(use Image.BICUBIC / Image.Resampling.BICUBIC); any oversized preview raises AttributeError"))
def test_large_image_is_downscaled_to_fit_and_sent_as_png_bytes(tmp_path):
    p = tmp_path / "big.png"
    Image.new("RGB", (1400, 600)).save(p)  # scale = max(2, 1) = 2
    el = MagicMock()
    d6.update_image(el, p)
    (_, kwargs) = el.update.call_args
    data = kwargs["data"]
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    from io import BytesIO
    assert Image.open(BytesIO(data)).size == (700, 300)


# --------------------------------------------------------------------------- #
# main() event loop against a mocked sg
# --------------------------------------------------------------------------- #

def _fake_sg(events):
    sg = MagicMock(name="sg")
    window = MagicMock(name="window")
    elements = {}
    window.__getitem__.side_effect = lambda key: elements.setdefault(key, MagicMock(name=key))
    window.read.side_effect = list(events) + [(sg.WINDOW_CLOSED, None)]
    sg.Window.return_value = window
    return sg, window, elements


def test_main_builds_window_and_closes_on_window_closed(monkeypatch):
    sg, window, _ = _fake_sg([])
    monkeypatch.setattr(d6, "sg", sg)
    d6.main()
    sg.theme.assert_called_once_with("Dark")
    sg.set_options.assert_called_once_with(font=("Courier New", 11))
    (title, layout), kwargs = sg.Window.call_args
    assert title == "Plan Viewer" and kwargs == {"finalize": True}
    sg.Listbox.assert_called_once()
    assert sg.Listbox.call_args.kwargs["key"] == "-LISTBOX-"
    assert sg.Listbox.call_args.kwargs["select_mode"] == sg.LISTBOX_SELECT_MODE_SINGLE
    sg.Image.assert_called_once_with(background_color="green", key="-IMAGE-")
    assert sg.Column.call_args_list[-1].kwargs["size"] == (715, 615)
    window.close.assert_called_once_with()


def test_main_folder_event_populates_listbox(monkeypatch, plan_dir):
    sg, window, elements = _fake_sg([
        ("-FOLDER-", {"-FOLDER-": str(plan_dir), "-FILTER-": ""}),
        ("Search", {"-FOLDER-": str(plan_dir), "-FILTER-": "site"}),
    ])
    monkeypatch.setattr(d6, "sg", sg)
    d6.main()
    calls = elements["-LISTBOX-"].update.call_args_list
    assert sorted(p.name for p in calls[0].args[0]) == ["GENERAL_PLAN.JPG", "Site_Plan.png", "cross.gif", "elev.tif"]
    assert [p.name for p in calls[1].args[0]] == ["Site_Plan.png"]


def test_main_listbox_selection_previews_image(monkeypatch, tmp_path):
    p = tmp_path / "pic.png"
    Image.new("RGB", (10, 10)).save(p)
    sg, window, elements = _fake_sg([
        ("-LISTBOX-", {"-LISTBOX-": [p], "-FOLDER-": str(tmp_path)}),
        ("-LISTBOX-", {"-LISTBOX-": [], "-FOLDER-": str(tmp_path)}),  # empty selection ignored
    ])
    monkeypatch.setattr(d6, "sg", sg)
    d6.main()
    elements["-IMAGE-"].update.assert_called_once_with(filename=p)
