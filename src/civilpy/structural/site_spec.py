#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Schema records for a bridge's site: coordinate system, alignment, profile,
terrain, and the link placing a bridge on them.

Step 1 of the procedural build (alignment + terrain come before support
lines, decks, girders ...).  Same conventions as
:mod:`civilpy.structural.bim_spec`: frozen dataclasses, units in the field
name and ``spec_field`` metadata, ``validate()`` as the type guarantor, and
``to_dict``/``from_dict`` for the JSONB store.

* :class:`CoordinateSystemRecord` - OCCS county zone or Ohio State Plane
  (resolved by :mod:`civilpy.state.ohio.coordinates`), datums, units.
* :class:`AlignmentRecord` - horizontal elements (line / arc / clothoid
  spiral), station equations, profile, superelevation table; converts to and
  from :class:`civilpy.transportation.alignment.Alignment`.
* :class:`TerrainRecord` - a *pointer* to a surface (source, vintage,
  resolution, extent, file hash), never the surface itself.
* :class:`BridgeSiteRecord` - one bridge on an alignment between two
  stations, with the terrain it sits on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from civilpy.structural.bim_spec import ElementRecord, Provenance, SpecRecord, spec_field

COORDINATE_KINDS = ("OCCS", "STATE_PLANE", "LOCAL", "NONE")
LINEAR_UNITS = ("us_ft", "m")
ELEMENT_KINDS = ("line", "arc", "spiral")
DIRECTIONS = ("R", "L")
ALIGNMENT_ROLES = ("design", "existing", "stationing")
TERRAIN_SOURCES = ("ogrip_3dep_las", "odnr_dem", "usgs_3dep", "landxml", "ord", "survey", "other")


# ── coordinate system ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class CoordinateSystemRecord(SpecRecord):
    """Horizontal/vertical reference of the site coordinates.

    ``code`` is an OCCS zone (``"OCCS-HAM"`` or the county abbreviation) or an
    ODOT State Plane seed name (``"OH83-2011-SF"``); ``LOCAL`` is a project
    ground system described by ``combined_scale_factor``.  OCCS is ODOT's
    preferred projection (L&D Vol. 4 Section 2101)."""

    kind: str = spec_field("OCCS", enum=COORDINATE_KINDS)
    code: str | None = spec_field(None, desc="OCCS-<county> or OH83[-2011]-NF/SF")
    horizontal_datum: str = spec_field("NAD83(2011)")
    vertical_datum: str = spec_field("NAVD88")
    geoid: str | None = spec_field("GEOID18")
    linear_unit: str = spec_field("us_ft", enum=LINEAR_UNITS)
    combined_scale_factor: float | None = spec_field(
        None, gt=0.0, desc="grid-to-ground factor for LOCAL/ground systems")

    def _cross_validate(self) -> list[str]:
        out = []
        if self.kind in ("OCCS", "STATE_PLANE"):
            if not self.code:
                out.append(f"code: required for kind {self.kind}")
            else:
                from civilpy.state.ohio import coordinates as oc

                try:
                    oc._crs_text(self.code)
                except KeyError:
                    out.append(f"code: {self.code!r} is not an OCCS zone or ODOT State Plane system")
                is_sp = self.code.upper() in oc.STATE_PLANE_EPSG
                if (self.kind == "STATE_PLANE") != is_sp:
                    out.append(f"code: {self.code!r} does not match kind {self.kind}")
        if self.kind == "LOCAL" and self.combined_scale_factor is None:
            out.append("combined_scale_factor: required for a LOCAL (ground) system")
        return out


# ── alignment ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HorizontalElementRecord(SpecRecord):
    """One horizontal element.  ``radius_*`` of ``None`` means infinite
    (a spiral's tangent end)."""

    kind: str = spec_field(enum=ELEMENT_KINDS)
    length_ft: float = spec_field(unit="ft", gt=0.0)
    direction: str | None = spec_field(None, enum=DIRECTIONS, desc="turn looking up-station")
    radius_ft: float | None = spec_field(None, unit="ft", gt=0.0, desc="arc radius")
    radius_start_ft: float | None = spec_field(None, unit="ft", gt=0.0, desc="spiral; None = infinite")
    radius_end_ft: float | None = spec_field(None, unit="ft", gt=0.0, desc="spiral; None = infinite")

    def _cross_validate(self) -> list[str]:
        out = []
        if self.kind in ("arc", "spiral") and self.direction is None:
            out.append(f"direction: required for {self.kind}")
        if self.kind == "arc" and self.radius_ft is None:
            out.append("radius_ft: required for arc")
        if self.kind == "spiral" and self.radius_start_ft is None and self.radius_end_ft is None:
            out.append("spiral: at least one of radius_start_ft / radius_end_ft must be finite")
        return out


@dataclass(frozen=True)
class StationEquationRecord(SpecRecord):
    back_ft: float = spec_field(unit="ft", desc="displayed station arriving")
    ahead_ft: float = spec_field(unit="ft", desc="displayed station leaving")


@dataclass(frozen=True)
class CrossSlopeRecord(SpecRecord):
    """Superelevation table row (positive = rising away from the centerline)."""

    station_ft: float = spec_field(unit="ft")
    left_pct: float = spec_field(unit="%")
    right_pct: float = spec_field(unit="%")


@dataclass(frozen=True)
class PVIRecord(SpecRecord):
    station_ft: float = spec_field(unit="ft")
    elevation_ft: float = spec_field(unit="ft")
    curve_length_ft: float = spec_field(0.0, unit="ft", ge=0.0, desc="parabola length (both halves); 0 = none")
    curve_length_in_ft: float = spec_field(0.0, unit="ft", ge=0.0,
                                           desc="unsymmetrical parabola: BVC to PVI; 0 = symmetric")
    curve_length_out_ft: float = spec_field(0.0, unit="ft", ge=0.0,
                                            desc="unsymmetrical parabola: PVI to EVC; 0 = symmetric")

    def as_pvi(self) -> tuple[float, ...]:
        """The tuple :class:`~civilpy.transportation.alignment.VerticalProfile` takes."""
        if self.curve_length_in_ft > 0.0 or self.curve_length_out_ft > 0.0:
            return (self.station_ft, self.elevation_ft, self.curve_length_in_ft, self.curve_length_out_ft)
        return (self.station_ft, self.elevation_ft, self.curve_length_ft)

    @classmethod
    def from_pvi(cls, station_ft: float, elevation_ft: float, len_in_ft: float, len_out_ft: float) -> "PVIRecord":
        if abs(len_in_ft - len_out_ft) > 1e-9:
            return cls(station_ft, elevation_ft, len_in_ft + len_out_ft, len_in_ft, len_out_ft)
        return cls(station_ft, elevation_ft, len_in_ft + len_out_ft)


@dataclass(frozen=True)
class ProfileRecord(SpecRecord):
    name: str | None = spec_field(None)
    pvis: tuple[PVIRecord, ...] = spec_field(())

    def _cross_validate(self) -> list[str]:
        out = []
        if len(self.pvis) < 2:
            out.append("pvis: a profile needs at least two PVIs")
        stations = [p.station_ft for p in self.pvis]
        if any(b <= a for a, b in zip(stations, stations[1:])):
            out.append("pvis: stations must strictly increase")
        return out


def _element_to_record(el) -> HorizontalElementRecord:
    from civilpy.transportation.alignment import Curve, Spiral, Tangent

    if isinstance(el, Tangent):
        return HorizontalElementRecord("line", float(el.length))
    if isinstance(el, Curve):
        return HorizontalElementRecord("arc", float(el.length), el.direction, float(el.radius_ft))
    if isinstance(el, Spiral):
        def fin(r):
            return None if math.isinf(r) else float(r)
        return HorizontalElementRecord("spiral", float(el.length), el.direction, None,
                                       fin(el.radius_start_ft), fin(el.radius_end_ft))
    raise TypeError(f"unknown alignment element {el!r}")


def _record_to_element(r: HorizontalElementRecord):
    from civilpy.transportation.alignment import Curve, Spiral, Tangent

    if r.kind == "line":
        return Tangent(r.length_ft)
    if r.kind == "arc":
        return Curve(r.radius_ft, math.degrees(r.length_ft / r.radius_ft), r.direction)
    return Spiral(r.length_ft,
                  math.inf if r.radius_start_ft is None else r.radius_start_ft,
                  math.inf if r.radius_end_ft is None else r.radius_end_ft,
                  r.direction)


@dataclass(frozen=True)
class AlignmentRecord(ElementRecord):
    """A horizontal alignment (with its profile and cross slopes) in site
    coordinates.  ``source_ref`` says exactly where it came from, e.g. a
    LandXML file hash or ``"TIMS Road_Inventory NLF_ID=SHAMIR00075**C"``."""

    BIM_TYPE = "site"
    SUBTYPE = "alignment"

    name: str = spec_field()
    start_easting_ft: float = spec_field(unit="ft")
    start_northing_ft: float = spec_field(unit="ft")
    start_bearing_deg: float = spec_field(unit="deg", desc="azimuth, clockwise from grid north")
    elements: tuple[HorizontalElementRecord, ...] = spec_field(())
    start_station_ft: float = spec_field(0.0, unit="ft")
    role: str = spec_field("design", enum=ALIGNMENT_ROLES)
    coordinate_system: CoordinateSystemRecord = spec_field(CoordinateSystemRecord("NONE"))
    station_equations: tuple[StationEquationRecord, ...] = spec_field(())
    profile: ProfileRecord | None = spec_field(None)
    superelevation: tuple[CrossSlopeRecord, ...] = spec_field(())
    source_ref: str | None = spec_field(None)
    provenance: Provenance = spec_field(Provenance())

    def _cross_validate(self) -> list[str]:
        return [] if self.elements else ["elements: an alignment needs at least one element"]

    def to_alignment(self):
        """The geometric :class:`~civilpy.transportation.alignment.Alignment`."""
        from civilpy.transportation.alignment import Alignment, VerticalProfile

        profile = None
        if self.profile is not None:
            profile = VerticalProfile([p.as_pvi() for p in self.profile.pvis])
        return Alignment((self.start_easting_ft, self.start_northing_ft), self.start_bearing_deg,
                         [_record_to_element(e) for e in self.elements], profile=profile,
                         start_station_ft=self.start_station_ft,
                         station_equations=[(q.back_ft, q.ahead_ft) for q in self.station_equations],
                         superelevation=[(c.station_ft, c.left_pct, c.right_pct) for c in self.superelevation])

    @classmethod
    def from_alignment(cls, alignment, name: str, **kwargs) -> "AlignmentRecord":
        """Record for an :class:`Alignment`; extra fields (``role``,
        ``coordinate_system``, ``source_ref``, ``provenance``) via kwargs."""
        profile = None
        if alignment.profile is not None:
            profile = ProfileRecord(pvis=tuple(PVIRecord.from_pvi(s, e, l_in, l_out)
                                               for (s, e, _), (l_in, l_out)
                                               in zip(alignment.profile.pvis, alignment.profile.pvi_lengths)))
        return cls(name=name,
                   start_easting_ft=alignment.start_point[0],
                   start_northing_ft=alignment.start_point[1],
                   start_bearing_deg=alignment.start_bearing,
                   elements=tuple(_element_to_record(e) for e in alignment.elements),
                   start_station_ft=alignment.start_station,
                   station_equations=tuple(StationEquationRecord(b, a) for b, a in alignment.station_equations),
                   profile=profile,
                   superelevation=tuple(CrossSlopeRecord(*row) for row in alignment.superelevation),
                   **kwargs)


# ── terrain ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TerrainRecord(ElementRecord):
    """Where a ground surface came from - a pointer, not the surface."""

    BIM_TYPE = "site"
    SUBTYPE = "terrain"

    name: str = spec_field()
    source: str = spec_field(enum=TERRAIN_SOURCES)
    vintage_year: int | None = spec_field(None, ge=1900, desc="acquisition year of the elevation data")
    resolution_ft: float | None = spec_field(None, unit="ft", gt=0.0)
    extent_ft: tuple[float, ...] = spec_field((), unit="ft", desc="(min E, min N, max E, max N)")
    coordinate_system: CoordinateSystemRecord = spec_field(CoordinateSystemRecord("NONE"))
    uri: str | None = spec_field(None, desc="service URL, tile ids or file path")
    file_sha256: str | None = spec_field(None)
    provenance: Provenance = spec_field(Provenance())

    def _cross_validate(self) -> list[str]:
        out = []
        if self.extent_ft:
            if len(self.extent_ft) != 4:
                out.append("extent_ft: expected (min E, min N, max E, max N)")
            elif not (self.extent_ft[0] < self.extent_ft[2] and self.extent_ft[1] < self.extent_ft[3]):
                out.append("extent_ft: min must be below max")
        return out


# ── the bridge on its site ────────────────────────────────────────────────

@dataclass(frozen=True)
class BridgeSiteRecord(ElementRecord):
    """One bridge placed on an alignment between two continuous stations,
    over a terrain.  Support lines, decks, girders ... (later steps) are
    located by station/offset along ``alignment``."""

    BIM_TYPE = "bridge"
    SUBTYPE = "site"

    alignment: AlignmentRecord = spec_field()
    begin_station_ft: float = spec_field(unit="ft", desc="continuous station")
    end_station_ft: float = spec_field(unit="ft", desc="continuous station")
    terrain: TerrainRecord | None = spec_field(None)
    provenance: Provenance = spec_field(Provenance())

    def _cross_validate(self) -> list[str]:
        out = []
        if self.end_station_ft <= self.begin_station_ft:
            out.append("end_station_ft: must be greater than begin_station_ft")
        try:
            al = self.alignment.to_alignment()
        except Exception as exc:  # reported by the nested validation too
            return out + [f"alignment: {exc}"]
        tol = 1e-6
        if self.begin_station_ft < al.start_station - tol or self.end_station_ft > al.end_station + tol:
            out.append("begin/end stations: outside the alignment")
        return out


# ── structure type study: alternatives on a site ─────────────────────────

SUPPORT_KINDS = ("abutment", "pier")
ABUTMENT_UNIT_TYPES = ("seat", "semi_integral", "integral")
PIER_UNIT_TYPES = ("cap_and_column", "hammerhead", "pile_bent", "wall")


@dataclass(frozen=True)
class SupportLineRecord(SpecRecord):
    """A support line of a bridge alternative: where (continuous station on
    the site alignment), how (skew, degrees, positive ahead-left) and what
    (the substructure unit type).  OBM's SupportLine + its Pier/Abutment."""

    station_ft: float = spec_field(unit="ft", desc="continuous station on the site alignment")
    kind: str = spec_field(enum=SUPPORT_KINDS)
    unit_type: str = spec_field(enum=ABUTMENT_UNIT_TYPES + PIER_UNIT_TYPES)
    skew_deg: float = spec_field(0.0, unit="deg", desc="support line skew from the normal, + ahead-left")
    name: str | None = spec_field(None)

    def _cross_validate(self) -> list[str]:
        out = []
        allowed = ABUTMENT_UNIT_TYPES if self.kind == "abutment" else PIER_UNIT_TYPES
        if self.unit_type not in allowed:
            out.append(f"unit_type: {self.unit_type!r} is not a {self.kind} type {allowed}")
        if abs(self.skew_deg) >= 60.0:
            out.append("skew_deg: must be below 60")
        return out


@dataclass(frozen=True)
class BridgeAlternativeRecord(ElementRecord):
    """One alternative of a Structure Type Study (ODOT BDM 201.1): a
    superstructure type (``civilpy.structural.bridge_type`` catalog key), a
    deck width and the support lines, on a site alignment.  Spans, unit
    heights, quantities and cost are derived from this record and the site;
    this is what the OBM writer builds the bridge from."""

    BIM_TYPE = "bridge"
    SUBTYPE = "alternative"

    label: str = spec_field()
    superstructure: str = spec_field(desc="bridge_type catalog key, e.g. ps_i_girder")
    deck_width_ft: float = spec_field(unit="ft", gt=0.0, desc="out-to-out")
    supports: tuple[SupportLineRecord, ...] = spec_field(())
    alignment_name: str | None = spec_field(None, desc="site alignment the stations refer to")
    girder_spacing_ft: float | None = spec_field(None, unit="ft")
    deck_thickness_in: float | None = spec_field(None, unit="in", desc="None = BDM 309.3.1 minimum for the spacing")
    railing: str = spec_field("SBR-1-20", desc="bridge railing SCD")
    notes: str = spec_field("")
    provenance: Provenance = spec_field(Provenance())

    def _cross_validate(self) -> list[str]:
        out = []
        if len(self.supports) < 2:
            out.append("supports: an alternative needs two supports at least")
            return out
        sts = [s.station_ft for s in self.supports]
        if any(b <= a for a, b in zip(sts, sts[1:])):
            out.append("supports: stations must strictly increase")
        if self.supports[0].kind != "abutment" or self.supports[-1].kind != "abutment":
            out.append("supports: the first and last supports must be abutments")
        try:
            from civilpy.structural.bridge_type import get_type
            get_type(self.superstructure)
        except Exception as exc:  # noqa: BLE001
            out.append(f"superstructure: {exc}")
        return out

    @property
    def spans_ft(self) -> tuple[float, ...]:
        sts = [s.station_ft for s in self.supports]
        return tuple(b - a for a, b in zip(sts, sts[1:]))
