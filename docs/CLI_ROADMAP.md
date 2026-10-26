# CivilPy CLI roadmap

The CLI becomes the **primary user interface** for CivilPy: an interactive
shell in the spirit of Claude Code — slash commands, context-aware
autocomplete, documentation surfaced inline as you type — plus a
non-interactive batch mode so every command also works in scripts and CI.

The preferred workflow is **files in, tables out**: DIGGS XML, `.csv`,
`.xlsx`, `.las`/`.laz`, `.3dm`, LPILE data files, TIFF plan sets in;
`.csv` / `.xlsx` (and terminal tables) out.

Status: **approved; Phase 1 complete 2026-07-15.**  `src/civilpy/cli/`
carries Phase 0 (registry, themed UI, ResultTable writers, lazy imports),
all of Phase 1's batch commands, the Phase 2 interactive shell
(completion, toolbar docs, slash commands, /log), and a Phase 4 seed
(session `load` + `--boring` object references).  Sixteen commands:
`boring parse|batch`, `odot slab|bridge|tiff-join|tiff-split`,
`hydro channel|scour-pier`, `road vcurve|hcurve`, `snbi validate`,
`photos exif|rename|resize|stamp`, `report notebook`.  (The registry is
two-level, so the catalog's `odot tiff join|split` shipped as
`tiff-join`/`tiff-split`.)  `snbi validate` exits nonzero on failed
records via `CommandResult.exit_code`, so submissions gate in CI.  Next
up: Phase 3 calculators (`struct section|beam|line-girder`,
`geotech spt|bearing`, `hydro pipe`) and plot sidecar outputs.

---

## 1. Vision

```
$ civilpy
CivilPy 0.6.1 — type /help for commands, Tab to complete, /quit to exit

civilpy> load borings/B-001-0-24.xml
  ✓ B-001 (Borehole): 42.5 ft, 14 SPT drives, 3 gradations

civilpy> scour pier --boring B-001 --velocity 6.2 --depth 8.0 --pier-width 3.0
  ┌──────────────────────┬────────┐
  │ D50 (from B-001)     │ 0.4 mm │
  │ Local pier scour ys  │ 7.1 ft │
  └──────────────────────┴────────┘
  ✓ wrote scour_pier_B-001.xlsx

civilpy> headwall --diameter-in 4▸8    ← Tab completes tabulated sizes: 48, …
```

Three interaction modes, one command registry:

| Mode | Invocation | Audience |
|---|---|---|
| Interactive shell | `civilpy` | primary UI: exploration, chained work on loaded files |
| One-shot | `civilpy scour pier --boring B-001.xml ...` | scripts, CI, power users |
| Python API | unchanged | notebooks, Rhino/Grasshopper |

The shell is a *view* over the same library calls the notebooks use — no
engineering logic lives in the CLI layer.

## 2. Guiding principles

1. **One source of truth for docs and completion.** Commands are declared
   against the existing frozen-dataclass input pattern
   (`HeadwallInput`-style: typed fields, `Literal[...]` choices, per-field
   docstrings — see commits a6a1b95, 7e695e0). The registry introspects
   those dataclasses to generate flags, Tab-completion choices, `/help`
   text, and validation messages. Adding a field to an Input class updates
   the CLI automatically.
2. **Fast startup, lazy everything.** `civilpy` must open in well under a
   second. Each command imports its module only when run; optional-extra
   deps fail with an actionable message
   (`this command needs 'pip install civilpy[pdf]'`), never a raw
   `ImportError`.
3. **Files in, tables out.** Every command returns one or more
   `ResultTable`s rendered identically to the terminal (rich), `.csv`, or
   `.xlsx` (openpyxl). Plots (matplotlib/plotly) are secondary outputs
   saved next to the tables.
4. **Python 3.9 floor stays.** The shell never runs inside Rhino, but the
   package must keep importing there — `from __future__ import
   annotations` in all new modules, no 3.10+ syntax.
5. **Units are explicit.** US customary throughout (matching the library);
   every output column header carries its unit; Pint stays internal.
6. **Pretty by default, never silent.** Color and visual structure are part
   of the product, not decoration: a single rich theme applied everywhere,
   and a progress bar (or spinner with elapsed time) on **any operation
   expected to take more than ~5 seconds**. See §3a.

## 3. Architecture

```
src/civilpy/cli/
    __init__.py        # civilpy_cli() entry point (replaces CLI.py)
    registry.py        # CommandSpec, command discovery, arg synthesis
    shell.py           # interactive REPL (prompt_toolkit)
    batch.py           # argparse front end for one-shot mode
    session.py         # Workspace: named loaded objects, history, cwd
    io_.py             # loaders (by extension) + ResultTable writers
    ui.py              # shared rich Console, theme, progress helpers
    docs.py            # /help, /docs rendering from specs + docstrings
    commands/
        boring.py      # parse/summary/export
        scour.py       # pier, contraction
        snbi.py        # validate
        photos.py      # exif, rename, resize, stamp
        ...            # one thin module per command group
```

### CommandSpec (the contract)

```python
@dataclass(frozen=True)
class CommandSpec:
    name: str                 # "scour pier"
    group: str                # "hydro"
    summary: str              # one line for /commands listing
    input_model: type         # frozen dataclass w/ Literal fields + docs
    accepts: tuple[str, ...]  # file kinds it can consume: ("boring",)
    produces: str             # "table" | "tables+plot" | "files"
    requires: tuple[str, ...] # optional extras: ("pdf",)
    runner: str               # "civilpy.water_resources.scour:pier_scour..."
```

- `batch.py` turns `input_model` fields into `--kebab-case` argparse flags
  (Literal → `choices=`, bool → `--flag/--no-flag`, defaults from the
  dataclass).
- `shell.py` turns the same fields into completers and the bottom-toolbar
  hint (field docstring of the argument under the cursor).
- `docs.py` renders the same metadata as `/help <command>`.

### Interactive shell

- **`prompt_toolkit`** (new core dependency, pure Python, supports 3.8+)
  for the REPL: history file, fish-style autosuggest, completion menus,
  bottom toolbar. **`rich`** (already a core dep) for all output.
- Completion is context-aware: command names → flag names → per-flag
  values (Literal choices, catalog values such as tabulated headwall
  diameters, session object names, paths filtered to the extensions the
  command `accepts`).
- Slash commands (shell meta-operations, distinct from engineering
  commands):

| Slash | Does |
|---|---|
| `/help [cmd]` | full docs for a command (from its Input dataclass) |
| `/commands [group]` | browsable catalog, grouped, with summaries |
| `/find <text>` | search command names + summaries + field docs |
| `/objects` | list loaded session objects with type + provenance |
| `/open <path>` | alias of `load`; extension → loader dispatch |
| `/export [name] [--xlsx/--csv] [path]` | re-export last / named result |
| `/recent` | recently loaded files (persisted across sessions) |
| `/settings` | output dir, default format, precision |
| `/units` | unit conventions cheat-sheet |
| `/log` | show the one-shot equivalents of this session (reproducibility) |
| `/clear`, `/quit` | housekeeping |

`/log` matters: every shell action records its exact one-shot form, so an
interactive exploration converts into a rerunnable script for the project
file.

### Session / workspace

`load <path> [as <name>]` dispatches on extension to a typed object:

| Extension | Object | Loader |
|---|---|---|
| `.xml` (DIGGS) | `Borehole` | `geotech.boring_io` (stdlib-only) |
| `.csv` / `.xlsx` | `DataFrame` | pandas / openpyxl |
| `.las` / `.laz` | `Terrain` | `transportation.terrain` (lazy laspy) |
| `.3dm` | `Model3dm` (objects + BIM user text) | rhino3dm (`[rhino]` extra) |
| `.lpd` / LPILE report `.txt` | `LPileModel` / `LPileResults` | `geotech.lpile` |
| `.tif` | plan-set handle | `state.ohio.search_tools` (`[geo]`) |
| `.ipynb` | notebook handle | `general.jupyter` (`[jupyter]`) |

Commands accept either a session object name or a raw path for any
`accepts` slot — one-shot mode just loads inline.

### Output layer

`ResultTable` = column names + units + rows + provenance (command, inputs,
input-file hashes, timestamp, civilpy version). Writers:

- terminal: rich table (always);
- `--csv` / `--xlsx` (or `/settings` default): file next to cwd or
  `--out`; xlsx gets one sheet per table plus a `provenance` sheet;
- multi-table commands (e.g. line-girder: loads, DFs, envelopes) write one
  workbook.

## 3a. Visual design & progress feedback

All terminal output flows through one `ui.py` module: a single shared
`rich.Console` with a named **CivilPy theme**, so color usage is consistent
and defined in exactly one place.

**Theme** (rich theme styles, refine during Phase 0):

| Style | Used for |
|---|---|
| `civilpy.ok` (green ✓) | completed steps, written files |
| `civilpy.warn` (yellow) | engineering advisories (Flag-level SNBI, cover limits) |
| `civilpy.err` (red ✗) | failures, validation Errors, nonzero exits |
| `civilpy.value` (cyan) | numbers/results in prose lines |
| `civilpy.unit` (dim) | unit annotations |
| `civilpy.path` (magenta, underlined) | file paths (clickable where supported) |
| `civilpy.heading` (bold blue) | table titles, group headers in `/commands` |

Tables get column-type-aware styling (units dimmed in headers, governing
rows highlighted), panels frame multi-part results, and the shell banner /
`/commands` catalog use rule lines and group colors. `NO_COLOR` and
non-TTY output (pipes, CI) degrade automatically to plain text — rich
handles both; never emit ANSI into a redirected file.

**Progress rule:** any operation with an expected runtime over ~5 seconds
must show live progress — no silent stalls. Conventions:

- **Determinate work** (N files, N holes, N sheets, N iterations):
  `rich.progress` bar with count, percentage, elapsed + ETA. Applies to
  `boring batch`, `photos rename|resize|stamp|exif`, `odot tiff
  join|split`, `snbi validate` (per record), `stm optimize` (per SIMP
  iteration), `terrain` LiDAR ingestion (per point chunk), batch
  downloads (per photo, with transfer size).
- **Indeterminate work** (single network call, external engine run,
  nbconvert): spinner + task description + elapsed time, e.g.
  `⠸ Querying TIMS for SFN 2100992… 4.1s`. Applies to `odot bridge`,
  `report notebook`, `lpile simulate`, CANDE runs.
- **Multi-stage commands** (line-girder: loads → DFs → envelope → write)
  render a step checklist, each line flipping to `civilpy.ok` as it
  completes.
- Implementation: `ui.progress()` / `ui.spinner()` context managers wrap
  `rich.progress` so command modules never construct progress UI
  directly; library-layer functions gain an optional `on_progress`
  callback (no rich imports inside `civilpy.*` engineering modules — the
  CLI owns presentation).
- In `--quiet`/`--json`/non-TTY mode, progress goes to a log line at
  start/end instead of a live display.

## 4. Command catalog (target state)

Grouped as the shell will present them. ✱ = depends on an optional extra.

**boring** — `parse` (DIGGS → summary + layer/SPT/gradation tables),
`batch` (folder of DIGGS → one workbook), `pdf`✱ (low-fidelity PDF log
scrape).

**geotech** — `spt correlations`, `bearing shallow`, `capacity pile`
(axial), `lateral pile` (p-y solver), `lpile emit|parse|simulate`,
`cande soil-zones` (boring → CANDE materials).

**hydro** — `channel` (critical/normal depth, specific energy),
`pipe profile` (EGL/HGL table), `scour pier|contraction` (HEC-18,
`--boring` aware).

**road** — `vcurve`, `hcurve` (station/elevation/geometry tables),
`alignment station` (station/offset → 3D point, needs alignment file
definition — see open questions), `terrain elevation`✱ (`.las` → elevations
at stations/points).

**struct** — `section` (built-up plates → properties),
`beam` (ContinuousBeam runs: reactions, diagrams),
`line-girder` (the flagship calculator: Literal-typed settings → loads,
DFs, V/M/Δ envelopes workbook), `splice place` (envelope csv → G6
candidates), `box-beam check` (PSBDD-1-25 line verification),
`stm optimize`✱ (D-region → truss + costing).

**odot** — `slab` (deck parameter lookup; argparse already written),
`bridge <SFN>` (TIMS record → table), `tiff join|split`✱,
`scd list|info` (catalog of built SCD components + their Input docs),
`photos download`✱ (AssetWise, credentialed).

**snbi** — `validate <file>` (Pydantic✱ rule engine → error report table,
nonzero exit on Critical/Error), `template` (emit a blank submission
skeleton).

**photos** — `exif` (GPS/timestamp table ± map✱), `rename` (from
spreadsheet), `resize`, `stamp`.

**report** — `notebook <ipynb> --format webpdf|pdf|html`✱ (tag-filtered
export).

**model** — `3dm objects`✱ (inventory of a `.3dm`: layer, `bim.*` tags),
`3dm quantities`✱ (roll `pay.*` items into an estimate workbook),
`3dm export`✱ (tagged geometry records → csv). Read-only first; BrIM
*emit to .3dm* from the CLI is a later decision.

Explicitly **out of scope** for the CLI: live Rhino/Grasshopper sessions,
live MIDAS REST sessions, torch-based title-sheet ML, Selenium flows other
than the wrapped photo downloader.

## 5. Phases

### Phase 0 — Foundation (the skeleton walks)
- `civilpy/cli/` package; registry, batch front end, `ResultTable` +
  csv/xlsx/terminal writers; lazy-import + extras error convention.
- `ui.py`: CivilPy rich theme + `progress()`/`spinner()` helpers (§3a) —
  in from day one so every later command inherits the look.
- Port the two commands that already exist in script form:
  `odot slab` (has argparse) and `boring parse` (stdlib-only).
- `pyproject`: entry point moves from `civilpy.CLI:civilpy_cli` to the new
  package; delete the placeholder.
- Tests: registry synthesis from a sample Input dataclass; golden-file
  csv/xlsx output; `--help` snapshot.
- **Done when:** `civilpy boring parse B-001.xml --xlsx` produces a
  workbook, and `civilpy --help` lists both commands with docs pulled from
  the dataclasses.

### Phase 1 — Batch commands (file-in/file-out tier)
- `snbi validate`, `photos exif|rename|resize|stamp`, `report notebook`,
  `odot bridge`, `odot tiff join|split`, `boring batch`.
- Exit-code and logging conventions (`--quiet`, `--json` for CI).
- **Done when:** an SNBI submission and a photo-rename job each run
  end-to-end from a script with no Python knowledge.

### Phase 2 — Interactive shell (the primary UI appears)
- prompt_toolkit REPL: history, autosuggest, completion menus,
  bottom-toolbar field docs; slash commands `/help /commands /find
  /settings /units /clear /quit`.
- Completion sources: commands, flags, Literal choices, catalog values,
  extension-filtered paths.
- `/log` recording (session → replayable one-shot script).
- **Done when:** every Phase 0–1 command is discoverable and runnable via
  Tab-completion alone, with the relevant field doc visible while typing.

### Phase 3 — Calculators
- `hydro channel|pipe|scour`, `road vcurve|hcurve`, `struct
  section|beam|line-girder`, `geotech spt|bearing|capacity`.
- Multi-table xlsx workbooks (line-girder is the reference case).
- Plot sidecar outputs (`--plot` → png/html next to the workbook).
- **Done when:** `struct line-girder` reproduces the notebook workflow as
  one command with a complete workbook.

### Phase 4 — Session objects & chaining
- `session.py`: `load`, `/objects`, object-name completion, `--boring
  B-001`-style references; `/recent` persistence.
- `.3dm` (rhino3dm) and `.las` (laspy) loaders; `model 3dm
  objects|quantities`; `terrain elevation`; `lpile emit|parse|simulate`;
  `cande soil-zones` chained off loaded borings.
- **Done when:** load a boring + a terrain + a `.3dm`, and run scour,
  elevations, and a quantity roll-up against them without re-specifying
  paths.

### Phase 5 — Polish & ecosystem
- Shell completions for bash/zsh (one-shot mode), `--version`,
  config file (`~/.config/civilpy/`) for defaults + credentials pointers
  (reuse `example_secrets.json` conventions).
- Sphinx: auto-generate a CLI reference page from the registry (same
  source as `/help`).
- Plugin entry points (`civilpy.cli.commands` group) so `civilpy_private`
  ships internal-only commands into the same shell.
- Homebrew/pipx install notes in README; demo GIF.

## 6. Dependency decisions

| Dep | Status | Call |
|---|---|---|
| `rich` | already core | all terminal rendering: theme, tables, panels, progress bars/spinners |
| `prompt_toolkit` | **new core** | the shell *is* the product; pure-Python, 3.8+ |
| `openpyxl` | already core | xlsx writer |
| `argparse` | stdlib | one-shot mode; no click/typer (registry already owns the metadata they'd provide) |
| `rhino3dm`, `laspy`, `pydantic`, `tifftools`, `nbconvert`, PDF stack | existing extras | lazy per-command with friendly install hints |

## 7. Open questions (refine before Phase 0)

1. **Command grammar**: `civilpy scour pier` (group + verb, as drafted) vs
   `civilpy hydro scour-pier`? Draft assumes two-level max.
2. **Session persistence**: should `/quit` offer to save the workspace
   (object list + settings) per project directory, like a `.civilpy/`
   folder?
3. **Alignment/terrain input format**: alignments currently exist only as
   Python objects. Define a small `.csv`/`.json` alignment schema so
   `road alignment` works from files, or defer to Phase 4+?
4. **`.3dm` write-back**: is CLI-driven BrIM emit (layout inputs →
   tagged `.3dm`) wanted, or does authoring stay in Grasshopper with the
   CLI read-only on models?
5. **State-DOT scope in the public repo**: ODOT commands ship publicly;
   anything credentialed (AssetWise) — public with config, or move to a
   `civilpy_private` plugin (Phase 5 mechanism)?
6. **xlsx house style**: header formatting, units row vs `(unit)` in
   header, number precision — pick once, apply in the writer.
7. **Name**: keep `civilpy` as the binary, or add a short alias (`cvp`)?
