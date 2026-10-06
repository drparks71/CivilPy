#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Midas Civil objects in ``apis``: the pydantic model classes (node,
material, section, element connectivity, boundary, load cases, result),
``MidasAPIConnection`` (MAPI-Key session, verb -> URL/body mapping,
HTTP errors raised), ``MidasBridge`` parsing of each ``/civil/db/*``
table into keyed dicts (wrapper-key tolerant, unknown element types fall
back to BEAM, per-table failures isolated), the element length / material
/ section lookups, and the Ohio standard vehicle table."""

import logging
import math

import pytest
import requests
from pydantic import ValidationError

from civilpy.state.ohio.DOT import apis
from civilpy.state.ohio.DOT.apis import (
    OHIO_STANDARD_VEHICLES, ElementType, LoadType, MidasAPIConnection, MidasBoundary,
    MidasBridge, MidasElement, MidasMaterial, MidasMovingLoad, MidasNode, MidasResult,
    MidasSection, MidasStaticLoad, _calculate_3d_distance,
)
from tests.state.ohio.DOT.apis_fixtures import midas_tables

BASE = "https://api-v2.midasit.com"


# --- models -----------------------------------------------------------------------

def test_node_coordinates_are_floats():
    n = MidasNode(id="7", x=1, y="2.5", z=0)
    assert (n.id, n.x, n.y, n.z) == (7, 1.0, 2.5, 0.0)
    with pytest.raises(ValidationError):
        MidasNode(id=1, x="north", y=0, z=0)
    with pytest.raises(ValidationError):
        MidasNode(id=1, x=0, y=0)


def test_material_and_section_optional_properties():
    m = MidasMaterial(id=1)
    assert (m.name, m.material_type, m.elastic_modulus, m.density) == ("", "", None, None)
    s = MidasSection(id=2, area="44.3")
    assert s.area == 44.3 and s.iyy is None and s.shape == ""


def test_element_connectivity_properties():
    assert MidasElement(id=1).node_ids == []
    assert MidasElement(id=1).start_node_id is None
    assert MidasElement(id=1).end_node_id is None
    one = MidasElement(id=1, node_ids=[5])
    assert (one.start_node_id, one.end_node_id) == (5, None)
    two = MidasElement(id=1, node_ids=[5, 6])
    assert (two.start_node_id, two.end_node_id) == (5, 6)
    plate = MidasElement(id=1, element_type="PLATE", node_ids=[1, 2, 3, 4])
    assert plate.element_type is ElementType.PLATE
    assert (plate.start_node_id, plate.end_node_id) == (1, 4)
    with pytest.raises(ValidationError):
        MidasElement(id=1, element_type="CABLE")


def test_element_type_enum_members():
    assert [e.value for e in ElementType] == \
        ["BEAM", "TRUSS", "PLATE", "SOLID", "TENDON", "SPRING", "LINK", "RIGID"]
    assert MidasElement(id=1).element_type is ElementType.BEAM


def test_boundary_and_load_defaults():
    b = MidasBoundary(node_id=1)
    assert not any([b.dx, b.dy, b.dz, b.rx, b.ry, b.rz])
    assert (b.spring_dx, b.spring_rz) == (0.0, 0.0)
    assert MidasStaticLoad(id=1).load_type is LoadType.STATIC
    mv = MidasMovingLoad(id=1)
    assert mv.load_type is LoadType.MOVING
    assert mv.dynamic_load_allowance == 33.0
    assert (mv.vehicle_load_name, mv.standard_code) == ("", "")
    r = MidasResult()
    assert r.element_id is None and r.load_case == "" and r.reaction_z is None


def test_3d_distance():
    a = MidasNode(id=1, x=0, y=0, z=0)
    b = MidasNode(id=2, x=3, y=4, z=12)
    assert _calculate_3d_distance(a, b) == 13.0
    assert _calculate_3d_distance(b, a) == 13.0
    assert _calculate_3d_distance(a, a) == 0.0


# --- connection -----------------------------------------------------------------------

def test_connection_headers_and_base_url(fake_session):
    conn = MidasAPIConnection("abc-123", base_url="http://localhost:8080/")
    assert conn.base_url == "http://localhost:8080"
    assert conn.api_key == "abc-123"
    assert fake_session.sessions[0].headers == {"MAPI-Key": "abc-123",
                                                "Content-Type": "application/json"}
    assert fake_session.sessions[0].auth is None


def test_connection_verbs(fake_session):
    fake_session.add("/civil/db/node", {"NODE": {}}, method="GET")
    fake_session.add("/civil/db/node", {"NODE": {"1": {}}}, method="POST")
    fake_session.add("/civil/db/node", {"NODE": {"1": {"X": 1}}}, method="PUT")
    fake_session.add("/civil/db/node", {"NODE": {}}, method="DELETE")
    conn = MidasAPIConnection("k")
    assert conn.get("/civil/db/node") == {"NODE": {}}
    assert conn.post("/civil/db/node", {"Assign": {"1": {"X": 0}}}) == {"NODE": {"1": {}}}
    assert conn.put("/civil/db/node", {"Assign": {"1": {"X": 1}}}) == {"NODE": {"1": {"X": 1}}}
    assert conn.delete("/civil/db/node") == {"NODE": {}}
    assert [(c.method, c.url, c.json) for c in fake_session.calls] == [
        ("GET", f"{BASE}/civil/db/node", None),
        ("POST", f"{BASE}/civil/db/node", {"Assign": {"1": {"X": 0}}}),
        ("PUT", f"{BASE}/civil/db/node", {"Assign": {"1": {"X": 1}}}),
        ("DELETE", f"{BASE}/civil/db/node", None),
    ]


def test_connection_raises_on_http_error(fake_session):
    fake_session.add("/civil/db/elem", {"message": "unauthorized"}, status=401)
    conn = MidasAPIConnection("bad")
    with pytest.raises(requests.HTTPError):
        conn.get("/civil/db/elem")
    with pytest.raises(requests.HTTPError):
        conn.post("/civil/db/elem", {})


# --- MidasBridge ----------------------------------------------------------------------

@pytest.fixture
def model(fake_session, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    for path, payload in midas_tables().items():
        fake_session.add(path, payload)
    return fake_session


def test_bridge_uses_explicit_key_without_secrets(fake_session, home):
    bridge = MidasBridge("explicit")
    assert bridge.api.api_key == "explicit"
    assert bridge.api.base_url == BASE
    assert bridge.nodes == {} and bridge.results == []


def test_bridge_reads_key_from_secrets(fake_session, secrets):
    secrets(MIDAS_API_KEY="from-secrets")
    assert MidasBridge().api.api_key == "from-secrets"
    assert MidasBridge(base_url="http://127.0.0.1:1/").api.base_url == "http://127.0.0.1:1"


def test_bridge_without_key_or_secrets_raises(fake_session, home):
    with pytest.raises(FileNotFoundError):
        MidasBridge()


def test_load_geometry_parses_nodes_materials_sections_elements(model):
    bridge = MidasBridge("k")
    bridge.load_geometry()
    assert model.urls == [f"{BASE}/civil/db/{t}" for t in ("node", "matl", "sect", "elem")]
    assert bridge.nodes[2] == MidasNode(id=2, x=3.0, y=4.0, z=12.0)
    assert set(bridge.nodes) == {1, 2, 3}

    conc = bridge.materials[1]
    assert (conc.name, conc.material_type) == ("Concrete 4.5ksi", "CONC")
    assert (conc.elastic_modulus, conc.poisson_ratio, conc.thermal_coeff, conc.density) == \
        (3824.0, 0.2, 6e-6, 0.150)
    assert bridge.materials[2].elastic_modulus is None

    w = bridge.sections[1]
    assert (w.name, w.shape, w.area, w.iyy, w.izz) == ("W36x150", "I", 44.3, 9040.0, 270.0)
    assert bridge.sections[2].shape == ""

    e1, e2, e3 = (bridge.elements[i] for i in (1, 2, 3))
    assert (e1.element_type, e1.material_id, e1.section_id, e1.node_ids) == \
        (ElementType.BEAM, 2, 1, [1, 2])
    assert (e2.element_type, e2.node_ids, e2.section_id) == (ElementType.TRUSS, [2, 3], None)
    assert e3.element_type is ElementType.BEAM     # unknown TYPE falls back
    assert e3.node_ids == [3]


def test_tables_without_wrapper_key_still_parse(fake_session):
    fake_session.add("/civil/db/node", {"1": {"X": 1.5, "Y": 0, "Z": 0}})
    fake_session.add("/civil/db/stld", {"1": {"NAME": "DC"}})
    bridge = MidasBridge("k")
    bridge._fetch_nodes()
    bridge._fetch_static_loads()
    assert bridge.nodes[1].x == 1.5
    assert bridge.static_loads[1].name == "DC"


def test_missing_coordinates_default_to_zero(fake_session):
    fake_session.add("/civil/db/node", {"NODE": {"9": {}}})
    bridge = MidasBridge("k")
    bridge._fetch_nodes()
    assert bridge.nodes[9] == MidasNode(id=9, x=0.0, y=0.0, z=0.0)


def test_load_boundaries_and_loads(model):
    bridge = MidasBridge("k")
    bridge.load_boundaries()
    bridge.load_static_loads()
    bridge.load_moving_loads()
    assert model.urls == [f"{BASE}/civil/db/{t}" for t in ("cons", "stld", "mvld")]
    pin = bridge.boundaries[1]
    assert (pin.dx, pin.dy, pin.dz, pin.rx, pin.ry, pin.rz) == (True, True, True, False, False, False)
    roller = bridge.boundaries[3]
    assert (roller.dx, roller.dy, roller.dz, roller.rx) == (False, True, True, False)
    assert bridge.boundaries[42].dz is True
    assert bridge.static_loads[1] == MidasStaticLoad(id=1, name="DC", description="Self weight")
    assert bridge.static_loads[2].description == "Wearing surface"
    mv = bridge.moving_loads[1]
    assert (mv.name, mv.description, mv.load_type) == ("HL-93", "Design truck + lane", LoadType.MOVING)


def test_load_all_hits_every_table_in_order(model):
    bridge = MidasBridge("k")
    bridge.load_all()
    assert model.urls == [f"{BASE}/civil/db/{t}"
                          for t in ("node", "matl", "sect", "elem", "cons", "stld", "mvld")]
    assert repr(bridge) == (
        "MidasBridge(\n  nodes=3,\n  elements=3,\n  materials=2,\n  sections=2,\n"
        "  boundaries=3,\n  static_loads=2,\n  moving_loads=1\n)"
    )


@pytest.mark.parametrize("table, attr, msg", [
    ("node", "nodes", "Failed to fetch nodes"),
    ("matl", "materials", "Failed to fetch materials"),
    ("sect", "sections", "Failed to fetch sections"),
    ("elem", "elements", "Failed to fetch elements"),
    ("cons", "boundaries", "Failed to fetch boundaries"),
    ("stld", "static_loads", "Failed to fetch static loads"),
    ("mvld", "moving_loads", "Failed to fetch moving loads"),
])
def test_each_table_failure_is_isolated(fake_session, caplog, table, attr, msg):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    for path, payload in midas_tables().items():
        if path.endswith(table):
            fake_session.add(path, {"message": "model not open"}, status=500)
        else:
            fake_session.add(path, payload)
    bridge = MidasBridge("k")
    bridge.load_all()
    assert getattr(bridge, attr) == {}
    assert msg in caplog.text
    populated = [a for a in ("nodes", "materials", "sections", "elements",
                             "boundaries", "static_loads", "moving_loads") if a != attr]
    assert all(getattr(bridge, a) for a in populated)


def test_bad_node_payload_is_logged_not_raised(fake_session, caplog):
    caplog.set_level(logging.WARNING, logger=apis.logger.name)
    fake_session.add("/civil/db/node", {"NODE": {"1": {"X": "abc", "Y": 0, "Z": 0}}})
    bridge = MidasBridge("k")
    bridge._fetch_nodes()
    assert bridge.nodes == {}
    assert "Failed to fetch nodes" in caplog.text


def test_element_length_material_section_lookups(model):
    bridge = MidasBridge("k")
    bridge.load_geometry()
    assert bridge.get_element_length(1) == 13.0
    assert bridge.get_element_length(2) == pytest.approx(math.sqrt(49 + 16 + 144))
    with pytest.raises(ValueError, match="Element 3 has insufficient node connectivity"):
        bridge.get_element_length(3)
    with pytest.raises(KeyError):
        bridge.get_element_length(99)
    assert bridge.get_element_material(1).name == "A709 Gr50"
    assert bridge.get_element_section(1).name == "W36x150"
    assert bridge.get_element_material(3) is None
    assert bridge.get_element_section(2) is None


def test_element_length_with_unloaded_node_raises_keyerror(model):
    bridge = MidasBridge("k")
    bridge._fetch_elements()
    with pytest.raises(KeyError):
        bridge.get_element_length(1)


def test_dangling_material_reference_returns_none(model):
    bridge = MidasBridge("k")
    bridge._fetch_elements()
    assert bridge.elements[1].material_id == 2
    assert bridge.get_element_material(1) is None


def test_supported_nodes_only_those_present_in_model(model):
    bridge = MidasBridge("k")
    bridge.load_all()
    assert [n.id for n in bridge.get_supported_nodes()] == [1, 3]   # 42 has no node


# --- Ohio standard vehicles -------------------------------------------------------------

def test_ohio_standard_vehicle_table():
    assert len(OHIO_STANDARD_VEHICLES) == 17
    assert OHIO_STANDARD_VEHICLES["HS20-FTG"] == {"standard": "AASHTO-LRFD", "dla": 15}
    assert all(v["dla"] == 33 for k, v in OHIO_STANDARD_VEHICLES.items() if k != "HS20-FTG")
    assert {v["standard"] for v in OHIO_STANDARD_VEHICLES.values()} == {
        "AASHTO-LRFD", "OHDOT LOAD", "AASHTO LEGAL/PERMIT LOAD", "FAST ACT EV LOADS", "OHDOT PERMIT",
    }
    assert OHIO_STANDARD_VEHICLES["PL 65T"]["standard"] == "OHDOT PERMIT"
