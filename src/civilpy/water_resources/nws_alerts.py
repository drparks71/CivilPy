#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""National Weather Service watches, warnings and advisories as triggers.

Two sources, one shape (:class:`Alert`):

* **api.weather.gov** - the live NWS alerts service (CAP as GeoJSON, no
  key; a ``User-Agent`` naming the caller is required).  It keeps roughly
  the last week of alerts, so a poller asks for everything *sent since its
  last check* and misses nothing even when it polls slowly.
* **Iowa Environmental Mesonet** (IEM) storm-based warning archive - every
  polygon warning since the 2000s, for replaying past storms and
  back-testing a trigger.

An NWS hazard is identified by its P-VTEC string
(``/O.NEW.KILN.FF.W.0012.250403T0100Z-250403T0400Z/``: action, office,
phenomenon, significance, event number, begin-end).  Every later message
about the same hazard (CON continue, EXT extend, CAN cancel, EXP expire,
...) carries the same office / phenomenon / significance / event number,
so :func:`current` collapses messages to the latest one per hazard.

Flood phenomena: **FF** flash flood, **FA** areal flood, **FL** river
(point) flood; significance **W** warning, **A** watch, **Y** advisory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

NWS_API = "https://api.weather.gov"
IEM_SBW = "https://mesonet.agron.iastate.edu/geojson/sbw.py"

FLOOD_WARNINGS = {("FF", "W"), ("FA", "W"), ("FL", "W")}
FLOOD_WATCHES = {("FF", "A"), ("FA", "A"), ("FL", "A")}
FLOOD_ADVISORIES = {("FA", "Y"), ("FL", "Y")}
ENDED = {"CAN", "EXP"}

_VTEC = re.compile(r"/([OTEX])\.([A-Z]{3})\.([A-Z]{4})\.([A-Z]{2})\.([A-Z])\.(\d{4})\."
                   r"(\d{6}T\d{4}Z)-(\d{6}T\d{4}Z)/")


def _utc(text) -> datetime | None:
    if not text:
        return None
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _vtec_time(s: str) -> datetime | None:
    return None if s.startswith("000000") else datetime.strptime(s, "%y%m%dT%H%MZ").replace(tzinfo=timezone.utc)


def parse_vtec(text: str) -> list[dict]:
    """Every P-VTEC string in ``text`` as a dict."""
    out = []
    for m in _VTEC.finditer(text or ""):
        cls, action, office, ph, sig, etn, b, e = m.groups()
        out.append({"class": cls, "action": action, "office": office, "phenomena": ph, "significance": sig,
                    "etn": int(etn), "begin": _vtec_time(b), "end": _vtec_time(e)})
    return out


@dataclass
class Alert:
    """One message about one hazard."""
    key: str                         # office.phenomena.significance.etn.year - the same for every message
    message_id: str
    source: str                      # "nws" | "iem"
    phenomena: str | None
    significance: str | None
    action: str                      # NEW, CON, EXT, EXA, EXB, UPG, CAN, EXP, COR, ROU
    event_name: str                  # "Flash Flood Warning"
    sent: datetime
    begins: datetime | None
    ends: datetime | None
    area_desc: str = ""
    same: list = field(default_factory=list)       # SAME codes, "039049" = Ohio (39), Franklin County (049)
    polygons: list = field(default_factory=list)   # [[[lon, lat], ...], ...] outer rings
    damage_threat: str | None = None               # flash flood damage threat tag: CONSIDERABLE / CATASTROPHIC
    emergency: bool = False                        # flash flood emergency
    headline: str = ""

    @property
    def pair(self):
        return (self.phenomena, self.significance)

    @property
    def is_flood_warning(self) -> bool:
        return self.pair in FLOOD_WARNINGS

    @property
    def is_flood_watch(self) -> bool:
        return self.pair in FLOOD_WATCHES

    def county_fips(self, state: str = "39") -> set[int]:
        """County FIPS numbers (int) this message names in ``state``."""
        out = set()
        for code in self.same:
            c = str(code).zfill(6)
            if c[1:3] == state and c[3:] != "000":
                out.add(int(c[3:]))
        return out

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ("key", "message_id", "source", "phenomena", "significance", "action",
                                           "event_name", "area_desc", "same", "polygons", "damage_threat",
                                           "emergency", "headline")}
        d.update({k: (getattr(self, k).isoformat() if getattr(self, k) else None) for k in ("sent", "begins", "ends")})
        return d


def _rings(geometry) -> list:
    if not geometry:
        return []
    t, c = geometry.get("type"), geometry.get("coordinates") or []
    if t == "Polygon":
        return [c[0]] if c else []
    if t == "MultiPolygon":
        return [p[0] for p in c if p]
    return []


def from_nws_feature(feature: dict) -> list[Alert]:
    """One api.weather.gov alert feature -> one :class:`Alert` per VTEC
    string it carries (messages without VTEC give one with no phenomenon)."""
    p = feature.get("properties", feature)
    params = p.get("parameters") or {}
    vtecs = [v for s in params.get("VTEC", []) for v in parse_vtec(s)]
    threat = (params.get("flashFloodDamageThreat") or [None])[0]
    sent = _utc(p.get("sent"))
    base = dict(message_id=p.get("id") or feature.get("id", ""), source="nws", event_name=p.get("event", ""),
                sent=sent, area_desc=p.get("areaDesc", ""), same=list((p.get("geocode") or {}).get("SAME", [])),
                polygons=_rings(feature.get("geometry")), damage_threat=threat,
                emergency=bool(threat == "CATASTROPHIC" or "EMERGENCY" in (p.get("headline") or "").upper()),
                headline=p.get("headline") or "")
    ends = _utc(p.get("ends")) or _utc(p.get("expires"))
    if not vtecs:
        return [Alert(key=base["message_id"], phenomena=None, significance=None,
                      action="CAN" if p.get("messageType") == "Cancel" else "NEW",
                      begins=_utc(p.get("onset")) or _utc(p.get("effective")), ends=ends, **base)]
    out = []
    for v in vtecs:
        key = f"{v['office']}.{v['phenomena']}.{v['significance']}.{v['etn']:04d}.{(v['begin'] or sent).year}"
        out.append(Alert(key=key, phenomena=v["phenomena"], significance=v["significance"], action=v["action"],
                         begins=v["begin"] or _utc(p.get("onset")), ends=v["end"] or ends, **base))
    return out


def from_iem_feature(feature: dict) -> Alert:
    """One IEM storm-based-warning feature -> :class:`Alert`."""
    p = feature.get("properties", feature)
    issue = _utc(p.get("issue")) or _utc(p.get("polygon_begin"))
    year = p.get("year") or issue.year
    office = str(p.get("wfo", ""))
    office = "K" + office if len(office) == 3 else office            # IEM drops the K of the VTEC office id
    key = f"{office}.{p['phenomena']}.{p['significance']}.{int(p['eventid']):04d}.{year}"
    damage = p.get("damagetag") or p.get("floodtag_damage")
    return Alert(key=key, message_id=p.get("product_id") or key, source="iem", phenomena=p.get("phenomena"),
                 significance=p.get("significance"), action=(p.get("status") or "NEW").upper(),
                 event_name=p.get("ps") or f"{p.get('phenomena')}.{p.get('significance')}",
                 sent=_utc(p.get("polygon_begin")) or issue, begins=_utc(p.get("polygon_begin")) or issue,
                 ends=_utc(p.get("polygon_end")) or _utc(p.get("expire")), area_desc=p.get("wfo", ""),
                 polygons=_rings(feature.get("geometry")), damage_threat=(damage or None) and str(damage).upper(),
                 emergency=bool(p.get("is_emergency")), headline=p.get("ps") or "")


def fetch_nws(area: str = "OH", *, start: datetime | None = None, end: datetime | None = None,
              user_agent: str, session=None, timeout: float = 60) -> list[Alert]:
    """Alerts for a state from api.weather.gov: everything sent since
    ``start`` (the service keeps about a week), or the active ones when
    ``start`` is None.  Follows pagination."""
    import requests

    s = session or requests.Session()
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    if start is None:
        url, params = f"{NWS_API}/alerts/active", {"area": area}
    else:
        url, params = f"{NWS_API}/alerts", {"area": area, "start": start.astimezone(timezone.utc)
                                            .strftime("%Y-%m-%dT%H:%M:%SZ")}
        if end is not None:
            params["end"] = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, seen = [], set()
    while url and url not in seen:
        seen.add(url)
        r = s.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        body = r.json()
        for f in body.get("features", []):
            out.extend(from_nws_feature(f))
        url, params = (body.get("pagination") or {}).get("next"), None
    return out


def fetch_iem(state: str, start: datetime, end: datetime, *, session=None, timeout: float = 120) -> list[Alert]:
    """Storm-based (polygon) warnings for a state from the IEM archive, for
    replaying a past storm."""
    import requests

    s = session or requests
    fmt = "%Y-%m-%dT%H:%MZ"
    r = s.get(IEM_SBW, params={"sts": start.astimezone(timezone.utc).strftime(fmt),
                               "ets": end.astimezone(timezone.utc).strftime(fmt), "states": state}, timeout=timeout)
    r.raise_for_status()
    return [from_iem_feature(f) for f in r.json().get("features", [])]


def current(alerts, at: datetime, *, grace: timedelta = timedelta(0)) -> dict[str, Alert]:
    """The latest message per hazard sent at or before ``at``, for hazards
    still in force at ``at`` (not cancelled / expired, ``begins`` reached,
    ``ends`` + ``grace`` not passed)."""
    latest: dict[str, Alert] = {}
    for a in alerts:
        if a.sent and a.sent > at:
            continue
        cur = latest.get(a.key)
        if cur is None or (a.sent, a.action not in ENDED) > (cur.sent, cur.action not in ENDED):
            latest[a.key] = a
    out = {}
    for k, a in latest.items():
        end = a.sent if a.action in ENDED else a.ends
        if a.begins and a.begins > at:
            continue
        if end is not None and end + grace < at:
            continue
        out[k] = a
    return out
