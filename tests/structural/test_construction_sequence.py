"""Construction sequence: validation, MIDAS tables, schedule and the
deck-pour preset.  Pure functions, no MIDAS session."""
from datetime import date

import pytest

from civilpy.structural import midas_composite_wizard as wiz
from civilpy.structural.construction_sequence import (
    PLUS_LICENSE_STAGE_LIMIT,
    AnalysisControl,
    BoundaryActivation,
    CompositePart,
    CompositeSection,
    ConstructionSequence,
    DeckPour,
    ElementActivation,
    ElementDeactivation,
    LoadActivation,
    SequenceError,
    Stage,
    deck_pour_sequence,
)


def _simple(**kw):
    stages = [Stage("S1", 10, activate=[ElementActivation("Sub", 28)],
                    boundaries=[BoundaryActivation("Supports", "ORIGINAL")], loads=[LoadActivation("SW")]),
              Stage("S2", 5, activate=[ElementActivation("Girder")], loads=[LoadActivation("Wet")]),
              Stage("S3", 0, activate=[ElementActivation("Deck", 1)], remove_loads=[LoadActivation("Wet")])]
    return ConstructionSequence(stages, boundary_groups=["Supports"], **kw)


def test_simple_sequence_is_valid():
    assert _simple().problems() == []


def test_wizard_sequence_valid_and_matches_tables():
    seq = wiz.wizard_sequence()
    assert seq.problems() == []
    tables = wiz.construction_stages()
    assert tables["STAG"]["1"]["ACT_BNGR"] == [{"BNGR_NAME": "SubstructureSupport", "POS": "ORIGINAL"}]
    assert {r["NAME"] for r in tables["BNGR"].values()} == {"SubstructureSupport", "GirderElastic Link",
                                                           "GirderRigid Link"}
    assert tables["STCT"]["1"]["FINAL_STAGE"] == "Stage5" and tables["STCT"]["1"]["bLAST_FINAL"] is True
    assert [e["vLCNAME"] for e in tables["STCT"]["1"]["vEREC"]] == [["Barrier"], ["Wearing Surface"]]
    assert "CSCS" not in tables


def test_undeclared_boundary_group_is_caught():
    # the wizard's old Stage1 named "Support", which no BNGR / CONS row carries
    seq = wiz.wizard_sequence()
    seq.stages[0].boundaries[0] = BoundaryActivation("Support", "ORIGINAL")
    assert any("'Support' is not in boundary_groups" in p for p in seq.problems())


@pytest.mark.parametrize("mutate, expect", [
    (lambda s: s.stages.append(Stage("S1", 1)), "duplicate stage names"),
    (lambda s: s.stages[1].activate.append(ElementActivation("Sub")), "'Sub' is already active"),
    (lambda s: s.stages[2].remove_loads.append(LoadActivation("Barrier")), "'Barrier' removed but not applied"),
    (lambda s: s.stages[1].loads.append(LoadActivation("SW")), "'SW' is already applied"),
    (lambda s: s.stages[1].deactivate.append(ElementDeactivation("Deck")), "'Deck' deactivated but not active"),
    (lambda s: setattr(s.stages[0], "duration", -1), "negative duration"),
    (lambda s: s.stages[0].boundaries.append(BoundaryActivation("Supports", "MOVED")), "boundary position"),
    (lambda s: s.stages[1].loads.append(LoadActivation("X", "MIDDLE")), "load day"),
    (lambda s: setattr(s.control, "final_stage", "S9"), "final stage 'S9'"),
])
def test_problems_found(mutate, expect):
    seq = _simple()
    mutate(seq)
    assert any(expect in p for p in seq.problems()), seq.problems()


def test_stage_limit():
    stages = [Stage(f"S{i}", 1) for i in range(PLUS_LICENSE_STAGE_LIMIT + 1)]
    assert any("license limit" in p for p in ConstructionSequence(stages).problems())
    assert ConstructionSequence(stages, max_stages=20).problems() == []


def test_unknown_groups_when_model_groups_given():
    found = _simple().problems(element_groups={"Sub", "Girder"}, load_groups={"SW"})
    assert any("'Deck' is not in the model" in p for p in found)
    assert any("'Wet' is not in the model" in p for p in found)


def test_composite_section_checks_and_table():
    good = CompositeSection(3, "S2", [CompositePart(1, "ELEM", 1, 0.05, 0.05),
                                      CompositePart(2, "MATL", 28, 0.6, 0.6, material="2", composite_stage="S3")])
    seq = _simple(composite_sections=[good])
    assert seq.problems() == []
    row = seq.to_midas()["CSCS"]["1"]
    assert row["SEC"] == 3 and row["ASTAGE"] == "S2" and row["vPARTINFO"][1]["CSTAGE"] == "S3"

    early = CompositeSection(4, "S3", [CompositePart(1, "MATL", 28, 0.0, 0.6, material="2", composite_stage="S2")])
    found = _simple(composite_sections=[early]).problems()
    assert any("comes before the section is active" in p for p in found)
    assert any("must be > 0" in p for p in found)


def test_to_midas_raises_with_every_problem():
    seq = _simple()
    seq.stages[0].duration = -1
    seq.control.final_stage = "nope"
    with pytest.raises(SequenceError) as err:
        seq.to_midas()
    assert len(err.value.problems) == 2


def test_unverified_bodies_refused():
    seq = _simple()
    seq.stages.append(Stage("S4", 1, deactivate=[ElementDeactivation("Girder")]))
    assert seq.problems() == []
    with pytest.raises(NotImplementedError, match="DACT_ELEM"):
        seq.to_midas()


def test_final_stage_not_last():
    stct = _simple(control=AnalysisControl(final_stage="S2")).to_midas()["STCT"]["1"]
    assert stct["FINAL_STAGE"] == "S2" and stct["bLAST_FINAL"] is False


def test_schedule_and_activation_tags():
    seq = _simple(start_date=date(2027, 4, 1))
    win = seq.schedule()
    assert [(w.start_day, w.finish_day) for w in win] == [(0, 10), (10, 15), (15, 15)]
    assert win[1].start_date == date(2027, 4, 11) and win[2].finish_date == date(2027, 4, 16)
    assert seq.activation_stage_by_group() == {"Sub": "S1", "Girder": "S2", "Deck": "S3"}


def _pours(n):
    return [DeckPour(f"Pour {i}", f"Wet {i}", f"Deck {i}") for i in range(1, n + 1)]


@pytest.mark.parametrize("n", [1, 3, 6])
def test_deck_pour_sequence_compact(n):
    seq = deck_pour_sequence(_pours(n))
    assert len(seq.stages) == n + 4 and seq.problems() == []
    names = [s.name for s in seq.stages]
    tags = seq.activation_stage_by_group()
    for i in range(1, n + 1):
        # each deck hardens in the stage after its pour, and its wet load comes off there
        later = names[names.index(f"Pour {i}") + 1]
        assert tags[f"Deck {i}"] == later
        stage = seq.stages[names.index(later)]
        assert LoadActivation(f"Wet {i}") in stage.remove_loads
    assert seq.stages[-1].name == "Long term" and seq.stages[-1].duration == 10000


def test_deck_pour_sequence_split_and_limit():
    seq = deck_pour_sequence(_pours(3), split_composite=True)
    assert len(seq.stages) == 10 and seq.problems() == []
    assert seq.stages[3].name == "Pour 1 composite" and seq.stages[3].duration == 0
    assert any("license limit" in p for p in deck_pour_sequence(_pours(7)).problems())
    assert any("license limit" in p for p in deck_pour_sequence(_pours(4), split_composite=True).problems())


def test_deck_pour_sequence_needs_a_pour():
    with pytest.raises(ValueError):
        deck_pour_sequence([])
