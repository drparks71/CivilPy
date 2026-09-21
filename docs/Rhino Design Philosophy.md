# Rhino ↔ Jupyter Design Philosophy

*Status: in development on branch `Modeling-Pipeline`. The Python read/write
bridge and a RhinoPython authoring prototype have shipped; a compiled C# plugin
and a Midas API path are planned. This document records the architectural
decisions, the schema contract, and the divided roadmap for using Rhino 3D as the
modeling front-end for civilpy structural analysis (starting with strut-and-tie).
See [Roadmap and separation of responsibilities](#roadmap-and-separation-of-responsibilities)
for the live task list.*

## Motivation

The current notebook workflow builds a model imperatively:

```python
model.add_node("A", 0, 0)
model.add_support("A", fix_x=True, fix_y=True)
model.add_load("E", fy=-600)
model.add_member("A", "B")
```

This is clunky for detailing real geometry. Rhino is a far better authoring
surface (best value for features + API accessibility), so the goal is to **draw
the model in Rhino and analyze it in Jupyter**, with a clean round trip.

The reference problem is FHWA-NHI-17-071 Example 1, already drawn in
`NHI17071_Ex_1.3dm` (units: **feet**, drawn flat in the **XZ plane** / front
elevation, Y = 0 throughout).

## Core principle

> **Geometry carries what is spatial; tags carry what is scalar.**

- *Spatial facts* live in the geometry: a member's connectivity is its endpoints,
  a load's direction is the arrow's vector, a support's location is its point.
- *Scalar / typed facts* live in **object user text** (Rhino attribute user
  text — a per-object key/value dictionary): magnitude, DOF fixity, and "kind".
- The **visual symbol** is either a chosen *block* (for supports — a fixed glyph)
  or the *drawn geometry itself* (for loads — the arrow is the data).

User text travels **with the object**, independent of its layer. This is
deliberately chosen over a layer-name convention: layers stay free for the
user's visual organization, and moving/recoloring/regrouping an object never
breaks the analysis. This is also how Grasshopper and Rhino plugins turn a plain
curve into a "smart" object.

**IFC alignment (forward-looking).** Vanilla Rhino has no native IFC-typed data,
so user text is the right carrier today. But we should keep the door open to a
future IFC bridge by naming tags after IFC structural concepts where sensible —
e.g. supports map to `IfcStructuralPointConnection`, loads to
`IfcStructuralLoadSingleForce`, members to `IfcStructuralCurveMember`. If a
better native carrier appears (an IFC-enabled object type via VisualARQ or a
future Rhino feature), the schema can migrate to it without changing the
geometry-vs-tags principle.

## The tag schema (`stm.*` namespace)

Encoded as Rhino object user text. Draft — names not final.

| Object kind | Geometry | Tags |
|---|---|---|
| Member | curve (line/polyline) | `stm.kind=member` preferred; an untagged curve falls back to a member |
| Support | block instance (or point) | `stm.kind=support`, `stm.fix_*` DOF flags (see below); optional `stm.bearing` |
| Load | line / arrow | `stm.kind=load`, `stm.kips=600` (direction from the line's vector); optional `stm.bearing` |
| Region (D-region domain) | closed planar curve | `stm.kind=region`, `stm.thickness`, `stm.fc` (+ optional `stm.E`, `stm.nu`, `stm.vol_frac`) — the concrete area the optimizer fills with a truss |
| Void | closed planar curve inside a region | `stm.kind=void` — a mandatory hole (duct/opening); those elements stay empty |
| Solid (keep-in) | closed planar curve inside a region | `stm.kind=solid` — a zone that must stay solid concrete (bearing/anchorage block); those elements stay full |

**Members:** tagging `stm.kind=member` is the explicit, preferred form, but the
importer treats any untagged curve as a member so quick sketches still work.

**Support fixity — store 6-DOF, consume the 2D subset.** Even though the current
STM solver is a 2D pin-jointed truss (translational DOF only), the tag schema
records the full set so the same model can later drive frame analysis and the
Midas API (true 3D, moving loads) without re-authoring:

`stm.fix_x`, `stm.fix_y`, `stm.fix_z`, `stm.fix_rx`, `stm.fix_ry`, `stm.fix_rz`
(booleans). A friendly `stm.support=pin|roller-v|roller-h|fixed|custom` sets the
common cases; explicit `stm.fix_*` flags override for custom fixity. The STM
importer reads only the in-plane translations (`fix_x`, `fix_y`); the rest is
forward-compatible metadata.

Nodes are **not** authored explicitly. They are derived by snapping member
endpoints together within a tolerance, deduping, and auto-labeling (A, B, C…
ordered left→right then bottom→top, so labels are stable and read like an
elevation). Supports/loads attach to whichever derived node they coincide with.

### Two front ends: author a truss, or author a region

The schema supports **two authoring workflows that share the same support and
load objects**:

1. **Draw the truss** (original workflow). The author lays out members; nodes are
   derived from endpoints; `from_3dm` returns a `StrutAndTieModel` ready to solve.
   Use when the load path is already known.
2. **Draw the region** (topology-optimization workflow). The author draws only the
   concrete outline as a closed `stm.kind=region` curve (a rectangle or an
   arbitrary polygon, optionally with `stm.kind=void`/`solid` inner curves), plus
   the same supports and loads. **No members are drawn.** civilpy meshes the
   region, runs SIMP topology optimization to find where concrete wants to be,
   skeletonizes the result into a truss, and hands back an (indeterminate)
   `StrutAndTieModel`. Use when you want civilpy to *discover* the strut-and-tie
   layout.

**Dispatch rule:** a file containing any `stm.kind=region` object is an
optimization problem; otherwise it is a drawn truss. Supports and loads are
identical in both — in the region workflow they become the finite-element
boundary conditions rather than joint conditions, so a model can migrate from
"draw the region, optimize" to "tune the resulting truss" without re-authoring
the boundary conditions.

**Bearing length.** Supports and loads may carry an optional `stm.bearing=<L>`
(model length units) giving the in-plane bearing width. The optimizer spreads the
reaction/applied force over that width (a point load on a continuum mesh is a
stress singularity), and the same width × `stm.thickness` gives the nodal-zone
bearing area `Acn` for the AASHTO 5.8.2.5 node check. Absent, a default tied to
the mesh size is used and the node check is skipped for that point.

**Units for the new tags.** Geometry and `stm.thickness`/`stm.bearing` are in the
model's length units (feet); `stm.fc` and `stm.E` are in **ksi**; the optional
`stm.vol_frac` is dimensionless (0–1). Numerical-method knobs (penalization,
density-filter radius, mesh resolution, move limit) are **not** authored in the
`.3dm` — they are Python-side optimizer arguments with defaults, keeping the file
a description of the *physics*, not the solver.

### Plane mapping

The model is drawn in the XZ plane (front elevation). The 2D analysis uses
(x, y). Map **X → x, Z → y**, with gravity = −Z. The importer should detect the
working plane rather than hard-coding it.

## Automatic visual representation

The feature we want: declaring an object's *kind* should produce the right
*symbol* automatically — a load is an arrow oriented with the force, a pin is a
triangle, a roller is a circle, a fixed support is a hatched line.

Mechanism options in Rhino:

1. **Block instances as symbols (preferred for supports).** Define a block per
   symbol type (`STM_Pin` triangle, `STM_Roller` circle, `STM_Fixed` hatch,
   `STM_Load` arrow). An inserted instance carries three things `rhino3dm` can
   read: the geometry (the glyph, drawn correctly and automatically), a transform
   (position + rotation → location and direction/skew), and attributes/user text
   (the structural data). Magnitude can scale the block.
2. **Generated symbol geometry from tags.** A "rebuild symbols" script reads tags
   and (re)draws triangle/circle/hatch/arrow geometry on a derived layer. Source
   data stays minimal; symbols are disposable and always consistent. Requires
   running the refresh.
3. **Display conduit (live overlay).** A `Rhino.Display.DisplayConduit` draws
   symbols on screen in real time from tags, without creating saved geometry.
   Most "alive"; most moving parts; overlay isn't persisted as geometry.

**Leaning:** blocks for supports (discrete glyph types; rotation handles skewed
supports cleanly), and loads as a tagged line/arrow (the geometry *is* the
direction, which is more robust than parsing block rotation; magnitude in a tag).

### Authoring commands (run locally in Rhino)

Small RhinoCommon/Python commands make "declare = draw the symbol + stamp the
tags" a single step, e.g.:

- `STMSupport` → pick a point → choose Pin / Roller / Fixed → inserts the correct
  symbol block **and** writes the DOF tags.
- `STMLoad` → pick the node, drag direction, type kips → draws the arrow and
  writes `stm.kips`.

These run in Rhino's script editor standalone, so they are
compatible with the ODOT environment (see constraints).

## The analysis bridge

The **tagged `.3dm` is the source of truth.** Three possible bridges to Jupyter:

| Bridge | What it is | Cost |
|---|---|---|
| **File round-trip (`rhino3dm`)** | Notebook reads/writes the saved `.3dm`; Rhino and Jupyter stay decoupled. | Tiny pip package; not live (save, then re-run). |
| **Analysis inside Rhino's Python** | Rhino 8 ships CPython 3 + pip; run analysis from the ScriptEditor with full RhinoCommon. | One environment; weaker Jupyter UX; must pip civilpy/numpy into Rhino. |
| **RhinoInside (`rhino-inside`)** | Load full Rhino into normal CPython so the notebook gets RhinoCommon live. | Powerful; heavyweight; licensing + harder IT approval. |

**Decision:** anchor on the **file round-trip via `rhino3dm`** for the analysis
read, even if Rhino is present. It keeps analysis reproducible and decoupled from
whether Rhino is running. Reserve live RhinoCommon for *authoring and visuals*,
not for the analysis read.

Target notebook surface:

```python
model = StrutAndTieModel.from_3dm(r"...\NHI17071_Ex_1.3dm")
model.plot()           # existing matplotlib view
forces = model.forces  # feeds the AASHTO capacity checks unchanged
```

Optional write-back: `results_to_3dm(model, path)` colors members strut/tie and
adds force labels for review in Rhino.

## Constraints

- **ODOT / AI policy:** AI tools are prohibited on ODOT machines. The
  constraint is therefore that everything we build must be **self-contained and
  runnable by the user with no AI tooling at runtime**, with dependencies tame
  enough for IT approval. It is *not* a statement about Rhino — Rhino is expected
  to be available in the ODOT environment.
- **Dependencies:** `rhino3dm` is a small pip package (`pip install
  civilpy[rhino]`); `numpy`/`matplotlib`/`scipy` already in use. The
  topology-optimization pipeline's heavier libraries (`pygmsh`, `scikit-fem`,
  `scikit-image`, `networkx`) live in a separate `pip install civilpy[fem]`
  extra and are imported lazily, so neither the truss solver nor the Rhino
  bridge pulls them in. RhinoInside adds the most approval risk.

## Resolved decisions

1. **Tag carrier:** object user text (`stm.*` namespace), unless a native
   IFC-enabled data type becomes available (see IFC alignment).
2. **Members:** `stm.kind=member` preferred; untagged curves fall back to member.
3. **Symbols:** blocks, with explicit per-DOF fixity overrides; schema stores
   full 6-DOF for future frame/Midas use, STM consumes the 2D subset.
4. **Load magnitude:** tag value (`stm.kips`) with a text label on the arrow.
   Optional later polish: scale the arrow proportionally over a typical band
   (~1–80 kips covers pedestrian to rail axle loads). Minor enhancement.
5. **First build scope:** importer + write-back + authoring commands — but settle
   the authoring-tool question below first.

## Authoring layer: Python scripts vs. compiled plugin

The authoring tools (create a load/support object: insert the symbol block +
stamp the tags) can be delivered two ways. This matters for **accessibility** —
the target audience includes non-programmers (students, intro users) who are
wary of running Python scripts, and a toolbar button labeled "Add Load" is
*1000× more approachable* than "run this script".

| Path | What it is | Pros | Cons |
|---|---|---|---|
| **Python scripts** | RhinoCommon/`rhinoscriptsyntax` run via ScriptEditor; can be aliased to commands and pinned to toolbar buttons. | Fast to prototype; same language as civilpy; validates schema + block geometry quickly. | Distribution/install is manual; users must trust/enable scripts. |
| **C# / .NET plugin** | Compiled `.rhp` (RhinoCommon). Real commands, toolbar buttons, Eto.Forms panels. Distributable via Rhino's **Yak** package manager (`_PackageManager` → install → buttons appear). | Professional, trusted install; native UI buttons; the accessible answer for non-programmers. | Separate C# codebase + build/packaging alongside Python civilpy; two languages. |
| **C++ (Rhino C++ SDK)** | Native plugin. | Maximum performance/SDK access. | Heaviest; **no benefit here over C#** — recommend against. |

**Recommendation:** prototype the command logic in **Python** first (cheap, nails
down the tag schema and block geometry), then port the proven commands to a
**C# RhinoCommon plugin** distributed via Yak for the button-driven UX. C# over
C++ — C++ buys nothing for insert-block + set-user-text commands.

This language split is *validated by the architecture*: because the source of
truth is the tagged `.3dm`, the C# authoring plugin and the Python analysis
never talk directly — they communicate only through the file + tag schema. Each
can be built and versioned independently.

### Mock-up — Python prototype (`STMLoad`)

Illustrative only, not built. Shows the command flow and where tags are stamped.

```python
import Rhino
import scriptcontext as sc

def STMLoad():
    # 1. pick the node the load acts on
    gp = Rhino.Input.Custom.GetPoint()
    gp.SetCommandPrompt("Pick loaded node")
    if gp.Get() != Rhino.Input.GetResult.Point:
        return
    node = gp.Point()

    # 2. drag the arrow to set direction
    gd = Rhino.Input.Custom.GetPoint()
    gd.SetCommandPrompt("Drag load direction")
    gd.SetBasePoint(node, True)
    if gd.Get() != Rhino.Input.GetResult.Point:
        return
    tip = gd.Point()

    # 3. magnitude
    gn = Rhino.Input.Custom.GetNumber()
    gn.SetCommandPrompt("Load magnitude (kips)")
    gn.Get()
    kips = gn.Number()

    # 4. insert the arrow block oriented along node->tip, scaled by band
    xform = _orient_and_scale("STM_Load", node, tip, kips)
    iref_id = sc.doc.Objects.AddInstanceObject(_defn("STM_Load"), xform)

    # 5. stamp the tags (the "advanced object")
    obj = sc.doc.Objects.FindId(iref_id)
    a = obj.Attributes
    a.SetUserString("stm.kind", "load")
    a.SetUserString("stm.kips", str(kips))
    sc.doc.Objects.ModifyAttributes(obj, a, True)
    sc.doc.Views.Redraw()
```

### Mock-up — C# plugin command equivalent

```csharp
[CommandStyle(Style.ScriptRunner)]
public class STMLoadCommand : Command
{
    public override string EnglishName => "STMLoad";

    protected override Result RunCommand(RhinoDoc doc, RunMode mode)
    {
        if (RhinoGet.GetPoint("Pick loaded node", false, out Point3d node)
                != Result.Success) return Result.Cancel;
        if (RhinoGet.GetPoint("Drag load direction", false, out Point3d tip)
                != Result.Success) return Result.Cancel;
        double kips = 0;
        if (RhinoGet.GetNumber("Load magnitude (kips)", false, ref kips)
                != Result.Success) return Result.Cancel;

        var xform = OrientAndScale("STM_Load", node, tip, kips);
        var idefIndex = doc.InstanceDefinitions.Find("STM_Load").Index;

        var attr = new ObjectAttributes();
        attr.SetUserString("stm.kind", "load");
        attr.SetUserString("stm.kips", kips.ToString());

        doc.Objects.AddInstanceObject(idefIndex, xform, attr);
        doc.Views.Redraw();
        return Result.Success;
    }
    // A toolbar button just runs "! _STMLoad" — one click for the user.
}
```

The toolbar button (`.rui`) issues `! _STMLoad`, so the end user clicks "Add
Load" and never sees code. Same pattern for `STMSupport` (choose Pin/Roller/Fixed
or set custom DOF) and a future `STMMember`.

## Implementation status (what shipped)

The first build landed on branch `Modeling-Pipeline`:

- **`civilpy.structural.rhino_stm`** — the read/write bridge (optional
  `rhino3dm` dep, `pip install civilpy[rhino]`):
  - `model_from_3dm(path, plane="auto", tol=...)` and the convenience
    `StrutAndTieModel.from_3dm(...)` — reads members (tagged or untagged
    fallback), supports, and loads; derives + labels nodes; detects the plane.
    Understands **both** Rhino-authored block-instance symbols **and** the
    tagged points/lines this package writes. Now parses once into the canonical
    hub and projects to 2D (see S2/S3 below).
  - `read_structural_model(path, plane="auto", tol=...)` (also
    `model_from_3dm(..., as_model=True)`) — reads the same file into the
    canonical `StructuralModel` hub, keeping full 3D coordinates, 6-DOF
    restraints, support presets, stable ids, and 3D load vectors.
  - `model_to_3dm(model, path)` / `StrutAndTieModel.to_3dm(...)` — writes a
    tagged model.
  - `results_to_3dm(model, path)` — solved-model write-back (ties red, struts
    blue, force + reaction text dots).
  - `build_template(path)` — starter `.3dm` with the STM layers.
- **Assets:** `templates/STM_Template.3dm` (layers) and
  `Notebooks/NHI17071_Ex_1_STM.3dm` (the tagged Example 1, round-trip-verified
  against the FHWA worked values — bottom tie 1012.5 kips, vertical tie 600).
- **Authoring prototype:** `src/civilpy/structural/rhino_scripts/stm_authoring.py` — RhinoPython
  `STMTemplate` / `STMSupport` / `STMLoad`, run inside Rhino.
- **Tests:** `tests/structural/test_rhino_stm.py` (skipped without `rhino3dm`).

### rhino3dm constraint that shaped the writer

rhino3dm 8.x's `InstanceDefinitions.Add` corrupts process memory
probabilistically (verified: it segfaults under repeated calls regardless of
curve type, and a cyclic-GC pass during construction triggers it). It is not
safe in a library function. Consequences, all already reflected above:

- The **Python writer emits tagged points (supports) and tagged lines
  (loads/members)** — only the rock-solid `AddLine`/`AddPoint` paths. This still
  honors *geometry spatial, tags scalar*; the arrow line's vector is the force
  direction, `stm.kips` is the magnitude.
- **Symbol *blocks* are created inside Rhino** (RhinoCommon's instance API is
  reliable), by `src/civilpy/structural/rhino_scripts/stm_authoring.py` and, later, the C# plugin —
  ensured on first use, the standard plugin pattern. `build_template` therefore
  ships **layers only**.
- The **reader still parses block-instance symbols**, so models authored with
  the rich Rhino symbols import correctly.

The earlier symbol/glyph mock-ups remain the spec the in-Rhino tools implement.

## Package coherence: the canonical structural model

*This is a long-term architectural track, not a one- or two-PR change. It is
documented here, before more is built, so every increment moves toward a coherent
package instead of adding another disconnected representation. The Rhino work is
the forcing function that surfaced the need, but the payoff is package-wide.*

### The actual goal

The deliverables wanted are **Rhino → STM** and **Rhino → Midas**. Note what both
share: a single Rhino read that must feed *two* different consumers. If each
consumer gets its own bespoke reader, the package fragments. The cohesive answer
is one read into a **canonical structural model**, then independent adapters off
of it:

```
                          ┌──────────────────────────┐
        tagged .3dm  ───► │  canonical StructuralModel │ ───► STM solver (2D view)
        (Rhino)           │  (IFC-aligned vocabulary)  │ ───► Midas payloads → API
        IFC 4.3      ◄──► │  nodes · elements · 6-DOF  │ ───► .3dm write-back (results)
        (from_ifc/        │  restraints · loads ·      │ ───► capacity checks (forces→ratings)
         to_ifc)          │  cases · results · ids     │ ◄──► IFC 4.3 (+ Pset_CivilPy_*)
        MIDAS model  ───► │                            │
        (future read)     └──────────────────────────┘
                                   the hub
```

`Rhino → STM` = read into the hub, project to 2D, solve. `Rhino → Midas` = read
into the **same** hub, serialize to payloads, push. The Rhino reader is written
once; the two adapters never touch each other. This is the same decoupling logic
already used at the file boundary (§Roadmap), pushed one level inward to the
in-memory model.

### What exists today — and the seams

Cross-checking the package, there are **three in-memory representations of "a
structure"**, none of which is shared:

1. **`StrutAndTieModel` / `Truss`** — `nodes{label:(x,y)}`, `members[(a,b)]`,
   `loads{node:[fx,fy]}`, `supports{node:(fix_x,fix_y)}`. **2D, 2-DOF, single
   implicit load case.** Solver = method of joints.
2. **`TrussBridge`** — its *own* 3D node/element generation, typed `Member`
   classes carrying `midas_type` + `expected`, deck/lane/floor load path. Emits
   MIDAS payloads via `midas_payloads()` / `to_midas()`.
3. **MIDAS payload dicts** — `{table:{id:{...}}}`, 3D, 7-char `CONS` DOF strings,
   real element types. Produced independently by `TrussBridge` *and* by
   `midas_models` (curved/bifurcated/abutment/soil-spring builders).

The seams that hurt coherence:

- **Lossy STM model.** `supports` holds only `(fix_x, fix_y)`. The full 6-DOF a
  Midas boundary condition needs exists only in the `.3dm` tags, so a
  Rhino→Midas path that went *through* `StrutAndTieModel` would silently drop
  `fix_z/rx/ry/rz`. Rhino→Midas must therefore **not** route through the 2D STM
  model — another reason for a richer hub.
- **Two Midas serializers.** `TrussBridge.midas_payloads()` and `midas_models.*`
  each encode NODE/ELEM/CONS/UNIT/MATL independently. The CONS-string,
  unit-block, and steel-material encodings are duplicated and can drift.
- **Two node-derivation strategies.** `rhino_stm` snaps/labels nodes from
  geometry; `TrussBridge` generates them from panel geometry. Both legitimately
  exist, but neither produces a shared node object.

### The decision: a data hub + adapters (composition), engines stay separate

**Composition, not a shared solver base class.** The three analysis paradigms in
the package solve genuinely different math — pin-jointed method of joints
(`StrutAndTieModel`/`Truss`/`TrussBridge`), continuous-beam/frame relaxation
(`MomentDistribution`, `pier.solve_continuous_beam`/`MultiColumnBent`), and an
external FEM (`cande.BoxCulvertModel`). Forcing them under one inheritance tree
would couple unrelated algorithms. But they all *describe the same kind of
thing*: a discretized structure with geometry, restraints, loads, and results.

So share the **data**, not the behavior:

- **`StructuralModel`** — a pure data hub (dataclasses: `Node`, `Element`,
  `Restraint` (6-DOF), `Load`, `LoadCase`, `Result`). **3D, full 6-DOF,
  multi-case, stable ids.** No solver lives on it — it is the interchange
  representation, the in-memory analogue of the tagged `.3dm`.
- **Engines consume/produce the hub.** `StrutAndTieModel` keeps its method-of-
  joints solver but gains `from_structural_model(hub)` / `to_structural_model()`
  (a 2D projection in/out). `TrussBridge` becomes a *generator* that emits the
  hub. Solvers never inherit from the hub; they hold or build one.
- **Adapters are pure functions over the hub.** `from_3dm(path) ->
  StructuralModel`, `to_3dm(model)`, `midas_payloads(model)`,
  `push_midas(model, client)`. Each is independently testable with no live
  session, mirroring the existing `midas_models` pure-builder style.
- **The typed `Member` taxonomy migrates onto the hub element's `role`.**
  `TopChord`/`Diagonal`/… and their `midas_type` + `expected` become a `role`
  attribute on `Element`, which simultaneously drives (a) Midas element type and
  (b) which AASHTO capacity check runs. One taxonomy, two uses.
- **Capacity calculators read `Result`, not geometry.** The stateless design side
  (`aashto`, `steel`, `wood`, `concrete`, `section_properties`, the
  `beam_bending` stress helpers) consume forces → ratings. They hang off the
  hub's results, completing the package story: *analysis models produce a hub;
  the hub feeds solvers, exporters, and checks.*

### IFC 4.3 as the hub vocabulary (and where it must be extended)

**Decision: align the hub to the IFC 4.3 `IfcStructuralAnalysisDomain`, and
extend it for the analysis↔design gap via property sets — not a schema fork.**
This continues the IFC alignment already chosen for the `stm.*` tag names
(§Core principle), so the vocabulary is consistent end to end:
**Rhino tag → hub field → IFC entity.**

A common misconception is that IFC is "just visual." Its *structural analysis*
domain is in fact a real linear-idealization schema and covers most of the hub:

| Hub concept | IFC 4.3 entity | Notes |
|---|---|---|
| analysis model | `IfcStructuralAnalysisModel` | 2D/3D container |
| node | `IfcStructuralPointConnection` | |
| support / restraint (6-DOF) | `IfcBoundaryNodeCondition` (+ `…Warping` for the 7th DOF) | maps directly to the MIDAS `CONS` `DX DY DZ RX RY RZ RW` string |
| member (strut/tie/beam) | `IfcStructuralCurveMember` | `PredefinedType`: tie ≈ `TENSION_MEMBER`, strut ≈ `COMPRESSION_MEMBER`, also `PIN_JOINED_MEMBER` / `RIGID_JOINED_MEMBER` |
| plate / wall | `IfcStructuralSurfaceMember` | future (shell models) |
| load case | `IfcStructuralLoadCase` (subtype of `IfcStructuralLoadGroup`) | the `stm.case` tag |
| point load | `IfcStructuralLoadSingleForce(Warping)` via `IfcStructuralPointAction` | |
| line / area load | `IfcStructuralLoadLinearForce` / `…PlanarForce` | |
| result / reaction | `IfcStructuralPointReaction` / `…CurveReaction` in `IfcStructuralResultGroup` | |
| bridge geometry / alignment | `IfcAlignment`, `IfcBridge` | the 4.3 infrastructure additions |

So nodes, **full 6-DOF supports**, members, load cases, and reactions are already
standard — that is the bulk of the canonical hub, for free and interoperable.

**The genuine gaps are the analysis↔design bridge** — which is exactly the STM
and reinforcement territory civilpy is built for:

1. **Reinforcement as analysis input.** `IfcReinforcingBar`, `IfcReinforcingMesh`
   (the rebar *mat*), and `IfcTendon` exist — but in the *physical/detailing*
   model, **not linked as properties of an analysis member**. For STM the tie
   *is* rebar, so this missing association is precisely the one needed.
   → `Pset_CivilPy_TieReinforcement` on the curve member, or an
   `IfcRelAssociates` link to the physical `IfcReinforcingMesh`.
2. **STM nodal-zone semantics** — CCC/CCT/CTT node classification, nodal-zone
   stress limits, bearing/anchorage detail (AASHTO 5.8.2.5). Absent from the
   analysis domain. → `Pset_CivilPy_STMNode`.
3. **Capacity / code-check data** — φFₙ, demand/capacity ratios, governing limit
   state. → `Pset_CivilPy_CapacityCheck` (results, attached to members/nodes).
4. **Vehicular live load / traffic lanes / influence** — IFC analysis carries
   static load cases, not the moving-load + lane concepts the Midas `LLAN` path
   uses (4.3 added the alignment/bridge *infrastructure*, not live-load
   definitions). → `Pset_CivilPy_LiveLoad`, or keep lane data in the Midas
   adapter until a standard emerges.

**Mechanism:** extend through buildingSMART's sanctioned route — `IfcPropertySet`
(`Pset_CivilPy_*`) and `IfcClassificationReference` on standard entities — never a
forked schema. **The hub stays clean civilpy dataclasses** whose field names
mirror these IFC entities; `ifcopenshell` appears only at the `from_ifc`/`to_ifc`
boundary as an optional dependency (`pip install civilpy[ifc]`, mirroring
`[rhino]`), so the solvers never carry a heavy IFC dependency. IFC becomes one
more adapter off the hub, alongside `.3dm` and MIDAS — not the in-memory model
itself.

This adds an IFC spoke to the hub diagram: `from_ifc(path) -> StructuralModel`
and `to_ifc(model, path)`, making civilpy models interoperable with any
IFC-aware tool (Revit, Tekla, SAP2000/ETABS IFC export, Civil NX IFC) while the
`Pset_CivilPy_*` layer carries the reinforcement/STM/design data the standard
omits.

### Scope boundary (deliberate non-goals, for now)

- **Frame/beam and FEM paradigms are not folded in yet.** `MomentDistribution`,
  `pier`, and `cande` stay as-is. But the hub's `Node`/`Element`/`Load`
  vocabulary should be designed general enough that a frame or beam engine
  *could* later consume it — design for it, don't build it.
- **`StrutAndTieModel`'s existing 2D convenience API stays.** Backward
  compatibility is a hard constraint; the hub is added *underneath*, not in place
  of, the current `add_node/add_member` surface. Existing notebooks keep working.

### Incremental, non-breaking migration

Each stage is independently shippable, additive, and leaves all current tests
green. Stop-anywhere ordering:

- [x] **S1 — Define `StructuralModel`** dataclasses (`Node`/`Element`/`Restraint`/
  `Load`/`LoadCase`/`Result`), 3D + 6-DOF + ids + cases. Pure data, fully
  unit-tested. Nothing else changes yet. **→ Shipped (Python):**
  `src/civilpy/structural/structural_model.py` + `tests/structural/
  test_structural_model.py` (27 tests). IFC-aligned field vocabulary;
  `Restraint.to_constraint_string()` emits the MIDAS 7-char `CONS` string,
  `.to_2d()` projects to the STM `(fix_x, fix_y)` subset; `member_type` defaults
  to `auto`; `Units` carried as kips/ft labels (conversion stays in adapters);
  `check()` provides the named pre-solve diagnostics. Resolved open questions:
  name = `StructuralModel`; units = explicit labels, not pint in the hub.
- [x] **S2 — `rhino_stm` reads into the hub. → Shipped.** `rhino_stm.
  read_structural_model(path, plane="auto", tol=...)` (and `model_from_3dm(...,
  as_model=True)`) return the rich hub with full 6-DOF, genuine 3D node
  coordinates, the support preset, stable ids, and full 3D load vectors. A
  single `_read_raw` parser now feeds both the hub reader and the 2D path, so
  the two never drift. This unblocks Rhino→Midas (the 6-DOF fixity the lossy
  `StrutAndTieModel` dropped now survives the read).
- [x] **S3 — STM ↔ hub interconversion. → Shipped.**
  `StrutAndTieModel.from_structural_model(hub, plane="auto")` projects the hub
  to 2D; `.to_structural_model(plane="XZ")` lifts the 2D model back up (carrying
  solved forces/reactions into a `Result`). `model_from_3dm` now parses once
  into the hub and returns `from_structural_model(hub)` — the 2D path is a thin
  projection of the hub, public behavior unchanged (all prior tests green).
- [x] **S4 — One Midas serializer. → Shipped (Python).** Extracted the shared
  encoding into `midas_models` helpers — `STEEL_PROPS`, `unit_block` /
  `unit_block_for(Units)`, `steel_material_block`, `placeholder_section_block`,
  `constraint_assign` — and `TrussBridge` now builds its UNIT/MATL through them
  (output byte-identical, regression-tested). Added
  `midas_models.midas_payloads(StructuralModel)` (pure; emits UNIT/MATL/SECT/
  NODE/ELEM/CONS/STLD/CNLD, mapping the hub's full 6-DOF restraints to the
  `CONS` string and loads to STLD cases + CNLD nodal forces) and
  `push_midas(model, midas=None, **client_kwargs)` (mirrors
  `TrussBridge.to_midas`'s per-table `{"sent": n} | {"error": ...}` report).
  **This is the Rhino→Midas adapter**: `read_structural_model(path)` →
  `push_midas(hub)`, never through the lossy 2D STM model. (CNLD layout follows
  the manual, unverified against a live Civil NX session.)
- [ ] **S5 — Refactor `TrussBridge` onto the shared serializer.** Have
  `TrussBridge.midas_payloads()` build the hub then call the shared serializer,
  collapsing the two Midas encoders into one. Keep its public API and report
  shape identical (regression-test against current output).
- [ ] **S6 — Migrate the `Member` taxonomy to `Element.role`.** Map role →
  `midas_type` and role → capacity check in one place; `TrussBridge` and the hub
  share it.
- [ ] **S7 — Wire capacity checks to `Result`.** A thin path from hub results into
  the existing AASHTO/steel/wood/concrete calculators, so a solved hub can be
  rated without manual force plumbing.
- [ ] **S8 — IFC adapter (optional `[ifc]` dep).** `from_ifc`/`to_ifc` over the
  hub via `ifcopenshell`, mapping the entity table above and reading/writing the
  `Pset_CivilPy_*` extension sets. Pure, fixture-tested against a small committed
  `.ifc`. Independent of S2–S6; can land whenever IFC interop is wanted.
- [ ] **S9 — `Pset_CivilPy_*` extension schema.** Define and document the
  reinforcement (rebar mat/tie), STM nodal-zone, capacity-check, and live-load
  property sets — the analysis↔design data IFC omits. This is the long-tail
  standards work; version it explicitly.

### Risks / open questions to settle as we go

- [x] **Hub vs. an external schema. → Resolved: IFC 4.3-aligned dataclasses.**
  The hub mirrors the `IfcStructuralAnalysisDomain` vocabulary with
  `Pset_CivilPy_*` extensions for the reinforcement/STM/design gap; `ifcopenshell`
  is an optional adapter, not the in-memory model (see §"IFC 4.3 as the hub
  vocabulary"). Remaining sub-question: confirm IFC 4.3's structural-analysis
  entities are unchanged from IFC4 (they are stable; 4.3's additions are the
  alignment/bridge infra) so we can target 4.3 for bridges without losing the
  analysis entities.
- [x] **Naming. → Resolved: `StructuralModel`.** No collision with the existing
  `*Model` classes (`BoxCulvertModel` is unrelated); matches the name used
  throughout this doc.
- [ ] **How far does "general enough for frames" go** before it's speculative
  generality? Bias toward what the truss/STM/Midas paths actually need now.
  (S1 leans lean: 3D coords, 6-DOF restraints, force+moment loads, element
  `role`/`member_type`/`midas_type` — enough for truss/STM/Midas, no shell/FE
  fields yet.)
- [x] **Units in the hub. → Resolved: explicit labels, conversion in adapters.**
  The hub carries a lightweight `Units(force, length)` (default kips/ft); numeric
  conversion stays in adapters (e.g. `midas.convert_node_units` via the
  `civilpy.general.units` pint registry), keeping the hub dependency-light.

## Roadmap and separation of responsibilities

Two codebases are now developed **in parallel**:

- **Python (this repo, `civilpy`)** — the analysis + file-bridge side.
- **C# / .NET RhinoCommon plugin (separate solution, built in Rider)** — the
  authoring + UI side, distributed via Yak.

They **never call each other.** The only thing they share is the **tag schema +
file format contract** below. Treat that contract as the API between the two
projects: neither side may change a tag name, value encoding, units convention,
or plane mapping without updating §"Shared contract" *and* notifying the other
side. This is the whole reason the file-round-trip architecture was chosen — it
lets the two languages ship and version independently.

```
   C# plugin (Rider)              tagged .3dm                Python (civilpy)
   ─────────────────         (source of truth)            ─────────────────
   STMSupport  ─┐                                          ┌─ model_from_3dm
   STMLoad      ├──── writes ──►  stm.* user text  ◄── reads ─┤  solve()
   STMMember   ─┘                 + geometry          writes ─┤  results_to_3dm
   STMResults  ◄──── reads ───────────────────────────────────┘
        ▲                                                       │
        └──────────── (future) Midas API  ◄────────────────────┘
```

### Shared contract (frozen interface — change deliberately)

Both sides MUST agree on all of the following. The Python side is the reference
implementation (`src/civilpy/structural/rhino_stm.py` constants); the C# side
mirrors it.

| Item | Value | Notes |
|---|---|---|
| Tag namespace | `stm.` prefix on all keys | object user text (attribute user strings) |
| Member | `stm.kind=member` | untagged curve also accepted as member |
| Member type | `stm.member=auto\|tie\|strut` | `auto` is the default and is **never written** (absent tag = auto); `tie`/`strut` are optional author overrides |
| Support | `stm.kind=support` | block instance **or** point geometry |
| Support preset | `stm.support=pin\|roller-v\|roller-h\|fixed\|custom` | sets common DOF; `fix_*` overrides win |
| DOF flags | `stm.fix_x/y/z/rx/ry/rz` = `true\|false` | lowercase booleans; full 6-DOF stored |
| Load | `stm.kind=load`, `stm.kips=<float>` | direction from arrow line vector (tip − tail) |
| Region | `stm.kind=region` on a closed planar curve | the D-region domain to optimize; its presence switches the importer to the optimization path |
| Region material/geometry | `stm.thickness` (ft), `stm.fc` (ksi); optional `stm.E` (ksi), `stm.nu`, `stm.vol_frac` | physical SIMP + capacity-check inputs; absent optionals fall back to Python defaults |
| Void / solid zones | `stm.kind=void` / `stm.kind=solid` on closed inner curves | passive empty / passive full regions (holes, keep-in blocks) |
| Bearing length | `stm.bearing=<float>` (ft) on support or load | in-plane loaded width; spreads the FEA point load, gives nodal `Acn = bearing × thickness` |
| Units | model unit system = **feet**; forces in **kips**; `stm.fc`/`stm.E` in **ksi** | reader honors `File3dm.Settings.ModelUnitSystem` |
| Plane | drawn in **XZ** (front elevation), gravity = −Z | reader auto-detects; X→x, Z→y |
| Block names | `STM_Pin`, `STM_Roller_V`, `STM_Roller_H`, `STM_Fixed`, `STM_Load` | C# creates them; Python reader maps them back |
| Result colors | tie = red `(200,0,0)`, strut = blue `(0,0,255)` | written by `results_to_3dm`; C# `STMResults` reads/recolors |
| File version | write `.3dm` v7+ | both sides read v5–v8 |

**Open contract questions to resolve jointly before they harden:**

- [ ] **Stable object identity.** Auto-derived node labels (A, B, C…) are
  positional and will renumber if geometry moves. For results write-back and for
  Midas, decide whether the C# plugin stamps a persistent `stm.id` (GUID) on each
  authored object so Python can round-trip results to the *same* object rather
  than by nearest-point. **Recommendation: yes** — cheap on the C# side, removes
  all nearest-node ambiguity. Owner: joint; C# stamps, Python reads/preserves.
- [x] **Member type hint. → Resolved.** `stm.member` is part of the contract with
  values `auto | tie | strut`. **`auto` is the invisible default** — the analysis
  decides from the solved sign (tension = tie, compression = strut), and an
  untagged or `auto` member is never written explicitly (keeps clean models
  clean). `tie` and `strut` are **optional author overrides** that force the
  classification regardless of sign — for detailing intent or to flag a member
  the author expects to behave a certain way. Python: read the hint, honor it for
  display/classification, and warn if a forced `tie` solves in compression (or
  vice-versa) — that mismatch is a useful modeling signal, not an error. C# UI:
  default has no `stm.member` tag; the override is a non-default dropdown choice.
- [ ] **Load combinations / cases.** A `stm.case=<name>` tag so one file can hold
  multiple load cases. Needed before Midas (which is multi-case by nature).
  Defer, but reserve the tag name now.
- [ ] **Girder-line tag namespace (new, for the splice pipeline).** The line
  girder → field splice workflow (§"Line girder → field splice — TODO") needs
  tags the STM contract doesn't have: girder lines carrying a rolled shape,
  bearing stations, deck parameters, and splice markers. **Recommendation: a
  parallel `gdr.*` namespace** (`gdr.kind=girder|support|splice`,
  `gdr.shape=<AISC label>`, …) rather than overloading `stm.kind` — the frozen
  STM contract and its readers stay untouched, and the two workflows can't
  corrupt each other's files. Reserve the prefix now; freeze the key list when
  G1 lands. Owner: joint (C# proposes, Python is the reference reader, same as
  `stm.*`).

### Python side — TODO (this repo)

Shipped (see "Implementation status"): `model_from_3dm`, `model_to_3dm`,
`results_to_3dm`, `build_template`, `StrutAndTieModel.from_3dm/.to_3dm`, 8 tests.

**Already in the codebase — reuse, do not rebuild** (verified by cross-checking
`strut_and_tie.py`, `truss.py`, `truss_builder.py`, `midas.py`, `midas_models.py`):

- **Solver-time validation already exists.** `StrutAndTieModel.solve()` raises a
  clear `ValueError` for an indeterminate/unstable model (the
  `members + reactions != 2*nodes` count check) and for singular geometry
  (catches `np.linalg.LinAlgError` → "unstable model geometry"). So the
  "mechanism" item below is an *augmentation*, not a from-scratch build.
- **The MIDAS export idiom already exists.** `TrussBridge.midas_payloads()`
  returns `{table: assign}` bodies and `TrussBridge.to_midas(midas=None,
  **client_kwargs)` sends them table-by-table and returns a per-table
  `{"sent": n} | {"error": ...}` report. **This is the pattern the STM→MIDAS
  adapter must copy** — same method names, same report shape.
- **The CONS constraint-string format is already established:** `TrussBridge`
  writes `"1110000"` (pin) / `"0110000"` (roller) — the 7-char `DX DY DZ RX RY RZ
  RW`. The STM adapter reuses this exact encoding.
- **Unit conversion already has a home:** `midas.convert_node_units` uses
  `civilpy.general.units` (pint). Reuse that pint registry for the inch/mm/m → ft
  read conversion rather than hand-rolling factors.
- **`Truss` *is* `StrutAndTieModel`** (subclass, identical solver/plot). The
  node-snap/auto-label derivation in `rhino_stm` is genuinely unique to the Rhino
  importer — `truss_builder` generates nodes from panel geometry, so there's
  nothing to reuse there. No duplication to remove.

Remaining (revised against the above):

- [ ] **Honor `stm.id` on read/write** once the contract question is resolved —
  preserve a per-object GUID through `from_3dm` → `solve` → `results_to_3dm` so
  results land back on the authored object, not by nearest point.
- [x] **Read the `stm.member` hint** (`auto` default; `tie`/`strut` override).
  **Done.** `rhino_stm._member_type` reads it (absent/`auto` = classify by sign;
  an unknown value warns + falls back to `auto`), threaded onto
  `Element.member_type` in the hub and `StrutAndTieModel.member_types` in the 2D
  model. `StrutAndTieModel.classify(member)` honors a forced override for
  display, `solve()` warns when a forced `tie` solves in compression (or a
  `strut` in tension), and `model_to_3dm` writes `stm.member` only for a forced
  override (auto stays invisible). **Python now consumes the C# `STMMember`
  override tag.**
- [ ] **Load-case support** (`stm.case`): today `add_load` accumulates everything
  into a single implicit case (`self.loads[node] += ...`). Add per-case grouping
  and solve-per-case. Gate behind the contract decision.
- [x] **Augment validation with pre-solve diagnostics. → Done.**
  `StrutAndTieModel.diagnose()` returns actionable, node-named problems (dangling
  node, load with no load path, support on an undefined node, missing supports,
  under- vs over-constrained), and `solve()` now appends those named diagnostics
  to its determinacy `ValueError` so an imported Rhino model fails with a fixable
  message, not just the generic count mismatch. (The hub's `StructuralModel.
  check()` gives the same at the hub level.)
- [x] **Unit robustness. → Done.** `rhino_stm._unit_to_feet` reads
  `File3dm.Settings.ModelUnitSystem` and scales every coordinate to feet through
  the `civilpy.general.units` pint registry (mirroring `midas.convert_node_units`);
  feet-authored files are untouched, an unrecognized unit warns and assumes feet.
  Forces stay in kips. (inch/mm/m → ft round-trip tested.)
- [x] **Preserve full 6-DOF for the MIDAS path. → Done (S2).**
  `StrutAndTieModel.supports` is still lossy `(fix_x, fix_y)`, but
  `read_structural_model` now retains the full `stm.fix_*` as 6-DOF
  `Restraint`s on the hub, so the MIDAS adapter reads from the hub (not the 2D
  model) and `fix_z/rx/ry/rz` reach `CONS` intact.
- [x] **3D / out-of-plane guard. → Done.** `model_from_3dm` (the 2D path) calls
  `_warn_if_not_planar`: when the nodes span more than `tol` along the plane
  normal it warns that the 2D solver will project away that depth and points to
  `read_structural_model` / `as_model=True` for the full 3D model.
- [ ] **Proportional arrow scaling on write** (minor polish): scale the written
  load line over the ~1–80 kip band so `results_to_3dm` reads cleanly.
- [ ] **Tests to add:**
  - [x] inch/mm/meter file → feet conversion round-trips. **Done**
    (`TestUnitConversion`).
  - [ ] block-instance authored support/load (simulate the C# output) imports
    identically to the tagged-point/line form. *(Build the block instance via a
    fixture `.3dm` committed under `tests/data/`, since rhino3dm can't safely
    create blocks — author it once in Rhino, check it in.)*
  - [ ] `stm.id` preservation through the full round trip (once implemented).
  - [ ] pre-solve diagnostics name the offending node (extends the existing
    determinacy-error test coverage).
  - [ ] STM→MIDAS adapter emits the right `CONS` string from `stm.fix_*` (pure
    payload test, no live session — mirror the `midas_models` test style).
  - [ ] FHWA Example 2 (cantilever bent cap) reproduces published forces.
- [ ] **Example 2** end-to-end in the notebook (cantilever bent cap), mirroring
  Example 1.
- [ ] **Docstrings + a short `docs/` how-to** for the notebook surface.

### C# / .NET plugin side — TODO (separate Rider solution)

The plugin is the accessible authoring front end: toolbar buttons, no scripts.
Port the proven logic from `src/civilpy/structural/rhino_scripts/stm_authoring.py` (the schema + glyph
spec) to RhinoCommon. All commands `[CommandStyle(Style.ScriptRunner)]`.

> **Code organization (mandatory).** Keep UI separate from command logic. Eto
> view/dialog/panel classes live in a `Views/` folder; `Command` subclasses live
> in a `Commands/` folder and contain only orchestration (get input → call a
> service/model → report). **Do not build Eto layouts inline inside
> `RunCommand`** — a command shows a view and acts on its result; it does not
> define the view. Shared schema/glyph/tag logic goes in a third folder (e.g.
> `Core/` or `Stm/`) so both commands and views reuse it. This keeps the
> `stm.*`-stamping logic testable and prevents the dialog code from tangling with
> the document-edit code.

- [~] **Project scaffold:** RhinoCommon plugin targeting Rhino 8 (targets
  `net7.0;net48`), `.rhp` output, Yak build target wired in the `.csproj`, and the
  `Commands/` · `Views/` · `Core/` folder split above. **Done:** folder split,
  both target frameworks build clean (0 warnings), git repo initialized. **Still
  open:** Yak `manifest.yml` + `.rui` toolbar (deferred to the packaging step).
- [x] **`STMTemplate`** — ensure the STM layers and create the symbol block
  definitions (`STM_Pin/Roller_V/Roller_H/Fixed/Load`) on first use. This is the
  command that legitimately uses `InstanceDefinitions.Add` — **safe in C#**,
  which is precisely why block creation lives here and not in Python. **Shipped:**
  `Commands/STMTemplateCommand.cs` (EnglishName `STMTemplate`) →
  `Core/StmDocument.EnsureTemplate`. Layers, glyph geometry, support presets, and
  tag keys are ported 1:1 from `src/civilpy/structural/rhino_scripts/stm_authoring.py` into
  `Core/Stm.cs` + `Core/StmDocument.cs` (the C# mirror of the frozen contract).
- [x] **`STMSupport`** — pick point → choose Pin/Roller-V/Roller-H/Fixed (or
  Custom with a DOF checkbox panel) → insert the correct block → stamp
  `stm.kind=support`, `stm.support`, and the six `stm.fix_*` flags. **Shipped:**
  `Commands/STMSupportCommand.cs` → `Core/StmDocument.AddSupport` /
  `AddCustomSupport`. Type chosen via a command-line option list on the point
  pick; **Custom** is implemented now as 6 Free/Fixed command-line toggles (not
  yet the Eto checkbox panel — that lands with the Views/ panel work). Inserts on
  the `STM::Supports` layer; self-heals by calling `EnsureTemplate` first so it
  works even if `STMTemplate` was never run.
- [x] **`STMLoad`** — pick node → drag direction → enter kips → insert `STM_Load`
  block rotated local +X onto the force direction (the orientation logic the
  Python prototype flagged as "eyeball this"), add a `"<kips> kips"` text label,
  stamp `stm.kind=load`, `stm.kips`. **Shipped:** `Commands/STMLoadCommand.cs` →
  `Core/StmDocument.AddLoad`. Rubber-band direction drag (`DrawLineFromPoint`);
  self-heals via `EnsureTemplate`; guards zero-length direction (→ warn + abort)
  and warns on non-positive / out-of-band (~1–80 kip) magnitudes without blocking.
  `stm.kips` is written with `StmDocument.FormatKips` (invariant '.' decimal,
  trailing zeros trimmed) so the Python `float()` parse never trips on a locale
  comma. Label text dot sits at the unit-glyph arrow tip. Optional proportional
  scaling still deferred (minor polish).
- [~] **`STMMember`** — draw/select curves, tag `stm.kind=member`. Member type is
  `auto` by default: do **not** write an `stm.member` tag in the default case
  (auto is invisible). Offer `tie`/`strut` as an optional override (a non-default
  dropdown/option) that writes `stm.member=tie|strut` only when chosen.
  **In progress (C#):** `Commands/STMMemberCommand.cs` (uncommitted). The Python
  side already *consumes* this tag (see the Python TODO `stm.member` item), so
  the override values must stay `tie`/`strut` exactly.
- [x] **`STMRegion`** — select/draw a closed planar curve, tag `stm.kind=region`,
  and prompt for `stm.thickness` (ft) and `stm.fc` (ksi) (optionally `stm.E`,
  `stm.nu`, `stm.vol_frac`). Offer a `Void`/`Solid` option that tags an inner
  closed curve `stm.kind=void`/`solid`. Optionally stamp `stm.bearing` on a
  support/load when picked. This is the front end for the topology-optimization
  workflow (Python meshes the region and discovers the truss). **Shipped:**
  `Commands/STMRegionCommand.cs` → `Core/StmDocument.TagRegion` /
  `TagRegionZone`. Labels closed curves (validates `Curve.IsClosed`, skips + warns
  open/non-curve picks); `Role` option (Region/Void/Solid) + inline `Thickness`/
  `Fc`/`VolFrac` doubles (numbers via `FormatNumber`, invariant decimal); moves
  curves to a new cosmetic `STM::Regions` layer; stamps `stm.id`. Solver knobs
  (penalization, filter radius, mesh resolution) are intentionally **not**
  authored, per the contract. **`stm.bearing` now shipped** on supports/loads:
  `STMSupport`/`STMLoad` expose an optional `Bearing` (ft) command-line value,
  stamped only when &gt; 0 (absent = optimizer default). *Deferred:* `stm.E`/
  `stm.nu` author overrides (rarely overridden; Python defaults apply).
- [~] **`STMResults`** (read-back) — load a `results.3dm` (or re-color in place):
  recolor ties red / struts blue and show force labels, per the result-color
  contract. Lets the engineer review Python's output without leaving Rhino.
  **In progress (C#):** `Commands/STMResultsCommand.cs` (uncommitted).
- [ ] **Stable IDs:** if adopted, stamp `stm.id` (GUID) on every authored object
  and preserve it through edits. *(C# owns minting; Python only reads.)*
- [ ] **Input validation + user feedback (do not assume perfect input).** The
  mock-ups above show the happy path only; real commands must guard every pick
  and tag read, and tell the user what went wrong via `RhinoApp.WriteLine`
  (warning) rather than throwing or silently no-op'ing. Minimum:
  - Cancelled/empty selection (`GetResult` ≠ `Success`, null point) → return
    `Result.Cancel` quietly.
  - Wrong geometry type (e.g. `STMLoad` got a surface, `STMMember` got a point)
    → `RhinoApp.WriteLine("STMMember: select a curve; skipping <id>.")` and skip.
  - **Missing/!malformed tags on a selected object** (e.g. an object with no
    `stm.kind`, or `stm.kips` that won't parse) → warn and skip:
    `RhinoApp.WriteLine("Selected member lacks the stm.kind tag — run STMMember to tag it.")`.
  - Zero-length load direction (tail == tip) → warn, abort that load.
  - Out-of-band magnitude (≤ 0, or far outside the ~1–80 kip band) → warn but
    allow (don't block legitimate edge cases).
  Return `Result.Failure` only on an actual exception; use `Result.Nothing`/
  `Cancel` for user-driven aborts so the command history stays clean.
- [~] **Eto.Forms panel** (nice-to-have): a dockable panel (in `Views/`) listing
  supports/loads with editable magnitudes/DOF, instead of command-line prompts.
  **In progress (C#):** `Views/` folder + `Commands/STMPanelCommand.cs`
  (uncommitted).
  The panel only reads/writes the model via the shared `Core/` services — no
  document edits in the view code.
- [ ] **Yak packaging + install docs** so a non-programmer does
  `_PackageManager` → install → buttons appear.
- [ ] **Contract conformance test:** author one of each object via the plugin,
  save, and confirm `StrutAndTieModel.from_3dm` reads it identically to the
  hand-tagged fixture. This is the cross-language integration check — keep a
  shared sample `.3dm` both repos test against.

### Rhino → Midas — TODO (future, Python side)

The wanted deliverable is **Rhino → Midas**, not STM → Midas: read the tagged
`.3dm` into the canonical `StructuralModel` (§Package coherence), then serialize
that hub to Midas — *without* routing through the lossy 2D `StrutAndTieModel`
(which would drop `fix_z/rx/ry/rz`). The 6-DOF fixity and reserved load-case tags
exist specifically so the same authored `.3dm` can drive MIDAS Civil NX (true 3D,
moving loads).

**Build on what already exists — do *not* start a new module.** civilpy already
ships the Midas plumbing:

- `civilpy.structural.midas.MidasCivil` — the API client: `get_db`/`put_db`/
  `post_db`/`delete_db`, typed helpers (`nodes`, `put_nodes`, `elements`,
  `put_elements`, `supports`, `put_supports`, `static_loads`, `put_static_loads`,
  `set_units`), document ops (`open`/`analyze`/`save`), results (`result_table`,
  `beam_forces`), and model triage (`summarize`/`capability`). Error/retry
  classes included.
- `civilpy.structural.midas_models` — pure payload builders returning the
  `{id: {...}}` *assign* dicts the API expects (`curved_girder_model`,
  `bifurcated_girder_model`, `abutment_connection`, `soil_spring_supports`).

The conventions already match the STM contract, which is the whole point of the
6-DOF design:

- MIDAS `CONS` boundary conditions use a 7-char flag string `DX DY DZ RX RY RZ
  RW` (`'1'` = fixed). The STM `stm.fix_x/y/z/rx/ry/rz` flags map **directly**
  onto the first six characters (RW/warping = `0`): e.g. a pin
  (`fix_x,fix_y`) → `"110000 0"` → `"1100000"`.
- MIDAS default units are **KIPS / FT** (`set_units`), matching the STM contract.

**There is already a working precedent to copy:** `TrussBridge.midas_payloads()`
+ `TrussBridge.to_midas()` do exactly this for truss bridges — build the
`{table: assign}` bodies (NODE/ELEM/CONS/STLD/…) and push them with a per-table
report. The Rhino→Midas serializer should be the same shape, just driven by the
canonical hub instead of `TrussBridge`'s internal model.

So the work is a **hub → MIDAS serializer** modeled on `TrussBridge`, reusing the
existing client and builders — not a fresh bridge (this is stage **S4** above):

- [x] Add `midas_payloads(StructuralModel)` / `push_midas(model, midas=None,
  **client_kwargs)` mirroring `TrussBridge`'s signatures and per-table report
  shape: emit `NODE` / `ELEM` / `CONS` / `STLD` assign dicts (pure, testable with
  no live session), then push via `MidasCivil.put_db`. **Done (S4):** in
  `midas_models`, sharing the extracted `unit_block`/`steel_material_block`/
  `constraint_assign`/`placeholder_section_block` encoders with `TrussBridge`.
- [x] `Rhino → Midas` end-to-end = `from_3dm(as_model=True)` → `push_midas(...)`;
  no `StrutAndTieModel` in the path. **Done (S4)** — covered by
  `TestRhinoToMidas` in `test_rhino_stm.py`.
- [x] Map `stm.fix_*` (6-DOF) → the `CONS` constraint flag string; map
  `stm.kips` + load direction → an `STLD` static load case + `CNLD` nodal force.
  **Done (S4)** via `Restraint.to_constraint_string()`. `stm.case` → MIDAS load
  case names still pending the load-case tag adoption.
- [ ] Pull results back with the existing `result_table` / `beam_forces`, and
  optionally feed them to `results_to_3dm` for review in Rhino (closing the loop:
  Rhino → civilpy → MIDAS → civilpy → Rhino).
- [ ] Reuse `model_from_3dm` as the front parser — the `.3dm` stays the single
  source of truth; MIDAS is just another consumer of the parsed model.
- [ ] This is where the **3D** geometry (not just the XZ projection) and the full
  6-DOF data finally get consumed — validate the schema carried enough; extend
  the parser to real 3D if STM was projecting.
- [ ] Confirm auth/licensing via the existing `~/secrets.json` `MIDAS_API_KEY`
  path the client already uses (no new auth mechanism needed).

### Line girder → field splice — TODO (new pipeline, both sides)

**Goal.** Make the rolled-beam splice workflow — the process demonstrated in
the civilpy notebooks `Notebooks/Bolted Field Splice Design Process.ipynb` and
`Notebooks/MIDAS Bridge Model Walkthrough.ipynb` — drivable from Rhino end to
end: **draw the bridge's five girder lines, set a rolled shape on them, push
the model to MIDAS, run the moving-load analysis, pick the splice stations
from the moment envelope, design the bolted field splices, and display the
designed splice back in the Rhino model.**

**The process being automated** (from the splice notebook, in the order the
levers matter): (1) splice *count* is forced by shipping length —
`n_splices = ceil(L / L_ship) − 1`, `L_ship ≈ 100 ft`; every splice beyond
that is pure cost (~$20/bolt fab + ~10 field-min/bolt, ~124 bolts/splice);
(2) splice *placement* goes in a low-moment window near the dead-load
contraflexure point read off the moving-load envelope — a near-pier splice
switches on the 6.13.6.1.3c web moment-couple and roughly doubles the web
bolts; (3) section transitions are shop welds, not field splices; (4) only
then size plates and bolts (`size_flange_splice_plates`,
`size_web_splice_plate`, `design_splice` — all shipped in
`civilpy.structural.aashto.lrfd`).

**Synthetic demonstration:** the rolled-beam example uses public AISC
W24x131/W24x104 shapes with invented demands (DC1=20, DC2=5, DW=8,
LL+=280, LL-=-160 kip-ft), an 8 in deck, 96 in effective width, and
6 square inches of reinforcement. Flange plates are 1/2 in thick, with a 12.5 in
outer plate and two 5 in inner plates; web plates are 1/2 in thick.
These are demonstration selections, not an as-built detail or a transcription
of a private calculation package. See `Notebooks/nsba_splice_check.ipynb`.
The pipeline goal is to reproduce the same calculated checks and quantities
from a Rhino-authored synthetic model.

> **Division of labor (mandatory).** The C# plugin is a loose UI over
> civilpy — it captures input (draw, pick, tag) and displays output (read,
> recolor, panel). **civilpy is the engine and does ~90% of the work:** every
> number that matters (section properties, envelopes, splice stations, bolt
> counts, plate sizes, pass/fail) is computed in Python and travels through
> the `.3dm` file. If a G-stage tempts you to compute anything structural in
> C#, that computation belongs in a Python stage and a tag/write-back in the
> contract.

**Already in civilpy — reuse, do not rebuild** (the same rule as the Python
TODO above; verified against the civilpy source):

- **AISC shapes:** `civilpy.structural.steel.SteelSection(label)` looks up the
  bundled AISC shape database (labels normalized, pint units attached);
  `steel.W(label)` adds the W-shape fields the splice work needs —
  `depth`, `flange_width`, `flange_thickness`, `web_thickness`, `k_design`
  (fillet), `fastener_workable_gage`. Historic shapes via
  `HistoricSteelSection`/`WF`.
- **Materials & bolts:** `steel.SteelMaterial` (AISC Table 2-4) and
  `steel.BoltMaterial` (AISC J3.2 / ASTM); `get_bolt_weights` for quantities.
- **Splice design:** `civilpy.structural.aashto.lrfd` — `design_splice`,
  `SpliceInput`/`SpliceLoads`/`BoltSpec`/`PlatePair`/`WebPlate`,
  `size_flange_splice_plates`, `size_web_splice_plate`, `proportion_limits`.
- **MIDAS:** `structural.midas.MidasCivil` client + `parse_result_table`;
  `structural.midas_models` payload builders (`midas_payloads`/`push_midas`).
- **Envelopes:** `structural.influence_lines` (`influence_line_from_midas`,
  `maximize_axle_train`, `hl93_effect`) and the `beam_bending.Beam`
  line-girder envelope for quick studies.

The chain in dependency order (G-stages). C# items are built here; Python
items are coordination requests for the civilpy side — do not build them in
this repo:

- [~] **G1 (joint) — freeze the `gdr.*` contract** (see the open contract
  question above). **C# mirror shipped:** `Core/Gdr.cs` implements the
  proposal below (marked PROPOSED in its doc comment) plus the write-back
  keys `gdr.status` (`OK|NG`), `gdr.summary`, and `gdr.checks`
  (newline-separated `article|check|actual|allowable|verdict` records) that
  G8 writes and G9 reads, and a plan-view plane convention (X = stations,
  Y = transverse, Z up, lengths authored in feet and scaled to the model's
  unit system). **Still open:** reconciliation with the civilpy side — the
  keys are not frozen until the civilpy side signs off:
  - `gdr.kind=girder` on the girder-line curve; `gdr.shape=<AISC label>`
    (exact manual label, e.g. `W24X104`;
    `civilpy.structural.steel.W(label)` is the authority for section
    properties — C# stores only the label); `gdr.grade=<name>` (default
    `Grade 50`, resolved by `steel.SteelMaterial`).
  - `gdr.kind=support` on bearing points, `gdr.fixity=fixed|expansion`.
  - `gdr.kind=splice` on marker points (authored by Python's placement pass,
    editable by the engineer, consumed by the splice designer).
  - Bridge-level (document user text, not per object): deck thickness /
    effective width / f'c for the composite section, `gdr.ship_max` (ft,
    default 100), bolt standard (diameter, hole type, surface class — the
    ODOT BDM 308.2.2.1.j defaults above).
  - Units stay kips/ft per the STM contract; girders drawn as lines in plan
    or elevation — decide the plane convention here too.

  **Python sign-off (civilpy reference reader, 2026-07-04).** Reviewed
  `Core/Gdr.cs` @ 6426f92 against the civilpy source. **Accepted** — the key
  list, the plan convention (X = stations / Y = transverse / Z up, feet), the
  feet-geometry / inch-detailing / ksi-stress unit split, the write-back format
  (`gdr.status`/`gdr.summary`/`gdr.checks` = `article|check|actual|allowable|verdict`),
  and `NormalizeShapeLabel` (verified byte-identical to
  `SteelSection.clean_user_input`: strip spaces + uppercase) all match. `gdr.line`
  is already stamped on supports (`GdrDocument.cs`), which settles the
  girder↔support/splice association explicitly (no nearest-curve inference —
  the `stm.id` lesson). **Three items to settle before the freeze:**
  0. **Bridge params must NOT live in `RhinoDoc.Strings`.** `rhino3dm` 8.x
     (the Python reader) exposes only `Delete`/`DocumentUserTextCount` on
     `File3dm.Strings` — it **cannot read document user text**, so the
     document-level `gdr.deck_*`/`gdr.ship_max`/`gdr.bolt_*` keys are
     unreadable as authored. **Fix (matches the STM contract, which keeps
     everything in object user text): stamp the bridge params as object user
     text on a dedicated `gdr.kind=bridge` marker object** (a point off to the
     side). The G4 reader reads them from that marker; `GirderParams` (C#) must
     author them there instead of `RhinoDoc.Strings`. **Implemented + verified
     Python-side** (`rhino_gdr.read_girder_model`, `test_rhino_gdr`).
  1. **Grade names don't resolve in civilpy yet.** `Gdr.GradeChoices`
     (`Grade 36/50/50W`, `HPS 50W/70W`, default `Grade 50`) are UI-friendly, but
     `steel.SteelMaterial` ships ASTM-named instances (`A36`, `A572Gr50`,
     `A992`, …) with **no `Grade 50` and no weathering/HPS grades**. Resolution:
     **Python owns a grade-name → `SteelMaterial` map** in G4 (`Grade 50` →
     Fy 50/Fu 65, `Grade 50W` → A588, `HPS 70W` → …) and adds the missing
     `A588`/HPS instances — keep the friendly names in the C# picker, **no C#
     change needed**. Flagged so the two lists stay in lock-step if the picker
     list changes.
  2. **Reserve `gdr.deck_rebar` (in², document-level).** The NSBA composite path
     (B4/G7) drops the *top-flange* splice demand using the negative-moment deck
     steel (6 square inches in the synthetic example). That area is carried today by neither the
     `gdr.*` doc tags nor civilpy's `SpliceInput`. Add the doc-level tag now
     (C#: one `Doc*` key, default-absent) and a matching `deck_rebar_area` field
     on `SpliceInput` (Python, G7). Everything else B4 needs is already in the
     contract.

  With those two noted (neither blocks authoring — #1 is Python-internal, #2 is
  one reserved key), **the Python side signs off on the `gdr.*` contract; C# may
  treat the key list as frozen.**
- [x] **G2 (C#) — `GirderLines` authoring command:** draw the framing — girder
  count (default 5) + spacing + span lengths, or trace existing curves; place
  bearing points at abutment/pier stations; tag everything per G1. Same
  Commands/ → Core/ split as the STM commands; self-heals layers like
  `EnsureTemplate`. **Shipped:** `Commands/GirderLinesCommand.cs` →
  `Core/GdrDocument.CreateFraming`/`TagGirder`. Pre-selected curves are
  tagged as traced framing; otherwise span lengths are entered one at a time
  (Enter finishes) with `Girders`/`Spacing` options. Bearing points get an
  editable fixity default (single span: fixed at the first bearing;
  continuous: fixed at the interior pier nearest mid-length, expansion
  elsewhere) and the run stamps the document-level bridge defaults
  (`gdr.ship_max`=100 ft + the BDM 308.2.2.1.j bolt set) where absent —
  values only, no computation.
- [x] **G3 (C#) — `GirderShape` command:** assign the rolled shape to selected
  girder lines from a picker (W-shape list; an Eto dropdown in Views/), write
  `gdr.shape`/`gdr.grade`. Optional polish: extrude a true-scale section
  along the line on a display layer so the model reads as a bridge, not
  wireframe — **display-only**: any dimensions C# holds for this are cosmetic
  (like the STM glyph specs) and feed no calculation; the label is the only
  thing Python reads. **Shipped:** `Commands/GirderShapeCommand.cs` +
  `Views/GirderShapeDialog.cs` → `Core/GdrDocument.AssignShape`/
  `AddDisplaySection`. Editable autocomplete combo seeded from a ~50-shape
  display-only W catalog in `Core/Gdr.cs`; free-typed labels are normalized
  exactly like civilpy's `SteelSection.clean_user_input` (strip spaces,
  uppercase) and tagged even when not in the catalog (they just get no
  cosmetic extrusion — a command-line note says civilpy resolves any AISC
  label). Grade dropdown mirrors `steel.SteelMaterial` names.
- [x] **G4 (Python) — read `gdr.*` into the hub. Done** —
  `structural/rhino_gdr.read_girder_model` + `test_rhino_gdr` (8 tests): girder
  polylines → `Element` chains (`section`=AISC label, `material`=grade,
  `role=girder`, `midas_type=BEAM`, `metadata['gdr.line']`), bearings → 6-DOF
  `Restraint` (`fixed`=XYZ / `expansion`=YZ), a `gdr.grade`→(Fy,Fu) map, feet
  units, loud missing-deck warnings. Reads bridge params from a `gdr.kind=bridge`
  marker (see G1 item #0: rhino3dm can't read `RhinoDoc.Strings`). Added a
  generic `Element.metadata` dict to the hub (also serves `stm.id`/`gdr.id`). It:
  parse girder lines +
  bearings into `StructuralModel` (one element chain per girder line,
  `Element.section` resolved via `civilpy.structural.steel.W(label)` — the
  existing AISC database lookup, not a new table), mirroring
  `read_structural_model`.
- [~] **G5 (Python) — MIDAS push with real sections + HL-93. Pure section/
  material slice done; moving load + live analyze remain.** `midas_models.
  rolled_i_section_block` emits a real I/H `SECT` from `steel.W` (AISC
  dimensions, not `placeholder_section_block`), and `hub_section_material_blocks`
  assigns one `SECT` per distinct shape + one `MATL` per grade across the hub's
  elements with a per-element `(sect_id, matl_id)` map (`test_girder_midas`, 5
  tests). *Remaining (needs a live Civil NX / MAPI session — Dane runs it):*
  the composite deck section, the `MVCD`/`MVHL`/`MVLD` + lane tables, `analyze()`,
  and pulling per-girder envelopes; and confirming the exact `DBUSER` SECT JSON
  + section unit against the live API. Original scope:
  extend
  `midas_models.midas_payloads` to emit real rolled `SECT` blocks (today:
  `placeholder_section_block`) and author the moving-load tables the
  walkthrough notebook reads (`MVCD`/`MVHL`/`MVLD` + lanes); `analyze()`;
  pull the per-girder envelope via `beam_forces` / `parse_result_table` or
  influence lines (`influence_line_from_midas` + `maximize_axle_train` for
  permit/rating trucks). Fold in the walkthrough notebook's own TODO cell:
  controlling member *per member type* (stringer/floorbeam/…), bearing
  reactions reported clearly, and (if the API allows) highlighting the
  controlling member in the Civil NX view.
- [x] **G6 (Python) — splice placement pass. Done** —
  `structural/girder_pipeline.py` (`n_field_splices`, `place_splices`,
  `SpliceCandidate`) + `test_girder_pipeline` (11 tests). Pure: takes the
  per-case moment envelope, computes `ceil(L/ship_max)−1`, and finds each
  splice at the lowest-Strength-I station inside its shipping-feasible window
  (contraflexure wins), returning the unfactored `SpliceLoads` demand there.
  Original scope: compute the forced splice count
  from shipping length, scan the envelope for the low-moment windows, emit
  candidate stations + the unfactored demand set at each
  (DC1/DC2/DW/LL+I⁺/LL+I⁻ → `SpliceLoads`), and stamp `gdr.kind=splice`
  markers back into the `.3dm` for the engineer to accept or drag.
- [~] **G7 (Python) — splice design for rolled shapes. Front end + fixture
  done; composite `fcf` (B4) remains.** Added `girder_side_from_w(label, grade)`
  (builds `GirderSide` from the AISC db via `steel.W`), and a selectable
  `SpliceInput.method="stress_based"` applies design stress `Fcf`, net-area hole
  allowances, and per-plate bolt checks. Synthetic regression cases cover
  both hand-entered section dimensions and catalog-label inputs
  (`TestSyntheticRolledSplice`, `TestGirderSideFromW`). The public NSBA
  plate-girder examples remain separate validation cases. Composite stresses
  can be computed through `design_rolled_splice`.
- [~] **G8 (Python) — write the designed splice back to the `.3dm`. Tags +
  round-trip done; detail geometry remains.** `rhino_gdr.splice_writeback_tags`
  builds `gdr.status`/`gdr.summary`/`gdr.checks`
  (`article|check|actual|allowable|verdict`) from a `SpliceDesign`;
  `write_splice_results` stamps `gdr.kind=splice` markers into a `.3dm` and
  `read_splice_results` round-trips them (`test_rhino_gdr`
  `TestSpliceWriteBack`). The C# `GirderSplice` renders the table (NG rows red).
  *Remaining:* the 3D plate/bolt/filler **detail geometry** and the
  moment-envelope overlay curve. Original scope: at each
  splice station, generate the 3D detail (flange/web plates, bolt circles,
  fillers) plus a check-summary tag, in the spirit of `results_to_3dm` —
  the file stays the single source of truth for what C# displays.
- [~] **G9 (C#) — `GirderSplice` review command + panel:** read the write-back
  file, show the 3D splice detail at each station, overlay the moment
  envelope on the elevation, and present the check summary (mirror the
  workbook's Design Summary sheet — actual vs. allowable per article) in an
  Eto panel; flag any NG check loudly. **C# side shipped:**
  `Commands/GirderSpliceCommand.cs` + `Views/GirderSpliceDialog.cs` →
  `Core/GdrDocument.ImportSpliceModel`/`ListSplices`. Imports the write-back
  `.3dm` (all geometry + tags + colors onto `Girders::Splices`, refreshed per
  run), prints a loud `*** NG ***` command-line verdict per failing splice,
  and shows a two-grid dialog (splices over per-splice limit-state checks,
  NG rows red) with select + zoom-to-station. **Still open:** exercising it
  against a real G8 file — blocked until the Python write-back exists (the
  moment-envelope overlay geometry also arrives from G8; C# just imports it).
- [ ] **End-to-end conformance:** author a synthetic bridge with G2/G3,
  run G4-G8, and compare splice stations, details, and checks with the same
  inputs run directly in Python.

**Benchmark + optimization goals (added 2026-07-03 — the point of the
pipeline is a *better* design, not just a reproduced one):**

- [ ] **B1 - independent analysis benchmark:** create a synthetic bridge
  with documented geometry, materials, construction stages, and loads.
  Run identical inputs through civilpy and an independent solver; compare
  moments, shears, deflections, and section properties. Record the inputs
  and explain discrepancies without distributing private deliverables.
- [ ] **B2 — deflection truth:** prior research found LEAP Steel
  overestimates deflections ~10%; MDX is believed closer. Use B1 to
  calibrate confidence in the MIDAS deflections (and the L/800-type service
  checks) before letting the optimizer trade steel against them.
- [ ] **B3 — MIDAS model completeness (extends G5):** the comparison is only
  fair if the MIDAS model is real: steel materials loaded per grade
  (`MATL`), rolled sections (`SECT`), bearing fixity from `gdr.fixity`
  (`CONS`), stiffener locations found/recorded, an ODOT-standard deck (BDM
  slab thickness / haunch / effective width) as the composite section, and
  the HL-93 moving-load setup (`MVCD`/`MVHL`/`MVLD` + lanes from the deck
  width). Non-composite (DC1) vs. composite (DC2/DW/LL) stages must match
  how MDX applies them.
- [~] **B4 — NSBA composite splice method (extends G7). Section engine done;
  auto-`fcf` wiring remains.** `aashto.lrfd.composite.CompositeGirder`
  computes the transformed non-composite / `n` / `3n` / cracked-`negative`
  section properties and per-case flange stress. `test_composite_section`
  checks a synthetic rectangular girder against independent hand-calculated
  area, centroid, inertia, and service stresses, including the cracked section.
  `design_rolled_splice` supplies computed stresses to the splice designer.
- [~] **B5 — optimization loop (the deliverable). Splice-region optimizer +
  cost model done; full limit-state set is the extension.**
  `girder_optimizer.optimize_splice_shape` sweeps candidate rolled shapes,
  gates each on the girder plastic moment (`φ·Fy·Zx ≥ Mu`), auto-sizes the
  flange/web splice plates (NSBA sizers) and searches web thickness / columns /
  plate thickness for the fewest-bolt splice that passes **every** splice check,
  then ranks feasible shapes by steel weight + splice cost (~$20/bolt fab + ~10
  field-min/bolt). The synthetic-load demonstration compares candidates against
  a heavier W24x131 baseline
  (`test_girder_optimizer`, 8 tests). Also `continuous_beam.ContinuousBeam` +
  `girder_pipeline.girder_line_envelope` give the **offline** DC + HL-93 moment
  envelope (no live MIDAS), wired end-to-end
  (`ContinuousBeam → place_splices → design_rolled_splice`). *Remaining:* fold
  Service II / fatigue / 6.10.2-proportion / deflection into the girder gate,
  let the section step between pieces, and sweep splice **stations** (not just
  shapes); trust it against real MIDAS/MDX numbers once B1 lands.
  Original scope: sweep rolled shapes
  (weights from `steel.W`) and splice stations subject to every limit state
  passing (strength, Service II, fatigue, 6.10.2 proportions, deflection)
  and constructability (shipping length, filler-plate limits), minimize
  total steel weight + splice cost (~$20/bolt fab, ~10 field-min/bolt), and
  report cost differences against a documented synthetic baseline.

### Quick status board

| Area | Python (civilpy) | C# plugin (Rider) |
|---|---|---|
| File read/write bridge | ✅ shipped | n/a |
| Topology optimization (region → truss) | building (`stm_topology`) | `STMRegion` ✅ (region/void/solid labeler) |
| Solve + results write-back | ✅ shipped | reads results (`STMResults`) ☐ |
| Authoring commands | prototype in `src/civilpy/structural/rhino_scripts/` ✅ | `STMTemplate`+`STMSupport`+`STMLoad` ✅; `STMMember`/`STMResults`/panel in progress (C#) |
| Symbol block creation | intentionally **not** here (rhino3dm bug) | ✅ `STMTemplate` owns this (`Core/StmDocument`) |
| Stable object IDs | read/preserve ☐ | mint/stamp ☐ |
| Load cases | ☐ | ☐ |
| Validation/diagnostics | solve-time checks ✅; pre-solve diagnostics ☐ | ☐ |
| Canonical `StructuralModel` hub | S1–S4 shipped ✅ (`structural_model.py`, `rhino_stm.read_structural_model`, `StrutAndTieModel.{from,to}_structural_model`, `midas_models.midas_payloads`/`push_midas`); S5–S9 ☐ | n/a |
| IFC 4.3 alignment + `Pset_CivilPy_*` | schema mapping documented ✅; adapter/extension ☐ | n/a |
| Rhino → STM | ✅ shipped (via `model_from_3dm`) | n/a |
| Rhino → Midas | ✅ shipped (`read_structural_model` → `midas_models.push_midas`); shares one encoder with `TrussBridge` | n/a |
| Packaging | pip extra ✅ | Yak ☐ |
| Girder-line authoring (`gdr.*` contract) | **signed off** ✅ (G1); grade-name map ✅; **reader ✅ (G4, `rhino_gdr`)**; open: reserve `gdr.deck_rebar`, move bridge params to a `gdr.kind=bridge` marker | `Core/Gdr.cs` ✅ (G1); `GirderLines`+`GirderShape` ✅ (G2–G3); **TODO: `GirderParams` → object user text, not `RhinoDoc.Strings`** |
| MIDAS moving-load run + envelope | splice designer ✅ (`design_splice`); sections/MVLD/envelope ☐ (G5) | n/a |
| Splice placement + rolled-shape design | ☐ (G6–G7; fixture = synthetic design) | n/a |
| Splice write-back + review | write-back ☐ (G8) | `GirderSplice` importer + check dialog ✅, live test vs. G8 ☐ (G9) |
| MDX benchmark + steel optimization | ☐ (B1–B5; beat the as-built design) | n/a (displays results) |

## Rhino layer taxonomy: NBIS inspection groups (2026-07-06)

**Deck / Superstructure / Substructure are authoritative and pinned to the
C# side.** `ODOT Rhino Plugin/Core/Gdr.cs` (`RhinoODOTExtension` repo,
commit `34f7051`, "GirderDeck command + Deck/Superstructure/Substructure
layer groups") defines the nested layer paths every import command
(`GirderDeck`, `DeckBarrier`/`DeckLaneLines`, `BoxBeamLines`) re-parents
objects into by `gdr.kind`, purely NBIS/SNBI's three inspection groups:

```
Deck            Deck::Bridge Deck, Deck::Traffic Barriers, Deck::Rebar, Deck::Lane Markings
Superstructure  Superstructure::Girders, ::Splices, ::Bearings, ::Display, ::Box Beams,
                ::Tendons, ::Diaphragms, ::Tie Rods
Substructure    (reserved -- no elements generated yet)
```

**Finding:** civilpy's own `.3dm` writers (`rhino_gdr`, `rhino_deck`,
`rhino_barrier`, `rhino_box_beam`) were baking into **flat leaf names**
("Girders", "Bridge Deck", "Beams", ...) instead of these nested paths.
This does **not** break the round trip -- every C# import command routes
strictly by `gdr.kind`, never by the source file's layer -- but it meant a
directly-opened civilpy write-back file didn't yet read the way an
assembled model does, `rhino_box_beam`'s "Beams" didn't even match
`Gdr.LayerBoxBeams` ("Box Beams"), and there was no shared source of truth
a future common-data-model exporter could read off the layer tree instead
of re-deriving it from tags. **Fixed:** `civilpy.structural.rhino_layers`
transcribes the ``Gdr.cs`` paths as constants plus an `ensure_layer(f,
full_path, color)` helper (the Python-side mirror of
`StmDocument.EnsureLayer`'s "walk the `::`-separated path, create what's
missing" logic, since standalone `rhino3dm` has no `FindByFullPath`); all
four writers now call it. Verified by writing a box-beam model and reading
its layer tree back (`test_rhino_layers.py`).

**PROPOSED — Culvert and Site (pending C#-side reconciliation).** Two more
groups for the ODOT SCD standard-drawing components, which are neither
deck, superstructure, nor substructure and were previously flat under an
ad hoc `SCD::<name>` layer:

```
Culvert   headwalls / box culverts: Culvert::HW-1.1, Culvert::HW-2.1 (HW-2.2 shares it), Culvert::BCHW
Site      off-structure roadway items: Site::AS-1-15, Site::AS-2-15, Site::DS-1-92, Site::PCB-91
```

This assignment is an assumption (see `docs/SCD_BUILD_QUESTIONS.md`): drip
strips (DS-1-92) physically mount on the deck fascia and could arguably be
`Deck::` instead, but every SCD component is untagged/display-only (none
carry `gdr.kind`, so none of the C# import commands touch them), which
puts them all in the same "standard-drawing reference, not analysis-model
participant" bucket — hence one shared split by Culvert vs. everything
else at grade, not by physical adjacency to the deck. Revisit if the SCD
components ever get `gdr.kind` tags of their own.

**Why this matters for the common data model.** NBIS/SNBI's inspection
groups are also IFC 4.3's `IfcBridgePart.PredefinedType` enumeration
(`ABUTMENT`, `DECK`, `PIER`, `SUBSTRUCTURE`, `SUPERSTRUCTURE`,
`SURFACESTRUCTURE`, ...) — see
[IFC 4.3 as the hub vocabulary](#ifc-43-as-the-hub-vocabulary-and-where-it-must-be-extended)
above. Keeping the Rhino layer tree, the `civilpy.state.ohio.snbi`
condition-rating groups, and (eventually) `to_ifc`'s `IfcBridgePart` split
on the *same* five-way taxonomy means one mapping serves Rhino, IFC,
and — when those adapters exist — BrR's NBI element groups and AssetWise's
inspection hierarchy, instead of three drifting, independently-invented
ones. Midas has no equivalent spatial-structure concept (it is
elements/sections/loads only), so the Midas adapter stays keyed off
`gdr.shape`/`gdr.grade` as today; the taxonomy question only applies to
adapters that carry a spatial/inspection hierarchy.
