#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Shared result type and article registry for AASHTO LRFD checks.

Units convention for the whole package: kip, inch, ksi (US customary,
matching the dimensional form of the LRFD equations).  All checks are pure
functions — no I/O, no global state — so they can be vectorized or looped
over candidate member sizes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Registry of check functions keyed by LRFD article number, populated by the
# @article decorator as check modules are imported.
ARTICLES: dict[str, callable] = {}


@dataclass
class CheckResult:
    """Outcome of a single spec-article check.

    ``capacity`` and ``demand`` are in the article's governing unit (stress,
    moment, or force); ``details`` carries the intermediate values an
    engineer would show in hand calcs, keyed by the symbol used in the
    spec.
    """

    article: str
    name: str
    capacity: float
    demand: float | None = None
    phi: float = 1.0
    details: dict = field(default_factory=dict)
    # an advisory check reports a condition (e.g. a NOTICE) without failing
    # the design that contains it; ``ok`` still reports the raw comparison.
    advisory: bool = False

    @property
    def factored_capacity(self) -> float:
        return self.phi * self.capacity

    @property
    def ratio(self) -> float | None:
        """Capacity/demand ratio (>= 1.0 passes); None when no demand given."""
        if self.demand is None:
            return None
        if self.demand == 0:
            return float("inf")
        return self.factored_capacity / self.demand

    @property
    def ok(self) -> bool | None:
        if self.demand is None:
            return None
        return self.ratio >= 1.0


def article(number: str, name: str):
    """Register a check function under its LRFD article number."""

    def decorator(func):
        func.article_number = number
        func.article_name = name
        ARTICLES[number] = func
        return func

    return decorator
