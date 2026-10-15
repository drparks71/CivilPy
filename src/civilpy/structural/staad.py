#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Read a STAAD.Pro ``.std`` input deck and translate it to MIDAS Civil NX.

:func:`read_std` parses the plain-text command file STAAD writes (joints,
members, supports, releases, user tables, member properties, master/slave
links, groups, static load cases and combinations) into a
:class:`StaadModel`.  :func:`to_midas` turns that into the ``{table:
{id: {...}}}`` assign bodies for ``MidasCivil.put_db``, so an archived
STAAD frame can be re-run in Civil NX with STAAD's own joint and member
numbers.

Conventions
-----------
STAAD decks here are **Y-up**; MIDAS is **Z-up**.  The mapping is the
right-handed rotation ``(X, Y, Z)_staad -> (X, -Z, Y)_midas``: MIDAS X =
STAAD X, MIDAS Y = -STAAD Z, MIDAS Z = STAAD Y.  Under that rotation the
default member axes line up (STAAD local y and MIDAS local z both lie in the
vertical plane through the member), so

* STAAD ``IZ`` (about local z) -> MIDAS ``RYY``; STAAD ``IY`` -> ``RZZ``;
* STAAD shear area ``AY`` -> MIDAS ``ASZ``; ``AZ`` -> ``ASY``;
* releases/loads: STAAD local ``MY`` <-> MIDAS ``Mz``, ``MZ`` <-> ``My``.

User-table GENERAL property order (STAAD TR.19.8): ``AX D TD B TB IZ IY IX
SZ SY AY AZ PZ PY HSS DEE``.  ISECTION (TR.19.9): ``DWW TWW DWW1 BFF TFF BFF1
TFF1 AYF AZF XIF`` with DWW the overall depth at the start node.

Every user-table section is sent as a MIDAS **value** section (``SECTTYPE
"VALUE"``, ``SHAPE "GEN"``, ``CALC_STIFF_OPT 0``) carrying STAAD's own
numbers -- the table *is* the structural record, so nothing is recomputed
from plate sizes.  AISC catalog shapes (``TABLE ST/RA/LD ...``) are computed
from the AISC shape table bundled with civilpy.  A tapered ISECTION (DWW !=
DWW1) is sent as the prismatic section at mid-depth: same weight, same
average axial stiffness; its flexural stiffness is approximate.

Not translated (reported in :attr:`StaadModel.skipped`): moving loads and
``LOAD GENERATION``, design/analysis commands, and any member or joint load
type outside UNI/CON and FX..MZ.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["StaadModel", "Section", "LoadCase", "read_std", "to_midas",
           "staad_to_midas_xyz", "expand_list", "logical_lines"]

_IN = {"INCH": 1 / 12, "INCHES": 1 / 12, "IN": 1 / 12, "FEET": 1.0, "FT": 1.0, "FOOT": 1.0,
       "MM": 1 / 304.8, "CM": 1 / 30.48, "METER": 1 / 0.3048, "METERS": 1 / 0.3048, "M": 1 / 0.3048}
_FORCE = {"KIP": 1.0, "KIPS": 1.0, "POUND": 1e-3, "LBS": 1e-3, "LB": 1e-3,
          "KN": 1 / 4.4482216, "NEWTON": 1 / 4448.2216, "KG": 2.20462e-3, "MTON": 2.20462}


# ----------------------------------------------------------------- data model
@dataclass
class Section:
    """One cross-section in feet (properties ``ft^2`` / ``ft^4``).

    Axis names are STAAD's: ``iz`` about local z (the in-plane, major axis of
    a horizontal member), ``iy`` about local y, ``ay`` shear area along local y.
    """
    name: str
    ax: float
    iz: float
    iy: float
    ix: float
    ay: float = 0.0
    az: float = 0.0
    d: float = 0.0
    b: float = 0.0
    source: str = ""


@dataclass
class LoadCase:
    number: int
    title: str = ""
    loadtype: str = ""
    units: str = "FEET KIP"                     # STAAD UNIT in force when the case was read
    selfweight: tuple | None = None             # (direction, factor)
    joint: list = field(default_factory=list)   # (joint, {FX: v, ...})
    member: list = field(default_factory=list)  # (member, kind, dir, w, d1, d2)
    combination: list = field(default_factory=list)  # (case, factor)
    other: list = field(default_factory=list)

    @property
    def is_combination(self) -> bool:
        return bool(self.combination) and not (self.joint or self.member or self.selfweight)


@dataclass
class StaadModel:
    """Everything :func:`read_std` understood, in **kip / ft** units."""
    joints: dict = field(default_factory=dict)       # id -> (x, y, z) STAAD axes
    members: dict = field(default_factory=dict)      # id -> (i, j)
    supports: dict = field(default_factory=dict)     # joint -> set of fixed STAAD dofs
    releases: dict = field(default_factory=dict)     # member -> {"START": set, "END": set}
    beta: dict = field(default_factory=dict)         # member -> degrees
    sections: dict = field(default_factory=dict)     # key -> Section
    member_section: dict = field(default_factory=dict)  # member -> section key
    material: dict = field(default_factory=dict)     # E (ksf), POISSON, DENSITY (kcf), ALPHA
    slaves: list = field(default_factory=list)       # (master, dofs, [slaves])
    groups: dict = field(default_factory=dict)       # name -> ("MEMBER"|"JOINT", [ids])
    loads: list = field(default_factory=list)        # LoadCase
    job: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)      # human-readable notes

    def length(self, member: int) -> float:
        i, j = self.members[member]
        return math.dist(self.joints[i], self.joints[j])


# ----------------------------------------------------------------- tokenizing
def logical_lines(text: str):
    """Yield STAAD commands: comments (``*``) dropped, ``-`` continuations
    joined, ``;`` separated commands split."""
    buf = ""
    for raw in text.splitlines():
        line = raw.split("!")[0].rstrip() if "!" in raw else raw.rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if re.search(r"(^|\s)-$", line):
            buf += line[:-1].rstrip() + " "
            continue
        buf += line
        for part in buf.split(";"):
            if part.strip():
                yield part.strip()
        buf = ""
    if buf.strip():
        yield buf.strip()


def expand_list(tokens) -> list[int]:
    """Expand a STAAD id list: ``1 TO 5 BY 2 9`` -> ``[1, 3, 5, 9]``."""
    out, i, tokens = [], 0, list(tokens)
    while i < len(tokens):
        t = tokens[i]
        if i + 2 < len(tokens) and tokens[i + 1].upper() == "TO":
            a, b, step = int(t), int(tokens[i + 2]), 1
            i += 3
            if i + 1 < len(tokens) and tokens[i].upper() == "BY":
                step = int(tokens[i + 1])
                i += 2
            out.extend(range(a, b + 1, step))
        else:
            out.append(int(t))
            i += 1
    return out


def _split_ids(tok):
    """Leading id list (digits / TO / BY) and the remaining words."""
    k = 0
    while k < len(tok) and (tok[k].isdigit() or tok[k].upper() in ("TO", "BY")):
        k += 1
    return expand_list(tok[:k]), tok[k:]


def _num(s: str) -> float:
    return float(s)


# ----------------------------------------------------------------- AISC shapes
def _aisc_row(label: str):
    from civilpy.structural.steel import steel_tables
    rows = steel_tables[steel_tables["EDI_Std_Nomenclature"] == label]
    if rows.empty:
        raise KeyError(f"AISC shape {label!r} not in civilpy's shape table")
    return rows.iloc[0]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def staad_angle_label(code: str) -> str:
    """STAAD angle code -> AISC label: ``L40355`` -> ``L4X3-1/2X5/16``
    (two digits per leg in tenths of an inch, last digits thickness in
    sixteenths)."""
    m = re.fullmatch(r"L(\d\d)(\d\d)(\d{1,2})", code.upper())
    if not m:
        raise ValueError(f"not a STAAD angle code: {code}")

    def inches(tenths):
        v = int(tenths) / 10
        whole, frac = int(v), v - int(v)
        if abs(frac) < 1e-9:
            return f"{whole}"
        from fractions import Fraction
        return f"{whole}-{Fraction(frac).limit_denominator(16)}" if whole else f"{Fraction(frac).limit_denominator(16)}"

    from fractions import Fraction
    t = Fraction(int(m.group(3)), 16)
    t_txt = f"{t.numerator}/{t.denominator}" if t.denominator != 1 else f"{t.numerator}"
    return f"L{inches(m.group(1))}X{inches(m.group(2))}X{t_txt}"


def catalog_section(kind: str, code: str, spacing_in: float = 0.0) -> Section:
    """A STAAD catalog shape as a :class:`Section` in ft units.

    ``kind`` is STAAD's specification word: ``ST`` (single), ``RA`` (single
    angle with local y/z swapped), ``LD`` (double angle, long legs back to
    back, ``SP`` = gap in inches), ``SD`` (short legs back to back).
    Single angles use the AISC *geometric* axes (``Ix``/``Iy``) -- the
    orientation of bracing angles barely affects truss forces.
    """
    kind = kind.upper()
    if code.upper().startswith("L") and code[1].isdigit() and "X" not in code.upper():
        label = staad_angle_label(code)
    else:
        label = code.upper()
    r = _aisc_row(label)
    A, Ix, Iy, J = _f(r["A"]), _f(r["Ix"]), _f(r["Iy"]), _f(r["J"])
    if label.startswith("L"):
        long_leg, short_leg = max(_f(r["b"]), _f(r["d"])), min(_f(r["b"]), _f(r["d"]))
        t = _f(r["t"])
        x_bar = _f(r["x"])                      # centroid to back of long leg
        if kind in ("LD", "SD"):
            s = spacing_in
            if kind == "LD":
                iz, iy = 2 * Ix, 2 * (Iy + A * (x_bar + s / 2) ** 2)
                d, b = long_leg, 2 * short_leg + s
            else:
                y_bar = _f(r["y"])
                iz, iy = 2 * Iy, 2 * (Ix + A * (y_bar + s / 2) ** 2)
                d, b = short_leg, 2 * long_leg + s
            sec = Section(f"{kind} {label} SP{s:g}", 2 * A, iz, iy, 2 * J,
                          ay=2 * d * t, az=2 * (b - s) / 2 * t, d=d, b=b, source=f"AISC {label}")
        else:
            iz, iy = (Iy, Ix) if kind == "RA" else (Ix, Iy)
            sec = Section(f"{kind} {label}", A, iz, iy, J, ay=long_leg * t, az=short_leg * t,
                          d=long_leg, b=short_leg, source=f"AISC {label}")
    else:                                         # W / S / C / HP: strong axis in plane
        d, bf, tw, tf = _f(r["d"]), _f(r["bf"]), _f(r["tw"]), _f(r["tf"])
        sec = Section(label, A, Ix, Iy, J, ay=d * tw, az=2 * bf * tf * 5 / 6, d=d, b=bf,
                      source=f"AISC {label}")
    return _scale_section(sec, 1 / 12)


def _scale_section(s: Section, k: float) -> Section:
    """Convert a section from length unit L to L*k (``k=1/12``: inches -> feet)."""
    return Section(s.name, s.ax * k ** 2, s.iz * k ** 4, s.iy * k ** 4, s.ix * k ** 4,
                   s.ay * k ** 2, s.az * k ** 2, s.d * k, s.b * k, s.source)


def _general_section(name, vals, k) -> Section:
    v = list(vals) + [0.0] * (16 - len(vals))
    ax, d, td, b, tb, iz, iy, ix, sz, sy, ay, az = v[:12]
    return _scale_section(Section(name, ax, iz, iy, ix, ay, az, d, b, "GENERAL"), k)


def _isection(name, vals, k) -> Section:
    v = list(vals) + [0.0] * (10 - len(vals))
    d0, tw, d1, bt, tt, bb, tbt, ayf, azf, xif = v[:10]
    d = (d0 + d1) / 2 if d1 else d0             # tapered -> mid-depth prism
    hw = d - tt - tbt
    A = hw * tw + bt * tt + bb * tbt
    yb = (bb * tbt * tbt / 2 + hw * tw * (tbt + hw / 2) + bt * tt * (d - tt / 2)) / A
    iz = (bb * tbt ** 3 / 12 + bb * tbt * (yb - tbt / 2) ** 2
          + tw * hw ** 3 / 12 + hw * tw * (tbt + hw / 2 - yb) ** 2
          + bt * tt ** 3 / 12 + bt * tt * (d - tt / 2 - yb) ** 2)
    iy = (tt * bt ** 3 + tbt * bb ** 3 + hw * tw ** 3) / 12
    ix = xif if xif > 0 else (bt * tt ** 3 + bb * tbt ** 3 + hw * tw ** 3) / 3
    ay = ayf if ayf > 0 else d * tw
    az = azf if azf > 0 else (bt * tt + bb * tbt) * 5 / 6
    src = "ISECTION" + (f" tapered {d0:g}->{d1:g} (mid-depth)" if d1 and abs(d1 - d0) > 1e-9 else "")
    return _scale_section(Section(name, A, iz, iy, ix, ay, az, d, max(bt, bb), src), k)


# ----------------------------------------------------------------- reader
def read_std(path_or_text) -> StaadModel:
    """Parse a STAAD ``.std`` deck (path or the text itself) into a
    :class:`StaadModel` in kip/ft."""
    text = (Path(path_or_text).read_text(errors="replace")
            if isinstance(path_or_text, Path) or (isinstance(path_or_text, str) and "\n" not in path_or_text)
            else path_or_text)
    m = StaadModel()
    L, F = 1.0, 1.0                     # current length / force factors to ft / kip
    unit_name = ["FEET", "KIP"]
    sect = None
    table = None
    tables: dict = {}                   # (table, name) -> (kind, values, length factor)
    ttype = None
    pending_name = None
    load: LoadCase | None = None
    lmode = None
    group_kind = None

    for line in logical_lines(text):
        U = line.upper()
        tok = line.split()
        T0 = tok[0].upper()

        if U.startswith("UNIT "):
            for w in tok[1:]:
                w = w.upper()
                if w in _IN:
                    L, unit_name[0] = _IN[w], w
                elif w in _FORCE:
                    F, unit_name[1] = _FORCE[w], w
            continue
        if U.startswith(("ENGINEER ", "JOB ")):
            m.job[" ".join(tok[:2]).upper()] = " ".join(tok[2:])
            continue
        if U in ("STAAD SPACE", "START JOB INFORMATION", "END JOB INFORMATION") or U.startswith(("STAAD ", "INPUT ", "SET ")):
            continue
        if U.startswith("JOINT COORD"):
            sect = "joints"; continue
        if U.startswith("MEMBER INCI"):
            sect = "members"; continue
        if U.startswith("SUPPORT"):
            sect = "supports"; continue
        if U.startswith("MEMBER RELEASE"):
            sect = "release"; continue
        if U.startswith("START USER TABLE"):
            sect = "utable"; continue
        if U.startswith("START GROUP"):
            sect = "group"; continue
        if U.startswith("END GROUP"):
            sect = None; continue
        if U.startswith("DEFINE MATERIAL"):
            sect = "material"; continue
        if U.startswith("END DEFINE MATERIAL"):
            sect = None; continue
        if U.startswith(("MEMBER PROPERTY", "MEMBER PROP")):
            sect = "prop"; continue
        if U.startswith("CONSTANTS"):
            sect = "constants"; continue
        if U.startswith("SLAVE"):
            # SLAVE <dofs> MASTER m JOINT list
            ut = [t.upper() for t in tok]
            mi = ut.index("MASTER")
            ji = ut.index("JOINT") if "JOINT" in ut else len(ut)
            dofs = set(ut[1:mi]) if mi > 1 else {"FX", "FY", "FZ", "MX", "MY", "MZ"}
            if "RIGID" in dofs:
                dofs = {"FX", "FY", "FZ", "MX", "MY", "MZ"}
            m.slaves.append((int(tok[mi + 1]), dofs, expand_list(tok[ji + 1:])))
            continue
        if U.startswith("DEFINE MOVING LOAD"):
            sect = "moving"; m.skipped.append("DEFINE MOVING LOAD (moving loads not translated)"); continue
        if U.startswith("LOAD GENERATION"):
            sect = "loadgen"; m.skipped.append(f"{line} (generated moving-load cases not translated)"); continue
        if U.startswith("LOAD COMB"):
            load = LoadCase(int(tok[2]), " ".join(tok[3:]), "COMB")
            m.loads.append(load); sect, lmode = "comb", None; continue
        if T0 == "LOAD" and len(tok) > 1 and tok[1].isdigit():
            title = line.split("TITLE", 1)[1].strip() if "TITLE" in U else " ".join(tok[2:])
            lt = ""
            if "LOADTYPE" in U:
                lt = tok[[t.upper() for t in tok].index("LOADTYPE") + 1]
            load = LoadCase(int(tok[1]), title, lt, units=" ".join(unit_name))
            m.loads.append(load); sect, lmode = "load", None; continue
        if U.startswith(("PERFORM", "FINISH", "PRINT", "LOAD LIST", "PARAMETER", "CHECK", "SELECT",
                         "DEFINE ENVELOPE", "CHANGE")):
            if U.startswith("FINISH"):
                break
            sect = None; continue

        # ---- section bodies
        if sect == "joints":
            m.joints[int(tok[0])] = tuple(_num(x) * L for x in tok[1:4])
        elif sect == "members":
            m.members[int(tok[0])] = (int(tok[1]), int(tok[2]))
        elif sect == "supports":
            ids, rest = _split_ids(tok)
            spec = [w.upper() for w in rest]
            if spec[:1] == ["PINNED"]:
                fixed = {"FX", "FY", "FZ"}
            elif spec[:1] == ["FIXED"]:
                fixed = {"FX", "FY", "FZ", "MX", "MY", "MZ"}
                if "BUT" in spec:
                    fixed -= set(spec[spec.index("BUT") + 1:])
            else:
                m.skipped.append(f"support '{line}' (springs/inclined not translated)")
                continue
            for j in ids:
                m.supports[j] = fixed
        elif sect == "release":
            ids, rest = _split_ids(tok)
            if not rest:
                continue
            end = rest[0].upper()
            dofs = {w.upper() for w in rest[1:] if w.upper() in ("FX", "FY", "FZ", "MX", "MY", "MZ")}
            ends = ("START", "END") if end not in ("START", "END") else (end,)
            for mm in ids:
                r = m.releases.setdefault(mm, {"START": set(), "END": set()})
                for e in ends:
                    r[e] |= dofs
        elif sect == "utable":
            if T0 == "TABLE":
                table = int(tok[1]); continue
            if T0 == "END":
                sect = None; continue
            if T0 in ("GENERAL", "ISECTION", "WIDE", "ANGLE", "CHANNEL", "TEE", "PIPE", "TUBE", "PRISMATIC", "DOUBLE"):
                ttype = T0; continue
            if re.match(r"^[-+]?[\d.]", tok[0]):
                if pending_name is not None:                    # a row may wrap without '-'
                    tables.setdefault((table, pending_name), [ttype, [], L])[1].extend(float(x) for x in tok)
            else:
                pending_name = tok[0]
        elif sect == "material":
            if T0 in ("E", "POISSON", "DENSITY", "ALPHA", "DAMP"):
                f = {"E": F / L ** 2, "DENSITY": F / L ** 3}.get(T0, 1.0)
                m.material[T0] = _num(tok[1]) * f
        elif sect == "prop":
            ids, rest = _split_ids(tok)
            if not ids or not rest:
                continue
            spec = [w.upper() for w in rest]
            if spec[0] == "UPTABLE":
                key = ("UT", int(rest[1]), rest[2])
                if key not in m.sections:
                    kind, vals, k = tables[(int(rest[1]), rest[2])]
                    m.sections[key] = (_isection if kind == "ISECTION" else _general_section)(rest[2], vals, k)
            elif spec[0] == "TABLE":
                kind, code = spec[1], rest[2]
                sp = float(rest[spec.index("SP") + 1]) * L * 12 if "SP" in spec else 0.0
                key = ("CAT", kind, code.upper(), sp)
                if key not in m.sections:
                    m.sections[key] = catalog_section(kind, code, sp)
            elif spec[0] == "PRIS":
                vals = dict(zip(spec[1::2], (float(x) for x in rest[2::2])))
                key = ("PRIS", tuple(sorted(vals.items())), L)
                if key not in m.sections:
                    yd, zd = vals.get("YD", 0.0), vals.get("ZD", vals.get("YD", 0.0))
                    ax = vals.get("AX", yd * zd)
                    iz = vals.get("IZ", zd * yd ** 3 / 12)
                    iy = vals.get("IY", yd * zd ** 3 / 12)
                    a, b_ = max(yd, zd), min(yd, zd)
                    ix = vals.get("IX", a * b_ ** 3 * (1 / 3 - 0.21 * b_ / a * (1 - b_ ** 4 / (12 * a ** 4))) if a else 0.0)
                    m.sections[key] = _scale_section(Section(f"PRIS {yd:g}x{zd:g}", ax, iz, iy, ix, ax * 5 / 6,
                                                             ax * 5 / 6, yd, zd, "PRISMATIC"), L)
            else:
                m.skipped.append(f"property '{line}' not translated")
                continue
            for mm in ids:
                m.member_section[mm] = key
        elif sect == "constants":
            if T0 == "BETA":
                ang = float(tok[1])
                ids = expand_list([t for t in tok[3:] if t.isdigit() or t.upper() in ("TO", "BY")]) \
                    if len(tok) > 3 and tok[2].upper() == "MEMB" else list(m.members)
                for mm in ids:
                    m.beta[mm] = ang
            elif T0 not in ("MATERIAL", "E", "DENSITY", "POISSON", "ALPHA"):
                m.skipped.append(f"constant '{line}' not translated")
        elif sect == "group":
            if T0 in ("MEMBER", "JOINT", "GEOMETRY"):
                group_kind = "JOINT" if T0 == "JOINT" else "MEMBER"; continue
            if tok[0].startswith("_"):
                m.groups[tok[0]] = (group_kind, expand_list(tok[1:]))
        elif sect == "load":
            if U.startswith("SELFWEIGHT"):
                load.selfweight = (tok[1].upper(), float(tok[2]))
                continue
            if U.startswith("JOINT LOAD"):
                lmode = "joint"; continue
            if U.startswith("MEMBER LOAD"):
                lmode = "member"; continue
            if lmode == "joint":
                ids, rest = _split_ids(tok)
                comp = {}
                for a, b in zip(rest[::2], rest[1::2]):
                    a = a.upper()
                    comp[a] = float(b) * F * (L if a.startswith("M") else 1.0)
                for j in ids:
                    load.joint.append((j, comp))
            elif lmode == "member":
                ids, rest = _split_ids(tok)
                kind, direction = rest[0].upper(), rest[1].upper()
                nums = [float(x) for x in rest[2:]]
                if kind not in ("UNI", "CON"):
                    load.other.append(line); m.skipped.append(f"LOAD {load.number}: '{line}'"); continue
                w = nums[0] * F / (L if kind == "UNI" else 1.0)
                d1 = nums[1] * L if len(nums) > 1 else None
                d2 = nums[2] * L if len(nums) > 2 else None
                for mm in ids:
                    load.member.append((mm, kind, direction, w, d1, d2))
            else:
                load.other.append(line); m.skipped.append(f"LOAD {load.number}: '{line}'")
        elif sect == "comb":
            nums = tok
            for a, b in zip(nums[::2], nums[1::2]):
                load.combination.append((int(a), float(b)))
    return m


# ----------------------------------------------------------------- translator
def staad_to_midas_xyz(p):
    """STAAD Y-up point/vector -> MIDAS Z-up: ``(x, y, z) -> (x, -z, y)``."""
    x, y, z = p
    return (x, -z, y)


# STAAD dof name -> MIDAS (index in DX DY DZ RX RY RZ, sign) for *global* dofs
_GLOBAL = {"FX": (0, 1), "FY": (2, 1), "FZ": (1, -1), "MX": (3, 1), "MY": (5, 1), "MZ": (4, -1)}
# STAAD *local* member dof -> MIDAS local (Fx Fy Fz Mx My Mz) index
_LOCAL = {"FX": 0, "FY": 2, "FZ": 1, "MX": 3, "MY": 5, "MZ": 4}


def _vertical(model, mm, tol=1e-6):
    i, j = model.members[mm]
    a, b = model.joints[i], model.joints[j]
    return abs(a[0] - b[0]) < tol and abs(a[2] - b[2]) < tol


def to_midas(model: StaadModel, *, vertical_beta: float = 0.0, matl_name: str = "STAAD steel",
             load_type: str = "D") -> dict:
    """Assign bodies ``{table: {id: {...}}}`` for a :class:`StaadModel`, in
    KIPS/FT, keeping STAAD's joint and member numbers.

    ``vertical_beta`` is added to the beta of members parallel to the vertical
    axis.  The default 0 is right: checked live (Civil NX 2025) with
    cantilevers carrying unequal IZ/IY, a vertical member at beta 0 bends
    about the same axes as in STAAD, and so do horizontal members along
    either plan axis.  Non-vertical members take the STAAD ``BETA`` unchanged.

    Members released for torsion at **both** ends keep torsion at the end
    (STAAD tolerates a torsion-free member; MIDAS reports it singular).
    Joints whose every connected member end is moment-released get their
    rotations restrained -- they carry no moment either way, and leaving them
    free is a singular stiffness matrix in MIDAS.
    """
    mat = model.material
    out: dict = {"UNIT": {"1": {"FORCE": "KIPS", "DIST": "FT", "HEAT": "BTU", "TEMPER": "F"}}}
    out["MATL"] = {"1": {"TYPE": "USER", "NAME": matl_name, "THMAL_UNIT": "F", "bMASS_DENS": False,
                         "DAMP_RAT": mat.get("DAMP", 0.0),
                         "PARAM": [{"P_TYPE": 2, "ELAST": mat.get("E", 4.176e6), "POISN": mat.get("POISSON", 0.3),
                                    "THERMAL": mat.get("ALPHA", 6.5e-6), "DEN": mat.get("DENSITY", 0.49), "MASS": 0.0}]}}

    # sections
    sect_id, sect = {}, {}
    names = set()
    for n, (key, s) in enumerate(sorted(model.sections.items(), key=lambda kv: str(kv[0])), 1):
        nm = s.name if s.name not in names else f"{s.name} T{key[1]}"
        names.add(nm)
        sect_id[key] = n
        sect[str(n)] = value_section(s, nm)
    out["SECT"] = sect

    out["NODE"] = {str(j): dict(zip("XYZ", (round(c, 6) for c in staad_to_midas_xyz(p))))
                   for j, p in sorted(model.joints.items())}
    elem = {}
    for mm, (i, j) in sorted(model.members.items()):
        if mm not in model.member_section:
            raise ValueError(f"member {mm} has no property")
        ang = model.beta.get(mm, 0.0)
        if _vertical(model, mm):
            up = model.joints[j][1] > model.joints[i][1]
            ang += vertical_beta if up else -vertical_beta
        elem[str(mm)] = {"TYPE": "BEAM", "MATL": 1, "SECT": sect_id[model.member_section[mm]],
                         "NODE": [i, j], "ANGLE": ang}
    out["ELEM"] = elem

    # supports
    cons = {}
    for j, fixed in sorted(model.supports.items()):
        flags = ["0"] * 7
        for d in fixed:
            flags[_GLOBAL[d][0]] = "1"
        cons[str(j)] = {"ITEMS": [{"ID": 1, "GROUP_NAME": "", "CONSTRAINT": "".join(flags)}]}

    # releases
    frls = {}
    full = {"MX", "MY", "MZ"}
    free_end = {}                                     # joint -> [all member ends fully released]
    for mm, (i, j) in model.members.items():
        r = model.releases.get(mm, {"START": set(), "END": set()})
        free_end.setdefault(i, []).append(full <= r["START"])
        free_end.setdefault(j, []).append(full <= r["END"])
    for mm, r in sorted(model.releases.items()):
        if mm not in model.members:
            continue
        s, e = set(r["START"]), set(r["END"])
        if "MX" in s and "MX" in e:
            e.discard("MX")
        fi, fj = ["0"] * 7, ["0"] * 7
        for d in s:
            fi[_LOCAL[d]] = "1"
        for d in e:
            fj[_LOCAL[d]] = "1"
        if "1" in fi or "1" in fj:
            frls[str(mm)] = {"ITEMS": [{"ID": 1, "GROUP_NAME": "", "bVALUE": False, "FLAG_I": "".join(fi),
                                        "VALUE_I": [0] * 7, "FLAG_J": "".join(fj), "VALUE_J": [0] * 7}]}
    for jt, ends in free_end.items():
        if ends and all(ends):
            body = cons.setdefault(str(jt), {"ITEMS": [{"ID": 1, "GROUP_NAME": "", "CONSTRAINT": "0000000"}]})
            f = list(body["ITEMS"][0]["CONSTRAINT"])
            f[3] = f[4] = f[5] = "1"
            body["ITEMS"][0]["CONSTRAINT"] = "".join(f)
    out["CONS"] = cons
    out["FRLS"] = frls

    # master / slave
    rigd = {}
    for master, dofs, slaves in model.slaves:
        flags = ["0"] * 6
        for d in dofs:
            flags[_GLOBAL[d][0]] = "1"
        body = rigd.setdefault(str(master), {"ITEMS": []})
        body["ITEMS"].append({"ID": len(body["ITEMS"]) + 1, "GROUP_NAME": "", "DOF": int("".join(flags)),
                              "S_NODE": [s for s in slaves if s != master]})
    if rigd:
        out["RIGD"] = rigd

    # groups
    if model.groups:
        out["GRUP"] = {str(n): {"NAME": g, "P_TYPE": 0,
                                "N_LIST": ids if kind == "JOINT" else [],
                                "E_LIST": ids if kind != "JOINT" else []}
                       for n, (g, (kind, ids)) in enumerate(model.groups.items(), 1)}

    out.update(midas_loads(model, load_type=load_type))
    return out


def value_section(s: Section, name: str | None = None) -> dict:
    """A MIDAS value section (``SECTTYPE "VALUE"``) carrying ``s``'s numbers;
    the outline is the ``b x d`` box (display only, ``CALC_STIFF_OPT 0``).
    Verified live (Civil NX 2025): inertias are ``RXX/RYY/RZZ`` in ``STIFF``."""
    d = s.d or math.sqrt(12 * s.iz / s.ax) if s.ax else 1.0
    b = s.b or math.sqrt(12 * s.iy / s.ax) if s.ax else 1.0
    hy, hz = b / 2, d / 2
    poly = [{"X": -hy, "Y": -hz}, {"X": hy, "Y": -hz}, {"X": hy, "Y": hz}, {"X": -hy, "Y": hz}, {"X": -hy, "Y": -hz}]
    stiff = {"AREA": s.ax, "ASY": s.az, "ASZ": s.ay, "RXX": s.ix, "RYY": s.iz, "RZZ": s.iy,
             "CYP": hy, "CYM": hy, "CZP": hz, "CZM": hz, "QYB": 0, "QZB": 0,
             "Y": [-hy, hy, hy, -hy], "Z": [hz, hz, -hz, -hz]}
    return {"SECTTYPE": "VALUE", "SECT_NAME": (name or s.name)[:60],
            "SECT_BEFORE": {"OFFSET_PT": "CC", "OFFSET_CENTER": 0, "USER_OFFSET_REF": 0, "HORZ_OFFSET_OPT": 0,
                            "USERDEF_OFFSET_YI": 0, "VERT_OFFSET_OPT": 0, "USERDEF_OFFSET_ZI": 0,
                            "USE_SHEAR_DEFORM": bool(s.ay and s.az), "USE_WARPING_EFFECT": False,
                            "SHAPE": "GEN", "CALC_STIFF_OPT": 0,
                            "SECT_I": {"PERIIN": 0, "PERIOUT": 2 * (b + d), "BUILT_FLAG": 1,
                                       "OUTER_POLYGON": [{"VERTEX": poly}], "INNER_POLYGON": [],
                                       "STIFF": stiff, "DESIGN": {"YBAR": 0, "ZBAR": 0}}}}


def case_name(lc: LoadCase) -> str:
    """MIDAS load-case name: STAAD number + title (unique even when titles repeat)."""
    return f"{lc.number} {lc.title}".strip()[:40]


def midas_loads(model: StaadModel, *, load_type: str = "D") -> dict:
    """STLD / BODF / CNLD / BMLD / LCOM-GEN for the static cases."""
    stld, bodf, cnld, bmld, lcom = {}, {}, {}, {}, {}
    names = {lc.number: case_name(lc) for lc in model.loads}
    n = 0
    for lc in model.loads:
        if lc.is_combination:
            continue
        n += 1
        stld[str(n)] = {"NAME": names[lc.number], "TYPE": load_type, "DESC": f"STAAD LOAD {lc.number} {lc.loadtype}".strip()}
        if lc.selfweight:
            d, f = lc.selfweight
            v = [0.0, 0.0, 0.0]
            idx, sign = _GLOBAL["F" + d[-1]]
            v[idx] = sign * f
            bodf[str(n)] = {"LCNAME": names[lc.number], "GROUP_NAME": "", "FV": v}
        for j, comp in lc.joint:
            if not any(comp.values()):
                continue
            g = [0.0] * 6
            for k, val in comp.items():
                if k in _GLOBAL:
                    idx, sign = _GLOBAL[k]
                    g[idx] += sign * val
            body = cnld.setdefault(str(j), {"ITEMS": []})
            body["ITEMS"].append({"ID": len(body["ITEMS"]) + 1, "LCNAME": names[lc.number], "GROUP_NAME": "",
                                  "FX": g[0], "FY": g[1], "FZ": g[2], "MX": g[3], "MY": g[4], "MZ": g[5]})
        for mm, kind, direction, w, d1, d2 in lc.member:
            if w == 0:                                # MIDAS rejects a zero load; it does nothing anyway
                continue
            mdir, sign = _member_dir(direction)
            Lm = model.length(mm)
            if kind == "UNI":
                a = (d1 or 0.0) / Lm if d1 is not None else 0.0
                b = (d2 / Lm) if d2 is not None else 1.0
                item = {"CMD": "BEAM", "TYPE": "UNILOAD", "D": [a, b, 0, 0], "P": [sign * w, sign * w, 0, 0]}
            else:
                a = (d1 / Lm) if d1 is not None else 0.5
                item = {"CMD": "BEAM", "TYPE": "CONLOAD", "D": [a, 0, 0, 0], "P": [sign * w, 0, 0, 0]}
            body = bmld.setdefault(str(mm), {"ITEMS": []})
            body["ITEMS"].append({"ID": len(body["ITEMS"]) + 1, "LCNAME": names[lc.number], "GROUP_NAME": "",
                                  "DIRECTION": mdir, "USE_PROJECTION": False, "USE_ECCEN": False, **item})
    k = 0
    for lc in model.loads:
        if not lc.is_combination:
            continue
        k += 1
        lcom[str(k)] = {"NAME": names[lc.number][:20], "ACTIVE": "ACTIVE", "iTYPE": 0, "DESC": lc.title,
                        "vCOMB": [{"ANAL": "ST", "LCNAME": names[c], "FACTOR": f} for c, f in lc.combination]}
    out = {"STLD": stld}
    for t, b in (("BODF", bodf), ("CNLD", cnld), ("BMLD", bmld), ("LCOM-GEN", lcom)):
        if b:
            out[t] = b
    return out


def _member_dir(d: str):
    """STAAD member-load direction -> (MIDAS direction, sign)."""
    d = d.upper()
    if d in ("GX", "PX"):
        return "GX", 1
    if d in ("GY", "PY"):
        return "GZ", 1
    if d in ("GZ", "PZ"):
        return "GY", -1
    if d == "X":
        return "LX", 1
    if d == "Y":
        return "LZ", 1
    if d == "Z":
        return "LY", -1
    raise ValueError(f"member load direction {d!r} not supported")


def applied_totals(model: StaadModel, case: int) -> tuple[float, float, float]:
    """Total applied force (STAAD global X, Y, Z) of a primary case, kips --
    the equilibrium check for reactions after a MIDAS run.  Self weight uses
    each member's area x density x length."""
    lc = next(c for c in model.loads if c.number == case)
    tot = [0.0, 0.0, 0.0]
    ax = {"X": 0, "Y": 1, "Z": 2}
    if lc.selfweight:
        d, f = lc.selfweight
        den = model.material.get("DENSITY", 0.49)
        for mm in model.members:
            tot[ax[d[-1]]] += f * den * model.sections[model.member_section[mm]].ax * model.length(mm)
    for _, comp in lc.joint:
        for k, v in comp.items():
            if k in ("FX", "FY", "FZ"):
                tot[ax[k[1]]] += v
    for mm, kind, direction, w, d1, d2 in lc.member:
        g = direction.upper()
        if g not in ("GX", "GY", "GZ"):
            continue
        Lm = model.length(mm)
        tot[ax[g[1]]] += w * (((d2 if d2 is not None else Lm) - (d1 or 0.0)) if kind == "UNI" else 1.0)
    return tuple(tot)
