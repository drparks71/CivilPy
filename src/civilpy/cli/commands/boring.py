#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``boring`` commands: DIGGS boring logs in, tables out."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from civilpy.cli import ui
from civilpy.cli.io_ import Column, CommandResult, ResultTable
from civilpy.cli.registry import CliError, CommandSpec


@dataclass(frozen=True)
class BoringParseInput:
    """Inputs for ``boring parse``."""

    path: str = field(metadata={
        "positional": True, "kind": "path", "exts": (".xml",),
        "doc": "DIGGS XML file (the structured export DOTs publish per hole)",
    })


@dataclass(frozen=True)
class BoringBatchInput:
    """Inputs for ``boring batch``."""

    folder: str = field(metadata={
        "positional": True, "kind": "path", "exts": (),
        "doc": "folder of DIGGS .xml files, read recursively",
    })


@dataclass(frozen=True)
class BoringPdfInput:
    """Inputs for ``boring pdf2diggs``."""

    path: str = field(metadata={
        "positional": True, "kind": "path", "exts": (".pdf",),
        "doc": "PDF of ODOT standard boring log sheets (a report or a bare log; vector, not scanned)",
    })
    xml: str = field(default="", metadata={
        "kind": "path", "exts": (".xml",),
        "doc": "DIGGS file to write (default: next to the PDF as <name>-DIGGS.xml)",
    })
    project: str = field(default="", metadata={"doc": "project name for the DIGGS Project (default: the sheet's PROJECT)"})
    pid: str = field(default="", metadata={"doc": "ODOT PID for the DIGGS Project identifier (default: the sheet's PID)"})


def _tables_for(holes) -> list:  # noqa: ANN001
    header_rows = []
    spt_rows = []
    grading_rows = []
    sample_rows = []
    for hole in holes:
        header_rows.append((
            hole.boring_id, hole.project, hole.ground_elevation_ft,
            hole.latitude, hole.longitude, hole.total_depth_ft,
            hole.water_strike_depth_ft, len(hole.spt), len(hole.grading),
            len(hole.samples),
        ))
        for spt in sorted(hole.spt, key=lambda s: s.depth_ft):
            blows = "/".join(str(i.blows) for i in spt.increments)
            spt_rows.append((
                hole.boring_id, spt.depth_ft, hole.elevation_at(spt.depth_ft),
                blows, spt.n_value, spt.refusal,
            ))
        for g in sorted(hole.grading, key=lambda g: g.depth_ft):
            grading_rows.append((
                hole.boring_id, g.depth_ft, g.d10, g.d30, g.d50, g.d60,
                g.fines_percent, g.coefficient_of_uniformity,
                g.coefficient_of_curvature,
            ))
        for s in sorted(hole.samples, key=lambda s: s.depth_top_ft):
            sample_rows.append((
                hole.boring_id, s.depth_top_ft, s.depth_bottom_ft, s.method,
                s.recovery_in, s.recovery_percent,
            ))

    tables = [ResultTable(
        title="Boreholes",
        columns=[
            Column("Boring"), Column("Project"),
            Column("Ground elev.", "ft", ".1f"), Column("Latitude", None, ".5f"),
            Column("Longitude", None, ".5f"), Column("Depth", "ft", ".1f"),
            Column("Water", "ft", ".1f"), Column("SPT"), Column("Gradations"),
            Column("Samples"),
        ],
        rows=header_rows,
    )]
    if spt_rows:
        tables.append(ResultTable(
            title="SPT",
            columns=[
                Column("Boring"), Column("Depth", "ft", ".1f"),
                Column("Elev.", "ft", ".1f"), Column("Blows"), Column("N"),
                Column("Refusal"),
            ],
            rows=spt_rows,
        ))
    if grading_rows:
        tables.append(ResultTable(
            title="Gradations",
            columns=[
                Column("Boring"), Column("Depth", "ft", ".1f"),
                Column("D10", "mm", ".3f"), Column("D30", "mm", ".3f"),
                Column("D50", "mm", ".3f"), Column("D60", "mm", ".3f"),
                Column("Fines", "%", ".1f"), Column("Cu", None, ".2f"),
                Column("Cc", None, ".2f"),
            ],
            rows=grading_rows,
        ))
    if sample_rows:
        tables.append(ResultTable(
            title="Samples",
            columns=[
                Column("Boring"), Column("Top", "ft", ".1f"),
                Column("Bottom", "ft", ".1f"), Column("Method"),
                Column("Recovery", "in", ".1f"), Column("Recovery", "%", ".0f"),
            ],
            rows=sample_rows,
        ))
    return tables


def run_parse(inp: BoringParseInput, ctx) -> CommandResult:  # noqa: ANN001
    from civilpy.geotech.boring_io import parse_diggs

    path = Path(inp.path).expanduser()
    if not path.exists():
        raise CliError(f"no such file: {path}")
    holes = parse_diggs(str(path))
    if not holes:
        raise CliError(f"{path.name}: no boreholes found in DIGGS document")
    return CommandResult(tables=_tables_for(holes), input_files=[str(path)])


def run_batch(inp: BoringBatchInput, ctx) -> CommandResult:  # noqa: ANN001
    from civilpy.geotech.boring_io import parse_diggs

    folder = Path(inp.folder).expanduser()
    if not folder.is_dir():
        raise CliError(f"not a folder: {folder}")
    files = sorted(folder.rglob("*.xml"))
    if not files:
        raise CliError(f"no .xml files under {folder}")

    holes, skipped = [], []
    with ui.progress("Parsing DIGGS files", total=len(files)) as advance:
        for f in files:
            try:
                holes.extend(parse_diggs(str(f)))
            except Exception as exc:  # malformed exports happen in bulk
                skipped.append(f"{f.name}: {exc}")
            advance(note=f.name)
    if not holes:
        raise CliError("no boreholes parsed from any file")

    tables = _tables_for(holes)
    for msg in skipped:
        tables[0].notes.append(f"skipped {msg}")
    return CommandResult(tables=tables, input_files=[str(f) for f in files])


def run_pdf2diggs(inp: BoringPdfInput, ctx) -> CommandResult:  # noqa: ANN001
    from civilpy.geotech.diggs_writer import write_diggs
    from civilpy.state.ohio.DOT.boring_log_pdf import read_log_pdf

    path = Path(inp.path).expanduser()
    if not path.exists():
        raise CliError(f"no such file: {path}")
    logs = read_log_pdf(path)
    if not logs:
        raise CliError(f"{path.name}: no ODOT log sheets with a text layer (a scanned log needs OCR first)")
    head = logs[0].header
    out = Path(inp.xml).expanduser() if inp.xml else path.with_name(path.stem + "-DIGGS.xml")
    write_diggs(logs, out, project=inp.project or head.project, pid=inp.pid or head.pid, source=path.name)
    holes = [log.to_borehole() for log in logs]
    tables = _tables_for(holes)
    tables[0].notes.append(f"wrote {out}")
    for log in logs:
        for w in log.warnings:
            tables[0].notes.append(f"{log.boring_id}: {w}")
    tables[0].notes.append("read from the printed log, not human-verified: check against the sheet before design use")
    return CommandResult(tables=tables, input_files=[str(path)])


SPECS = [
    CommandSpec(
        name="boring pdf2diggs",
        summary="Read ODOT standard boring log sheets from a PDF and write them as a DIGGS file",
        description=(
            "Reads the vector PDF of ODOT's standard gINT boring log (header, layers, "
            "samples, SPT blows, lab columns) and writes a DIGGS 2.5 document that the "
            "rest of the library reads like a published one. Values are taken as printed "
            "and should be checked against the sheet; scanned logs need OCR first."
        ),
        input_model=BoringPdfInput,
        runner="civilpy.cli.commands.boring:run_pdf2diggs",
    ),
    CommandSpec(
        name="boring parse",
        summary="Read a DIGGS XML boring log into summary/SPT/gradation tables",
        description=(
            "Parses the DIGGS (Data Interchange for Geotechnical and "
            "Geoenvironmental Specialists) XML export of a boring log — the "
            "structured file many DOTs publish alongside the rendered PDF — "
            "into borehole header, SPT, gradation, and sample tables."
        ),
        input_model=BoringParseInput,
        runner="civilpy.cli.commands.boring:run_parse",
    ),
    CommandSpec(
        name="boring batch",
        summary="Parse a folder of DIGGS files into one combined set of tables",
        input_model=BoringBatchInput,
        runner="civilpy.cli.commands.boring:run_batch",
    ),
]
