#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``report notebook`` around a mocked ``notebook_converter``: input
checks, the per-format install hints when the exporter fails, the
"finished but wrote nothing" guard, and the arguments actually handed to
the converter (text_width 'none' → None, branding passthrough)."""

import csv

import pytest

from civilpy.cli.batch import execute

nbformat = pytest.importorskip("nbformat")
pytest.importorskip("nbconvert")


@pytest.fixture()
def notebook(tmp_path):
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_markdown_cell("# Calc")]
    p = tmp_path / "calc.ipynb"
    nbformat.write(nb, str(p))
    return p


@pytest.fixture()
def converter(monkeypatch):
    """Records calls; ``behaviour`` decides what the fake does."""
    import civilpy.general.jupyter as jup

    calls = []
    state = {"behaviour": "write"}

    def fake(path, format="webpdf", text_width=None, branding=None):
        calls.append(dict(path=path, format=format, text_width=text_width,
                          branding=branding))
        if state["behaviour"] == "write":
            from pathlib import Path

            Path(path).with_suffix(".tex" if format == "latex" else ".pdf") \
                .write_bytes(b"%PDF-1.7\n" * 256)
        elif state["behaviour"] == "raise":
            raise RuntimeError("chromium not found")

    monkeypatch.setattr(jup, "notebook_converter", fake)
    state["calls"] = calls
    return state


def _flat(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_missing_notebook(capsys):
    assert execute(["report", "notebook", "ghost.ipynb"]) == 2
    assert "no such file" in _flat(capsys)


def test_not_a_notebook(tmp_path, capsys):
    p = tmp_path / "calc.py"
    p.write_text("x = 1")
    assert execute(["report", "notebook", str(p)]) == 2
    assert "calc.py is not a .ipynb notebook" in _flat(capsys)


@pytest.mark.parametrize("fmt, hint", [
    ("webpdf", "playwright install chromium"),
    ("pdf", "LaTeX installation"),
    ("latex", "needs pandoc"),
])
def test_export_failure_carries_the_format_hint(notebook, converter, capsys, fmt, hint):
    converter["behaviour"] = "raise"
    assert execute(["report", "notebook", str(notebook), "--format", fmt]) == 2
    out = _flat(capsys)
    assert "export failed: chromium not found" in out
    assert hint in out


def test_exporter_that_writes_nothing_is_an_error(notebook, converter, capsys):
    converter["behaviour"] = "silent"
    assert execute(["report", "notebook", str(notebook)]) == 2
    out = _flat(capsys)
    assert "exporter finished but" in out and "calc.pdf was not written" in out


def test_webpdf_export_passes_options_and_reports_size(notebook, converter, tmp_path, capsys):
    report = tmp_path / "export.csv"
    assert execute(["report", "notebook", str(notebook), "--text-width", "none",
                    "--branding", "odot", "-o", str(report)]) == 0
    (call,) = converter["calls"]
    assert call == dict(path=str(notebook), format="webpdf", text_width=None,
                        branding="odot")
    assert "Exporting calc.ipynb → calc.pdf (webpdf)" in _flat(capsys)
    with open(report, newline="") as fh:
        (row,) = list(csv.DictReader(fh))
    assert row["Notebook"] == "calc.ipynb" and row["Format"] == "webpdf"
    assert row["Output"] == str(tmp_path / "calc.pdf")
    assert float(row["Size (KB)"]) == pytest.approx(9 * 256 / 1024)


def test_text_width_default_is_forwarded(notebook, converter):
    assert execute(["report", "notebook", str(notebook), "--format", "latex"]) == 0
    (call,) = converter["calls"]
    assert call["text_width"] == "70ch" and call["format"] == "latex"
    assert (notebook.with_suffix(".tex")).exists()
