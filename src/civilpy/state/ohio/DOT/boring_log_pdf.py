#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Read ODOT's standard gINT boring log sheet from a PDF.

Every consultant logging for ODOT prints from the same gINT library
("STANDARD ODOT SOIL BORING LOG (8.5 X 11)", landscape letter), so the
sheet has one geometry: a header of labelled cells, then a body of columns
separated by vertical rules - material description, graphic, elevation,
depths (water levels, top of rock, EOB), the depth scale (1 ft = 15.24 pt,
30 ft a page), SPT blows / RQD, N60, recovery, sample id, hand penetrometer,
the gradation fractions (GR CS FS SI CL), Atterberg limits, water content,
ODOT class with group index, and hole sealed.  The reader works from the
text layer and the drawn lines (layer boundaries, sample bars, column
rules), so it needs a vector PDF - the gINT print, not a scan.  A scanned
log needs OCR first; :func:`is_odot_log_page` says no for it.

Coordinates come from the sheet, never from a template: columns are found
from the vertical rules under their header labels, the depth scale is fitted
to the printed tick numbers, layer boundaries are the lines drawn across the
description column, and sample intervals are the bars in the sample column.
Values the sheet prints are read as printed (a dash is "not run"); nothing is
inferred except the sample interval from its bar and the gradation curve
from the five fractions.

The result is a :class:`BoringLog` per hole (header, layers, sample rows,
water levels, notes) with :meth:`BoringLog.to_borehole` giving the canonical
:class:`~civilpy.geotech.boring.Borehole`.  ``civilpy.geotech.diggs_writer``
turns either into a DIGGS file.

Requires PyMuPDF (``pip install civilpy[pdf]``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from civilpy.geotech.boring import (
    ROCK_NAMES,
    Borehole,
    DriveIncrement,
    GradingPoint,
    GradingResult,
    Layer,
    Sample,
    SPTResult,
)

#: points per foot on the sheet (30 ft a page between the body rules)
PT_PER_FT = 15.24
FT_PER_PAGE = 30.0
#: header labels (as printed, upper case); "EXPLORATION ID" and "PAGE" take their value from the row below
HEADER_LABELS = (
    "EXPLORATION ID", "PROJECT:", "TYPE:", "PID:", "SFN:", "BR ID:", "START:", "END:",
    "DRILLING FIRM / OPERATOR:", "SAMPLING FIRM / LOGGER:", "DRILLING METHOD:", "SAMPLING METHOD:",
    "DRILL RIG:", "HAMMER:", "CALIBRATION DATE:", "ENERGY RATIO (%):", "STATION / OFFSET:", "ALIGNMENT:",
    "ELEVATION:", "EOB:", "LAT / LONG:", "PAGE", "PG", "JOB:",
)
_ID_PATTERN = re.compile(r"^[A-Z]{1,4}\d?-\d{1,4}(-\d+)*(-\d{2})?[A-Z]?$")
_PSEUDO = re.compile(r"^(Topsoil|Asphalt|Portland Cement Concrete|Concrete|Aggregate Base|Granular Base|Brick|Pavement|Base)"
                     r"\s*[-:]\s*(\d+(?:\.\d+)?)\s*(?:\"|in\b|inches|INCHES|\u201d)", re.I)
_BELOW_LABELS = ("EXPLORATION ID", "PAGE")
#: body column labels -> column keys
COLUMN_LABELS = {
    "MATERIAL": "description", "ELEV.": "elev", "DEPTHS": "depths", "SPT/": "spt", "N60": "n60", "REC": "rec",
    "SAMPLE": "sample", "HP": "hp", "GR": "gr", "CS": "cs", "FS": "fs", "SI": "si", "CL": "cl", "LL": "ll",
    "PL": "pl", "PI": "pi", "WC": "wc", "ODOT": "cls", "HOLE": "sealed",
}
#: the sheet's column rules (x, points) - the fallback when a label is not found
DEFAULT_COLUMNS = {
    "description": (28.8, 266.4), "graphic": (266.4, 284.4), "elev": (284.4, 316.8), "depths": (316.8, 356.4),
    "scale": (356.4, 385.2), "spt": (385.2, 410.4), "n60": (410.4, 432.0), "rec": (432.0, 453.6),
    "sample": (453.6, 489.6), "hp": (489.6, 511.2), "gr": (511.2, 529.2), "cs": (529.2, 547.2),
    "fs": (547.2, 565.2), "si": (565.2, 583.2), "cl": (583.2, 601.2), "ll": (601.2, 619.2), "pl": (619.2, 637.2),
    "pi": (637.2, 655.2), "wc": (655.2, 676.8), "cls": (676.8, 716.4), "sealed": (716.4, 748.8),
}
VALUE_COLUMNS = ("n60", "rec", "hp", "gr", "cs", "fs", "si", "cl", "ll", "pl", "pi", "wc")
#: ODOT gradation fractions -> the sieve size each fraction passes (mm): gravel 75-2.0, coarse sand 2.0-0.42,
#: fine sand 0.42-0.075, silt 0.075-0.005, clay under 0.005 (SGE / ODOT soil classification sheet)
FRACTION_SIZES_MM = {"gr": 2.0, "cs": 0.425, "fs": 0.075, "si": 0.005}
TOP_SIZE_MM = 75.0
CONSISTENCY = ("very soft", "soft", "medium stiff", "stiff", "very stiff", "hard",
               "very loose", "loose", "medium dense", "dense", "very dense")
MOISTURE = ("damp to moist", "moist to wet", "damp to wet", "damp", "moist", "wet", "dry", "saturated")
ROCK_STRENGTH = ("extremely weak", "very weak", "weak", "slightly strong", "moderately strong", "strong",
                 "very strong", "extremely strong")
ROCK_WEATHERING = ("unweathered", "slightly weathered", "moderately weathered", "highly weathered",
                   "severely weathered", "completely weathered", "weathered")
PAVEMENT_WORDS = ("ASPHALT", "PORTLAND", "CONCRETE", "AGGREGATE", "BASE", "GRANULAR BASE", "PAVEMENT", "BRICK")
_SOIL_NOUNS = ("GRAVEL", "SAND", "SILT", "CLAY", "PEAT", "MUCK", "SHALE", "LIMESTONE", "SANDSTONE", "SILTSTONE",
               "DOLOMITE", "CLAYSTONE", "MUDSTONE", "COAL", "TOPSOIL")
_CORE_PREFIXES = ("NQ", "NX", "HQ", "RC", "CORE", "C-", "BX")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


# ---------------------------------------------------------------------- records


@dataclass
class LogHeader:
    """The header cells, typed where the rest of the reader needs them;
    ``raw`` keeps every label's text as printed."""

    exploration_id: str
    raw: dict = field(default_factory=dict)
    ground_elevation_ft: float | None = None
    eob_ft: float | None = None
    station: str | None = None
    offset_ft: float | None = None
    offset_direction: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    start: str | None = None
    end: str | None = None
    pid: str | None = None
    project: str | None = None
    alignment: str | None = None
    type: str | None = None
    sfn: str | None = None
    hammer: str | None = None
    energy_ratio_pct: float | None = None
    drilling_method: str | None = None
    sampling_method: str | None = None
    page: int = 1
    pages: int = 1


@dataclass
class SampleRow:
    """One row of the sample table: the interval from the bar in the sample
    column, the blows in it, and the lab columns as printed (``None`` where
    the sheet prints a dash)."""

    sample_id: str
    depth_top_ft: float
    depth_bottom_ft: float
    method: str
    blows: tuple[str, ...] = ()
    n60: float | None = None
    rec_pct: float | None = None
    rqd_pct: float | None = None
    hp_tsf: float | None = None
    hp_text: str | None = None
    gradation: dict | None = None            # {'gr', 'cs', 'fs', 'si', 'cl'} percent
    ll: float | None = None
    pl: float | None = None
    pi: float | None = None
    wc: float | None = None
    odot_class: str | None = None
    group_index: str | None = None           # '10', or 'V' when the class is visual

    @property
    def is_core(self) -> bool:
        return self.method.upper().startswith(_CORE_PREFIXES) or (self.odot_class or "").upper() == "CORE"

    def increments(self) -> tuple[DriveIncrement, ...]:
        """The 6 in drives: ``50/4"`` is 50 blows for 4 in; ``WOH`` / ``WOR``
        (weight of hammer / rods) is zero blows."""
        out = []
        for b in self.blows:
            t = b.strip().upper().replace("”", '"')
            if t in ("WOH", "WOR", "WH", "WR"):
                out.append(DriveIncrement(0, 6.0))
            elif "/" in t:
                n, pen = t.split("/", 1)
                pen = re.sub(r"[^0-9.]", "", pen)
                try:
                    out.append(DriveIncrement(int(float(n)), float(pen) if pen else 6.0))
                except ValueError:
                    continue
            elif _NUM.match(t):
                out.append(DriveIncrement(int(float(t)), 6.0))
        return tuple(out)

    def grading(self) -> GradingResult | None:
        """The five printed fractions as a percent-passing curve."""
        g = self.gradation
        if not g or all(v is None for v in g.values()):
            return None
        gr, cs, fs, si, cl = (g.get(k) or 0.0 for k in ("gr", "cs", "fs", "si", "cl"))
        pts = [GradingPoint(TOP_SIZE_MM, 100.0), GradingPoint(2.0, 100.0 - gr), GradingPoint(0.425, 100.0 - gr - cs),
               GradingPoint(0.075, 100.0 - gr - cs - fs), GradingPoint(0.005, cl)]
        return GradingResult(depth_ft=self.depth_top_ft, points=tuple(pts))


@dataclass
class LogLayer:
    depth_top_ft: float
    depth_bottom_ft: float
    description: str
    notes: list[str] = field(default_factory=list)
    elevation_top_ft: float | None = None

    def to_layer(self, rows: list[SampleRow] | None = None) -> Layer:
        f = describe(self.description)
        if f["classification"] is None and f["system"] == "SOIL":
            # older sheets print the class only in the ODOT CLASS column of the sample rows
            inside = [r.odot_class for r in (rows or [])
                      if r.odot_class and r.odot_class.upper() not in ("ROCK", "CORE")
                      and self.depth_top_ft - 0.05 <= r.depth_top_ft < self.depth_bottom_ft - 0.05]
            if inside:
                f["classification"] = max(set(inside), key=inside.count)
        rec = rqd = None
        cores = [r for r in (rows or []) if r.is_core and r.depth_top_ft < self.depth_bottom_ft and r.depth_bottom_ft > self.depth_top_ft]
        if cores:
            w = [max(min(r.depth_bottom_ft, self.depth_bottom_ft) - max(r.depth_top_ft, self.depth_top_ft), 0.01) for r in cores]
            if any(r.rec_pct is not None for r in cores):
                rec = sum(wi * (r.rec_pct or 0.0) for wi, r in zip(w, cores)) / sum(w)
            if any(r.rqd_pct is not None for r in cores):
                rqd = sum(wi * (r.rqd_pct or 0.0) for wi, r in zip(w, cores)) / sum(w)
        desc = self.description + ((" " + " ".join(self.notes)) if self.notes else "")
        return Layer(depth_top_ft=self.depth_top_ft, depth_bottom_ft=self.depth_bottom_ft, system=f["system"],
                     classification=f["classification"], description=desc, constituents=tuple(f["constituents"]),
                     color=f["color"], consistency=f["consistency"], moisture=f["moisture"],
                     rock_strength=f["rock_strength"], rock_weathering=f["rock_weathering"],
                     recovery_pct=None if rec is None else round(rec, 1), rqd_pct=None if rqd is None else round(rqd, 1))


@dataclass
class BoringLog:
    """One hole as read from its sheet(s)."""

    header: LogHeader
    layers: list[LogLayer] = field(default_factory=list)
    samples: list[SampleRow] = field(default_factory=list)
    water: list[dict] = field(default_factory=list)     # {'elevation_ft', 'depth_ft'}
    top_of_rock_ft: float | None = None
    pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str | None = None

    @property
    def boring_id(self) -> str:
        return self.header.exploration_id

    def to_borehole(self) -> Borehole:
        h = self.header
        samples = [Sample(r.depth_top_ft, r.depth_bottom_ft, r.method,
                          recovery_in=None if r.rec_pct is None else round(r.rec_pct / 100.0 * (r.depth_bottom_ft - r.depth_top_ft) * 12.0, 2))
                   for r in self.samples]
        spt = []
        eff = None if h.energy_ratio_pct is None else f"{h.energy_ratio_pct:g}"
        drives: dict[str, list[SampleRow]] = {}
        for r in self.samples:
            if r.is_core or r.method.upper().startswith("ST"):
                continue
            # SS-2A / SS-2B are two jars from one 18 in drive: one SPT at the top of the first
            drives.setdefault(re.sub(r"[A-Z]$", "", r.sample_id), []).append(r)
        for rows in drives.values():
            rows.sort(key=lambda r: r.depth_top_ft)
            inc = tuple(i for r in rows for i in r.increments())
            if inc:
                spt.append(SPTResult(rows[0].depth_top_ft, inc, hammer_type=h.hammer, hammer_efficiency=eff))
        spt.sort(key=lambda s: s.depth_ft)
        grading = [g for g in (r.grading() for r in self.samples) if g is not None]
        layers = [lay.to_layer(self.samples) for lay in self.layers]
        rock = self.top_of_rock_ft
        if rock is None:
            tops = [lay.depth_top_ft for lay in layers if lay.group == "rock"]
            rock = min(tops) if tops else None
        return Borehole(boring_id=h.exploration_id, project=h.project or h.pid, ground_elevation_ft=h.ground_elevation_ft,
                        latitude=h.latitude, longitude=h.longitude, station=h.station, offset_ft=h.offset_ft,
                        offset_direction=h.offset_direction, total_depth_ft=h.eob_ft,
                        water_strike_depth_ft=self.water[0]["depth_ft"] if self.water else None, date=h.start,
                        purpose=h.type, samples=samples, spt=spt, grading=grading, layers=layers, depth_to_rock_ft=rock)


# ---------------------------------------------------------------------- description text


def describe(text: str) -> dict:
    """Split a printed description into the logged fields: consistency,
    color, constituents (major first), ODOT class, moisture; or for rock the
    name, color, strength and weathering."""
    out = {"system": "SOIL", "classification": None, "constituents": [], "color": None, "consistency": None,
           "moisture": None, "rock_strength": None, "rock_weathering": None}
    t = text.strip()
    if not t:
        return out
    up = t.upper()
    m = re.search(r"\((A-\d(?:-\d)?[ab]?)\)", t, flags=re.I)
    if m:
        out["classification"] = m.group(1)
    if "TOPSOIL" in up[:40]:
        out["classification"] = "TOPSOIL"
        out["constituents"] = ["TOPSOIL"]
        return out
    if re.search(r"\d\s*(?:\"|”|IN\b|INCH)", up[:60]) and re.search(r"ASPHALT|CONCRETE|BASE|PAVEMENT|BRICK", up[:60]):
        out["classification"] = "PAVEMENT OR BASE"
        out["constituents"] = [re.sub(r"\s*\(.*$", "", t).strip().upper()]
        return out
    head = re.split(r"[,;:(]", up)[0].strip().split()
    first = head[0] if head else ""
    if first in ROCK_NAMES or first.rstrip(",;") in ROCK_NAMES:
        out["system"] = "ROCK"
        parts = [p.strip(" .") for p in re.split(r"[,;]", t)]
        out["constituents"] = [parts[0].upper()]
        out["classification"] = out["classification"] or parts[0].upper().split()[0]
        low = [p.lower() for p in parts[1:]]
        for p in low:
            if any(p.startswith(s) or p == s for s in ROCK_STRENGTH) and out["rock_strength"] is None:
                out["rock_strength"] = next(s for s in ROCK_STRENGTH if p.startswith(s) or p == s)
            elif any(p.endswith(w) or p == w for w in ROCK_WEATHERING) and out["rock_weathering"] is None:
                out["rock_weathering"] = next(w for w in ROCK_WEATHERING if p.endswith(w) or p == w)
            elif out["color"] is None and re.fullmatch(r"(?:(?:light|dark|mottled|and|to|brownish|grayish|reddish|greenish|yellowish)\s+)*(?:gray|grey|brown|black|tan|red|green|yellow|white|blue|olive|orange)(?:\s+(?:and|to)\s+\w+)*", p):
                out["color"] = p
        return out
    if any(up.startswith(w) for w in ("ASPHALT", "PORTLAND", "CONCRETE", "AGGREGATE", "GRANULAR BASE", "BRICK", "PAVEMENT")):
        out["classification"] = "PAVEMENT OR BASE"
        name = re.split(r"[-:(]", t)[0].strip().upper()
        out["constituents"] = [name if len(name.split()) <= 3 else name.split()[0]]
        return out
    if t.upper() == t and t.count(",") >= 2:
        return _describe_comma_form(t, out)
    body = re.sub(r"^(POSSIBLE |POSSIBILE )?FILL:\s*", "", t, flags=re.I)
    low = body.lower()
    for c in sorted(CONSISTENCY, key=len, reverse=True):
        if low.startswith(c + " ") or low.startswith(c + ","):
            out["consistency"] = c
            body = body[len(c):].strip(" ,")
            break
    for mo in sorted(MOISTURE, key=len, reverse=True):
        if re.search(r"\b" + re.escape(mo) + r"\b", body, flags=re.I):
            out["moisture"] = mo
            break
    # words before the first upper-case soil noun are the color
    words = body.replace(";", ",").split()
    color = []
    for w in words:
        if w.isupper() and len(w) > 1 and re.sub(r"[^A-Z]", "", w) in _SOIL_NOUNS + ("SILTY", "SANDY", "CLAYEY", "GRAVELLY", "COARSE", "FINE", "AND", "WITH"):
            break
        if w.lower().strip(",") in ("and", "to", "light", "dark", "mottled", "with") or re.fullmatch(r"[a-z]+-?[a-z]*,?", w.lower()):
            color.append(w.strip(","))
        else:
            break
    if color:
        out["color"] = " ".join(color).strip()
    caps = re.search(r"((?:[A-Z][A-Z-]+\s*)+)", body)
    if caps:
        main = caps.group(1).strip()
        main = re.sub(r"\s*\(A-.*$", "", main)
        out["constituents"] = [main]
        rest = body[caps.end():]
        for mod in re.findall(r"\b((?:trace|little|some|and)\s+[a-z\"' ]+?)(?=,|\.|;|\(|$)", rest, flags=re.I):
            mod = mod.strip()
            if mod and mod.lower() not in MOISTURE and not any(mod.lower().startswith(m_) for m_ in MOISTURE):
                out["constituents"].append(mod)
    return out


_COLOR_WORDS = ("gray", "grey", "brown", "black", "tan", "red", "green", "yellow", "white", "blue", "olive", "orange",
                "light", "dark", "mottled", "and", "with", "to", "brownish", "grayish", "reddish", "greenish", "yellowish")
_MODIFIER = re.compile(r"^(trace|little|some|and|with|contains|occasional|few)\b", re.I)


def _describe_comma_form(t: str, out: dict) -> dict:
    """The all-caps, comma-separated form of older sheets: ``HARD, BROWN AND
    GRAY, SANDY SILT, SOME CLAY, TRACE GRAVEL, DAMP (FILL)``."""
    body = re.sub(r"\((?:POSSIBLE )?FILL\)|\bFILL:\s*", "", t, flags=re.I).strip(" .")
    parts = [x.strip(" .") for x in body.split(",") if x.strip(" .")]
    main = None
    for part in parts:
        low = part.lower()
        if out["consistency"] is None and low in CONSISTENCY:
            out["consistency"] = low
        elif out["moisture"] is None and low in MOISTURE:
            out["moisture"] = low
        elif out["color"] is None and main is None and all(w in _COLOR_WORDS for w in low.split()):
            out["color"] = low
        elif _MODIFIER.match(part) and main is not None:
            out["constituents"].append(part)
        elif main is None:
            main = part.upper()
            out["constituents"].insert(0, main)
        elif out["moisture"] is None and any(m_ in low for m_ in MOISTURE):
            out["moisture"] = next(m_ for m_ in sorted(MOISTURE, key=len, reverse=True) if m_ in low)
    return out


# ---------------------------------------------------------------------- page geometry


def _words(page, *, min_x: float = 30.0):
    """PyMuPDF words as dicts, dropping the rotated footer in the left margin."""
    out = []
    for w in page.get_text("words"):
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        if x0 < min_x or not text.strip():
            continue
        out.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "xc": 0.5 * (x0 + x1), "yc": 0.5 * (y0 + y1), "text": text})
    return out


def _rules(page):
    """Horizontal and vertical line segments drawn on the page."""
    h, v = [], []
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.height < 2.5 and r.width > 8:
            h.append((round(r.y0, 1), round(r.x0, 1), round(r.x1, 1)))
        elif r.width < 2.5 and r.height > 8:
            v.append((round(r.x0, 1), round(r.y0, 1), round(r.y1, 1)))
        elif r.height <= 14 and r.width > 100 and r.x0 < 40 and all(it[0] == "l" for it in dr["items"]):
            # a gradational contact: gINT draws it as a sloped line across the description column
            h.append((round(0.5 * (r.y0 + r.y1), 1), round(r.x0, 1), round(r.x1, 1)))
    return sorted(set(h)), sorted(set(v))


def _snap(d: float, grid: float = 0.05) -> float:
    """Depths read off the sheet scale, to the sheet's 0.05 ft resolution."""
    return round(round(d / grid) * grid, 2)


def _float(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.strip().replace(",", "").rstrip("*+").strip()
    if t in ("", "-", "--", "NP", "N/A", "NA"):
        return None
    m = re.search(r"-?\d+(\.\d+)?", t)
    return float(m.group(0)) if m else None


def is_odot_log_page(page) -> bool:
    """True when the page carries the ODOT sheet's body header (text layer
    present)."""
    text = page.get_text()
    if "DEPTHS" not in text or "N60" not in text:
        return False
    return "EXPLORATION ID" in text or re.search(r"\bPG\s+\d+\s+OF\s+\d+", text) is not None


def _geometry(page, words, hrules, vrules) -> dict:
    """Body rules and column intervals of one sheet."""
    width = page.rect.width
    full = sorted({y for y, x0, x1 in hrules if x1 - x0 > 0.8 * width})
    if not full:
        raise ValueError("no full-width rules - not an ODOT log sheet (or a scan)")
    header_rule = full[0]
    inner = [y for y in full if header_rule < y <= header_rule + 40]
    body_top = max(inner) if inner else header_rule + 21.6
    # the column rules run from the column header to the bottom of the logged depth - the full 30 ft on a
    # deep hole, a few feet on a shallow subgrade boring (the sheet below them is blank or holds notes)
    long_v = [(x, y0, y1) for x, y0, y1 in vrules if y1 - y0 > 40 and header_rule - 2 <= y0 <= body_top + 2]
    body_bottom = max((y1 for _, _, y1 in long_v), default=body_top + FT_PER_PAGE * PT_PER_FT)
    xs = sorted({x for x, _, _ in long_v})
    left = min((x0 for y, x0, x1 in hrules if x1 - x0 > 0.8 * width), default=28.8)
    right = max((x1 for y, x0, x1 in hrules if x1 - x0 > 0.8 * width), default=748.8)
    bounds = sorted({left, right, *xs})
    cols = {}
    labels = [w for w in words if body_top - 26 < w["yc"] < body_top and w["text"].upper() in COLUMN_LABELS]
    for w in labels:
        key = COLUMN_LABELS[w["text"].upper()]
        if key in cols:
            continue
        for a, b in zip(bounds, bounds[1:]):
            if a <= w["xc"] < b:
                cols[key] = (a, b)
                break
    for key, iv in DEFAULT_COLUMNS.items():
        cols.setdefault(key, iv)
    if "depths" in cols and "spt" in cols:
        cols["scale"] = (cols["depths"][1], cols["spt"][0])
    cols["description"] = (left, cols["description"][1])
    header_cells = sorted({x for x, y0, y1 in vrules if y1 <= body_top and 15 < y1 - y0 < 70})
    return {"header_rule": header_rule, "body_top": body_top, "body_bottom": body_bottom, "columns": cols,
            "header_cells": header_cells or [190.8, 388.8, 525.6, 712.8], "right": right}


def _in(col, w) -> bool:
    return col[0] <= w["xc"] < col[1]


def _rows(words, tol: float = 2.5):
    """Group words into text rows by vertical centre."""
    rows = []
    for w in sorted(words, key=lambda w: (w["yc"], w["x0"])):
        if rows and abs(rows[-1][0] - w["yc"]) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([w["yc"], [w]])
    return [(yc, sorted(ws, key=lambda w: w["x0"])) for yc, ws in rows]


# ---------------------------------------------------------------------- header


def _split_colon(words):
    """``OPERATOR:DLZ`` -> ``OPERATOR:`` + ``DLZ`` so labels end at the colon."""
    out = []
    for w in words:
        t = w["text"]
        if ":" in t[:-1] and not t.startswith("http"):
            a, b = t.split(":", 1)
            cut = w["x0"] + (w["x1"] - w["x0"]) * (len(a) + 1) / max(len(t), 1)
            out.append({**w, "text": a + ":", "x1": cut, "xc": 0.5 * (w["x0"] + cut)})
            out.append({**w, "text": b, "x0": cut, "xc": 0.5 * (cut + w["x1"])})
        else:
            out.append(w)
    return out


def _parse_header(words, geo) -> dict:
    hw = _split_colon([w for w in words if w["y1"] <= geo["header_rule"] + 1])
    id_label = [w for w in hw if w["text"].upper() == "EXPLORATION"]
    box_left = id_label[0]["x0"] - 4 if id_label else None
    rows = _rows(hw, tol=3.0)
    cells = geo["header_cells"] + [geo["right"]]
    labels_by_len = sorted(HEADER_LABELS, key=lambda s: -len(s.split()))
    raw, below = {}, []
    for ri, (yc, ws) in enumerate(rows):
        i = 0
        while i < len(ws):
            hit = None
            for lab in labels_by_len:
                n = len(lab.split())
                if i + n <= len(ws) and " ".join(w["text"].upper() for w in ws[i:i + n]) == lab:
                    hit = lab
                    break
            if hit is None:
                i += 1
                continue
            n = len(hit.split())
            x_label = ws[i]["x0"]
            cell_right = next((c for c in cells if c > x_label + 1), geo["right"])
            j = i + n
            vals = []
            in_box = box_left is not None and x_label >= box_left
            limit = cell_right if hit not in ("PG",) else geo["right"]
            if box_left is not None and not in_box:
                limit = min(limit, box_left)
            while j < len(ws) and ws[j]["x0"] < limit - 1:
                nxt = None
                for lab in labels_by_len:
                    m_ = len(lab.split())
                    if j + m_ <= len(ws) and " ".join(w["text"].upper() for w in ws[j:j + m_]) == lab:
                        nxt = lab
                        break
                if nxt:
                    break
                vals.append(ws[j]["text"])
                j += 1
            if hit in _BELOW_LABELS and not vals:
                below.append((hit, ri, ws[i]["x0"] - 20, cell_right))
            else:
                raw[hit] = " ".join(vals).strip()
            i = j
    for lab, ri, xa, xb in below:
        if ri + 1 < len(rows):
            vals = [w["text"] for w in rows[ri + 1][1] if xa <= w["x0"] < xb]
            raw[lab] = " ".join(vals).strip()
    if not raw.get("EXPLORATION ID"):
        # continuation sheets print the id alone at the right of the first row
        ids = [w for w in hw if w["x0"] > geo["right"] - 90 and _ID_PATTERN.match(w["text"])]
        if ids:
            raw["EXPLORATION ID"] = ids[0]["text"]
    if raw.get("PG") and not raw.get("PAGE"):
        raw["PAGE"] = raw.pop("PG")
    return raw


def _typed_header(raw: dict) -> LogHeader:
    h = LogHeader(exploration_id=raw.get("EXPLORATION ID", "").strip() or "UNKNOWN", raw=raw)
    h.ground_elevation_ft = _float(raw.get("ELEVATION:"))
    h.eob_ft = _float(raw.get("EOB:"))
    so = raw.get("STATION / OFFSET:", "")
    if so:
        parts = [p.strip() for p in so.split(",", 1)]
        h.station = parts[0] or None
        if len(parts) > 1:
            h.offset_ft = _float(parts[1])
            m = re.search(r"\b(LT|RT|L|R)\b", parts[1].upper())
            h.offset_direction = {"L": "LT", "R": "RT"}.get(m.group(1), m.group(1)) if m else None
    ll = raw.get("LAT / LONG:", "")
    nums = re.findall(r"-?\d+\.\d+", ll)
    if len(nums) >= 2:
        lat, lon = float(nums[0]), float(nums[1])
        if "S" in ll.upper().replace("LAT", "").split(",")[0][-3:]:
            lat = -abs(lat)
        if "W" in ll.upper() and lon > 0:
            lon = -lon
        h.latitude, h.longitude = lat, lon
    h.start, h.end = raw.get("START:") or None, raw.get("END:") or None
    h.pid = raw.get("PID:") or None
    h.project = raw.get("PROJECT:") or None
    h.alignment = raw.get("ALIGNMENT:") or None
    h.type = raw.get("TYPE:") or None
    h.sfn = raw.get("SFN:") or raw.get("BR ID:") or None
    h.hammer = raw.get("HAMMER:") or None
    h.energy_ratio_pct = _float(raw.get("ENERGY RATIO (%):"))
    h.drilling_method = raw.get("DRILLING METHOD:") or None
    h.sampling_method = raw.get("SAMPLING METHOD:") or None
    m = re.search(r"(\d+)\s*OF\s*(\d+)", raw.get("PAGE", "").upper())
    if m:
        h.page, h.pages = int(m.group(1)), int(m.group(2))
    return h


# ---------------------------------------------------------------------- body


def _scale(words, geo, page_index_in_hole: int, anchors=()):
    """depth(y): the slope from the printed tick numbers (least squares, the
    sheet constant when a page prints fewer than two), the offset from the
    elevation-labelled boundary lines (``anchors`` = (y, depth) pairs) when
    the sheet gives them, else from the ticks."""
    col = geo["columns"]["scale"]
    pts = [(w["yc"], int(w["text"])) for w in words
           if _in(col, w) and re.fullmatch(r"\d{1,3}", w["text"]) and geo["body_top"] < w["yc"] < geo["body_bottom"]]
    a = 1.0 / PT_PER_FT
    b = page_index_in_hole * FT_PER_PAGE - geo["body_top"] * a
    if len(pts) >= 2:
        n = len(pts)
        sy = sum(p[0] for p in pts)
        sd = sum(p[1] for p in pts)
        syy = sum(p[0] ** 2 for p in pts)
        syd = sum(p[0] * p[1] for p in pts)
        den = n * syy - sy * sy
        if den:
            a_fit = (n * syd - sy * sd) / den
            if 0.8 / PT_PER_FT < a_fit < 1.25 / PT_PER_FT:
                a = a_fit
                b = (sd - a * sy) / n
    offs = sorted(d - a * y for y, d in anchors)
    if offs:
        b = offs[len(offs) // 2]
    return lambda y: a * y + b


def _parse_page(page, page_index_in_hole: int, ground: float | None) -> dict:
    words = _words(page)
    hrules, vrules = _rules(page)
    geo = _geometry(page, words, hrules, vrules)
    cols = geo["columns"]
    top, bottom = geo["body_top"], geo["body_bottom"]
    body = [w for w in words if top - 1 < w["yc"] < bottom + 1]
    warnings = []

    # layer boundaries: lines across the description column (not the full-width rules)
    d0, d1 = cols["description"]
    bounds = sorted({y for y, x0, x1 in hrules if x0 <= d0 + 2 and x1 >= d1 - 2 and x1 < d1 + 30 and top + 1 < y < bottom - 1})
    # elevation labels sit just above their boundary line
    elev_words = [w for w in body if _in(cols["elev"], w) and _NUM.match(w["text"])]
    elev_at = {}
    for y in bounds:
        near = [w for w in elev_words if -2 <= y - w["y1"] <= 8]
        if near:
            elev_at[y] = float(min(near, key=lambda w: abs(y - w["y1"]))["text"])
    anchors = [(y, ground - e) for y, e in elev_at.items()] if ground is not None else []
    depth = _scale(words, geo, page_index_in_hole, anchors)
    segs = [top, *bounds, bottom]
    desc_rows = _rows([w for w in body if _in(cols["description"], w)])
    layers = []
    for a, b in zip(segs, segs[1:]):
        lines = [" ".join(w["text"] for w in ws) for yc, ws in desc_rows if a - 1 <= yc < b - 1]
        main, notes = [], []
        for ln in lines:
            (notes if ln.startswith("@") else main).append(ln)
        d_top = depth(a) if a == top else (ground - elev_at[a] if ground is not None and a in elev_at else depth(a))
        d_bot = depth(b) if b == bottom else (ground - elev_at[b] if ground is not None and b in elev_at else depth(b))
        if page_index_in_hole == 0 and a == top:
            d_top = 0.0
        layers.append({"y_top": a, "y_bottom": b, "depth_top_ft": _snap(d_top), "depth_bottom_ft": _snap(d_bot),
                       "description": " ".join(main).strip(), "notes": notes,
                       "elevation_top_ft": elev_at.get(a), "at_page_top": a == top, "at_page_bottom": b == bottom})

    # depths column: water elevations, top of rock, EOB
    water, rock, eob_y = [], None, None
    for w in body:
        if not _in(cols["depths"], w):
            continue
        t = w["text"].upper()
        if t == "TR":
            rock = _snap(depth(w["yc"]))
        elif t == "EOB":
            eob_y = w["yc"]
        elif _NUM.match(w["text"]):
            e = float(w["text"])
            water.append({"elevation_ft": e, "depth_ft": round(ground - e, 2) if ground is not None else round(depth(w["yc"]), 2)})

    # samples: bars across the sample column bracket each id
    s0, s1 = cols["sample"]
    bars = sorted({y for y, x0, x1 in hrules if x0 <= s0 + 2 and x1 >= s1 - 2 and x1 < s1 + 30 and top < y <= bottom + 1} | {top})
    ids = [w for w in body if _in(cols["sample"], w) and re.match(r"^[A-Z]{1,4}\d?-\d+[A-Z]?$", w["text"])]
    rows = []
    spans = {}
    for w in ids:
        above = [y for y in bars if y <= w["yc"] + 1]
        below = [y for y in bars if y > w["yc"] + 1]
        if not above or not below:
            warnings.append(f"{w['text']}: no sample bar on the sheet - interval from the sheet scale")
            ya, yb = w["yc"] - 0.75 * PT_PER_FT, w["yc"] + 0.75 * PT_PER_FT
        else:
            ya, yb = above[-1], below[0]
        spans.setdefault((ya, yb), []).append(w)
    bounds_of = {}
    for (ya, yb), ws in spans.items():
        ws.sort(key=lambda w: w["yc"])
        if len(ws) == 1:
            bounds_of[ws[0]["text"]] = (ya, yb)
            continue
        # two ids in one bar (a split spoon logged as A / B): divide at the midpoints between the labels
        cuts = [ya] + [0.5 * (p["yc"] + q["yc"]) for p, q in zip(ws, ws[1:])] + [yb]
        for w, a, b in zip(ws, cuts, cuts[1:]):
            bounds_of[w["text"]] = (a, b)
    for w in ids:
        ya, yb = bounds_of[w["text"]]
        method = re.match(r"^([A-Z]{1,4}\d?)-", w["text"]).group(1)
        row = SampleRow(sample_id=w["text"], depth_top_ft=_snap(depth(ya)), depth_bottom_ft=_snap(depth(yb)), method=method)
        same = [v for v in body if abs(v["yc"] - w["yc"]) <= 4.5 and not _in(cols["sample"], v)]
        vals = {}
        for k in VALUE_COLUMNS:
            got = [v["text"] for v in same if _in(cols[k], v)]
            vals[k] = " ".join(got) if got else None
        row.n60 = _float(vals["n60"])
        row.rec_pct = _float(vals["rec"])
        row.hp_text = vals["hp"] if vals["hp"] not in (None, "-") else None
        row.hp_tsf = _float(vals["hp"])
        frac = {k: _float(vals[k]) for k in ("gr", "cs", "fs", "si", "cl")}
        row.gradation = frac if any(v is not None for v in frac.values()) else None
        row.ll, row.pl, row.pi, row.wc = (_float(vals[k]) for k in ("ll", "pl", "pi", "wc"))
        cls = [v["text"] for v in same if _in(cols["cls"], v)]
        for t in cls:
            m = re.fullmatch(r"\((\w+)\)", t)
            if m:
                row.group_index = m.group(1)
            else:
                row.odot_class = (row.odot_class + " " + t) if row.odot_class else t
        blow_words = sorted([v for v in body if _in(cols["spt"], v) and ya - 1.5 <= v["yc"] <= yb + 1.5], key=lambda v: v["yc"])
        if row.is_core:
            nums = [v["text"] for v in blow_words if _NUM.match(v["text"])]
            row.rqd_pct = float(nums[0]) if nums else None
        else:
            row.blows = tuple(v["text"] for v in blow_words if v["text"] != "-")
        rows.append(row)
    rows.sort(key=lambda r: r.depth_top_ft)
    return {"layers": layers, "samples": rows, "water": water, "top_of_rock_ft": None if rock is None else round(rock, 2),
            "eob_depth_ft": None if eob_y is None else round(depth(eob_y), 2), "warnings": warnings}


# ---------------------------------------------------------------------- holes


def _page_header(page) -> LogHeader | None:
    words = _words(page)
    hrules, vrules = _rules(page)
    try:
        geo = _geometry(page, words, hrules, vrules)
    except ValueError:
        return None
    return _typed_header(_parse_header(words, geo))


def read_log_pdf(path, *, pages=None, hole_ids=None) -> list[BoringLog]:
    """Every ODOT log sheet in ``path`` (a report or a bare log), grouped
    into holes by exploration id and page number.  ``pages`` limits the
    scan (0-based); ``hole_ids`` keeps only those explorations."""
    import fitz  # PyMuPDF

    path = Path(path)
    doc = fitz.open(str(path))
    sheets: dict[str, list] = {}
    for i in (pages if pages is not None else range(len(doc))):
        page = doc[i]
        if not is_odot_log_page(page):
            continue
        h = _page_header(page)
        if h is None or h.exploration_id == "UNKNOWN":
            continue
        if hole_ids and h.exploration_id not in hole_ids:
            continue
        key = h.exploration_id
        if h.page == 1 and key in sheets and any(pg == 1 for pg, _, _ in sheets[key]):
            n = 2
            while f"{key} #{n}" in sheets:
                n += 1
            key = f"{key} #{n}"
        elif h.page > 1:
            # a continuation belongs to the latest hole of that id
            later = [k for k in sheets if k == key or k.startswith(key + " #")]
            if later:
                key = later[-1]
        sheets.setdefault(key, []).append((h.page, i, h))
    logs = []
    for hid, items in sheets.items():
        items.sort(key=lambda t: (t[0], t[1]))
        head = items[0][2]
        log = BoringLog(header=head, pages=[i for _, i, _ in items], source=str(path))
        prev_bottom = None
        for k, (pno, i, h) in enumerate(items):
            if k > 0 and pno == items[k - 1][0]:
                log.warnings.append(f"page {i + 1}: duplicate sheet page {pno} skipped")
                continue
            res = _parse_page(doc[i], pno - 1 if pno else k, head.ground_elevation_ft)
            log.warnings += [f"page {i + 1}: {w}" for w in res["warnings"]]
            for lay in res["layers"]:
                desc = lay["description"]
                continued = re.search(r"\(continued\)\s*$", desc, flags=re.I) is not None
                if lay["at_page_top"] and log.layers and (not desc or continued):
                    log.layers[-1].depth_bottom_ft = lay["depth_bottom_ft"]
                    log.layers[-1].notes += lay["notes"]
                    continue
                if lay["at_page_top"] and log.layers:
                    lay["depth_top_ft"] = log.layers[-1].depth_bottom_ft
                if not desc and not lay["notes"] and lay["at_page_bottom"] and log.layers:
                    # nothing logged below the last boundary on this page (EOB or blank tail)
                    continue
                d_top = lay["depth_top_ft"]
                # "Topsoil - 7\"" / "Asphalt - 6\"" printed inside a segment without a boundary line of their own
                while True:
                    m = _PSEUDO.match(desc)
                    if not m:
                        break
                    thick = float(m.group(2)) / 12.0
                    first = d_top == lay["depth_top_ft"]
                    log.layers.append(LogLayer(d_top, round(d_top + thick, 2), desc[:m.end()].strip(), [],
                                               lay["elevation_top_ft"] if first else None))
                    d_top = round(d_top + thick, 2)
                    desc = desc[m.end():].strip()
                if d_top != lay["depth_top_ft"] and not desc and abs(d_top - lay["depth_bottom_ft"]) <= 0.15:
                    # the printed thicknesses fill the segment: close the last one on the drawn boundary
                    log.layers[-1].depth_bottom_ft = lay["depth_bottom_ft"]
                    d_top = lay["depth_bottom_ft"]
                if desc or lay["notes"] or d_top == lay["depth_top_ft"]:
                    log.layers.append(LogLayer(d_top, lay["depth_bottom_ft"], desc, lay["notes"],
                                               lay["elevation_top_ft"] if d_top == lay["depth_top_ft"] else None))
            log.samples += res["samples"]
            log.water += res["water"]
            if res["top_of_rock_ft"] is not None and log.top_of_rock_ft is None:
                log.top_of_rock_ft = res["top_of_rock_ft"]
            if res["eob_depth_ft"] is not None:
                prev_bottom = res["eob_depth_ft"]
        eob = head.eob_ft if head.eob_ft is not None else prev_bottom
        if log.layers and eob is not None:
            log.layers[-1].depth_bottom_ft = round(eob, 2)
            log.layers = [lay for lay in log.layers if lay.depth_bottom_ft > lay.depth_top_ft + 0.01 or lay.description]
        log.samples.sort(key=lambda r: r.depth_top_ft)
        if log.top_of_rock_ft is not None:
            # the TR marker sits at a sample top or a layer boundary; take that depth when one is within 0.3 ft
            marks = [r.depth_top_ft for r in log.samples] + [lay.depth_top_ft for lay in log.layers]
            near = [d for d in marks if abs(d - log.top_of_rock_ft) <= 0.3]
            if near:
                log.top_of_rock_ft = min(near, key=lambda d: abs(d - log.top_of_rock_ft))
        if not log.layers:
            log.warnings.append("no layers read from the description column")
        logs.append(log)
    return logs


def read_boreholes(path, **kw) -> list[Borehole]:
    """:func:`read_log_pdf` as canonical boreholes."""
    return [log.to_borehole() for log in read_log_pdf(path, **kw)]
