#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Storable parametric Spec records — the BIM system's schema authority.

The queryable-BIM architecture stores every parameter needed to run the
:mod:`civilpy.structural.aashto.lrfd` checks from scratch as a JSON
document (Postgres JSONB on the application side).  This module declares
those records **once**, as plain dataclasses of JSON-safe primitives:

* every field carries its engineering metadata (``unit``, bounds, enum
  options, the checks that consume it) in ``dataclasses.field(metadata=)``
  — one declaration drives validation, documentation, and the
  check-coverage test;
* :func:`record_to_dict` / :func:`record_from_dict` round-trip a record
  through a JSON document with no schema declared anywhere else (add a
  field here and the document simply carries an extra key);
* JSON is not type-checked on write, so :meth:`SpecRecord.validate` is
  the type guarantor — validate before save;
* the record *reconstitutes* the executed-design objects the geometry
  builders in :mod:`civilpy.structural.substructure_layout` consume, so
  a record read back from storage can regenerate geometry, the tagged
  ``.3dm`` emit, and every check input without the session that authored
  it.

The first element modeled end-to-end was the single-column hammerhead
pier (:class:`HammerheadPierRecord`); the Phase-6 breadth elements —
:class:`BentPierRecord`, :class:`PileBentRecord`,
:class:`SeatAbutmentRecord` — follow the same pattern.  Each element has
a ``*_CHECK_INPUTS`` coverage map tying every LRFD check that consumes
it to the record fields that feed it — the test suite walks the maps, so
a check added without a mapped input path (or a field renamed out from
under one) fails loudly instead of rotting silently.

Units follow the hub convention: layout-scale dimensions in **feet**
(``_ft``), section-scale in **inches** (``_in``), strengths in **ksi**.
"""

from __future__ import annotations

import types
import typing
from dataclasses import MISSING, dataclass, field, fields, is_dataclass

#: Bump when a saved document's meaning changes (not when a field is
#: merely added — additive keys are the point of the JSON substrate).
SCHEMA_VERSION = 1

#: Provenance tiers, element-level (decision 3 of the build plan):
#: per-field overrides ride in ``Provenance.field_sources`` only for
#: manually-entered values where a re-derivation trigger pays off.
#: ``snbi`` = seeded from the inventory columns; ``inferred`` = resolved
#: through the era-standards registry (the standard-default path) — both
#: mark records the Tier A campaign populates without a plan in hand.
#: ``obm`` = read from an OpenBridge Modeler model; ``gis`` = public GIS
#: services (TIMS, OGRIP); ``design_file`` = a design deliverable such as
#: LandXML / OpenRoads geometry.
SOURCES = ("brr", "plans", "manual", "snbi", "inferred", "obm", "gis", "design_file")


def spec_field(default=MISSING, *, unit: str | None = None,
               desc: str | None = None, enum: tuple | None = None,
               gt: float | None = None, ge: float | None = None,
               checks: tuple[str, ...] = ()):
    """A dataclass field carrying its engineering metadata: ``unit``,
    bounds (``gt``/``ge``), ``enum`` options, and the article numbers of
    the ``checks`` consuming it.  The metadata rides on the one field
    declaration — validation and the coverage test both read it here."""
    md = {k: v for k, v in dict(unit=unit, desc=desc, enum=enum, gt=gt,
                                ge=ge, checks=checks).items()
          if v is not None and v != ()}
    if default is MISSING:
        return field(metadata=md)
    return field(default=default, metadata=md)


# ── serialization / validation base ───────────────────────────────────────

_JSON_SCALARS = (str, int, float, bool)


def _strip_optional(tp):
    """``X | None`` -> ``X`` (unchanged when not an optional)."""
    if typing.get_origin(tp) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def record_to_dict(rec) -> dict:
    """Flatten a record to JSON-safe primitives (nested dicts/lists)."""
    def conv(v):
        if is_dataclass(v):
            return {f.name: conv(getattr(v, f.name)) for f in fields(v)}
        if isinstance(v, (tuple, list)):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v
    return conv(rec)


def record_from_dict(cls, data: dict):
    """Rebuild ``cls`` from :func:`record_to_dict` output (tuples restored,
    nested records recursed via the type hints — the single schema)."""
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        v = data[f.name]
        tp = _strip_optional(hints[f.name])
        origin = typing.get_origin(tp)
        if v is None:
            kwargs[f.name] = None
        elif is_dataclass(tp):
            kwargs[f.name] = record_from_dict(tp, v)
        elif origin is tuple:
            args = typing.get_args(tp)
            inner = args[0] if args else None
            if inner is not None and is_dataclass(inner):
                kwargs[f.name] = tuple(record_from_dict(inner, x) for x in v)
            else:
                kwargs[f.name] = tuple(v)
        else:
            kwargs[f.name] = v
    return cls(**kwargs)


class SpecRecord:
    """Validation mixin: the type guarantor in front of a schema-free
    JSON store.  Checks every field against its annotation and its
    ``spec_field`` metadata (enum membership, ``gt``/``ge`` bounds),
    recursing into nested records.  Returns problem strings;
    ``validate(strict=True)`` raises instead."""

    def validate(self, *, strict: bool = False,
                 _prefix: str = "") -> list[str]:
        problems: list[str] = []
        hints = typing.get_type_hints(type(self))
        for f in fields(self):
            name = f"{_prefix}{f.name}"
            v = getattr(self, f.name)
            tp = _strip_optional(hints[f.name])
            if v is None:
                if hints[f.name] is tp:      # not optional
                    problems.append(f"{name}: required, got None")
                continue
            if is_dataclass(tp):
                if isinstance(v, tp):
                    problems += v.validate(_prefix=f"{name}.")
                else:
                    problems.append(f"{name}: expected {tp.__name__}, "
                                    f"got {type(v).__name__}")
                continue
            if tp in _JSON_SCALARS:
                if tp is float:
                    ok = (isinstance(v, (int, float))
                          and not isinstance(v, bool))
                elif tp is bool:
                    ok = isinstance(v, bool)
                elif tp is int:
                    ok = isinstance(v, int) and not isinstance(v, bool)
                else:
                    ok = isinstance(v, tp)
                if not ok:
                    problems.append(f"{name}: expected {tp.__name__}, "
                                    f"got {type(v).__name__}")
                    continue
            md = f.metadata
            if "enum" in md and v not in md["enum"]:
                problems.append(f"{name}: {v!r} not in {md['enum']}")
            if "gt" in md and isinstance(v, (int, float)) \
                    and v <= md["gt"]:
                problems.append(f"{name}: {v} must be > {md['gt']}")
            if "ge" in md and isinstance(v, (int, float)) \
                    and v < md["ge"]:
                problems.append(f"{name}: {v} must be >= {md['ge']}")
        try:
            problems += [f"{_prefix}{p}" for p in self._cross_validate()]
        except TypeError:
            pass                 # already reported as a type problem above
        if strict and problems:
            raise ValueError("; ".join(problems))
        return problems

    def _cross_validate(self) -> list[str]:
        """Override for multi-field rules (dimension consistency)."""
        return []


# ── provenance ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Provenance(SpecRecord):
    """Where this element's parameters came from.  ``source`` is the
    element-level tier; ``field_sources`` overrides it per field (dotted
    record path -> tier) for manually-entered values; ``doc_id`` /
    ``sheet`` point into the plans document store when
    ``source="plans"`` so a plan revision flags exactly which fields to
    re-verify."""

    source: str = spec_field("manual", enum=SOURCES)
    field_sources: dict | None = spec_field(
        None, desc="dotted path -> source tier")
    doc_id: str | None = spec_field(None, desc="plan_document id")
    sheet: str | None = spec_field(None)


class ElementRecord(SpecRecord):
    """Base for whole-element records: the ``bim.type``/``subtype``
    identity keys stamped into the flattened document, and the guarded
    round-trip every element shares."""

    BIM_TYPE = ""
    SUBTYPE = ""

    def to_dict(self) -> dict:
        """The JSONB document: identity keys + flattened fields."""
        return {"bim.type": self.BIM_TYPE, "subtype": self.SUBTYPE,
                "schema_version": SCHEMA_VERSION, **record_to_dict(self)}

    @classmethod
    def from_dict(cls, data: dict):
        if data.get("bim.type", cls.BIM_TYPE) != cls.BIM_TYPE or \
                data.get("subtype", cls.SUBTYPE) != cls.SUBTYPE:
            raise ValueError(
                f"not a {cls.BIM_TYPE}/{cls.SUBTYPE} document: "
                f"{data.get('bim.type')}/{data.get('subtype')}")
        return record_from_dict(cls, data)


# ── hammerhead pier: the Phase-1 vertical slice ───────────────────────────

@dataclass(frozen=True)
class PierCapRecord(SpecRecord):
    """The executed hammerhead cap design as parameters: overall envelope
    plus the governing STM tie's bar schedule (the outputs of
    :func:`~civilpy.structural.stm_topology.design.optimize_pier_cap`
    that geometry and checks consume — the sweep itself is not stored)."""

    span_ft: float = spec_field(unit="ft", gt=0.0,
                                desc="cap length along the support line")
    depth_ft: float = spec_field(unit="ft", gt=0.0,
                                 checks=("5.7.3.3", "5.6.7"),
                                 desc="full section depth at the column")
    thickness_ft: float = spec_field(unit="ft", gt=0.0,
                                     checks=("5.8.2.5", "5.8.2.6",
                                             "5.7.3.3", "5.7.2.5"),
                                     desc="cap width across the bridge")
    tie_bar_size: int = spec_field(unit="US bar #", ge=4,
                                   checks=("5.8.2.4", "5.6.7",
                                           "5.10.8.2.1"))
    tie_bar_count: int = spec_field(ge=1, checks=("5.8.2.4",))
    tie_at_top: bool = spec_field(True, desc="hammerhead cantilever: the "
                                  "governing tie is the top chord")
    tip_depth_ft: float | None = spec_field(
        None, unit="ft", gt=0.0,
        desc="soffit taper depth at the cantilever tips; None = prismatic")
    fc_ksi: float = spec_field(4.0, unit="ksi", gt=0.0,
                               checks=("5.8.2.5", "5.7.3.3", "5.7.2.5",
                                       "5.7.2.6", "5.10.8.2.1"))
    fy_ksi: float = spec_field(60.0, unit="ksi", gt=0.0,
                               checks=("5.8.2.4", "5.7.3.3", "5.7.2.5",
                                       "5.6.7", "5.10.8.2.1"))

    def _cross_validate(self):
        if (self.tip_depth_ft is not None
                and self.tip_depth_ft > self.depth_ft):
            return [f"tip_depth_ft: {self.tip_depth_ft} exceeds cap "
                    f"depth {self.depth_ft}"]
        return []


@dataclass(frozen=True)
class PierStemRecord(SpecRecord):
    """The hammerhead stem (single column): section, clear height, and
    the longitudinal steel the executed design carries.  Rectangular
    ``b_in x h_in`` (``b`` along the cap) or circular ``diameter_in``."""

    height_ft: float = spec_field(unit="ft", gt=0.0,
                                  checks=("4.5.3.2.2b",),
                                  desc="clear height, cap soffit to "
                                       "footing top")
    bars_area_in2: float = spec_field(unit="in^2", gt=0.0,
                                      checks=("5.6.4.4", "5.6.4.2",
                                              "5.6.4.5 check"),
                                      desc="total longitudinal steel")
    b_in: float | None = spec_field(None, unit="in", gt=0.0,
                                    checks=("5.6.4.4", "5.6.4.2",
                                            "5.6.4.5 check", "4.5.3.2.2b"))
    h_in: float | None = spec_field(None, unit="in", gt=0.0,
                                    checks=("5.6.4.4", "5.6.4.2",
                                            "5.6.4.5 check", "4.5.3.2.2b"))
    diameter_in: float | None = spec_field(
        None, unit="in", gt=0.0,
        checks=("5.6.4.4", "5.6.4.2", "5.6.4.5 check", "4.5.3.2.2b",
                "5.6.4.6"))
    bar_size: int = spec_field(9, unit="US bar #", ge=4,
                               desc="size the steel area is broken into")
    fc_ksi: float = spec_field(4.0, unit="ksi", gt=0.0,
                               checks=("5.6.4.4", "5.6.4.2",
                                       "5.6.4.5 check", "4.5.3.2.2b",
                                       "5.6.4.6"))
    fy_ksi: float = spec_field(60.0, unit="ksi", gt=0.0,
                               checks=("5.6.4.4", "5.6.4.2",
                                       "5.6.4.5 check"))
    spiral: bool = spec_field(False, checks=("5.6.4.4", "5.6.4.6"))
    fixity: str = spec_field("fixed-fixed",
                             enum=("fixed-fixed", "fixed-free"),
                             checks=("4.5.3.2.2b",))

    def _cross_validate(self):
        rect = self.b_in is not None and self.h_in is not None
        circ = self.diameter_in is not None
        if rect == circ:
            return ["give either b_in+h_in or diameter_in"]
        return []


@dataclass(frozen=True)
class FootingRecord(SpecRecord):
    """Spread-footing plan dims — a geotech deliverable, explicit inputs
    (mirrors :class:`~civilpy.structural.substructure_layout.FootingSpec`)."""

    length_ft: float = spec_field(unit="ft", gt=0.0,
                                  desc="along the cap axis")
    width_ft: float = spec_field(unit="ft", gt=0.0)
    thickness_ft: float = spec_field(unit="ft", gt=0.0)


@dataclass(frozen=True)
class CapDetailingRecord(SpecRecord):
    """Cap/stem detailing outside the STM schedule: covers, the shear
    stirrups the sectional checks run with, the D-region crack-control
    grid (5.8.2.6), and the bearing-seat plan side the node faces bear
    on."""

    cover_in: float = spec_field(3.0, unit="in", gt=0.0,
                                 checks=("5.6.7", "5.7.3.3"))
    stirrup_size: int = spec_field(5, unit="US bar #", ge=3,
                                   checks=("5.7.3.3", "5.7.2.5",
                                           "5.8.2.6"))
    stirrup_spacing_in: float = spec_field(12.0, unit="in", gt=0.0,
                                           checks=("5.7.3.3", "5.7.2.5",
                                                   "5.7.2.6", "5.8.2.6"))
    skin_bar_size: int = spec_field(5, unit="US bar #", ge=3,
                                    checks=("5.8.2.6",))
    skin_bar_spacing_in: float = spec_field(12.0, unit="in", gt=0.0,
                                            checks=("5.8.2.6",))
    seat_side_in: float = spec_field(27.0, unit="in", gt=0.0,
                                     checks=("5.8.2.5",),
                                     desc="bearing-seat plan side = node "
                                          "face bearing dimension")


# ── reconstitution helpers (shared by every cap-on-support element) ───────

def _pier_column(stem: PierStemRecord, cover_in: float):
    """The :class:`~civilpy.structural.pier.PierColumn` the geometry
    builders consume, carrying the stored steel as one layer at cover
    (geometry needs only the total; run the P-M checks with a real ring
    via :func:`stem_rebar_layers`)."""
    from civilpy.structural.pier import PierColumn
    from civilpy.structural.aashto.lrfd.columns import RebarLayer

    return PierColumn(
        height=stem.height_ft * 12.0,
        layers=[RebarLayer(area=stem.bars_area_in2, depth=cover_in)],
        f_c=stem.fc_ksi, f_y=stem.fy_ksi, b=stem.b_in, h=stem.h_in,
        diameter=stem.diameter_in, spiral=stem.spiral, fixity=stem.fixity)


def _cap_design(cap: PierCapRecord):
    """A :class:`~civilpy.structural.stm_topology.design.PierCapDesign`
    carrying the stored envelope + tie schedule (the record is the
    design's *output*; the optimizer sweep is not replayed)."""
    from types import SimpleNamespace

    from civilpy.structural.stm_topology.design import (
        DepthCandidate, PierCapDesign)

    tie_y = cap.depth_ft - 0.2 if cap.tie_at_top else 0.2
    tie = SimpleNamespace(force=0.0, bar_size=cap.tie_bar_size,
                          bar_count=cap.tie_bar_count, member=("A", "B"))
    result = SimpleNamespace(
        report=SimpleNamespace(ties=[tie]),
        model=SimpleNamespace(nodes={"A": (0.0, tie_y),
                                     "B": (cap.span_ft, tie_y)}))
    cand = DepthCandidate(depth=cap.depth_ft, cost=0.0, concrete_cost=0.0,
                          steel_lb=0.0, strut_angle=0.0, node_ratio=0.0,
                          max_tie=0.0, complete=True, feasible=True,
                          result=result)
    return PierCapDesign(optimal=cand, candidates=[cand],
                         span=cap.span_ft, thickness=cap.thickness_ft)


def _footing_spec(footing: FootingRecord | None):
    """The layout-side :class:`FootingSpec`, or None."""
    if footing is None:
        return None
    from civilpy.structural.substructure_layout import FootingSpec
    return FootingSpec(length_ft=footing.length_ft,
                       width_ft=footing.width_ft,
                       thickness_ft=footing.thickness_ft)


@dataclass(frozen=True)
class HammerheadPierRecord(ElementRecord):
    """One hammerhead pier as a storable parametric record — the Phase-1
    vertical slice of the queryable-BIM schema.  ``standard`` +
    ``standard_year`` key the standards-catalog defaults lookup;
    :meth:`build` reconstitutes the geometry-builder spec so a record
    read back from storage regenerates placement, the tagged ``.3dm``
    emit, and the check inputs in :data:`HAMMERHEAD_CHECK_INPUTS`."""

    pier_cap: PierCapRecord
    pier_stem: PierStemRecord
    footing: FootingRecord | None = None
    detailing: CapDetailingRecord | None = spec_field(None)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    #: identity keys stamped into the flattened document
    BIM_TYPE = "pier"
    SUBTYPE = "hammerhead"

    def __post_init__(self):
        if self.detailing is None:
            object.__setattr__(self, "detailing", CapDetailingRecord())
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    # ── reconstitution: record -> executed-design objects ────────────
    def to_pier_column(self):
        """See :func:`_pier_column`."""
        return _pier_column(self.pier_stem, self.detailing.cover_in)

    def to_cap_design(self):
        """See :func:`_cap_design`."""
        return _cap_design(self.pier_cap)

    def build(self, layout, unit, **frame_kw):
        """Place the pier under ``layout`` — the same contract as the
        specs :func:`~civilpy.structural.substructure_layout
        .assemble_substructure` consumes, so a stored record slots
        straight into the emit pipeline."""
        from civilpy.structural.substructure_layout import HammerheadSpec

        return HammerheadSpec(
            cap_design=self.to_cap_design(), column=self.to_pier_column(),
            tip_depth_ft=self.pier_cap.tip_depth_ft,
            footing=_footing_spec(self.footing)).build(layout, unit,
                                                       **frame_kw)


def stem_rebar_layers(record: HammerheadPierRecord, n_layers: int = 2):
    """Break the stored stem steel into strain-compatibility layers for
    the P-M checks: half at each face, ``cover`` from the extreme
    fibers (the conventional two-layer idealization of a ring)."""
    from civilpy.structural.aashto.lrfd.columns import RebarLayer

    s = record.pier_stem
    depth = s.diameter_in if s.diameter_in is not None else s.h_in
    c = record.detailing.cover_in
    per = s.bars_area_in2 / n_layers
    return [RebarLayer(area=per,
                       depth=c + (depth - 2.0 * c) * k / (n_layers - 1))
            for k in range(n_layers)]


# ── shared sub-records for the Phase-6 breadth elements ──────────────────

@dataclass(frozen=True)
class PileRecord(SpecRecord):
    """A driven HP-pile group under a cap: positions along the support
    line (girder-1 frame, same as the cap design's supports), the AISC
    section, and the structural-check inputs.  Pay length is the driven
    length from the geotech recommendation."""

    xs_ft: tuple[float, ...] = spec_field(
        unit="ft", desc="pile centers along the cap, girder-1 frame")
    shape: str = spec_field("HP12X53", checks=("6.9.4.1.1",),
                            desc="AISC HP label (CPP-1-08 default)")
    length_ft: float = spec_field(40.0, unit="ft", gt=0.0,
                                  desc="driven/pay length")
    fy_ksi: float = spec_field(50.0, unit="ksi", gt=0.0,
                               checks=("6.9.4.1.1",))
    unbraced_length_ft: float = spec_field(
        0.0, unit="ft", ge=0.0, checks=("6.9.4.1.1",),
        desc="exposed/scour length; 0 = fully embedded")

    def _cross_validate(self):
        problems = []
        if not self.xs_ft:
            problems.append("xs_ft: at least one pile required")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                   for x in self.xs_ft):
            problems.append("xs_ft: entries must be numbers")
        return problems


@dataclass(frozen=True)
class WingwallRecord(SpecRecord):
    """Wingwall panel dimensions — the executed
    :class:`~civilpy.structural.abutment.RetainingWall` stem/footing as
    stored parameters, plus the run along the roadway.  The Section-11
    wall checks are not yet in the ported library, so this record is
    geometry/quantity space; its check-coverage entries land when they
    port (the §3 fallback: manual enumeration until the check exists)."""

    length_ft: float = spec_field(unit="ft", gt=0.0,
                                  desc="run along the roadway")
    stem_height_ft: float = spec_field(unit="ft", gt=0.0)
    stem_thickness_ft: float = spec_field(unit="ft", gt=0.0)
    base_width_ft: float = spec_field(unit="ft", gt=0.0)
    footing_thickness_ft: float = spec_field(unit="ft", gt=0.0)


# ── Phase-6 breadth: bent pier, pile bent, seat abutment ─────────────────

@dataclass(frozen=True)
class BentPierRecord(ElementRecord):
    """One multi-column bent pier: the cap envelope + governing tie (the
    bent cap's tie is normally the **bottom** chord — set
    ``pier_cap.tie_at_top=False`` when storing one), a uniform column
    section/steel, and the column centers along the cap.  Per-column
    height/section variation is a later refinement; the uniform case is
    the standard-drawing bent."""

    pier_cap: PierCapRecord
    column: PierStemRecord
    column_xs_ft: tuple[float, ...] = spec_field(
        unit="ft", desc="column centers from the cap's left end")
    footing: FootingRecord | None = None
    detailing: CapDetailingRecord | None = spec_field(None)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "pier"
    SUBTYPE = "bent"

    def __post_init__(self):
        if self.detailing is None:
            object.__setattr__(self, "detailing", CapDetailingRecord())
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def _cross_validate(self):
        problems = []
        if len(self.column_xs_ft) < 2:
            problems.append("column_xs_ft: a bent needs >= 2 columns "
                            "(one column is a hammerhead)")
        for x in self.column_xs_ft:
            if not 0.0 <= x <= self.pier_cap.span_ft:
                problems.append(f"column_xs_ft: {x} outside the cap span "
                                f"[0, {self.pier_cap.span_ft}]")
        return problems

    def to_bent(self):
        """The ``bent`` object :func:`~civilpy.structural
        .substructure_layout.pier_geometry` consumes: column positions in
        inches from the cap's left end + one executed column per
        position."""
        from types import SimpleNamespace

        col = _pier_column(self.column, self.detailing.cover_in)
        return SimpleNamespace(
            cap=SimpleNamespace(column_positions=[x * 12.0
                                                  for x in self.column_xs_ft]),
            columns=[col] * len(self.column_xs_ft))

    def build(self, layout, unit, **frame_kw):
        from civilpy.structural.substructure_layout import BentPierSpec

        return BentPierSpec(
            cap_design=_cap_design(self.pier_cap), bent=self.to_bent(),
            footing=_footing_spec(self.footing)).build(layout, unit,
                                                       **frame_kw)


@dataclass(frozen=True)
class PileBentRecord(ElementRecord):
    """One capped-pile pier (pile bent): the cap directly on driven HP
    piles — the CPP-1-08 pattern.  The cap design's supports are the
    piles, so the governing tie is normally the bottom chord."""

    pier_cap: PierCapRecord
    piles: PileRecord
    detailing: CapDetailingRecord | None = spec_field(None)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "pier"
    SUBTYPE = "pile_bent"

    def __post_init__(self):
        if self.detailing is None:
            object.__setattr__(self, "detailing", CapDetailingRecord())
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def build(self, layout, unit, **frame_kw):
        from civilpy.structural.substructure_layout import PileBentSpec

        return PileBentSpec(
            cap_design=_cap_design(self.pier_cap),
            pile_xs_ft=self.piles.xs_ft, pile_shape=self.piles.shape,
            pile_length_ft=self.piles.length_ft).build(layout, unit,
                                                       **frame_kw)


@dataclass(frozen=True)
class SeatAbutmentRecord(ElementRecord):
    """One conventional capped-pile seat abutment: the cap on driven
    piles, the backwall up to the low deck edge, and optional wingwalls.
    The semi-integral and integral variants get their own subtypes when
    they land (their geometry builders already exist)."""

    cap: PierCapRecord
    piles: PileRecord
    backwall_thickness_in: float = spec_field(18.0, unit="in", gt=0.0)
    wingwall: WingwallRecord | None = None
    detailing: CapDetailingRecord | None = spec_field(None)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "abutment"
    SUBTYPE = "seat"

    def __post_init__(self):
        if self.detailing is None:
            object.__setattr__(self, "detailing", CapDetailingRecord())
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def to_abutment_spec(self):
        """The layout-side :class:`~civilpy.structural
        .substructure_layout.AbutmentSpec` (wingwall reconstituted as the
        4-attribute wall the geometry builder reads)."""
        from types import SimpleNamespace

        from civilpy.structural.substructure_layout import AbutmentSpec

        wall = None
        length = 0.0
        if self.wingwall is not None:
            w = self.wingwall
            wall = SimpleNamespace(stem_height=w.stem_height_ft,
                                   stem_thickness=w.stem_thickness_ft,
                                   base_width=w.base_width_ft,
                                   footing_thickness=w.footing_thickness_ft)
            length = w.length_ft
        return AbutmentSpec(pile_xs_ft=self.piles.xs_ft,
                            pile_shape=self.piles.shape,
                            pile_length_ft=self.piles.length_ft,
                            backwall_thickness_in=self.backwall_thickness_in,
                            wingwall=wall, wingwall_length_ft=length)

    def build(self, layout, unit, **frame_kw):
        from civilpy.structural.substructure_layout import SeatAbutmentSpec

        return SeatAbutmentSpec(
            cap_design=_cap_design(self.cap),
            spec=self.to_abutment_spec()).build(layout, unit, **frame_kw)


# ── metrics sidecar ───────────────────────────────────────────────────────

def pier_metrics(geom) -> dict:
    """Derived metrics for one placed pier
    (:class:`~civilpy.structural.substructure_layout.PierGeometry`),
    reported at emit time — civilpy knows the semantic element, so this
    is cheaper and safer than re-measuring meshes.  The application side
    lands these next to the JSONB record and promotes the query-hot ones
    to generated columns."""
    cap = geom.cap
    cols = geom.columns
    m = {
        "cap_length_ft": cap.length_ft,
        "cap_width_ft": cap.width_ft,
        "cap_depth_ft": cap.depth_ft,
        "cap_volume_cy": round(cap.volume_cy, 3),
        "cap_top_elev_ft": cap.origin[2],
        "n_seats": len(geom.seats),
        "n_columns": len(cols),
        "n_piles": len(geom.piles),
    }
    if cap.soffit_profile is not None:
        m["tip_depth_ft"] = min(d for _, d in cap.soffit_profile)
    if geom.piles:
        m["pile_total_lf"] = round(sum(p.length_ft for p in geom.piles), 1)
    if cols:
        m["stem_height_ft"] = round(
            max(c.height_ft for c in cols), 3)
        m["stem_volume_cy"] = round(sum(c.volume_cy for c in cols), 3)
        z_lo = min(c.z_bot for c in cols)
    else:
        z_lo = min((p.head[2] - p.length_ft for p in geom.piles),
                   default=cap.origin[2] - cap.depth_ft)
    if geom.footings:
        m["footing_volume_cy"] = round(
            sum(f.volume_cy for f in geom.footings), 3)
        z_lo = min(z_lo, min(f.z_top - f.thickness_ft
                             for f in geom.footings))
    seats_cy = sum((s.side_in / 12.0) ** 2 * (s.height_in / 12.0) / 27.0
                   for s in geom.seats)
    m["concrete_cy"] = round(
        cap.volume_cy + seats_cy
        + sum(c.volume_cy for c in cols)
        + sum(f.volume_cy for f in geom.footings), 3)
    m["height_ft"] = round(cap.origin[2] - z_lo, 3)
    return m


def abutment_metrics(geom) -> dict:
    """Derived metrics for one placed abutment
    (:class:`~civilpy.structural.substructure_layout.AbutmentGeometry`)
    — same emit-time sidecar contract as :func:`pier_metrics`."""
    cap = geom.cap
    m = {
        "cap_length_ft": cap.length_ft,
        "cap_width_ft": cap.width_ft,
        "cap_depth_ft": cap.depth_ft,
        "cap_volume_cy": round(cap.volume_cy, 3),
        "cap_top_elev_ft": cap.origin[2],
        "n_seats": len(geom.seats),
        "n_piles": len(geom.piles),
        "pile_total_lf": round(sum(p.length_ft for p in geom.piles), 1),
    }
    walls_cy = 0.0
    z_hi = cap.origin[2]
    if geom.backwall is not None:
        m["backwall_height_ft"] = round(geom.backwall.height_ft, 3)
        walls_cy += geom.backwall.volume_cy
        z_hi = max(z_hi, geom.backwall.origin[2] + geom.backwall.height_ft)
    if geom.diaphragm is not None:
        m["diaphragm_height_ft"] = round(geom.diaphragm.height_ft, 3)
        walls_cy += geom.diaphragm.volume_cy
        z_hi = max(z_hi, geom.diaphragm.origin[2]
                   + geom.diaphragm.height_ft)
    if geom.wingwalls:
        m["wingwall_volume_cy"] = round(
            sum(w.volume_cy for w in geom.wingwalls), 3)
        walls_cy += sum(w.volume_cy for w in geom.wingwalls)
    seats_cy = sum((s.side_in / 12.0) ** 2 * (s.height_in / 12.0) / 27.0
                   for s in geom.seats)
    m["concrete_cy"] = round(cap.volume_cy + seats_cy + walls_cy, 3)
    m["height_ft"] = round(z_hi - (cap.origin[2] - cap.depth_ft), 3)
    return m


# ── check-coverage map (the §3 forcing function) ──────────────────────────

#: How each LRFD check consuming a hammerhead resolves its inputs.
#: Values are ``("field", "<dotted record path>")`` for a direct read,
#: ``("derived", (<paths>...), "<how>")`` for a value computed from
#: record fields, and ``("loads", "<what>")`` for demand-side inputs
#: that come from the superstructure reactions / analysis, not the
#: element record.  ``tests/structural/test_bim_spec.py`` asserts every
#: required parameter of every listed check is mapped and every mapped
#: path exists on the record schema — a gap is a failing test, i.e. the
#: live backlog of missing parameters.
HAMMERHEAD_CHECK_INPUTS: dict[str, dict[str, tuple]] = {
    # cap D-region (STM)
    "5.8.2.4": {
        "a_st": ("derived", ("pier_cap.tie_bar_size",
                             "pier_cap.tie_bar_count"),
                 "bar area x count"),
        "f_y": ("field", "pier_cap.fy_ksi"),
        "p_u": ("loads", "governing tie force from the STM solve"),
    },
    "5.8.2.5": {
        "a_cn": ("derived", ("pier_cap.thickness_ft",
                             "detailing.seat_side_in"),
                 "node face area: seat side x min(cap width, seat side)"),
        "f_c": ("field", "pier_cap.fc_ksi"),
        "p_u": ("loads", "strut / node face force from the STM solve"),
    },
    "5.8.2.6": {
        "b_w": ("field", "pier_cap.thickness_ft"),
        "s_h": ("field", "detailing.stirrup_spacing_in"),
        "s_v": ("field", "detailing.skin_bar_spacing_in"),
        "a_s_horizontal": ("derived", ("detailing.skin_bar_size",),
                           "two-face skin bar area"),
        "a_s_vertical": ("derived", ("detailing.stirrup_size",),
                         "stirrup legs area"),
    },
    # cap sectional checks away from the D-region
    "5.7.3.3": {
        "b_v": ("field", "pier_cap.thickness_ft"),
        "d_v": ("derived", ("pier_cap.depth_ft", "detailing.cover_in",
                            "pier_cap.tie_bar_size"),
                "effective shear depth from the section"),
        "f_c": ("field", "pier_cap.fc_ksi"),
        "a_v": ("derived", ("detailing.stirrup_size",),
                "stirrup legs area"),
        "s": ("field", "detailing.stirrup_spacing_in"),
        "f_y": ("field", "pier_cap.fy_ksi"),
        "v_u": ("loads", "factored shear at the section"),
    },
    "5.7.2.5": {
        "b_v": ("field", "pier_cap.thickness_ft"),
        "s": ("field", "detailing.stirrup_spacing_in"),
        "f_c": ("field", "pier_cap.fc_ksi"),
        "a_v": ("derived", ("detailing.stirrup_size",),
                "stirrup legs area"),
    },
    "5.7.2.6": {
        "v_u": ("loads", "factored shear at the section"),
        "b_v": ("field", "pier_cap.thickness_ft"),
        "d_v": ("derived", ("pier_cap.depth_ft", "detailing.cover_in",
                            "pier_cap.tie_bar_size"),
                "effective shear depth from the section"),
        "f_c": ("field", "pier_cap.fc_ksi"),
    },
    "5.6.7": {
        "d_c": ("derived", ("detailing.cover_in", "pier_cap.tie_bar_size"),
                "cover + half bar diameter"),
        "h": ("field", "pier_cap.depth_ft"),
        "f_ss": ("loads", "service tie-steel stress"),
    },
    "5.10.8.2.1": {
        "d_b": ("derived", ("pier_cap.tie_bar_size",), "bar diameter"),
        "f_y": ("field", "pier_cap.fy_ksi"),
        "f_c": ("field", "pier_cap.fc_ksi"),
    },
    # stem (compression member)
    "5.6.4.4": {
        "a_g": ("derived", ("pier_stem.b_in", "pier_stem.h_in",
                            "pier_stem.diameter_in"), "gross area"),
        "a_st": ("field", "pier_stem.bars_area_in2"),
        "f_c": ("field", "pier_stem.fc_ksi"),
        "f_y": ("field", "pier_stem.fy_ksi"),
        "spiral": ("field", "pier_stem.spiral"),
        "p_u": ("loads", "factored axial from the cap reactions"),
    },
    "5.6.4.2": {
        "a_g": ("derived", ("pier_stem.b_in", "pier_stem.h_in",
                            "pier_stem.diameter_in"), "gross area"),
        "a_st": ("field", "pier_stem.bars_area_in2"),
        "f_c": ("field", "pier_stem.fc_ksi"),
        "f_y": ("field", "pier_stem.fy_ksi"),
    },
    "5.6.4.5 check": {
        "p_u": ("loads", "factored axial"),
        "m_u": ("loads", "factored (magnified) moment"),
        "layers": ("derived", ("pier_stem.bars_area_in2",
                               "detailing.cover_in", "pier_stem.h_in",
                               "pier_stem.diameter_in"),
                   "stem_rebar_layers()"),
        "f_c": ("field", "pier_stem.fc_ksi"),
        "f_y": ("field", "pier_stem.fy_ksi"),
        "h": ("field", "pier_stem.h_in"),
        "b": ("field", "pier_stem.b_in"),
        "diameter": ("field", "pier_stem.diameter_in"),
        "spiral": ("field", "pier_stem.spiral"),
    },
    "4.5.3.2.2b": {
        "p_u": ("loads", "factored axial"),
        "p_e": ("derived", ("pier_stem.b_in", "pier_stem.h_in",
                            "pier_stem.diameter_in",
                            "pier_stem.height_ft", "pier_stem.fixity",
                            "pier_stem.fc_ksi"),
                "Euler load from cracked EI and effective length"),
        "m_2": ("loads", "larger end moment"),
    },
}


def _retarget(mapping: dict, renames: dict[str, str]) -> dict:
    """A copy of a check-inputs map with record-path prefixes renamed —
    the cap/column checks are the same physics on every cap-on-support
    element; only the field paths differ per record class.  The coverage
    test resolves the result against the target record, so a bad rename
    fails loudly."""
    def fix(path: str) -> str:
        for old, new in renames.items():
            if path.startswith(old):
                return new + path[len(old):]
        return path

    out = {}
    for article, inputs in mapping.items():
        out[article] = {}
        for param, entry in inputs.items():
            if entry[0] == "field":
                out[article][param] = ("field", fix(entry[1]))
            elif entry[0] == "derived":
                out[article][param] = ("derived",
                                       tuple(fix(p) for p in entry[1]),
                                       entry[2])
            else:
                out[article][param] = entry
    return out


#: The cap D-region / sectional / detailing checks — identical on every
#: cap-on-support element (hammerhead, bent, pile bent, abutment).
_CAP_ARTICLES = ("5.8.2.4", "5.8.2.5", "5.8.2.6", "5.7.3.3", "5.7.2.5",
                 "5.7.2.6", "5.6.7", "5.10.8.2.1")

#: The compression-member checks the hammerhead stem runs — a bent's
#: columns run the same set.
_COLUMN_ARTICLES = ("5.6.4.4", "5.6.4.2", "5.6.4.5 check", "4.5.3.2.2b")

#: Driven HP piles: steel compression member (kl/r from the section and
#: the exposed/scour length; fully-embedded piles are axial-only).
_PILE_CHECK_INPUTS: dict[str, dict[str, tuple]] = {
    "6.9.4.1.1": {
        "a_g": ("derived", ("piles.shape",), "AISC HP section area"),
        "f_y": ("field", "piles.fy_ksi"),
        "kl_over_r": ("derived", ("piles.shape",
                                  "piles.unbraced_length_ft"),
                      "K*Lu/r_y from the section and exposed length"),
        "p_u": ("loads", "factored pile reaction"),
    },
}

#: Multi-column bent: the hammerhead map with the stem paths renamed to
#: the bent's uniform ``column`` record (same checks, same physics).
BENT_PIER_CHECK_INPUTS: dict[str, dict[str, tuple]] = _retarget(
    HAMMERHEAD_CHECK_INPUTS, {"pier_stem.": "column."})

#: Pile bent: the cap family plus the pile compression check.
PILE_BENT_CHECK_INPUTS: dict[str, dict[str, tuple]] = {
    **{a: HAMMERHEAD_CHECK_INPUTS[a] for a in _CAP_ARTICLES},
    **_PILE_CHECK_INPUTS,
}

#: Seat abutment: cap family (paths under ``cap.``) plus piles.  The
#: backwall / wingwall (Section 11) checks are not yet in the ported
#: library — their fields are geometry/quantity space until they land
#: (the §3 fallback), at which point they join this map.
SEAT_ABUTMENT_CHECK_INPUTS: dict[str, dict[str, tuple]] = {
    **_retarget({a: HAMMERHEAD_CHECK_INPUTS[a] for a in _CAP_ARTICLES},
                {"pier_cap.": "cap."}),
    **_PILE_CHECK_INPUTS,
}


def record_paths(cls) -> set[str]:
    """Every dotted field path reachable on a record class (Optionals
    unwrapped, nested records recursed) — the schema surface the
    coverage test resolves against."""
    out: set[str] = set()
    hints = typing.get_type_hints(cls)
    for f in fields(cls):
        out.add(f.name)
        tp = _strip_optional(hints[f.name])
        if is_dataclass(tp):
            out |= {f"{f.name}.{p}" for p in record_paths(tp)}
        elif typing.get_origin(tp) is tuple:
            args = typing.get_args(tp)
            if args and is_dataclass(args[0]):
                # a schedule (tuple of records): a check input can reference the
                # element-type fields — "some entry has this field", the losless
                # per-bay / per-splice model
                out |= {f"{f.name}.{p}" for p in record_paths(args[0])}
    return out


# ══ Phase-6a: superstructure girder record + beam-customization spaces ══════
#
# Build plan §3a.  The superstructure emit draws prismatic rolled girders only
# (a catalog label, composite reduced to a stud toggle); the real-bridge
# details below have no space to live in the schema and would be silently
# dropped by the BIM round-trip.  Each gets the §3a three-part treatment: a
# JSON-safe record with field metadata, a place on the girder for the tagged
# emit to consume, and check-coverage-map entries.  These land *before* the
# BrR->Spec extract that fills them (§9): the girder record must exist first or
# extraction has nowhere to put the data.
#
# Consuming checks that are already ported to ``aashto.lrfd`` go straight into
# the coverage map (6.10.8 flange/LTB, 6.10.9 web shear, 6.10.10 studs,
# 6.10.11.2.3 bearing stiffener, 6.13.6 splice, 6.8.2.1/6.9.4.1.1 cross-frame
# members).  The two that are *not* yet ported -- 6.7.4 (cross-frame spacing)
# and 6.10.11.3 (longitudinal stiffener) -- leave their fields as
# geometry/quantity space until they land, exactly the WingwallRecord fallback.
#
# A customization the checks consume is a *single* nested record (like
# ``PileRecord`` under a bent): one controlling detail whose scalar fields the
# coverage test resolves.  The full variable-depth plate schedule rides in the
# ``plates`` tuple as geometry/quantity space -- a tapered prism is still a
# loop + profile, so the mesh emit reuses unchanged.


@dataclass(frozen=True)
class GirderSectionRecord(SpecRecord):
    """The girder cross-section the sectional checks run on: EITHER a cataloged
    rolled shape (``label``) OR an explicit built-up plate section.  This is the
    single controlling section (the design's governing positive-moment / pier
    section); the whole variable-depth schedule lives in
    :attr:`SteelGirderRecord.plates`.  Give exactly one representation -- a
    label or the full set of plate dims -- and :meth:`resolve` returns the
    ``(d, t_w, b_fc, t_fc)`` the checks need from whichever is present."""

    label: str | None = spec_field(
        None, desc="AISC rolled shape, e.g. W36X150",
        checks=("6.10.8.2.2", "6.10.8.2.3", "6.10.9"))
    web_depth_in: float | None = spec_field(
        None, unit="in", gt=0.0, checks=("6.10.9", "6.10.8.2.3"))
    web_thickness_in: float | None = spec_field(
        None, unit="in", gt=0.0, checks=("6.10.9", "6.10.8.2.3"))
    top_flange_width_in: float | None = spec_field(
        None, unit="in", gt=0.0, checks=("6.10.8.2.2", "6.10.8.2.3"))
    top_flange_thickness_in: float | None = spec_field(
        None, unit="in", gt=0.0, checks=("6.10.8.2.2", "6.10.8.2.3"))
    bot_flange_width_in: float | None = spec_field(None, unit="in", gt=0.0)
    bot_flange_thickness_in: float | None = spec_field(None, unit="in", gt=0.0)
    fyc_ksi: float = spec_field(50.0, unit="ksi", gt=0.0,
                                checks=("6.10.8.2.2", "6.10.8.2.3"))
    fyw_ksi: float = spec_field(50.0, unit="ksi", gt=0.0,
                                checks=("6.10.9", "6.10.8.2.2", "6.10.8.2.3"))

    _PLATE_DIMS = ("web_depth_in", "web_thickness_in", "top_flange_width_in",
                   "top_flange_thickness_in", "bot_flange_width_in",
                   "bot_flange_thickness_in")

    def _cross_validate(self):
        has_label = self.label is not None
        has_plates = all(getattr(self, n) is not None
                         for n in self._PLATE_DIMS)
        if has_label == has_plates:
            return ["give either a catalog label or a full plate section, "
                    "not both / neither"]
        return []

    def resolve(self) -> tuple[float, float, float, float]:
        """``(depth, web_thickness, top_flange_width, top_flange_thickness)``
        in inches -- from the AISC catalog when a ``label`` is stored, else the
        explicit plate dims."""
        if self.label is not None:
            from civilpy.structural.bridge_layout import girder_section
            gs = girder_section(self.label)
            return (gs.depth, gs.web_thickness, gs.flange_width,
                    gs.flange_thickness)
        return (self.web_depth_in, self.web_thickness_in,
                self.top_flange_width_in, self.top_flange_thickness_in)


@dataclass(frozen=True)
class PlateSegmentRecord(SpecRecord):
    """One station-ranged built-up girder segment: the web + flange plates over
    ``[x_start_ft, x_end_ft]``.  Variable depth rides on ``web_depth_in``
    varying between segments; flange transitions on the flange plate dims.
    Geometry/quantity space for the mesh emit -- the sectional checks run on the
    single :class:`GirderSectionRecord`."""

    x_start_ft: float = spec_field(unit="ft", ge=0.0)
    x_end_ft: float = spec_field(unit="ft", gt=0.0)
    web_depth_in: float = spec_field(unit="in", gt=0.0)
    web_thickness_in: float = spec_field(unit="in", gt=0.0)
    top_flange_width_in: float = spec_field(unit="in", gt=0.0)
    top_flange_thickness_in: float = spec_field(unit="in", gt=0.0)
    bot_flange_width_in: float = spec_field(unit="in", gt=0.0)
    bot_flange_thickness_in: float = spec_field(unit="in", gt=0.0)

    def _cross_validate(self):
        if self.x_end_ft <= self.x_start_ft:
            return [f"x_end_ft {self.x_end_ft} must exceed x_start_ft "
                    f"{self.x_start_ft}"]
        return []


@dataclass(frozen=True)
class CompositeRecord(SpecRecord):
    """The shear-stud connection + composite deck properties -- promotes what
    were emit-time stud arguments into stored fields so a bridge round-trips
    them.  Consuming checks 6.10.10 (fatigue pitch, stud strength)."""

    stud_diameter_in: float = spec_field(
        0.875, unit="in", gt=0.0,
        checks=("6.10.10.1.2", "6.10.10.4", "6.10.10.2", "6.10.10.3"))
    studs_per_row: int = spec_field(3, ge=1,
                                    checks=("6.10.10.1.2", "6.10.10.3"))
    stud_gauge_in: float = spec_field(3.0, unit="in", gt=0.0,
                                      checks=("6.10.10.3",),
                                      desc="transverse c/c between studs")
    pitch_in: float = spec_field(12.0, unit="in", gt=0.0,
                                 checks=("6.10.10.1.2",),
                                 desc="longitudinal stud pitch, governing zone")
    effective_width_in: float = spec_field(
        96.0, unit="in", gt=0.0, desc="effective flange width (4.6.2.6)")
    modular_ratio_n: float = spec_field(8.0, gt=0.0,
                                        desc="steel/concrete modular ratio")
    haunch_in: float = spec_field(2.0, unit="in", ge=0.0)
    deck_fc_ksi: float = spec_field(4.5, unit="ksi", gt=0.0,
                                    checks=("6.10.10.4",))


@dataclass(frozen=True)
class TransverseStiffenerRecord(SpecRecord):
    """Transverse web stiffener plates on the governing shear zone: dims +
    the panel spacing ``d_o`` that turns on 6.10.9's stiffened-panel path.
    The record's presence means a stiffened web (absent = the unstiffened
    default)."""

    plate_width_in: float = spec_field(unit="in", gt=0.0,
                                       checks=("6.10.11.1.2", "6.10.11.1.3"))
    plate_thickness_in: float = spec_field(
        unit="in", gt=0.0, checks=("6.10.11.1.2", "6.10.11.1.3"))
    spacing_in: float = spec_field(unit="in", gt=0.0,
                                   checks=("6.10.11.1.3",),
                                   desc="panel length d_o (feeds 6.10.9)")
    single_sided: bool = spec_field(False)
    fy_ksi: float = spec_field(50.0, unit="ksi", gt=0.0,
                               checks=("6.10.11.1.3",))


@dataclass(frozen=True)
class BearingStiffenerRecord(SpecRecord):
    """Bearing stiffener plate pair at a support (6.10.11.2.3)."""

    plate_width_in: float = spec_field(unit="in", gt=0.0,
                                       checks=("6.10.11.2.3",))
    plate_thickness_in: float = spec_field(unit="in", gt=0.0,
                                           checks=("6.10.11.2.3",))
    pairs: int = spec_field(1, ge=1, checks=("6.10.11.2.3",),
                            desc="stiffener pairs at the seat")
    fy_ksi: float = spec_field(50.0, unit="ksi", gt=0.0,
                               checks=("6.10.11.2.3",))
    milled_to_bear: bool = spec_field(True)


@dataclass(frozen=True)
class LongitudinalStiffenerRecord(SpecRecord):
    """Longitudinal web stiffener on a deep web.  6.10.11.3 is not yet in the
    ported library, so this is geometry/quantity space; its check-coverage
    entry lands when the article ports (the :class:`WingwallRecord`
    fallback)."""

    plate_width_in: float = spec_field(unit="in", gt=0.0)
    plate_thickness_in: float = spec_field(unit="in", gt=0.0)
    location_from_top_flange_in: float = spec_field(
        unit="in", gt=0.0, desc="stiffener depth below the compression flange")
    fy_ksi: float = spec_field(50.0, unit="ksi", gt=0.0)


@dataclass(frozen=True)
class CrossFrameRecord(SpecRecord):
    """An intermediate cross-frame / steel diaphragm bay: type, member section,
    connection plate, and along-span spacing.  The members run the ported
    tension/compression checks (6.8.2.1 / 6.9.4.1.1); the *spacing* feeds
    6.7.4 when it ports and the LTB unbraced length today (6.10.8.2.3
    ``l_b``)."""

    frame_type: str = spec_field("K", enum=("X", "K", "bent_plate"))
    member_shape: str = spec_field("L4X4X1/2", checks=("6.8.2.1", "6.9.4.1.1"),
                                   desc="AISC angle/WT/channel label")
    member_length_ft: float = spec_field(
        6.0, unit="ft", gt=0.0, checks=("6.9.4.1.1",),
        desc="diagonal/chord work length")
    spacing_ft: float = spec_field(20.0, unit="ft", gt=0.0,
                                   desc="uniform along-span spacing fallback")
    stations_ft: tuple[float, ...] | None = spec_field(
        None, unit="ft",
        desc="explicit cross-frame line stations — the lossless per-bay "
             "placement for irregular spacing; None = uniform at spacing_ft")
    connection_plate_thickness_in: float = spec_field(0.5, unit="in", gt=0.0)
    fy_ksi: float = spec_field(50.0, unit="ksi", gt=0.0,
                               checks=("6.8.2.1", "6.9.4.1.1"))

    def bay_stations(self, length_ft: float) -> tuple[float, ...]:
        """The cross-frame line stations along a girder of ``length_ft``:
        the stored :attr:`stations_ft` when given (irregular spacing kept
        verbatim), else a uniform run at :attr:`spacing_ft`."""
        if self.stations_ft is not None:
            return tuple(self.stations_ft)
        n = max(1, int(round(length_ft / self.spacing_ft)))
        return tuple(self.spacing_ft * k for k in range(1, n))

    def max_bay_ft(self, length_ft: float) -> float:
        """Governing unbraced length ``l_b`` = the largest gap between brace
        points (span ends included)."""
        pts = (0.0, *self.bay_stations(length_ft), length_ft)
        return max(b - a for a, b in zip(pts, pts[1:]))

    def _cross_validate(self):
        if self.stations_ft is not None and not all(
                isinstance(s, (int, float)) and not isinstance(s, bool)
                and s > 0 for s in self.stations_ft):
            return ["stations_ft: entries must be positive numbers"]
        return []


@dataclass(frozen=True)
class FieldSpliceRecord(SpecRecord):
    """A bolted field splice on the girder (6.13.6 family): location, the
    flange/web splice-plate schedule as the checks size it, and the bolt group.
    Ties into the NSBA splice designer and the girder->splice ``gdr.*``
    contract."""

    station_ft: float = spec_field(unit="ft", ge=0.0)
    flange_width_left_in: float = spec_field(unit="in", gt=0.0,
                                             checks=("6.13.6.1.3b",))
    flange_width_right_in: float = spec_field(unit="in", gt=0.0,
                                              checks=("6.13.6.1.3b",))
    flange_thickness_in: float = spec_field(unit="in", gt=0.0,
                                            checks=("6.13.6.1.3b", "6.13.6.1.4"))
    web_depth_in: float = spec_field(unit="in", gt=0.0,
                                     checks=("6.13.6.1.3c",))
    web_thickness_left_in: float = spec_field(
        unit="in", gt=0.0, checks=("6.13.6.1.3b", "6.13.6.1.3c"))
    web_thickness_right_in: float = spec_field(
        unit="in", gt=0.0, checks=("6.13.6.1.3b", "6.13.6.1.3c"))
    flange_clearance_in: float = spec_field(1.0, unit="in", gt=0.0,
                                            checks=("6.13.6.1.3c",))
    splice_plate_thickness_in: float = spec_field(
        0.5, unit="in", gt=0.0, checks=("6.13.6.1.4",),
        desc="flange splice plate thickness (filler reduction)")
    bolt_diameter_in: float = spec_field(0.875, unit="in", gt=0.0)
    bolt_rows: int = spec_field(2, ge=1)
    bolt_cols: int = spec_field(3, ge=1)
    bolt_fu_ksi: float = spec_field(120.0, unit="ksi", gt=0.0)
    plate_fy_ksi: float = spec_field(50.0, unit="ksi", gt=0.0)
    plate_fu_ksi: float = spec_field(65.0, unit="ksi", gt=0.0)


@dataclass(frozen=True)
class SteelGirderRecord(ElementRecord):
    """One steel girder line as a storable parametric record -- the Phase-6a
    superstructure schema space.  ``section`` is the controlling section (a
    catalog label or a built-up plate section); the optional customization
    records give cross-frames, stiffeners, the composite block, and a field
    splice somewhere to live.  ``plates`` carries the full variable-depth
    schedule for the mesh emit.  The check inputs are in
    :data:`GIRDER_CHECK_INPUTS`."""

    section: GirderSectionRecord
    length_ft: float = spec_field(unit="ft", gt=0.0)
    grade: str = spec_field("Grade 50",
                            enum=("Grade 36", "Grade 50", "Grade 50W",
                                  "Grade HPS70W"))
    plates: tuple[PlateSegmentRecord, ...] | None = spec_field(
        None, desc="variable-depth plate schedule (emit/quantity space)")
    composite: CompositeRecord | None = spec_field(None)
    transverse_stiffener: TransverseStiffenerRecord | None = spec_field(None)
    bearing_stiffener: BearingStiffenerRecord | None = spec_field(None)
    longitudinal_stiffener: LongitudinalStiffenerRecord | None = \
        spec_field(None)
    cross_frame: CrossFrameRecord | None = spec_field(None)
    splices: tuple[FieldSpliceRecord, ...] | None = spec_field(
        None, desc="bolted field splices — each independent (plate/bolt "
                   "schedules need not match between splices)")
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "girder"
    SUBTYPE = "steel"

    def __post_init__(self):
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def _cross_validate(self):
        problems = []
        if self.plates is not None:
            for i, seg in enumerate(self.plates):
                problems += [f"plates[{i}].{p}" for p in seg.validate()]
            spans = [(s.x_start_ft, s.x_end_ft) for s in self.plates]
            for (a0, a1), (b0, _) in zip(spans, spans[1:]):
                if abs(a1 - b0) > 1e-6:
                    problems.append(
                        f"plates: gap/overlap between {a1} and {b0} ft")
            if spans and spans[-1][1] - spans[0][0] > self.length_ft + 1e-6:
                problems.append("plates: schedule runs past length_ft")
        # tuple-of-record schedules aren't auto-recursed by validate()
        for i, sp in enumerate(self.splices or ()):
            problems += [f"splices[{i}].{p}" for p in sp.validate()]
        return problems

    def to_bridge_input(self, *, girder_count: int, girder_spacing_ft: float,
                        overhang_ft: float, spans_ft=None, **overrides):
        """Reconstitute the :class:`~civilpy.structural.bridge_layout
        .BridgeInput` the superstructure emit consumes today.  Only a cataloged
        ``section.label`` maps into the current prismatic engine; a plate
        schedule and the stiffener/cross-frame/splice records are carried for
        the emit extension (§3a follow-on) and raise here until it lands."""
        from civilpy.structural.bridge_layout import BridgeInput

        if self.section.label is None:
            raise NotImplementedError(
                "plate-section emit is the §3a geometry follow-on; the "
                "current engine takes a catalog label only")
        return BridgeInput(
            spans_ft=tuple(spans_ft) if spans_ft else (self.length_ft,),
            girder_count=girder_count, girder_spacing_ft=girder_spacing_ft,
            girder_label=self.section.label, overhang_ft=overhang_ft,
            grade=self.grade,
            composite=self.composite is not None, **overrides)


def girder_metrics(record: SteelGirderRecord) -> dict:
    """Derived, JSON-safe metrics for the sidecar/generated columns: the
    query-hot superstructure numbers, computed from the record (not remeasured
    off the mesh) the way ``pier_metrics`` is."""
    d, t_w, b_fc, t_fc = record.section.resolve()
    m: dict = {
        "length_ft": record.length_ft,
        "section_label": record.section.label,
        "web_depth_in": d,
        "is_composite": record.composite is not None,
        "is_plate_girder": record.section.label is None,
        "n_plate_segments": len(record.plates) if record.plates else 0,
        "has_transverse_stiffeners": record.transverse_stiffener is not None,
        "has_bearing_stiffeners": record.bearing_stiffener is not None,
        "has_longitudinal_stiffener":
            record.longitudinal_stiffener is not None,
        "n_splices": len(record.splices) if record.splices else 0,
    }
    if record.cross_frame is not None:
        m["cross_frame_bays"] = max(
            1, round(record.length_ft / record.cross_frame.spacing_ft))
        m["cross_frame_type"] = record.cross_frame.frame_type
    return m


#: The check-coverage map for a steel girder line (build plan §3, applied to
#: §3a).  Aggregates every ported LRFD check that consumes some part of the
#: girder and where its inputs live.  ``("loads", ...)`` marks a demand from
#: the line-girder / grillage analysis, not a stored field.  The coverage test
#: asserts every required parameter of every listed check resolves to a path on
#: :class:`SteelGirderRecord`.  Not-yet-ported checks (6.7.4 cross-frame
#: spacing, 6.10.11.3 longitudinal stiffener) are deliberately absent -- their
#: fields are quantity space until the article lands.
GIRDER_CHECK_INPUTS: dict[str, dict[str, tuple]] = {
    # compression-flange local buckling
    "6.10.8.2.2": {
        "b_fc": ("derived", ("section.label", "section.top_flange_width_in"),
                 "compression-flange width from the catalog DB or plates"),
        "t_fc": ("derived", ("section.label",
                             "section.top_flange_thickness_in"),
                 "compression-flange thickness"),
        "f_yc": ("field", "section.fyc_ksi"),
        "f_yw": ("field", "section.fyw_ksi"),
    },
    # lateral-torsional buckling (unbraced length = governing cross-frame bay)
    "6.10.8.2.3": {
        "l_b": ("derived", ("cross_frame.stations_ft",
                            "cross_frame.spacing_ft"),
                "governing unbraced length = max bay (CrossFrameRecord."
                "max_bay_ft), from the per-bay stations or uniform spacing"),
        "b_fc": ("derived", ("section.label", "section.top_flange_width_in"),
                 "compression-flange width"),
        "t_fc": ("derived", ("section.label",
                             "section.top_flange_thickness_in"),
                 "compression-flange thickness"),
        "d_c": ("derived", ("section.label", "section.web_depth_in"),
                "depth of web in compression"),
        "t_w": ("derived", ("section.label", "section.web_thickness_in"),
                "web thickness"),
        "f_yc": ("field", "section.fyc_ksi"),
        "f_yw": ("field", "section.fyw_ksi"),
    },
    # web shear (d_o from the transverse stiffener turns on the panel path)
    "6.10.9": {
        "d_web": ("derived", ("section.label", "section.web_depth_in"),
                  "web depth"),
        "t_w": ("derived", ("section.label", "section.web_thickness_in"),
                "web thickness"),
        "f_yw": ("field", "section.fyw_ksi"),
    },
    # shear-connector fatigue pitch
    "6.10.10.1.2": {
        "d_stud": ("field", "composite.stud_diameter_in"),
        "n_per_row": ("field", "composite.studs_per_row"),
        "shear_flow": ("loads", "fatigue horizontal shear flow at the section"),
        "pitch": ("field", "composite.pitch_in"),
    },
    # shear-connector strength
    "6.10.10.4": {
        "d_stud": ("field", "composite.stud_diameter_in"),
        "f_c": ("field", "composite.deck_fc_ksi"),
        "e_c": ("derived", ("composite.deck_fc_ksi",),
                "deck modulus from f_c (C5.4.2.4)"),
    },
    # bearing stiffener
    "6.10.11.2.3": {
        "a_pn": ("derived", ("bearing_stiffener.plate_width_in",
                             "bearing_stiffener.plate_thickness_in",
                             "bearing_stiffener.pairs"),
                 "net projecting bearing area"),
        "f_ys": ("field", "bearing_stiffener.fy_ksi"),
    },
    # cross-frame member: tension
    "6.8.2.1": {
        "a_g": ("derived", ("cross_frame.member_shape",),
                "AISC member gross area"),
        "f_y": ("field", "cross_frame.fy_ksi"),
    },
    # cross-frame member: compression
    "6.9.4.1.1": {
        "a_g": ("derived", ("cross_frame.member_shape",),
                "AISC member gross area"),
        "f_y": ("field", "cross_frame.fy_ksi"),
        "kl_over_r": ("derived", ("cross_frame.member_shape",
                                  "cross_frame.member_length_ft"),
                      "K*L/r_y from the section and work length"),
    },
    # field splice: flange plates (per splice in the schedule)
    "6.13.6.1.3b": {
        "flange_width_left": ("field", "splices.flange_width_left_in"),
        "flange_width_right": ("field", "splices.flange_width_right_in"),
        "flange_thickness": ("field", "splices.flange_thickness_in"),
        "web_thickness_left": ("field", "splices.web_thickness_left_in"),
        "web_thickness_right": ("field", "splices.web_thickness_right_in"),
    },
    # field splice: web plate
    "6.13.6.1.3c": {
        "web_depth": ("field", "splices.web_depth_in"),
        "web_thickness": ("field", "splices.web_thickness_left_in"),
        "web_thickness_other": ("field", "splices.web_thickness_right_in"),
        "flange_clearance": ("field", "splices.flange_clearance_in"),
    },
    # field splice: filler plate reduction
    "6.13.6.1.4": {
        "a_f": ("derived", ("splices.flange_width_left_in",
                            "splices.flange_thickness_in"),
                "smaller-side flange area"),
        "a_p": ("derived", ("splices.flange_width_left_in",
                            "splices.splice_plate_thickness_in"),
                "splice plate area"),
    },
    # transverse stiffener proportions (ported 2026-07-17)
    "6.10.11.1.2": {
        "b_t": ("field", "transverse_stiffener.plate_width_in"),
        "t_p": ("field", "transverse_stiffener.plate_thickness_in"),
        "d_web": ("derived", ("section.label", "section.web_depth_in"),
                  "web depth"),
        "b_f": ("derived", ("section.label", "section.top_flange_width_in"),
                "widest compression flange in the field section"),
    },
    "6.10.11.1.3": {
        "moment_of_inertia": ("derived",
                              ("transverse_stiffener.plate_width_in",
                               "transverse_stiffener.plate_thickness_in",
                               "transverse_stiffener.single_sided"),
                              "I_t about the web face (single) or "
                              "mid-thickness (pair)"),
        "b_t": ("field", "transverse_stiffener.plate_width_in"),
        "t_p": ("field", "transverse_stiffener.plate_thickness_in"),
        "d_web": ("derived", ("section.label", "section.web_depth_in"),
                  "web depth"),
        "t_w": ("derived", ("section.label", "section.web_thickness_in"),
                "web thickness"),
        "d_o": ("field", "transverse_stiffener.spacing_in"),
        "f_yw": ("field", "section.fyw_ksi"),
        "f_ys": ("field", "transverse_stiffener.fy_ksi"),
    },
    # bearing stiffener proportions + effective column (ported 2026-07-17)
    "6.10.11.2.2": {
        "b_t": ("field", "bearing_stiffener.plate_width_in"),
        "t_p": ("field", "bearing_stiffener.plate_thickness_in"),
        "f_ys": ("field", "bearing_stiffener.fy_ksi"),
    },
    "6.10.11.2.4": {
        "b_t": ("field", "bearing_stiffener.plate_width_in"),
        "t_p": ("field", "bearing_stiffener.plate_thickness_in"),
        "t_w": ("derived", ("section.label", "section.web_thickness_in"),
                "web thickness"),
        "d_web": ("derived", ("section.label", "section.web_depth_in"),
                  "web depth"),
        "f_ys": ("field", "bearing_stiffener.fy_ksi"),
        "pairs": ("field", "bearing_stiffener.pairs"),
        "p_u": ("loads", "factored bearing reaction"),
    },
    # compression-flange resistance family (ported 2026-07-17)
    "6.10.8.2.1": {
        "l_b": ("derived", ("cross_frame.stations_ft",
                            "cross_frame.spacing_ft"),
                "governing unbraced length (max bay)"),
        "b_fc": ("derived", ("section.label", "section.top_flange_width_in"),
                 "compression-flange width"),
        "t_fc": ("derived", ("section.label",
                             "section.top_flange_thickness_in"),
                 "compression-flange thickness"),
        "d_c": ("derived", ("section.label", "section.web_depth_in"),
                "depth of web in compression"),
        "t_w": ("derived", ("section.label", "section.web_thickness_in"),
                "web thickness"),
        "f_yc": ("field", "section.fyc_ksi"),
        "f_yw": ("field", "section.fyw_ksi"),
    },
    "6.10.8.1.1": {
        "f_nc": ("derived", ("section.label", "section.top_flange_width_in",
                             "section.top_flange_thickness_in",
                             "cross_frame.spacing_ft"),
                 "Fnc from 6.10.8.2.1"),
        "f_bu": ("loads", "factored flange stress"),
        "f_l": ("loads", "flange lateral bending stress"),
    },
    "6.10.8.1.3": {
        "f_yf": ("field", "section.fyc_ksi"),
        "f_bu": ("loads", "factored flange stress"),
    },
    # shear connector fatigue + transverse spacing (ported 2026-07-17)
    "6.10.10.2": {
        "d_stud": ("field", "composite.stud_diameter_in"),
        "n_cycles": ("loads", "design fatigue cycles N (None = Fatigue I)"),
    },
    "6.10.10.3": {
        "d_stud": ("field", "composite.stud_diameter_in"),
        "n_per_row": ("field", "composite.studs_per_row"),
        "gauge_in": ("field", "composite.stud_gauge_in"),
        "flange_width_in": ("derived", ("section.label",
                                        "section.top_flange_width_in"),
                            "top flange width"),
    },
    # cross-frame member plate slenderness (ported 2026-07-17)
    "6.9.4.2.1": {
        "b": ("derived", ("cross_frame.member_shape",),
              "outstanding leg width from the AISC label"),
        "t": ("derived", ("cross_frame.member_shape",),
              "leg thickness from the AISC label"),
        "f_y": ("field", "cross_frame.fy_ksi"),
    },
    # splice plate shear (ported 2026-07-17)
    "6.13.5.3": {
        "a_vg": ("derived", ("splices.web_depth_in",
                             "splices.splice_plate_thickness_in"),
                 "gross shear area of the web splice plate"),
        "a_vn": ("derived", ("splices.web_depth_in",
                             "splices.splice_plate_thickness_in",
                             "splices.bolt_diameter_in",
                             "splices.bolt_rows"),
                 "net shear area through the bolt line"),
        "f_y": ("field", "splices.plate_fy_ksi"),
        "f_u": ("field", "splices.plate_fu_ksi"),
    },
    # longitudinal web stiffener proportions (now ported, Dane 2026-07-17)
    "6.10.11.3": {
        "proj_width": ("field", "longitudinal_stiffener.plate_width_in"),
        "t_s": ("field", "longitudinal_stiffener.plate_thickness_in"),
        "moment_of_inertia": ("derived",
                              ("longitudinal_stiffener.plate_width_in",
                               "longitudinal_stiffener.plate_thickness_in"),
                              "I_l of the plate about the web face"),
        "radius_of_gyration": ("derived",
                               ("longitudinal_stiffener.plate_width_in",
                                "longitudinal_stiffener.plate_thickness_in"),
                               "r = sqrt(I_l/A) of the stiffener"),
        "d_web": ("derived", ("section.label", "section.web_depth_in"),
                  "web depth"),
        "t_w": ("derived", ("section.label", "section.web_thickness_in"),
                "web thickness"),
        "d_o": ("derived", ("transverse_stiffener.spacing_in",),
                "panel spacing (uniform default if no transverse stiffener)"),
        "f_ys": ("field", "longitudinal_stiffener.fy_ksi"),
        "f_yc": ("field", "section.fyc_ksi"),
    },
    # cross-frame / diaphragm stability bracing (now ported)
    "6.7.4.2.2": {
        "m_r": ("loads", "required flexural strength Mr at the brace"),
        "l_span": ("derived", ("length_ft",), "girder span/length"),
        "n_braces": ("derived", ("cross_frame.stations_ft",
                                 "cross_frame.spacing_ft"),
                     "number of intermediate brace points"),
        "i_eff": ("derived", ("section.label", "section.top_flange_width_in",
                             "section.top_flange_thickness_in"),
                  "effective lateral moment of inertia"),
        "brace_stiffness": ("derived", ("cross_frame.member_shape",
                                        "cross_frame.member_length_ft",
                                        "cross_frame.connection_plate_thickness_in"),
                            "provided cross-frame torsional stiffness"),
    },
}


@dataclass(frozen=True)
class BridgeLayoutRecord(ElementRecord):
    """The bridge-level superstructure geometry as a storable record: the
    :class:`~civilpy.structural.bridge_layout.BridgeInput` a stored bridge
    reconstitutes to for the ``.3dm`` emit.  This is the whole-bridge frame
    (spans, girder count/spacing, overhang, skew, deck) that the per-girder-line
    :class:`SteelGirderRecord` details hang off; the batch materializer reads it,
    calls :meth:`to_bridge_input`, and runs ``girder_bridge_emit`` — so the
    served model comes from an authored Spec, not a second geometry engine
    (build plan §2.4/§8).  Every field mirrors ``BridgeInput`` one-for-one, so
    the round-trip is faithful."""

    spans_ft: tuple[float, ...] = spec_field(
        unit="ft", desc="span lengths along the centerline")
    girder_count: int = spec_field(2, ge=2)
    girder_spacing_ft: float = spec_field(8.0, unit="ft", gt=0.0)
    girder_label: str = spec_field("W36X150",
                                   desc="AISC rolled shape (current engine)")
    overhang_ft: float = spec_field(3.0, unit="ft", gt=0.0)
    railing: str = spec_field("SBR-1-20", desc="ODOT SCD railing designation")
    grade: str = spec_field("Grade 50",
                            enum=("Grade 36", "Grade 50", "Grade 50W",
                                  "Grade HPS70W"))
    skew_deg: float = spec_field(0.0, unit="deg")
    design_haunch_in: float = spec_field(2.0, unit="in", ge=0.0)
    deck_thickness_in: float | None = spec_field(
        None, unit="in", gt=0.0, desc="None = ODOT standard deck design")
    deck_fc_ksi: float = spec_field(4.5, unit="ksi", gt=0.0)
    cross_slope_pct: float = spec_field(2.0, desc="deck cross slope, percent")
    crown_offset_ft: float | None = spec_field(
        None, unit="ft", desc="crown transverse offset; None = centered")
    composite: bool = spec_field(True)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "bridge"
    SUBTYPE = "layout"

    def __post_init__(self):
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def _cross_validate(self):
        problems = []
        if not self.spans_ft:
            problems.append("spans_ft: at least one span required")
        elif not all(isinstance(s, (int, float)) and not isinstance(s, bool)
                     and s > 0 for s in self.spans_ft):
            problems.append("spans_ft: entries must be positive numbers")
        return problems

    def to_bridge_input(self):
        """Reconstitute the :class:`~civilpy.structural.bridge_layout
        .BridgeInput` the superstructure emit consumes."""
        from civilpy.structural.bridge_layout import BridgeInput

        return BridgeInput(
            spans_ft=tuple(self.spans_ft), girder_count=self.girder_count,
            girder_spacing_ft=self.girder_spacing_ft,
            girder_label=self.girder_label, overhang_ft=self.overhang_ft,
            railing=self.railing, grade=self.grade, skew_deg=self.skew_deg,
            design_haunch_in=self.design_haunch_in,
            deck_thickness_in=self.deck_thickness_in,
            deck_fc_ksi=self.deck_fc_ksi, cross_slope_pct=self.cross_slope_pct,
            crown_offset_ft=self.crown_offset_ft, composite=self.composite)


# ══ Tier A parametric records: standard slab + adjacent box beam ════════════
#
# The project-object phase's Tier A campaign (project_object_schema.md P4)
# populates the ODOT-maintained standard-drawing bridges straight from SNBI +
# the era registry — the standard sheets ARE the design, so a handful of
# parameters regenerates geometry *including reinforcement* (LOD 400
# as-designed).  Each record mirrors its emit engine's input one-for-one
# (the BridgeLayoutRecord pattern) and validates against the cataloged
# design-table envelope, so a record that stores is a record that emits.


@dataclass(frozen=True)
class SlabBridgeRecord(ElementRecord):
    """One single-span ODOT standard slab bridge (SB-1-24 series): the
    :class:`~civilpy.structural.odot.slab_bridge.SlabBridgeInput` as a
    storable record.  The slab thickness and the full A/B/M/N bar
    schedule come from the standard's design table at emit time — they
    are the *standard's* content, so they are never stored here (design
    rule: never copy what the era registry derives)."""

    span_ft: int = spec_field(unit="ft", gt=0, desc="single span, c/c "
                              "bearings — a design-table key")
    width_ft: float = spec_field(unit="ft", gt=0.0,
                                 desc="out-to-out slab width")
    skew_deg: float = spec_field(0.0, unit="deg",
                                 desc="SB-1-24 caps skew at 25 deg")
    edge_condition: str = spec_field(
        "over_the_side", enum=("over_the_side", "parapet"),
        desc="edge-beam schedule option on the sheet")
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "bridge"
    SUBTYPE = "slab"

    def __post_init__(self):
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def _cross_validate(self):
        from civilpy.structural.odot.slab_bridge import (SKEW_MAX_DEG,
                                                         SLAB_DESIGNS)
        problems = []
        if self.span_ft not in SLAB_DESIGNS:
            lo, hi = min(SLAB_DESIGNS), max(SLAB_DESIGNS)
            problems.append(f"span_ft: {self.span_ft} outside the SB-1-24 "
                            f"design table ({lo}-{hi} ft, integer)")
        if abs(self.skew_deg) > SKEW_MAX_DEG:
            problems.append(f"skew_deg: {self.skew_deg} exceeds the sheet "
                            f"maximum {SKEW_MAX_DEG}")
        return problems

    def to_input(self):
        """The :class:`~civilpy.structural.odot.slab_bridge
        .SlabBridgeInput` the emit engine consumes."""
        from civilpy.structural.odot.slab_bridge import SlabBridgeInput

        return SlabBridgeInput(span_ft=self.span_ft,
                               width_ft=self.width_ft,
                               skew_deg=self.skew_deg,
                               edge_condition=self.edge_condition)


def select_box(span_ft: float, *, composite: bool = True) -> str | None:
    """The shallowest PSBDD-1-25 box designation whose cataloged span
    range covers ``span_ft`` (48-in widths; the standard's selection
    logic), or None when no box reaches — spans are cataloged in 5-ft
    steps, so the lookup rounds up to the next step."""
    import math

    from civilpy.structural.odot.box_beam_design import (BOX_DESIGNATIONS,
                                                         designs_for_box)
    span = 5 * math.ceil(span_ft / 5.0)
    want = (lambda b: b.startswith("CB")) if composite \
        else (lambda b: not b.startswith("CB"))
    for box in BOX_DESIGNATIONS:            # shallow -> deep per family
        if not want(box):
            continue
        if any(d.span == span for d in designs_for_box(box)):
            return box
    return None


@dataclass(frozen=True)
class BoxBeamBridgeRecord(ElementRecord):
    """One adjacent prestressed box-beam bridge on the ODOT standard
    designs (PSBDD-1-25 tables): the :class:`~civilpy.structural
    .rhino_box_bim.BoxBridgeInput` as a storable record.  The strand
    pattern and section come from the design table for ``(box,
    span_ft)`` at emit time."""

    box: str = spec_field(desc="PSBDD-1-25 designation, e.g. CB27-48")
    span_ft: float = spec_field(unit="ft", gt=0.0,
                                desc="one of the box's cataloged spans")
    n_beams: int = spec_field(ge=2)
    skew_deg: float = spec_field(0.0, unit="deg")
    fc_psi: float = spec_field(6000.0, unit="psi", gt=0.0)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "bridge"
    SUBTYPE = "box_beam"

    def __post_init__(self):
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    def _cross_validate(self):
        from civilpy.structural.odot import BOX_MAX_SKEW_DEG
        from civilpy.structural.odot.box_beam_design import (
            BOX_DESIGNATIONS, designs_for_box)
        if self.box not in BOX_DESIGNATIONS:
            return [f"box: {self.box!r} not a PSBDD-1-25 designation"]
        problems = []
        spans = sorted(d.span for d in designs_for_box(self.box))
        if self.span_ft not in spans:
            problems.append(f"span_ft: {self.span_ft} not cataloged for "
                            f"{self.box} (spans {spans[0]}-{spans[-1]} in "
                            f"5-ft steps)")
        if abs(self.skew_deg) > BOX_MAX_SKEW_DEG:
            problems.append(f"skew_deg: {self.skew_deg} exceeds the "
                            f"PSBD-1-25 limit of {BOX_MAX_SKEW_DEG:g} deg")
        return problems

    def to_input(self):
        """The :class:`~civilpy.structural.rhino_box_bim.BoxBridgeInput`
        the emit engine consumes."""
        from civilpy.structural.rhino_box_bim import BoxBridgeInput

        return BoxBridgeInput(box=self.box, span_ft=self.span_ft,
                              n_beams=self.n_beams,
                              skew_deg=self.skew_deg, fc_psi=self.fc_psi)


# ══ As-rated prestressed concrete beams: strands, mild steel, stirrups ═══════
#
# The Tier A records above regenerate reinforcement from a *standard* design
# table.  These records store the reinforcement a rating engineer actually
# entered for one beam — the per-strand layout with debonding and harping,
# the mild-steel rows, the stirrup ranges, the composite deck ranges — so a
# rated bridge round-trips to a full-detail model and, later, to a QA pass
# that compares what was entered with what the standard for that beam says.
# Shape follows the source it will most often be filled from (a load-rating
# model: a strand *grid* on the section, then the *positions used* per span),
# but nothing here names that source.
#
# Units: section-scale in inches, along-member in feet, strengths in ksi.

STRAND_CONFIGURATIONS = ("straight", "debonded", "harped", "harped_debonded",
                         "p_and_e")
STRAND_TYPES = ("low_relaxation", "stress_relieved")
CONDITION_FACTORS = ("good", "fair", "poor")
VOID_TYPES = ("none", "circular", "rectangular")


@dataclass(frozen=True)
class StrandRowRecord(SpecRecord):
    """One row of the strand grid on the section: ``positions`` equally
    spaced slots at ``height_in`` above the soffit, centred on the beam.
    Which slots carry a strand is the per-span :class:`StrandRecord` list."""

    height_in: float = spec_field(unit="in", ge=0.0)
    positions: int = spec_field(ge=1)
    spacing_in: float | None = spec_field(None, unit="in", gt=0.0)

    def x_in(self, column: int) -> float | None:
        """Transverse offset of grid ``column`` (1-based) from the beam
        centreline, +right; ``None`` when the row has no spacing."""
        if self.spacing_in is None:
            return None
        return (column - (self.positions + 1) / 2.0) * self.spacing_in


@dataclass(frozen=True)
class StrandRecord(SpecRecord):
    """One strand in one span: its grid slot plus any debonding (length
    from each beam end over which the strand is sleeved) and harping (the
    hold-down points and the slot the strand rises to at each end)."""

    row: int = spec_field(ge=1, desc="1-based index into the pattern rows")
    column: int = spec_field(ge=1)
    debond_left_ft: float | None = spec_field(None, unit="ft", ge=0.0)
    debond_right_ft: float | None = spec_field(None, unit="ft", ge=0.0)
    harp_left_ft: float | None = spec_field(
        None, unit="ft", ge=0.0, desc="hold-down point from the left end")
    harp_right_ft: float | None = spec_field(
        None, unit="ft", ge=0.0, desc="hold-down point from the right end")
    harp_end_left_row: int | None = spec_field(
        None, ge=1, desc="grid row the strand occupies at the left end")
    harp_end_right_row: int | None = spec_field(None, ge=1)
    extends_left: bool = spec_field(False, desc="continuity strand into "
                                    "the adjacent span / diaphragm")
    extends_right: bool = spec_field(False)

    @property
    def debonded(self) -> bool:
        return bool(self.debond_left_ft or self.debond_right_ft)

    @property
    def harped(self) -> bool:
        return self.harp_left_ft is not None or self.harp_right_ft is not None


@dataclass(frozen=True)
class StrandPatternRecord(SpecRecord):
    """The prestressing of one span: material, grid rows, and the strands
    placed in them.  ``configuration == "p_and_e"`` means the author gave a
    force and eccentricities instead of a layout — ``strands`` is then
    empty and ``p_kips`` / ``cg_*`` carry what is known.  A full-detail
    model needs a layout; the P-and-e case is stored so it can be found."""

    configuration: str = spec_field("straight", enum=STRAND_CONFIGURATIONS)
    strand_diameter_in: float = spec_field(0.5, unit="in", gt=0.0)
    strand_area_in2: float = spec_field(0.153, unit="in^2", gt=0.0)
    fpu_ksi: float = spec_field(270.0, unit="ksi", gt=0.0)
    fpy_ksi: float | None = spec_field(None, unit="ksi", gt=0.0)
    strand_type: str = spec_field("low_relaxation", enum=STRAND_TYPES)
    jacking_ratio: float | None = spec_field(
        None, gt=0.0, desc="jacking stress / fpu")
    rows: tuple[StrandRowRecord, ...] = spec_field(())
    strands: tuple[StrandRecord, ...] = spec_field(())
    p_kips: float | None = spec_field(None, unit="kip", ge=0.0,
                                      desc="P-and-e only: effective force")
    cg_mid_in: float | None = spec_field(
        None, unit="in", ge=0.0, desc="P-and-e only: strand cg above "
                                      "soffit at midspan")
    cg_end_in: float | None = spec_field(None, unit="in", ge=0.0)

    # ── derived ────────────────────────────────────────────────────────
    @property
    def n_strands(self) -> int:
        return len(self.strands)

    @property
    def n_debonded(self) -> int:
        return sum(1 for s in self.strands if s.debonded)

    @property
    def n_harped(self) -> int:
        return sum(1 for s in self.strands if s.harped)

    @property
    def total_area_in2(self) -> float:
        return self.n_strands * self.strand_area_in2

    def cg_height_in(self) -> float | None:
        """Strand-group centroid above the soffit at midspan (harped
        strands at their midspan row), ``None`` without a layout."""
        if not self.strands:
            return self.cg_mid_in
        return sum(self.rows[s.row - 1].height_in for s in self.strands) \
            / len(self.strands)

    def row_counts(self) -> tuple[int, ...]:
        """Strands per grid row, in row order."""
        counts = [0] * len(self.rows)
        for s in self.strands:
            counts[s.row - 1] += 1
        return tuple(counts)

    def _cross_validate(self):
        problems = []
        for i, r in enumerate(self.rows):
            problems += [f"rows[{i}].{p}" for p in r.validate()]
        seen = set()
        for i, s in enumerate(self.strands):
            problems += [f"strands[{i}].{p}" for p in s.validate()]
            if s.row > len(self.rows):
                problems.append(f"strands[{i}].row {s.row} beyond "
                                f"{len(self.rows)} rows")
            elif s.column > self.rows[s.row - 1].positions:
                problems.append(f"strands[{i}].column {s.column} beyond "
                                f"row {s.row}'s {self.rows[s.row-1].positions}"
                                f" positions")
            for end in ("left", "right"):
                r_end = getattr(s, f"harp_end_{end}_row")
                if r_end is not None and r_end > len(self.rows):
                    problems.append(f"strands[{i}].harp_end_{end}_row "
                                    f"{r_end} beyond {len(self.rows)} rows")
            if (s.row, s.column) in seen:
                problems.append(f"strands[{i}]: slot ({s.row}, {s.column}) "
                                f"used twice")
            seen.add((s.row, s.column))
        if self.configuration == "p_and_e":
            if self.strands:
                problems.append("configuration p_and_e cannot carry a "
                                "strand layout")
            if self.p_kips is None:
                problems.append("configuration p_and_e needs p_kips")
        elif not self.strands:
            problems.append(f"configuration {self.configuration} needs at "
                            f"least one strand")
        return problems


@dataclass(frozen=True)
class MildBarRowRecord(SpecRecord):
    """A row of longitudinal mild bars in a prestressed beam: ``count``
    bars of ``bar`` at ``height_in`` above the soffit, running
    ``length_ft`` from ``start_ft`` (measured along the member from its
    start, so a bar in span 2 starts past span 1).  ``role`` separates the
    beam's own bars from continuity bars over a support."""

    bar: str = spec_field(desc="US bar size as '#5', or legacy '0.5 sq'")
    count: int = spec_field(ge=1)
    height_in: float = spec_field(unit="in", ge=0.0)
    start_ft: float = spec_field(unit="ft")
    length_ft: float = spec_field(unit="ft", gt=0.0)
    spacing_in: float | None = spec_field(None, unit="in", gt=0.0)
    side_cover_in: float | None = spec_field(None, unit="in", ge=0.0)
    fy_ksi: float = spec_field(60.0, unit="ksi", gt=0.0)
    role: str = spec_field("longitudinal",
                           enum=("longitudinal", "continuity"))
    developed_start: bool = spec_field(False)
    developed_end: bool = spec_field(False)


@dataclass(frozen=True)
class ContinuityBarRecord(SpecRecord):
    """Continuity reinforcement over a support of a beam made continuous
    for live load: ``count`` bars of ``bar`` at ``height_in`` above the
    soffit, anchored at the support ``support_ft`` along the member."""

    support_ft: float = spec_field(unit="ft")
    bar: str = spec_field()
    count: int = spec_field(ge=1)
    height_in: float = spec_field(unit="in", ge=0.0)
    fy_ksi: float = spec_field(60.0, unit="ksi", gt=0.0)


@dataclass(frozen=True)
class StirrupRangeRecord(SpecRecord):
    """A run of vertical shear reinforcement: ``n_spaces`` spaces of
    ``spacing_in`` starting ``start_ft`` along the member."""

    start_ft: float = spec_field(unit="ft")
    spacing_in: float = spec_field(unit="in", gt=0.0)
    n_spaces: int = spec_field(ge=1)
    bar: str = spec_field("#4")
    legs: int = spec_field(2, ge=1)
    angle_deg: float = spec_field(90.0, unit="deg", gt=0.0)
    fy_ksi: float = spec_field(60.0, unit="ksi", gt=0.0)
    extends_into_deck: bool = spec_field(
        False, desc="stirrups project into the deck (horizontal shear)")

    @property
    def length_ft(self) -> float:
        return self.n_spaces * self.spacing_in / 12.0

    @property
    def end_ft(self) -> float:
        return self.start_ft + self.length_ft


@dataclass(frozen=True)
class CompositeRangeRecord(SpecRecord):
    """Whether the deck acts compositely with the beam over
    ``[start_ft, start_ft + length_ft]``."""

    start_ft: float = spec_field(unit="ft")
    length_ft: float = spec_field(unit="ft", gt=0.0)
    composite: bool = spec_field(True)


@dataclass(frozen=True)
class DeckRangeRecord(SpecRecord):
    """The deck slab over a beam along ``[start_ft, start_ft + length_ft]``:
    thickness (actual, and the effective/structural value used in
    analysis) and the tributary width."""

    start_ft: float = spec_field(unit="ft")
    length_ft: float = spec_field(unit="ft", gt=0.0)
    thickness_in: float = spec_field(unit="in", gt=0.0)
    effective_thickness_in: float | None = spec_field(None, unit="in", gt=0.0)
    tributary_width_in: float | None = spec_field(None, unit="in", gt=0.0)
    fc_ksi: float | None = spec_field(None, unit="ksi", gt=0.0)


@dataclass(frozen=True)
class DiaphragmRangeRecord(SpecRecord):
    """Interior diaphragms: ``n_spaces`` at ``spacing_ft`` from ``start_ft``,
    each ``thickness_in`` thick."""

    start_ft: float = spec_field(unit="ft")
    spacing_ft: float = spec_field(unit="ft", gt=0.0)
    n_spaces: int = spec_field(ge=1)
    thickness_in: float | None = spec_field(None, unit="in", gt=0.0)


@dataclass(frozen=True)
class PsBoxSectionRecord(SpecRecord):
    """A prestressed box section as dimensioned: outer envelope, walls and
    slabs, corner haunches, shear key, voids.  ``name`` is the shape label
    as authored (``OH-CB21-48``); the standard-design lookup keys on it."""

    name: str = spec_field()
    depth_in: float = spec_field(unit="in", gt=0.0)
    top_width_in: float = spec_field(unit="in", gt=0.0)
    bot_width_in: float = spec_field(unit="in", gt=0.0)
    wall_in: float | None = spec_field(None, unit="in", gt=0.0)
    top_slab_in: float | None = spec_field(None, unit="in", gt=0.0)
    bot_slab_in: float | None = spec_field(None, unit="in", gt=0.0)
    top_haunch_in: float | None = spec_field(None, unit="in", ge=0.0)
    bot_haunch_in: float | None = spec_field(None, unit="in", ge=0.0)
    shear_key_height_in: float | None = spec_field(None, unit="in", ge=0.0)
    shear_key_depth_in: float | None = spec_field(None, unit="in", ge=0.0)
    void_type: str = spec_field("rectangular", enum=VOID_TYPES)
    n_voids: int | None = spec_field(None, ge=0)
    void_diameter_in: float | None = spec_field(None, unit="in", gt=0.0)
    area_in2: float | None = spec_field(None, unit="in^2", gt=0.0)
    y_cg_in: float | None = spec_field(None, unit="in", gt=0.0,
                                       desc="centroid above the soffit")
    ixx_in4: float | None = spec_field(None, unit="in^4", gt=0.0)

    def _cross_validate(self):
        problems = []
        # equality is a solid section (the 12 in "boxes" are solid slabs)
        if self.wall_in is not None and 2 * self.wall_in > self.bot_width_in + 1e-6:
            problems.append("wall_in: two walls exceed the beam width")
        if self.top_slab_in is not None and self.bot_slab_in is not None \
                and self.top_slab_in + self.bot_slab_in > self.depth_in + 1e-6:
            problems.append("top_slab_in + bot_slab_in exceed depth_in")
        if self.y_cg_in is not None and self.y_cg_in >= self.depth_in:
            problems.append("y_cg_in must be inside the section depth")
        return problems


@dataclass(frozen=True)
class PsBeamSpanRecord(SpecRecord):
    """One span of a prestressed beam line: its length, the section it
    uses (index into the beam's ``sections``), the strand pattern, mild
    steel and materials.  ``overhang_*_ft`` is the beam projection past the
    bearing at each end."""

    length_ft: float = spec_field(unit="ft", gt=0.0)
    strands: StrandPatternRecord = spec_field()
    section: int = spec_field(0, ge=0, desc="index into sections")
    mild_steel: tuple[MildBarRowRecord, ...] = spec_field(())
    fc_ksi: float | None = spec_field(None, unit="ksi", gt=0.0)
    fci_ksi: float | None = spec_field(None, unit="ksi", gt=0.0)
    overhang_left_ft: float | None = spec_field(None, unit="ft", ge=0.0)
    overhang_right_ft: float | None = spec_field(None, unit="ft", ge=0.0)

    def _cross_validate(self):
        problems = [f"mild_steel[{i}].{p}"
                    for i, m in enumerate(self.mild_steel)
                    for p in m.validate()]
        half = self.length_ft / 2.0
        for i, s in enumerate(self.strands.strands):
            for side in ("left", "right"):
                d = getattr(s, f"debond_{side}_ft")
                if d is not None and d > half:
                    problems.append(f"strands.strands[{i}].debond_{side}_ft "
                                    f"{d} exceeds half the span")
                h = getattr(s, f"harp_{side}_ft")
                if h is not None and h > self.length_ft:
                    problems.append(f"strands.strands[{i}].harp_{side}_ft "
                                    f"{h} is past the span end")
        return problems


@dataclass(frozen=True)
class PrestressedBoxBeamRecord(ElementRecord):
    """One prestressed box-beam line, as rated: sections, spans with their
    strands and mild steel, stirrup ranges, composite and deck ranges,
    interior diaphragms, and the condition the rater assigned.  Stations
    (``start_ft``) run along the member from its start through every span,
    the way the source model lays them out."""

    name: str = spec_field(desc="member name as authored")
    sections: tuple[PsBoxSectionRecord, ...] = spec_field()
    spans: tuple[PsBeamSpanRecord, ...] = spec_field()
    stirrups: tuple[StirrupRangeRecord, ...] = spec_field(())
    composite_ranges: tuple[CompositeRangeRecord, ...] = spec_field(())
    deck: tuple[DeckRangeRecord, ...] = spec_field(())
    diaphragms: tuple[DiaphragmRangeRecord, ...] = spec_field(())
    continuity_bars: tuple[ContinuityBarRecord, ...] = spec_field(())
    condition_factor: str | None = spec_field(None, enum=CONDITION_FACTORS)
    rebar_fy_ksi: float | None = spec_field(None, unit="ksi", gt=0.0)
    standard: str | None = spec_field(None, desc="ODOT standard drawing id")
    standard_year: int | None = spec_field(None, ge=1900)
    provenance: Provenance | None = spec_field(None)

    BIM_TYPE = "girder"
    SUBTYPE = "ps_box"

    def __post_init__(self):
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance())

    @property
    def length_ft(self) -> float:
        return sum(s.length_ft for s in self.spans)

    @property
    def composite(self) -> bool | None:
        """``True`` when any range is composite, ``False`` when ranges exist
        and none is, ``None`` when the model says nothing."""
        if not self.composite_ranges:
            return None
        return any(r.composite for r in self.composite_ranges)

    def _cross_validate(self):
        problems = []
        if not self.sections:
            problems.append("sections: at least one required")
        if not self.spans:
            problems.append("spans: at least one required")
        for i, sec in enumerate(self.sections):
            problems += [f"sections[{i}].{p}" for p in sec.validate()]
        for i, sp in enumerate(self.spans):
            problems += [f"spans[{i}].{p}" for p in sp.validate()]
            if sp.section >= len(self.sections):
                problems.append(f"spans[{i}].section {sp.section} beyond "
                                f"{len(self.sections)} sections")
            else:
                depth = self.sections[sp.section].depth_in
                for j, row in enumerate(sp.strands.rows):
                    if row.height_in >= depth:
                        problems.append(
                            f"spans[{i}].strands.rows[{j}].height_in "
                            f"{row.height_in} is above the {depth} in "
                            f"section")
        for attr in ("stirrups", "composite_ranges", "deck", "diaphragms",
                     "continuity_bars"):
            for i, r in enumerate(getattr(self, attr)):
                problems += [f"{attr}[{i}].{p}" for p in r.validate()]
        return problems
