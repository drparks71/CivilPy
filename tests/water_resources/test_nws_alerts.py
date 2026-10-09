#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""NWS alerts as scour triggers: P-VTEC parsing, api.weather.gov and IEM
features to one Alert shape, hazards collapsed to their latest message,
and the severity / response classes built on them.  Synthetic messages,
no network."""

import random
from datetime import datetime, timedelta, timezone

import pytest

from civilpy.water_resources import nws_alerts as nws
from civilpy.water_resources import scour_screening as sc

T0 = datetime(2025, 4, 3, 1, 0, tzinfo=timezone.utc)
SQUARE = {"type": "Polygon", "coordinates": [[[-83.5, 39.0], [-83.0, 39.0], [-83.0, 39.5], [-83.5, 39.5], [-83.5, 39.0]]]}


def vtec(action, ph="FF", sig="W", etn=12, begin=T0, end=T0 + timedelta(hours=3), office="KILN"):
    f = lambda t: "000000T0000Z" if t is None else t.strftime("%y%m%dT%H%MZ")     # noqa: E731
    return f"/O.{action}.{office}.{ph}.{sig}.{etn:04d}.{f(begin)}-{f(end)}/"


def nws_feature(action="NEW", sent=T0, ph="FF", sig="W", etn=12, end=T0 + timedelta(hours=3), threat=None,
                geometry=SQUARE, same=("039027", "039071")):
    params = {"VTEC": [vtec(action, ph, sig, etn, end=end)]}
    if threat:
        params["flashFloodDamageThreat"] = [threat]
    return {"id": f"urn:{action}:{sent.isoformat()}", "geometry": geometry, "properties": {
        "id": f"urn:{action}:{sent.isoformat()}", "event": "Flash Flood Warning", "sent": sent.isoformat(),
        "areaDesc": "Clinton, OH; Highland, OH", "geocode": {"SAME": list(same)}, "parameters": params,
        "headline": "Flash Flood Warning issued", "expires": (sent + timedelta(hours=1)).isoformat()}}


@pytest.mark.parametrize("action", ["NEW", "CON", "EXT", "CAN", "EXP"])
@pytest.mark.parametrize("ph,sig", [("FF", "W"), ("FA", "W"), ("FL", "W"), ("FA", "A"), ("FL", "Y")])
def test_vtec_roundtrip(action, ph, sig):
    v = nws.parse_vtec("text " + vtec(action, ph, sig) + " more")
    assert len(v) == 1
    v = v[0]
    assert (v["action"], v["phenomena"], v["significance"], v["etn"]) == (action, ph, sig, 12)
    assert v["begin"] == T0 and v["end"] == T0 + timedelta(hours=3)


def test_vtec_open_begin_is_none():
    assert nws.parse_vtec(vtec("CON", begin=None))[0]["begin"] is None


@pytest.mark.parametrize("ph,sig,warning,watch", [("FF", "W", True, False), ("FA", "W", True, False),
                                                  ("FL", "W", True, False), ("FA", "A", False, True),
                                                  ("FL", "Y", False, False)])
def test_nws_feature(ph, sig, warning, watch):
    a, = nws.from_nws_feature(nws_feature(ph=ph, sig=sig, threat="CONSIDERABLE"))
    assert a.key == f"KILN.{ph}.{sig}.0012.2025" and a.source == "nws"
    assert a.is_flood_warning is warning and a.is_flood_watch is watch
    assert a.county_fips() == {27, 71} and a.county_fips("21") == set()
    assert len(a.polygons) == 1 and a.damage_threat == "CONSIDERABLE" and not a.emergency
    assert nws.from_nws_feature(nws_feature(threat="CATASTROPHIC"))[0].emergency


def test_iem_feature_matches_nws_key():
    iem = {"geometry": SQUARE, "properties": {"wfo": "ILN", "phenomena": "FF", "significance": "W", "eventid": 12,
                                              "year": 2025, "status": "NEW", "issue": T0.isoformat(),
                                              "polygon_begin": T0.isoformat(),
                                              "polygon_end": (T0 + timedelta(hours=3)).isoformat(),
                                              "ps": "Flash Flood Warning", "is_emergency": True}}
    a = nws.from_iem_feature(iem)
    assert a.key == nws.from_nws_feature(nws_feature())[0].key
    assert a.emergency and a.is_flood_warning and a.ends == T0 + timedelta(hours=3)


def iem_message(status, begin, expire, polygon_end=None, eventid=68):
    return {"geometry": SQUARE, "properties": {
        "wfo": "ILN", "phenomena": "FL", "significance": "W", "eventid": eventid, "year": 2026, "status": status,
        "utc_issue": T0.isoformat(), "utc_polygon_begin": begin.isoformat(), "utc_expire": expire.isoformat(),
        "utc_polygon_end": (polygon_end or expire).isoformat(), "event_label": "Flood Warning",
        "product_id": f"{begin:%Y%m%d%H%M}-KILN-FLWILN"}}


@pytest.mark.parametrize("seed", range(10))
def test_iem_interval_messages_run_the_warning_its_full_length(seed):
    """IEM's polygon_end is only when the next message replaced the polygon;
    replayed through current(), a warning extended and then cancelled is in
    force from NEW until the cancel, as it was live."""
    rng = random.Random(seed)
    t, expire, feats = T0, T0 + timedelta(hours=rng.randint(6, 30)), []
    for status in ["NEW"] + ["EXT" if rng.random() < 0.5 else "CON" for _ in range(rng.randint(0, 4))]:
        if status == "EXT":
            expire += timedelta(hours=rng.randint(2, 12))
        nxt = t + timedelta(hours=rng.randint(1, 5))
        feats.append(iem_message(status, t, expire, polygon_end=min(nxt, expire)))
        if nxt >= expire:                                          # updates come before the warning runs out
            break
        t = nxt
    cancel = nxt if rng.random() < 0.5 and nxt < expire else None
    if cancel:
        feats.append(iem_message("CAN", cancel, cancel))
    alerts = [nws.from_iem_feature(f) for f in feats]
    assert len({a.key for a in alerts}) == 1 and len({a.message_id for a in alerts}) == len(alerts)
    stop = cancel or expire
    for h in range(0, 60):
        at = T0 + timedelta(hours=h, minutes=30)
        assert (alerts[0].key in nws.current(alerts, at)) == (at < stop)


@pytest.mark.parametrize("seed", range(10))
def test_current_follows_the_latest_message(seed):
    """A hazard is in force from its first message until it is cancelled /
    expired or its end time passes; later messages move the end."""
    rng = random.Random(seed)
    msgs, end, t, ended_at = [], T0 + timedelta(hours=3), T0, None
    msgs.append(nws.from_nws_feature(nws_feature("NEW", sent=t, end=end))[0])
    for _ in range(rng.randint(0, 4)):
        t += timedelta(minutes=rng.randint(20, 120))
        if t > end:
            break
        if rng.random() < 0.3:
            msgs.append(nws.from_nws_feature(nws_feature("CAN", sent=t, end=end))[0])
            ended_at = t
            break
        end += timedelta(hours=rng.randint(0, 3))
        msgs.append(nws.from_nws_feature(nws_feature("EXT", sent=t, end=end))[0])
    rng.shuffle(msgs)
    stop = ended_at or end
    for minutes in range(-30, 12 * 60, 17):
        at = T0 + timedelta(minutes=minutes)
        live = nws.current(msgs, at)
        expect = T0 <= at <= stop and not (ended_at and at >= ended_at)
        assert (len(live) == 1) == expect, (at, stop)
        assert len(nws.current(msgs, at, grace=timedelta(hours=24))) == (1 if T0 <= at else 0)


@pytest.mark.parametrize("ari", [None, 0.5, 1.5, 3, 9.9, 10, 24, 25, 99, 100, 500])
@pytest.mark.parametrize("threat", [None, "CONSIDERABLE", "CATASTROPHIC"])
def test_severity_monotone_and_raised_by_threat(ari, threat):
    order = sc.SEVERITY_ORDER
    s, s0 = sc.storm_severity(ari, threat), sc.storm_severity(ari)
    assert order.index(s) >= order.index(s0)
    if threat == "CATASTROPHIC":
        assert s == "extreme"
    if threat == "CONSIDERABLE":
        assert order.index(s) >= order.index("severe")
    if ari:
        assert order.index(sc.storm_severity(ari * 2)) >= order.index(s0)


@pytest.mark.parametrize("ari", [1.5, 5, 10, 25, 50, 100, 300])
@pytest.mark.parametrize("b3", ["A", "B", "0", "U", "C", "D"])
@pytest.mark.parametrize("bc11", ["8", "6", "4", "2"])
@pytest.mark.parametrize("bap02", ["0", "4", "6"])
def test_response_level_rules(ari, b3, bc11, bap02):
    r = sc.screen(sc.ScreeningInput(ari, bap03=b3, bc11=bc11, bap02=bap02))
    rank = sc.response_rank(r.response)
    assert (r.response == "none") == (r.tier == "none")
    if r.tier == "inspect":
        assert rank >= sc.response_rank("24h")
    if r.response == "immediate":
        assert r.on_record and (r.overtopping_likely or r.score >= sc.IMMEDIATE_SCORE)
    if r.tier == "watch":
        assert r.response == ("1week" if r.on_record else "monitor")
    # a rarer storm never lowers the response
    r2 = sc.screen(sc.ScreeningInput(ari * 3, bap03=b3, bc11=bc11, bap02=bap02))
    assert sc.response_rank(r2.response) >= rank
    # a flash flood emergency puts every flagged bridge at immediate
    r3 = sc.screen(sc.ScreeningInput(ari, bap03=b3, bc11=bc11, bap02=bap02, nws_damage_threat="CATASTROPHIC"))
    assert r3.response == ("immediate" if r3.tier != "none" else "none")
