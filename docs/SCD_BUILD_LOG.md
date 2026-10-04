# ODOT SCD component build log

One line per SCD, updated as each lands. NOTE 2026-08-19: the GH prototype
scripts in `Notebooks/Rhino Components/` were removed after porting completed
(every SCD below is done or not-built-by-design); the table's GH-script paths
are historical — retrieve them from git history if ever needed. The live
components (`draw_bim_emit.py`, `odot_bridge_generator_ghpython.py`,
`ODOT SCDs.gh`) remain.

One line per SCD, updated as each lands. Status: done / parked /
skipped-by-rating. Companion decisions and open questions live in
`SCD_BUILD_QUESTIONS.md`.

| SCD | Status | Module | GH script | Tests |
|---|---|---|---|---|
| AS-1-15 | done (rebuilt 2026-07-14: BrIM emit + near/far + alignment placement) | `structural/odot/approach_slab.py` + `structural/rhino_approach_slab.py` | `Notebooks/Rhino Components/AS-1-15.py` | 21 (`test_odot_approach_slab.py`) + 11 (`test_rhino_approach_slab.py`) |
| DS-1-92 | done | `structural/odot/drip_strip.py` | `Notebooks/res/DS-1-92.py` | 10 (`test_odot_drip_strip.py`) |
| PCB-91 | done | `structural/odot/portable_barrier.py` | `Notebooks/res/PCB-91.py` | 9 (`test_odot_portable_barrier.py`) |
| AS-2-15 | done | `structural/odot/sleeper_slab.py` | `Notebooks/res/AS-2-15.py` | 9 (`test_odot_sleeper_slab.py`) |
| HW-2.1 | done | `structural/odot/headwall.py` | `Notebooks/res/HW-2.1.py` | 10 (`test_odot_headwall.py`) + table tests in `test_odot_rocker_headwall.py` |
| HW-2.2 | done (circular) | `structural/odot/headwall.py` (`concrete=True`) | `Notebooks/res/HW-2.1.py` (`concrete` toggle) | shared with HW-2.1; elliptical table cataloged, not drawn |
| HW-1.1 | done | `structural/odot/full_height_headwall.py` | `Notebooks/res/HW-1.1.py` | 11 (`test_odot_full_height_headwall.py`) |
| BCHW | done (wingwall/foreslope wall) | `structural/odot/box_culvert_headwall.py` | `Notebooks/res/BCHW.py` | 11 (`test_odot_box_culvert_headwall.py`) |
| SBR-1-20, SBR-3-20, BR-1-13, SBR-2-20, TST-1-99, TST-2-21, DBR-2-73, DBR-3-11, TBR-1-11 | done | `structural/odot/bridge_railing.py` (catalog, pre-existing) | `structural/rhino_barrier.py` `build_barriers()` (shared pipeline, not per-SCD scripts) | covered by `test_rhino_barrier.py` + `test_odot_bridge_railing.py` |
| BR-2-15 | done (bugfix) | `structural/odot/bridge_railing.py` (added `base_width`, `rail_height_above_in`) + `structural/rhino_barrier.py` (new `"combination"` shape family) | `build_barriers()` | `test_rhino_barrier.py::test_combination_*` (2 new tests) |
| SB-1-24 | done | `structural/odot/slab_bridge.py` | `Notebooks/res/SB-1-24.py` | 14 (`test_odot_slab_bridge.py`) |
| CPA-1-08 | done | `structural/odot/capped_pile_abutment.py` | `Notebooks/res/CPA-1-08.py` | 16 (`test_odot_capped_pile_abutment.py`) |
| CPP-1-08 | done | `structural/odot/capped_pile_pier.py` | `Notebooks/res/CPP-1-08.py` | 11 (`test_odot_capped_pile_pier.py`) |
| CS-1-24 | done | `structural/odot/continuous_slab_bridge.py` | `Notebooks/res/CS-1-24.py` | 17 (`test_odot_continuous_slab_bridge.py`) |
| A-1-20 | done (guidance only) | `structural/odot/typical_abutment.py` | `Notebooks/res/A-1-20.py` | 7 (`test_odot_typical_abutment.py`) |
| RB-1-55 | done | `structural/odot/rocker_bolster.py` (`layout_rocker_bolster`, added) | `Notebooks/res/RB-1-55.py` | 22 total in `test_odot_rocker_headwall.py` (5 new) |
| FB-1-82 | done | `structural/odot/fixed_bearing.py` | `Notebooks/res/FB-1-82.py` | 14 (`test_odot_fixed_bearing.py`) |
| BD-1-11 | done | `structural/odot/box_beam.py` (`layout_load_plate`, added; catalog pre-existing) | `Notebooks/res/BD-1-11.py` | 41 total in `test_odot_box_beam.py` (7 new) |
| EXJ-4-87 | done | `structural/odot/strip_seal_joint.py` | `Notebooks/res/EXJ-4-87.py` | 8 (`test_odot_strip_seal_joint.py`) |
| EXJ-5-93 | done | `structural/odot/strip_seal_joint_box_beam.py` | `Notebooks/res/EXJ-5-93.py` | 8 (`test_odot_strip_seal_joint_box_beam.py`) |
| PSBD-1-25 | done (earlier work) | `structural/odot/box_beam.py` + `box_beam_design.py` | `rhino_box_beam.build_box_beams` (full pipeline, not a single GH script) | shared with box-beam tests |
| PSID-1-13 | done | `structural/odot/ps_i_beam.py` | `Notebooks/res/PSID-1-13.py` | 7 (`test_odot_ps_i_beam.py`) |
| ICD-1-20, ICD-2-18, SICD-1-21, SICD-2-14 | not built (by design) | — | — | end-condition add-ons / guide sheets, not standalone structures |
| VPF-1-24 | done | `structural/odot/vandal_fence.py` | `Notebooks/res/VPF-1-24.py` | 9 (`test_odot_vandal_fence.py`) |
| TVPF-1-18, GSD-1-19, NBS-1-09, WU-1-26 | not built (by design) | — | — | temporary-variant/reference-catalog/notes-only sheets, rated 6-8 |
| RM-4.3, RM-4.5, RM-4.8 | done | `structural/odot/roadway_barrier.py` (Types B, B1, C, C1, D, N) | `Notebooks/res/RM-4.x_RoadwayBarrier.py` | 14 (`test_odot_roadway_barrier.py`, shared) |
| RM-4.9 | done (catalog only, Type E) | `structural/odot/roadway_barrier.py` (Type E; concrete face not dimensioned on sheet, `layout_roadway_barrier` refuses) | — | shared with above |
| RM-4.2 | done | `structural/odot/roadway_portable_barrier.py` (32 in, pin & loop) | `Notebooks/res/RM-4.1_RM-4.2.py` | 8 (`test_odot_roadway_portable_barrier.py`, shared) |
| RM-4.1 | done | `structural/odot/roadway_portable_barrier.py` (50 in, hinge bar + `TRANSITION_50_TO_32`) | `Notebooks/res/RM-4.1_RM-4.2.py` | shared with above |
| BP-5.1 | done | `structural/odot/concrete_curb.py` (13 catalog entries, 19 sheet labels) | `Notebooks/res/BP-5.1.py` | 10 (`test_odot_concrete_curb.py`) |
| PSID-1-13 (extension) | done | `structural/odot/ps_i_beam.py` (13 sections: +7 WF, MT4 flange fix, strand grids, profiles) + `structural/ps_i_beam_pipeline.py` + `structural/rhino_ps_i_bim.py` | `draw_bim_emit.py` (generic driver, no new script) | 30 (`test_odot_ps_i_beam.py` + `test_ps_i_beam_pipeline.py`) + 9 (`test_rhino_ps_i_bim.py`) |
| RM-4.6 | done | `structural/odot/roadway_barrier.py` (`BARRIER_END_SECTIONS`, `layout_barrier_end_section`, Types B/B1/D) | — | 5 (`test_odot_barrier_extensions.py`, shared) |
| RM-4.4 | done | `structural/odot/roadway_barrier.py` (`layout_barrier_transition`: sign support / pier plan-width transitions) | — | 3 (shared) |
| RM-5.2 | done | `structural/odot/bikeway_railing.py` (wood post-and-rail, `layout_bikeway_railing`) | — | 3 (shared) |
| RM-4.7 | done (catalog) | `structural/odot/roadway_portable_barrier.py` (`THRIE_BEAM_PCB_TRANSITIONS`, 3 pairs + hardware) | — | 3 (shared) |
| MGS-3.1, MGS-3.2, MGS-3.3 | done | `structural/odot/guardrail.py` (`BRIDGE_TERMINALS`, `layout_bridge_terminal`) | — | 6 (`test_odot_mgs_terminals.py`, shared) |
| MGS-2.1 (extension) | done | `structural/odot/guardrail.py` (`layout_mgs_run`; parameters pre-existing) | — | 2 (shared) |
| MGS-2.2/2.3/2.4, MGS-4.1/4.2, MGS-6.1 | done (registry notes, proportional) | `structural/odot/guardrail.py` (`MGS_DRAWINGS` notes) | — | 1 (shared) |

## BrIM emit tier (2026-10-03)

The Grasshopper prototypes were deleted (commit `0800b5d`); the sheets below now
emit tagged `EmitObject` records (prisms / cylinders / meshes / polylines with
`bim.*` + `pay.*` user text) through the same `objects_to_3dm` / `objects_to_ifc`
backends as the approach slab and box beams, placed on a support line
(`rhino_scd_substructure.SupportFrame`: alignment + station, skew, offset,
elevation, near / far).  Quantities come from the geometry (concrete cy, pile ft)
or the sheet tables (headwall cy / lb).

| SCD | Emit module | Objects | Pay | Tests |
|---|---|---|---|---|
| CPA-1-08 | `rhino_scd_substructure.capped_pile_abutment_emit` | cap prism, HP12x53 pile cylinders, 1 or 2 wingwall prisms | 511E40000 cy, 507E10000 ft | `test_rhino_scd_substructure.py` |
| CPP-1-08 | `rhino_scd_substructure.capped_pile_pier_emit` | stadium cap prism (centred on the alignment), piles | 511, 507 | same |
| A-1-20 | `rhino_scd_substructure.typical_abutment_emit` | backwall, footing (from -depth up to the seat; the prototype's double-depth footing fixed), wingwalls | 511 | same |
| RB-1-55 | `rhino_scd_bearings.rocker_bolster_emit(kind=rocker\|bolster)` | base plate prism, tapered body mesh, rocker top prism | 516E10000 ea | `test_rhino_scd_bearings.py` |
| FB-1-82 | `rhino_scd_bearings.fixed_bearing_emit` | masonry plate, pin cylinder across the beam, top plate | 516 ea | same |
| BD-1-11 | `rhino_scd_bearings.load_plate_emit` | beveled plate mesh | 513E10220 lb (490 pcf) | same |
| EXJ-4-87 | `rhino_scd_details.strip_seal_joint_emit` | gland polyline, support-angle runs (display) | 516E13000 ft [CONFIRM code] | `test_rhino_scd_details.py` |
| EXJ-5-93 | `rhino_scd_details.box_beam_joint_emit` | gland polyline, beam-gap ticks | 516E13000 ft | same |
| VPF-1-24 | `rhino_scd_details.vandal_fence_emit` | post and rail cylinders | 607E23000 ft [CONFIRM code] | same |
| HW-2.1 / HW-2.2 | `rhino_scd_headwalls.headwall_emit` | side profile swept across the width, pipe cylinder (display) | 511 cy (table) | same |
| HW-1.1 | `rhino_scd_headwalls.full_height_headwall_emit` | centre face + 2 wingwall prisms at t_s, opening circle, rebar schedule marker | 511 cy, 509E00200 lb (table) | same |

Stated assumptions carried in the tags: wingwall thickness 1.5 ft (CPA, A-1-20),
pile length 40 ft default, FB top plate 1 in.  Still GH-only: none - every sheet
in the build log with geometry now emits.  Not built: EXJ-2-81 / EXJ-3-82 /
EXJ-6-17, ICD-1-20 / ICD-2-18 / SICD-1-21 / SICD-2-14, and the notes-only sheets.
