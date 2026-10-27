"""4-D User Text from a construction sequence (no Rhino)."""
from datetime import date

from civilpy.structural.construction_sequence import (ConstructionSequence, ElementActivation, ElementDeactivation,
                                                      Stage)
from civilpy.structural.rhino_bim import EmitObject
from civilpy.structural.rhino_stages import stage_filter, stage_tags, tag_objects


def _seq(start=None):
    return ConstructionSequence([
        Stage("Piers", 10, activate=[ElementActivation("Substructure", 28)]),
        Stage("Steel", 5, activate=[ElementActivation("Girder"), ElementActivation("Shoring")]),
        Stage("Deck", 20, activate=[ElementActivation("Deck", 1)], deactivate=[ElementDeactivation("Shoring")]),
    ], start_date=start)


def test_stage_tags_order_days_and_dates():
    t = stage_tags(_seq(date(2027, 4, 1)), "Girder")
    assert (t["stage"], t["stage_order"]) == ("Steel", "2")
    assert (t["stage_start_day"], t["stage_finish_day"]) == ("10", "15")
    assert (t["start"], t["finish"]) == ("2027-04-11", "2027-04-16")
    assert "removed_stage" not in t


def test_removed_group_and_unknown_group():
    t = stage_tags(_seq(), "Shoring")
    assert t["removed_stage"] == "Deck" and t["removed_day"] == "15"
    u = stage_tags(_seq(), "Railing")
    assert u["stage"] == "" and u["midas_group"] == "Railing" and u["start"] == ""


def test_tag_objects_by_mapping_and_callable():
    objs = [EmitObject("point", "L", ((0, 0, 0),), {"bim.type": "girder", "bim.id": "G1"}),
            EmitObject("point", "L", ((0, 0, 0),), {"bim.type": "deck_slab", "bim.id": "S1"}),
            EmitObject("point", "L", ((0, 0, 0),), {"bim.type": "pier", "bim.id": "P1"})]
    n = tag_objects(objs, _seq(), {"girder": "Girder", "S1": "Deck"})
    assert n == 2 and objs[0].tags["stage"] == "Steel" and objs[1].tags["stage_order"] == "3"
    assert "stage" not in objs[2].tags
    n2 = tag_objects(objs, _seq(), lambda o: "Substructure" if o.tags["bim.type"] == "pier" else None)
    assert n2 == 1 and objs[2].tags["stage"] == "Piers"


def test_stage_filter_states():
    seq = _seq()
    g, s = stage_tags(seq, "Girder"), stage_tags(seq, "Shoring")
    assert stage_filter(g, day=5) == "future"
    assert stage_filter(g, day=12) == "current"
    assert stage_filter(g, day=30) == "built"
    assert stage_filter(s, day=20) == "removed"
    assert stage_filter(g, stage_order=1) == "future" and stage_filter(g, stage_order=2) == "current"
    assert stage_filter({}, day=0) == "built"
