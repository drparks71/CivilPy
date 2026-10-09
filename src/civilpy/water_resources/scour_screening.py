#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Post-storm scour screening: which waterway bridges should be looked at
first after a rain event.

Score = 100 x hazard x vulnerability, with multipliers for evidence of
overtopping and bed-moving velocity, and every input kept in ``reasons`` so
a reviewer sees why a bridge ranked where it did.

* **Hazard** - how rare the event was at the bridge: the return period of
  the basin rainfall (or of the estimated flow), 0 at 1 year, 0.5 at 10
  years, 1.0 at 100 years and beyond (``log10(ARI) / 2``).
* **Vulnerability** - from the SNBI record (FHWA *Specifications for the
  National Bridge Inventory*, March 2022): Item B.AP.03 Scour Vulnerability,
  raised by a poor B.C.11 Scour Condition or B.C.09 Channel Condition.
* **Overtopping** - B.AP.02 Overtopping Likelihood is coded as a return-
  period band ("4 - Moderate, once every 11 to 25 years"); an event at or
  beyond the band's lower bound is flagged as a likely overtopping.  A
  terrain-based water surface above the low point of the roadway confirms it.
* **Velocity** - channel velocity over the bed's critical velocity (HEC-18
  Eq. 6.1, :func:`civilpy.water_resources.scour.critical_velocity`).

The weights are screening placeholders, NOT calibrated: back-test them
against post-flood damage inspections before the score drives anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: B.AP.02 code -> lower bound of its overtopping return-period band (years).
#: 0 "Never" has no band.
OVERTOPPING_BAND_YR = {"0": None, "1": 100.0, "2": 51.0, "3": 26.0, "4": 11.0, "5": 3.0, "6": 1.0}

#: B.AP.03 code -> vulnerability weight (0..1).
SCOUR_VULNERABILITY = {
    "D": 1.0,    # appraised: is, or may become, unstable - scour critical
    "C": 0.9,    # scour critical, temporary (not designed) countermeasure
    "U": 0.9,    # not appraised: unknown foundations
    "E": 0.8,    # not appraised, temporary countermeasure installed
    "0": 0.6,    # scour appraisal not completed
    "B": 0.4,    # stable, dependent on designed, functioning countermeasures
    "A": 0.2,    # stable for scour
}
UNCODED_VULNERABILITY = 0.6

#: B.AP.03 codes that record a scour vulnerability (scour critical, or foundations unknown)
VULNERABLE_CODES = {"C", "D", "E", "U"}
#: B.C.11 at or below this (4 = poor) is scour damage on record
POOR_SCOUR_CONDITION = 4

INSPECT_SCORE = 50.0
WATCH_SCORE = 25.0
#: score at which a bridge with vulnerability on record must be seen immediately
IMMEDIATE_SCORE = 75.0

#: storm severity at the bridge: (lowest return period in years, class), rarest first
SEVERITY_CLASSES = [(100.0, "extreme"), (25.0, "severe"), (10.0, "moderate"), (2.0, "common")]
SEVERITY_ORDER = ["minor", "common", "moderate", "severe", "extreme"]

#: response levels, least to most urgent, and what each asks of the district
RESPONSE_LEVELS = ["none", "monitor", "1week", "24h", "immediate"]
RESPONSE_LABELS = {"immediate": "Inspect immediately", "24h": "Inspect within 24 hours",
                   "1week": "Inspect within 1 week", "monitor": "Monitor (no inspection deadline)",
                   "none": "No action"}


def clean_code(code) -> str:
    """Strip whitespace and the transition suffix ("2-T" -> "2")."""
    s = str(code or "").strip().upper()
    return s[:-2] if s.endswith("-T") else s


def hazard(ari_yr: float | None) -> float:
    if not ari_yr or ari_yr <= 1.0:
        return 0.0
    return min(1.0, math.log10(ari_yr) / 2.0)


def vulnerability_on_record(bap03=None, bc11=None, bap04=None) -> list[str]:
    """What in the SNBI record says this bridge is vulnerable to scour, as
    reasons (empty when nothing does).  Alerts list these bridges first: a
    rare storm over a bridge coded scour critical, with scour damage logged,
    or with a scour plan of action outranks the same storm over one whose
    appraisal simply hasn't been done (B.AP.03 = 0)."""
    out = []
    b3 = clean_code(bap03)
    if b3 in VULNERABLE_CODES:
        out.append(f"B.AP.03 {b3}")
    sc = _rating(bc11)
    if sc is not None and sc <= POOR_SCOUR_CONDITION:
        out.append(f"B.C.11 scour condition {sc}")
    b4 = clean_code(bap04)
    if b4 in ("Y", "N"):
        out.append("B.AP.04 Y: scour plan of action in place" if b4 == "Y"
                   else "B.AP.04 N: scour plan of action required, not implemented")
    return out


def storm_severity(ari_yr: float | None, damage_threat: str | None = None) -> str:
    """Class of the storm at one bridge from its return period: minor (under
    2-yr), common (2-10), moderate (10-25), severe (25-100), extreme (100+).
    An NWS flash flood damage threat raises it: CONSIDERABLE to at least
    severe, CATASTROPHIC (a flash flood emergency) to extreme."""
    cls = "minor"
    for lo, name in SEVERITY_CLASSES:
        if ari_yr and ari_yr >= lo:
            cls = name
            break
    threat = str(damage_threat or "").upper()
    floor = {"CONSIDERABLE": "severe", "CATASTROPHIC": "extreme"}.get(threat)
    if floor and SEVERITY_ORDER.index(floor) > SEVERITY_ORDER.index(cls):
        cls = floor
    return cls


def response_level(score: float, tier: str, overtopping: bool, on_record: list, damage_threat: str | None = None) -> str:
    """How soon the district should look at the bridge.

    * **immediate** - vulnerability on record (:func:`vulnerability_on_record`)
      and either overtopping evidence or a score of :data:`IMMEDIATE_SCORE`+;
      or any flagged bridge under an NWS flash flood emergency (CATASTROPHIC).
    * **24h** - the *inspect* tier (score 50+, or overtopping on a bridge of
      vulnerability 0.8+).
    * **1week** - the *watch* tier with vulnerability on record.
    * **monitor** - the *watch* tier otherwise (no deadline; listed in the daily digest).
    * **none** - not flagged.
    """
    if tier == "none":
        return "none"
    if on_record and (overtopping or score >= IMMEDIATE_SCORE):
        return "immediate"
    if str(damage_threat or "").upper() == "CATASTROPHIC":
        return "immediate"
    if tier == "inspect":
        return "24h"
    return "1week" if on_record else "monitor"


def response_rank(level: str | None) -> int:
    return RESPONSE_LEVELS.index(level) if level in RESPONSE_LEVELS else 0


@dataclass
class ScreeningInput:
    event_ari_yr: float | None                 # return period of the event at this bridge
    bap02: str | None = None                   # overtopping likelihood
    bap03: str | None = None                   # scour vulnerability
    bap04: str | None = None                   # scour plan of action
    bc11: str | None = None                    # scour condition rating
    bc09: str | None = None                    # channel condition rating
    ari_source: str = "rainfall"               # what event_ari_yr came from
    # optional terrain hydraulics (None when not run)
    channel_velocity_fps: float | None = None
    critical_velocity_fps: float | None = None
    wse_ft: float | None = None
    road_low_ft: float | None = None
    # optional culvert analysis (HDS-5 crossing with the road as a weir); for a culvert it replaces the
    # open-channel water surface in the overtopping test
    culvert_headwater_ft: float | None = None
    culvert_overtopping_cfs: float | None = None
    culvert_outlet_velocity_fps: float | None = None
    # NWS flash flood damage threat of a warning over the basin (CONSIDERABLE / CATASTROPHIC), if any
    nws_damage_threat: str | None = None


@dataclass
class ScreeningResult:
    score: float
    tier: str                    # inspect | watch | none
    hazard: float
    vulnerability: float
    overtopping_likely: bool
    reasons: list = field(default_factory=list)
    on_record: list = field(default_factory=list)   # vulnerability_on_record(): alert these first
    severity: str = "minor"                         # storm_severity()
    response: str = "none"                          # response_level()

    def as_dict(self):
        return {"score": round(self.score, 1), "tier": self.tier, "hazard": round(self.hazard, 3),
                "vulnerability": round(self.vulnerability, 3), "overtopping_likely": self.overtopping_likely,
                "reasons": self.reasons, "on_record": self.on_record, "severity": self.severity,
                "response": self.response}


def _rating(code):
    c = clean_code(code)
    return int(c) if c.isdigit() else None


def screen(inp: ScreeningInput) -> ScreeningResult:
    reasons = []
    h = hazard(inp.event_ari_yr)
    if inp.event_ari_yr:
        reasons.append(f"event ~{inp.event_ari_yr:.0f}-yr ({inp.ari_source})" if inp.event_ari_yr >= 1
                       else f"event under 1-yr ({inp.ari_source})")

    b3 = clean_code(inp.bap03)
    v = SCOUR_VULNERABILITY.get(b3, UNCODED_VULNERABILITY)
    reasons.append(f"B.AP.03 {b3 or 'uncoded'}")
    sc = _rating(inp.bc11)
    if sc is not None and sc <= 6:
        v = max(v, {6: 0.5, 5: 0.7}.get(sc, 1.0))
        reasons.append(f"B.C.11 scour condition {sc}")
    ch = _rating(inp.bc09)
    if ch is not None and ch <= 4:
        v = min(1.0, v + 0.1)
        reasons.append(f"B.C.09 channel condition {ch}")

    score = 100.0 * h * v

    b2 = clean_code(inp.bap02)
    band = OVERTOPPING_BAND_YR.get(b2)
    over = bool(band and inp.event_ari_yr and inp.event_ari_yr >= band)
    if over:
        score *= 1.25
        reasons.append(f"B.AP.02 {b2}: overtops about every {band:.0f}+ yr - event reached it")
    if inp.culvert_headwater_ft is not None:
        q_over = inp.culvert_overtopping_cfs or 0.0
        if q_over > 0 or (inp.road_low_ft is not None and inp.culvert_headwater_ft >= inp.road_low_ft):
            over = True
            score *= 1.25
            reasons.append(f"culvert: headwater {inp.culvert_headwater_ft:.1f} ft"
                           + (f" over road low point {inp.road_low_ft:.1f} ft" if inp.road_low_ft is not None else "")
                           + f", {q_over:.0f} cfs over the road")
        else:
            reasons.append(f"culvert: headwater {inp.culvert_headwater_ft:.1f} ft"
                           + (f", {inp.road_low_ft - inp.culvert_headwater_ft:.1f} ft below the road low point"
                              if inp.road_low_ft is not None else "") + " - culvert carries the event")
    elif inp.wse_ft is not None and inp.road_low_ft is not None and inp.wse_ft >= inp.road_low_ft:
        over = True
        score *= 1.25
        reasons.append(f"terrain: water surface {inp.wse_ft:.1f} ft at or over road low point {inp.road_low_ft:.1f} ft")

    ratios = []
    if inp.channel_velocity_fps and inp.critical_velocity_fps:
        ratios.append((inp.channel_velocity_fps / inp.critical_velocity_fps, "channel velocity",
                       inp.channel_velocity_fps))
    if inp.culvert_outlet_velocity_fps and inp.critical_velocity_fps:
        ratios.append((inp.culvert_outlet_velocity_fps / inp.critical_velocity_fps, "culvert outlet velocity",
                       inp.culvert_outlet_velocity_fps))
    if ratios:
        ratio, what, v_fps = max(ratios)
        if ratio > 1.0:
            score *= 1.0 + 0.25 * min(ratio - 1.0, 1.0)
            reasons.append(f"{what} {v_fps:.1f} ft/s = {ratio:.1f}x critical")

    b4 = clean_code(inp.bap04)
    if b4 == "Y":
        reasons.append("scour POA in place - follow its monitoring trigger")
    elif b4 == "N":
        reasons.append("scour POA required but not implemented")

    score = min(100.0, score)
    tier = ("inspect" if score >= INSPECT_SCORE or (over and v >= 0.8)
            else "watch" if score >= WATCH_SCORE else "none")
    if inp.nws_damage_threat:
        reasons.append(f"NWS flash flood damage threat {str(inp.nws_damage_threat).upper()}")
    rec = vulnerability_on_record(inp.bap03, inp.bc11, inp.bap04)
    return ScreeningResult(score, tier, h, v, over, reasons, rec,
                           storm_severity(inp.event_ari_yr, inp.nws_damage_threat),
                           response_level(score, tier, over, rec, inp.nws_damage_threat))
