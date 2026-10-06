#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrR (AASHTOWare Bridge Rating) wrapper in ``apis``: pydantic rating
models, the vehicle/design-method code tables, secrets.json discovery,
engine construction from a URL or from secrets, and ``BrRBridge`` run
against the module's own SQL on an in-memory SQLite ``BRIDGEWARE`` schema.
The controlling-rating query uses Oracle-only ``FETCH FIRST`` so it is
driven through a recording engine double; the per-query error isolation
in ``_populate`` is checked the same way."""

import logging

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from civilpy.state.ohio.DOT import apis
from civilpy.state.ohio.DOT.apis import (
    BRR_DESIGN_METHOD_MAP, BRR_VEHICLE_MAP, BrRBridge, ControllingRating,
    MemberCapacity, RatingMethod, VehicleLoad, _create_brr_engine, _load_secrets,
)
from tests.state.ohio.DOT.conftest import BRR_SFN


# --- models ------------------------------------------------------------------

def test_rating_method_enum_is_the_three_aashto_methods():
    assert [m.value for m in RatingMethod] == ["ASR", "LFR", "LRFD"]
    assert RatingMethod("LRFD") is RatingMethod.LRFD
    assert isinstance(RatingMethod.LFR, str)


def test_controlling_rating_defaults_to_all_none_and_coerces_method():
    cr = ControllingRating()
    assert cr.model_dump() == {k: None for k in cr.model_dump()}
    cr = ControllingRating(inventory_rf="0.95", rating_method="LFR", span_num="2")
    assert cr.inventory_rf == 0.95
    assert cr.rating_method is RatingMethod.LFR
    assert cr.span_num == 2


def test_controlling_rating_rejects_unknown_method():
    with pytest.raises(ValidationError):
        ControllingRating(rating_method="WSD")


def test_member_capacity_requires_a_string_point_id():
    with pytest.raises(ValidationError):
        MemberCapacity()
    with pytest.raises(ValidationError):
        MemberCapacity(point_id=7)  # DB returns ints; the client must str() them
    mc = MemberCapacity(point_id="7", span="1", dist="25.5", design_method_type="3")
    assert (mc.span, mc.dist, mc.design_method_type) == (1, 25.5, 3)
    assert mc.member_id is None and mc.inv_rf is None


def test_vehicle_load_requires_id_and_name():
    with pytest.raises(ValidationError):
        VehicleLoad(vehicle_id=1)
    v = VehicleLoad(vehicle_id="4", name="Type 3S2")
    assert v.vehicle_id == 4 and v.gross_weight is None


def test_brr_code_tables():
    assert len(BRR_VEHICLE_MAP) == 16
    assert BRR_VEHICLE_MAP[1] == "HL-93"
    assert BRR_VEHICLE_MAP[4] == "Type 3S2"
    assert BRR_VEHICLE_MAP[16] == "PL 65T"
    assert len(set(BRR_VEHICLE_MAP.values())) == 16
    assert BRR_DESIGN_METHOD_MAP == {1: "ASR", 2: "LFR", 3: "LRFD"}
    assert set(BRR_DESIGN_METHOD_MAP.values()) == set(RatingMethod.__members__)


# --- secrets ------------------------------------------------------------------

def test_load_secrets_prefers_home(secrets, home, tmp_path):
    secrets(BRR_ORACLE_USER="dane")
    (tmp_path / "cwd" / "secrets.json").write_text('{"BRR_ORACLE_USER": "cwd"}')
    assert _load_secrets() == {"BRR_ORACLE_USER": "dane"}


def test_load_secrets_falls_back_to_cwd(home, tmp_path):
    (tmp_path / "cwd" / "secrets.json").write_text('{"MIDAS_API_KEY": "k"}')
    assert _load_secrets() == {"MIDAS_API_KEY": "k"}


def test_load_secrets_missing_everywhere(home):
    with pytest.raises(FileNotFoundError, match="secrets.json"):
        _load_secrets()


# --- engine construction -------------------------------------------------------

def test_create_brr_engine_from_url():
    engine = _create_brr_engine("sqlite://")
    assert isinstance(engine, Engine)
    assert engine.dialect.name == "sqlite"


def test_create_brr_engine_builds_oracle_url_from_secrets(secrets, monkeypatch):
    secrets(BRR_ORACLE_HOST="brr-db.example.test", BRR_ORACLE_PORT="1522",
            BRR_ORACLE_SERVICE="BRRPRD", BRR_ORACLE_USER="bridgeware", BRR_ORACLE_PASSWORD="s3cret")
    seen = []
    monkeypatch.setattr("sqlalchemy.create_engine", lambda url: seen.append(url) or "ENGINE")
    assert _create_brr_engine() == "ENGINE"
    assert seen == ["oracle+oracledb://bridgeware:s3cret@brr-db.example.test:1522/?service_name=BRRPRD"]


def test_create_brr_engine_secret_defaults(secrets, monkeypatch):
    secrets()
    seen = []
    monkeypatch.setattr("sqlalchemy.create_engine", lambda url: seen.append(url))
    _create_brr_engine()
    assert seen == ["oracle+oracledb://:@localhost:1521/?service_name=BRR"]


def test_create_brr_engine_without_secrets_raises(home):
    with pytest.raises(FileNotFoundError):
        _create_brr_engine()


# --- BrRBridge against SQLite ---------------------------------------------------

@pytest.fixture
def bridge(brr_seeded, caplog):
    caplog.set_level(logging.DEBUG, logger=apis.logger.name)
    return BrRBridge(f"  {BRR_SFN} ", engine=brr_seeded)


def test_bridge_id_is_stripped_and_engine_kept(bridge, brr_seeded):
    assert bridge.bridge_id == BRR_SFN
    assert bridge.engine is brr_seeded


def test_nbi_info_maps_every_column(bridge):
    assert bridge.nbi_info == {
        "brkey": "K000123", "bridge_id": BRR_SFN, "struct_num": "DEL-00003-1234",
        "name": "ALUM CREEK BRIDGE", "feature_intersected": "ALUM CREEK",
        "facility": "SR 3", "location": "2.1 MI N OF SUNBURY",
        "district": "06", "county": "DEL", "owner": "01", "custodian": "01",
        "year_built": 2005, "rating_date": "2024-06-15",
        "operating_load": 54.0, "operating_type": "1",
        "inventory_load": 36.0, "inventory_type": "1",
        "posting": "A", "notes": "Routine 2024",
    }


def test_member_capacities_joined_through_interest_points_in_member_order(bridge):
    caps = bridge.member_capacities
    assert [(c.member_id, c.point_id, c.span, c.dist) for c in caps] == [
        ("G1", "1", 1, 0.0), ("G1", "2", 1, 25.5), ("G2", "1", 2, 10.0),
    ]
    assert all(isinstance(c, MemberCapacity) for c in caps)
    g1_mid = caps[1]
    assert (g1_mid.inv_rf, g1_mid.opr_rf) == (0.95, 1.23)
    assert (g1_mid.inv_capacity, g1_mid.opr_capacity) == (1210.0, 1568.0)
    assert g1_mid.vehicle_name == "HL-93"
    assert g1_mid.design_method_type == 3
    assert caps[2].vehicle_name == "Type 3S2"
    # the other bridge's event (601) never leaks in
    assert all(c.inv_capacity != 1.0 for c in caps)


def test_vehicle_loads_only_vehicles_used_by_this_bridge(bridge):
    assert [(v.vehicle_id, v.name, v.gross_weight) for v in bridge.vehicle_loads] == [
        (1, "HL-93", 72.0), (4, "Type 3S2", 72.0), (15, "PL 60T", 120.0),
    ]


def test_controlling_rating_query_is_oracle_only_so_sqlite_leaves_defaults(brr_seeded, caplog):
    # FETCH FIRST n ROWS ONLY is not SQLite syntax: the query fails, is logged,
    # and the other three fetches still populate.
    caplog.set_level(logging.ERROR, logger=apis.logger.name)
    bridge = BrRBridge(BRR_SFN, engine=brr_seeded)
    assert bridge.controlling_rating == ControllingRating()
    assert any("Failed to fetch controlling rating" in r.message and r.levelno == logging.ERROR
               for r in caplog.records)
    assert bridge.nbi_info["brkey"] == "K000123"
    assert len(bridge.member_capacities) == 3


def test_get_all_rating_summaries_sorted_by_inv_rf_with_method_names(bridge):
    rows = bridge.get_all_rating_summaries()
    assert [r["inv_rf"] for r in rows] == [0.80, 0.95, 1.42]
    assert rows[0] == {
        "inv_rf": 0.80, "opr_rf": 1.04, "post_rf": None, "safe_rf": None,
        "legal_inv_rf": None, "legal_opr_rf": None,
        "permit_inv_rf": 0.80, "permit_opr_rf": 1.04,
        "vehicle": "PL 60T", "design_method": "7",   # unknown code falls back to str
        "inv_limit_state": "SERVICE-II", "opr_limit_state": "SERVICE-II",
        "span_num": 2, "member_id": "G2",
    }
    assert rows[1]["design_method"] == "LRFD" and rows[1]["member_id"] == "G1"
    assert rows[2]["design_method"] == "LFR" and rows[2]["legal_opr_rf"] == 1.90


def test_get_roadway_info_uses_brkey_from_nbi(bridge):
    roads = bridge.get_roadway_info()
    assert roads == [
        {"on_under": "1", "kind_highway": "1", "level_service": "1", "route_num": "00003",
         "roadway_name": "SR 3", "adt": 12500, "adt_year": 2023, "truck_pct": 8.5},
        {"on_under": "2", "kind_highway": "2", "level_service": "2", "route_num": None,
         "roadway_name": "ALUM CREEK TRAIL", "adt": 300, "adt_year": 2023, "truck_pct": 0.0},
    ]


def test_get_roadway_info_without_brkey_returns_empty(brr_engine):
    bridge = BrRBridge("0000000", engine=brr_engine)   # tables exist, no rows
    assert bridge.nbi_info == {}
    assert bridge.get_roadway_info() == []
    assert bridge.member_capacities == [] and bridge.vehicle_loads == []


def test_repr_uses_name_and_counts(bridge):
    text = repr(bridge)
    assert text.startswith(f"BrRBridge('{BRR_SFN}', 'ALUM CREEK BRIDGE')\n")
    assert "Inventory RF: None" in text
    assert "Member Capacities: 3 points" in text
    assert "Vehicle Loads:     3 vehicles" in text


def test_repr_falls_back_to_facility_then_nothing(brr_engine, fake_engine_cls):
    nbi_row = ("K1", "1", None, None, "X", "US 23") + (None,) * 13
    bridge = BrRBridge("1", engine=fake_engine_cls({"FROM BRIDGEWARE.BRIDGE": [nbi_row]}))
    assert repr(bridge).startswith("BrRBridge('1', 'US 23')\n")
    bare = BrRBridge("1", engine=brr_engine)
    assert repr(bare).startswith("BrRBridge('1')\n")


def test_connection_string_path_builds_engine(home, caplog):
    caplog.set_level(logging.ERROR, logger=apis.logger.name)
    bridge = BrRBridge(BRR_SFN, connection_string="sqlite://")
    assert bridge.engine.dialect.name == "sqlite"
    # no BRIDGEWARE schema on a bare engine: every fetch fails but is isolated
    assert bridge.nbi_info == {}
    assert sum("Failed to fetch" in r.message for r in caplog.records) == 4


# --- controlling rating via engine double ----------------------------------------

CONTROLLING_ROW = (0.95, 1.23, 1.10, 0.90, 1.05, 1.30, "HL-93", 3, "STRENGTH-I", 1, 0.5)


def test_controlling_rating_parsed_and_bound_to_sfn(fake_engine_cls):
    engine = fake_engine_cls({"FETCH FIRST 1 ROWS ONLY": [CONTROLLING_ROW]})
    bridge = BrRBridge(BRR_SFN, engine=engine)
    cr = bridge.controlling_rating
    assert cr == ControllingRating(
        inventory_rf=0.95, operating_rf=1.23, legal_rf=1.10, permit_rf=0.90,
        post_rf=1.05, safe_rf=1.30, controlling_vehicle="HL-93",
        rating_method=RatingMethod.LRFD, limit_state="STRENGTH-I", span_num=1, location=0.5,
    )
    sql, params = next(e for e in engine.executed if "FETCH FIRST" in e[0])
    assert params == {"bridge_id": BRR_SFN}
    assert "ORDER BY s.INV_RF ASC" in sql and "s.INV_RF IS NOT NULL" in sql
    assert "Method:       RatingMethod.LRFD" in repr(bridge) or "Method:       LRFD" in repr(bridge)


def test_controlling_rating_unknown_method_code_is_none(fake_engine_cls):
    row = CONTROLLING_ROW[:7] + (42,) + CONTROLLING_ROW[8:]
    bridge = BrRBridge(BRR_SFN, engine=fake_engine_cls({"FETCH FIRST": [row]}))
    assert bridge.controlling_rating.rating_method is None
    assert bridge.controlling_rating.controlling_vehicle == "HL-93"


def test_every_query_binds_the_sfn(fake_engine_cls):
    engine = fake_engine_cls()
    BrRBridge(BRR_SFN, engine=engine)
    assert len(engine.executed) == 4
    assert [p for _, p in engine.executed] == [
        {"sfn": BRR_SFN}, {"bridge_id": BRR_SFN}, {"bridge_id": BRR_SFN}, {"bridge_id": BRR_SFN},
    ]
    assert "WHERE BRIDGE_ID = :sfn" in engine.executed[0][0]
    assert all("b.AGENCY_CODE = :bridge_id" in sql for sql, _ in engine.executed[1:])


def test_populate_isolates_each_failure(fake_engine_cls, caplog):
    caplog.set_level(logging.ERROR, logger=apis.logger.name)
    boom = OperationalError("SELECT", {}, Exception("ORA-12541: no listener"))
    engine = fake_engine_cls({
        "FROM BRIDGEWARE.BRIDGE": boom,
        "FETCH FIRST": [CONTROLLING_ROW],
        "ABW_INTEREST_PT": boom,
        "SELECT DISTINCT": [(1, "HL-93", 72.0)],
    })
    bridge = BrRBridge(BRR_SFN, engine=engine)
    assert bridge.nbi_info == {}
    assert bridge.controlling_rating.inventory_rf == 0.95
    assert bridge.member_capacities == []
    assert [v.name for v in bridge.vehicle_loads] == ["HL-93"]
    msgs = [r.message for r in caplog.records]
    assert any(m.startswith("CRITICAL: Failed to fetch NBI info") for m in msgs)
    assert any("Failed to fetch member capacities" in m for m in msgs)
    assert not any("controlling rating" in m or "vehicle loads" in m for m in msgs)
