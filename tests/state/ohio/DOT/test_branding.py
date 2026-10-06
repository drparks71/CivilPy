#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.DOT.branding`.

Verifies the published ODOT brand hex values, the sanitizer-safe title block
(inline styles only, logo embedded as a data URI when a file is supplied),
the webpdf export stylesheet, and the idempotent ``stamp_title_block`` /
``remove_title_block`` edits of a ``.ipynb`` file (nbformat 4.4 and 4.5 cell
shapes, trailing newline preserved, string vs list cell sources).
"""

import base64
import json
from pathlib import Path

import pytest

from civilpy.state.ohio.DOT import branding

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def logo(tmp_path):
    p = tmp_path / "odot_logo.png"
    p.write_bytes(PNG_1X1)
    return p


@pytest.fixture
def no_default_logo(tmp_path, monkeypatch):
    """Make the default logo lookup miss regardless of the checkout."""
    monkeypatch.setattr(branding, "DEFAULT_LOGO_PATH", tmp_path / "absent.png")


# --------------------------------------------------------------------------- #
# Palette / constants
# --------------------------------------------------------------------------- #

def test_published_odot_brand_colors():
    assert branding.ODOT_COLORS == {
        "primary_blue": "#0E3F75",
        "cardinal_red": "#C12637",
        "zephyr_green": "#00855B",
        "neutral_gray": "#54585A",
    }


def test_default_logo_path_is_repo_notebooks_res():
    p = branding.DEFAULT_LOGO_PATH
    assert p.parts[-3:] == ("Notebooks", "res", "odot_logo.png")
    # parents[5] of src/civilpy/state/ohio/DOT/branding.py is the repo root
    assert p.parents[2] == Path(branding.__file__).parents[5]


def test_title_block_marker_is_an_html_comment():
    assert branding.TITLE_BLOCK_MARKER == "<!-- civilpy-title-block -->"


# --------------------------------------------------------------------------- #
# logo_data_uri
# --------------------------------------------------------------------------- #

def test_logo_data_uri_encodes_png(logo):
    uri = branding.logo_data_uri(logo)
    assert uri == "data:image/png;base64," + base64.b64encode(PNG_1X1).decode()


def test_logo_data_uri_guesses_mime_from_extension(tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_bytes(b"<svg/>")
    assert branding.logo_data_uri(svg).startswith("data:image/svg+xml;base64,")
    odd = tmp_path / "logo.noext"
    odd.write_bytes(b"x")
    assert branding.logo_data_uri(odd).startswith("data:image/png;base64,")  # fallback


def test_logo_data_uri_missing_file_is_none(tmp_path):
    assert branding.logo_data_uri(tmp_path / "nope.png") is None


def test_logo_data_uri_uses_default_path(monkeypatch, logo):
    monkeypatch.setattr(branding, "DEFAULT_LOGO_PATH", logo)
    assert branding.logo_data_uri() == branding.logo_data_uri(logo)


# --------------------------------------------------------------------------- #
# title_block_html
# --------------------------------------------------------------------------- #

def test_title_block_html_without_logo(no_default_logo):
    html = branding.title_block_html("Steel Composite Design")
    assert html == (
        "<!-- civilpy-title-block -->\n"
        '<div style="border-top:6px solid #0E3F75; border-bottom:2px solid #C12637; '
        'padding:0.6em 0 0.6em 0; margin-bottom:1.2em;">\n'
        '<span style="font-size:1.5em; font-weight:bold; color:#0E3F75;">Steel Composite Design</span><br>\n'
        '<span style="color:#54585A;">Ohio Department of Transportation &middot; CivilPy Notebook Series</span>\n'
        "</div>"
    )


def test_title_block_html_is_sanitizer_safe(no_default_logo):
    html = branding.title_block_html("T")
    assert "<style" not in html and "<script" not in html
    assert "class=" not in html  # inline styles only


def test_title_block_html_custom_org_and_series(no_default_logo):
    html = branding.title_block_html("T", organization="MDTA", series="Inspection Notes")
    assert "MDTA &middot; Inspection Notes" in html


def test_title_block_html_embeds_logo(logo):
    html = branding.title_block_html("T", logo_path=logo)
    uri = branding.logo_data_uri(logo)
    assert f'<img src="{uri}" alt="ODOT logo" style="height:3em; float:right; margin-left:1em;">' in html
    # logo precedes the title span inside the div
    assert html.index("<img") < html.index("<span")


# --------------------------------------------------------------------------- #
# export_css
# --------------------------------------------------------------------------- #

def test_export_css_default_measure_and_colors():
    css = branding.export_css()
    assert css.startswith("<style>\n") and css.endswith("</style>")
    assert ".jp-RenderedMarkdown, .jp-MarkdownOutput { max-width: 70ch; }" in css
    assert ".jp-RenderedMarkdown h1, .jp-RenderedMarkdown h2 { color: #0E3F75; }" in css
    assert ".jp-RenderedMarkdown h1 { border-bottom: 2px solid #C12637; padding-bottom: 0.2em; }" in css
    assert ".jp-RenderedMarkdown h3 { color: #54585A; }" in css


def test_export_css_custom_and_no_measure():
    assert "max-width: 90ch;" in branding.export_css("90ch")
    assert "max-width" not in branding.export_css(text_width=None)


# --------------------------------------------------------------------------- #
# notebook_title
# --------------------------------------------------------------------------- #

def test_notebook_title_from_filename():
    assert branding.notebook_title("/x/Steel_Composite_Ch2.ipynb") == "Steel Composite Ch2"
    assert branding.notebook_title(Path("plain.ipynb")) == "plain"


# --------------------------------------------------------------------------- #
# stamp_title_block / remove_title_block
# --------------------------------------------------------------------------- #

def _write_nb(path, cells, minor=5, newline=True):
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": minor}
    text = json.dumps(nb, indent=1)
    path.write_text(text + ("\n" if newline else ""), encoding="utf-8")
    return path


def _code_cell(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": src}


def test_stamp_inserts_cell_at_top_with_8char_id(tmp_path, no_default_logo):
    nb_path = _write_nb(tmp_path / "Steel_Ch2.ipynb", [_code_cell(["x = 1\n"])])
    branding.stamp_title_block(nb_path)
    nb = json.loads(nb_path.read_text())
    assert len(nb["cells"]) == 2
    cell = nb["cells"][0]
    assert cell["cell_type"] == "markdown"
    assert len(cell["id"]) == 8 and cell["metadata"] == {}
    assert "".join(cell["source"]) == branding.title_block_html("Steel Ch2")
    # every line but the last carries its newline (nbformat list-of-lines style)
    assert all(line.endswith("\n") for line in cell["source"][:-1])
    assert not cell["source"][-1].endswith("\n")
    assert nb["cells"][1] == _code_cell(["x = 1\n"])


def test_stamp_nbformat_4_4_cell_has_no_id(tmp_path, no_default_logo):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [], minor=4)
    branding.stamp_title_block(nb_path, title="Custom")
    cell = json.loads(nb_path.read_text())["cells"][0]
    assert "id" not in cell
    assert ">Custom</span>" in "".join(cell["source"])


def test_stamp_is_idempotent_and_refreshes_title(tmp_path, no_default_logo):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [_code_cell("print(1)")])
    branding.stamp_title_block(nb_path, title="First")
    branding.stamp_title_block(nb_path, title="Second")
    nb = json.loads(nb_path.read_text())
    assert len(nb["cells"]) == 2
    text = "".join(nb["cells"][0]["source"])
    assert ">Second</span>" in text and "First" not in text


def test_stamp_replaces_existing_marker_cell_even_if_not_first(tmp_path, no_default_logo):
    marker_cell = {"cell_type": "markdown", "metadata": {},
                   "source": branding.TITLE_BLOCK_MARKER + "\nold"}  # string source
    nb_path = _write_nb(tmp_path / "nb.ipynb", [_code_cell("a"), marker_cell])
    branding.stamp_title_block(nb_path, title="New")
    nb = json.loads(nb_path.read_text())
    assert len(nb["cells"]) == 2
    assert nb["cells"][0]["cell_type"] == "code"
    assert ">New</span>" in "".join(nb["cells"][1]["source"])


def test_stamp_ignores_marker_in_code_cells(tmp_path, no_default_logo):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [_code_cell(branding.TITLE_BLOCK_MARKER)])
    branding.stamp_title_block(nb_path, title="T")
    nb = json.loads(nb_path.read_text())
    assert [c["cell_type"] for c in nb["cells"]] == ["markdown", "code"]


@pytest.mark.parametrize("newline", [True, False])
def test_stamp_preserves_trailing_newline_and_indent(tmp_path, no_default_logo, newline):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [], newline=newline)
    branding.stamp_title_block(nb_path, title="T")
    raw = nb_path.read_text(encoding="utf-8")
    assert raw.endswith("\n") is newline
    assert raw.startswith('{\n "cells"')  # indent=1


def test_stamp_keeps_non_ascii(tmp_path, no_default_logo):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [])
    branding.stamp_title_block(nb_path, title="Résumé — φ")
    assert "Résumé — φ" in nb_path.read_text(encoding="utf-8")  # ensure_ascii=False


def test_stamp_embeds_logo(tmp_path, logo):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [])
    branding.stamp_title_block(nb_path, title="T", logo_path=logo)
    assert branding.logo_data_uri(logo) in nb_path.read_text()


def test_remove_title_block_round_trip(tmp_path, no_default_logo):
    original = [_code_cell(["x = 1\n"]), {"cell_type": "markdown", "metadata": {}, "source": "# hi"}]
    nb_path = _write_nb(tmp_path / "nb.ipynb", original)
    before = nb_path.read_text(encoding="utf-8")
    branding.stamp_title_block(nb_path, title="T")
    assert branding.remove_title_block(nb_path) is True
    assert json.loads(nb_path.read_text())["cells"] == original
    assert nb_path.read_text(encoding="utf-8") == before


def test_remove_title_block_noop_returns_false(tmp_path):
    nb_path = _write_nb(tmp_path / "nb.ipynb", [_code_cell("a")], newline=False)
    before = nb_path.read_text(encoding="utf-8")
    assert branding.remove_title_block(nb_path) is False
    assert nb_path.read_text(encoding="utf-8") == before


def test_remove_drops_every_marker_cell_but_not_code(tmp_path):
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": [branding.TITLE_BLOCK_MARKER, "\nx"]},
        _code_cell(branding.TITLE_BLOCK_MARKER),
        {"cell_type": "markdown", "metadata": {}, "source": branding.TITLE_BLOCK_MARKER},
    ]
    nb_path = _write_nb(tmp_path / "nb.ipynb", cells, newline=False)
    assert branding.remove_title_block(nb_path) is True
    nb = json.loads(nb_path.read_text())
    assert nb["cells"] == [cells[1]]
    assert not nb_path.read_text().endswith("\n")
