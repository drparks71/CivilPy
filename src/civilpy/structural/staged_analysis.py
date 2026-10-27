#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Stage-by-stage linear solve of a :class:`~civilpy.structural.structural_model.StructuralModel`
following a :class:`~civilpy.structural.construction_sequence.ConstructionSequence`
-- the **fallback** when no MIDAS Civil NX session is available (or the
sequence exceeds the license's stage count).

What it does
------------
For every stage, in order:

1. the element groups the stage activates join the structure (the hub's
   ``Element.metadata["group"]``, see :meth:`StructuralModel.set_group`);
   the stage's boundary groups add their restraints (``restraint_groups``
   maps a boundary-group name to node ids; restraints with no group are
   present from the first stage);
2. the stage's **increment** of load is assembled: the load groups it
   applies (nodal loads, beam loads, body forces carrying that ``group``),
   the self weight of the elements activated *now* (for every body-force
   group already on), the negated load groups it removes, the forces the
   deactivated elements were carrying (released back into the structure,
   ``redistribution_pct`` of them) and the reactions of removed supports
   (applied as loads, so the structure takes them over);
3. that increment is solved on the structure **as it stands at this stage**
   (:func:`civilpy.structural.frame_analysis.solve` on a sub-model) and
   added to the running totals.

What it does not do: creep, shrinkage, concrete age (every element is
linear-elastic with its final properties), geometric nonlinearity, cables.
The results are therefore labelled approximate; use them for erection-order
checks, lock-in of statically indeterminate configurations (a prop removed, a
splice made under load) and as a sanity check of the MIDAS run -- not in
place of it.

Sign conventions follow :mod:`civilpy.structural.frame_analysis`:
``Result.end_forces`` are forces on the element at its i then j end in local
axes; ``Result.element_forces`` the axial force (tension positive).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

import numpy as np

from civilpy.structural import frame_analysis as fa
from civilpy.structural.structural_model import (BeamLoad, BodyForce, Element, Load, LoadCase, Result,
                                                 RigidLink, StructuralModel)

__all__ = ["StageResult", "StagedResults", "staged_solve"]


@dataclass
class StageResult:
    """One stage: the loads applied in it and the structure's response."""
    stage: str
    increment: Result
    cumulative: Result
    active_elements: list[str]
    active_restraints: list[str]
    #: element ids removed in this stage (their forces redistributed)
    removed_elements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class StagedResults:
    """All stages; ``approximate`` is always True for this solver."""
    stages: list[StageResult]
    approximate: bool = True

    def final(self) -> Result:
        return self.stages[-1].cumulative

    def by_stage(self) -> dict[str, StageResult]:
        return {s.stage: s for s in self.stages}

    def element_history(self, element_id: str) -> list[tuple[str, tuple[float, ...] | None]]:
        """``[(stage, cumulative end forces or None before activation)]``."""
        return [(s.stage, s.cumulative.end_forces.get(element_id)) for s in self.stages]


# --------------------------------------------------------------------------- helpers
def _add_result(total: Result, inc: Result) -> None:
    for k, v in inc.end_forces.items():
        if k in total.end_forces:
            total.end_forces[k] = tuple(a + b for a, b in zip(total.end_forces[k], v))
        else:
            total.end_forces[k] = tuple(v)
        total.element_forces[k] = -total.end_forces[k][0]
    for k, v in inc.displacements.items():
        if k in total.displacements:
            total.displacements[k] = tuple(a + b for a, b in zip(total.displacements[k], v))
        else:
            total.displacements[k] = tuple(v)
    for k, v in inc.reactions.items():
        if k in total.reactions:
            total.reactions[k] = tuple(a + b for a, b in zip(total.reactions[k], v))
        else:
            total.reactions[k] = tuple(v)


def _global_end_forces(model: StructuralModel, e: Element, local: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Local (i, j) end-force 6-vectors -> global 6-vectors at the i and j nodes."""
    pi, pj = model.nodes[e.node_a].coords, model.nodes[e.node_b].coords
    rot = fa.local_axes(pi, pj, e.beta_deg)          # rows = local axes in global components
    f = np.asarray(local, float)
    out = []
    for k in (0, 6):
        force = rot.T @ f[k:k + 3]
        moment = rot.T @ f[k + 3:k + 6]
        out.append(np.r_[force, moment])
    return out[0], out[1]


def _element_self_weight(model: StructuralModel, e: Element, bf: BodyForce) -> np.ndarray:
    """Global uniform load vector (force / length) of ``e`` under body force ``bf``."""
    sec, mat = fa._resolve(model, e)
    return np.array([bf.gx, bf.gy, bf.gz]) * mat.density * sec.area


# --------------------------------------------------------------------------- the solver
def staged_solve(model: StructuralModel, sequence, *,
                 restraint_groups: Mapping[str, Iterable[str]] | None = None,
                 store: bool = False) -> StagedResults:
    """Solve ``model`` stage by stage along ``sequence`` (a
    :class:`~civilpy.structural.construction_sequence.ConstructionSequence`).

    ``restraint_groups`` = ``{boundary group: node ids}`` for the restraints a
    stage switches on (``Stage.boundaries``) or off (``Stage.remove_boundaries``);
    restrained nodes in no group are supports from the start.  Elements with
    no group are present from the first stage too (and noted).  Rigid links
    join when both their nodes are active.  With ``store`` the cumulative
    result of every stage is written to ``model.results["stage:<name>"]``."""
    groups = model.element_groups()
    grouped = {eid for ids in groups.values() for eid in ids}
    ungrouped = [eid for eid in model.elements if eid not in grouped]
    rgroups = {k: set(v) for k, v in (restraint_groups or {}).items()}
    grouped_nodes = {n for ids in rgroups.values() for n in ids}
    base_restraints = [n for n in model.restraints if n not in grouped_nodes]
    missing_r = [g for s in sequence.stages for g in [b.group for b in s.boundaries] + list(s.remove_boundaries)
                 if g not in rgroups]
    missing_e = [a.group for s in sequence.stages for a in s.activate if a.group not in groups]
    notes_global = []
    if ungrouped:
        notes_global.append(f"{len(ungrouped)} ungrouped elements present from the first stage")
    if missing_r:
        notes_global.append(f"boundary groups without restraint_groups entry (ignored): {sorted(set(missing_r))}")
    if missing_e:
        notes_global.append(f"element groups not in the model (ignored): {sorted(set(missing_e))}")

    active_e: list[str] = list(ungrouped)
    active_r: list[str] = list(base_restraints)
    active_load_groups: list[str] = []
    total = Result(case="staged")
    out: list[StageResult] = []
    for stage in sequence.stages:
        notes = list(notes_global) if not out else []
        case = f"stage:{stage.name}"
        new_e = [eid for a in stage.activate for eid in groups.get(a.group, [])]
        removed = [eid for d in stage.deactivate for eid in groups.get(d.group, [])]
        redist = {eid: d.redistribution_pct / 100.0 for d in stage.deactivate for eid in groups.get(d.group, [])}
        new_r = [n for b in stage.boundaries for n in rgroups.get(b.group, ()) if n in model.restraints]
        gone_r = [n for g in stage.remove_boundaries for n in rgroups.get(g, ()) if n in model.restraints]
        new_lg = [ld.group for ld in stage.loads]
        gone_lg = [ld.group for ld in stage.remove_loads]

        # the structure at this stage
        active_e = [e for e in active_e if e not in removed] + new_e
        active_r = [n for n in active_r if n not in gone_r] + new_r
        active_set = set(active_e)
        active_nodes = {n for eid in active_e for n in model.elements[eid].nodes}
        sub = StructuralModel(units=model.units)
        sub.section_properties = dict(model.section_properties)
        sub.material_properties = dict(model.material_properties)
        for nid in active_nodes:
            n = model.nodes[nid]
            sub.nodes[nid] = replace(n)
        for eid in active_e:
            e = model.elements[eid]
            sub.elements[eid] = replace(e, metadata=dict(e.metadata), nodes=list(e.nodes))
        for nid in active_r:
            if nid in active_nodes:
                sub.restraints[nid] = replace(model.restraints[nid])
        for link in model.rigid_links:
            if link.master in active_nodes and all(s in active_nodes for s in link.slaves):
                sub.rigid_links.append(RigidLink(link.master, list(link.slaves), link.dof))

        # the increment of load
        for g in new_lg:
            if g in active_load_groups:
                notes.append(f"load group {g!r} already applied; skipped")
                continue
            active_load_groups.append(g)
        for ld in model.loads:
            sign = (1.0 if ld.group in new_lg else -1.0 if ld.group in gone_lg else 0.0)
            if sign and ld.node_id in active_nodes:
                sub.loads.append(Load(ld.node_id, sign * ld.fx, sign * ld.fy, sign * ld.fz, sign * ld.mx,
                                      sign * ld.my, sign * ld.mz, case=case))
            elif sign:
                notes.append(f"load on inactive node {ld.node_id} in group {ld.group!r} dropped")
        for bl in model.beam_loads:
            sign = (1.0 if bl.group in new_lg else -1.0 if bl.group in gone_lg else 0.0)
            if sign and bl.element_id in active_set:
                w_end = bl.w_end if bl.w_end is not None else bl.w_start
                sub.beam_loads.append(BeamLoad(bl.element_id, sign * bl.w_start, sign * w_end, case=case,
                                               direction=bl.direction, start=bl.start, end=bl.end, kind=bl.kind))
            elif sign:
                notes.append(f"beam load on inactive element {bl.element_id} in group {bl.group!r} dropped")
        # self weight: body-force groups switched on now load every active element; groups already on
        # load only the elements activated now
        for bf in model.body_forces:
            if bf.group in new_lg:
                targets = active_e
            elif bf.group in active_load_groups and bf.group not in gone_lg:
                targets = new_e
            elif bf.group in gone_lg:
                targets = []
                notes.append(f"body force group {bf.group!r} removed: self weight is not un-applied")
            else:
                continue
            for eid in targets:
                q = _element_self_weight(model, model.elements[eid], bf)
                for axis, comp in zip("XYZ", q):
                    if abs(comp) > 0:
                        sub.beam_loads.append(BeamLoad(eid, float(comp), None, case=case, direction=f"G{axis}"))
        for g in gone_lg:
            if g in active_load_groups:
                active_load_groups.remove(g)
        # forces released by removed elements and supports
        for eid in removed:
            if eid in total.end_forces:
                fi, fj = _global_end_forces(model, model.elements[eid], total.end_forces[eid])
                e = model.elements[eid]
                for nid, f in ((e.node_a, fi), (e.node_b, fj)):
                    if nid in active_nodes:
                        r = redist.get(eid, 1.0)
                        sub.loads.append(Load(nid, *(r * f).tolist(), case=case))
                total.end_forces.pop(eid, None)
                total.element_forces.pop(eid, None)
        for nid in gone_r:                      # the support's reaction is withdrawn: load the structure with -R
            if nid in total.reactions and nid in active_nodes:
                R = total.reactions[nid]
                sub.loads.append(Load(nid, *[-float(v) for v in R], case=case))
                total.reactions.pop(nid, None)
        if case not in sub.load_cases:
            sub.load_cases[case] = LoadCase(name=case)
        # solve the increment on the current structure
        if sub.elements:
            try:
                inc = fa.solve(sub, [case], store=False)[case]
            except KeyError as exc:
                raise KeyError(f"stage {stage.name!r}: {exc}") from exc
        else:
            inc = Result(case=case)
        # nodes that appear now start from zero displacement: nothing to adjust, the
        # increment is already relative to the undeformed position of the new parts
        _add_result(total, inc)
        snap = Result(case=case, element_forces=dict(total.element_forces), reactions=dict(total.reactions),
                      end_forces=dict(total.end_forces), displacements=dict(total.displacements),
                      notes=list(notes))
        out.append(StageResult(stage.name, inc, snap, list(active_e), list(active_r), removed, notes))
        if store:
            model.results[case] = snap
    return StagedResults(out)
