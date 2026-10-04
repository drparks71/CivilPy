# ODOT Structural SCDs — Grasshopper Component Feasibility Review

Reviewed 2026-07-05 from the ODOT Office of Structural Engineering SCD
index (https://www.dot.state.oh.us/SCDs/Pages/structural.aspx). All 41
current drawings are archived in `res/odot_scds/` (git-ignored; ~190 MB —
re-run the index download if missing). Ratings were assigned after
profiling every PDF (page count, text density, table content) and
rendering the ambiguous ones.

**Rating scale:** 1 = very feasible as a parametric Grasshopper component
(dimensioned, table-driven geometry) … 10 = not feasible (guidance text,
pay items, site-specific work with no parametric geometry).

**Conventions for implementation:** each component ships as a GHPython
source named exactly after its SCD (e.g. `Notebooks/res/AS-1-15.py`),
backed by a pure-Python catalog/layout module in `civilpy.structural.odot`
(the `deck_design` / `bridge_layout` pattern: engineering data + geometry
math testable outside Rhino, thin Rhino emission in the script, `gdr.*`
tagging where the MIDAS pipeline consumes the result). Several SCDs have
companion **Design Data (DD) sheets** published separately (PSBDD-1-25 is
already encoded as `odot.box_beam_design`; HWDD-1, PCBDD, SICDD-2-14,
NBSDD-1-09, TVPFDD-1-18, DBP-1-92 are in `~/Downloads`) — where a DD sheet
exists, the catalog module should encode it alongside the drawing.

## Wave 1 — approach slabs & simple details

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| AS-1-15 | Reinforced Concrete Approach Slab | 2023-01 | **1** | ✅ DONE — `odot.approach_slab` + `Notebooks/res/AS-1-15.py`, 21 tests. Replaces the lost AS-1-15.3dm. |
| DS-1-92 | Drip Strip (over-the-side drainage) | 2022-07 | **1** | ✅ DONE — `odot.drip_strip` + `Notebooks/res/DS-1-92.py`, 10 tests. Plugs the "drainage" gap in the bridge generator. |
| PCB-91 | Portable Concrete Barrier | 2020-07 | **1** | ✅ DONE — `odot.portable_barrier` + `Notebooks/res/PCB-91.py`, 9 tests; TL data stays in `bridge_railing`. |
| AS-2-15 | Approach Slab Installation | 2023-07 | **4** | ✅ DONE — `odot.sleeper_slab` + `Notebooks/res/AS-2-15.py`, 9 tests. Drawable subset = the Type A/C reinforced concrete sleeper slab; the 14 installation configs are cataloged as data (`INSTALLATION_INDEX`), Type B (joint mesh) raises. |

## Wave 2 — headwalls

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| HW-2.1 | Half-Height Headwalls, CMP/plastic | 2022-07 | **1** | ✅ DONE — `odot.headwall.layout_headwall` + `Notebooks/res/HW-2.1.py`, 10 tests. Rectangular circular-pipe headwall (end treatment "A", D 12–48 in); battered back, pipe opening. Treatment "B" / pipe-arch / elliptical guarded out (cover < 6 in raises). |
| HW-2.2 | Half-Height Headwalls, concrete pipe | 2018-07 | **1** | ✅ DONE (circular) — same solid as HW-2.1 via `layout_headwall(..., concrete=True)` and the HW-2.1 GH component's `concrete` toggle (HW-2.2 concrete-pipe table, D 12–60 in). Elliptical table (`HEADWALLS_CONCRETE_ELLIPTICAL`) cataloged but not drawn. |
| HW-1.1 | Full Height Headwalls | 2025-07 | **2** | ✅ DONE — `odot.full_height_headwall` + `Notebooks/res/HW-1.1.py`, 11 tests. Center face + Type A/B wingwall planes; skew snapped to the tabulated 0/15/30/45 deg buckets (10 deg Type A/B cutoff pinned exactly); wall batter/footing/rebar cataloged, not drawn. |

## Wave 3 — bridge railings (replaces the generator's placeholder boxes)

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| SBR-1-20 | Single Slope Railing 42" | 2024-07 | **1** | ✅ DONE — cataloged in `bridge_railing` (already had profile data); drawn by the generic `rhino_barrier.build_barriers()` pipeline (`shape_family` -> "single slope"), not a per-SCD GH script. |
| SBR-3-20 | Single Slope Railing 36" | 2024-07 | **1** | ✅ DONE — same family/pipeline as SBR-1-20. |
| BR-1-13 | New Jersey Shape Railing | 2014-01 | **1** | ✅ DONE — cataloged + drawn via `build_barriers()` (`shape_family` -> "new jersey"); the default barrier in every earlier deck/barrier test. |
| SBR-2-20 | 57" Single Slope Median | 2024-07 | **2** | ✅ DONE (single Type B1) — cataloged + drawn via `build_barriers()`; the back-to-back variant is two SBR-2 instances placed independently (not a single symmetric F-shape call), see `SCD_BUILD_QUESTIONS.md`. |
| BR-2-15 | Sidewalk Railing w/ Concrete Barrier | 2024-07 | **2** | ✅ DONE — fixed a real bug found while wiring up Wave 3: `shape_family()` matched "combination (barrier + steel tube)" as plain "steel tube" (substring match on "tube"), drawing only a 10 in curb instead of the true 42 in x 12 in rectangular crashworthy barrier (SECTION A-A/B-B/C-C). Added a `"combination"` family: full-height reinforced barrier + steel tube rail `rail_height_above_in` (2'-0") above it. |
| TST-1-99 | Twin Steel Tube Railing | 2021-01 | **2** | ✅ DONE — cataloged + drawn via `build_barriers()` (`shape_family` -> "steel tube": curb + posts + rails). |
| TST-2-21 | Three Steel Tube Railing | 2025-01 | **3** | ✅ DONE — same "steel tube" pipeline as TST-1-99; mounting-configuration variants (15 sheets) are catalog notes, not separately drawn. |
| DBR-2-73 | Deep Beam Bridge Guardrail | 2002-07 | **3** | ✅ DONE (approximate) — "steel tube" family draws a generic curb + post + rail; the true corrugated deep-beam rail shape is not modeled (HSS-tube approximation, same simplification as TST-1/2). Links to `odot.guardrail` for the MGS transition. |
| DBR-3-11 | Deep Beam Retrofit Railing | 2011-07 | **3** | ✅ DONE (approximate) — same "steel tube" pipeline/simplification as DBR-2-73. |
| TBR-1-11 | Thrie Beam Retrofit Railing | 2013-01 | **3** | ✅ DONE (approximate) — same "steel tube" pipeline/simplification; the true thrie-beam corrugation is not modeled. |

## Wave 4 — slab bridges & substructure

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| SB-1-24 | Single Span Slab Bridges | 2026-01 | **1** | ✅ DONE — `odot.slab_bridge` + `Notebooks/res/SB-1-24.py`, 14 tests. Full SLAB DATA + EDGE BEAM SLAB DATA tables (spans 11-38 ft); skewed parallelogram plan (0-25 deg) + A/B/M/N longitudinal bar mats. Edge-beam taper solid, bent bar ends, camber, abutment diaphragm not drawn. |
| CS-1-24 | Continuous Slab Bridge | 2026-01 | **2** | ✅ DONE — `odot.continuous_slab_bridge` + `Notebooks/res/CS-1-24.py`, 17 tests. Full SLAB DATA table (end spans 14-46 ft, interior = 1.25x end span, 779 numeric entries, cross-checked programmatically against the extracted PDF text). Haunches over piers not modeled (uniform T assumed). |
| CPA-1-08 | Capped Pile Abutment (slab bridges) | 2024-01 | **2** | ✅ DONE — `odot.capped_pile_abutment` + `Notebooks/res/CPA-1-08.py`, 16 tests. Like BCHW, a detailing template (overall dims project-supplied); cataloged fixed section constants + the 5-shape rebar bend legend (Type 6/D801 cross-references `approach_slab`). Cap + pile line + one flared wingwall drawn. |
| CPP-1-08 | Capped Pile Pier (continuous slabs) | 2017-07 | **2** | ✅ DONE — `odot.capped_pile_pier` + `Notebooks/res/CPP-1-08.py`, 11 tests. Genuinely parametric (unlike BCHW/CPA-1-08): sheet's own `pier_length_ft` formula + fixed cap width/end-radius; only pile count/spacing project-supplied. |
| A-1-20 | Typical Abutment Details (expansion joints) | 2024-01 | **3** | ✅ DONE — `odot.typical_abutment` + `Notebooks/res/A-1-20.py`, 7 tests. Explicitly guidance/minimum-values (sheet's own note: "do not use as standalone construction drawings") — cataloged the 2 literal formulas (bearing seat, wingwall limit) + section minimums; backwall/footing/wingwall drawn as a visual check only. |

## Wave 5 — bearings & expansion joints

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| RB-1-55 | Rockers and Bolsters | 2024-07 | **2** | ✅ DONE — added `layout_rocker_bolster` to the already-encoded `odot.rocker_bolster` catalog + `Notebooks/res/RB-1-55.py`, 5 new tests (22 total in the shared rocker/headwall test file). Simplified tapered-body solids (flat top for bolster, curved TOP BEARING DETAIL radius for rocker); flange plate, welds, anchor bolts/dowels not drawn. |
| FB-1-82 | Fixed Bearings, steel bridges | 2024-07 | **3** | ✅ DONE — `odot.fixed_bearing` + `Notebooks/res/FB-1-82.py`, 14 tests. F-50..F-400 dimension/capacity table; masonry plate + pin + top plate solids. Anchor rods, welds, seat reinforcing not drawn. |
| BD-1-11 | Bearing Details, box beams | 2018-07 | **3** | ✅ DONE — catalog (`BeveledLoadPlate`/`load_plate_bevel`) already existed in `odot.box_beam`; added `layout_load_plate` + `Notebooks/res/BD-1-11.py`, 7 new tests (41 total in `test_odot_box_beam.py`). Beveled plate sized to the B1/B2 bearing pad; anchor recesses/box-width-dependent hole spacing not drawn. |
| EXJ-4-87 | Strip Seal EXJ, steel stringers | 2024-01 | **4** | ✅ DONE — `odot.strip_seal_joint` + `Notebooks/res/EXJ-4-87.py`, 8 tests. Skewed joint line + the sheet's own a1-a4 support-angle formulas per stringer. Gland (manufacturer-generic), retainer plates, anchor bars not drawn. |
| EXJ-5-93 | Strip Seal EXJ, box beams | 2024-01 | **4** | ✅ DONE — `odot.strip_seal_joint_box_beam` + `Notebooks/res/EXJ-5-93.py`, 8 tests. Plate "A"/"B"/"C" spacing table (36/48 in beams) + joint-length formula. Closes Wave 5. |
| EXJ-6-17 | Strip Seal EXJ, I-beams | 2024-01 | **4** | Same pattern. |
| EXJ-2-81 | Compression Seal EXJ, steel | 2022-07 | **4** | Aging detail, still standard. |
| EXJ-3-82 | Compression Seal EXJ, box beams | 2013-01 | **4** | Same pattern. |

## Wave 6 — prestressed & integral construction

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| PSBD-1-25 | PS Box Beam Details | 2026-01 | **2** | ✅ DONE (earlier work) — sections/strands/ties/bearing pads in `odot.box_beam`/`box_beam_design`; full Rhino pipeline in `rhino_box_beam.build_box_beams`, tested (`test_odot_box_beam.py`, `test_rhino_box_beam.py`). |
| PSID-1-13 | PS I-Beam Details | 2025-07 | **3** | ✅ DONE (extended 2026-07-12) — `odot.ps_i_beam` now carries all **13** sections (7 WF sections from sheets 2-3 added; Modified Type 4 top flanges corrected to 36/36/48 in), permissible strand grids (vector-extracted; totals reconcile with the sheet's 26/40/52/62), true tapered outlines, sheet 10 design constants. No PSIDD sheet exists, so `ps_i_beam_pipeline` *designs* the strand pattern (Service III + Strength I, losses, transfer with designed end debonding per 5.9.4.3.3) and `rhino_ps_i_bim` emits the BrIM slice (work-plan Phase 6). 39 tests. |
| ICD-1-20 | Integral details, steel on flexible abutments | 2024-01 | **4** | ✅ DONE (2026-10-03) — `odot.integral_abutment` + `rhino_scd_substructure.integral_abutment_emit`: 3 ft pile cap on one pile row (2 ft embed), 3 ft end diaphragm around the beam ends, 6 in approach seat, 2'-6" turned-back wingwalls; the sheet's limits (skew <= 30 deg, expansion length 267 -> 133 ft, pile spacing 3 dia .. 8 ft, >= 4 piles, cap <= 7'-6"), pile minimum-length table, rebar list. Built for the type study's integral abutment type. |
| ICD-2-18 | Integral details, PS I-beams | 2024-01 | **4** | ✅ DONE — same module with `beam_type="ps_i"` (333 -> 166.5 ft expansion length, 1'-8" beam embedment / 3 ft level seat cataloged). |
| SICD-1-21 | Semi-integral details, steel on rigid abutments | 2024-01 | **4** | ✅ DONE — `odot.semi_integral_abutment` + `semi_integral_abutment_emit`: 2 ft stem on a 6 x 3 ft footing (two pile rows) or 4 x 3 ft on drilled shafts, diaphragm seated 9 in above the seat, wingwalls, SICD-2-14 guides. |
| SICD-2-14 | Semi-Integral Abutment Diaphragm Guide | 2021-01 | **5** | ✅ cataloged inside `semi_integral_abutment` (ITEM 511 EACH, rub plates, guide points on the seat); the guide's own concrete is not drawn. |

## Wave 7 — fencing & guidance-heavy sheets

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| VPF-1-24 | Vandal Protection Fencing | 2025-01 | **5** | ✅ DONE — `odot.vandal_fence` + `Notebooks/res/VPF-1-24.py`, 9 tests. The three post sections (PS-1 curved/BP-3, PS-2/BP-1, PS-2/BP-2) and their max spacings; fence-run post/rail layout. Fabric, tension wire, base plate/anchor hardware, and the PS-1 curve geometry are cataloged, not drawn. |
| TVPF-1-18 | Temporary Vandal Protection Fencing | 2025-01 | **6** | Not built — a temporary variant of VPF-1-24 with its own DD (design detail) sheet to build against if this becomes worth doing; `vandal_fence.py`'s pattern would extend directly. |
| GSD-1-19 | General Steel Details | 2024-07 | **7** | Not built as a component — a library of unrelated details (stiffeners, cross-frames, welds) better suited as a reference doc than one parametric module; referenced by name from CPA-1-08/CPP-1-08 already. |
| NBS-1-09 | Noise Barrier Specifications | 2025-01 | **8** | Not built — 13.6k words of specification text, only generic post/panel geometry (rated 8, per the original SCD-program rule: 8-10 gets a note only). |
| WU-1-26 | Wildlife Underpass | 2026-01 | **8** | Not built — site grading/aggregate path guidance + pay items under an existing bridge, no parametric structure (rated 8, note only). |

## Not applicable

- **2026-01-16 Full Set** — concatenation of the above; not downloaded.

---

# Roadway, Hydraulic & Plan-Insert SCDs — structural-library subset

Reviewed 2026-07-05 from the roadway index
(https://www.dot.state.oh.us/SCDs/Pages/roadway.aspx), the hydraulic index
(https://www.dot.state.oh.us/SCDs/Pages/hydraulic.aspx), and the
structures Plan Insert Sheets page.  Only drawings with structural
content were archived (`res/odot_scds/roadway|hydraulic|plan_inserts/`);
purely roadway/landscape/erosion sheets (BP-4/7/9, LA, RM-1/3/6/7, DM-1.x,
DM-3/4, WQ, F-1/2, MGS-5.x layout sheets) were reviewed on the index and
excluded.

## Wave 8 — roadway concrete barriers & curbs (same profile engine as Wave 3)

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| RM-4.3 | Single Slope Barrier, Types B, C, B1, C1 | 2025-07 | **1** | ✅ DONE — Roadway counterparts of the SBR bridge railings; identical profile-sweep engine (fixed a latent `side=0` symmetric-profile bug in the engine along the way). C/C1 catalog as their fixed-height B/B1 base body; the project-variable upper extension is not modeled (see SCD_BUILD_QUESTIONS.md). |
| RM-4.5 | Single Slope Barrier, Type D | 2026-01 | **1** | ✅ DONE — Same family, founded on compacted soil instead of pavement. |
| RM-4.8 | Single Slope Barrier, Type N | 2026-01 | **1** | ✅ DONE — Same family (largest table of the group). |
| RM-4.9 | Single Slope Barrier, Type E | 2025-07 | **1** | ✅ DONE (catalog only) — turned out NOT to be the same family: 36 in barrier on a cast-in-place moment slab, and the sheet dimensions the rebar cage, not the concrete face envelope. Cataloged foundation/rebar data; `layout_roadway_barrier` refuses to draw its (undimensioned) profile rather than invent one. |
| RM-4.2 | 32" Portable Concrete Barrier | 2026-01 | **2** | ✅ DONE — Segment + connection hardware; successor family to PCB-91 (pin & loop vs. hinge bar + bolt). |
| RM-4.1 | 50" Portable Concrete Barrier | 2020-01 | **2** | ✅ DONE — Same pattern, taller; includes the 50"->32" transition section tying it to RM-4.2/PCB-91. |
| BP-5.1 | Concrete Curbs and Curb & Gutter | 2026-01 | **1** | ✅ DONE — 19 sheet labels consolidated into 13 catalog entries (substrate-only variants share a profile); rolled curbs and Type 11's compound curve approximated as straight chamfers; Types 9/10/11 use the project-variable gutter-plate thickness T. |
| RM-2.1 | Concrete Steps | 2013-07 | **2** | Small parametric stair. |
| RM-5.2 | Bikeway Railing | 2023-07 | **2** | ✅ DONE — `odot.bikeway_railing`: a treated-wood 6x6 post / 2x8 top rail / 2x12 face-rail fence (not a crashworthy barrier — the BR-2-15 pairing was role-only), `layout_bikeway_railing` with flared ends and low-shoulder embedment; Item 607 wood fence. |
| RM-4.6 | Concrete Barrier End Sections | 2025-07 | **2** | ✅ DONE — `roadway_barrier.BARRIER_END_SECTIONS` + `layout_barrier_end_section`: Type B/B1 (30 ft median) and Type D (14 ft roadside) as lofting stations down to the 32 in vertical-faced end; Item 622 Each; connects to MGS-3.x / attenuators. |
| RM-4.4 | Single Slope Barrier Transitions | 2025-01 | **3** | ✅ DONE — the sheet is *plan-width* transitions (40 ft tapers wrapping sign-support/light-tower foundations, 36-48 in, and 48 in pier-column protection), not profile lofts; `layout_barrier_transition` returns width-vs-station with joint/raceway/payment rules. |
| RM-4.7 | Thrie-Beam Transition for PCB | 2025-01 | **3** | ✅ DONE (catalog) — `roadway_portable_barrier.THRIE_BEAM_PCB_TRANSITIONS`: 3 connection pairs (generic NJ / generic F / J-J Hook F; no J-J Hook NJ) sharing the nested 6'-3" thrie beam + terminal connectors + spacer/toe-plate hardware; deployment limits and Item 622 incidental payment. |

## Wave 9 — guardrail systems (extends `odot.guardrail`)

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| MGS-3.1 | Bridge Terminal Assembly, Type 1 | 2026-01 | **2** | ✅ DONE — `guardrail.BRIDGE_TERMINALS['Type 1']` + `layout_bridge_terminal`: 13 posts (9 quarter + 3 half spaces), long posts 1-6, thrie-beam rail stack, parapet/end-section connections, curb rule, Item 606 Each. |
| MGS-3.2 | Bridge Terminal Assembly, Type 2 | 2025-07 | **2** | ✅ DONE — trailing-end W-beam terminal connector on an 11x10x5/8 in bearing plate (one-directional roadways only). |
| MGS-3.3 | Bridge Terminal Assembly, Type TST-2 | 2026-01 | **2** | ✅ DONE — 10-post W-to-thrie transition to TST-2-21 (W6x9/W6x15 groups, symmetrical + single + nested thrie segments). |
| MGS-2.1 | Midwest Guardrail System, standard run | 2026-01 | **2** | ✅ DONE — parameters were already cataloged; `layout_mgs_run` now lays out posts/panels at standard/half/quarter spacing. |
| MGS-2.2 | MGS with Rub Rail | 2026-01 | **3** | ✅ registry notes (proportional) — rub rail below the W-beam; full build open if needed. |
| MGS-2.3 | Long Span Guardrail | 2025-07 | **3** | ✅ registry notes (proportional) — unposted span over culverts, Item 606 Long-Span per foot. |
| MGS-2.4 | Socketed Weak Post on Headwall | 2026-01 | **3** | ✅ registry notes (proportional) — weak posts socketed into HW-series headwalls, Item 606 With Socketed Posts per foot. |
| MGS-4.1 | Type A Anchor Assembly | 2025-07 | **3** | ✅ registry notes (proportional) — buried anchor block, 18'-9" rail, Item 606 Each. |
| MGS-4.2 | Type T Anchor Assembly | 2025-07 | **3** | ✅ registry notes (proportional) — tangent end terminal: rounded-end W-beam, breakaway posts, Type 2 BCT cable; Item 606 Each. |
| MGS-4.3 | Guardrail Transitions | 2025-07 | **3** | Height/stiffness transitions. |
| MGS-6.1 | Guardrail at Bridges | 2018-01 | **3** | ✅ registry notes (proportional) — run arrangement at structures: 25 ft BTA + 12'-6" min MGS, 7:1 tapers/flare arcs. |
| MGS-4.5 | Buried-in-Backslope Terminal | 2025-07 | **4** | Earthwork-dependent geometry. |
| MGS-6.2 | MGS at Piers | 2025-07 | **4** | Pier-protection arrangement. |
| MGS-6.3 | Thrie Beam Bullnose | 2025-07 | **4** | Median-nose layout, 8 sheets. |
| F-3.1 | Fence Details at Bridges | 2013-07 | **5** | Bridge fence mounting; pairs with VPF-1-24. |

## Wave 10 — drainage structures (hydraulic SCDs with structural content)

| SCD | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| I-3B / I-3C / I-3D / I-3N | Inlet No. 3 for Single Slope Barrier B/B1, C/C1, D, N | 2024–26 | **2** | Inlets formed INTO the RM-4.x barrier profiles — build on the Wave 8 engine. |
| I-4B | Inlet No. 4 for Single Slope Barrier B/B1 | 2025-01 | **2** | Same. |
| CB-3 / CB-3A | Catch Basin No. 3 / 3A | 2026-01 | **2** | Reinforced concrete boxes, depth-tabled walls, grate castings. |
| CB-2 series | Catch Basins 2-2A…2-6 | 2024-07 | **2** | Family of RC boxes; one parametric module, per-number data. |
| CB-4/4A/5/5A/6/8/8A/9 | Catch Basins | 2024–26 | **3** | Smaller variants; grate/casting geometry dominates. |
| MH-2 / MH-4 | Manholes No. 2 / 4 | 2021–24 | **3** | Tabled riser/base dimensions. |
| MH-1 / MH-3 / MH-5 | Manholes No. 1 / 3 / 5 | 2022–24 | **3** | Same family. |
| I-2 / I-2A | Median / Pavement Inlet No. 2 | 2024-07 | **3** | Frame-and-grate inlets. |
| CB-1 / CB-7 | Side Ditch Inlets / CB No. 7 | 2024-07 | **3** | Sloped-apron inlets. |
| DM-2.1 | Paved Gutters | 2013-01 | **2** | Trivial profile sweeps. |

Excluded from the archive (reviewed on the index): DM-1.1/1.2/1.3
(outlets/underdrains/slotted drains — product-driven), DM-3.1, DM-4.x
(erosion control), WQ-1.x (site basins).

## Plan Insert Sheets (Office of Structural Engineering)

| Sheet | Title | Rev | Rating | Notes |
|---|---|---|---|---|
| BCHW | Precast Concrete Box Culverts | 2022-01 | **3** | ✅ DONE (wingwall/foreslope wall) — `odot.box_culvert_headwall` + `Notebooks/res/BCHW.py`, 11 tests. This sheet is a detailing template, not a dimensioned standard (every length is project-supplied, no catalog); cataloged the general notes, payment items, and the 8-shape rebar bend legend (`bend_shape`), and generate the wingwall/foreslope-wall/footing geometry from supplied dimensions. The ASTM C1577 precast box section span x rise catalog itself is a separate, not-yet-encoded sheet. |
| AJBCBBB | Abutment Joints in Bit. Concrete Box Beam Bridges | 2022-01 | **8** | Notes-dominated single sheet; catalog note on the box-beam modules at most. |
| BC | Bridge Cleaning | 2022-01 | **10** | Pure notes; not archived. |
| CRHS | Collision Repair & Heat Straightening Notes | 2022-01 | **10** | Pure notes; not archived. |
