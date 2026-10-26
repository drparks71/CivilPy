# SNBI Validation — FHWA gap closure roadmap

Tracks bringing `civilpy.state.ohio.snbi` into agreement with FHWA's own SNBI
processing report. Baseline = FHWA `FinalProcessingReport_OH_JSON_…` (report
date **5/6/2026**), *Validation Summary* sheet: **68 distinct items / 8,301
findings**, typed Safety / Error / Flag.

## Why we currently disagree

A 6-30-2026 `validate_snbi` run (post-0.3.1) agrees with FHWA on only **~8 of 68
items (~12%)**. Two root causes, in order of impact:

1. **Requiredness.** The model makes nearly every item `Optional`, and every
   helper (`_require_in`, `_require_code`, …) returns early on `None`. So
   FHWA's "*X is null or not valid*" Errors — the majority of findings — never
   raise. The module docstring already states the *intent* that
   "must be reported for all bridges" items are required; the implementation
   just didn't carry it through. Closing this is the single biggest lever.
2. **Dead enum tables.** `_SNBI_CODES` / `_PATTERN_CODES` (added on this branch)
   are defined but **never wired to a field**, so coded-value checks for ~20
   items don't run. Wiring them is safe and is this branch's stated purpose.

> Headline caveat: the single largest line (BIR02, 2085) is a **Flag** advisory
> ("don't report Fatigue Details on non-steel bridges"), not an Error — low
> priority despite the count.

## Action categories

Legend: ☐ todo · ☑ done · `freq` = FHWA finding count · `T` = Safety/Error/Flag

### A. Wire existing enum / pattern tables — ✅ DONE (this branch)
Catches *invalid present* values. Tables already existed on this branch but
were never wired to a field; now connected via `_require_code` /
`_require_pattern_code` / `_require_multi_code`. (Still skips `None` — null
flagging is section B.) Fixtures using lenient shorthand (`BF01="H"`,
`BSP01="M"`, `BCL01="1"`, `BPS01="A"`, `BSB01="A1"`) updated to real codes.

- ☑ BSP12 (390, E) Deck Reinforcing Protective System
- ☑ BSP09 (58, E)  Deck Material and Type
- ☑ BSP06 (17, E)  Span Type
- ☑ BSP04 (12, E)  Span Material
- ☑ BRT03 (71, E)  Route Direction
- ☑ BAP05 (111, E) Seismic Vulnerability
- ☑ BAP03 (22, E)  Scour Vulnerability
- ☑ BLR04 (13, E)  Load Rating Method
- ☑ BF02 (7, E)    Feature Location
- ☑ BIR01 (159, E) NSTM Inspection Required — added to Y/N set
- ☑ BIR03 (65, E)  Underwater Inspection Required — added to Y/N set
- ☑ BCL03 (28, E)  Federal/Tribal Land Access — `_require_multi_code`
- ☑ (no FHWA hits, wired for completeness) BSP07/08/10/11/13, BSB03-07,
  BG12, BH01, BRR01, BLR01/02, BIE01, BEP03, BPS01, BCL01/02, and patterns
  BF01 / BSP01 / BSB01

> ⚠️ Verification owed: a fresh `validate_snbi` run + re-compare vs FHWA, to
> confirm wiring closes the targeted "not valid" findings **without** adding
> false positives on items FHWA passed (e.g. if `_AGENCY`/span tables are
> narrower than FHWA's). Couldn't run here (needs warehouse DB access).

### B. Make required ("must be reported for all bridges" → flag null)
**Decision: Option A** — make unconditional items required in the base model.

**B1 — Unconditional, Bridge-level — ✅ DONE** (flipped Optional→required):
- ☑ BG06 (1232, E) Curb-to-Curb width — required **and** `> 0`
- ☑ BG07 (63) / BG08 (62) curb/sidewalk width
- ☑ BG03 (5, `>0`) Max Span Length
- ☑ BG10 (4) Median · BG11 (8) Skew · BG14 (19) Sidehill
- ☑ BAP01 (71) · BAP02 (63) · BAP03 (22) · BAP05 (111) appraisal
- ☑ BCL03 (28) Land Access · BCL04 (9) Historic · BCL05 (33) Toll
- ☑ BIR01 (159) NSTM req'd · BIR03 (65) Underwater req'd

**B2 — Conditional requiredness via model_validators.** These live on child
models / apply only in context (forcing plain-required would reject
inapplicable records, e.g. a waterway feature has no `BH*`).
- ☑ BH06 (147) · BH09 (98) · BH11 (95) · BH13 (95) · BH17 (122) — required on
  **highway features** (BF01 starts "H"), via `Feature._feature_type_conditionals`
- ☑ BRT02 (83) / BRT03 (71) / BRT04 (18) / BRT05 (18) — required per `Route`
- ☑ BSP02 (67) / BSP04 (12) / BSP05 (17) / BSP06 (17) — required per `SpanSet`;
  BSP09 (58) / BSP12 (390) required for non-pipe-culvert spans (have a deck)
- ☐ BLR05 (26) / BLR06 (26) rating factors — when load-rated *(TODO)*
- ☐ BF03 (80) Feature Name · BE03 (3) Element total · BIE05 (1) interval ·
  BL03 (2) Place · BL07 (25) border *(TODO — lower freq)*

### C. Numeric format (one decimal place) — ✅ DONE
Via `_one_decimal` (float can't distinguish 12 from 12.0, so enforces ≤1
fractional digit; rejects 12.55).
- ☑ BG15 (358, E) Irregular Deck Area
- ☑ BH16 (346, E) Highway Maximum Usable Surface Width

### D. Cross-field / conditional rules
- ☑ BEP04 (197, E)  Do not report when BEP03 ∈ {C,S,L,V}
- ☑ BC09 (86, E)     Channel rating: N when no waterway feature, else 0-9
- ☑ BG05 (21, E)     Out-to-out must exceed curb-to-curb (unless sidehill)
- ☑ BH18 (29, E)     Crossing bridge number ≠ BID01
- ☑ BSP03 (8)        Zero beam lines only valid for pipe/slab span (P01/P02)
- ☑ BN02/04/06       Navigation clearances required when BN01 = 'Y'
- ☑ BW02 (11, F)     Year work performed ≥ year built
- ☐ BSP01 (211, E)  Culvert-definition consistency — **deferred** (complex
  semantic rule: coding vs. the full SNBI culvert definition)
- ☐ BW03 (50, F)     Work-performed code consistency — **deferred** (many
  interacting sub-rules)
- ☐ BE01 (10, F) · BC02/03/04 flags (no super/sub/culvert present) —
  **deferred** (needs span material/presence reasoning)
- ☐ BIR02 (2085, F) fatigue details on non-steel — **deferred** (Flag advisory)
- ☐ Border-bridge "do not report" flags — **deferred** (low freq)

### E. Urban code (BH02) — ✅ partial
- ☑ BH02 (899, E) required on highway features + numeric format check. Full
  Census UACE code-table validation **deferred** (table not reproduced here;
  catches the null/format bulk, not "code is not a real UACE").

### F. Done already (FHWA-calculated, must-not-report)
- ☑ BG16, BC12, BC13, BIE06

## Decision record
"Must report for all bridges" enforcement: **Option A — make fields required
in the base model** (chosen 2026-06-30; single-developer library, no external
consumers, so the stricter contract is acceptable and matches FHWA directly).

## Calibration round 1 (0.3.3, against the 6-30-2026 NBIS run)
First real `validate_snbi --nbis` run vs FHWA (28,045 bridges) raised item
coverage 12% → 37% (BOTH 8 → 25) but also over-reported ~5.5×. Per-item ratios
(attributing model-level errors to the items named in their messages) showed
two over-reach patterns, now corrected:

- **Reverted required → optional** (FHWA flags their nulls far less often than
  our API data omits them): BG03, BG07, BG08, BG10, BG11, BIR01, BIR03, BAP01,
  BAP02, BAP03; Route BRT03/04/05; dropped BSP12 from the span deck-required
  set. Kept the items that matched (~1×): BG06, BG14, BAP05, BCL03/04/05, the
  highway `BH*` set, BN02/04/06, BSP02/04/05/06/09.
- **Dropped enum checks that rejected valid Ohio codes** (FHWA flagged 0):
  BCL01/BCL02 owner/maint, BF01 pattern, BEP03, BSP07/08/10/11/13, BSB05/06/07.
- **Relaxed** BG05 > BG06 to BG05 ≥ BG06 (equal allowed; FHWA flagged 21 vs our
  1,627).

> Caveat (per the data owner): AssetWise's "export FHWA data" feed is what FHWA
> validated, and it can differ from our REST API read — so some residual
> over/under counts (e.g. BG02/BG09 required-but-FHWA-0, BRT01 "highway has no
> route") may be **data-source** differences, not rule bugs. Confirm against the
> export before tightening/loosening those further.

## Calibration round 2 (0.3.4, against the 7-1-2026 NBIS run)
First run against the **local** DB (full 46,355-bridge AssetWise `--snbi-only`
sync; 28,045 NBIS). Started at 22,534 errors (5.5× FHWA's 8,301) and dialled
down to **5,929 (0.71×)** by removing the pathological over-reporters — each one
an item FHWA's own report flags **0 times** while our REST read trips it in bulk
(the "export FHWA data" feed carries data the API read omits). Attributing
model-level errors to the items named in their messages, per-item ratios landed
in the FHWA band (BH02 0.8×, BH06 0.5×, BH09/11 1.4×, BAP05 1.2×, BSP02 1.1×).

Principle applied: **strip only rules FHWA does not enforce at all (FHWA = 0);
keep rules FHWA enforces even when our pull over-triggers them on missing data.**

- **BRT01 highway-route requirement dropped (7,358 → 0).** SNBI makes a Route
  dataset critical for every highway feature, but FHWA flags it 0×; ~7,300
  highway features come back from the API with neither their Route nor their
  `BH*` detail block. The `BH*` requiredness is now gated on the feature having a
  Route (i.e. having actually been retrieved), so it no longer re-reports the one
  data-source gap thousands of times across BH02/06/09/11/13/16/17.
- **2026-10-26 (location gate).** Once the routes under the bridges were fully
  synced, the highway sub-item rule fired on ~1,200 under-features per item that
  FHWA never flags. FHWA's OH report (ODOT-owned rows, carried vs under): BH02
  544/8, BH06 90/0, BH09 48/0, BH11 42/0, BH13 44/0, BH17 70/0, **BH16 54/222**.
  So BH02/06/09/11/13/17 are now required only on carried features (B.F.02 C, T,
  L); BH16 stays required on every highway feature.
- **BAP03 enum accepts "N" (5,999 → 0).** Ohio codes Scour Vulnerability "N"
  (not applicable); FHWA accepts it (BAP05 already allowed "N").
- **BG05 out-to-out → optional (1,624 → 0).** FHWA flags BG05 only via the
  cross-field out-to-out ≥ curb-to-curb rule (21×), never for nulls, unlike BG06
  curb-to-curb (kept required — FHWA *does* flag its nulls, 1,232×).
- **BCL01/BCL02, BG02, BG09 → optional** (owner/maint, total length, approach
  width): all FHWA = 0 on nulls; data-source omissions.

Kept despite >1.5× (FHWA enforces them; the excess is our data gap, not a rule
bug): BG06 (1.6×), BH13 (2.2×), BCL04/BCL05 toll/historic, BRT03/05.

### Finding: BRT01 is a field-mapping bug, not a rule bug
The 417 residual BRT01 errors are 281× the literal string `"Unknown"` (over the
3-char max) plus route *numbers* (`270`, `71`, `480`) failing "must begin with
R". That means our AssetWise→SNBI mapping is loading the route **number** into
BRT01 **Route Designation**. This is the long-suspected Route-mapping gap —
fix the mapping in `snbi_ui`, do **not** loosen the rule to swallow it.

## Still owed
- **snbi_ui:** fix the BRT01 Route Designation field mapping (see finding above).
- **civilpy:** the remaining FHWA MISSes are unimplemented/deferred rules, not
  regressions — BIR02 (2085, Flag advisory), BG15 (358), BSP01 (211, culvert
  definition), BIR01/03, BC09, BF03, BAP01/02. Revisit section-D deferrals when
  chasing coverage rather than precision.
