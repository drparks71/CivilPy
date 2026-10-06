#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Bridge-type feasibility advisor (``civilpy.structural.bridge_type``).

Checks the catalog lookup, the per-type verdict logic (ok / marginal /
infeasible against the simple vs continuous ceilings and the marginal band),
the ranking of feasible types, the equal-span re-split that turns an over-long
single span into a continuous unit, and the ``assess`` redirect that the
docstring promises (a 300 ft rc_slab request becomes a 2 x 150 ft continuous
steel plate girder).  All expected numbers are hand-computed from the CATALOG
envelopes (ODOT BDM 302 planning ranges).
"""

import pytest

from civilpy.structural.bridge_type import (
    CATALOG,
    BridgeType,
    Feasibility,
    Recommendation,
    TypeAssessment,
    _controlling_span,
    _equal_split_for,
    assess,
    evaluate_type,
    feasible_types,
    get_type,
    recommend_for_length,
)


# ── catalog ────────────────────────────────────────────────────────────────

def test_catalog_is_ordered_short_to_long_and_keys_unique():
    keys = [t.key for t in CATALOG]
    assert len(keys) == len(set(keys)) == 6
    assert keys[0] == "rc_slab" and keys[-1] == "steel_plate_girder"
    maxes = [t.max_span_ft for t in CATALOG]
    assert maxes[0] == 40.0 and maxes[-1] == 400.0
    for t in CATALOG:
        assert 0 < t.min_span_ft < t.max_span_ft
        assert t.material in ("concrete", "prestressed", "steel")


def test_get_type_returns_catalog_entry():
    bt = get_type("ps_i_girder")
    assert bt is CATALOG[3]
    assert (bt.min_span_ft, bt.max_span_ft) == (40.0, 160.0)
    assert bt.needs_continuity is False


def test_get_type_unknown_key_lists_valid_keys():
    with pytest.raises(KeyError) as ei:
        get_type("suspension")
    msg = str(ei.value)
    assert "suspension" in msg and "rc_slab" in msg and "steel_plate_girder" in msg


def test_simple_ceiling_falls_back_to_max_span():
    assert get_type("adjacent_box").simple_ceiling_ft() == 100.0      # no simple cap
    assert get_type("steel_plate_girder").simple_ceiling_ft() == 180.0
    assert get_type("rc_slab_cont").simple_ceiling_ft() == 40.0
    bare = BridgeType("x", "X", "steel", 10.0, 50.0)
    assert bare.simple_ceiling_ft() == 50.0


# ── controlling span ───────────────────────────────────────────────────────

def test_controlling_span_is_the_longest():
    assert _controlling_span([60, 90.5, 70]) == 90.5
    assert _controlling_span((25,)) == 25.0
    assert isinstance(_controlling_span([1]), float)


@pytest.mark.parametrize("bad", [[], (), [50, 0], [50, -10]])
def test_controlling_span_rejects_empty_or_nonpositive(bad):
    with pytest.raises(ValueError):
        _controlling_span(bad)


# ── evaluate_type ──────────────────────────────────────────────────────────

def test_single_span_comfortably_in_range_is_ok():
    f = evaluate_type(get_type("rc_slab"), [30.0])
    assert isinstance(f, Feasibility)
    assert f.verdict == "ok" and f.feasible
    assert f.controlling_span_ft == 30.0 and f.continuous is False
    assert len(f.reasons) == 1 and "comfortably" in f.reasons[0]


def test_marginal_band_is_ten_percent_of_the_range():
    # rc_slab: 11-40 ft, band 0.10*(40-11) = 2.9 -> marginal below 13.9 / above 37.1
    top = evaluate_type(get_type("rc_slab"), [38.0])
    assert top.verdict == "marginal" and top.feasible
    assert "near the top" in top.reasons[0]
    bottom = evaluate_type(get_type("rc_slab"), [12.0])
    assert bottom.verdict == "marginal"
    assert "near the bottom" in bottom.reasons[0]
    # just inside the band edges is still ok
    assert evaluate_type(get_type("rc_slab"), [37.0]).verdict == "ok"
    assert evaluate_type(get_type("rc_slab"), [14.0]).verdict == "ok"


def test_marginal_band_zero_removes_the_marginal_verdict():
    assert evaluate_type(get_type("rc_slab"), [38.0], marginal_band=0.0).verdict == "ok"
    assert evaluate_type(get_type("rc_slab"), [40.0], marginal_band=0.0).verdict == "ok"


def test_span_above_ceiling_or_below_floor_is_infeasible():
    over = evaluate_type(get_type("rc_slab"), [45.0])
    assert over.verdict == "infeasible" and not over.feasible
    assert "exceeds the ~40 ft ceiling" in over.reasons[-1]
    under = evaluate_type(get_type("rc_slab"), [10.0])
    assert under.verdict == "infeasible"
    assert "below the ~11 ft floor" in under.reasons[-1]


def test_continuity_type_single_span_uses_the_simple_ceiling():
    cont = get_type("rc_slab_cont")                     # 20-60 ft, 40 ft simple
    single = evaluate_type(cont, [50.0])
    assert single.verdict == "infeasible"
    assert single.continuous is False
    assert "only as a continuous unit" in single.reasons[0]
    assert "capped at 40 ft" in single.reasons[0]
    assert "exceeds the ~40 ft ceiling" in single.reasons[1]
    multi = evaluate_type(cont, [50.0, 50.0])
    assert multi.verdict == "ok" and multi.continuous is True
    assert multi.controlling_span_ft == 50.0
    assert all("continuous unit" not in r for r in multi.reasons)


def test_plate_girder_300ft_single_is_infeasible_but_two_150s_are_ok():
    spg = get_type("steel_plate_girder")
    assert evaluate_type(spg, [300.0]).verdict == "infeasible"
    f = evaluate_type(spg, [150.0, 150.0])
    assert f.verdict == "ok" and f.continuous


def test_evaluate_type_propagates_bad_spans():
    with pytest.raises(ValueError):
        evaluate_type(get_type("rc_slab"), [])


# ── feasible_types ─────────────────────────────────────────────────────────

def test_feasible_types_30ft_ranked_by_centering():
    out = feasible_types([30.0])
    keys = [f.type.key for f in out]
    # rc_slab_cont (single-span range 20-40, mid 30 -> 0.0), rc_slab (mid 25.5,
    # half 14.5 -> 0.31), adjacent_box (mid 60, half 40 -> 0.75)
    assert keys == ["rc_slab_cont", "rc_slab", "adjacent_box"]
    assert all(f.feasible for f in out)
    assert all(f.verdict == "ok" for f in out)


def test_feasible_types_marginal_filter():
    only_marginal = feasible_types([12.0])
    assert [f.type.key for f in only_marginal] == ["rc_slab"]
    assert only_marginal[0].verdict == "marginal"
    assert feasible_types([12.0], include_marginal=False) == []


def test_feasible_types_ok_beats_marginal_in_ranking():
    # at 38 ft rc_slab is marginal (+0.5 penalty) while rc_slab_cont and
    # adjacent_box are ok, so rc_slab drops behind them
    keys = [f.type.key for f in feasible_types([38.0])]
    assert keys.index("rc_slab") > keys.index("adjacent_box")
    assert keys.index("rc_slab") > keys.index("rc_slab_cont")


def test_feasible_types_long_crossing_only_continuous_plate_girder():
    out = feasible_types([200.0, 200.0])
    assert [f.type.key for f in out] == ["steel_plate_girder"]
    assert out[0].continuous


# ── _equal_split_for ───────────────────────────────────────────────────────

def test_equal_split_fewest_spans_in_range():
    # rc_slab 11-40: 300/7 = 42.9 > 40, 300/8 = 37.5 fits
    assert _equal_split_for(get_type("rc_slab"), 300.0) == (37.5,) * 8
    # ps_i_girder 40-160: a single 150 ft span fits
    assert _equal_split_for(get_type("ps_i_girder"), 150.0) == (150.0,)
    # adjacent_box 20-100: 250/3 = 83.33 -> rounded to 0.1 ft
    assert _equal_split_for(get_type("adjacent_box"), 250.0) == (83.3, 83.3, 83.3)


def test_equal_split_continuity_type_needs_two_spans():
    spg = get_type("steel_plate_girder")
    assert _equal_split_for(spg, 300.0) == (150.0, 150.0)
    # 150 ft total: 2 spans of 75 are below the 90 ft floor and n=1 is not
    # allowed for a continuity-dependent type -> no arrangement
    assert _equal_split_for(spg, 150.0) is None


def test_equal_split_none_when_nothing_fits():
    assert _equal_split_for(get_type("rc_slab"), 5.0) is None        # below floor
    # 12 spans of rc_slab max out at 480 ft
    assert _equal_split_for(get_type("rc_slab"), 500.0) is None


# ── recommend_for_length ───────────────────────────────────────────────────

def test_recommend_300ft_ranks_plate_girder_first():
    recs = recommend_for_length(300.0, exclude="rc_slab")
    assert len(recs) == 3
    assert all(isinstance(r, Recommendation) for r in recs)
    assert [r.type.key for r in recs] == ["steel_plate_girder", "ps_i_girder", "steel_rolled"]
    spg, psi, rolled = recs
    assert spg.spans_ft == (150.0, 150.0) and spg.verdict == "ok" and spg.resplit
    assert psi.spans_ft == (150.0, 150.0) and psi.verdict == "marginal"
    assert rolled.spans_ft == (100.0,) * 3 and rolled.verdict == "ok"
    assert "continuous 2-span unit" in spg.reason
    assert "90-400 ft range" in spg.reason


def test_recommend_excludes_the_requested_type_and_honours_n():
    keys = [r.type.key for r in recommend_for_length(300.0, n=10)]
    assert "rc_slab" in keys                     # 8 x 37.5 ft is a legal split
    assert "rc_slab" not in [r.type.key for r in recommend_for_length(300.0, exclude="rc_slab", n=10)]
    assert len(recommend_for_length(300.0, n=1)) == 1
    # every catalog type has some equal split of 300 ft and none is infeasible
    assert len(recommend_for_length(300.0, n=10)) == 6 == len(
        [bt for bt in CATALOG if _equal_split_for(bt, 300.0) is not None])


def test_recommend_single_span_fits_as_arranged():
    recs = recommend_for_length(50.0, exclude="rc_slab")
    assert [r.type.key for r in recs] == ["adjacent_box", "steel_rolled", "ps_i_girder"]
    box = recs[0]
    assert box.resplit is False and box.spans_ft == (50.0,)
    assert "single span fits the 20-100 ft range" in box.reason
    assert box.describe() == ("Prestressed adjacent box beams: as arranged -- "
                              "single span fits the 20-100 ft range")
    psi = recs[2]
    assert psi.verdict == "marginal"
    assert psi.describe().startswith("Prestressed I-girder, composite deck (marginal): as arranged")


def test_recommendation_describe_resplit():
    r = recommend_for_length(300.0, exclude="rc_slab")[0]
    assert r.describe().startswith(
        "Continuous steel plate girder, composite deck: 2 spans of ~150 ft -- ")


# ── assess ─────────────────────────────────────────────────────────────────

def test_assess_redirects_300ft_slab_to_continuous_steel():
    a = assess("rc_slab", [300.0])
    assert isinstance(a, TypeAssessment)
    assert a.allowed is False and a.verdict == "infeasible"
    assert a.requested.key == "rc_slab" and a.spans_ft == (300.0,)
    assert len(a.recommended) == 3
    top = a.recommended[0]
    assert top.type.material == "steel" and top.type.key == "steel_plate_girder"
    assert top.resplit and top.spans_ft == (150.0, 150.0)
    assert sum(top.spans_ft) == 300.0                     # crossing length preserved
    assert all(r.type.key != "rc_slab" for r in a.recommended)


def test_assess_feasible_request_has_no_recommendations():
    a = assess("rc_slab", [30])
    assert a.allowed and a.verdict == "ok"
    assert a.recommended == ()
    assert a.spans_ft == (30.0,) and isinstance(a.spans_ft[0], float)


def test_assess_marginal_is_allowed():
    a = assess("rc_slab", [38.0])
    assert a.allowed and a.verdict == "marginal" and a.recommended == ()


def test_assess_multi_span_total_length_drives_the_redirect():
    a = assess("rc_slab", [60.0, 60.0])                   # 60 ft > 40 ft ceiling
    assert not a.allowed
    assert all(abs(sum(r.spans_ft) - 120.0) < 1e-6 for r in a.recommended)
    assert len(assess("rc_slab", [60.0, 60.0], n_recommend=1).recommended) == 1


def test_assess_unknown_key_raises():
    with pytest.raises(KeyError):
        assess("bailey", [50.0])


def test_summary_text_for_a_redirect_and_for_an_ok_request():
    s = assess("rc_slab", [300.0]).summary()
    lines = s.splitlines()
    assert lines[0] == "Reinforced concrete slab (single span) for single span: INFEASIBLE"
    assert any("exceeds the ~40 ft ceiling" in ln for ln in lines)
    assert "  Recommended instead:" in lines
    assert any(ln.startswith("    * Continuous steel plate girder") for ln in lines)

    ok = assess("rc_slab", [30.0, 25.0]).summary()
    assert ok.splitlines()[0] == ("Reinforced concrete slab (single span) for 2 spans, "
                                  "max 30 ft: OK")
    assert "Recommended instead" not in ok
