#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""One-shot (non-interactive) front end: ``civilpy <group> <verb> …``.

The argparse tree is synthesized from the command registry — groups
become subparsers, verbs become sub-subparsers, and each verb's flags
come from :func:`civilpy.cli.registry.introspect` on its input
dataclass.  Results render to the terminal and, with ``-o/--out``, to a
``.csv`` or ``.xlsx`` file (extension picks the writer).
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path
from typing import List, Optional

from civilpy.cli import io_, ui
from civilpy.cli.registry import (
    ArgInfo,
    CliError,
    CommandSpec,
    all_specs,
    build_inputs,
    resolve_runner,
)
from civilpy.cli.session import CliContext


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("civilpy")
    except Exception:  # pragma: no cover
        return "unknown"


def _help(text):
    # argparse %-formats help strings (strictly since 3.14), but field docs are
    # prose where a bare % is natural ("3-5% of span") — escape at the boundary
    return text.replace("%", "%%") if text else text


def _add_argument(parser: argparse.ArgumentParser, arg: ArgInfo) -> None:
    if arg.positional:
        parser.add_argument(arg.name, metavar=arg.metavar, type=arg.type,
                            choices=arg.choices, help=_help(arg.doc))
    elif arg.is_bool and arg.flag.startswith("--no-"):
        # already a negation (--no-ground): 3.14 argparse rejects
        # BooleanOptionalAction here, and --no-no-ground is meaningless anyway
        parser.add_argument(arg.flag, dest=arg.name, action="store_true",
                            default=arg.default, help=_help(arg.doc))
    elif arg.is_bool:
        parser.add_argument(arg.flag, dest=arg.name,
                            action=argparse.BooleanOptionalAction,
                            default=arg.default, help=_help(arg.doc))
    else:
        parser.add_argument(arg.flag, dest=arg.name, metavar=arg.metavar,
                            type=arg.type, choices=arg.choices,
                            required=arg.required, default=arg.default,
                            help=_help(arg.doc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="civilpy",
        description=(
            "Civil engineering tools. Run with no arguments for the "
            "interactive shell (Tab completion, /help)."
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"civilpy {_version()}")
    groups = parser.add_subparsers(dest="group", metavar="GROUP")

    by_group: dict = {}
    for spec in all_specs():
        by_group.setdefault(spec.group, []).append(spec)

    for group_name, specs in by_group.items():
        group_parser = groups.add_parser(
            group_name,
            help=", ".join(s.verb for s in specs),
        )
        verbs = group_parser.add_subparsers(dest="verb", metavar="VERB")
        for spec in specs:
            verb_parser = verbs.add_parser(
                spec.verb,
                help=_help(spec.summary),
                description=spec.description or spec.summary,
                formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            )
            for arg in spec.args:
                _add_argument(verb_parser, arg)
            out_group = verb_parser.add_argument_group("output")
            out_group.add_argument(
                "-o", "--out", metavar="PATH", default=None,
                help="write results to a .csv or .xlsx file",
            )
            out_group.add_argument(
                "--quiet", action="store_true",
                help="suppress status chatter and progress display",
            )
            verb_parser.set_defaults(_spec=spec)
    return parser


_PLAIN = re.compile(r"[\w@%+=:,./\\-]+", re.ASCII)


def _quote(value) -> str:
    """shlex.quote that leaves Windows paths alone: a backslash is a path
    separator here, not an escape, and quoting every ``C:\\...`` made the
    /log lines unreadable (and unreplayable in cmd / PowerShell)."""
    text = str(value)
    return text if text and _PLAIN.fullmatch(text) else shlex.quote(text)


def one_shot_line(spec: CommandSpec, values: dict, out: Optional[str]) -> str:
    """The replayable command line for /log and provenance."""
    parts = ["civilpy", spec.group, spec.verb]
    for arg in spec.args:
        value = values.get(arg.name)
        if value is None or value == arg.default:
            continue
        if arg.positional:
            parts.append(_quote(value))
        elif arg.is_bool:
            parts.append(arg.flag if value else "--no-" + arg.flag[2:])
        else:
            parts += [arg.flag, _quote(value)]
    if out:
        parts += ["-o", _quote(out)]
    return " ".join(parts)


def execute(argv: List[str], ctx: Optional[CliContext] = None,
            parser: Optional[argparse.ArgumentParser] = None) -> int:
    """Parse and run one command line; returns the exit code.  The shell
    passes its persistent ``ctx`` and reuses one parser."""
    parser = parser or build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed usage/help
        return int(exc.code or 0)

    if not getattr(ns, "group", None):
        parser.print_help()
        return 0
    spec: Optional[CommandSpec] = getattr(ns, "_spec", None)
    if spec is None:
        try:
            parser.parse_args([ns.group, "--help"])  # prints group verbs
        except SystemExit:
            pass
        return 0

    ctx = ctx or CliContext()
    ui.set_quiet(bool(getattr(ns, "quiet", False)))
    values = {a.name: getattr(ns, a.name) for a in spec.args}
    command_line = one_shot_line(spec, values, ns.out)

    try:
        inputs = build_inputs(spec, values)
        result = resolve_runner(spec)(inputs, ctx)
    except CliError as exc:
        ui.error(str(exc))
        return exc.exit_code
    except (ValueError, KeyError) as exc:
        ui.error(str(exc))
        return 2

    result.command = command_line
    result.inputs = {k: v for k, v in values.items() if v is not None}
    ctx.workspace.log.append(command_line)

    ui.render_result(result)
    if ns.out:
        try:
            written = io_.write_result(result, Path(ns.out))
        except ValueError as exc:
            ui.error(str(exc))
            return 2
        for path in written:
            ui.ok(f"wrote [civilpy.path]{path}[/]")
    return result.exit_code


def main(argv: Optional[List[str]] = None) -> int:
    return execute(sys.argv[1:] if argv is None else argv)
