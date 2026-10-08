#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Readers that turn published boring-log deliverables into the canonical
:class:`~civilpy.geotech.boring.Borehole` objects.

The primary, near-lossless path is **DIGGS** (Data Interchange for
Geotechnical and Geoenvironmental Specialists) XML -- the structured export
many DOTs publish alongside the rendered PDF log.  Ohio DOT, for example,
serves a ``DIGGS_URL`` for each hole on its TIMS geotechnical layer; that
file carries the borehole geometry, every SPT drive set, and the full
particle-size curve, so no character-window scraping is needed.

A DIGGS document is GML-based and heavily namespaced; this reader matches
on *local* element names so it is agnostic to the schema version
(2.5.a, 2.6, ...) and to namespace-prefix churn.  Only the standard
library (:mod:`defusedxml.ElementTree`) is used.

PDF log ingestion (for the raster/scanned holes that have no DIGGS file) is
a separate, lower-fidelity concern handled by :func:`read_pdf_log`.
"""

from __future__ import annotations

import defusedxml.ElementTree as ET  # stdlib etree is XXE-vulnerable
from pathlib import Path

from civilpy.geotech.boring import (
    Borehole,
    DriveIncrement,
    Layer,
    GradingPoint,
    GradingResult,
    Sample,
    SPTResult,
)

# --------------------------------------------------------------- ET helpers


def _ln(tag: str) -> str:
    """Local name of a (possibly namespaced) element tag."""
    return tag.rsplit("}", 1)[-1]


def _children(el, name: str):  # pragma: no cover - convenience helper, unused
    """Direct children of ``el`` with local name ``name``."""
    return [c for c in el if _ln(c.tag) == name]


def _descendants(el, name: str):
    """All descendants (any depth) of ``el`` with local name ``name``."""
    return [c for c in el.iter() if _ln(c.tag) == name and c is not el]


def _first(el, name: str):
    for c in el.iter():
        if c is not el and _ln(c.tag) == name:
            return c
    return None


def _text(el, name: str) -> str | None:
    c = _first(el, name)
    if c is None or c.text is None:
        return None
    t = c.text.strip()
    return t or None


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip().split()[0])
    except (ValueError, IndexError):
        return None


def _ref_id(el, name: str) -> str | None:
    """The ``#id`` href target of a reference child (``samplingFeatureRef``
    etc.), with the leading ``#`` and any stray brace stripped."""
    c = _first(el, name)
    if c is None:
        return None
    for k, v in c.attrib.items():
        if _ln(k) == "href":
            return v.lstrip("#").rstrip("}")
    return None


def _gml_id(el) -> str | None:
    for k, v in el.attrib.items():
        if _ln(k) == "id":
            return v
    return None


def _poslist_floats(el) -> list[float]:
    """Numbers from the first ``posList``/``pos`` descendant of ``el``."""
    for name in ("posList", "pos"):
        node = _first(el, name)
        if node is not None and node.text:
            return [float(x) for x in node.text.split()]
    return []


# --------------------------------------------------------------- DIGGS


def parse_diggs(source) -> list[Borehole]:
    """Parse a DIGGS document into a list of :class:`Borehole`.

    ``source`` may be a file path, an open file/bytes, or a string of XML.
    Every ``Borehole`` sampling feature becomes one object; the SPT and
    particle-size ``Test`` records and the ``SamplingActivity`` sample
    intervals are attached to their borehole by ``samplingFeatureRef``.
    """
    root = _load_root(source)

    project = _project_name(root)
    holes: dict[str, Borehole] = {}
    # id-stripped lookups so refs like "Borehole_B-001" and "B-001" both hit.
    by_id: dict[str, Borehole] = {}

    for bh_el in (e for e in root.iter() if _ln(e.tag) == "Borehole"):
        bh = _parse_borehole(bh_el, project)
        holes[bh.boring_id] = bh
        gid = _gml_id(bh_el)
        if gid:
            by_id[gid] = bh
        by_id[bh.boring_id] = bh

    def resolve(ref: str | None) -> Borehole | None:
        if ref is None:
            return None
        if ref in by_id:
            return by_id[ref]
        # "Borehole_B-001-0-21" -> "B-001-0-21"
        trimmed = ref.split("_", 1)[-1]
        return by_id.get(trimmed)

    for test_el in (e for e in root.iter() if _ln(e.tag) == "Test"):
        bh = resolve(_ref_id(test_el, "samplingFeatureRef"))
        if bh is None:
            continue
        name = (_text(test_el, "name") or "").upper()
        if _first(test_el, "DriveSet") is not None:
            spt = _parse_spt(test_el)
            if spt is not None:
                bh.spt.append(spt)
        elif "PARTICLE" in name or _first(test_el, "Grading") is not None:
            grad = _parse_grading(test_el)
            if grad is not None:
                bh.grading.append(grad)

    for act_el in (e for e in root.iter() if _ln(e.tag) == "SamplingActivity"):
        bh = resolve(_ref_id(act_el, "samplingFeatureRef"))
        if bh is None:
            continue
        sample = _parse_sample(act_el)
        if sample is not None:
            bh.samples.append(sample)

    for sys_el in (e for e in root.iter() if _ln(e.tag) == "LithologySystem"):
        bh = resolve(_ref_id(sys_el, "samplingFeatureRef"))
        if bh is None:
            continue
        system = (_text(sys_el, "lithologyClassificationType") or "").strip().upper() or None
        for obs in _descendants(sys_el, "LithologyObservation"):
            lay = _parse_layer(obs, system)
            if lay is not None:
                bh.layers.append(lay)

    for bh in holes.values():
        bh.layers = _merge_layers(bh.layers)
        bh.spt.sort(key=lambda s: s.depth_ft)
        bh.grading.sort(key=lambda g: g.depth_ft)
        bh.samples.sort(key=lambda s: s.depth_top_ft)

    return list(holes.values())


def _load_root(source):
    if isinstance(source, (str, Path)) and (
        isinstance(source, Path) or "<" not in str(source)[:200]
    ):
        return ET.parse(source).getroot()
    if isinstance(source, bytes):
        return ET.fromstring(source)
    if isinstance(source, str):
        return ET.fromstring(source)
    # open file object
    return ET.parse(source).getroot()


def _project_name(root) -> str | None:
    proj = _first(root, "Project")
    if proj is None:
        return None
    return _text(proj, "name")


def _parse_borehole(el, project: str | None) -> Borehole:
    name = _text(el, "name") or _gml_id(el) or "UNKNOWN"

    lat = lon = elev = None
    rp = _first(el, "referencePoint")
    if rp is not None:
        coords = _poslist_floats(rp)
        if len(coords) >= 3:
            lon, lat, elev = coords[0], coords[1], coords[2]
        elif len(coords) == 2:
            lon, lat = coords

    station = _text(el, "station")
    offset_ft = _float(_text(el, "offset"))
    offset_dir = _text(el, "offsetDirection")
    total_depth = _float(_text(el, "totalMeasuredDepth"))
    purpose = _text(el, "boreholePurpose")

    date = None
    when = _first(el, "whenConstructed")
    if when is not None:
        date = _text(when, "start") or _text(when, "end")

    water_depth = None
    ws = _first(el, "waterStrike")
    if ws is not None:
        wl_coords = _poslist_floats(_first(ws, "waterLocation") or ws)
        if wl_coords:
            # a single value is a depth/elevation reading
            water_depth = wl_coords[-1]

    depth_to_rock = None
    for prm in _descendants(el, "Parameter"):
        if (_text(prm, "parameterName") or "").strip().lower() == "depth to rock":
            depth_to_rock = _float(_text(prm, "parameterValue"))

    return Borehole(
        depth_to_rock_ft=depth_to_rock,
        boring_id=name,
        project=project,
        ground_elevation_ft=elev,
        latitude=lat,
        longitude=lon,
        station=station,
        offset_ft=offset_ft,
        offset_direction=offset_dir,
        total_depth_ft=total_depth,
        water_strike_depth_ft=water_depth,
        date=date,
        purpose=purpose,
    )


def _depth_from_test(el) -> float | None:
    """Top depth of a Test from its result location, falling back to the
    numeric suffix of its gml:id (``SPT_B-001-0-21_1.5`` -> 1.5)."""
    loc = _first(el, "location")
    if loc is not None:
        vals = _poslist_floats(loc)
        if vals:
            return vals[0]
    gid = _gml_id(el) or ""
    tail = gid.rsplit("_", 1)[-1]
    return _float(tail)


def _parse_spt(el) -> SPTResult | None:
    depth = _depth_from_test(el)
    if depth is None:
        return None
    proc = _first(el, "DrivenPenetrationTest")
    hammer_type = _text(proc, "hammerType") if proc is not None else None
    hammer_eff = _text(proc, "hammerEfficiency") if proc is not None else None
    increments = []
    for ds in _descendants(el, "DriveSet"):
        blows = _float(_text(ds, "blowCount"))
        pen = _float(_text(ds, "penetration"))
        if blows is None:
            continue
        increments.append(
            DriveIncrement(blows=int(blows), penetration_in=pen if pen is not None else 6.0)
        )
    if not increments:
        return None
    increments.sort(key=lambda d: 0)  # preserve document order
    return SPTResult(
        depth_ft=depth,
        increments=tuple(increments),
        hammer_type=hammer_type,
        hammer_efficiency=hammer_eff,
    )


def _parse_grading(el) -> GradingResult | None:
    depth = _depth_from_test(el)
    if depth is None:
        return None
    points = []
    for g in _descendants(el, "Grading"):
        size = _float(_text(g, "particleSize"))
        pct = _float(_text(g, "percentPassing"))
        if size is None or pct is None:
            continue
        points.append(GradingPoint(particle_size_mm=size, percent_passing=pct))
    if not points:
        return None
    points.sort(key=lambda p: p.particle_size_mm, reverse=True)
    return GradingResult(depth_ft=depth, points=tuple(points))


def _parse_sample(el) -> Sample | None:
    loc = _first(el, "samplingLocation")
    coords = _poslist_floats(loc) if loc is not None else []
    if len(coords) >= 2:
        top, bottom = coords[0], coords[1]
    elif len(coords) == 1:
        top = bottom = coords[0]
    else:
        return None
    method = None
    sm = _first(el, "samplingMethod")
    if sm is not None:
        method = _text(sm, "name")
    recovery = _float(_text(el, "totalSampleRecoveryLength"))
    return Sample(
        depth_top_ft=top,
        depth_bottom_ft=bottom,
        method=method,
        recovery_in=recovery,
    )


def _merge_layers(layers: list[Layer]) -> list[Layer]:
    """One layer per depth interval: ODOT files log a rock interval in both
    the SOIL and the ROCK lithology systems - merged field by field (the
    first non-empty value wins, the ROCK system first)."""
    import dataclasses

    by_iv: dict = {}
    order = sorted(layers, key=lambda lay: (lay.depth_top_ft, lay.depth_bottom_ft, lay.system != "ROCK"))
    for lay in order:
        key = (round(lay.depth_top_ft, 3), round(lay.depth_bottom_ft, 3))
        cur = by_iv.get(key)
        if cur is None:
            by_iv[key] = lay
            continue
        merged = {}
        for f in dataclasses.fields(Layer):
            a, b = getattr(cur, f.name), getattr(lay, f.name)
            merged[f.name] = a if a not in (None, (), "") else b
        by_iv[key] = Layer(**merged)
    return sorted(by_iv.values(), key=lambda lay: lay.depth_top_ft)


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _parse_layer(el, system: str | None) -> Layer | None:
    loc = _first(el, "location")
    coords = _poslist_floats(loc) if loc is not None else []
    if len(coords) < 2 or coords[1] <= coords[0]:
        return None
    lith = _first(el, "Lithology")
    if lith is None:
        return None
    graphic = None
    for prm in _descendants(lith, "Parameter"):
        if (_text(prm, "parameterName") or "").strip().lower() == "graphic":
            graphic = _clean(_text(prm, "parameterValue"))
    constituents = []
    for con in _descendants(lith, "Constituent"):
        val = _clean(_text(con, "codeValue"))
        if val:
            major = (_text(con, "abundanceCode") or "").strip().lower() == "major"
            constituents.insert(0, val) if major else constituents.append(val)
    color = None
    col = _first(lith, "Color")
    if col is not None:
        color = _clean(_text(col, "colorName"))
    fp = _first(lith, "FieldProperties")

    def prop(name):
        return _clean(_text(fp, name)) if fp is not None else None

    return Layer(
        depth_top_ft=coords[0], depth_bottom_ft=coords[1], system=system,
        classification=graphic, uscs=_clean(_text(lith, "classificationCode")),
        description=_clean(_text(lith, "lithDescription")), constituents=tuple(constituents), color=color,
        consistency=prop("consistency"), moisture=prop("moistureCondition"),
        rock_strength=prop("rockStrength"), rock_weathering=prop("rockWeathering"),
        recovery_pct=_float(prop("unitRecoveryLength")), rqd_pct=_float(prop("unitRQDLength")),
    )


# --------------------------------------------------------------- PDF (fallback)


def read_pdf_log(path) -> Borehole:  # pragma: no cover - placeholder
    """Best-effort reader for a rendered PDF boring log.

    Most published logs are raster/scanned PDFs with no text layer, which
    require OCR and template-specific table recovery; that lower-fidelity
    path is not yet implemented.  Prefer :func:`parse_diggs` whenever a
    DIGGS file is available for the hole.
    """
    raise NotImplementedError(
        "PDF boring-log parsing is not implemented yet; use parse_diggs() "
        "with the hole's DIGGS export when available."
    )
