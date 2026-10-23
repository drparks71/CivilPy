"""Fatigue evaluation of existing steel bridges -- AASHTO Manual for Bridge
Evaluation (MBE) Section 7, the 2018 revision with traffic growth.

The pieces, in the order the MBE uses them:

* :func:`rp_factor` -- the stress-range estimate factor R_p for a member's
  span, lane count and truck traffic (MBE Eq. 7.2.2.1-1)
* :func:`effective_stress_range` -- (Δf)eff = R_s R_p Δf (MBE Eq. 7.2.2-1)
* :func:`infinite_life` -- (Δf)max = (γ_FatI / γ_FatII)(Δf)eff against the
  constant-amplitude threshold (MBE 7.2.4, Eq. 7.2.4-1)
* :func:`available_cycles` / :func:`consumed_cycles` -- N_av and N_1
  (MBE Eqs. 7.2.5.1-2 and -3)
* :func:`remaining_life` -- Y_rem with geometric traffic growth, capped by
  the single-lane ADTT limit (MBE Eqs. 7.2.5.1-1 and -4 to -8)

:func:`evaluate` strings them together for one detail and returns a
:class:`FatigueLife`.  Detail categories use
:data:`civilpy.structural.aashto.lrfd.steel.FATIGUE_DETAIL_CATEGORIES`.

Units: ksi, trucks per day, years.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field

from civilpy.structural.aashto.lrfd.steel import FATIGUE_DETAIL_CATEGORIES

GAMMA_FAT_I = 1.75
GAMMA_FAT_II = 0.80


@dataclass(frozen=True)
class Traffic:
    """Truck traffic and history for a fatigue-life estimate.

    ``adtt_present`` / ``adtt_0`` are the single-lane ADTT now and when
    the bridge opened, ``adtt_limit`` the single-lane ADTT the roadway
    saturates at, ``growth`` the expected annual growth rate from now on
    (a fraction; a tiny positive value stands in for "no growth"), and
    ``cycles_per_truck`` the stress-range cycles per truck passage."""

    adtt_present: float
    adtt_0: float
    adtt_limit: float
    year_built: int
    year_current: int
    growth: float = 1e-6
    cycles_per_truck: float = 1.0
    span_ft: float | None = None
    lanes: int | None = None


def rp_factor(span_ft: float, adtt_sl: float, lanes: int) -> float:
    """Stress-range estimate partial load factor R_p (MBE Eq. 7.2.2.1-1):
    ``0.988 + 6.87e-5 L + 4.01e-6 ADTT_SL + 0.0107 / n_L``."""
    return 0.988 + 6.87e-5 * span_ft + 4.01e-6 * adtt_sl + 0.0107 / lanes


def effective_stress_range(delta_f: float, r_s: float = 1.0,
                           r_p: float = 1.0) -> float:
    """(Δf)eff = R_s R_p Δf (MBE Eq. 7.2.2-1)."""
    return r_s * r_p * delta_f


def infinite_life(delta_f_eff: float, category: str,
                  gamma_fat_i: float = GAMMA_FAT_I,
                  gamma_fat_ii: float = GAMMA_FAT_II) -> tuple[bool, float]:
    """MBE 7.2.4: ``(Δf)max = (γ_FatI/γ_FatII)(Δf)eff <= (ΔF)TH`` means
    infinite life.  Returns ``(infinite, (Δf)max)``."""
    df_max = delta_f_eff * gamma_fat_i / gamma_fat_ii
    return df_max <= FATIGUE_DETAIL_CATEGORIES[category][1], df_max


def available_cycles(delta_f_eff: float, category: str,
                     r_r: float = 1.0) -> float:
    """N_av = R_R A / (Δf)eff^3 (MBE Eq. 7.2.5.1-2; R_R from MBE Table
    7.2.5.2-1, 1.0 for the evaluation life)."""
    return r_r * FATIGUE_DETAIL_CATEGORIES[category][0] / delta_f_eff ** 3


def consumed_cycles(t: Traffic, year_offset: float = 0.0) -> float:
    """N_1, the cycles already consumed since the bridge opened, with the
    ADTT growing geometrically from ``adtt_0`` to ``adtt_present`` (MBE
    Eq. 7.2.5.1-3; constant traffic when the two are equal).
    ``year_offset`` is added to the years in service in the growth
    exponent (the NSBA IRM Flexural Evaluator uses 0.01 to avoid a zero
    divisor in the year built)."""
    years = t.year_current - t.year_built + year_offset
    n = t.cycles_per_truck
    if t.adtt_present == t.adtt_0:
        return 365.0 * n * (t.year_current - t.year_built + 1) * t.adtt_present
    ratio = t.adtt_present / t.adtt_0
    return 365.0 * n * t.adtt_present * (
        (1.0 - t.adtt_0 / t.adtt_present) / (ratio ** (1.0 / years) - 1.0) + 1.0)


@dataclass
class RemainingLife:
    """``years`` of remaining fatigue life (0 when used up) and how it was
    found: ``limited`` when the ADTT reaches ``adtt_limit`` first."""

    years: float
    limited: bool = False
    adtt_future: float | None = None
    y_limit: float | None = None


def remaining_life(n_av: float, n_1: float, t: Traffic) -> RemainingLife:
    """Remaining fatigue life (MBE Eqs. 7.2.5.1-1, -4 to -8).

    Unlimited growth: ``Y = log[(g/(1+g)) (N_av - N_1)/(365 n ADTT_p) + 1]
    / log(1+g)``.  If the ADTT then projected, ``ADTT_p (1+g)^Y``
    (Eq. 7.2.5.1-6; the NSBA IRM evaluators use this form except one
    faulted-state cell with ``Y - 1``, immaterial unless the projection
    lands within a year's growth of the limit), exceeds ``adtt_limit``, traffic stops growing at
    ``Y_limit = log(ADTT_limit/ADTT_p)/log(1+g)`` and
    ``Y = (N_av - N_1)/(365 n ADTT_limit) - ((1+g)^Y_limit - 1)/(g
    (1+g)^(Y_limit - 1)) + Y_limit``."""
    if n_av <= n_1:
        return RemainingLife(0.0)
    g, n = t.growth, t.cycles_per_truck
    y = math.log10(g / (1.0 + g) * (n_av - n_1) / (365.0 * n * t.adtt_present)
                   + 1.0) / math.log10(1.0 + g)
    future = t.adtt_present * (1.0 + g) ** y
    if future <= t.adtt_limit:
        return RemainingLife(y, False, future)
    y_lim = math.log10(t.adtt_limit / t.adtt_present) / math.log10(1.0 + g)
    y2 = ((n_av - n_1) / (365.0 * n * t.adtt_limit)
          - ((1.0 + g) ** y_lim - 1.0) / (g * (1.0 + g) ** (y_lim - 1.0)) + y_lim)
    return RemainingLife(y2, True, future, y_lim)


@dataclass
class FatigueLife:
    """One detail's fatigue evaluation: stress ranges, whether the life is
    infinite, and the remaining and total lives (``math.inf`` when
    infinite)."""

    category: str
    delta_f: float
    delta_f_eff: float
    delta_f_max: float
    infinite: bool
    remaining_years: float
    n_av: float | None = None
    n_1: float | None = None
    detail: RemainingLife | None = None
    notes: list = field(default_factory=list)


def evaluate(delta_f: float, category: str, t: Traffic, *, r_s: float = 1.0,
             r_p: float | None = None, r_r: float = 1.0,
             consumed: float | None = None,
             gamma_fat_i: float = GAMMA_FAT_I,
             gamma_fat_ii: float = GAMMA_FAT_II) -> FatigueLife:
    """Fatigue life of a detail with live-load stress range ``delta_f``
    (Fatigue II truck incl. impact).  ``r_p`` defaults to
    :func:`rp_factor` from the traffic's span and lane count (1.0 when
    they are not given).  ``consumed`` overrides N_1 (e.g. 0 for a
    hypothetical fault that happens today)."""
    if r_p is None:
        r_p = (rp_factor(t.span_ft, t.adtt_present, t.lanes)
               if t.span_ft is not None and t.lanes else 1.0)
    eff = effective_stress_range(delta_f, r_s, r_p)
    inf, df_max = infinite_life(eff, category, gamma_fat_i, gamma_fat_ii)
    if inf:
        return FatigueLife(category, delta_f, eff, df_max, True, math.inf)
    n_av = available_cycles(eff, category, r_r)
    n_1 = consumed_cycles(t) if consumed is None else consumed
    rem = remaining_life(n_av, n_1, t)
    return FatigueLife(category, delta_f, eff, df_max, False, rem.years,
                       n_av, n_1, rem)
