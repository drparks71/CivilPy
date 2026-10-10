#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""The CivilPy interactive shell — the primary UI.

A prompt_toolkit REPL over the same command registry the one-shot mode
uses: Tab completes groups → verbs → flags → values (Literal choices,
extension-filtered paths, loaded object names), the bottom toolbar shows
the doc of the argument under the cursor, and slash commands handle the
meta-operations (``/help``, ``/commands``, ``/find``, ``/objects``,
``/log``, …).  Every engineering command executed here is recorded as its
one-shot equivalent (``/log``) so a session converts to a script.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import List, Optional

from rich.panel import Panel
from rich.table import Table

from civilpy.cli import batch, ui
from civilpy.cli.registry import ArgInfo, CliError, CommandSpec, all_specs, find_spec
from civilpy.cli.session import CliContext

HISTORY_FILE = Path.home() / ".civilpy_history"

SHELL_WORDS = ("load", "help", "exit", "quit")
SLASH_COMMANDS = {
    "/help": "documentation for a command: /help hydro scour-pier",
    "/commands": "browse every command, grouped, with summaries",
    "/find": "search commands and their argument docs: /find scour",
    "/objects": "list objects loaded into this session",
    "/log": "the one-shot equivalents of everything run this session",
    "/units": "unit conventions cheat-sheet",
    "/clear": "clear the screen",
    "/quit": "leave the shell",
}
LOADABLE_EXTS = (".xml", ".csv", ".xlsx", ".las", ".laz", ".3dm")


def _split(text: str) -> List[str]:
    """Split a shell line into tokens.  On Windows the backslash is a path
    separator, so the POSIX rules (which would turn ``C:\\Users`` into
    ``C:Users``) are replaced by: whitespace splits, double or single quotes
    group, nothing escapes."""
    try:
        if os.name == "nt":
            return [_unquote(tok) for tok in shlex.split(text, posix=False)]
        return shlex.split(text)
    except ValueError:  # unterminated quote while typing
        return text.split()


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def _groups() -> List[str]:
    seen: List[str] = []
    for spec in all_specs():
        if spec.group not in seen:
            seen.append(spec.group)
    return seen


def _path_candidates(prefix: str, exts: tuple) -> List[tuple]:
    """(text, meta) filesystem completions: directories always, files
    filtered to ``exts`` when given."""
    p = Path(prefix).expanduser() if prefix else Path(".")
    if prefix.endswith("/") or prefix == "":
        base, stem = (p if prefix else Path(".")), ""
    else:
        base, stem = p.parent, p.name
    if not base.is_dir():
        return []
    out = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.startswith(stem):
            continue
        if entry.name.startswith(".") and not stem.startswith("."):
            continue
        shown = str(entry) + ("/" if entry.is_dir() else "")
        if prefix and not prefix.startswith(("/", "~", "./")):
            shown = shown[len("") :]
        if entry.is_dir():
            out.append((shown, "directory"))
        elif not exts or entry.suffix.lower() in exts:
            out.append((shown, entry.suffix.lstrip(".") + " file"))
    return out


class _State:
    """What the cursor position means, shared by completer and toolbar."""

    def __init__(self, text: str, ctx: CliContext):
        self.ctx = ctx
        self.tokens = _split(text)
        self.trailing_space = text.endswith((" ", "\t")) or not text
        self.word = "" if self.trailing_space else (self.tokens[-1] if self.tokens else "")
        done = self.tokens if self.trailing_space else self.tokens[:-1]
        self.done = done
        self.spec: Optional[CommandSpec] = None
        if len(done) >= 2 and done[0] not in SHELL_WORDS:
            self.spec = find_spec(done[0], done[1])

    def pending_arg(self) -> Optional[ArgInfo]:
        """The ArgInfo whose *value* the cursor is on (flag just typed),
        or the positional not yet supplied."""
        if self.spec is None:
            return None
        args = {a.flag: a for a in self.spec.args}
        if len(self.done) > 2:
            last = self.done[-1]
            arg = args.get(last)
            if arg is not None and not arg.is_bool:
                return arg
        if self.word.startswith("-"):
            return None
        used_positional = any(
            not t.startswith("-") for t in self.done[2:]
        ) and not (len(self.done) > 2 and self.done[-1] in args)
        if not used_positional:
            for a in self.spec.args:
                if a.positional:
                    return a
        return None

    def unused_flags(self) -> List[ArgInfo]:
        if self.spec is None:
            return []
        used = set(self.done[2:])
        out = []
        for a in self.spec.args:
            if a.positional or a.flag in used:
                continue
            out.append(a)
        return out


def _completions(state: _State) -> List[tuple]:
    """(text, meta) candidates for the current word."""
    word, done = state.word, state.done
    if not done:
        if word.startswith("/"):
            return [(c, d) for c, d in SLASH_COMMANDS.items()]
        cands = [(g, ", ".join(s.verb for s in all_specs() if s.group == g))
                 for g in _groups()]
        cands += [("load", "load a file into the session (DIGGS, csv, las, 3dm)"),
                  ("help", "same as /help"),
                  ("quit", "leave the shell")]
        return cands
    if done[0].startswith("/"):
        if done[0] in ("/help", "/find"):
            return [(s.name, s.summary) for s in all_specs()]
        return []
    if done[0] == "load":
        return _path_candidates(word, LOADABLE_EXTS)
    if done[0] == "help":
        return [(s.name.split()[0], "") for s in all_specs()] if len(done) == 1 else []
    if len(done) == 1:
        return [(s.verb, s.summary) for s in all_specs() if s.group == done[0]]
    if state.spec is None:
        return []
    arg = state.pending_arg()
    if arg is not None:
        if arg.choices:
            return [(str(c), arg.doc) for c in arg.choices]
        if arg.is_bool:   # pragma: no cover - pending_arg never yields a switch
            return []
        if arg.kind == "path":
            cands = _path_candidates(word, arg.exts)
            if arg.name == "boring":
                cands = [
                    (name, f"loaded boring — {lo.summary}")
                    for name, lo in state.ctx.workspace.objects.items()
                    if lo.kind == "boring"
                ] + cands
            return cands
        return []
    flags = [(a.flag, a.doc) for a in state.unused_flags()]
    flags += [("-o", "write results to a .csv or .xlsx file")]
    return flags


def _make_completer(ctx: CliContext):
    from prompt_toolkit.completion import Completer, Completion

    class CivilPyCompleter(Completer):
        def get_completions(self, document, complete_event):
            state = _State(document.text_before_cursor, ctx)
            for text, meta in _completions(state):
                if text.startswith(state.word):
                    yield Completion(
                        text,
                        start_position=-len(state.word),
                        display_meta=meta[:70] if meta else None,
                    )

    return CivilPyCompleter()


def _toolbar(ctx: CliContext):
    from prompt_toolkit.application import get_app

    def toolbar():
        text = get_app().current_buffer.text
        state = _State(text, ctx)
        arg = state.pending_arg() if state.spec else None
        if arg is None and state.spec and state.word.startswith("-"):
            flag_args = {a.flag: a for a in state.spec.args}
            arg = flag_args.get(state.word)
        if arg is not None:
            return f" {arg.flag if not arg.positional else arg.name}: {arg.describe()}"
        if state.spec is not None:
            return f" {state.spec.name} — {state.spec.summary}"
        return " Tab completes · /commands to browse · /help <command> for docs"

    return toolbar


def _print_banner() -> None:
    console = ui.console()
    console.print(
        Panel.fit(
            f"[civilpy.heading]CivilPy[/] [civilpy.value]{batch._version()}[/]"
            " — civil engineering tools\n"
            "[civilpy.dim]Tab completes · /commands to browse · "
            "/help <command> for docs · /quit to exit[/]",
            border_style="civilpy.heading",
        )
    )


def _cmd_help(args: List[str]) -> None:
    console = ui.console()
    if len(args) >= 2:
        spec = find_spec(args[0], args[1])
        if spec is None:
            ui.error(f"no command '{' '.join(args[:2])}' — try /commands")
            return
        console.print(f"[civilpy.heading]{spec.name}[/] — {spec.summary}")
        if spec.description:
            console.print(spec.description)
        table = Table(header_style="bold", border_style="civilpy.dim")
        table.add_column("argument")
        table.add_column("type")
        table.add_column("default")
        table.add_column("doc")
        for arg in spec.args:
            kind = "flag" if arg.is_bool else (
                "|".join(str(c) for c in arg.choices) if arg.choices
                else arg.type.__name__)
            default = ("required" if arg.required
                       else "" if arg.default is None else str(arg.default))
            name = arg.name if arg.positional else arg.flag
            table.add_row(name, kind, default, arg.doc)
        console.print(table)
        console.print(
            f"[civilpy.dim]output: add -o results.xlsx (or .csv) "
            f"to write files[/]"
        )
    elif len(args) == 1:
        _cmd_commands(group=args[0])
    else:
        _cmd_commands()
        console.print(
            "\n[civilpy.dim]/help <group> <verb> shows a command's full "
            "argument docs; anything you can type here also works as "
            "'civilpy <group> <verb> …' in a normal shell.[/]"
        )


def _cmd_commands(group: Optional[str] = None) -> None:
    console = ui.console()
    table = Table(title="Commands", title_style="civilpy.heading",
                  title_justify="left", header_style="bold",
                  border_style="civilpy.dim")
    table.add_column("command")
    table.add_column("summary")
    last_group = None
    for spec in all_specs():
        if group and spec.group != group:
            continue
        if last_group is not None and spec.group != last_group:
            table.add_section()
        table.add_row(f"[civilpy.value]{spec.name}[/]", spec.summary)
        last_group = spec.group
    console.print(table)


def _cmd_find(args: List[str]) -> None:
    if not args:
        ui.error("usage: /find <text>")
        return
    needle = " ".join(args).lower()
    hits = []
    for spec in all_specs():
        haystack = " ".join(
            [spec.name, spec.summary, spec.description]
            + [a.name + " " + a.doc for a in spec.args]
        ).lower()
        if needle in haystack:
            hits.append(spec)
    if not hits:
        ui.console().print(f"[civilpy.dim]nothing matches '{needle}'[/]")
        return
    for spec in hits:
        ui.console().print(
            f"[civilpy.value]{spec.name}[/] — {spec.summary}")


def _cmd_objects(ctx: CliContext) -> None:
    console = ui.console()
    if not ctx.workspace.objects:
        console.print(
            "[civilpy.dim]nothing loaded — try: load <file.xml|csv|las|3dm>[/]")
        return
    table = Table(header_style="bold", border_style="civilpy.dim")
    table.add_column("name")
    table.add_column("kind")
    table.add_column("summary")
    table.add_column("source")
    for lo in ctx.workspace.objects.values():
        table.add_row(f"[civilpy.value]{lo.name}[/]", lo.kind, lo.summary,
                      f"[civilpy.path]{lo.source}[/]")
    console.print(table)


def _cmd_units() -> None:
    ui.console().print(Panel.fit(
        "US customary throughout, matching the library:\n"
        "  lengths/depths/stations  [civilpy.value]ft[/]   "
        "sections/covers/spacings  [civilpy.value]in[/]\n"
        "  velocity  [civilpy.value]ft/s[/]   discharge  "
        "[civilpy.value]cfs[/]   grades  [civilpy.value]%[/]\n"
        "  grain sizes  [civilpy.value]mm[/] (geotech convention)   "
        "speeds  [civilpy.value]mph[/]\n"
        "Every output column header carries its unit.",
        title="units", border_style="civilpy.dim",
    ))


def _cmd_load(ctx: CliContext, args: List[str]) -> None:
    if not args:
        ui.error("usage: load <path> [as <name>]")
        return
    name = None
    if len(args) >= 3 and args[-2] == "as":
        name, args = args[-1], args[:-2]
    try:
        loaded = ctx.workspace.load(" ".join(args), name=name)
    except CliError as exc:
        ui.error(str(exc))
        return
    for lo in loaded:
        ui.ok(f"[civilpy.value]{lo.name}[/] ({lo.kind}): {lo.summary}")
    ctx.workspace.log.append(
        "load " + " ".join(args) + (f" as {name}" if name else ""))


def _dispatch(line: str, ctx: CliContext, parser) -> bool:  # noqa: ANN001
    """Handle one shell line; returns False to exit the loop."""
    tokens = _split(line)
    if not tokens:
        return True
    head = tokens[0]
    if head in ("/quit", "/exit", "quit", "exit"):
        return False
    if head == "/clear":
        ui.console().clear()
        return True
    if head in ("/help", "help"):
        _cmd_help(tokens[1:])
        return True
    if head == "/commands":
        _cmd_commands(tokens[1] if len(tokens) > 1 else None)
        return True
    if head == "/find":
        _cmd_find(tokens[1:])
        return True
    if head == "/objects":
        _cmd_objects(ctx)
        return True
    if head == "/units":
        _cmd_units()
        return True
    if head == "/log":
        if not ctx.workspace.log:
            ui.console().print("[civilpy.dim]nothing run yet[/]")
        for entry in ctx.workspace.log:
            ui.console().print(f"  [civilpy.value]{entry}[/]")
        return True
    if head.startswith("/"):
        ui.error(f"unknown slash command {head} — try /help")
        return True
    if head == "load":
        _cmd_load(ctx, tokens[1:])
        return True
    batch.execute(tokens, ctx=ctx, parser=parser)
    return True


def run_shell() -> int:
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style
    except ImportError:  # pragma: no cover - core dep, but degrade politely
        ui.error(
            "the interactive shell needs prompt_toolkit "
            "(pip install prompt_toolkit); one-shot mode still works: "
            "civilpy --help"
        )
        return 1

    ctx = CliContext(interactive=True)
    parser = batch.build_parser()
    _print_banner()
    session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=_make_completer(ctx),
        bottom_toolbar=_toolbar(ctx),
        style=Style.from_dict({
            "prompt": "bold ansicyan",
            "bottom-toolbar": "noreverse italic fg:ansibrightblack",
        }),
        complete_while_typing=True,
    )
    while True:
        try:
            line = session.prompt([("class:prompt", "civilpy> ")])
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
        try:
            if not _dispatch(line.strip(), ctx, parser):
                break
        except CliError as exc:
            ui.error(str(exc))
        except Exception as exc:  # keep the shell alive on command bugs
            ui.error(f"{type(exc).__name__}: {exc}")
    ui.console().print("[civilpy.dim]bye[/]")
    return 0
