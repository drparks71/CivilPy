#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""4-D tags for Rhino / IFC from a :class:`~civilpy.structural.construction_sequence.ConstructionSequence`.

Every drawn object that belongs to a MIDAS element group gets User Text

======================  ==========================================================
``midas_group``         the element group (the same name the ``GRUP`` / ``STAG`` tables use)
``stage``               the stage that activates the group ("" if never)
``stage_order``         1-based index of that stage ("" if never)
``stage_start_day`` /   days from the start of construction (``ConstructionSequence.schedule``)
``stage_finish_day``
``start`` / ``finish``  ISO dates when the sequence has a ``start_date``, else ""
``removed_stage``       the stage that deactivates the group (only when one does)
======================  ==========================================================

:func:`stage_tags` gives the dict for one group; :func:`tag_objects` writes
them onto :class:`~civilpy.structural.rhino_bim.EmitObject` tags (by a
``group_of`` callback or a ``bim.type`` / ``bim.id`` -> group mapping) before
:func:`~civilpy.structural.rhino_bim.objects_to_3dm` bakes them, so the
Grasshopper date slider and the Rhino Snapshots
(``rhino_scripts/stage_snapshots.py``) can filter on ``start`` / ``finish``
and ``stage_order``.  Nothing here imports Rhino.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

__all__ = ["STAGE_TAG_KEYS", "stage_tags", "tag_objects", "stage_filter"]

STAGE_TAG_KEYS = ("midas_group", "stage", "stage_order", "stage_start_day", "stage_finish_day", "start", "finish",
                  "removed_stage")


def stage_tags(sequence, group: str) -> dict[str, str]:
    """User Text for an object in element group ``group``."""
    by_group = sequence.activation_stage_by_group()
    tags = {"midas_group": group, "stage": "", "stage_order": "", "stage_start_day": "", "stage_finish_day": "",
            "start": "", "finish": ""}
    stage = by_group.get(group)
    if stage is None:
        return tags
    windows = {w.name: w for w in sequence.schedule()}
    w = windows[stage]
    names = [s.name for s in sequence.stages]
    tags.update({"stage": stage, "stage_order": str(names.index(stage) + 1),
                 "stage_start_day": f"{w.start_day:g}", "stage_finish_day": f"{w.finish_day:g}",
                 "start": w.start_date.isoformat() if w.start_date else "",
                 "finish": w.finish_date.isoformat() if w.finish_date else ""})
    for s in sequence.stages:
        if any(d.group == group for d in s.deactivate):
            tags["removed_stage"] = s.name
            tags["removed_day"] = f"{windows[s.name].start_day:g}"
            break
    return tags


def tag_objects(objects: Iterable, sequence, group_of: Callable[[object], str | None] | Mapping[str, str]) -> int:
    """Write the stage tags onto ``objects`` (EmitObjects or anything with a
    mutable ``tags`` dict).  ``group_of`` is a callable ``object -> group``
    or a mapping keyed by ``bim.id`` then ``bim.type``; objects with no group
    are left alone.  Returns the number tagged."""
    cache: dict[str, dict[str, str]] = {}
    n = 0
    for o in objects:
        if callable(group_of):
            g = group_of(o)
        else:
            g = group_of.get(o.tags.get("bim.id")) or group_of.get(o.tags.get("bim.type"))
        if not g:
            continue
        if g not in cache:
            cache[g] = stage_tags(sequence, g)
        o.tags.update(cache[g])
        n += 1
    return n


def stage_filter(tags: Mapping[str, str], *, day: float | None = None, stage_order: int | None = None) -> str:
    """How an object with these tags shows at a point in the schedule:
    ``"future"`` (not yet built), ``"current"`` (being built in this stage),
    ``"built"`` or ``"removed"``.  Pass ``day`` (days from the start) or a
    1-based ``stage_order``; untagged objects are ``"built"``."""
    if not tags.get("stage"):
        return "built"
    if stage_order is not None:
        k = int(tags["stage_order"])
        if stage_order < k:
            return "future"
        rm = tags.get("removed_stage")
        if rm and "removed_day" in tags and stage_order > k and float(tags["removed_day"]) <= 0:
            return "removed"
        return "current" if stage_order == k else "built"
    if day is None:
        raise ValueError("pass day or stage_order")
    s0, s1 = float(tags["stage_start_day"]), float(tags["stage_finish_day"])
    if day < s0:
        return "future"
    if tags.get("removed_day") and day >= float(tags["removed_day"]):
        return "removed"
    return "current" if day <= s1 else "built"
