#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""One-shot front end edge paths: bare invocation, runner exceptions that
are not CliErrors, and an output path with an unsupported suffix."""

import pytest

from civilpy.cli import batch
from civilpy.cli.batch import build_parser, execute
from civilpy.cli.session import CliContext


def test_no_arguments_prints_top_level_help(capsys):
    assert execute([]) == 0
    out = capsys.readouterr().out
    assert "GROUP" in out and "interactive shell" in out


def test_group_without_verb_prints_group_help(capsys):
    assert execute(["hydro"]) == 0
    out = capsys.readouterr().out
    assert "channel" in out and "scour-pier" in out


def test_argparse_errors_return_their_exit_code(capsys):
    assert execute(["hydro", "channel"]) == 2  # missing required --width
    assert "--width" in capsys.readouterr().err


@pytest.mark.parametrize("exc", [ValueError("negative width"), KeyError("slab")])
def test_runner_value_and_key_errors_exit_2(monkeypatch, capsys, exc):
    def boom(spec):
        def runner(inputs, ctx):
            raise exc
        return runner

    monkeypatch.setattr(batch, "resolve_runner", boom)
    ctx = CliContext()
    assert execute(["odot", "slab", "20"], ctx=ctx) == 2
    out = capsys.readouterr().out
    assert "✗" in out and str(exc).strip("'") in out
    assert ctx.workspace.log == []  # a failed command is not logged


def test_unsupported_output_suffix_exits_2(tmp_path, capsys):
    out = tmp_path / "result.txt"
    assert execute(["odot", "slab", "20", "-o", str(out)]) == 2
    assert "unsupported output type '.txt'" in capsys.readouterr().out
    assert not out.exists()


def test_successful_run_logs_the_replayable_line(tmp_path, capsys):
    pytest.importorskip("openpyxl")
    from civilpy.cli import ui

    ctx = CliContext()
    out = tmp_path / "slab.xlsx"
    try:
        assert execute(["odot", "slab", "20", "--quiet", "-o", str(out)],
                       ctx=ctx, parser=build_parser()) == 0
        assert ctx.workspace.log == [f"civilpy odot slab 20 -o {out}"]
        # --quiet: the "wrote ..." status line is suppressed, the file is not
        assert "wrote" not in capsys.readouterr().out
        assert out.exists()
    finally:
        ui.set_quiet(False)


def test_entry_point_without_arguments_opens_the_shell(monkeypatch):
    from civilpy.cli import civilpy_cli, shell

    monkeypatch.setattr(shell, "run_shell", lambda: 7)
    monkeypatch.setattr("sys.argv", ["civilpy"])
    assert civilpy_cli() == 7          # argv from sys.argv
    assert civilpy_cli([]) == 7        # explicit empty argv
