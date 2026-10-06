#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Shared fixtures for the ``civilpy.state.ohio.DOT.apis`` tests.

Nothing here opens a socket. ``requests.get`` and ``requests.Session`` are
swapped for a :class:`Transport` that routes by URL substring, records every
call (URL, params, json body, timeout) and answers with canned payloads, so
tests can assert the exact request each client sends. The BrR Oracle schema
is stood up in an in-memory SQLite engine with ``BRIDGEWARE`` attached as a
schema so the module's schema-qualified SQL runs unmodified; the one query
that uses Oracle-only ``FETCH FIRST`` syntax is driven through
:class:`FakeEngine` instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from civilpy.state.ohio.DOT import apis


# ---------------------------------------------------------------------------
# Fake HTTP transport
# ---------------------------------------------------------------------------

class UnroutedRequest(Exception):
    """The code under test hit a URL the test did not register."""


class FakeResponse:
    """Just enough of ``requests.Response`` for the clients in ``apis``."""

    def __init__(self, payload=None, status: int = 200, text: Optional[str] = None,
                 json_error: bool = False):
        self._payload = payload
        self.status_code = status
        self._json_error = json_error
        if text is not None:
            self.text = text
        elif payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = ""

    def json(self):
        if self._json_error:
            raise requests.exceptions.JSONDecodeError("Expecting value", self.text, 0)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


@dataclass
class Call:
    method: str
    url: str
    kwargs: Dict[str, Any] = field(default_factory=dict)

    @property
    def params(self):
        return self.kwargs.get("params")

    @property
    def json(self):
        return self.kwargs.get("json")

    @property
    def timeout(self):
        return self.kwargs.get("timeout")


@dataclass
class Route:
    needle: str
    method: Optional[str]
    response: Optional[FakeResponse]
    exc: Optional[BaseException]


class Transport:
    """Routes fake HTTP calls by URL substring and records every call."""

    def __init__(self):
        self.routes: List[Route] = []
        self.calls: List[Call] = []
        self.sessions: List["FakeSession"] = []

    def add(self, needle: str, payload=None, *, status: int = 200, method: Optional[str] = None,
            text: Optional[str] = None, json_error: bool = False,
            exc: Optional[BaseException] = None) -> "Transport":
        resp = None if exc is not None else FakeResponse(payload, status=status, text=text,
                                                         json_error=json_error)
        self.routes.append(Route(needle, method, resp, exc))
        return self

    def __call__(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append(Call(method, url, kwargs))
        for route in self.routes:
            if route.needle in url and (route.method is None or route.method == method):
                if route.exc is not None:
                    raise route.exc
                return route.response
        raise UnroutedRequest(f"{method} {url}")

    # --- inspection helpers -------------------------------------------------
    @property
    def urls(self) -> List[str]:
        return [c.url for c in self.calls]

    @property
    def last(self) -> Call:
        return self.calls[-1]

    def calls_to(self, needle: str) -> List[Call]:
        return [c for c in self.calls if needle in c.url]


class FakeSession:
    """Stand-in for ``requests.Session`` bound to a :class:`Transport`."""

    def __init__(self, transport: Transport):
        self._transport = transport
        self.headers: Dict[str, str] = {}
        self.auth = None

    def get(self, url, **kw):
        return self._transport("GET", url, **kw)

    def post(self, url, **kw):
        return self._transport("POST", url, **kw)

    def put(self, url, **kw):
        return self._transport("PUT", url, **kw)

    def delete(self, url, **kw):
        return self._transport("DELETE", url, **kw)


@pytest.fixture
def transport() -> Transport:
    return Transport()


@pytest.fixture
def fake_get(transport, monkeypatch) -> Transport:
    """Patch the module-level ``requests.get`` the ArcGIS/USGS/Django clients use."""
    monkeypatch.setattr(apis.requests, "get", lambda url, **kw: transport("GET", url, **kw))
    return transport


@pytest.fixture
def fake_session(transport, monkeypatch) -> Transport:
    """Patch ``requests.Session`` for the AssetWise and Midas clients."""
    def factory():
        session = FakeSession(transport)
        transport.sessions.append(session)
        return session

    monkeypatch.setattr(apis.requests, "Session", factory)
    return transport


# ---------------------------------------------------------------------------
# secrets.json
# ---------------------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """Redirect ``Path.home()`` and the cwd to empty temp dirs."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.chdir(cwd)
    return home_dir


@pytest.fixture
def secrets(home):
    """Write ``~/secrets.json`` with the given keys; returns the dict written."""
    def write(**values):
        (home / "secrets.json").write_text(json.dumps(values))
        return values
    return write


# ---------------------------------------------------------------------------
# BrR: in-memory SQLite with a BRIDGEWARE schema
# ---------------------------------------------------------------------------

BRR_DDL = [
    """CREATE TABLE BRIDGEWARE.BRIDGE (
        BRKEY TEXT, BRIDGE_ID TEXT, STRUCT_NUM TEXT, STRUCNAME TEXT,
        FEATINT TEXT, FACILITY TEXT, LOCATION TEXT,
        DISTRICT TEXT, COUNTY TEXT, OWNER TEXT, CUSTODIAN TEXT,
        YEARBUILT INTEGER, RATINGDATE TEXT,
        ORLOAD REAL, ORTYPE TEXT, IRLOAD REAL, IRTYPE TEXT, POSTING TEXT,
        NOTES TEXT)""",
    """CREATE TABLE BRIDGEWARE.ROADWAY (
        BRKEY TEXT, ON_UNDER TEXT, KIND_HIGHWAY TEXT, LEVEL_SERVICE TEXT,
        ROUTENUM TEXT, ROADWAY_NAME TEXT, ADTTOTAL INTEGER, ADTYEAR INTEGER,
        TRUCKPCT REAL)""",
    "CREATE TABLE BRIDGEWARE.ABW_BRIDGE (BRIDGE_ID INTEGER, AGENCY_CODE TEXT)",
    """CREATE TABLE BRIDGEWARE.ABW_SPNG_MBR_ALT_EVENTS (
        SPNG_MBR_ALT_EVENT_ID INTEGER, BRIDGE_ID INTEGER, SUPER_STRUCT_MBR_ID TEXT)""",
    """CREATE TABLE BRIDGEWARE.ABW_RATING_RESULTS_SUMMARY (
        SPNG_MBR_ALT_EVENT_ID INTEGER, VEHICLE_ID INTEGER,
        INV_RF REAL, OPR_RF REAL, LEGAL_INV_RF REAL, LEGAL_OPR_RF REAL,
        PERMIT_INV_RF REAL, PERMIT_OPR_RF REAL, POST_RF REAL, SAFE_RF REAL,
        DESIGN_METHOD_TYPE INTEGER, INV_LIMIT_STATE TEXT, OPR_LIMIT_STATE TEXT,
        SPAN_NUM INTEGER, INV_LOCATION REAL)""",
    "CREATE TABLE BRIDGEWARE.ABW_LIB_VEHICLE (VEHICLE_ID INTEGER, NAME TEXT, VEHICLE_WEIGHT REAL)",
    """CREATE TABLE BRIDGEWARE.ABW_INTEREST_PT (
        SPNG_MBR_ALT_EVENT_ID INTEGER, POINT_ID INTEGER, SPAN INTEGER, DIST REAL)""",
    """CREATE TABLE BRIDGEWARE.ABW_RATING_RESULTS (
        SPNG_MBR_ALT_EVENT_ID INTEGER, POINT_ID INTEGER, VEHICLE_ID INTEGER,
        INV_RF REAL, OPR_RF REAL, INV_CAPACITY REAL, OPR_CAPACITY REAL,
        INV_LIMIT_STATE TEXT, OPR_LIMIT_STATE TEXT, DESIGN_METHOD_TYPE INTEGER)""",
]

BRR_SFN = "2102226"

BRR_SEED = {
    "BRIDGE": [
        ("K000123", BRR_SFN, "DEL-00003-1234", "ALUM CREEK BRIDGE", "ALUM CREEK",
         "SR 3", "2.1 MI N OF SUNBURY", "06", "DEL", "01", "01",
         2005, "2024-06-15", 54.0, "1", 36.0, "1", "A", "Routine 2024"),
    ],
    "ROADWAY": [
        ("K000123", "1", "1", "1", "00003", "SR 3", 12500, 2023, 8.5),
        ("K000123", "2", "2", "2", None, "ALUM CREEK TRAIL", 300, 2023, 0.0),
    ],
    "ABW_BRIDGE": [(10, BRR_SFN), (11, "9999999")],
    "ABW_SPNG_MBR_ALT_EVENTS": [(501, 10, "G1"), (502, 10, "G2"), (601, 11, "X1")],
    "ABW_LIB_VEHICLE": [(1, "HL-93", 72.0), (4, "Type 3S2", 72.0), (15, "PL 60T", 120.0),
                        (99, "UNUSED", 1.0)],
    "ABW_RATING_RESULTS_SUMMARY": [
        (501, 1, 0.95, 1.23, 1.10, 1.40, 0.90, 1.20, 1.05, 1.30, 3, "STRENGTH-I", "STRENGTH-I", 1, 0.5),
        (502, 4, 1.42, 1.84, 1.50, 1.90, 1.10, 1.45, 1.60, 1.70, 2, "FLEXURE", "FLEXURE", 2, 0.4),
        (502, 15, 0.80, 1.04, None, None, 0.80, 1.04, None, None, 7, "SERVICE-II", "SERVICE-II", 2, 0.5),
        (601, 1, 0.10, 0.20, None, None, None, None, None, None, 3, "OTHER", "OTHER", 1, 0.0),
    ],
    "ABW_INTEREST_PT": [(501, 1, 1, 0.0), (501, 2, 1, 25.5), (502, 1, 2, 10.0), (601, 1, 1, 0.0)],
    "ABW_RATING_RESULTS": [
        (501, 1, 1, 1.80, 2.33, 1540.0, 1995.0, "STRENGTH-I", "STRENGTH-I", 3),
        (501, 2, 1, 0.95, 1.23, 1210.0, 1568.0, "STRENGTH-I", "STRENGTH-I", 3),
        (502, 1, 4, 1.42, 1.84, 900.0, 1166.0, "FLEXURE", "FLEXURE", 2),
        (601, 1, 1, 0.10, 0.20, 1.0, 2.0, "OTHER", "OTHER", 3),
    ],
}


def _sqlite_engine():
    # StaticPool: every connect() returns the same underlying connection, so
    # the ATTACHed schema and the in-memory tables survive across connections.
    return create_engine("sqlite://", poolclass=StaticPool,
                         connect_args={"check_same_thread": False})


@pytest.fixture
def brr_engine():
    """Empty BRIDGEWARE schema in SQLite (tables exist, no rows)."""
    engine = _sqlite_engine()
    with engine.begin() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS BRIDGEWARE"))
        for ddl in BRR_DDL:
            conn.execute(text(ddl))
    return engine


@pytest.fixture
def brr_seeded(brr_engine):
    """BRIDGEWARE schema populated with one rated bridge (SFN 2102226)."""
    with brr_engine.begin() as conn:
        for table, rows in BRR_SEED.items():
            for row in rows:
                placeholders = ", ".join(f":p{i}" for i in range(len(row)))
                conn.execute(
                    text(f"INSERT INTO BRIDGEWARE.{table} VALUES ({placeholders})"),
                    {f"p{i}": v for i, v in enumerate(row)},
                )
    return brr_engine


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, engine: "FakeEngine"):
        self._engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        sql = str(query)
        self._engine.executed.append((sql, params))
        for needle, rows in self._engine.rows.items():
            if needle in sql:
                if isinstance(rows, BaseException):
                    raise rows
                return FakeResult(rows)
        return FakeResult([])


class FakeEngine:
    """Engine double: ``rows`` maps a SQL substring to the rows to return
    (or an exception to raise). Every executed (sql, params) is recorded."""

    def __init__(self, rows: Optional[Dict[str, Any]] = None):
        self.rows = rows or {}
        self.executed: List[tuple] = []

    def connect(self):
        return FakeConnection(self)


@pytest.fixture
def fake_engine_cls():
    return FakeEngine
