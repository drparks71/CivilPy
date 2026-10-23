# civilpy — Full Scope & Architecture Handoff

**Audience:** this document is written to be handed, on its own, to a
person or AI assistant with no other context (no repo access, no prior
conversation) so they can understand what civilpy is, how it is organized,
what engineering authority stands behind each part, and how the pieces
connect into a production workflow. Last updated 2026-07-06.

## 1. What civilpy is

civilpy (`https://github.com/civilpy/civilpy`, MIT-licensed, maintained by
Dane Parks) is a Python engineering library that has grown into an
**all-encompassing Ohio DOT (ODOT) bridge-production tool**. It combines:

1. **Spec-faithful calculation engines** — AASHTO LRFD checks implemented
   article-by-article as pure functions, AREMA and timber/masonry checks,
   geotechnical and hydraulic analysis.
2. **Transcribed ODOT standards** — the Bridge Design Manual (BDM)
   formulas/policies and the Standard Construction Drawing (SCD) catalogs
   encoded as queryable Python data with their sources cited.
3. **A CAD front end** — a parametric bridge generator whose geometry is
   authored in Rhino 8 / Grasshopper, tagged so Python can read the model
   back and drive downstream analysis (MIDAS Civil).
4. **ODOT enterprise integrations** — TIMS, AssetWise, inspection photo
   tooling, plan-set utilities.

The guiding division of labor: **geometry programs and UI stay thin;
every engineering number comes from a civilpy module that cites its
source** (LRFD article, BDM section, SCD designation).

## 2. Repository layout (src/civilpy)

### 2.1 `structural` — the core

**AASHTO LRFD checks** (`structural/aashto/lrfd/`): each file implements
one spec area as pure functions of primitive inputs (kip, inch, ksi),
registered by article number in an `ARTICLES` dict via the `@article`
decorator and returning a shared `CheckResult` (capacity, demand, phi,
hand-calc intermediate details). Modules: `steel` (flexure, shear, bolts,
welds, fatigue, stiffeners, shear connectors), `concrete` (RC flexure,
minimum reinforcement, crack control, MCFT shear, development, culvert
slab shear), `columns` (P-M interaction, slenderness), `prestressed`
(stresses, losses — approximate and refined), `creep_shrinkage`,
`composite` (composite girder sections), `splices` + `bolted_field_splice`
(complete AASHTO/NSBA bolted field splice design), `distribution` (live
load distribution factors, strips, multiple presence, IM), `deck` (LRFD
9.7.3 equivalent-strip deck design: Table 4.6.2.1.3-1 strip widths, the
full Appendix A4 Table A4-1 live-load moment table, and a flexure/crack
check chain), `railing` (Table A13.2 test-level loads, yield-line parapet
capacity, overhang collision), `stm` (strut-and-tie resistance), `timber`,
`lrfr` (load rating factors), `appendix_a6`/`appendix_b6`, `editions`
(edition-aware behavior). `structural/aashto/` also carries `vehicles`
(HL-93 truck/tandem/lane, permit vehicles), `bearings`, `load_definitions`.

**Analysis engines**: `continuous_beam` (matrix stiffness continuous-beam
solver), `influence_lines` (influence-line generation + `hl93_effect`
governing HL-93 envelopes per LRFD 3.6.1.3), `moment_distribution`,
`beam_bending`, `section_properties`, `truss`/`truss_builder`,
`strut_and_tie` + `stm_topology/` (SIMP topology optimization → STM
extraction → design → cost).

**Steel & materials**: `steel` — the AISC shape database (`W(label)` is
the single authority for section properties; historic shapes, e.g. the
depth-first `14WF34` naming, are also resolvable), `Rebar` (ASTM A615
table), `SteelMaterial` grades.

**ODOT standards** (`structural/odot/`): transcriptions of standard
drawings, each citing its SCD and revision — `bridge_railing` (BR/SBR/
TST/DBR/TBR/PCB catalog with MASH/NCHRP test levels), `guardrail` (MGS
system + bridge terminal assemblies), `box_beam` + `box_beam_design`
(PSBD-1-25 details; PSBDD-1-25 strand patterns and LRFR ratings),
`rocker_bolster` (RB-1-55), `headwall` (HW series), and `deck_design` —
the ODOT BDM 309.3 deck module: the 309.3.1 minimum-thickness formula,
the mandatory design policy (LRFD 9.7.3 strip method only, HL-93,
0.06 ksf FWS, covers, γe=0.75, QC2 concrete), the complete Figure 309-3
standard deck design table (spans 7.0–14.0 ft: thicknesses + all four
rebar mats + overhang bars), and BDM 309.3.5 haunch requirements
(2 in minimum, vertical sides at flange edges).

**The bridge generator** (`structural/bridge_layout.py`): a pure-Python
(no Rhino imports, fully unit-tested) parametric layout engine.
`BridgeInput` (spans, girder count/spacing/AISC label, overhang, railing
SCD, skew, haunch, optional deck override) → `layout_bridge()` →
girder lines, bearing points with default fixity, haunch runs, the skewed
deck slab with BDM thickness and mats, barrier runs from the SCD catalog,
and `deck_rebar_segments()` which instantiates every deck bar as clipped
3D segments (BDM 309.3.4 stacking and skew rules applied). Output
primitives carry the `gdr.*` tag payloads (section 3).

**Rhino interop**: `rhino_stm` (frozen `stm.*` contract reader),
`rhino_gdr` (the `gdr.*` girder-pipeline reader: resolves tagged curves/
points into a `StructuralModel`), `girder_pipeline` (line-girder analysis:
HL-93 envelopes per girder), `girder_optimizer`, `structural_model` (the
canonical analysis-model hub), `frame_analysis` (direct-stiffness 3-D
frame/truss solver on the hub: releases, rigid links, camber strains;
validated against TSC's 2009 STAAD decks), `midas` / `midas_models` (MIDAS Civil
model generation — the refined-analysis backend).

**Other codes**: `arema/` (railroad: masonry, steel, TPG design),
`wood`, `concrete`, `abutment`, `pier`, `effective_length`, `cande`
(buried-structure adapter).

### 2.2 Supporting packages

- `geotech/` — borings, SPT, soil profiles, shallow/deep foundations,
  lateral piles (incl. LPILE adapters), axial load transfer, Culmann's
  method, CANDE adapter.
- `water_resources/` — open channel, pipe flow, hydraulics, scour.
- `transportation/` — horizontal/vertical curves, roadway, FHWA NBI/SNBI.
- `state/ohio/` — ODOT enterprise: TIMS, AssetWise client, OSE tools,
  inspection photo downloader, plan splitter, title sheets, SNBI, legacy
  DB tables. (`state/ohio/DOT/gemini.py` is an existing LLM integration
  point.)
- `general/`, `construction/`, `environmental/`, `CLI.py` — utilities.

### 2.3 Tests

`tests/` mirrors the package (~1,200 tests passing as of 2026-07-06).
House rules: every transcribed table gets integrity tests (e.g. the BDM
Figure 309-3 thickness column is re-derived from the 309.3.1 formula;
Table A4-1 spot values are cross-checked against independently published
design aids), and every engine gets hand-verifiable numeric tests.

## 3. The Rhino / Grasshopper / MIDAS production pipeline

Two repos cooperate **without ever calling each other** — they share only
tagged `.3dm` files:

- **RhinoODOTExtension** (C#, RhinoCommon plugin `ODOT STM Tools`):
  input capture and display only. Commands: `STM*` (strut-and-tie
  authoring, frozen `stm.*` tag schema) and the girder pipeline
  (`GirderLines`, `GirderShape`, `GirderSplice`) writing the `gdr.*`
  schema.
- **civilpy** (this repo): reads the tags, builds the analysis model,
  runs envelopes/design (or exports to MIDAS Civil for refined analysis),
  and writes results back onto tagged objects (e.g. splice markers with
  `gdr.status` / `gdr.checks` that the C# `GirderSplice` dialog displays).

**The `gdr.*` contract** (mirror constants: C# `Gdr.cs` ↔ Python
`rhino_gdr.py`): object tags `gdr.kind` (girder|support|splice),
`gdr.line`, `gdr.shape` (AISC label; civilpy resolves), `gdr.grade`,
`gdr.fixity` (fixed|expansion), `gdr.id` (C# mints, Python preserves);
write-back tags `gdr.status`/`gdr.summary`/`gdr.checks`; document-level
keys `gdr.deck_t` (STRUCTURAL thickness, in), `gdr.deck_weff`,
`gdr.deck_fc`, `gdr.ship_max`, `gdr.bolt_*` (ODOT BDM defaults). Display
geometry deliberately carries **no** `gdr.kind` so readers ignore it.
The authoritative contract/roadmap lives in `docs/Rhino Design
Philosophy.md`, kept as reconciled copies in both repos.

**Grasshopper generators** (`Notebooks/res/`, GHPython CPython-3 sources
for Rhino 8): `odot_bridge_generator_ghpython.py` — sliders → 
`layout_bridge()` → full 3D bridge (true-fillet girders, haunches, skewed
deck, barriers, every deck bar) with a `bake` mode that writes the tagged,
`rhino_gdr`-readable document; `concrete_slab_ghpython.py` — generic slab
mats. **Naming convention going forward: one GH script per ODOT SCD,
named exactly after it** (e.g. `AS-1-15.py`).

## 4. The ODOT SCD component program (active roadmap)

Goal: a drop-in parametric Grasshopper component for every ODOT Standard
Construction Drawing with real geometry, so a full bridge site (structure,
approach slabs, barriers, guardrail runs, drainage, culverts) can be
generated, tagged, extracted, and analyzed from one environment.

- Feasibility review (all 41 structural SCDs + the structurally relevant
  roadway, hydraulic, and plan-insert sheets, each rated 1–10 with
  rationale): `docs/ODOT_SCD_Feasibility.md`.
- Source PDFs archived at `res/odot_scds/{.,roadway,hydraulic,plan_inserts}`
  (git-ignored ~270 MB; re-download from dot.state.oh.us indexes).
- Implementation waves (tracked in the working task list):
  1. Approach slabs + simple details (AS-1-15, AS-2-15, DS-1-92, PCB-91)
  2. Headwalls + precast box culverts (HW-1.1/2.1/2.2, BCHW + ASTM C1577)
  3. Bridge railings (BR/SBR/TST/DBR/TBR — replaces generator placeholders)
  4. Slab bridges + substructure (SB-1-24, CS-1-24, CPA-1-08, CPP-1-08, A-1-20)
  5. Bearings + expansion joints (FB-1-82, RB-1-55, BD-1-11, EXJ series)
  6. Prestressed + integral details (PSBD-1-25, PSID-1-13, ICD/SICD)
  7. Fencing/misc where geometry exists (VPF, TVPF, GSD, NBS, WU)
  8. Roadway barriers + curbs (RM-4.x family, BP-5.1, RM-2.1, RM-5.2)
  9. MGS guardrail systems (MGS-2/3/4/6.1, F-3.1)
  10. Drainage structures (CB, I — incl. barrier-integrated inlets, MH)

Pattern for every component: a **catalog/layout module** in
`civilpy.structural.odot` (transcribed drawing data + pure-Python
geometry math + tests, companion Design Data sheets encoded alongside) and
a **thin GH script** that only draws and tags.

## 5. Conventions an implementer must follow

- **Units:** LRFD checks in kip/inch/ksi; plan layouts in feet with
  section dimensions in inches (`_in` suffixes); Grasshopper scripts
  scale via `RhinoMath.UnitScale` — never hardcode a unit system.
- **Provenance:** module docstrings cite the exact source (spec article,
  BDM section + page, SCD designation + revision date) and state that the
  source document remains controlling.
- **Data over code:** standard-drawing content is data (dataclasses/CSV in
  `odot/res/`), looked up through small guarded functions that raise
  `ValueError` with the governing limit when inputs leave the drawing's
  assumptions.
- **Python owns engineering, C#/GH own capture and display.** Cosmetic
  geometry must never become an analysis input.
- **ODOT policy guards:** e.g. deck design must use the LRFD 9.7.3
  approximate elastic method — the empirical method (9.7.2) and refined
  deck analysis are deliberately not implemented; any shape label is
  taggable but the UI confirm-prompts suspected typos (civilpy databases,
  modern + historic, are the existence authority).

## 6. Current status snapshot (2026-07-06)

Done: LRFD check library (steel, concrete, PS, splices, deck, columns,
LRFR…), HL-93 envelope machinery, bolted-field-splice design, BDM deck +
haunch modules, parametric girder-bridge generator + GH script with
MIDAS-ready tagging, six SCD catalogs, SCD feasibility review, ~1,200
tests green. In progress: SCD component waves 1–10 (none started),
C#-side `gdr.deck_*` authoring command (needs contract reconciliation),
crown/cross-slope + overhang thickening + drainage details in the
generator, independent-solver benchmark of the synthetic splice pipeline
with documented inputs and reproducible comparisons.
