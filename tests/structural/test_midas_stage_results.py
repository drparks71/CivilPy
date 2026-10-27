"""Construction-stage result post-processing (pure functions)."""
import pytest

from civilpy.structural.midas_stage_results import (camber_table, locked_in_split, stage_increments, stage_step,
                                                    stage_table_argument)


def test_stage_step_and_argument_shape():
    assert stage_step("Stage3-2") == "Stage3-2:001(last)"
    assert stage_step("Stage1", "first") == "Stage1:001(first)"
    assert stage_step("Stage1", 3) == "Stage1:003"
    arg = stage_table_argument("beamforce", [1, 2], ["Stage1", "Stage2"])
    assert arg["TABLE_TYPE"] == "BEAMFORCE" and arg["PARTS"] == ["Part I", "Part J"]
    assert arg["STAGE_STEP"] == ["Stage1:001(last)", "Stage2:001(last)"]
    assert arg["NODE_ELEMS"] == {"KEYS": [1, 2]} and arg["LOAD_CASE_NAMES"] == ["Summation(CS)"]
    disp = stage_table_argument("displacement", [5], ["S"], summation=False)
    assert "PARTS" not in disp and disp["LOAD_CASE_NAMES"] == ["Dead Load(CS)"]
    with pytest.raises(ValueError):
        stage_table_argument("plate", [1], ["S"])


def _rows():
    # accumulated moments at the last step of each stage for element 7, part I
    return [{"Elem": 7, "Part": "I", "Stage": "Stage1:001(last)", "Moment-y": "0", "Axial": "0"},
            {"Elem": 7, "Part": "I", "Stage": "Stage2:001(last)", "Moment-y": "-100", "Axial": "0"},
            {"Elem": 7, "Part": "I", "Stage": "Stage3-1:001(last)", "Moment-y": "-250", "Axial": "0"},
            {"Elem": 7, "Part": "I", "Stage": "Stage4:001(last)", "Moment-y": "-280", "Axial": "0"},
            {"Elem": 7, "Part": "I", "Stage": "Stage5:001(last)", "Moment-y": "-290", "Axial": "0"}]


def test_increments_and_locked_in_split():
    stages = ["Stage1", "Stage2", "Stage3-1", "Stage4", "Stage5"]
    inc = stage_increments(_rows(), stages, components=("Moment-y", "Axial"))
    k = (7, "I")
    assert inc[k]["Stage2"]["Moment-y"] == -100 and inc[k]["Stage3-1"]["Moment-y"] == -150
    assert inc[k]["Stage4"]["Moment-y"] == -30 and inc[k]["Stage5"]["Moment-y"] == -10
    split = locked_in_split(inc, {"Stage2": "DC1", "Stage3-1": "DC1", "Stage4": "DC2", "Stage5": "CR+SH"})
    assert split[k]["DC1"]["Moment-y"] == -250 and split[k]["DC2"]["Moment-y"] == -30
    assert split[k]["CR+SH"]["Moment-y"] == -10 and "Stage1" not in split[k]


def test_camber_table():
    rows = [{"Node": 3, "Stage": "Stage2:001(last)", "DZ": "-0.10"}, {"Node": 3, "Stage": "Stage4:001(last)", "DZ": "-0.25"},
            {"Node": 4, "Stage": "Stage2:001(last)", "DZ": "-0.05"}]
    t = camber_table(rows, ["Stage2", "Stage4"])
    assert t["3"] == {"Stage2": -0.10, "Stage4": -0.25} and t["4"] == {"Stage2": -0.05}
