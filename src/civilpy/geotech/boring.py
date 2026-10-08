#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Canonical, library-neutral data model for a subsurface boring.

A geotechnical boring log is the hub object the rest of CivilPy reads from:
the same :class:`Borehole` can drive scour grain-size lookups in the
hydraulics library, axial capacity in the foundations modules, and soil
zone moduli for CANDE.  Ingestion (DIGGS XML, PDF logs, ...) lives in
:mod:`civilpy.geotech.boring_io` and produces these objects; nothing here
depends on how the data was read.

Units are US customary: depths and elevations in feet, particle sizes in
millimetres (the geotechnical convention for gradations), recovery in
inches.  Blow counts are dimensionless.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------- SPT

#: A single 6-inch drive increment of a Standard Penetration Test: the
#: number of hammer ``blows`` to advance ``penetration_in`` inches.  A
#: refusal increment advances less than its nominal length.
@dataclass(frozen=True)
class DriveIncrement:
    blows: int
    penetration_in: float = 6.0


@dataclass(frozen=True)
class SPTResult:
    """One Standard Penetration Test at ``depth_ft`` (top of the 18-inch
    drive).  ``increments`` are the successive 6-inch drives in order
    (seating, then the two that count)."""

    depth_ft: float
    increments: tuple[DriveIncrement, ...]
    hammer_type: str | None = None
    hammer_efficiency: str | None = None

    @property
    def total_blows(self) -> int:
        return sum(i.blows for i in self.increments)

    @property
    def total_penetration_in(self) -> float:
        return sum(i.penetration_in for i in self.increments)

    @property
    def refusal(self) -> bool:
        """True if the spoon did not advance the full nominal length
        (driven penetration short of 6 in per recorded increment)."""
        return any(i.penetration_in < 6.0 for i in self.increments)

    @property
    def n_value(self) -> int | None:
        """Field SPT blow count N: the sum of the second and third 6-inch
        increments (ASTM D1586).  With only two increments their sum is
        used; with fewer than two, ``None``."""
        n = len(self.increments)
        if n >= 3:
            return self.increments[1].blows + self.increments[2].blows
        if n == 2:
            return self.increments[0].blows + self.increments[1].blows
        return None

    def n60(self, energy_ratio: float = 0.60, rod_length_ft: float | None = None,
            borehole_diameter_in: float = 4.0, liner: bool = False) -> float | None:
        """Energy-corrected blow count N60 (Skempton 1986):
        N60 = N * (Em/0.60) * Cr * Cb * Cs, where ``energy_ratio`` Em is the
        measured/rated hammer efficiency as a decimal.  Rod-length Cr is
        applied from ``rod_length_ft`` (taken as ``depth_ft`` when omitted),
        borehole Cb from ``borehole_diameter_in``, sampler Cs from
        ``liner``."""
        n = self.n_value
        if n is None:
            return None
        rod = rod_length_ft if rod_length_ft is not None else self.depth_ft
        if rod < 13:
            cr = 0.75
        elif rod < 20:
            cr = 0.85
        elif rod < 33:
            cr = 0.95
        else:
            cr = 1.0
        if borehole_diameter_in <= 4.7:
            cb = 1.0
        elif borehole_diameter_in <= 6.0:
            cb = 1.05
        else:
            cb = 1.15
        cs = 1.2 if liner else 1.0
        return n * (energy_ratio / 0.60) * cr * cb * cs


# --------------------------------------------------------------- gradation

@dataclass(frozen=True)
class GradingPoint:
    """One point on a particle-size distribution: ``percent_passing`` finer
    than ``particle_size_mm``."""

    particle_size_mm: float
    percent_passing: float


@dataclass(frozen=True)
class GradingResult:
    """A particle-size (sieve + hydrometer) analysis on a sample taken at
    ``depth_ft``.  ``points`` are stored sorted coarse-to-fine."""

    depth_ft: float
    points: tuple[GradingPoint, ...]

    #: US No. 200 sieve opening, mm (the silt/sand fines boundary).
    FINES_SIZE_MM = 0.075

    def percent_passing_at(self, size_mm: float) -> float | None:
        """Percent finer than ``size_mm`` by log-linear interpolation on
        the gradation curve; ``None`` if outside the measured range."""
        pts = sorted(self.points, key=lambda p: p.particle_size_mm)
        if not pts or size_mm < pts[0].particle_size_mm or size_mm > pts[-1].particle_size_mm:
            # allow exact endpoints
            for p in pts:
                if abs(p.particle_size_mm - size_mm) < 1e-12:  # pragma: no cover
                    return p.percent_passing
            return None
        import math
        for a, b in zip(pts, pts[1:]):
            if a.particle_size_mm <= size_mm <= b.particle_size_mm:
                if b.particle_size_mm == a.particle_size_mm:
                    return a.percent_passing
                t = (math.log10(size_mm) - math.log10(a.particle_size_mm)) / (
                    math.log10(b.particle_size_mm) - math.log10(a.particle_size_mm))
                return a.percent_passing + t * (b.percent_passing - a.percent_passing)
        return None

    def d_size(self, percent: float) -> float | None:
        """Particle size (mm) at which ``percent`` of the sample is finer
        (e.g. ``d_size(50)`` is D50), log-linearly interpolated; ``None`` if
        the curve does not bracket that percentage."""
        pts = sorted(self.points, key=lambda p: p.percent_passing)
        if not pts or percent < pts[0].percent_passing or percent > pts[-1].percent_passing:
            return None
        import math
        for a, b in zip(pts, pts[1:]):
            if a.percent_passing <= percent <= b.percent_passing:
                if b.percent_passing == a.percent_passing:
                    return a.particle_size_mm
                t = (percent - a.percent_passing) / (b.percent_passing - a.percent_passing)
                log_d = math.log10(a.particle_size_mm) + t * (
                    math.log10(b.particle_size_mm) - math.log10(a.particle_size_mm))
                return 10 ** log_d
        return None

    @property
    def d10(self) -> float | None:
        return self.d_size(10)

    @property
    def d30(self) -> float | None:
        return self.d_size(30)

    @property
    def d50(self) -> float | None:
        """Median grain size D50, mm -- the key input to HEC-18 scour."""
        return self.d_size(50)

    @property
    def d60(self) -> float | None:
        return self.d_size(60)

    @property
    def fines_percent(self) -> float | None:
        """Percent finer than the No. 200 sieve (0.075 mm)."""
        return self.percent_passing_at(self.FINES_SIZE_MM)

    @property
    def coefficient_of_uniformity(self) -> float | None:
        """Cu = D60 / D10."""
        d10, d60 = self.d10, self.d60
        return d60 / d10 if d10 and d60 else None

    @property
    def coefficient_of_curvature(self) -> float | None:
        """Cc = D30^2 / (D10 * D60)."""
        d10, d30, d60 = self.d10, self.d30, self.d60
        return d30 ** 2 / (d10 * d60) if d10 and d30 and d60 else None


# --------------------------------------------------------------- sample / borehole

@dataclass(frozen=True)
class Sample:
    """A recovered sample interval (split spoon, Shelby tube, rock core)."""

    depth_top_ft: float
    depth_bottom_ft: float
    method: str | None = None
    recovery_in: float | None = None

    @property
    def length_in(self) -> float:
        return (self.depth_bottom_ft - self.depth_top_ft) * 12.0

    @property
    def recovery_percent(self) -> float | None:
        if self.recovery_in is None or self.length_in <= 0:
            return None
        return 100.0 * self.recovery_in / self.length_in


# --------------------------------------------------------------- lithology

ROCK_NAMES = ("SHALE", "LIMESTONE", "SANDSTONE", "SILTSTONE", "DOLOMITE", "CLAYSTONE", "MUDSTONE", "COAL",
              "BEDROCK", "ROCK")
#: field rock-strength terms (ODOT / ISRM descriptive scale) that count as weak
WEAK_ROCK = ("extremely weak", "very weak", "weak")
#: weathering grades (the logged range's worse end) at which rock no longer counts as scour-resistant
WEATHERED_OUT = ("highly", "severely", "completely")
#: material groups, in display order
GROUPS = ("pavement", "topsoil", "granular", "silt", "clay", "organic", "rock", "unknown")


def material_group(classification: str | None = None, description: str | None = None,
                   constituents: tuple = (), system: str | None = None) -> str:
    """Coarse material group of a logged layer: ``granular`` (AASHTO A-1,
    A-2, A-3), ``silt`` (A-4, A-5), ``clay`` (A-6, A-7), ``organic`` (A-8),
    ``rock``, ``pavement``, ``topsoil`` or ``unknown`` - from the AASHTO /
    ODOT class when logged, else the rock system or the words used."""
    c = (classification or "").upper().replace(" ", "")
    words = " ".join([description or ""] + [str(x) for x in constituents]).upper()
    if "PAVEMENT" in c or "ASPHALT" in words or c in ("BASE",):
        return "pavement"
    if "TOPSOIL" in c or (not c and "TOPSOIL" in words):
        return "topsoil"
    if (system or "").upper() == "ROCK" or any(r in c for r in ROCK_NAMES):
        return "rock"
    if c.startswith("A-"):
        major = c[2:3]
        return {"1": "granular", "2": "granular", "3": "granular", "4": "silt", "5": "silt",
                "6": "clay", "7": "clay", "8": "organic"}.get(major, "unknown")
    if any(r in words for r in ROCK_NAMES[:-2]):
        return "rock"
    # the head noun of "sandy silt", "silty clay", "gravel and sand": the last soil noun before any "with"
    nouns = {"GRAVEL": "granular", "SAND": "granular", "SILT": "silt", "CLAY": "clay", "PEAT": "organic"}
    head = [nouns[w] for w in words.split(" WITH ")[0].replace(",", " ").split() if w in nouns]
    return head[-1] if head else "unknown"


@dataclass(frozen=True)
class Layer:
    """One logged stratum (a DIGGS ``LithologyObservation``)."""

    depth_top_ft: float
    depth_bottom_ft: float
    system: str | None = None            # SOIL | ROCK as logged
    classification: str | None = None    # AASHTO / ODOT class or rock name (ODOT "Graphic")
    uscs: str | None = None
    description: str | None = None
    constituents: tuple = ()             # major first
    color: str | None = None
    consistency: str | None = None       # cohesive soils / relative density
    moisture: str | None = None
    rock_strength: str | None = None
    rock_weathering: str | None = None
    recovery_pct: float | None = None
    rqd_pct: float | None = None

    @property
    def thickness_ft(self) -> float:
        return self.depth_bottom_ft - self.depth_top_ft

    @property
    def group(self) -> str:
        return material_group(self.classification, self.description, self.constituents, self.system)

    @property
    def label(self) -> str:
        """Short text for a drawing: class (or major constituent) and consistency / strength."""
        name = self.classification or (self.constituents[0] if self.constituents else None) or self.group
        extra = self.rock_strength or self.consistency
        return f"{name}{', ' + extra if extra else ''}"

    def scour_resistant(self, min_rqd_pct: float = 50.0) -> bool:
        """Screening test for rock that limits scour: a rock layer not logged
        weak (a range at its weaker end) nor highly / severely / completely
        weathered, with RQD at least ``min_rqd_pct`` when RQD is logged.  Weak
        or slaking rock (most Ohio shales) erodes and is NOT counted - HEC-18
        treats it as erodible rock needing its own analysis."""
        if self.group != "rock":
            return False
        strength = (self.rock_strength or "").strip().lower()
        lower = strength.split(" to ")[0].strip()          # a logged range counts at its weaker end
        if lower in WEAK_ROCK:
            return False
        if (self.rock_weathering or "").strip().lower().split(" to ")[-1] in WEATHERED_OUT:
            return False
        if self.rqd_pct is not None and self.rqd_pct < min_rqd_pct:
            return False
        return bool(strength) or self.rqd_pct is not None


@dataclass
class Borehole:
    """A single subsurface boring: header location/geometry plus the
    depth-indexed sample, SPT, and gradation records read from a log."""

    boring_id: str
    project: str | None = None
    ground_elevation_ft: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    station: str | None = None
    offset_ft: float | None = None
    offset_direction: str | None = None
    total_depth_ft: float | None = None
    water_strike_depth_ft: float | None = None
    date: str | None = None
    purpose: str | None = None
    samples: list[Sample] = field(default_factory=list)
    spt: list[SPTResult] = field(default_factory=list)
    grading: list[GradingResult] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    depth_to_rock_ft: float | None = None   # as reported on the log header

    def elevation_at(self, depth_ft: float) -> float | None:
        """Ground-surface elevation minus ``depth_ft`` (None if the collar
        elevation is unknown)."""
        if self.ground_elevation_ft is None:
            return None
        return self.ground_elevation_ft - depth_ft

    def spt_profile(self) -> list[tuple[float, int]]:
        """``(depth_ft, N)`` pairs sorted by depth, skipping tests whose N
        is undefined."""
        out = [(s.depth_ft, s.n_value) for s in self.spt if s.n_value is not None]
        return sorted(out)

    def n_at(self, depth_ft: float) -> int | None:
        """SPT N of the test nearest ``depth_ft`` (None if no SPT data)."""
        if not self.spt:
            return None
        nearest = min(self.spt, key=lambda s: abs(s.depth_ft - depth_ft))
        return nearest.n_value

    def grading_at(self, depth_ft: float) -> GradingResult | None:
        """Gradation analysis nearest ``depth_ft`` (None if none present)."""
        if not self.grading:
            return None
        return min(self.grading, key=lambda g: abs(g.depth_ft - depth_ft))

    def d50_at(self, depth_ft: float) -> float | None:
        """D50 (mm) of the gradation nearest ``depth_ft`` -- the scour
        input."""
        g = self.grading_at(depth_ft)
        return g.d50 if g else None

    def layer_at(self, depth_ft: float) -> Layer | None:
        """The logged layer containing ``depth_ft`` (None outside the log)."""
        for lay in self.layers:
            if lay.depth_top_ft <= depth_ft < lay.depth_bottom_ft:
                return lay
        return None

    def rock_top_ft(self) -> float | None:
        """Depth to rock: the header value, else the first rock layer."""
        if self.depth_to_rock_ft is not None:
            return self.depth_to_rock_ft
        tops = [lay.depth_top_ft for lay in self.layers if lay.group == "rock"]
        return min(tops) if tops else None

    def resistant_rock_top_ft(self, min_rqd_pct: float = 50.0) -> float | None:
        """Depth to the first scour-resistant rock layer
        (:meth:`Layer.scour_resistant`), or None."""
        tops = [lay.depth_top_ft for lay in self.layers if lay.scour_resistant(min_rqd_pct)]
        return min(tops) if tops else None
