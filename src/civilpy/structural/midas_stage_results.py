#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Construction-stage results back from MIDAS Civil NX: the request bodies and
the pure post-processing (locked-in dead-load split, per-stage increments,
camber) that load rating and the constructibility checks need.

The staged analysis itself runs in MIDAS; this module only asks for its
tables (``POST /post/TABLE``) and reads them.

.. warning::
   The construction-stage **request** arguments (``STAGE_STEP`` strings such
   as ``"Stage3-2:001(last)"`` and the ``CS:`` load-case suffixes) follow the
   API manual's result-table article and have **not yet been read back from a
   live model**; :func:`stage_table_argument` marks them with
   ``UNVERIFIED = True`` in its docstring and the first live run should
   confirm them (record the working strings here with the date).  The
   post-processing works on the flattened rows
   (:func:`civilpy.structural.midas.parse_result_table`) and does not depend
   on them.

Dead-load split
---------------
For a steel composite girder the rating needs the permanent load in three
parts (LRFD 6.10.1.1.1, MBE 6A.6.2): **DC1** on the non-composite section
(steel self weight and the wet deck, pour by pour), **DC2** on the long-term
composite section (barriers, railing, sidewalks) and **DW** (wearing surface,
utilities).  A construction stage analysis gives each as the forces *locked
in* at the stage its loads were applied -- :func:`locked_in_split` groups the
per-stage increments by the stage's load kind.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

__all__ = ["UNVERIFIED", "stage_step", "stage_table_argument", "stage_increments", "locked_in_split",
           "camber_table"]

#: The request strings below come from the API manual, not a live read-back.
UNVERIFIED = True

DEFAULT_FORCE_COMPONENTS = ("Elem", "Load", "Stage", "Step", "Part", "Axial", "Shear-y", "Shear-z",
                            "Moment-y", "Moment-z")
DEFAULT_STRESS_COMPONENTS = ("Elem", "Load", "Stage", "Step", "Part", "Sax(1)", "Sax(2)", "Sax(3)", "Sax(4)",
                             "Ssy", "Ssz", "Sby(1)", "Sby(2)", "Sbz(1)", "Sbz(2)", "Combined(1)", "Combined(2)",
                             "Combined(3)", "Combined(4)")


def stage_step(stage: str, step: str | int = "last") -> str:
    """The ``STAGE_STEP`` item for one stage: ``"<stage>:001(first)"`` /
    ``"(last)"`` or an additional step number."""
    if step in ("first", "last"):
        return f"{stage}:001({step})"
    return f"{stage}:{int(step):03d}"


def stage_table_argument(table_type: str, elem_ids: Iterable[int], stages: Sequence[str], *,
                         step: str = "last", components: Sequence[str] | None = None,
                         summation: bool = True, unit: Mapping | None = None) -> dict:
    """``Argument`` for ``POST /post/TABLE`` of a construction-stage result
    table: ``BEAMFORCE`` / ``BEAMSTRESS`` / ``DISPLACEMENT`` / ``REACTION``
    for the given stages at their first or last step.  ``summation`` asks
    for the accumulated result (``"Summation"``), else the per-stage
    (``"Stage"``) result -- the two MIDAS result modes for construction
    stages.  UNVERIFIED request strings (module docstring)."""
    table_type = table_type.upper()
    names = {"BEAMFORCE": "BeamForce", "BEAMSTRESS": "BeamStress", "DISPLACEMENT": "Displacements",
             "REACTION": "Reaction"}
    if table_type not in names:
        raise ValueError(f"table type {table_type!r}: use one of {sorted(names)}")
    comps = list(components) if components else list(
        DEFAULT_FORCE_COMPONENTS if table_type == "BEAMFORCE" else DEFAULT_STRESS_COMPONENTS
        if table_type == "BEAMSTRESS" else ("Node", "Load", "Stage", "Step", "DX", "DY", "DZ", "RX", "RY", "RZ"))
    arg = {
        "TABLE_NAME": names[table_type], "TABLE_TYPE": table_type,
        "UNIT": dict(unit or {"FORCE": "KIPS", "DIST": "FT"}),
        "STYLES": {"FORMAT": "Default", "PLACE": 12},
        "COMPONENTS": comps,
        "NODE_ELEMS": {"KEYS": [int(e) for e in elem_ids]},
        "LOAD_CASE_NAMES": ["Summation(CS)" if summation else "Dead Load(CS)"],
        "STAGE_STEP": [stage_step(s, step) for s in stages],
    }
    if table_type in ("BEAMFORCE", "BEAMSTRESS"):
        arg["PARTS"] = ["Part I", "Part J"]
    return arg


# --------------------------------------------------------------------------- post-processing
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stage_increments(rows: Iterable[Mapping], stages: Sequence[str], *, key=("Elem", "Part"),
                     components: Sequence[str] = ("Axial", "Shear-y", "Shear-z", "Moment-y", "Moment-z"),
                     stage_field: str = "Stage") -> dict[tuple, dict[str, dict[str, float]]]:
    """From **accumulated** (summation) rows at the last step of every stage,
    the increment each stage added: ``{(elem, part): {stage: {component:
    delta}}}``.  Rows carry the stage in ``stage_field`` (``"Stage3-2:001(last)"``
    or the bare name)."""
    acc: dict[tuple, dict[str, dict[str, float]]] = defaultdict(dict)
    for r in rows:
        st = str(r.get(stage_field, "")).split(":")[0]
        if st not in stages:
            continue
        k = tuple(r.get(f) for f in key)
        acc[k][st] = {c: _num(r.get(c)) or 0.0 for c in components}
    out: dict[tuple, dict[str, dict[str, float]]] = {}
    for k, by_stage in acc.items():
        prev = {c: 0.0 for c in components}
        out[k] = {}
        for st in stages:
            cur = by_stage.get(st)
            if cur is None:
                continue
            out[k][st] = {c: cur[c] - prev[c] for c in components}
            prev = cur
    return out


def locked_in_split(increments: Mapping[tuple, Mapping[str, Mapping[str, float]]],
                    stage_kind: Mapping[str, str]) -> dict[tuple, dict[str, dict[str, float]]]:
    """Group the per-stage increments into load kinds -- ``stage_kind`` maps
    each stage to ``"DC1"`` / ``"DC2"`` / ``"DW"`` / ``"CR+SH"`` (or any
    label); stages not listed are ignored.  Returns ``{(elem, part): {kind:
    {component: sum}}}`` -- the DC1 / DC2 / DW the rating factor needs."""
    out: dict[tuple, dict[str, dict[str, float]]] = {}
    for k, by_stage in increments.items():
        kinds: dict[str, dict[str, float]] = {}
        for st, comps in by_stage.items():
            kind = stage_kind.get(st)
            if kind is None:
                continue
            tgt = kinds.setdefault(kind, {})
            for c, v in comps.items():
                tgt[c] = tgt.get(c, 0.0) + v
        out[k] = kinds
    return out


def camber_table(rows: Iterable[Mapping], stages: Sequence[str], *, node_field: str = "Node",
                 dz_field: str = "DZ", stage_field: str = "Stage") -> dict[str, dict[str, float]]:
    """Dead-load deflection by stage from accumulated displacement rows:
    ``{node: {stage: dz}}`` -- the camber diagram is the negative of the
    final column (or of the non-composite stages only, per the plans'
    camber note)."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        st = str(r.get(stage_field, "")).split(":")[0]
        if st in stages:
            out[str(r.get(node_field))][st] = _num(r.get(dz_field)) or 0.0
    return dict(out)
