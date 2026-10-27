#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Construction sequence for a MIDAS Civil NX construction stage analysis.

One :class:`ConstructionSequence` describes how a bridge is built -- which
element groups, boundary groups and load groups switch on or off in each
stage, how long each stage lasts, and which sections turn composite and
when.  It is the single source for:

* the MIDAS tables (:meth:`ConstructionSequence.to_midas` -> ``BNGR`` /
  ``STAG`` / ``STCT`` / ``CSCS``), where the construction stage analysis
  itself runs (creep, shrinkage, locked-in forces);
* the 4D schedule (:meth:`ConstructionSequence.schedule`,
  :meth:`ConstructionSequence.activation_stage_by_group`) that tags the Rhino
  model.

Nothing here talks to MIDAS; push the tables with
:func:`civilpy.structural.midas_composite_wizard.push` (or
``MidasCivil.put_db``) in ``TABLE_ORDER``, after
:func:`civilpy.state.ohio.DOT.midas_bridge.ensure_base_stage` -- stage writes
are legal in Base Stage only.

Field names and values are the live-verified ones from
:func:`civilpy.structural.midas_composite_wizard.construction_stages` (Civil NX
2025 v2.1).  Two operations the sequence can *describe* have no verified body
yet -- deactivating element groups (``DACT_ELEM``) and boundary groups
(``DACT_BNGR``) -- so :meth:`Stage.to_midas` refuses them rather than guess:
read the rows back off a live model first and add them here with the source.

License: a Civil NX **Plus** license refuses a model with more than
:data:`PLUS_LICENSE_STAGE_LIMIT` construction stages
(:class:`~civilpy.structural.midas.MidasLicenseError`), so
:meth:`ConstructionSequence.problems` checks the count before anything is
sent.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

#: Construction stages a Civil NX Plus license accepts.
PLUS_LICENSE_STAGE_LIMIT = 10

#: Values MIDAS accepts for the verified fields.
BOUNDARY_POSITIONS = ("ORIGINAL", "DEFORMED")
LOAD_DAYS = ("FIRST", "LAST")
COMPOSITE_PART_KINDS = ("ELEM", "MATL")

#: ``STCT`` row as the wizard writes it (time-dependent effects on, creep and
#: shrinkage, 5 creep iterations at 1 %, strength variation).  The fields
#: :class:`AnalysisControl` owns are overwritten; ``overrides`` can set any
#: other one.
_STCT_BASE = {"bLAST_FINAL": True, "FINAL_STAGE": "", "iINC_NLA": 0, "iNLA_TYPE": 1, "bINC_PDL": False,
              "bINC_TDE": True, "bCNS": True, "TYPE": "BOTH", "iITER_CR": 5, "TOL_CR": 0.01, "bOUCC": False,
              "bITS": False, "iITS": 2, "bATS": True, "iT10": 2, "iT100": 5, "iT1K": 7, "iT5K": 10, "iT10K": 20,
              "bTTLE_CS": False, "bRCE": False, "bVAR": True, "bAPPLY_ELA": False, "bTTLE_ES": False, "iTTLE_ES": 0,
              "vEREC": [], "CPFC": "INTERNAL", "bEXT_REPL": False, "bCONV": False, "bTRUSS": False, "bBEAM": False,
              "bCHANGE_CABLE": False, "bAPPLY_IMF": False, "bITD": False, "ITD": "ALL", "bLFFC": False,
              "bCAMBER": False, "bSD": False, "iSDOPT": 0, "SDCONST": 0, "iBSC": 0,
              "bCALC_CFF": False, "bCALC_CSP": True, "bSELFCONS": False, "bSAVE_OCS": False}


class SequenceError(ValueError):
    """A sequence MIDAS would refuse or solve wrongly; ``problems`` lists
    every one found, not just the first."""

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("construction sequence is invalid:\n  - " + "\n  - ".join(self.problems))


# ------------------------------------------------------------------ stage parts
@dataclass(frozen=True)
class ElementActivation:
    """Element group switched on; ``age`` (days) is the concrete age at
    activation (0 for steel)."""
    group: str
    age: float = 0.0


@dataclass(frozen=True)
class ElementDeactivation:
    """Element group switched off (shoring, falsework, temporary bracing).
    ``redistribution_pct`` of its internal forces goes back into the
    structure.  No verified MIDAS body yet -- see the module docstring."""
    group: str
    redistribution_pct: float = 100.0


@dataclass(frozen=True)
class BoundaryActivation:
    """Boundary group switched on.  ``"DEFORMED"`` attaches it where the
    structure already sits (bearings under erected steel); ``"ORIGINAL"`` at
    the undeformed geometry (substructure supports)."""
    group: str
    position: str = "DEFORMED"


@dataclass(frozen=True)
class LoadActivation:
    """Load group applied (or, in ``Stage.remove_loads``, removed) on the
    ``"FIRST"`` or ``"LAST"`` day of the stage."""
    group: str
    day: str = "FIRST"


@dataclass
class Stage:
    """One construction stage.  ``duration`` in days (0 is legal: an
    instantaneous change such as wet deck turning composite)."""
    name: str
    duration: float
    activate: list[ElementActivation] = field(default_factory=list)
    deactivate: list[ElementDeactivation] = field(default_factory=list)
    boundaries: list[BoundaryActivation] = field(default_factory=list)
    remove_boundaries: list[str] = field(default_factory=list)
    loads: list[LoadActivation] = field(default_factory=list)
    remove_loads: list[LoadActivation] = field(default_factory=list)
    save_results: bool = True
    save_steps: bool = False
    #: Free text for the schedule / Rhino tags ("Pour 2: span 2 positive").
    note: str = ""

    def to_midas(self) -> dict:
        """The ``STAG`` row.  Empty activation lists are left out, as the
        wizard does."""
        unverified = [k for k, v in (("DACT_ELEM", self.deactivate), ("DACT_BNGR", self.remove_boundaries)) if v]
        if unverified:
            raise NotImplementedError(
                f"stage {self.name!r}: {' / '.join(unverified)} has no verified MIDAS body yet -- read one back "
                f"off a live model (GET /db/STAG) and add it to construction_sequence with the source")
        row = {"NAME": self.name, "DURATION": self.duration, "bSV_RSLT": self.save_results,
               "bSV_STEP": self.save_steps, "ADD_STEP": []}
        if self.activate:
            row["ACT_ELEM"] = [{"GRUP_NAME": a.group, "AGE": a.age} for a in self.activate]
        if self.boundaries:
            row["ACT_BNGR"] = [{"BNGR_NAME": b.group, "POS": b.position} for b in self.boundaries]
        if self.loads:
            row["ACT_LOAD"] = [{"LOAD_NAME": ld.group, "DAY": ld.day} for ld in self.loads]
        if self.remove_loads:
            row["DACT_LOAD"] = [{"LOAD_NAME": ld.group, "DAY": ld.day} for ld in self.remove_loads]
        return row


# ------------------------------------------------------------ composite sections
@dataclass(frozen=True)
class CompositePart:
    """One part of a composite section for construction stage.

    ``kind="ELEM"`` takes the material and age of the elements themselves
    (the steel girder); ``kind="MATL"`` names a material (``material`` id as
    a string) that joins in ``composite_stage`` at ``age`` days (the deck).
    ``h`` and ``vs`` are the notional size and volume/surface ratio in the
    model length unit; MIDAS refuses 0.
    """
    part: int
    kind: str
    age: float
    h: float
    vs: float
    material: str = ""
    composite_stage: str = ""

    def to_midas(self) -> dict:
        return {"PART": self.part, "MTYPE": self.kind, "MAT": self.material, "CSTAGE": self.composite_stage,
                "AGE": self.age, "PARTINFO_H": self.h, "PARTINFO_VS": self.vs}


@dataclass
class CompositeSection:
    """``CSCS`` row: section ``section`` is active from ``activation_stage``
    and becomes composite part by part."""
    section: int
    activation_stage: str
    parts: list[CompositePart]
    type: str = "NORMAL"
    tapered: bool = False

    def to_midas(self) -> dict:
        return {"SEC": self.section, "ASTAGE": self.activation_stage, "TYPE": self.type, "bTAP": self.tapered,
                "vPARTINFO": [p.to_midas() for p in self.parts]}


# -------------------------------------------------------------- analysis control
@dataclass(frozen=True)
class ErectionLoad:
    """Maps the load cases applied during erection to a result case
    (``"Erection Load 1"`` -> ``"DC"``)."""
    load_type: str
    erection_case: str
    load_cases: tuple[str, ...]


@dataclass
class AnalysisControl:
    """``STCT``: what the construction stage analysis includes.
    ``final_stage=None`` means the last stage."""
    final_stage: str | None = None
    time_dependent: bool = True
    creep_iterations: int = 5
    creep_tolerance: float = 0.01
    erection_loads: list[ErectionLoad] = field(default_factory=list)
    overrides: dict = field(default_factory=dict)

    def to_midas(self, last_stage: str) -> dict:
        row = copy.deepcopy(_STCT_BASE)
        final = self.final_stage or last_stage
        row.update({"bLAST_FINAL": final == last_stage, "FINAL_STAGE": final, "bINC_TDE": self.time_dependent,
                    "iITER_CR": self.creep_iterations, "TOL_CR": self.creep_tolerance,
                    "vEREC": [{"LTYPECC": e.load_type, "EREC": e.erection_case, "vLCNAME": list(e.load_cases)}
                              for e in self.erection_loads]})
        row.update(self.overrides)
        return row


# ---------------------------------------------------------------------- schedule
@dataclass(frozen=True)
class StageWindow:
    """When a stage runs: days from the start of construction, and calendar
    dates when the sequence has a ``start_date``."""
    name: str
    start_day: float
    finish_day: float
    start_date: date | None = None
    finish_date: date | None = None


# ---------------------------------------------------------------------- sequence
@dataclass
class ConstructionSequence:
    """Stages in order, the boundary groups they use, the composite sections
    and the analysis control.

    ``boundary_groups`` become the ``BNGR`` table; every boundary group a
    stage activates must be listed (and the supports / links must carry that
    group name in ``CONS`` / ``ELNK`` / ``RIGD``).  ``max_stages`` defaults to
    the Plus license limit.
    """
    stages: list[Stage]
    boundary_groups: list[str] = field(default_factory=list)
    composite_sections: list[CompositeSection] = field(default_factory=list)
    control: AnalysisControl = field(default_factory=AnalysisControl)
    start_date: date | None = None
    max_stages: int = PLUS_LICENSE_STAGE_LIMIT

    # ---------------------------------------------------------------- checks
    def problems(self, *, element_groups: Iterable[str] | None = None,
                 load_groups: Iterable[str] | None = None) -> list[str]:
        """Everything wrong with the sequence.  Pass the model's
        ``element_groups`` (GRUP names) and ``load_groups`` (LDGR / STLD
        names) to also check that every name a stage uses exists."""
        out: list[str] = []
        if not self.stages:
            return ["no stages"]
        names = [s.name for s in self.stages]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            out.append(f"duplicate stage names: {dupes}")
        if len(self.stages) > self.max_stages:
            out.append(f"{len(self.stages)} stages exceeds the license limit of {self.max_stages} "
                       f"(Civil NX Plus allows {PLUS_LICENSE_STAGE_LIMIT})")
        known_elem = set(element_groups) if element_groups is not None else None
        known_load = set(load_groups) if load_groups is not None else None
        bngr = set(self.boundary_groups)
        if len(bngr) != len(self.boundary_groups):
            out.append("duplicate boundary group names")

        active_elem: set[str] = set()
        active_load: set[str] = set()
        active_bngr: set[str] = set()
        for s in self.stages:
            where = f"stage {s.name!r}"
            if s.duration < 0:
                out.append(f"{where}: negative duration {s.duration}")
            for a in s.activate:
                if a.age < 0:
                    out.append(f"{where}: element group {a.group!r} has negative age {a.age}")
                if a.group in active_elem:
                    out.append(f"{where}: element group {a.group!r} is already active")
                if known_elem is not None and a.group not in known_elem:
                    out.append(f"{where}: element group {a.group!r} is not in the model")
                active_elem.add(a.group)
            for d in s.deactivate:
                if d.group not in active_elem:
                    out.append(f"{where}: element group {d.group!r} deactivated but not active")
                if not 0 <= d.redistribution_pct <= 100:
                    out.append(f"{where}: redistribution {d.redistribution_pct} % outside 0-100")
                active_elem.discard(d.group)
            for b in s.boundaries:
                if b.position not in BOUNDARY_POSITIONS:
                    out.append(f"{where}: boundary position {b.position!r} not in {BOUNDARY_POSITIONS}")
                if b.group not in bngr:
                    out.append(f"{where}: boundary group {b.group!r} is not in boundary_groups {sorted(bngr)}")
                if b.group in active_bngr:
                    out.append(f"{where}: boundary group {b.group!r} is already active")
                active_bngr.add(b.group)
            for g in s.remove_boundaries:
                if g not in active_bngr:
                    out.append(f"{where}: boundary group {g!r} removed but not active")
                active_bngr.discard(g)
            for ld in s.loads:
                if ld.day not in LOAD_DAYS:
                    out.append(f"{where}: load day {ld.day!r} not in {LOAD_DAYS}")
                if ld.group in active_load:
                    out.append(f"{where}: load group {ld.group!r} is already applied")
                if known_load is not None and ld.group not in known_load:
                    out.append(f"{where}: load group {ld.group!r} is not in the model")
                active_load.add(ld.group)
            for ld in s.remove_loads:
                if ld.day not in LOAD_DAYS:
                    out.append(f"{where}: load day {ld.day!r} not in {LOAD_DAYS}")
                if ld.group not in active_load:
                    out.append(f"{where}: load group {ld.group!r} removed but not applied")
                active_load.discard(ld.group)

        order = {n: i for i, n in enumerate(names)}
        sects = [c.section for c in self.composite_sections]
        if len(set(sects)) != len(sects):
            out.append(f"composite sections listed twice: {sorted({x for x in sects if sects.count(x) > 1})}")
        for c in self.composite_sections:
            where = f"composite section {c.section}"
            if c.activation_stage not in order:
                out.append(f"{where}: activation stage {c.activation_stage!r} is not a stage")
            for p in c.parts:
                if p.kind not in COMPOSITE_PART_KINDS:
                    out.append(f"{where} part {p.part}: kind {p.kind!r} not in {COMPOSITE_PART_KINDS}")
                if p.h <= 0 or p.vs <= 0:
                    out.append(f"{where} part {p.part}: h and v/s must be > 0 (MIDAS refuses 0)")
                if p.composite_stage:
                    if p.composite_stage not in order:
                        out.append(f"{where} part {p.part}: composite stage {p.composite_stage!r} is not a stage")
                    elif c.activation_stage in order and order[p.composite_stage] < order[c.activation_stage]:
                        out.append(f"{where} part {p.part}: composite stage {p.composite_stage!r} comes before "
                                   f"the section is active ({c.activation_stage!r})")
        if self.control.final_stage is not None and self.control.final_stage not in order:
            out.append(f"final stage {self.control.final_stage!r} is not a stage")
        return out

    def validate(self, **groups) -> ConstructionSequence:
        """Raise :class:`SequenceError` listing every problem; returns
        ``self`` so it chains."""
        found = self.problems(**groups)
        if found:
            raise SequenceError(found)
        return self

    # -------------------------------------------------------------- outputs
    def to_midas(self, *, validate: bool = True) -> dict:
        """``{"BNGR", "STAG", "STCT"[, "CSCS"]}`` assign dictionaries keyed
        ``"1"``, ``"2"``, ...  in stage order."""
        if validate:
            self.validate()
        tables = {
            "BNGR": {str(i): {"NAME": n, "AUTOTYPE": 0} for i, n in enumerate(self.boundary_groups, 1)},
            "STAG": {str(i): s.to_midas() for i, s in enumerate(self.stages, 1)},
            "STCT": {"1": self.control.to_midas(self.stages[-1].name)},
        }
        if self.composite_sections:
            tables["CSCS"] = {str(i): c.to_midas() for i, c in enumerate(self.composite_sections, 1)}
        return tables

    def schedule(self) -> list[StageWindow]:
        """Each stage's start and finish, back to back from day 0."""
        out, t = [], 0.0
        for s in self.stages:
            start, finish = t, t + s.duration
            d0 = d1 = None
            if self.start_date is not None:
                d0 = self.start_date + timedelta(days=start)
                d1 = self.start_date + timedelta(days=finish)
            out.append(StageWindow(s.name, start, finish, d0, d1))
            t = finish
        return out

    def activation_stage_by_group(self) -> dict[str, str]:
        """``{element group: stage it is activated in}`` -- the stage tag for
        every object in that group (Rhino User Text, IFC, 4D)."""
        return {a.group: s.name for s in self.stages for a in s.activate}


# ----------------------------------------------------------------------- presets
@dataclass(frozen=True)
class DeckPour:
    """One deck placement: its wet-concrete load group and the element group
    that carries the hardened deck.  ``days`` until the next pour (or the
    superimposed loads)."""
    name: str
    wet_load_group: str
    deck_group: str
    days: float = 10.0
    age_at_composite: float = 1.0


def deck_pour_sequence(pours: Sequence[DeckPour], *,
                       substructure_groups: Sequence[str] = ("Substructure",),
                       support_group: str = "SubstructureSupport",
                       steel_groups: Sequence[str] = ("Girder", "Bracing"),
                       bearing_groups: Sequence[str] = ("GirderElastic Link", "GirderRigid Link"),
                       self_weight_group: str = "SW",
                       superimposed_load_groups: Sequence[str] = ("DC2", "DW"),
                       substructure_age: float = 28.0,
                       stage_days: float = 10.0,
                       long_term_days: float = 10000.0,
                       split_composite: bool = False,
                       erection_loads: Sequence[ErectionLoad] = (),
                       start_date: date | None = None,
                       max_stages: int = PLUS_LICENSE_STAGE_LIMIT) -> ConstructionSequence:
    """Steel girder bridge: substructure, steel erection, the deck pours in
    the order given, superimposed dead load, long term.

    With ``split_composite=False`` (default, fits a Plus license) each pour
    stage also hardens the previous pour: its deck group activates at
    ``age_at_composite`` and its wet load comes off, the same simultaneous
    change the wizard makes in its 0-day stages -- the wet load of pour *k*
    therefore lands on pours 1..*k*-1 already composite.  The last pour
    hardens in the superimposed-load stage.  Stage count = pours + 4, so up
    to 6 pours on a Plus license.

    ``split_composite=True`` gives every pour its own 0-day "composite" stage
    as the wizard does (results saved for the wet and the hardened state
    separately); stage count = 2 x pours + 4.
    """
    if not pours:
        raise ValueError("at least one deck pour is needed")
    stages = [
        Stage("Substructure", stage_days,
              activate=[ElementActivation(g, substructure_age) for g in substructure_groups],
              boundaries=[BoundaryActivation(support_group, "ORIGINAL")],
              loads=[LoadActivation(self_weight_group)]),
        Stage("Steel erection", stage_days,
              activate=[ElementActivation(g, 0.0) for g in steel_groups],
              boundaries=[BoundaryActivation(g, "DEFORMED") for g in bearing_groups]),
    ]

    def harden(p: DeckPour, stage: Stage) -> None:
        stage.activate.append(ElementActivation(p.deck_group, p.age_at_composite))
        stage.remove_loads.append(LoadActivation(p.wet_load_group))

    previous: DeckPour | None = None
    for p in pours:
        pour = Stage(p.name, p.days, loads=[LoadActivation(p.wet_load_group)], note=f"wet concrete {p.name}")
        if previous is not None and not split_composite:
            harden(previous, pour)
        stages.append(pour)
        if split_composite:
            hard = Stage(f"{p.name} composite", 0.0, note=f"{p.name} composite")
            harden(p, hard)
            stages.append(hard)
        previous = p
    sdl = Stage("Superimposed DL", stage_days, loads=[LoadActivation(g) for g in superimposed_load_groups])
    if not split_composite:
        harden(previous, sdl)
    stages += [sdl, Stage("Long term", long_term_days)]
    return ConstructionSequence(stages, boundary_groups=[support_group, *bearing_groups],
                                control=AnalysisControl(erection_loads=list(erection_loads)),
                                start_date=start_date, max_stages=max_stages)
