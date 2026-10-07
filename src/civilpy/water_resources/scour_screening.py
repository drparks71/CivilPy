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

INSPECT_SCORE = 50.0
WATCH_SCORE = 25.0


def clean_code(code) -> str:
    """Strip whitespace and the transition suffix ("2-T" -> "2")."""
    s = str(code or "").strip().upper()
    return s[:-2] if s.endswith("-T") else s


def hazard(ari_yr: float | None) -> float:
    if not ari_yr or ari_yr <= 1.0:
        return 0.0
    return min(1.0, math.log10(ari_yr) / 2.0)


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


@dataclass
class ScreeningResult:
    score: float
    tier: str                    # inspect | watch | none
    hazard: float
    vulnerability: float
    overtopping_likely: bool
    reasons: list = field(default_factory=list)

    def as_dict(self):
        return {"score": round(self.score, 1), "tier": self.tier, "hazard": round(self.hazard, 3),
                "vulnerability": round(self.vulnerability, 3), "overtopping_likely": self.overtopping_likely,
                "reasons": self.reasons}


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
    if inp.wse_ft is not None and inp.road_low_ft is not None and inp.wse_ft >= inp.road_low_ft:
        over = True
        score *= 1.25
        reasons.append(f"terrain: water surface {inp.wse_ft:.1f} ft at or over road low point {inp.road_low_ft:.1f} ft")

    if inp.channel_velocity_fps and inp.critical_velocity_fps:
        ratio = inp.channel_velocity_fps / inp.critical_velocity_fps
        if ratio > 1.0:
            score *= 1.0 + 0.25 * min(ratio - 1.0, 1.0)
            reasons.append(f"channel velocity {inp.channel_velocity_fps:.1f} ft/s = {ratio:.1f}x critical")

    b4 = clean_code(inp.bap04)
    if b4 == "Y":
        reasons.append("scour POA in place - follow its monitoring trigger")
    elif b4 == "N":
        reasons.append("scour POA required but not implemented")

    score = min(100.0, score)
    tier = ("inspect" if score >= INSPECT_SCORE or (over and v >= 0.8)
            else "watch" if score >= WATCH_SCORE else "none")
    return ScreeningResult(score, tier, h, v, over, reasons)
