#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""LandXML 1.2 alignments: read and write :class:`Alignment` objects.

LandXML is the exchange format OpenRoads Designer, OpenBridge Modeler,
InRoads/GEOPAK exports and most survey/CAD tools share, so it is how
alignments move between civilpy and those programs.  Covered:

* ``CoordGeom``: ``Line``, ``Curve`` (circular), ``Spiral`` (clothoid; other
  ``spiType`` values are rejected rather than approximated);
* ``StaEquation`` (``staBack``, ``staAhead``, ``staInternal``);
* ``Profile/ProfAlign``: ``PVI`` and symmetric ``ParaCurve`` (an
  ``UnsymParaCurve`` is rejected);
* units: ``Imperial`` (``USSurveyFoot`` / ``foot`` / ``internationalFoot``)
  or ``Metric`` (``meter``); civilpy alignments are in feet, so metric files
  are converted on read, and ``units=`` picks what is written.

LandXML points are ``northing easting``; civilpy plan coordinates are
``(x=East, y=North)``.  Surfaces are read by
:meth:`civilpy.transportation.terrain.Terrain.from_landxml`.

Example (round trip):

>>> import math, io
>>> from civilpy.transportation.alignment import Alignment, Tangent, Spiral, Curve
>>> al = Alignment((1000.0, 5000.0), 45.0,
...                [Tangent(200.0), Spiral(150.0, math.inf, 800.0, "R"),
...                 Curve(800.0, 20.0, "R"), Spiral(150.0, 800.0, math.inf, "R"),
...                 Tangent(300.0)], start_station_ft=10000.0)
>>> buf = io.StringIO()
>>> write_alignments({"CL": al}, buf)
>>> back = read_alignments(io.StringIO(buf.getvalue()))["CL"]
>>> [round(v, 6) for v in back.point_at(10500.0)[:2]] == [round(v, 6) for v in al.point_at(10500.0)[:2]]
True
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as _WET

import defusedxml.ElementTree as _RET  # stdlib etree is XXE-vulnerable for reading

from civilpy.transportation.alignment import Alignment, Curve, Spiral, Tangent, VerticalProfile

NS = "http://www.landxml.org/schema/LandXML-1.2"
US_FT_M = 1200.0 / 3937.0
IFT_M = 0.3048
#: feet per file unit
_LINEAR = {
    "USSurveyFoot": 1.0,
    "foot": 1.0,                                  # LandXML "foot" = US survey foot in US DOT exports
    "internationalFoot": IFT_M / US_FT_M,
    "meter": 1.0 / US_FT_M,
}
_WRITE_UNITS = {"USSurveyFoot": ("Imperial", 1.0), "meter": ("Metric", US_FT_M)}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _ne(el) -> tuple[float, float]:
    """(x=E, y=N) of a LandXML point element's 'northing easting [elev]' text."""
    v = [float(t) for t in (el.text or "").split()]
    return v[1], v[0]


def _az(p0, p1) -> float:
    return math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1])) % 360.0


def _radius(text, f) -> float:
    if text is None or str(text).strip().upper() in ("INF", "INFINITY", ""):
        return math.inf
    r = float(text)
    return math.inf if r == 0.0 else r * f


def _rot(el) -> str:
    rot = (el.get("rot") or "").lower()
    if rot not in ("cw", "ccw"):
        raise ValueError(f"{_local(el.tag)} has no rot='cw'|'ccw'")
    return "R" if rot == "cw" else "L"


def _linear_factor(root) -> float:
    units = _child(root, "Units")
    if units is None:
        return 1.0
    for sys_el in units:
        name = sys_el.get("linearUnit")
        if name:
            if name not in _LINEAR:
                raise ValueError(f"unsupported linearUnit {name!r}")
            return _LINEAR[name]
    return 1.0


def _elements(coord_geom, f):
    """(start point, start bearing, [elements]) from a CoordGeom, in feet."""
    elements, start_pt, start_az = [], None, None
    for g in coord_geom:
        kind = _local(g.tag)
        if kind == "Line":
            p0, p1 = _ne(_child(g, "Start")), _ne(_child(g, "End"))
            p0, p1 = (p0[0] * f, p0[1] * f), (p1[0] * f, p1[1] * f)
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if start_pt is None:
                start_pt, start_az = p0, _az(p0, p1)
            elements.append(Tangent(length))
        elif kind == "Curve":
            if (g.get("crvType") or "arc").lower() != "arc":
                raise ValueError(f"unsupported crvType {g.get('crvType')!r}")
            d = _rot(g)
            r = float(g.get("radius")) * f
            p0 = _ne(_child(g, "Start"))
            pc = _ne(_child(g, "Center"))
            p0, pc = (p0[0] * f, p0[1] * f), (pc[0] * f, pc[1] * f)
            if g.get("length") is not None:
                delta = math.degrees(float(g.get("length")) * f / r)
            else:
                p1 = _ne(_child(g, "End"))
                p1 = (p1[0] * f, p1[1] * f)
                a0 = math.atan2(p0[1] - pc[1], p0[0] - pc[0])
                a1 = math.atan2(p1[1] - pc[1], p1[0] - pc[0])
                sweep = (a0 - a1) if d == "R" else (a1 - a0)
                delta = math.degrees(sweep % (2 * math.pi))
            if start_pt is None:
                # tangent is perpendicular to the radius, turned toward travel
                radial = _az(pc, p0)
                start_pt, start_az = p0, (radial - 90.0 if d == "R" else radial + 90.0) % 360.0
            elements.append(Curve(r, delta, d))
        elif kind == "Spiral":
            spi = (g.get("spiType") or "clothoid").lower()
            if spi != "clothoid":
                raise ValueError(f"unsupported spiType {g.get('spiType')!r} (only clothoid)")
            d = _rot(g)
            length = float(g.get("length")) * f
            r0, r1 = _radius(g.get("radiusStart"), f), _radius(g.get("radiusEnd"), f)
            if start_pt is None:
                p0 = _ne(_child(g, "Start"))
                p0 = (p0[0] * f, p0[1] * f)
                if g.get("dirStart") is not None:
                    az = float(g.get("dirStart"))
                else:
                    pi = _ne(_child(g, "PI"))
                    az = _az(p0, (pi[0] * f, pi[1] * f))
                start_pt, start_az = p0, az % 360.0
            elements.append(Spiral(length, r0, r1, d))
        elif kind in ("IrregularLine", "Chain", "CurveSpiral"):
            raise ValueError(f"unsupported CoordGeom element {kind}")
    if not elements:
        raise ValueError("CoordGeom has no elements")
    return start_pt, start_az, elements


def _profile(align_el, f):
    prof = _child(align_el, "Profile")
    pa = _child(prof, "ProfAlign") if prof is not None else None
    if pa is None:
        return None
    pvis = []
    for p in pa:
        kind = _local(p.tag)
        vals = [float(t) for t in (p.text or "").split()]
        if kind == "PVI":
            pvis.append((vals[0] * f, vals[1] * f, 0.0))
        elif kind == "ParaCurve":
            pvis.append((vals[0] * f, vals[1] * f, float(p.get("length")) * f))
        elif kind == "UnsymParaCurve":
            raise ValueError("unsymmetrical vertical curves are not supported")
        elif kind == "CircCurve":
            raise ValueError("circular vertical curves are not supported")
    return VerticalProfile(pvis) if len(pvis) >= 2 else None


def read_alignments(source) -> dict[str, Alignment]:
    """All alignments in a LandXML file (path or file-like), keyed by name.

    Stations are continuous stations (``staStart`` + distance); station
    equations are attached as ``station_equations``.
    """
    root = _RET.parse(source).getroot()
    f = _linear_factor(root)
    out = {}
    for group in root:
        if _local(group.tag) != "Alignments":
            continue
        for a in group:
            if _local(a.tag) != "Alignment":
                continue
            name = a.get("name") or f"Alignment{len(out) + 1}"
            cg = _child(a, "CoordGeom")
            if cg is None:
                continue
            start_pt, start_az, elements = _elements(cg, f)
            sta_start = float(a.get("staStart") or 0.0) * f
            equations = []
            for eq in a:
                if _local(eq.tag) == "StaEquation":
                    equations.append((float(eq.get("staBack")) * f, float(eq.get("staAhead")) * f,
                                      float(eq.get("staInternal")) * f))
            equations.sort(key=lambda t: t[2])
            out[name] = Alignment(start_pt, start_az, elements, profile=_profile(a, f),
                                  start_station_ft=sta_start,
                                  station_equations=[(b, ah) for b, ah, _ in equations])
    return out


# ----------------------------------------------------------------- writing

def _pt(parent, tag, x, y, g):
    e = _WET.SubElement(parent, tag)
    e.text = f"{y * g:.6f} {x * g:.6f}"
    return e


def _fmt(v):
    return f"{v:.10g}"


def write_alignments(alignments: dict[str, Alignment], target, *, units: str = "USSurveyFoot",
                     project: str = "civilpy") -> None:
    """Write alignments (name -> Alignment) as LandXML 1.2 to a path or file-like.

    ``units``: ``"USSurveyFoot"`` (default) or ``"meter"``.
    """
    if units not in _WRITE_UNITS:
        raise ValueError(f"units must be one of {sorted(_WRITE_UNITS)}")
    system, g = _WRITE_UNITS[units]
    root = _WET.Element("LandXML", {"xmlns": NS, "version": "1.2"})
    u = _WET.SubElement(_WET.SubElement(root, "Units"), system,
                        {"linearUnit": units, "areaUnit": "squareFoot" if system == "Imperial" else "squareMeter",
                         "volumeUnit": "cubicFeet" if system == "Imperial" else "cubicMeter",
                         "angularUnit": "decimal degrees", "directionUnit": "decimal degrees"})
    del u
    _WET.SubElement(root, "Project", {"name": project})
    als = _WET.SubElement(root, "Alignments")
    for name, al in alignments.items():
        a = _WET.SubElement(als, "Alignment", {"name": name, "length": _fmt(al.length_ft * g),
                                               "staStart": _fmt(al.start_station * g)})
        cg = _WET.SubElement(a, "CoordGeom")
        for seg in al._segments:
            el = seg["el"]
            if isinstance(el, Tangent):
                ln = _WET.SubElement(cg, "Line", {"length": _fmt(el.length * g),
                                                  "staStart": _fmt(seg["s0"] * g)})
                _pt(ln, "Start", seg["x0"], seg["y0"], g)
                _pt(ln, "End", seg["x1"], seg["y1"], g)
            elif isinstance(el, Curve):
                c = _WET.SubElement(cg, "Curve", {"rot": "cw" if el.sign > 0 else "ccw",
                                                  "crvType": "arc", "radius": _fmt(el.radius_ft * g),
                                                  "length": _fmt(el.length * g),
                                                  "delta": _fmt(el.delta_deg),
                                                  "dirStart": _fmt(seg["az0"] % 360.0),
                                                  "dirEnd": _fmt(seg["az1"] % 360.0),
                                                  "staStart": _fmt(seg["s0"] * g)})
                _pt(c, "Start", seg["x0"], seg["y0"], g)
                _pt(c, "Center", seg["cx"], seg["cy"], g)
                _pt(c, "End", seg["x1"], seg["y1"], g)
            elif isinstance(el, Spiral):
                def rad(r):
                    return "INF" if math.isinf(r) else _fmt(r * g)
                s = _WET.SubElement(cg, "Spiral", {"rot": "cw" if el.sign > 0 else "ccw",
                                                   "spiType": "clothoid", "length": _fmt(el.length * g),
                                                   "radiusStart": rad(el.radius_start_ft),
                                                   "radiusEnd": rad(el.radius_end_ft),
                                                   "dirStart": _fmt(seg["az0"] % 360.0),
                                                   "dirEnd": _fmt(seg["az1"] % 360.0),
                                                   "staStart": _fmt(seg["s0"] * g)})
                _pt(s, "Start", seg["x0"], seg["y0"], g)
                _pt(s, "End", seg["x1"], seg["y1"], g)
            else:
                raise TypeError(f"cannot write element {el!r}")
        for (back, ahead), (c0, _, _) in zip(al.station_equations, al._equation_table[1:]):
            _WET.SubElement(a, "StaEquation", {"staBack": _fmt(back * g), "staAhead": _fmt(ahead * g),
                                               "staInternal": _fmt(c0 * g)})
        if al.profile is not None:
            pa = _WET.SubElement(_WET.SubElement(a, "Profile"), "ProfAlign", {"name": f"{name} profile"})
            for sta, elev, length in al.profile.pvis:
                if length > 0.0:
                    p = _WET.SubElement(pa, "ParaCurve", {"length": _fmt(length * g)})
                else:
                    p = _WET.SubElement(pa, "PVI")
                p.text = f"{sta * g:.6f} {elev * g:.6f}"
    tree = _WET.ElementTree(root)
    _WET.indent(tree)
    if hasattr(target, "write"):
        target.write(_WET.tostring(root, encoding="unicode", xml_declaration=True))
    else:
        tree.write(str(target), encoding="utf-8", xml_declaration=True)
