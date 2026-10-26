#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""
Tests for the FHWA SNBI validation models in civilpy.state.ohio.snbi.
"""
import pytest
from pydantic import ValidationError

from civilpy.state.ohio.snbi import (
    Bridge, Element, Route, Feature, Inspection, PostingEvaluation,
    PostingStatus, SpanSet, SubstructureSet, Work,
)


def _route():
    return Route(BRT01="R1", BRT02="00071", BRT03="NB", BRT04="1", BRT05="1")


def _highway_feature(**overrides):
    data = dict(
        BF01="H01", BF02="C", BH02="99999", BH06="ROUTE 71", BH09=5000, BH11=2024,
        BH13=99.9, BH16=40.0, BH17=10, Routes=[_route()],
    )
    data.update(overrides)
    return Feature(**data)


def _features():
    return [_highway_feature()]


def _valid_kwargs(**overrides):
    """A minimal bridge that satisfies every required FHWA check."""
    data = dict(
        BID01="0100226",
        BL01=39, BL05=40.0, BL06=-82.0,
        BCL01="S01", BCL02="S01", BCL03="N", BCL04="N", BCL05="N",
        BG01=100.0, BG02=110.0, BG03=50.0, BG05=40.0, BG06=38.0,
        BG07=2.0, BG08=2.0, BG09=36.0, BG10="0", BG11=0, BG14="N",
        BC01="7", BC02="6", BC03="6", BC04="N", BC09="N",
        BIR01="N", BIR03="N",
        BAP01="G", BAP02="0", BAP03="U", BAP05="N",
        Features=_features(),
        PostingStatuses=[PostingStatus(BPS01="N")],
        SpanSets=[SpanSet(BSP01="M01", BSP02=2, BSP04="S01", BSP05="1",
                          BSP06="G01", BSP09="C01", BSP12="R01")],
        SubstructureSets=[SubstructureSet(BSB01="A01")],
        Works=[Work(BW02=1985)],
    )
    data.update(overrides)
    return data


def make_bridge(**overrides):
    return Bridge(**_valid_kwargs(**overrides))


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def test_valid_bridge_passes():
    b = make_bridge()
    assert b.BID01 == "0100226"
    assert b.BID03 == "0"  # default


# --------------------------------------------------------------------------- #
# State code (B.L.01) - replaces the broken Field(eq=39) no-op
# --------------------------------------------------------------------------- #
class TestStateCode:
    def test_ohio_valid(self):
        assert make_bridge(BL01=39).BL01 == 39

    def test_other_state_valid(self):
        # Generic FHWA check: any valid state code passes, not just Ohio
        assert make_bridge(BL01=6).BL01 == 6      # California
        assert make_bridge(BL01=72).BL01 == 72    # Puerto Rico

    def test_invalid_state_raises(self):
        with pytest.raises(ValidationError):
            make_bridge(BL01=99)


# --------------------------------------------------------------------------- #
# Data-type / length corrections
# --------------------------------------------------------------------------- #
class TestTypesAndLengths:
    def test_district_alphanumeric_allowed(self):
        # B.L.04: FHWA allows A-Z, a-z, 0-9 (was wrongly int-only before)
        assert make_bridge(BL04="0A").BL04 == "0A"

    def test_district_symbol_rejected(self):
        with pytest.raises(ValidationError):
            make_bridge(BL04="*")

    def test_longitude_accepts_decimal(self):
        assert make_bridge(BL06=-82.123456).BL06 == pytest.approx(-82.123456)

    def test_previous_number_max_15(self):
        with pytest.raises(ValidationError):
            make_bridge(BID03="x" * 16)

    def test_bridge_location_restored(self):
        assert make_bridge(BL11="Over Main St, 0.5 mi N of SR-10").BL11.startswith("Over")

    def test_min_span_length_restored(self):
        assert make_bridge(BG04=25.0).BG04 == 25.0

    def test_bridge_number_charset(self):
        with pytest.raises(ValidationError):
            make_bridge(BID01="BAD%CHAR")


# --------------------------------------------------------------------------- #
# FHWA-calculated items must NOT be reported
# --------------------------------------------------------------------------- #
class TestDoNotReport:
    @pytest.mark.parametrize("field", ["BG16", "BC12", "BC13"])
    def test_calculated_fields_rejected(self, field):
        with pytest.raises(ValidationError):
            make_bridge(**{field: "5"})

    def test_inspection_due_date_rejected(self):
        with pytest.raises(ValidationError):
            Inspection(BIE01="2", BIE02="20240101", BIE06="20250101")


# --------------------------------------------------------------------------- #
# Enumerations & condition ratings
# --------------------------------------------------------------------------- #
class TestEnumerations:
    def test_condition_rating_valid(self):
        assert make_bridge(BC01="9").BC01 == "9"
        assert make_bridge(BC04="N").BC04 == "N"

    def test_condition_rating_invalid(self):
        with pytest.raises(ValidationError):
            make_bridge(BC01="X")

    def test_median_range(self):
        assert make_bridge(BG10="3").BG10 == "3"
        with pytest.raises(ValidationError):
            make_bridge(BG10="4")

    def test_toll_enum(self):
        with pytest.raises(ValidationError):
            make_bridge(BCL05="9")

    def test_approach_alignment_enum(self):
        assert make_bridge(BAP01="G").BAP01 == "G"
        with pytest.raises(ValidationError):
            make_bridge(BAP01="Z")

    def test_border_state_or_country(self):
        assert make_bridge(BL08="MX").BL08 == "MX"
        with pytest.raises(ValidationError):
            make_bridge(BL08="99")


# --------------------------------------------------------------------------- #
# Date format / calendar validity
# --------------------------------------------------------------------------- #
class TestDates:
    def test_valid_date(self):
        assert make_bridge(BLR03="20240101").BLR03 == "20240101"

    def test_non_numeric_date_raises(self):
        with pytest.raises(ValidationError):
            make_bridge(BLR03="2024-01-01")

    def test_impossible_calendar_date_raises(self):
        with pytest.raises(ValidationError):
            make_bridge(BLR03="20241350")


# --------------------------------------------------------------------------- #
# Numeric magnitude bounds
# --------------------------------------------------------------------------- #
class TestRanges:
    def test_span_length_magnitude(self):
        with pytest.raises(ValidationError):
            make_bridge(BG03=10000.0)   # exceeds 9999.9

    def test_load_rating_factor_magnitude(self):
        with pytest.raises(ValidationError):
            make_bridge(BLR05=100.0)    # exceeds 99.99


# --------------------------------------------------------------------------- #
# "At least one dataset" critical rules
# --------------------------------------------------------------------------- #
class TestRequiredDatasets:
    @pytest.mark.parametrize("field", ["Features", "PostingStatuses", "SpanSets", "Works"])
    def test_missing_dataset_raises(self, field):
        with pytest.raises(ValidationError):
            make_bridge(**{field: None})

    def test_substructure_required_for_non_culvert(self):
        with pytest.raises(ValidationError):
            make_bridge(SubstructureSets=None)

    def test_substructure_optional_for_buried_culvert(self):
        # All spans are buried pipe culverts (BSP06 = P01) -> substructure optional
        b = make_bridge(
            SpanSets=[SpanSet(BSP01="C01", BSP02=1, BSP04="C01", BSP05="7",
                              BSP06="P01")],
            SubstructureSets=None,
            BC04="5",
        )
        assert b.SubstructureSets is None


# --------------------------------------------------------------------------- #
# Feature-type conditional rules
# --------------------------------------------------------------------------- #
class TestFeatureConditionals:
    def test_highway_without_route_is_tolerated(self):
        # A highway feature that came back from the API with no Route dataset
        # also came back without its BH* detail block; that is a data-source gap
        # (FHWA's export carries it, the REST read does not), not a coding error,
        # so it must NOT raise -- otherwise we re-report the gap thousands of times.
        b = make_bridge(Features=[Feature(BF01="H01")])
        assert b.Features[0].BF01 == "H01"

    def test_waterway_requires_navigable_code(self):
        with pytest.raises(ValidationError):
            make_bridge(Features=[Feature(BF01="W01")])

    def test_waterway_with_navigable_code_ok(self):
        # A waterway feature means the bridge must carry a 0-9 channel rating.
        b = make_bridge(Features=[Feature(BF01="W01", BN01="N")], BC09="5")
        assert b.Features[0].BN01 == "N"


# --------------------------------------------------------------------------- #
# Load evaluation / posting requirement (B.EP)
# --------------------------------------------------------------------------- #
class TestPostingEvaluation:
    def test_required_when_open_and_under_rated(self):
        with pytest.raises(ValidationError):
            make_bridge(BLR07=0.8, PostingStatuses=[PostingStatus(BPS01="SP")])

    def test_satisfied_with_evaluation(self):
        b = make_bridge(
            BLR07=0.8,
            PostingStatuses=[PostingStatus(BPS01="SP")],
            PostingEvaluations=[PostingEvaluation(BEP01="Type3")],
        )
        assert b.PostingEvaluations[0].BEP01 == "Type3"

    def test_not_required_when_closed(self):
        b = make_bridge(BLR07=0.8, PostingStatuses=[PostingStatus(BPS01="C")])
        assert b.PostingEvaluations is None


# --------------------------------------------------------------------------- #
# Safety checks
# --------------------------------------------------------------------------- #
class TestSafety:
    def test_low_condition_rating_not_closed(self):
        with pytest.raises(ValidationError):
            make_bridge(BC01="1")  # < 2 and not posted closed

    def test_low_condition_rating_closed_ok(self):
        b = make_bridge(BC01="1", PostingStatuses=[PostingStatus(BPS01="C")])
        assert b.BC01 == "1"

    def test_low_operating_rating_not_closed(self):
        with pytest.raises(ValidationError):
            make_bridge(BLR06=0.05)

    def test_legal_rating_below_one_requires_posting(self):
        with pytest.raises(ValidationError):
            make_bridge(
                BLR07=0.8,
                PostingStatuses=[PostingStatus(BPS01="N")],
                PostingEvaluations=[PostingEvaluation(BEP01="T")],
            )


# --------------------------------------------------------------------------- #
# Length consistency & previous bridge number
# --------------------------------------------------------------------------- #
class TestConsistency:
    def test_nbis_not_greater_than_total(self):
        with pytest.raises(ValidationError):
            make_bridge(BG01=200.0, BG02=110.0)

    def test_previous_number_must_differ(self):
        with pytest.raises(ValidationError):
            make_bridge(BID03="0100226")  # equals BID01

    def test_nstm_condition_only_when_required(self):
        with pytest.raises(ValidationError):
            make_bridge(BC14="7")  # BIR01 != 'Y'
        b = make_bridge(BIR01="Y", BC14="7")
        assert b.BC14 == "7"


# --------------------------------------------------------------------------- #
# Element quantity reconciliation
# --------------------------------------------------------------------------- #
class TestElement:
    def test_total_equals_sum(self):
        e = Element(BE01="12", BE02="0", BE03=100, BCS01=70, BCS02=20, BCS03=10, BCS04=0)
        assert e.BE03 == 100

    def test_total_mismatch_raises(self):
        with pytest.raises(ValidationError):
            Element(BE01="12", BE02="0", BE03=100, BCS01=70, BCS02=20, BCS03=5, BCS04=0)


# --------------------------------------------------------------------------- #
# Child key-field requirements
# --------------------------------------------------------------------------- #
class TestChildRequirements:
    def test_route_designation_starts_with_r(self):
        with pytest.raises(ValidationError):
            Route(BRT01="US")

    def test_work_year_required(self):
        with pytest.raises(ValidationError):
            Work()

    def test_inspection_requires_type_and_begin_date(self):
        with pytest.raises(ValidationError):
            Inspection()
        insp = Inspection(BIE01="2", BIE02="20240101")
        assert insp.BIE01 == "2"


# --------------------------------------------------------------------------- #
# Coded-value enumerations (newly wired from _SNBI_CODES / _PATTERN_CODES)
# --------------------------------------------------------------------------- #
class TestCodedValues:
    def _span(self, **overrides):
        data = dict(BSP01="M01", BSP02=2, BSP04="S01", BSP05="1",
                    BSP06="G01", BSP09="C01", BSP12="R01")
        data.update(overrides)
        return SpanSet(**data)

    def test_span_protective_system_invalid(self):
        # BSP12 Deck Reinforcing Protective System: enum now enforced
        with pytest.raises(ValidationError):
            self._span(BSP12="ZZ")

    def test_span_protective_system_valid(self):
        assert self._span(BSP12="R01").BSP12 == "R01"

    def test_route_direction_invalid(self):
        with pytest.raises(ValidationError):
            _highway_feature(Routes=[Route(BRT01="R1", BRT02="00071",
                                           BRT03="QQ", BRT04="1", BRT05="1")])

    def test_route_direction_valid(self):
        assert _route().BRT03 == "NB"

    def test_nstm_flag_enum_when_present(self):
        # BIR01 is optional now, but still Y/N when a value is given
        with pytest.raises(ValidationError):
            make_bridge(BIR01="X")

    def test_posting_status_code_invalid(self):
        with pytest.raises(ValidationError):
            PostingStatus(BPS01="ZZ")

    def test_substructure_material_invalid(self):
        with pytest.raises(ValidationError):
            SubstructureSet(BSB01="A01", BSB03="ZZ")

    def test_land_access_multivalue(self):
        # BCL03 is pipe-delimited; every token must be valid
        assert make_bridge(BCL03="BIA|NPS").BCL03 == "BIA|NPS"
        with pytest.raises(ValidationError):
            make_bridge(BCL03="BIA|NOPE")

    def test_transition_code_accepted(self):
        # "<base>-T" transition codes (valid 2026-2027) pass the enum check.
        # BAP03 (max_length 5) is still enum-checked and accommodates "A-T".
        assert make_bridge(BAP03="A-T").BAP03 == "A-T"


# --------------------------------------------------------------------------- #
# Required for all bridges (FHWA "X is null ..." rules → now required fields)
# --------------------------------------------------------------------------- #
class TestRequiredForAllBridges:
    # Only the items that match FHWA's null-finding rate stay required; the
    # over-flagging ones (BG03/07/08/10/11, BIR01/03, BAP01/02/03) were reverted
    # to optional.
    @pytest.mark.parametrize("field", [
        "BG06", "BG14", "BAP05", "BCL03", "BCL04", "BCL05",
    ])
    def test_missing_required_field_raises(self, field):
        kwargs = _valid_kwargs()
        kwargs.pop(field)
        with pytest.raises(ValidationError):
            Bridge(**kwargs)

    def test_curb_to_curb_must_be_positive(self):
        # BG06 (1232 FHWA findings): "either null or not a value greater than 0"
        with pytest.raises(ValidationError):
            make_bridge(BG06=0)


# --------------------------------------------------------------------------- #
# Conditional requiredness & cross-field rules (B2 / C / D / E)
# --------------------------------------------------------------------------- #
class TestConditionalAndCrossField:
    @pytest.mark.parametrize("field", [
        "BH02", "BH06", "BH09", "BH11", "BH13", "BH16", "BH17",
    ])
    def test_highway_feature_requires_sub_items(self, field):
        with pytest.raises(ValidationError):
            make_bridge(Features=[_highway_feature(**{field: None})])

    @pytest.mark.parametrize("location", ["C", "T", "L"])
    @pytest.mark.parametrize("field", ["BH02", "BH06", "BH09", "BH11", "BH13", "BH17"])
    def test_carried_only_items_required_on_every_carried_location(self, location, field):
        with pytest.raises(ValidationError):
            make_bridge(Features=[_highway_feature(BF02=location, **{field: None})])

    @pytest.mark.parametrize("field", ["BH02", "BH06", "BH09", "BH11", "BH13", "BH17"])
    def test_carried_only_items_tolerated_under_the_bridge(self, field):
        # FHWA checks these six only on the carried feature (B.F.02 C/T/L);
        # a road under the bridge (B) or above it (A) may leave them blank.
        for location in ("B", "A"):
            b = make_bridge(Features=[_highway_feature(BF02=location, **{field: None})])
            assert getattr(b.Features[0], field) is None

    def test_bh16_required_on_highway_features_under_the_bridge(self):
        # BH16 is the one item FHWA flags on under-features too (222 of 276 OH rows)
        with pytest.raises(ValidationError):
            make_bridge(Features=[_highway_feature(BF02="B", BH16=None)])

    def test_navigable_waterway_requires_clearances(self):
        # BN01 = 'Y' -> navigation clearances (BN02/BN04/BN06) required
        with pytest.raises(ValidationError):
            make_bridge(
                Features=[Feature(BF01="W01", BN01="Y")], BC09="5")
        b = make_bridge(
            Features=[Feature(BF01="W01", BN01="Y", BN02=20.0, BN04=100.0,
                              BN06="0")],
            BC09="5")
        assert b.Features[0].BN02 == 20.0

    def test_span_set_requires_core_items(self):
        with pytest.raises(ValidationError):
            make_bridge(SpanSets=[SpanSet(BSP01="M01", BSP06="G01")])

    def test_deck_items_skipped_for_pipe_culvert(self):
        # P01 pipe culvert needs no BSP09/BSP12 (no deck)
        b = make_bridge(
            SpanSets=[SpanSet(BSP01="C01", BSP02=1, BSP04="C01", BSP05="7",
                              BSP06="P01")],
            SubstructureSets=None, BC04="5")
        assert b.SpanSets[0].BSP06 == "P01"

    def test_zero_beam_lines_only_for_pipe(self):
        with pytest.raises(ValidationError):
            make_bridge(SpanSets=[SpanSet(BSP01="M01", BSP02=2, BSP03=0,
                                          BSP04="S01", BSP05="1", BSP06="G01",
                                          BSP09="C01", BSP12="R01")])

    def test_posting_value_not_reported_for_type_c(self):
        with pytest.raises(ValidationError):
            PostingEvaluation(BEP01="X", BEP03="C", BEP04="10")

    def test_out_to_out_not_less_than_curb_to_curb(self):
        # out-to-out < curb-to-curb is invalid; equal is allowed (FHWA tolerates)
        with pytest.raises(ValidationError):
            make_bridge(BG05=30.0, BG06=35.0)
        assert make_bridge(BG05=30.0, BG06=30.0).BG05 == 30.0   # equal is ok
        # ...and even less-than is ok on a sidehill bridge
        assert make_bridge(BG05=30.0, BG06=35.0, BG14="Y").BG14 == "Y"

    def test_channel_rating_requires_waterway_consistency(self):
        # waterway feature but BC09 = 'N' -> error
        with pytest.raises(ValidationError):
            make_bridge(Features=[Feature(BF01="W01", BN01="N")], BC09="N")
        # no waterway feature but BC09 is a number -> error
        with pytest.raises(ValidationError):
            make_bridge(BC09="5")

    def test_crossing_bridge_number_differs(self):
        with pytest.raises(ValidationError):
            make_bridge(Features=[_highway_feature(BH18="0100226")])  # == BID01

    def test_work_year_not_before_built(self):
        with pytest.raises(ValidationError):
            make_bridge(BW01=1990, Works=[Work(BW02=1985)])

    def test_irregular_deck_area_one_decimal(self):
        with pytest.raises(ValidationError):
            make_bridge(BG15=12.55)
        assert make_bridge(BG15=12.5).BG15 == 12.5