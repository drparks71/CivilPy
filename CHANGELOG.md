# Changelog

All notable changes to CivilPy are documented here. Generated from git history.
Versions follow [Semantic Versioning](https://semver.org/) (major.minor.patch).

---

## [0.6.1] - 2026-10-26

### Added

- **AREMA floorbeam design checks (`structural.arema.rail_tpg_design`).**
  `ThroughPlateGirderFloorbeam.design_checks(spacing, ...)` runs the Chapter 15 allowable-stress
  checks of a ballasted-deck floorbeam without stringers: live load 1.15 A D / S to the two
  rails, impact (vertical plus rocking, 90 % on ballast), wind on the train as a rail couple,
  dead load given or self-weight; flexure (tension flange net section, compression flange with
  the Table 15-1-12 buckling formulas), web shear net of connection holes, fatigue (Table
  15-1-10 categories A to E', live load plus mean impact) and live-load deflection L/640, in
  Group I and Group II (wind, x 1.25). Returns `FloorbeamChecks` (`.ok`, `.governing`,
  `.table()`, `.loads`). `TPG` keeps the interior floorbeam result on `fb_checks`.

### Fixed

- **TPG floorbeam moment used the girder rocking moment.** The interior floorbeam totals
  added `M_re` (rocking on the main girder, 95.8 kip-ft in the default model) instead of the
  floorbeam's own `fb_M_re` (10.8 kip-ft), overstating the floorbeam moment by 85 kip-ft
  (466 to 381). The end floorbeam's Group II moment read the interior floorbeam's value.
- **Built-up `ThroughPlateGirderFloorbeam(rolled_shape=False)`** stored its dimensions as
  one-element tuples; they are quantities now.
- **`get_tims_data` no longer returns a partial table (`state.ohio.DOT.TIMS`).** A dropped
  connection, HTTP error or ArcGIS `{"error": ...}` body used to print a message and return the
  rows fetched so far (14,000 of ~46,000 bridges in one run). Each page is now retried
  (`retries=3`, `backoff=2.0` s doubling) and a page that still fails raises
  `TIMSDownloadError`, with the fetched rows on `.partial`. No matches now return an empty
  DataFrame instead of raising `UnboundLocalError`.
- **Shape lookups (`structural.steel`).** Current shapes are found by AISC manual label as well
  as EDI name, in any case (`Pipe("Pipe6STD")`, `HSS("HSS12X8X1/2")`). A missing label raises
  `KeyError` listing close names, as documented (was a bare `IndexError` on first use).
  Historic shapes: an unknown name raises `KeyError`, an unknown designation raises `KeyError`
  listing the valid ones, and a name under several designations raises `ValueError` (was a
  plain `Exception`).
- **`slenderness_ratio_flange` is a plain number** on W, HP and historic WF (bf/2tf was
  returned in inches).

### Project

- The PyPI page links the GitHub mirror (github.com/drparks71/civilpy) alongside the
  daneparks.com repository.

---

## [0.6.0] - 2026-10-25

### Changed (defaults - results move)

- **Storm sewer junction HGL follows OHE (`state.ohio.DOT.roadway_drainage`).**
  `design_storm_sewer`, `hydraulic_grade_line` and `junction_hgl` default to
  `hgl_method="ohe"`: the junction HGL is the higher of normal depth (the
  diameter when flowing full) and `(dc + D) / 2` - ODOT's Office of
  Hydraulic Engineering's October 2026 answer.  Travel velocity and the
  intensity re-take are as `"cdss"`, which stays available for re-checking
  CDSS 1.0.0.3 designs.  The junction HGL can only rise.

- **Steel I-girders check to the AASHTO LRFD 10th Edition by default.**
  Lateral-torsional buckling Lp = 1.1 rt sqrt(E / Fyc) and Fyr = 0.5 Fyc
  welded / 0.7 Fyc rolled; web slenderness lambda_rw = c_rw sqrt(E / Fyc),
  c_rw = 3.1 + 5 / a_wc in 4.6..5.7 (`web_slenderness_limit`), also in
  Appendix A6; studs Qn = 0.70 Asc Fu with phi_sc 1.0 and fatigue
  Zr = (dF)n Asc (Condition 9.2).  `design_year < 2024` keeps the 9th
  Edition forms.  Checked end to end against NSBA Steel Bridge Design
  Handbook Design Examples 1, 2 and 4.
- `bolt_shear_resistance` defaults to C = 0.56 / 0.45 (8th Edition on);
  `design_year < 2017` gives 0.48 / 0.38.
- **`bolted_field_splice` follows the NSBA Steel Bridge Design Handbook
  Ch. 14 (Dec 2025) and the AISC-NSBA Standard Plans.**  Girder-flange
  block shear uses each flange's own thickness and Fy / Fu (results no
  longer change when the sides are swapped); flange bearing sums end and
  interior holes against the weaker of the flanges and splice plates; the
  flange-only Service II slip check is advisory (`CheckResult.advisory`)
  since the web slip check governs; Kc = 0.80 for Class C and
  duplex-over-galvanized (`BoltSpec.duplex_galvanized`).  The C6.13.6.1.3b
  10 % rule applies automatically (`splices.plate_area_difference`), and
  block-shear tension planes span every gage line.  `method="stress_based"`
  takes concurrent top / bottom flange stresses (`SpliceInput.stress_cases`)
  for the full 6.13.6.1.4c design forces - was 22 % low on compression
  cases.

### Added

- `idf.overland_flow_chart_minutes` / `OverlandFlowChart` / `FIGURE_1101_1`:
  the L&D Vol. 2 Figure 1101-1 overland flow nomograph, its scale geometry
  read off the published figure (any similar chart by passing its geometry).
  `idf.intensity_function` and `idf.idf_curve` give rainfall curves as
  functions of duration.
- `roadway_drainage.analyze_inlet_run`: given catch basins and inlets
  element by element down a curbed gutter - time-of-concentration loop
  (tc + gutter travel at 0.75 Q / A), straight / composite gutters,
  1103.5.2 interception on grade, sags taking both sides
  (`sag_inlet` default, pluggable).  With `InletBasin`, `CB_6` (SCD CB-6),
  `sag_depth` (weir / transition / orifice), `ponded_spread`,
  `capture_per_foot`, `side_capture_fraction` (optional floor),
  `gutter_area`, `composite_gutter_area`, `gutter_travel_minutes`,
  `GUTTER_VELOCITY_FACTOR`.
- `design_storm_sewer`: rainfall as functions (`intensity`,
  `check_intensity`), a size series (`sizes`), `min_d_in`,
  `start_at_upstream_size`, crowns in place of inverts, a fixed `slope`,
  per-run `n` and `areas`, held sizes below the minimum flagged,
  `full_q_ratio` (Q / A full near capacity; `flowing_full`, `flow_depth`),
  `round_output=False`; rows carry the local / total area.
- `analyze_ditch`: rainfall as functions, any section object
  (`CircularChannel` for round-bottomed ditches), `start_min`,
  `max_depth_ft`, and a lining `progression` that re-runs the shear storm
  with each rougher lining (trials in `storms["shear_trials"]`).
- `culvert_design.first_passing`, `design_table` (D / D-1 / D-2 / D+1 and
  F rows) and `overflow_discharge` (the flow the culvert cannot pass at the
  overflow elevation).
- `structural.staad`: read a STAAD.Pro .std deck (geometry, sections,
  releases, master / slave, static loads, combinations, moving loads and
  LOAD GENERATION) and translate it to MIDAS Civil NX tables.
- `frame_analysis`: direct-stiffness 3-D frame / truss solver on the
  StructuralModel hub, for truss analysis per AASHTO/NSBA G13.2-2024.
- `aashto/lrfd/pins`: pins, eyebars and pin-connected plates (6.7.6, 6.8.6,
  6.8.7) with `pin_actions` / `pin_checks`.
- `member_strengthening`: FHWA HIF-18-042 locked-in / shared stress method
  for plates bolted onto in-service members, with interaction and
  magnified rating factors.
- `aashto/irm`: internal redundancy of built-up members (NSBA IRM Evaluator
  v3.2 port).
- `lrfr.steel_member_rating`: the MBE 6A steel rating flow for inventory,
  operating, legal, permit and emergency vehicles.
- `aashto/fatigue_retrofit`: retrofit categories and retrofitted remaining
  life (AASHTO/NSBA G14.1-2021).
- `structural/heat_straightening` (Avent's method) and
  `structural/heat_curving` (Fabrication Spec 14.3.2.2, NSBA Heat Curve
  Evaluator v2.01 port).
- `aashto/cif`: constraint-induced fracture scorecard (NSBA B304).
- `aashto/lrfd/stability_bracing`: torsional and lean-on bracing
  (6.7.4.2.2, NSBA B303).
- `structural/span_curves`: span weight / depth curves for preliminary
  design (curve data supplied by the caller).
- `ContinuousBeam` shear, reaction and continuous-moment influence lines;
  `InfluenceLine.hs20_44_effect` (Standard Specifications HS20-44,
  validated against the AISC continuous highway bridge tables) and
  `hl93_effect(dual_truck=...)` for the 3.6.1.3.1 two-truck negative-moment
  loading (`"contraflexure"` applies it only in the negative-moment region)
  with the C3.6.1.3.1 dual tandem.
- `lrfd.rigid_rotation_exterior`, `moment_gradient_factor`,
  `lateral_bending_amplification`, `b6_rotation_limit`,
  `b6_refined_effective_moment`.

### Fixed

- Constructibility, discretely braced and tension-flange checks take fbu
  and fl as magnitudes - a negative compressive fbu passed every case.
- `transverse_stiffener_inertia` interpolates Eq. 6.10.11.1.3-7 on rho_w
  when the panel shears are given (was I_t2 always).
- The historic steel shapes table reads a lone space as missing, so its
  property columns stay numeric under pint 0.26.

### Dependencies

- Lock file refreshed for published advisories: Pillow 13.0.0,
  certifi 2026.10.23, tornado 6.6, filelock 4.2.4, werkzeug 3.1.9,
  setuptools 84.2.1, paramiko 5.1.0.  Pillow 13 and filelock 4.2 need
  Python 3.11+, so Python 3.10 stays on Pillow 12.3.0, filelock 4.1.0 and
  tornado 6.5.10.

## [0.5.0] - 2026-10-14

### Changed (defaults - results move)

- **Storm sewers follow ODOT CDSS by default (`state.ohio.DOT.roadway_drainage`).**
  `design_storm_sewer` / `hydraulic_grade_line` take `hgl_method="cdss"`:
  pipe travel at the mean velocity at the design flow (`mean_velocity`), the
  HGL intensity at the outlet arrival time re-taken where the HGL is
  repositioned, junction HGL = max(junction, flow line + (dc + D) / 2)
  (`junction_hgl`; normal depth never repositions it), and a run over
  capacity at least at its crown upstream.  Checked run by run against CDSS
  1.0.0.3 printouts of branched systems (0.012 ft HGL).
  `hgl_method="single_intensity"` keeps the 0.4.x behaviour.
- **Ditches follow CDSS by default.** `ditch_n` / `ditch_check` /
  `analyze_ditch` take `n_method="cdss"`: the lining n for the velocity /
  shear storm and 0.040 for the depth storm; `"single"` keeps one Table
  1102-2 n for both.
- `bolted_field_splice`: `method="stress_based"` replaces `"odot_bdm"` (kept
  as a deprecated alias with a `DeprecationWarning`).

### Added

- `design_storm_sewer`: branched systems (`from_junction` / `to_junction`,
  junction "0" = no pipe in; any tree with one outlet).
- `analyze_ditch`: a ditch run reach by reach - CA accumulation, each storm
  carried down on its own, travel at the velocity of the start-time flow,
  concentrated inflows (`inflows`).
- `state.ohio.DOT.drainage`, `idf`, `roadway_drainage`, `culvert_design`: ODOT
  L&D Vol 2 (July 2026) as functions - design floods, Figure 1101-2 IDF,
  rational method, ditches, pavement drainage and inlets, storm sewers and
  the 4 % HGL, 1105 culvert sizing (with an agency conduit catalog option).
- `water_resources`: HDS-5 culvert analysis (`culvert`), embankments and
  digital-dam openings, StreamStats / NSS, Atlas 14 + MRMS precipitation,
  irregular cross sections, scour screening, NWS alerts, FEMA NFHL, NHDPlus HR.
- `geotech`: boring layers and DIGGS writer, PDF boring logs to DIGGS
  (`state.ohio.DOT.boring_log_pdf`), strata correlation between borings
  (`stratigraphy`).
- `transportation`: clothoid spirals, unsymmetrical vertical curves, LandXML
  1.2 alignments; `state.ohio.coordinates` (Ohio County Coordinate System,
  88 zones checked against the published PRJ files).
- `structural`: site and bridge-alternative schema records (`site_spec`),
  SCD substructure / abutment BrIM emits incl. integral and semi-integral
  abutments, gusset-plate geometry and riveted-truss BrIM (LOD 400/500, IFC
  backend), prestressed box-beam and continuity-bar records (`bim_spec`),
  box-bridge detail gallery, composite steel girder MIDAS payload builder.
- `state.ohio.DOT`: permit-load route screen (`permit_route`), airway /
  highway clearance screen, AssetWise inspection-file dump
  (`civilpy odot photos`).
- Scan-to-CAD (`civilpy.scan`), below.

### Fixed

- `MethodABearing.get_strain_from_stress` argument order (crashed on every call).
- `bolted_field_splice` matches the NSBA Bolted Splice Designer v4.01 Hw rule.
- `state.ohio.ogrip`: EPSG:6549 is Ohio North (comments).
- `influence_lines` imports matplotlib only inside `plot()`.

### Scan-to-CAD

- **Scan-to-CAD: `civilpy.scan` — point-cloud segmentation, meshing and
  feature extraction for bridge sites.** `cloud` streams `.las`/`.laz`
  (laspy), `.xyz` and `.ply` through bbox / class / decimation / voxel-grid
  reductions so a 9 GB static scan reads into a few million points;
  `preprocess` (voxel, SOR/radius outliers, PCA normals, crops, axis
  frames), `segment` (vectorised RANSAC planes with SVD refinement,
  two-point-with-normals RANSAC cylinders with normal-based axis
  refinement, progressive-morphological ground filter, Euclidean
  clustering, region growing, slices), `features` (typed plane / cylinder /
  line / polyline records, alpha-shape boundaries, plane–plane crease
  edges, a surface-supported under-clearance grid, cross sections, bridge
  role labels, coplanar-fragment merging, and substructure units + span
  layout from the lowest-structure-point profile under the deck),
  `mesh` (Delaunay / grid meshing, primitive meshes, PLY/OBJ/STL writers,
  optional Open3D Poisson / ball-pivot), `cad` (DXF via ezdxf and Rhino
  `.3dm` via rhino3dm on the shared `rhino_layers` taxonomy, plus a
  `Terrain` bridge), `pipeline.extract_features` (one call, `ScanFeatures`
  report with JSON / DXF / 3dm / mesh export) and `plots` (plan +
  elevation overview). New `civilpy scan info` / `civilpy scan extract`
  CLI commands. Validated on synthetic bridges (tests) and on three real
  static scans (a 600 ft railroad viaduct on seven tower piers, a
  three-span through truss, and a whole-valley site scan) — deck extents,
  pier heights and span lengths come out to within the 2 ft profile bin.
  Scans are never committed: `.gitignore` now blocks `.las/.laz/.pod/
  .e57/.pcd/.rcp/.rcs`.
## [0.4.5] - 2026-09-15

- **Fix: continuous-bridge span ratio was inverted (`structural.rating_ratios`).**
  The three-span sub-model built the adjacent spans as *ratio x maximum
  span*; the ratio is defined as *maximum span / adjacent span*, so the
  adjacent spans are the shorter ones (``L/r | L | L/r``).  At ratio 1.2 on
  a 40 ft span the two layouts differ by ~50 % in positive moment, which
  moved the governing-case search onto the wrong ratio.  Simple spans were
  unaffected.  Re-run any continuous-bridge predictions.

- **Fix: mirror-image M+ peak stations broke the alignment check.** The
  envelope sometimes reports a vehicle's positive-moment peak in the far
  end span of the symmetric model; the critical-section check then compared
  a 16 ft station against a 104 ft one and dropped knowns that align.
  Peak stations are now folded into the first half of the beam.


## [0.4.4] - 2026-09-15

Everything since 0.4.1 — 0.4.2 and 0.4.3 were tagged without changelog
entries, so this section carries their items too.

- **AssetWise client — retries that succeed are INFO, and counted.**
  `_get_with_retry` logs only the final failed attempt at WARNING; earlier
  attempts log at INFO and bump the process-wide
  `AssetWiseClient.transient_retries` counter, so a caller reports "N
  transient retries" once instead of filling an error log with them.

- **AssetWise client — who performed a report.**
  `get_report_inspectors(ast_id)` (InspectionReport/GetInspectors, team
  leader first) and `get_user_full_name(in_id)`; `get_report_inspection_types`
  (rt_id is always 1 in ODOT data; InspectionReportInspTypeMap is the real
  type source); fail-fast 4xx with explanatory 404 messages (asset gone vs.
  no report container).

- **AssetWise client — files.** `get_report_files` / `get_asset_files`
  (report-map and asset-level scopes are independent), `download_file` /
  `download_file_named` (names from Content-Disposition), plus the
  `civilpy odot photos` dump.

- **MIDAS Steel Composite Girder Bridge wizard, reproduced
  (`structural.midas_composite_wizard`).** `build(WizardInputs)` emits the
  `/db` payload the Civil NX wizard would; its geometry rules were verified
  against a wizard-generated model and are now exact: every reference line
  is a skewed straight line with the skew interpolated between supports,
  strips are one element per bay and three per overhang, the deck-edge
  "Dummy Beam2" chains, downward V cross frames, seat-plus-link bearings,
  cap tips on the deck edges, bank about the reference line, a
  `vertical_curve` input. Property tests over three bridges.

- **Airway/Highway Clearance Analysis screen (`state.ohio.DOT`)** — L&D
  1407.1 / 14 CFR 77.9 imaginary surfaces from NASR runway geometry.

- **Gusset-plate geometry model and checks (`structural`)** — Whitmore
  section, unbraced lengths, block-shear paths, cut sections, section-loss
  thickness field; LRFD 6.14.2.8 and 2012 ODOT LFR gusset checks, validated
  against a 2012 ODOT LFR gusset rating sheet; `rhino_gusset` interchange.

- **Riveted-truss BrIM** — `rhino_truss`, built-up members modelled as real
  I-sections, LOD 500 riveted gusset joints, the Truss layer group; **IFC
  backend** with the review overlay that makes a model a review model.

- **Security CI** — re-vendored template (SAST was scanning zero files),
  High-severity dependency findings from the 2026-08-31 scan cleared.


- **Cost estimate straight from a BrIM `.3dm`
  (`structural.bim.cost_estimate`, `structural.rhino_bim.read_bim_estimate`).**
  The pay-item quantity read-back now runs through a swappable unit-price
  book: `DEFAULT_UNIT_PRICES` seeds planning-level $/unit for the catalog
  items, `cost_estimate(quantities, prices={...})` extends each row with
  `unit_price`/`cost` (unpriced items are flagged, not silently dropped)
  and totals the rest, and `read_bim_estimate(path)` does the whole trip
  from a saved Rhino file in one call. Read-back also honors layer
  visibility now — `read_bim_tags`/`read_bim_quantities` walk the layer
  parent chain and skip components under a hidden layer (e.g. a `Legacy`
  tree kept for reference), so the takeoff counts exactly what the
  viewport shows (`include_hidden=True` restores the old behavior; the
  bridge marker always comes back). Demonstrated end-to-end in the new
  **BIM Cost Estimate from a Rhino Model** notebook against the committed
  `AI Generated Bridge.3dm`.

- **Critical-section alignment check for positive-moment RF
  predictions (`structural.rating_ratios`).** Completes the ORIL 2026
  flowchart: when positive moment governs, a known vehicle's RF only
  transfers cleanly if its maximum-moment section falls near the
  target's, so `predict_rating_factors` now computes each known's M+
  peak-station offset as a fraction of the span and keeps only knowns
  inside the report's ±5 % band (`ALIGNMENT_TOL`) in the average —
  short spans under ~50 ft are where this bites, per the report's
  Figure 6. Each `RFPrediction` carries the per-known `misalignment`
  map, the `aligned` subset actually averaged, and an `alignment_ok`
  flag that goes `False` when *no* known aligns (all are then averaged
  as a fallback so callers can route the bridge to full analysis
  instead). Shear and negative-moment cases skip the check — their
  critical sections sit at the supports for every vehicle. Wired
  through `identify_governing_case(alignment_tol=...)`; pass `None` to
  disable. Tests cover long-span convergence, short-span exclusion
  (a corrupted misaligned known cannot contaminate the prediction),
  the none-aligned fallback, and the disabled path.

- **Constrained inputs documented at the type level.** Enum-like string
  parameters across the library now carry `typing.Literal` annotations
  and `#:` field docs naming their allowed values — they render in the
  Sphinx signatures, autocomplete in IDEs, and type-check statically
  instead of failing at the runtime guard. Swept: slab-bridge
  `edge_condition`, alignment curve `direction`, pier column `fixity`,
  retaining-wall `method`, STM `solve` method, anchor `shear_direction`
  / `anchor_type`, bearing `fixity` + `default_fixity`, barrier-run
  `edge`, abutment `kind`, load `direction`, MGS bridge-terminal
  designations and post `spacing`, and BCHW `headwall_type`.
  Catalog-keyed strings (AISC girder/pile labels, ODOT railing and PSBD
  box designations, line-girder `barrier`/`vehicle` choices) instead
  gained field docs pointing at the owning catalog.

- **Ratio matrices and governing-case identification
  (`structural.rating_ratios`).** The core of the ORIL 2026 load-factor
  assignment method (ODOT PID 123396): known rating factors scale to
  unknown vehicles through 1D live-load-effect ratios because capacity
  cancels, but the inventory hides *which* action governed — so
  `identify_governing_case` matches the empirical relative-RF matrix
  (`RF_i/RF_j`) against theoretical demand-ratio matrices (`E_j/E_i`)
  per action and picks the minimum Frobenius-norm residual. Simple
  spans compare M+ vs V on the longest span; `continuous=True` adds M-
  and sweeps the paper's `r*L | L | r*L` three-span sub-model across
  candidate span ratios (default 1.00-1.80 by 0.01) for the global
  minimum, returning the best-fit ratio and the full sweep curves.
  Demand bases (`simple_span_demands` / `three_span_demands`, cached
  per configuration) ride the new `UnitResponses` fast path in
  `continuous_beam` — unit-load matrices solved once per beam and
  shared across all vehicles — and carry M+ peak stations for the
  critical-section alignment check. `predict_rating_factors`
  finishes the flowchart: each known RF scaled through the governing
  ratio, averaged, with per-known-vehicle spread kept for QC.
  Synthetic-recovery tests confirm exact identification of action and
  span ratio (zero residual, ground-truth RFs reproduced) and
  robustness to ±3 % RF noise.

- **Rating-vehicle catalog and moving-load envelopes** (groundwork for
  the ORIL 2026 load-factor assignment methodology, ODOT PID 123396).
  `aashto.vehicles` gains a frozen `RatingVehicle` axle-train dataclass
  and the full catalog behind Ohio's legal-load ratings: AASHTO legal
  trucks Type 3 / 3S2 / 3-3 (MBE Fig. D6A-1), SHVs SU4-SU7 (Fig. D6A-2),
  FAST-Act EV2/EV3, Ohio 2F1/3F1/4F1/5C1 (BDM 908), and HS20 / HL-93 in
  train form — all exposed via `RATING_VEHICLES` and ready for the
  axle-train steppers. `continuous_beam` gains `moving_load_envelope`:
  unit-load response matrices (one stiffness solve per grid point, every
  truck/direction/placement a gather-sum afterwards) enveloping shear and
  moment at every station, with patterned lane-load placement from the
  same influence columns and `EnvelopeExtreme` peak lookups (max M+, max
  M-, max |V| with stations). Verified against the closed-form
  influence-line path and the HS-20 textbook maximum.

- **BCHW rebuilt against the actual Design Data sheets.** The module's
  "no dimension table" premise was wrong — ODOT's six Design Data
  sheets tabulate everything. `box_culvert_headwall` now carries the
  full catalog: headwall Types A/B/C (Type B per roadway skew
  0/15/30/45), the eight design-height rows each of dimensions,
  X/Y bar callouts, footing designs 1-8 with their V/W/Z reinforcing,
  foreslope-wall quantities, the span -> wall-thickness rule, and
  `design_headwall` resolving `H = rise + 2 slab + foreslope height`
  against the tables. `rhino_bchw.bchw_emit` produces the complete
  culvert-end assembly — **both** wingwalls placed per type (45 deg /
  straight / parallel, 2:1 backslope tops), the foreslope wall sitting
  on top of the box with the barrel opening clear, a display-only
  precast box stub, footings with the 4 ft extension and cutoff walls,
  and the sheet's reinforcing series — on `Culvert::*` layers.
  Wingwall roots retain the full design height H (the tabulated `h` is
  the tip height, dropping with the graded embankment — level walls
  tabulate h = H); the wall footings clip flush against the culvert
  footing strip (no overlaps, no wedge gaps); the strip carries its own
  V/W mats and Z cutoff bars running continuously across the opening;
  and a skewed culvert's box stub is end-cut on the rotated headwall
  plane. Quantities are the sheet's tabulated values (concrete on the
  solids, reinforcing on schedule markers), so `pay_item_quantities` /
  `read_bim_quantities` reproduce the sheet estimate exactly. The
  Grasshopper component now takes the real design inputs (type, span,
  rise, skew, foreslope height). All 24 civilpy-importing GH components
  also gained the `# r: civilpy` package directive Rhino 8 needs.

- **Basic line-girder tool (`structural.line_girder_tool`).** The
  simplest useful form of a shear/moment/deflection run, with no Rhino
  or MIDAS dependence: a `BridgeConfig` of dropdown-able settings
  (barrier type from the ODOT railing catalog, AASHTO vehicle, deck
  thickness, span count/length, girder size/spacing/overhang, FWS)
  produces the per-girder load build-up (DC1/DC2/DW klf plus the
  4.6.2.2 moment/shear/deflection distribution factors, interior and
  exterior) and V/M/Δ diagrams — dead load exact, live load as a
  stepped-axle-train + patterned-lane envelope. The *Shear Moment and
  Deflection Diagrams* notebook was rewritten around it: an
  ipywidgets dropdown panel plus three statically-rendered preset
  configurations, replacing the old Rhino-file/MDX walkthrough.
- **`ContinuousBeam` grows shear and deflection.** `shear_at`,
  `shear_diagram`, `diagrams` (one reactions solve, vectorized statics
  at arbitrary stations), and `deflection_diagram` (curvature
  integrated twice, rigid-body line removed least-squares through the
  supports, inches, negative down) join `moment_at`. Verified against
  AISC Steel Construction Manual Table 3-23 cases 1/29/30/43/44 in
  `test_line_girder_tool.py`, including the moving-load maxima.
- **Fix: point load exactly on an interior support.** The
  slope-deflection statics counted such a load in *both* adjacent
  spans (closed intervals), so a stepped axle landing on a pier
  inflated the reactions (72-kip truck → 104 kips of reaction) and the
  envelopes built on them. Span membership is now half-open — the load
  goes to the span on its right and straight into that support's
  reaction.

## [0.4.1] - 2026-07-13

- **Offline `.3dm` backend (`rhino_bim.emit_to_3dm`).** Bakes a
  `BridgeEmit` into a real Rhino file with standalone `rhino3dm` — no
  Rhino session, no MCP server, no network: prisms become capped
  extrusion breps (correct caps for the non-convex I-girder and parapet
  profiles, closed-mesh fallback for oblique vectors), studs cylinder
  breps, rebar polyline curves, on the shared colored layer taxonomy
  with every `bim.*` / `pay.*` / `mat.*` tag intact. The bridge-wide
  record rides the `bim.type = bridge` marker, so
  `read_bim_quantities` regenerates the pay-item estimate from the
  saved file exactly (round-trip covered in `test_rhino_bim`). The MCP
  server the prototypes used was only a transport; this is the
  equivalent for locked-down networks.

- **Substructure Gallery notebook.** One 3-span bridge carrying one of
  each substructure type — semi-integral abutment, hammerhead pier,
  capped-pile bent, integral abutment (bearing stack correctly
  omitted) — every cap a real `optimize_pier_cap` STM design fed by
  native `ContinuousBeam` Strength I reactions, executed end to end
  (~30 s) and baked to `substructure_gallery.3dm` (4,468 tagged
  objects) plus the JSON payload for the live `draw_bim_emit.py` path.

- **OGRIP LiDAR fetch actually works.** The tile-index URLs shipped in
  `state.ohio.ogrip` had been guessed and 404'd on every call. Now
  live-verified: the `OGRIP/3DepTiles` index on `maps.ohio.gov`
  (queries pass `inSR=4326`; the layer's native SR is EPSG:6549),
  download URLs built from `Year`/`County`/`TileName` against the
  `gis1.oit.ohio.gov` ZIP archives mirroring the portal's year switch,
  ZIP-to-LAS extraction, and newest-collection-year dedup where OSIP
  and 3DEP flights overlap. `Terrain.from_ogrip` caches tiles in
  `temp_las/` and skips both re-download and re-extraction on reruns.

- **Map-drawn bbox picker (`transportation.terrain.bbox_picker`).**
  ipyleaflet widget: draw a rectangle in the notebook and
  `picker.bbox` holds the WGS84 `(xmin, ymin, xmax, ymax)` tuple
  `from_ogrip` takes — no copy/paste. Hybrid basemap by default (Esri
  WorldImagery + their transparent road/place-label reference tiles,
  individually toggleable, streets as an alternate base), scroll-wheel
  zoom, fullscreen control, and a Nominatim search box that flies to a
  typed address or jobsite.

- **Steel girder walkthrough cleanup.** The Rhino emit cell's
  SyntaxError (literal newline inside an f-string) is fixed and the
  cell now writes `bim_emit.json`; the synthetic-valley terrain
  fallback is removed (real data only — fallbacks belong in tests),
  the LiDAR fetch sits behind `fetch_terrain = False` so the notebook
  runs terrain-free, terrain stats read the TIN's own state-plane
  bounds instead of bridge-frame points (`elevation_at` returns `None`
  outside the hull — the old cell's crash), and the alignment takes
  designed endpoint elevations. Tying the bridge frame to the terrain
  frame is the flagged follow-up.

- **API reference caught up.** 45 modules were missing from the sphinx
  tree — the whole bridge-pipeline buildout (`bridge_layout`,
  `bridge_type`, `continuous_beam`, `girder_pipeline` /
  `girder_optimizer`, `construction_staging`, `substructure` +
  `substructure_layout`, `placement`, `bim`, the box-beam and PS
  I-beam pipelines, all nine `rhino_*` backends), `alignment` +
  `terrain`, the `ogrip` package, and 21 ODOT SCD component modules —
  plus refreshed package blurbs and the handful of real build
  complaints fixed. Deployed to Pages via the `docs` tag.

## [0.4.0] - 2026-07-12

The BrIM "source of truth" release: the Rhino model now carries faithful
geometry **and** a complete per-object BIM attribute record (pay items,
SCD keys, materials) for three full bridge types — steel girder,
adjacent box beam, and prestressed I-beam — plus the substructure, all
regenerable into MIDAS models and quantity estimates. See
`docs/BrIM_Work_Plan.md` for the phase-by-phase record.

- **BrIM emit architecture (`structural.bim` + `structural.rhino_bim`).**
  Typed per-component tag builders (`bim.*` / `pay.*` / `mat.*`), a
  seeded ODOT pay-item catalog, and the transport-neutral
  `girder_bridge_emit` → `EmitObject` record drawn by the pure-Rhino
  `draw_bim_emit.py` driver. Deck as a crowned closed solid with BDM
  Figure 309-4 overhangs, vertical-sided haunches (BDM 309.3.5), girder
  k-fillets, shear studs, crown-following deck rebar mats, and the
  SBR-1-20 parapet with its true bar cage. `read_bim_tags` /
  `read_bim_quantities` / `pay_item_quantities` round-trip every tagged
  object back into a pay-item rollup.

- **Substructure (work-plan Phase 4/4v).** `substructure_layout` places
  skew-aligned units under the layout with stepped beam seats that land
  the bearing pads exactly; emit dimensions come from the executed
  design objects (`PierCapDesign` STM ties drive the cap steel). Five
  substructure types, mixable per support line via typed specs:
  multi-column bent, capped-pile bent, hammerhead (tapered cap,
  top-chord tie steel), seat / semi-integral / integral abutments (the
  integral type skips the bearing stack entirely). Cap STM results
  overlay in place; all concrete/pile/reinforcing quantities roll into
  the 511/507/509 items.

- **Adjacent box beams (Phase 5).** `box_beam_pipeline` re-derives the
  PSBDD-1-25 standard designs' governing checks (adjacent-box LLDF,
  elastic shortening + lump-sum losses, transfer/service stresses,
  Strength I flexure) and builds the MIDAS line-beam hub with tie
  elements; `rhino_box_bim` emits hollow members, strand rows, tie
  rods, diaphragms, pads, and the composite topping. Walkthrough
  notebook: design line → checks → tagged emit → MIDAS model.

- **Prestressed I-beams (Phase 6, PSID-1-13).** The catalog now carries
  all 13 sections — the seven WF36-49..WF72-49 wide-flange sections
  were added, and the Modified AASHTO Type 4 top-flange widths were
  **corrected** from Type 4's 20 in to the sheet's wide thin flanges
  (36 in for the 60/66 in beams, 48 in for the 72 in) — plus the
  permissible strand grids (vector-extracted from the drawing; row
  totals reconcile with the stated 26/40/52/62 counts), draped-required
  and shipping-strand locations, true tapered outlines, and the sheet
  10 design constants. With no PSIDD companion sheet, the new
  `ps_i_beam_pipeline` *designs* the strand pattern: smallest even
  straight count passing Service III + Strength I on the composite
  section, with end debonding designed in pairs (5.9.4.3.3, 45 % cap)
  when transfer overstresses the beam end. MIDAS spoke breaks lines at
  the sheet 5 diaphragm stations; `rhino_ps_i_bim` emits the slice with
  the designed strand rows (and debond counts) in the tags.

- **Railing program (SCD Waves 8-9).** RM-4.6 concrete barrier end
  sections (Type B/B1/D lofting stations down to the 32 in
  terminal-ready end), RM-4.4 single-slope barrier transitions
  (plan-width tapers at sign supports and pier protection), RM-5.2
  bikeway railing (new treated-wood post-and-rail module), RM-4.7
  thrie-beam transitions between 32 in PCB families (three connection
  pairs; the J-J Hook NJ shape correctly refuses). MGS bridge terminal
  assemblies Type 1 / Type 2 / TST-2 as post-by-post layouts joining
  guardrail runs to the bridge railings, plus `layout_mgs_run` and
  registry-note coverage of the remaining MGS sheets.

- **Roadway alignment + terrain.** New `transportation` alignment
  module (horizontal/vertical geometry) with terrain support and a
  point-cloud processing notebook — the first leg of the native
  Alignment/Terrain roadmap.

- **SCD review pass.** Every previously-built SCD component
  (A-1-20 through VPF-1-24) re-verified against its drawing; findings
  folded into the modules and `Validation TODOs.md`. The
  `tests/functional_tests/ODOT SCD Components Verification.ipynb`
  notebook now exercises all 33 component families end to end,
  including the three BrIM emits, the substructure type gallery, and
  every barrier shape family generated to a tagged `.3dm`.

### Breaking

- `odot.ps_i_beam`: the Modified AASHTO Type 4 sections'
  `top_flange_width_in` changed from the incorrect `20.0` to the
  drawing's `36.0` / `36.0` / `48.0`; anything consuming those values
  (haunch widths, emit geometry) gets different — now correct —
  dimensions.

## [0.3.9] - 2026-07-07

- **Python 3.9 support (Rhino compatibility).** Lowered `requires-python` to
  `>=3.9` so civilpy installs into Rhino's bundled Python 3.9 (`rhinoinside` /
  Rhino 8 CPython). Added `from __future__ import annotations` to the ~40
  modules that used PEP 604 `X | Y` union type hints, which only evaluate
  natively on 3.10+; deferred evaluation makes the same annotations safe on
  3.9 without changing any typing. `tox.ini` now runs the suite under `py39`
  in addition to `py311`.

- **Bolted field splice — plate sizing tools.** Added
  `size_flange_splice_plates` (C6.13.6.1.3b) and `size_web_splice_plate`
  (6.13.6.1.3c / seal spacing 6.13.2.6.2) to `aashto.lrfd.splices`, so the
  designer proportions the splice plates from the girder geometry instead of
  taking them as inputs: outer plate = narrowest connected flange, web
  clearance gap from `max(tw) + 2*(weld + 1/8)`, inner width `(b - clr)/2`,
  minimum thickness `t/2 + 1/16`, and inner thickness proportioned to the
  outer plate with the 10% double-shear band. The web tool returns the
  near-full-depth plate height, the 6.13.2.6.2 sealing pitch, the resulting
  minimum bolts per row, and whether a web filler is required. Validated
  against both NSBA plate-girder worked examples (`FlangeSplicePlates`,
  `WebSplicePlates`).

- **Documentation overhaul.**
  - Finished the MIT relicense in the source tree: replaced the AGPL notice in
    ~200 file headers with an SPDX MIT notice (`CONTRIBUTING.md` updated too);
    every module now carries the same header.
  - Added module docstrings to the 50+ modules that had none, and fixed
    docstring reST errors so autodoc renders them cleanly.
  - Sphinx site now covers the whole package: new/expanded `.rst` pages for
    `geotech`, `structural` (incl. new `aashto.lrfd`, `odot`, `stm_topology`
    pages), `state.maryland`, `state.ohio.snbi`, transportation and
    water-resources modules; rewrote `docs/index.rst` into a real landing page
    (install, quickstart, package overview, MIT license section); `conf.py`
    reads the release from package metadata instead of a stale hardcode.
  - Import-safety fixes so autodoc (and plain `import`) can't hang or crash:
    GUI scripts (`mdta_photo_editor`, `D6_file_explorer`,
    `ODOT_Inspection_Photo_DL`) no longer launch windows at import —
    wrapped in `main()`; `gemini.py` refactored into callable functions
    (no more API-key check at import); `transportation.FHWA.snbi` no longer
    plots at import; fixed `mdta_photo_editor`'s broken `photos` import;
    added `state/maryland/__init__.py`.
  - New demo notebooks: **Bridge Scour (HEC-18)**, **Geotech Foundations from
    a Boring Log**, and **Roadway Geometry — Curves and Sight Distance**,
    executed and matching the existing invented-problem house style.
  - Added `TODO.md` cataloguing architecture cleanups (redundant modules,
    placeholder stubs, misplaced files, naming inconsistencies).

## [0.3.8] - 2026-07-01

- **Relicensed to MIT.** Reverted from AGPL-3.0-or-later back to MIT (`LICENSE`,
  `pyproject.toml` license field and classifier).

## [0.3.7] - 2026-07-01

- **Bolted field splice — web horizontal force Hw** (`structural.aashto.lrfd`).
  The web bolt group is now sized for the AASHTO 6.13.6.1.3c moment couple: when
  the flanges cannot resist the full splice moment, the excess is delivered to
  the web as `Hw = (|Mu| - Mflange)/(D/4)` and the web bolts are designed for the
  resultant of Hw and the design shear. The controlling ± Hw combines with each
  composite service shear case; deck casting keeps its own. Reproduces the second
  worked example's 66-bolt web exactly (previously governed only by the
  maximum-pitch layout).
  - Fixed the Strength I permanent-load factor in `_factor_loads`: gamma_p is now
    chosen (max 1.25/1.50 vs min 0.90/0.65) to maximize the moment in the
    direction checked, per AASHTO 3.4.1 — required for splices whose dead-load
    moment is negative at the splice.
  - Web checks now include a Service II slip check and bearing against the
    shear-plus-Hw resultant.

## [0.3.6] - 2026-07-01

- **AASHTO 6.13.6.1 bolted field-splice designer** (`structural.aashto.lrfd`). New
  `bolted_field_splice` module: `design_splice(SpliceInput) -> SpliceDesign` sizes
  the flange and web bolt groups, lays out the bolt pattern (gage / pitch / edge /
  end), sizes the splice plates, and runs the limit-state checks by feeding the
  existing `steel`/`splices` primitives. Exported from the `lrfd` package.
  - Extended `splices.py` with the remaining article functions: splice-plate
    design-force apportioning (C6.13.6.1.3b), filler-plate reduction R
    (6.13.6.1.4), net-section limit An ≤ 0.85·Ag (6.13.5.2), composite slab
    crushing (D6.1), flange moment resistance, and bolt spacing/edge limits
    (6.13.2.6).
  - `steel.bolt_shear_resistance` gained a `design_year` switch selecting the
    0.56/0.45 shear coefficient (2017+) vs the legacy 0.48/0.38 (6.13.2.7); the
    default is unchanged.
  - Validated to the cent against two independently worked plate-girder splices
    (bolt counts, layout, plate sizes, block-shear modes, bearing, slab crushing);
    `tests/structural/test_bolted_field_splice.py`. Known limitation: the web
    moment-couple Huw for the inadequate-flange case (needs elastic flange
    stresses) is surfaced through the failing flange checks rather than by
    enlarging the web group.

## [0.3.5] - 2026-07-01

- **SNBI validation — B.RT.01 optional** (`state.ohio.snbi`). AssetWise reports a
  route's number/direction but omits the B.RT.01 Route Designation on many routes,
  and FHWA flags that omission 0 times. `Route.BRT01` is now optional (was
  required); when present it must still be a valid designation (begins with "R",
  ≤3 chars). This clears the residual BRT01 false errors that traced to a
  snbi_ui field-mapping bug (fixed there in parallel: routes were read at the
  feature stride of 31 instead of their own stride of 30, and absent designations
  were fabricated as the literal "Unknown").

## [0.3.4] - 2026-07-01

- **SNBI validation — calibration round 2** (`state.ohio.snbi`). First run against
  a full local AssetWise sync (46,355 bridges / 28,045 NBIS) cut the error count
  from 22,534 (5.5× FHWA's 8,301) to **5,929 (0.71×)** by removing over-reporters
  that FHWA's own report flags 0 times (our REST read omits data the "export FHWA
  data" feed carries). Principle: strip only rules FHWA does not enforce at all;
  keep the ones it does even when our pull over-triggers them on missing data.
  - Dropped the "highway feature must report a Route (BRT01)" requirement (7,358
    false errors); the BH02/06/09/11/13/16/17 requiredness is now gated on the
    feature actually having a Route, so it no longer re-reports the same
    incomplete-pull records thousands of times.
  - BAP03 Scour Vulnerability now accepts "N" (not applicable), matching BAP05.
  - BG05 Width Out-to-Out, BG02 Total Length, BG09 Approach Width, and BCL01/BCL02
    owner/maintenance are optional (FHWA flags none of their nulls); BG06
    curb-to-curb stays required (FHWA does flag its nulls).
  - See `docs/SNBIValidationRules.md` for the per-item table and the finding that
    the residual BRT01 errors are an `snbi_ui` field-mapping bug (route *number*
    loaded into Route *Designation*), to be fixed there, not by loosening the rule.

## [0.3.3] - 2026-06-30

- **SNBI validation — calibration against FHWA** (`state.ohio.snbi`). The first
  full NBIS run against FHWA's processing report showed 0.3.2 over-reported, so
  this release dials the rules back to match FHWA's actual finding rates:
  - Reverted to optional (FHWA tolerates the null far more than our data omits
    it): BG03, BG07, BG08, BG10, BG11, BIR01, BIR03, BAP01, BAP02, BAP03, Route
    BRT03/04/05; BSP12 no longer forced on decked spans. Kept the items that
    matched FHWA (BG06, BG14, BAP05, BCL03/04/05, the highway BH set, BN02/04/06,
    BSP02/04/05/06/09).
  - Removed enum checks that rejected valid codes FHWA accepts: BCL01/BCL02,
    BF01 pattern, BEP03, BSP07/08/10/11/13, BSB05/06/07.
  - Relaxed BG05 > BG06 to BG05 ≥ BG06 (equal widths allowed).

---

## [0.3.2] - 2026-06-30

- **SNBI validation — FHWA agreement build-out** (`state.ohio.snbi`). Closes
  most of the gap against FHWA's own SNBI processing report. See
  `docs/SNBIValidationRules.md` for the full per-item roadmap.
  - Wired the coded-value tables (`_SNBI_CODES` / `_PATTERN_CODES`, previously
    unused) to their fields, so invalid coded values now raise.
  - Made the unconditional "report for all bridges" items required: BG06 (`>0`),
    BG07, BG08, BG03 (`>0`), BG10, BG11, BG14, BAP01/02/03/05, BCL03/04/05,
    BIR01/03.
  - Conditional requiredness: highway features require BH02/06/09/11/13/16/17;
    routes require BRT02–05; span sets require BSP02/04/05/06 (plus BSP09/12 for
    decked, non-pipe-culvert spans); navigable waterways require BN02/04/06.
  - Cross-field rules: BG05 > BG06 (except sidehill), BC09 channel-vs-waterway,
    BH18 ≠ BID01, BW02 ≥ BW01, BEP04 not reported with BEP03 ∈ {C,S,L,V}, and
    one-decimal-place format for BG15/BH16.

---

## [0.3.1] - 2026-06-29

- **SNBI validation fix** — `state.ohio.snbi` `Element.BE02` (Element Parent
  Number) is now optional. It is only reported for child elements (defects,
  protective systems); top-level NBE elements have no parent, so requiring it
  raised a spurious "Field required" on every parentless element (the dominant
  share of validation errors on complete inventories).

---

## [0.3.0] - 2026-06-24

Final 0.3.0 release, promoting the tested 0.3.0rc1/rc2 candidates so a plain
`pip install civilpy` selects it by default.

- **SNBI validation** — `state.ohio.snbi` now enforces the FHWA SNBI Data
  Validation Rules as real Pydantic checks (state-code validation replacing
  the former `Field(eq=39)` no-op, do-not-report rejection, enumerations,
  date/charset/range rules, and cross-field critical/safety checks).
- Includes everything from 0.3.0rc1 and 0.3.0rc2 below.

---

## [0.3.0rc2] - 2026-06-16 (release candidate)

`MidasCivil` hardening from live batch load-rating runs:
- **Long-operation timeout** — `analyze()`, `open()`, and `result_table()` now
  use a 600 s read timeout (class attr `ANALYSIS_TIMEOUT`); the 30 s default cut
  off large finite-element solves mid-analysis. Default request timeout 30 → 60 s,
  and `request()` takes a per-call `timeout=`.
- **`beam_forces(elem_ids, load_case_names, …)`** — element-force extraction in
  the request shape confirmed against live Civil NX (integer `NODE_ELEMS` KEYS +
  `UNIT` + `STYLES` + `PARTS`); omitting any of those returns the
  `"second query is wrong"` HTTP 400.

---

## [0.3.0rc1] - 2026-06-16 (release candidate)

Pre-release for 0.3.0. A plain `pip install civilpy` will **not** select it;
install it explicitly with `pip install civilpy==0.3.0rc1`.

Highlights since 0.2.4:
- **Substructure design** — cantilever retaining wall / abutment
  (`structural.abutment`) and multi-column pier & bent (`structural.pier`).
- **Geotechnical** — laterally loaded piles with a p-y library + FE solver and
  Broms / subgrade methods (`geotech.lateral_pile`), LPILE integration
  (`geotech.lpile`), drilled-shaft & driven-pile axial capacity from boring
  logs (`geotech.deep_foundation`), shallow/spread foundations
  (`geotech.shallow_foundation`), DIGGS boring schema and SPT correlations.
- **MIDAS modeling** — `structural.midas_models` payload builders (curved
  girders, bifurcated girders, integral/semi-integral abutment connections,
  nodal soil-spring supports) and `geotech.axial_load_transfer` API RP 2A
  t-z / q-z axial pile load-transfer curves.
- **RC design** — `aashto.lrfd.concrete.size_flexural_rebar` selects flexural
  reinforcement from a factored moment.
- HEC-18 scour, ODOT standards (box beams, railings, guardrail), CANDE
  box-culvert integration, the truss-bridge builder, and AASHTO LRFD/LRFR
  check-suite expansions.

---

## [0.2.4] - 2026-06-11
- Added `MidasCivil` class to `civilpy.structural.midas` — object-oriented MIDAS API client
  covering the full API surface: generic `/db/*` access (`get_db`/`put_db`/`post_db`/`delete_db`),
  typed table helpers (nodes, elements, materials, sections, supports, static loads, groups,
  load combinations, units), document operations (`new`/`open`/`save`/`save_as`/`analyze`/
  `import_file`/`export_file`), and results extraction via `result_table` (`POST /post/TABLE`).
  Supports custom base URLs, request timeouts, and raises `MidasApiError` instead of printing.
- Fixed `convert_node_units` inverting the conversion factor (12 in → 144 instead of 1 ft)
  and crashing when `to_units` is None.
- Fixed `setup_output_directory` creating the parent directory instead of the `output/` subdirectory.
- Expanded `tests/structural/test_midas.py` with regression tests and full `MidasCivil` coverage.

## [0.2.3] - 2026-05-03
- Bumped version to 0.2.3 for next patch release.
- Updated `pyproject.toml` and synchronized `uv.lock`.
- Preparation for structural engineering TODO implementations.

## [0.1.40] - 2025

- Added extensive docstrings to structural, geotechnical, water resources, and transportation modules
- Migrated from `setup.py` to `pyproject.toml` (PEP 517/518)
- Added Sphinx autodoc documentation pipeline via GitLab Pages
- Fixed CI/CD pipeline: removed Windows/CUDA-only packages (`torch`, `torchvision`, `rhinoinside`) from requirements
- Added `[docs]` and `v*` git tag triggers to CI for selective deployments
- Updated `autodoc_mock_imports` for optional heavy dependencies

## [0.1.39] - 2025

- Added comprehensive Sphinx documentation for structural, geotech, transportation, and state modules
- Updated ReadTheDocs configuration and directory structure
- Improved legacy file handling in `state/ohio/DOT/legacy.py`
- Updated Python and OS version support in `.readthedocs.yaml`

## [0.1.38] - 2025

- Added `# pragma: no cover` annotations to improve coverage reporting accuracy
- Expanded unit tests for structural analysis, geotechnical calculations, and hydraulic designs

## [0.1.37] - 2024

- Added function to display Rhino BREP geometries in Jupyter notebooks

## [0.1.36] - 2024

- Updated licensing of all source files to reflect correct dates

## [0.1.35] - 2024

- Added generalized function for Pydantic models to be used by DBEs

## [0.1.34] - 2024

- Updated Pydantic Bridge Model to QC'd version

## [0.1.33] - 2024

- Updated AssetWise Data Extractor

## [0.1.32] - 2024

- Fixed CI/CD error caused by NumPy compatibility

## [0.1.31] - 2024

- Fixed CI/CD errors caused by NumPy compatibility

## [0.1.30] - 2024

- Fixed CI/CD errors caused by NumPy compatibility

## [0.1.29] - 2024

- Fixed CI/CD errors caused by Python 3.14 compatibility
- Refactored `simple_concrete_slab` for improved readability
- Added `odot_concrete_slab_generator.py` for parameterized bridge deck generation

## [0.1.28] - 2024

- Fixed missing files from previous versions

## [0.1.27] - 2024

- Further developed steel manual reference

## [0.1.26] - 2024

- Various updates and notebook restorations

## [0.1.25] - 2024

- Improvements to SNBI and ODOT tools

## [0.1.24] - 2024

- Improvements to SNBI and ODOT tools

## [0.1.23] - 2024

- Improvements to SNBI and ODOT tools

## [0.1.22] - 2024

- Improvements to SNBI fields and AssetWise data pulling

## [0.1.21] - 2024

- Focused on SNBI fields, AssetWise data, and QOL functions

## [0.1.20] - 2024

- Focused on SNBI fields, AssetWise data, and QOL functions

## [0.1.19] - 2024

- Added BRR functions, updated FEA tools
- Added new way to query and generate maps for ODOT bridges

## [0.1.18] - 2024

- Added BRR functions, updated FEA tools
- Added new way to query and generate maps for ODOT bridges

## [0.1.17] - 2024

- Moved modules; bearing design first draft complete

## [0.1.16] - 2024

- Moved modules; bearing module mostly complete (compressive stress pending)

## [0.1.15] - 2024

- Removed secondary function providing incorrect results

## [0.1.14] - 2024

- Removed secondary function providing incorrect results

## [0.1.13] - 2024

- Removed secondary function providing incorrect results

## [0.1.12] - 2024

- Updated bearing calculation code; ready for early review

## [0.1.11] - 2024

- Reorganized to separate AASHTO and AREMA tools into distinct subpackages

## [0.1.10] - 2024

- Added AASHTO load combinations

## [0.1.9] - 2024

- Added OSE tools; renamed `section` to `reference`

## [0.1.7] - 2024

- Added OSE tools

---

_This file is generated from git commit history. To regenerate:_

```bash
git log --oneline | grep "Release" | head -50
```
