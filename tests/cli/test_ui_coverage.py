#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Terminal presentation layer: status lines, the live and non-live
progress/spinner paths, quiet mode, and table cell formatting.

The live branches need ``Console.is_terminal`` to be true, so those tests
swap the module console for one with ``force_terminal=True`` writing to
a buffer; the rest print through the real console and read capsys.
"""

import io
import re

import pytest
from rich.console import Console

from civilpy.cli import ui
from civilpy.cli.io_ import Column, CommandResult, ResultTable


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _plain(buf: io.StringIO) -> str:
    """The buffer's text with terminal control sequences stripped."""
    return _ANSI.sub("", buf.getvalue())


@pytest.fixture(autouse=True)
def _restore_quiet():
    yield
    ui.set_quiet(False)


@pytest.fixture()
def live(monkeypatch):
    """A console that reports itself as a terminal, capturing to a buffer."""
    buf = io.StringIO()
    console = Console(theme=ui.CIVILPY_THEME, highlight=False,
                      force_terminal=True, file=buf, width=100)
    monkeypatch.setattr(ui, "_console", console)
    return buf


def test_console_is_shared_and_quiet_flag_round_trips():
    assert ui.console() is ui._console
    assert ui.is_quiet() is False
    ui.set_quiet(True)
    assert ui.is_quiet() is True


def test_status_lines(capsys):
    ui.ok("built")
    ui.warn("check this")
    ui.error("broke")
    out = capsys.readouterr().out
    assert "✓ built" in out
    assert "⚠ check this" in out
    assert "✗ broke" in out


def test_ok_is_silenced_by_quiet_but_errors_are_not(capsys):
    ui.set_quiet(True)
    ui.ok("built")
    ui.warn("hmm")
    ui.error("broke")
    out = capsys.readouterr().out
    assert "built" not in out
    assert "⚠ hmm" in out and "✗ broke" in out


# ── non-live progress (what CI and pipes see) ─────────────────────────────

def test_progress_logs_start_and_end_when_not_a_terminal(capsys):
    with ui.progress("Parsing", total=3) as advance:
        assert advance() is None
        assert advance(2, note="x") is None
    out = capsys.readouterr().out
    assert "Parsing… (3 items)" in out
    assert "Parsing done." in out


def test_progress_quiet_prints_nothing(capsys):
    ui.set_quiet(True)
    with ui.progress("Parsing", total=2) as advance:
        advance()
    assert capsys.readouterr().out == ""


def test_spinner_logs_start_and_end_when_not_a_terminal(capsys):
    with ui.spinner("Querying"):
        pass
    out = capsys.readouterr().out
    assert "Querying…" in out and "Querying done." in out


def test_spinner_quiet_prints_nothing(capsys):
    ui.set_quiet(True)
    with ui.spinner("Querying"):
        pass
    assert capsys.readouterr().out == ""


# ── live progress (a real terminal) ───────────────────────────────────────

def test_live_progress_advances_and_reports_completion(live):
    with ui.progress("Reading EXIF", total=3) as advance:
        advance()
        advance(note="IMG_2.jpg")
        advance(1)
    out = _plain(live)
    assert "✓ Reading EXIF (3)" in out      # the end-of-bar summary
    assert "Reading EXIF… (3 items)" not in out  # not the fallback log


def test_live_progress_note_updates_the_description(live, monkeypatch):
    updates = []
    from rich.progress import Progress

    real_update = Progress.update

    def spy(self, task_id, **kw):
        updates.append(kw.get("description"))
        return real_update(self, task_id, **kw)

    monkeypatch.setattr(Progress, "update", spy)
    with ui.progress("Stamping", total=1) as advance:
        advance(note="a.jpg")
    assert "Stamping — a.jpg" in updates


def test_live_spinner_reports_completion(live):
    with ui.spinner("Querying TIMS"):
        pass
    out = _plain(live)
    assert "✓ Querying TIMS" in out
    assert "Querying TIMS…" not in out


def test_live_console_still_honours_quiet(live):
    ui.set_quiet(True)
    with ui.progress("Parsing", total=1) as advance:
        advance()
    with ui.spinner("Querying"):
        pass
    assert _plain(live) == ""


# ── cells and tables ──────────────────────────────────────────────────────

def test_format_cell_variants():
    assert ui._format_cell(None) == "[civilpy.dim]–[/]"
    assert ui._format_cell(True) == "yes"
    assert ui._format_cell(False) == "no"
    assert ui._format_cell(2.0 / 3, ".2f") == "0.67"
    assert ui._format_cell(2.5) == "2.5"
    assert ui._format_cell(1e-7) == "1e-07"
    assert ui._format_cell(7, ".2f") == "7"      # ints ignore fmt
    assert ui._format_cell("P1") == "P1"


@pytest.fixture()
def wide(monkeypatch):
    """A plain (non-terminal) console wide enough that nothing wraps."""
    buf = io.StringIO()
    console = Console(theme=ui.CIVILPY_THEME, highlight=False,
                      force_terminal=False, file=buf, width=120)
    monkeypatch.setattr(ui, "_console", console)
    return buf


def test_render_table_shows_units_values_and_notes(wide):
    table = ResultTable(
        title="Pole values",
        columns=[Column("Pole"), Column("Tension", "lb", ".1f"), Column("Ok")],
        rows=[("P1", 1234.567, True), ("P2", None, False)],
        notes=["tail 2 mis-set"],
    )
    ui.render_table(table)
    out = wide.getvalue()
    assert "Pole values" in out
    assert "(lb)" in out
    assert "1234.6" in out
    assert "yes" in out and "no" in out
    assert "–" in out
    assert "⚠ tail 2 mis-set" in out


def test_render_result_renders_every_table(wide):
    result = CommandResult(tables=[
        ResultTable("First", [Column("a")], [(1,)]),
        ResultTable("Second", [Column("b")], [("a cell wide enough for the title",)]),
    ])
    ui.render_result(result)
    out = wide.getvalue()
    assert "First" in out and "Second" in out
