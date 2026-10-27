#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Payload builders for the bridge model types MIDAS Civil NX is built for.

These are **pure** functions: each returns the ``{id: {...}}`` *assign*
dictionaries the MIDAS API expects, so they can be unit-tested with no live
session and then pushed with
``civilpy.structural.midas.MidasCivil.put_db(table, assign)``.  They cover
the geometries a line-girder framing plan cannot express:

* :func:`curved_girder_model` -- horizontally curved girders, modelled as
  concentric chorded beam lines with optional transverse diaphragms (the
  grid action that makes a curved bridge behave is in the diaphragms).
* :func:`bifurcated_girder_model` -- a girder line that splits at a gore
  node into diverging branches (ramp splits, Y-piers).
* :func:`abutment_connection` -- the super-/substructure connection for
  **integral** (monolithic, moment-continuous via a rigid link) and
  **semi-integral** (girders on bearings, deck continuous) abutments.
* :func:`soil_spring_supports` -- nodal foundation springs from the p-y /
  t-z / q-z stiffnesses in :mod:`civilpy.geotech.lateral_pile` and
  :mod:`civilpy.geotech.axial_load_transfer`, so a pier or integral pile
  bent rests on soil rather than on fixed points.

Table schemas (NODE, ELEM, CONS, FRLS, ELNK, RIGD) follow the
``/db/*`` manual pages.  **The point-spring table name is not yet verified
against a live release** -- :func:`soil_spring_supports` returns the body and
takes the table name as an argument; capture a real one per the live-capture
checklist before relying on it.

Units: geometry in the model's length unit (feet in the civilpy/BrR default
KIPS/FT system); spring stiffnesses are passed through in model units -- use
:func:`lb_per_in_to_kip_per_ft` to convert the geotech curves' lb/in values.
Constraint/release flag strings are DX DY DZ RX RY RZ RW ('1' = fixed for
CONS, '1' = released for FRLS), matching the rest of the API client.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:                                    # avoid an import cycle / hard dep
    from civilpy.structural.structural_model import StructuralModel


def lb_per_in_to_kip_per_ft(k_lb_per_in: float) -> float:
    """Convert a spring constant from lb/in (the geotech curve unit) to
    kip/ft (the KIPS/FT model unit): ``k[kip/ft] = k[lb/in] * 12 / 1000``."""
    return k_lb_per_in * 12.0 / 1000.0


# ===================================================== shared MIDAS encoders
#
# The NODE/ELEM/CONS/UNIT/MATL encodings below are the *single* source of
# those payload fragments: both the hub serializer in
# this module and ``TrussBridge.midas_payloads`` build them here so the two
# Midas exporters cannot drift.

#: A709 Grade 50 steel in KIPS/FT model units (E in ksf, density in kcf) --
#: the structural-steel property block both exporters share.
STEEL_PROPS = {"ELAST": 4_176_000.0, "POISN": 0.3,
               "THERMAL": 6.5e-06, "DEN": 0.490}

#: Map civilpy ``Units`` labels onto the MIDAS ``UNIT`` enum values.
_FORCE_UNIT = {"kips": "KIPS", "kip": "KIPS", "kn": "KN", "n": "N",
               "lbf": "LBF", "tonf": "TONF", "kgf": "KGF"}
_DIST_UNIT = {"ft": "FT", "feet": "FT", "in": "IN", "inch": "IN", "m": "M",
              "mm": "MM", "cm": "CM"}


def unit_block(force: str = "KIPS", dist: str = "FT",
               heat: str = "BTU", temper: str = "F") -> dict:
    """The ``/db/UNIT`` assign body ``{"1": {FORCE, DIST, HEAT, TEMPER}}``."""
    return {"1": {"FORCE": force, "DIST": dist, "HEAT": heat, "TEMPER": temper}}


def unit_block_for(units) -> dict:
    """``unit_block`` from a hub :class:`~civilpy.structural.structural_model.Units`
    (maps the kips/ft labels to the MIDAS enum; unknown labels pass through
    upper-cased)."""
    force = _FORCE_UNIT.get(units.force.lower(), units.force.upper())
    dist = _DIST_UNIT.get(units.length.lower(), units.length.upper())
    return unit_block(force, dist)


def steel_material_block(name: str = "A709-50", *, matl_id: int = 1,
                         props: Optional[dict] = None,
                         length_unit: str = "ft") -> dict:
    """The ``/db/MATL`` assign body for a USER-defined steel material.

    :data:`STEEL_PROPS` is stated in KIPS/FT; ``length_unit`` rescales
    ``ELAST`` (force/length^2) and ``DEN`` (force/length^3) into the
    model's own length unit -- see :func:`concrete_material_block` for why
    that matters.
    """
    props = dict(props or STEEL_PROPS)
    per_ft = _length_ft_per(length_unit)
    if per_ft != 1.0:
        if "ELAST" in props:
            props["ELAST"] = round(props["ELAST"] * per_ft ** 2, 6)
        if "DEN" in props:
            props["DEN"] = round(props["DEN"] * per_ft ** 3, 9)
    return {str(matl_id): {
        "TYPE": "USER", "NAME": name, "THMAL_UNIT": "F",
        "bMASS_DENS": False, "DAMP_RAT": 0.0,
        "PARAM": [{"P_TYPE": 2, "MASS": 0.0, **props}],
    }}


def concrete_elastic_modulus_ksf(fc_psi: float, unit_wt_pcf: float = 145.0) -> float:
    """Concrete elastic modulus in **kips/ft^2** from ``f'c`` (psi).

    AASHTO LRFD 5.4.2.4 / ACI 318:
    ``Ec = 33000 * K1 * (wc/1000)^1.5 * sqrt(f'c)`` with ``wc`` in kcf and
    ``f'c`` in ksi gives ``Ec`` in ksi; convert to ksf (x144) for a model
    whose DIST unit is feet. For ``f'c`` = 4500 psi, ``wc`` = 145 pcf this is
    ~3952 ksi, the value MIDAS should hold for an SB-1-24 slab -- not the
    ~29000 ksi steel modulus ``midas_payloads`` otherwise defaults to.
    """
    wc_kcf = unit_wt_pcf / 1000.0
    fc_ksi = fc_psi / 1000.0
    ec_ksi = 33000.0 * (wc_kcf ** 1.5) * (fc_ksi ** 0.5)
    return ec_ksi * 144.0


def concrete_material_block(name: str = "Class-S-4500", *, matl_id: int = 1,
                            fc_psi: float = 4500.0,
                            unit_wt_pcf: float = 145.0,
                            length_unit: str = "ft") -> dict:
    """A ``/db/MATL`` USER concrete material with ``Ec`` from :func:`concrete_elastic_modulus_ksf`.

    ``ELAST`` and ``DEN`` are carried in the model's own length unit --
    ksf and kcf when ``length_unit`` is ``"ft"``, ksi and kip/in^3 when it
    is ``"in"``.  MIDAS applies one length unit model-wide, so a material
    block built for feet inside an inch model overstates ``Ec`` by 144x
    and the density by 1728x, with nothing in the response to say so:
    pass the hub's ``units.length``.
    """
    per_ft = _length_ft_per(length_unit)
    return {str(matl_id): {
        "TYPE": "USER", "NAME": name, "THMAL_UNIT": "F",
        "bMASS_DENS": False, "DAMP_RAT": 0.0,
        "PARAM": [{"P_TYPE": 2, "MASS": 0.0,
                   "ELAST": round(concrete_elastic_modulus_ksf(fc_psi, unit_wt_pcf)
                                  * per_ft ** 2, 6),
                   "POISN": 0.2, "THERMAL": 6.0e-06,
                   "DEN": round(unit_wt_pcf / 1000.0 * per_ft ** 3, 9)}],
    }}


def time_dependent_material_blocks(name: str, *, matl_id: int, fc_psi: float,
                                   humidity_pct: float = 70.0, v_s_in: float = 3.5,
                                   curing_age_days: float = 3.0,
                                   tdmt_id: int = 1, tdme_id: int = 1,
                                   force_unit: str = "KIPS", length_unit: str = "ft",
                                   strength_a: float = 4.0, strength_b: float = 0.85) -> dict:
    """Time-dependent concrete for a construction stage analysis: ``TDMT``
    (creep / shrinkage, AASHTO code form), ``TDME`` (compressive-strength
    development, ACI) and the ``TMAT`` row linking them to material
    ``matl_id`` -- the shapes read back from the Civil NX girder wizard
    (:func:`civilpy.structural.midas_composite_wizard.property_tables`).

    Inputs are the ones :mod:`civilpy.structural.aashto.lrfd.creep_shrinkage`
    takes: ``fc_psi`` (28-day strength), ambient relative ``humidity_pct``,
    volume-to-surface ratio ``v_s_in`` (inches; MIDAS ``VOL`` in the model
    length unit) and the age at the end of curing (``AGE``).  ``strength_a`` /
    ``strength_b`` are the ACI 209 strength-gain constants ``f'c(t) = f'c t /
    (a + b t)``; 4.0 / 0.85 is moist-cured Type I cement, the wizard's
    values.  Strength is carried in the model stress unit (ksf for kips / ft,
    psi for lbf / in)."""
    per_ft = _length_ft_per(length_unit)
    force = {"KIPS": 1.0 / 1000.0, "KIP": 1.0 / 1000.0, "LBF": 1.0, "LB": 1.0}.get(force_unit.upper())
    if force is None:
        raise ValueError(f"force unit {force_unit!r}: use KIPS or LBF")
    stress = fc_psi * force * (12.0 * per_ft) ** 2            # psi -> force / length^2
    cs_name, comp_name = f"{name} C&S"[:16], f"{name} Comp"[:16]
    return {
        "TDMT": {str(tdmt_id): {"NAME": cs_name, "CODE": "AASHTO", "STR": round(stress, 6), "HU": humidity_pct,
                                "VOL": round(v_s_in / 12.0 / per_ft, 6), "AGE": curing_age_days, "bEXPOSE": False}},
        "TDME": {str(tdme_id): {"NAME": comp_name, "TYPE": "CODE", "CODENAME": "ACI", "STRENGTH": round(stress, 6),
                                "A": strength_a, "B": strength_b}},
        "TMAT": {str(matl_id): {"TDMT_NAME": cs_name, "TDME_NAME": comp_name}},
    }


#: Feet per unit of a model's ``UNIT`` DIST setting.  ``ELAST`` scales with
#: this squared (force/length^2) and ``DEN`` with its cube (force/length^3).
_FT_PER = {"ft": 1.0, "feet": 1.0, "foot": 1.0,
           "in": 1.0 / 12.0, "inch": 1.0 / 12.0, "inches": 1.0 / 12.0,
           "m": 3.280839895, "mm": 0.003280839895, "cm": 0.03280839895}


def _length_ft_per(length_unit: str) -> float:
    try:
        return _FT_PER[str(length_unit).strip().lower()]
    except KeyError:
        raise ValueError(
            f"unsupported model length unit {length_unit!r}; expected one of "
            f"{sorted(set(_FT_PER))}") from None


def solid_rect_section_block(width: float, height: float, *, sect_id: int = 1,
                             name: str | None = None) -> dict:
    """A solid-rectangle (``SB``) ``/db/SECT`` body, ``width`` x ``height`` in
    the model's length unit.

    This is the honest section for an equivalent-strip slab beam (a 1 ft wide
    x thickness deep concrete strip), where an AISC I-shape reference makes no
    sense. Dimension order matches the placeholder square: ``vSIZE = [H, B]``
    is MIDAS's [depth, width] for the SB shape.
    """
    name = name or f"RECT-{width:g}x{height:g}"
    return {str(sect_id): {
        "SECTTYPE": "DBUSER", "SECT_NAME": name,
        "SECT_BEFORE": {"SHAPE": "SB", "DATATYPE": 2,
                        "SECT_I": {"vSIZE": [round(height, 6),
                                             round(width, 6)]}},
    }}


def thickness_block(t_ft: float, *, thik_id: int = 1,
                    name: str | None = None) -> dict:
    """A ``/db/THIK`` value-thickness body (``t_ft`` in the model length unit),
    the plate-element analogue of a beam ``SECT``.  A plate ``ELEM`` references
    this id through its **``SECT`` field** (verified against a live Civil NX
    release: the plate body is ``{"TYPE":"PLATE","MATL":m,"SECT":<thik id>,
    "NODE":[n1..n4,0,0,0,0],"ANGLE":0,"STYPE":1}``)."""
    return {str(thik_id): {
        "NAME": name or str(thik_id), "TYPE": "VALUE", "bINOUT": False,
        "T_IN": round(t_ft, 6), "T_OUT": round(t_ft, 6), "O_VALUE": 0,
    }}


def _thickness_ft_from_label(label: str) -> float:
    """Parse a deck-thickness label like ``"DECK-8.5in"`` to feet (default 8 in)."""
    import re
    m = re.search(r"([\d.]+)\s*in", label or "")
    return (float(m.group(1)) if m else 8.0) / 12.0


def _fc_psi_from_label(label: str) -> float:
    """Parse an f'c out of a concrete label like ``"Deck-4500psi"`` (default 4500)."""
    import re
    m = re.search(r"([\d.]+)\s*psi", label or "")
    return float(m.group(1)) if m else 4500.0


def placeholder_section_block(*, sect_id: int = 1, side_ft: float = 1.0,
                              name: str = "PLACEHOLDER-1ft-SQ") -> dict:
    """A solid-square ``/db/SECT`` placeholder so exported elements reference a
    valid section.  Swap to the real shape inside Civil NX for flexure -- the
    equal-area square keeps axial stiffness honest meanwhile (same convention
    as ``TrussBridge``)."""
    return {str(sect_id): {
        "SECTTYPE": "DBUSER", "SECT_NAME": name,
        "SECT_BEFORE": {"SHAPE": "SB", "DATATYPE": 2,
                        "SECT_I": {"vSIZE": [round(side_ft, 6),
                                             round(side_ft, 6)]}},
    }}


def rolled_i_section_block(shape_label: str, *, sect_id: int = 1,
                          length_unit: str = "in",
                          db_name: str | None = "AISC10(US)") -> dict:
    """A ``/db/SECT`` body for a rolled I/H shape.

    By default this references the shape directly out of MIDAS's own
    section database (``db_name="AISC10(US)"``, ``DATATYPE=1``) rather than
    re-entering dimensions as a user-input section: ``shape_label`` (e.g.
    ``"W24X104"``) must match a name in that database, and MIDAS -- not
    civilpy -- is then the source of truth for the section properties used
    in analysis.  This is the correct choice for standard rolled shapes;
    civilpy's own ``steel.W`` dimensions are not sent at all in this path.
    Confirmed against a live Civil NX round-trip: ``GET /db/SECT`` echoed
    back exactly this ``SECT_BEFORE`` shape for a section entered as
    "DB/Shape -> AISC10(US) -> W24X104" in the Civil NX UI.

    Pass ``db_name=None`` for a built-up or historic shape with no library
    entry -- this falls back to a user-input (``DATATYPE=2``) section with
    dimensions pulled from ``steel.W`` (the AISC database module), the
    previous default behavior.  ``length_unit`` is a Pint unit string
    (``"in"``, ``"ft"``, ...) and **must match the model's own ``UNIT``
    table DIST** in that fallback -- MIDAS applies one length unit to every
    geometric quantity in the model, section dimensions included, so a
    mismatch silently scales the section by the conversion factor (inches
    sent while the model is in feet gives a 12x oversized, self-intersecting
    section). Callers building a full model payload should pass the model's
    own ``units.length`` (see :func:`hub_section_material_blocks`); the
    ``"in"`` default is only for standalone use."""
    common = {
        "OFFSET_PT": "CC", "OFFSET_CENTER": 0, "USER_OFFSET_REF": 0,
        "HORZ_OFFSET_OPT": 0, "USERDEF_OFFSET_YI": 0,
        "VERT_OFFSET_OPT": 0, "USERDEF_OFFSET_ZI": 0,
        "USE_SHEAR_DEFORM": True, "USE_WARPING_EFFECT": False,
        "SHAPE": "H",
    }
    if db_name is not None:
        sect_before = {**common, "DATATYPE": 1,
                       "SECT_I": {"DB_NAME": db_name,
                                  "SECT_NAME": shape_label}}
    else:
        from civilpy.structural import steel
        w = steel.W(shape_label)

        def _conv(q):
            return round(float(q.to(length_unit).magnitude), 6)

        h, b, tw, tf = (_conv(w.depth), _conv(w.flange_width),
                        _conv(w.web_thickness), _conv(w.flange_thickness))
        sect_before = {**common, "DATATYPE": 2,
                       "SECT_I": {"vSIZE": [h, b, tw, tf, b, tf]}}
    return {str(sect_id): {
        "SECTTYPE": "DBUSER", "SECT_NAME": shape_label,
        "SECT_BEFORE": sect_before,
    }}


def hub_section_material_blocks(model, *, sect_start: int = 1,
                                matl_start: int = 1,
                                default_grade: str = "Grade 50",
                                length_unit: str | None = None,
                                db_name: str | None = "AISC10(US)") -> dict:
    """Assign a real ``SECT`` per distinct AISC shape and a ``MATL`` per
    distinct grade from the hub's elements (stage **G5** -- replaces the single
    placeholder SECT/MATL that ``midas_payloads`` emits by default).

    Every shape is sent as a reference into MIDAS's own ``db_name`` section
    database (default ``"AISC10(US)"``) rather than a re-entered set of
    dimensions -- see :func:`rolled_i_section_block`.  Pass ``db_name=None``
    if the model's shapes are built-up/historic sections with no library
    entry; ``length_unit`` (defaulting to the model's own ``units.length``)
    only matters in that fallback, to keep section dimensions consistent
    with the ``NODE`` coordinates and the ``UNIT`` table's DIST.

    Returns ``{"SECT", "MATL", "sect_by_shape", "matl_by_grade",
    "elem_assign"}`` where ``elem_assign`` maps each ``Element.id`` to its
    ``(sect_id, matl_id)`` so the caller can wire real sections onto elements.
    Elements with no ``section`` label get ``sect_id=None`` (keep the
    placeholder for those).
    """
    length_unit = length_unit or model.units.length
    shapes: dict[str, int] = {}
    grades: dict[str, int] = {}
    sect: dict = {}
    matl: dict = {}
    elem_assign: dict = {}
    for elem in model.elements.values():
        if elem.midas_type == "PLATE":
            continue                 # plates carry a THIK + concrete, not a SECT
        label = elem.section
        grade = elem.material or default_grade
        meta = getattr(elem, "metadata", None) or {}
        if label and label not in shapes:
            sid = sect_start + len(shapes)
            shapes[label] = sid
            sect.update(_section_block_for(elem, label, sid, length_unit,
                                           db_name))
        if grade not in grades:
            mid = matl_start + len(grades)
            grades[grade] = mid
            fc_psi = meta.get("matl.fc_psi")
            if meta.get("matl.dummy"):
                matl.update(steel_material_block(
                    name=grade, matl_id=mid, props=DUMMY_PROPS,
                    length_unit=length_unit))
            elif fc_psi is not None:
                matl.update(concrete_material_block(
                    name=grade, matl_id=mid, fc_psi=float(fc_psi),
                    unit_wt_pcf=float(meta.get("matl.unit_wt_pcf", 145.0)),
                    length_unit=length_unit))
            else:
                matl.update(steel_material_block(name=grade, matl_id=mid,
                                                 length_unit=length_unit))
        elem_assign[elem.id] = (shapes.get(label), grades[grade])
    return {"SECT": sect, "MATL": matl, "sect_by_shape": shapes,
            "matl_by_grade": grades, "elem_assign": elem_assign}


def _section_block_for(elem, label: str, sect_id: int, length_unit: str,
                       db_name: str | None) -> dict:
    """The ``/db/SECT`` body for one element, dispatched on its
    ``sect.kind`` metadata.

    Without that metadata an element's ``section`` label is taken to be a
    rolled shape and looked up in MIDAS's AISC database -- which is the
    right default for the steel pipelines but silently wrong for anything
    else: a concrete girder labelled ``"CB27-48"`` stores as a DB/Shape
    reference to a name that database does not contain, and MIDAS neither
    resolves it nor complains.  Concrete pipelines therefore tag their
    elements:

    ``sect.kind = "psc"``
        a PSC value section from the element's ``sect.designation`` and
        ``sect.family`` (``"box"``, ``"shear-key"`` or ``"i-beam"``) --
        the exact outline and void polygons, not a parametric shape.
    ``sect.kind = "rect"``
        a solid rectangle ``sect.width_in`` x ``sect.height_in``.
    ``sect.kind = "round"``
        a solid circle of ``sect.diameter_in`` -- a tie rod, a dowel.
    """
    meta = getattr(elem, "metadata", None) or {}
    kind = meta.get("sect.kind")
    scale = 1.0 / (12.0 * _length_ft_per(length_unit))       # inches -> model
    if kind == "psc":
        from civilpy.structural import psc_section as _psc

        family = meta.get("sect.family", "box")
        designation = meta.get("sect.designation", label)
        if family == "shear-key":
            shape = _psc.shear_key_shape(designation)
        elif family == "i-beam":
            shape = _psc.i_beam_shape(designation)
        else:
            shape = _psc.box_beam_shape(
                designation, solid=bool(meta.get("sect.solid")))
        return {str(sect_id): _psc.midas_section_payload(
            shape, name=label, length_unit=length_unit)}
    if kind == "rect":
        return solid_rect_section_block(
            float(meta["sect.width_in"]) * scale,
            float(meta["sect.height_in"]) * scale,
            sect_id=sect_id, name=label)
    if kind == "round":
        return solid_round_section_block(
            float(meta["sect.diameter_in"]) * scale,
            sect_id=sect_id, name=label)
    return rolled_i_section_block(label, sect_id=sect_id,
                                  length_unit=length_unit, db_name=db_name)


def solid_round_section_block(diameter: float, *, sect_id: int = 1,
                              name: str | None = None) -> dict:
    """A solid-round (``SR``) ``/db/SECT`` body -- the honest section for a
    tie rod or anchor dowel, which is a bar, not a rectangle."""
    return {str(sect_id): {
        "SECTTYPE": "DBUSER", "SECT_NAME": name or f"ROUND-{diameter:g}",
        "SECT_BEFORE": {"SHAPE": "SR", "DATATYPE": 2,
                        "SECT_I": {"vSIZE": [round(diameter, 6)]}},
    }}


#: A709 Grade 50 is the default steel; tie rods are ASTM A307 Grade 307A.
#: Same modulus and density -- the grade matters for capacity, not for the
#: stiffness this model carries.
ROD_STEEL_PROPS = dict(STEEL_PROPS)


#: A weightless, near-rigid-free material for dummy elements (traffic lane
#: lines).  They exist to carry a lane definition and must not attract load
#: or add stiffness: 1 ksi and zero density.
DUMMY_PROPS = {"ELAST": 144.0, "POISN": 0.3, "THERMAL": 0.0, "DEN": 0.0}


def constraint_assign(cons_by_id: dict[int, str]) -> dict:
    """Wrap ``{node_id: "DX..RW" flag string}`` into the ``/db/CONS`` body
    ``{node_id: {"ITEMS": [{"ID": 1, "CONSTRAINT": flags}]}}``."""
    return {str(i): {"ITEMS": [{"ID": 1, "CONSTRAINT": flags}]}
            for i, flags in cons_by_id.items()}


# ============================================================ curved girders


def circular_curve_nodes(
    radius: float,
    central_angle_deg: float,
    n_segments: int,
    girder_offsets: Iterable[float],
    *,
    z: float = 0.0,
    node_start: int = 1,
) -> tuple[dict, dict]:
    """Nodes for girders following a horizontal circular curve.

    Each girder is a concentric arc: girder ``g`` at radial ``offset`` rides
    radius ``radius + offset`` (offset positive toward the outside of the
    curve).  The arc sweeps ``central_angle_deg`` in ``n_segments`` equal
    steps; the curve centre is at the origin and station 0 lies on the +Y
    axis, so ``X = r*sin(theta)`` and ``Y = r*cos(theta)``.

    Returns ``(assign, grid)`` where ``assign`` is the ``/db/NODE`` body
    ``{id: {"X", "Y", "Z"}}`` and ``grid`` maps ``(girder_index,
    station_index) -> node_id`` for wiring elements.
    """
    offsets = list(girder_offsets)
    dtheta = math.radians(central_angle_deg) / n_segments
    assign: dict = {}
    grid: dict = {}
    nid = node_start
    for g, offset in enumerate(offsets):
        r = radius + offset
        for i in range(n_segments + 1):
            theta = i * dtheta
            assign[str(nid)] = {
                "X": round(r * math.sin(theta), 6),
                "Y": round(r * math.cos(theta), 6),
                "Z": z,
            }
            grid[(g, i)] = nid
            nid += 1
    return assign, grid


def curved_girder_model(
    radius: float,
    central_angle_deg: float,
    n_segments: int,
    girder_offsets: Iterable[float],
    *,
    matl: int = 1,
    sect: int = 1,
    diaphragm_sect: Optional[int] = None,
    node_start: int = 1,
    elem_start: int = 1,
) -> dict:
    """A horizontally curved multi-girder model: concentric chorded girder
    lines plus, when ``diaphragm_sect`` is given, a transverse diaphragm
    between adjacent girders at every station.

    Returns ``{"NODE": ..., "ELEM": ..., "grid": ..., "meta": ...}`` where
    ``NODE``/``ELEM`` are ``/db/*`` assign bodies.  Chorded straight beams
    approximate the curve (standard practice); refine ``n_segments`` until
    the chord offset is acceptable.
    """
    offsets = list(girder_offsets)
    nodes, grid = circular_curve_nodes(
        radius, central_angle_deg, n_segments, offsets, node_start=node_start
    )
    elems: dict = {}
    eid = elem_start
    # Longitudinal girder beams.
    for g in range(len(offsets)):
        for i in range(n_segments):
            elems[str(eid)] = {
                "TYPE": "BEAM", "MATL": matl, "SECT": sect,
                "NODE": [grid[(g, i)], grid[(g, i + 1)]], "ANGLE": 0,
            }
            eid += 1
    # Transverse diaphragms / cross-frames between adjacent girders.
    if diaphragm_sect is not None:
        for g in range(len(offsets) - 1):
            for i in range(n_segments + 1):
                elems[str(eid)] = {
                    "TYPE": "BEAM", "MATL": matl, "SECT": diaphragm_sect,
                    "NODE": [grid[(g, i)], grid[(g + 1, i)]], "ANGLE": 0,
                }
                eid += 1
    return {
        "NODE": nodes, "ELEM": elems, "grid": grid,
        "meta": {"radius": radius, "central_angle_deg": central_angle_deg,
                 "n_segments": n_segments, "n_girders": len(offsets),
                 "arc_length": math.radians(central_angle_deg) * radius},
    }


# ============================================================ bifurcated girders


def bifurcated_girder_model(
    stem_length: float,
    stem_segments: int,
    branches: list[dict],
    *,
    stem_offset: float = 0.0,
    matl: int = 1,
    sect: int = 1,
    node_start: int = 1,
    elem_start: int = 1,
) -> dict:
    """A girder line that runs straight for ``stem_length`` then splits at a
    gore node into diverging branches.

    The stem runs along +X from ``(0, stem_offset)`` to ``(stem_length,
    stem_offset)`` in ``stem_segments`` beams; the last stem node is the
    **gore**.  Each entry in ``branches`` is
    ``{"length", "end_offset", "segments"}`` -- a branch from the gore to
    ``(stem_length + length, end_offset)``, straight-line interpolated.

    Returns ``{"NODE", "ELEM", "gore_node", "branch_end_nodes", "meta"}``.
    """
    nodes: dict = {}
    elems: dict = {}
    nid = node_start
    eid = elem_start

    # Stem.
    stem_ids = []
    for i in range(stem_segments + 1):
        x = stem_length * i / stem_segments
        nodes[str(nid)] = {"X": round(x, 6), "Y": stem_offset, "Z": 0.0}
        stem_ids.append(nid)
        nid += 1
    for i in range(stem_segments):
        elems[str(eid)] = {
            "TYPE": "BEAM", "MATL": matl, "SECT": sect,
            "NODE": [stem_ids[i], stem_ids[i + 1]], "ANGLE": 0,
        }
        eid += 1
    gore_node = stem_ids[-1]

    # Branches diverging from the gore.
    branch_end_nodes = []
    for br in branches:
        length = br["length"]
        end_offset = br["end_offset"]
        segments = br.get("segments", stem_segments)
        prev = gore_node
        for j in range(1, segments + 1):
            f = j / segments
            x = stem_length + length * f
            y = stem_offset + (end_offset - stem_offset) * f
            nodes[str(nid)] = {"X": round(x, 6), "Y": round(y, 6), "Z": 0.0}
            elems[str(eid)] = {
                "TYPE": "BEAM", "MATL": matl, "SECT": sect,
                "NODE": [prev, nid], "ANGLE": 0,
            }
            prev = nid
            nid += 1
            eid += 1
        branch_end_nodes.append(prev)

    return {
        "NODE": nodes, "ELEM": elems, "gore_node": gore_node,
        "branch_end_nodes": branch_end_nodes,
        "meta": {"stem_length": stem_length, "n_branches": len(branches)},
    }


# ============================================================ abutments


def abutment_connection(
    kind: str,
    girder_end_nodes: Iterable[int],
    seat_node: int,
    *,
    bearing_stiffness: Optional[list[float]] = None,
    link_start: int = 1,
) -> dict:
    """Super-/substructure connection at an abutment.

    ``kind="integral"`` -- girders are cast monolithically into the abutment
    cap: a **rigid link** (``/db/RIGD``) makes ``seat_node`` the master and
    every girder end a slave for all six DOF, so the connection is
    moment-continuous and thermal movement is taken by the (flexible) pile
    bent below -- give that bent :func:`soil_spring_supports`, not fixed
    bases.

    ``kind="semi-integral"`` -- the deck/backwall is continuous but the
    girders bear on bearings at the seat: an **elastic link** (``/db/ELNK``,
    ``LINK="GEN"``) per girder carries vertical load stiffly and frees
    longitudinal translation and rotation.  ``bearing_stiffness`` is the
    ``SDR`` vector ``[kdx, kdy, kdz, krx, kry, krz]`` in model units;
    the default is a near-rigid vertical (kdz) bearing, soft elsewhere.

    Returns a dict of ``/db/*`` assign bodies to merge into the model
    (``{"RIGD": ...}`` or ``{"ELNK": ...}``).
    """
    ends = list(girder_end_nodes)
    if kind == "integral":
        return {"RIGD": {str(seat_node): {
            "ITEMS": [{"ID": 1, "DOF": 111111, "S_NODE": ends}],
        }}}
    if kind == "semi-integral":
        sdr = bearing_stiffness or [10.0, 10.0, 1.0e7, 0.0, 0.0, 0.0]
        elnk: dict = {}
        for i, end in enumerate(ends):
            elnk[str(link_start + i)] = {
                "NODE": [end, seat_node], "LINK": "GEN", "ANGLE": 0,
                "SDR": list(sdr),
            }
        return {"ELNK": elnk}
    raise ValueError(f"unknown kind {kind!r} (use 'integral' or 'semi-integral')")


# ============================================================ soil springs


def soil_spring_supports(
    node_springs: dict[int, list[float]],
    *,
    table: str = "SPRING",
    spring_type: str = "LINEAR",
) -> dict:
    """Nodal foundation springs from per-node stiffness vectors.

    ``node_springs`` maps ``node_id -> [kdx, kdy, kdz, krx, kry, krz]`` in
    model units (convert the geotech curves' lb/in values with
    :func:`lb_per_in_to_kip_per_ft`).  Typically ``kdx``/``kdy`` come from
    the p-y secant modulus (:mod:`civilpy.geotech.lateral_pile`), ``kdz``
    from the t-z springs and the q-z tip spring
    (:mod:`civilpy.geotech.axial_load_transfer`).

    Returns the assign body ``{node_id: {"ITEMS": [{"ID": 1, "TYPE": ...,
    "SDR": [...]}]}}``.  **The MIDAS point-spring table name is unverified**
    -- pass the live-confirmed ``table`` to
    ``MidasCivil.put_db(table, body)`` (see the live-capture checklist).
    """
    assign: dict = {}
    for node_id, sdr in node_springs.items():
        if len(sdr) != 6:
            raise ValueError(
                f"node {node_id}: expected 6 stiffnesses [kdx,kdy,kdz,krx,kry,krz], "
                f"got {len(sdr)}")
        assign[str(node_id)] = {
            "ITEMS": [{"ID": 1, "TYPE": spring_type, "SDR": list(sdr)}],
        }
    return assign


# ============================================ canonical hub -> MIDAS
#
# The Rhino -> Midas adapter: read a tagged ``.3dm`` into the canonical
# ``StructuralModel`` (``rhino_stm.read_structural_model``), then serialize that
# hub straight to MIDAS -- *without* routing through the lossy 2D
# ``StrutAndTieModel`` (which drops fix_z/rx/ry/rz).  Mirrors
# ``TrussBridge.midas_payloads`` / ``.to_midas`` in shape and report so the two
# exporters behave identically.


def midas_vehicle_payload(vehicle, *, lane_load_klf: float | None = None,
                          plm_kip: float = 0.0, plv_kip: float = 0.0,
                          im_percent: float = 0.0,
                          length_unit: str = "in") -> dict:
    """A ``/db/mvhl`` user-defined Truck/Lane vehicle record from a
    :class:`~civilpy.structural.aashto.vehicles.RatingVehicle` -- the way
    to run vehicles Midas's DB lacks (ODOT's FAST-Act EV2/EV3, custom
    permit trains).

    Schema verified live 2026-07-27: axles ride a ``LOAD_ITEMS`` array of
    ``{POINT_LOAD, POINT_DIST}`` (distance to the NEXT axle; kips and
    model length units); the lane component and concentrated moment/shear
    loads (PLM/PLV) sit in ``VEH_DEFAULT``.  ``lane_load_klf`` defaults
    to the vehicle's own definition.

    ``length_unit`` must match the model's ``UNIT`` DIST -- axle spacings
    and the lane load are carried in it, so a truck built for inches and
    pushed to a model in feet is 12x too long, stores without complaint,
    and simply produces the wrong envelope.  Read it off the model with
    :func:`model_length_unit` rather than assuming.

    .. warning::
       ``im_percent`` is **silently discarded** for user-defined
       vehicles.  Verified live 2026-07-28: a standard-DB record
       (:func:`midas_standard_vehicle`) stores
       ``VEH_DEFAULT.DYN_LOAD_ALLOWANCE``, but on a ``Truck/Lane`` user
       vehicle Midas drops the field entirely -- it is absent from the
       record on read-back, i.e. IM = 0.  Apply the dynamic load
       allowance downstream instead (moving-load-case scale factor, or
       the load combination), or the live load effect will be low by the
       full IM.  The parameter is kept so the axle loads stay nominal and
       auditable against the source figure.
    """
    if lane_load_klf is None:
        lane_load_klf = vehicle.lane_load_klf
    per_ft = _length_ft_per(length_unit)      # feet per model length unit
    spac = list(vehicle.axle_spacings_ft) + [0.0]
    items = [{"POINT_LOAD": float(p), "POINT_DIST": float(d) / per_ft}
             for p, d in zip(vehicle.axle_loads_kip, spac)]
    return {
        "MVLD_CODE": 2, "VEHICLE_LOAD_NAME": vehicle.name,
        "VEHICLE_LOAD_NUM": 2, "USER_LOAD_TYPE": "Truck/Lane",
        "VEH_DEFAULT": {"UNIFORM_LOAD": lane_load_klf * per_ft,
                        "PL": 0.0, "PLM": plm_kip, "PLV": plv_kip,
                        "DYN_LOAD_ALLOWANCE": im_percent,
                        "CENT_F": False},
        "LOAD_ITEMS": items,
    }


def model_length_unit(client, default: str = "in") -> str:
    """The live model's ``UNIT`` table DIST, lower-cased (``"in"``,
    ``"ft"``, ...).

    Axle spacings, section coordinates, material moduli and densities are
    all carried in this one unit, and nothing in an API response says
    which it is -- a vehicle built in feet and pushed to an inch model
    stores cleanly and then runs a truck 12x too short.  Read it, don't
    assume it.
    """
    try:
        unit = client.request("GET", "db/UNIT").get("UNIT", {})
        dist = next(iter(unit.values())).get("DIST")
        return str(dist).strip().lower() if dist else default
    except Exception:
        return default


#: Midas standard-DB entries for the ODOT BDM 908.3 rating vehicles,
#: as ``{civilpy name: (STANDARD_CODE, VEHICLE_TYPE_NAME)}``.  Strings are
#: read back off a live model where dane added them through the UI
#: (2026-07-28).  **Note the spaces**: the online API manual renders these
#: with all spaces stripped ("AASHTOLegalType3", "OHDOTLOAD"), which is a
#: rendering artifact -- those forms are wrong and, because the API does
#: not validate names, would store cleanly and then apply ZERO load
#: silently.  Always confirm nonzero envelopes after the first analysis.
#:
#: The two ODOT state permit loads (S-PL60T/S-PL65T) have no DB entry at
#: all.  Build those with :func:`midas_vehicle_payload` -- but
#: note the IM caveat there.
#:
#: .. warning::
#:    These map a BDM vehicle NAME to a Midas DB entry; they do **not**
#:    assert that Midas's axle train matches the current BDM figure.
#:    Midas's built-in definitions are a vendor transcription frozen at
#:    some past spec revision -- their ODOT standard box sections are
#:    known to be out of date, and the same risk applies here.  A DB
#:    vehicle also hides its axle data: the stored record carries only
#:    the type name, so the API cannot read back what Midas will
#:    actually apply.  Verify each against
#:    :data:`~civilpy.structural.aashto.vehicles.RATING_VEHICLES` (which
#:    IS checked against BDM Figures 908.3-1..-5) before using the DB
#:    entry for a rating.
BDM_908_STANDARD_DB = {
    "2F1": ("OHDOT LOAD", "OH Legal load 2F1"),
    "3F1": ("OHDOT LOAD", "OH Legal load 3F1"),
    "4F1": ("OHDOT LOAD", "OH Legal load 4F1"),
    "5C1": ("OHDOT LOAD", "OH Legal load 5C1"),
    "Type 3": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Legal Type 3"),
    "Type 3S2": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Legal Type 3S2"),
    "Type 3-3": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Legal Type 3-3"),
    "SU4": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Posting load SU4"),
    "SU5": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Posting load SU5"),
    "SU6": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Posting load SU6"),
    "SU7": ("AASHTO LEGAL/PERMIT LOAD", "AASHTO Posting load SU7"),
    "EV2": ("FAST ACT EV LOADS", "Type EV2"),
    "EV3": ("FAST ACT EV LOADS", "Type EV3"),
}


def midas_standard_vehicle(type_name: str, *, name: str | None = None,
                           standard_code: str = "AASHTO-LRFD",
                           im_percent: float = 33.0) -> dict:
    """A ``/db/mvhl`` standard-DB vehicle record.

    Verified live 2026-07-27: ``STANDARD_CODE`` is REQUIRED for the DB
    reference to resolve -- without it the record stores cleanly but the
    vehicle applies zero load, silently.  LRFD DB names include
    "HL-93TRK", "HL-93TDM", "HS20-FTG"; ``standard_code`` "OHDOT LOAD"
    reaches the Ohio legal/permit set ("OH Legal load 5C1", 2F1, 3F1,
    4F1 -- the BDM's EV vehicles are absent, use
    :func:`midas_vehicle_payload` for those).
    """
    return {
        "MVLD_CODE": 2, "VEHICLE_LOAD_NAME": name or type_name,
        "VEHICLE_LOAD_NUM": 1, "VEHICLE_TYPE_NAME": type_name,
        "STANDARD_CODE": standard_code,
        "VEH_DEFAULT": {"DYN_LOAD_ALLOWANCE": im_percent,
                        "CENT_F": False},
    }


def midas_payloads(model: "StructuralModel", *, node_start: int = 1,
                   elem_start: int = 1, material_name: str = "A709-50",
                   db_name: str | None = "AISC10(US)") -> dict:
    """Serialize a :class:`~civilpy.structural.structural_model.StructuralModel`
    to MIDAS ``PUT /db/*`` assign bodies -- the **Rhino -> Midas** payload step.

    Pure (no live session): returns ``{table: assign}`` in send order
    ``UNIT, MATL, SECT, [THIK], NODE, ELEM, [GRUP], [FRLS], [RIGD], CONS, STLD,
    [LDGR], [BODF], CNLD, [BMLD]`` -- the bracketed tables only when the model
    carries element groups (:meth:`StructuralModel.set_group`), load groups,
    self weight, releases or rigid links.  The hub's stable string
    ids are mapped to the 1-based integer ids MIDAS uses (node insertion order);
    full 6-DOF restraints become the 7-char ``CONS`` flag string via
    :meth:`Restraint.to_constraint_string`, so ``fix_z/rx/ry/rz`` reach MIDAS
    intact.  Loads are grouped into ``STLD`` cases with their nodal forces and
    moments in ``CNLD``.

    Every element gets a real ``SECT`` per distinct AISC shape label
    (:func:`hub_section_material_blocks`) and a real ``MATL`` per distinct
    grade; an element with no shape label falls back to the placeholder
    square section (still real steel material) so it always references a
    valid section.  By default each ``SECT`` references the shape directly
    out of MIDAS's own ``db_name`` database (``"AISC10(US)"``) instead of
    re-entering dimensions; pass ``db_name=None`` for built-up/historic
    shapes with no library entry.

    .. note::
       The ``CNLD`` concentrated-nodal-load layout follows the API manual but is
       **unverified against a live Civil NX release** -- check the send report's
       errors first when debugging (same caveat as the ``midas_models`` builders).
    """
    node_int: dict[str, int] = {}
    coords_by_id: dict[int, tuple] = {}
    for k, node in enumerate(model.nodes.values(), start=node_start):
        node_int[node.id] = k
        coords_by_id[k] = node.coords

    nodes = {str(i): {"X": round(x, 6), "Y": round(y, 6), "Z": round(z, 6)}
             for i, (x, y, z) in coords_by_id.items()}

    blocks = hub_section_material_blocks(model, default_grade=material_name,
                                          db_name=db_name)
    sect = dict(blocks["SECT"])
    matl = dict(blocks["MATL"])
    elem_assign = blocks["elem_assign"]

    # Elements with no gdr.shape label (or no elements at all) get the
    # placeholder square so every ELEM still references a valid SECT.
    placeholder_id = None
    if not sect or any(sid is None for sid, _ in elem_assign.values()):
        placeholder_id = max((int(k) for k in sect), default=0) + 1
        sect.update(placeholder_section_block(sect_id=placeholder_id))

    # Plate (deck) elements: a THIK per distinct thickness label and a concrete
    # MATL per distinct concrete label (steel MATL ids are already taken).
    plate_elems = [e for e in model.elements.values()
                   if e.midas_type == "PLATE"]
    thik: dict = {}
    thik_by_label: dict[str, int] = {}
    conc_by_label: dict[str, int] = {}
    next_matl = max((int(k) for k in matl), default=0)
    per_ft = _length_ft_per(model.units.length)
    for e in plate_elems:
        tlabel = e.section or "DECK-8in"
        if tlabel not in thik_by_label:
            tid = len(thik_by_label) + 1
            thik_by_label[tlabel] = tid
            thik.update(thickness_block(
                _thickness_ft_from_label(tlabel) / per_ft,   # ft -> model unit
                thik_id=tid, name=tlabel))
        clabel = e.material or "Deck-4500psi"
        if clabel not in conc_by_label:
            next_matl += 1
            conc_by_label[clabel] = next_matl
            meta = getattr(e, "metadata", None) or {}
            matl.update(concrete_material_block(
                name=clabel, matl_id=next_matl,
                fc_psi=_fc_psi_from_label(clabel),
                unit_wt_pcf=float(meta.get("matl.unit_wt_pcf", 145.0)),
                length_unit=model.units.length))

    elements: dict[str, dict] = {}
    for j, elem in enumerate(model.elements.values(), start=elem_start):
        node_ids = [node_int[nid] for nid in elem.nodes]
        if elem.midas_type == "PLATE":
            # 3- or 4-node area element; NODE list padded to 8 ids with zeros.
            node_ids = (node_ids + [0, 0, 0, 0, 0, 0, 0, 0])[:8]
            elements[str(j)] = {
                "TYPE": "PLATE",
                "MATL": conc_by_label[elem.material or "Deck-4500psi"],
                "SECT": thik_by_label[elem.section or "DECK-8in"],
                "NODE": node_ids, "ANGLE": 0, "STYPE": 1,
            }
        else:
            sid, mid = elem_assign[elem.id]
            elements[str(j)] = {
                "TYPE": elem.midas_type, "MATL": mid,
                "SECT": sid if sid is not None else placeholder_id,
                "NODE": node_ids, "ANGLE": elem.beta_deg,
            }

    # Beam end releases -> /db/FRLS (same body as staad.to_midas, verified
    # live): local DX DY DZ RX RY RZ flags plus the warping digit.
    releases: dict[str, dict] = {}
    for j, elem in enumerate(model.elements.values(), start=elem_start):
        if elem.midas_type == "PLATE" or not elem.is_released:
            continue
        fi, fj = (f + "0" for f in elem.releases)
        releases[str(j)] = {"ITEMS": [{"ID": 1, "GROUP_NAME": "", "bVALUE": False,
                                       "FLAG_I": fi, "VALUE_I": [0] * 7,
                                       "FLAG_J": fj, "VALUE_J": [0] * 7}]}

    cons = {node_int[r.node_id]: r.to_constraint_string()
            for r in model.restraints.values()
            if any(r.flags())}

    # Static load cases (one STLD per named case) and their nodal point loads.
    # A case counts if it carries *either* nodal or distributed beam loads --
    # a distributed-load-only model (e.g. an equivalent-strip slab) otherwise
    # emits no STLD, and MIDAS then rejects the solve with "Load information
    # has not been entered for Analysis."
    cases = [c for c in model.cases()
             if model.loads_in_case(c) or model.beam_loads_in_case(c)
             or any(b.case == c for b in model.body_forces)]
    static_loads = {
        str(i): {"NAME": name, "TYPE": "USER", "DESC": ""}
        for i, name in enumerate(cases, start=1)
    }
    nodal_loads: dict[str, dict] = {}
    for load in model.loads:
        if not any((load.fx, load.fy, load.fz, load.mx, load.my, load.mz)):
            continue
        body = nodal_loads.setdefault(str(node_int[load.node_id]), {"ITEMS": []})
        body["ITEMS"].append({
            "ID": len(body["ITEMS"]) + 1, "LCNAME": load.case, "GROUP_NAME": load.group,
            "FX": load.fx, "FY": load.fy, "FZ": load.fz,
            "MX": load.mx, "MY": load.my, "MZ": load.mz,
        })

    payloads = {
        "UNIT": unit_block_for(model.units),
        "MATL": matl,
        "SECT": sect,
    }
    if thik:                       # THIK before ELEM: plates reference it
        payloads["THIK"] = thik
    payloads["NODE"] = nodes
    payloads["ELEM"] = elements
    # Structure groups -> /db/GRUP (the wizard's shape: the elements and their
    # nodes).  Construction stages activate elements by these names.
    groups = model.element_groups()
    if groups:
        elem_int_g = {elem.id: j for j, elem in enumerate(model.elements.values(), start=elem_start)}
        grup: dict = {}
        for i, (name, eids) in enumerate(groups.items(), start=1):
            n_list = sorted({node_int[n] for eid in eids for n in model.elements[eid].nodes})
            grup[str(i)] = {"NAME": name, "P_TYPE": 0, "N_LIST": n_list,
                            "E_LIST": sorted(elem_int_g[eid] for eid in eids)}
        payloads["GRUP"] = grup
    if releases:
        payloads["FRLS"] = releases
    # Rigid (master-slave) links -> /db/RIGD. The DOF flag string is sent as an
    # integer; MIDAS right-aligns it to the 6 DOF positions (DX DY DZ RX RY RZ),
    # so "011111" (free longitudinal slip, non-composite) rides as 11111.
    if model.rigid_links:
        rigd: dict = {}
        for link in model.rigid_links:
            m = str(node_int[link.master])
            body = rigd.setdefault(m, {"ITEMS": []})
            body["ITEMS"].append({
                "ID": len(body["ITEMS"]) + 1,
                "GROUP_NAME": "",
                "DOF": int(link.dof),
                "S_NODE": [node_int[s] for s in link.slaves],
            })
        payloads["RIGD"] = rigd
    if cons:
        payloads["CONS"] = constraint_assign(cons)
    if static_loads:
        payloads["STLD"] = static_loads
    # Load groups -> /db/LDGR, before the loads that name them.
    load_groups = model.load_groups()
    if load_groups:
        payloads["LDGR"] = {str(i): {"NAME": g} for i, g in enumerate(load_groups, start=1)}
    # Self weight -> /db/BODF (the wizard's shape; FV = gravity factors).
    if model.body_forces:
        payloads["BODF"] = {str(i): {"LCNAME": b.case, "GROUP_NAME": b.group, "FV": [b.gx, b.gy, b.gz]}
                            for i, b in enumerate(model.body_forces, start=1)}
    if nodal_loads:
        payloads["CNLD"] = nodal_loads

    # Element distributed loads -> /db/BMLD (verified against a live Civil NX
    # release). The table is BMLD, not "BEAM" (which the API rejects), and the
    # uniform-load body uses CMD="BEAM", TYPE="UNILOAD", relative distances in
    # D=[d_i, d_j, 0, 0] (0..1 along the element) and magnitudes in
    # P=[w_i, w_j, 0, 0] -- not flat D1/D2/W1/W2 fields ("Wrong Field").
    if model.beam_loads:
        elem_int: dict[str, int] = {elem.id: j for j, elem in enumerate(model.elements.values(), start=elem_start)}
        beam_loads: dict[str, dict] = {}
        for bload in model.beam_loads:
            body = beam_loads.setdefault(str(elem_int[bload.element_id]), {"ITEMS": []})
            w_end = bload.w_end if bload.w_end is not None else bload.w_start
            if bload.kind == "point":
                shape = {"TYPE": "CONLOAD", "D": [bload.start, 0.0, 0.0, 0.0],
                         "P": [bload.w_start, 0.0, 0.0, 0.0]}
            else:
                shape = {"TYPE": "UNILOAD",
                         "D": [bload.start, bload.end, 0.0, 0.0],   # relative
                         "P": [bload.w_start, w_end, 0.0, 0.0]}
            body["ITEMS"].append({
                "ID": len(body["ITEMS"]) + 1,
                "LCNAME": bload.case,
                "GROUP_NAME": bload.group,
                "CMD": "BEAM",
                "DIRECTION": bload.direction,
                "USE_PROJECTION": False,
                "USE_ECCEN": False,
                **shape,
            })
        payloads["BMLD"] = beam_loads

    return payloads


#: Send order for the construction-stage tables (groups and loads must already be in the model).
STAGE_TABLE_ORDER = ("TDMT", "TDME", "TMAT", "BNGR", "STAG", "STCT", "CSCS")


def push_stage_tables(midas, tables: dict, *, base_stage: bool = True) -> dict:
    """Send construction-stage tables (``ConstructionSequence.to_midas()``
    plus any :func:`time_dependent_material_blocks`) to a live Civil NX
    session in :data:`STAGE_TABLE_ORDER`.

    Stage writes are legal in **Base Stage** only: with ``base_stage`` the
    session is flipped back to preprocessing first
    (:func:`civilpy.state.ohio.DOT.midas_bridge.ensure_base_stage`), which
    discards analysis results.  A license refusal (``MidasLicenseError``, a
    Plus license and more than 10 stages) stops the push and is reported
    under the table that raised it; other errors are reported per table and
    the push continues.  Keys of ``tables`` that start with ``_`` (notes) are
    ignored.  Returns ``{table: {"sent": n} | {"error": msg}}``."""
    from civilpy.structural.midas import MidasLicenseError
    report: dict = {}
    if base_stage:
        try:
            from civilpy.state.ohio.DOT.midas_bridge import ensure_base_stage
            report["_base_stage"] = {"sent": int(bool(ensure_base_stage(midas)))}
        except Exception as exc:                      # pragma: no cover - import / transport
            report["_base_stage"] = {"error": str(exc)}
    pending = {k: v for k, v in tables.items() if not k.startswith("_")}
    unknown = [k for k in pending if k not in STAGE_TABLE_ORDER]
    if unknown:
        raise ValueError(f"not construction-stage tables: {unknown}; order is {STAGE_TABLE_ORDER}")
    for table in STAGE_TABLE_ORDER:
        if table not in pending:
            continue
        try:
            midas.put_db(table, pending[table])
            report[table] = {"sent": len(pending[table])}
        except MidasLicenseError as exc:
            report[table] = {"error": f"license: {exc}"}
            break
        except Exception as exc:
            report[table] = {"error": str(exc)}
    return report


def push_midas(model: "StructuralModel", midas=None, **client_kwargs) -> dict:
    """Send a hub to a live Civil NX session (built from ``~/secrets.json`` when
    ``midas`` is not given).  Pushes each :func:`midas_payloads` table in order,
    keeps going on errors, and returns ``{table: {"sent": n} | {"error": msg}}``
    -- the same report shape as ``TrussBridge.to_midas``."""
    if midas is None:
        from civilpy.structural.midas import MidasCivil
        midas = MidasCivil(**client_kwargs)
    report = {}
    for table, assign in midas_payloads(model).items():
        try:
            midas.put_db(table, assign)
            report[table] = {"sent": len(assign)}
        except Exception as exc:            # MidasApiError, transport, etc.
            report[table] = {"error": str(exc)}
    return report


#: The design loads ODOT BDM 908.2 specifies for inventory/operating
#: ratings, as ``{label: (STANDARD_CODE, VEHICLE_TYPE_NAME)}``.  Figures
#: 908.2-1/-2 reproduce the standard AASHTO definitions unchanged (HS20
#: lane 0.640 klf with the 18 kip moment / 26 kip shear concentrated
#: loads; HL-93 tandem 25 kip axles at 4 ft), so the DB entries apply.
BDM_908_DESIGN_DB = {
    "HL-93 truck": ("AASHTO-LRFD", "HL-93TRK"),
    "HL-93 tandem": ("AASHTO-LRFD", "HL-93TDM"),
    "HS20-44 truck": ("AASHTO-STD", "HS20-44"),
    "HS20-44 lane": ("AASHTO-STD", "HS20-44L"),
}

#: Entries in :data:`BDM_908_DESIGN_DB` that are a LANE load rather than a
#: truck or tandem.  BDM 924.4.C: "Dynamic load allowance shall only be
#: applied to the truck or tandem portion of HL93 loading (dynamic load
#: allowance shall not be provided to the lane portion)."  These get
#: IM = 0.
BDM_908_LANE_LOADS = frozenset({"HS20-44 lane"})


def load_oh_vehicles(client, *, im_percent: float = 33.0,
                     include_design: bool = True,
                     use_standard_db: bool = False,
                     replace: bool = False) -> dict:
    """Push every vehicle ODOT BDM Section 908 specifies into a live model.

    Loads exactly the BDM set and nothing else -- the ten commercial legal
    vehicles and two emergency vehicles of 908.3, the two state permit
    loads of 908.3.3, and (with ``include_design``) the 908.2
    inventory/operating design loads.  Vehicles Midas offers but the BDM
    does not call for -- the AASHTO National Rating Load, the H15/H20/HS15/
    HS25/AML standard set, Ohio 4F1 -- are deliberately excluded.

    Parameters
    ----------
    client:
        A live :class:`~civilpy.structural.midas.MidasCivil`.
    im_percent:
        Dynamic load allowance written onto standard-DB records, per BDM
        924.4.A (33% for all non-buried bridges).  Two rules from that
        article are applied automatically: lane loads get IM = 0
        (924.4.C, :data:`BDM_908_LANE_LOADS`), and the state permit loads
        get IM = 0 (924.4.E allows the allowance to be ignored for
        permit loads under controlled conditions).  The rest of 924.4 is
        bridge-specific and must be handled by the caller: 15% for
        fatigue (B), no IM on wood components (D), and the buried-
        structure reduction IM = 33(1 - 0.125*DE) (F).

        **The value is silently discarded on user-defined records** --
        see :func:`midas_vehicle_payload` -- so when ``use_standard_db``
        is False the returned ``"im_applied"`` is False and the allowance
        must be applied downstream.
    include_design:
        Also load the 908.2 HL-93 / HS20 design loads.
    use_standard_db:
        Reference Midas's built-in definitions instead of writing explicit
        axle trains.  Default False: the built-ins are a vendor
        transcription frozen at some past spec revision (Midas's ODOT
        standard box sections are demonstrably out of date), a DB record
        stores only its type name so the API cannot read back what will
        actually be applied, and an unresolved name applies ZERO load
        silently.  The user-defined axle trains come from
        :data:`~civilpy.structural.aashto.vehicles.RATING_VEHICLES`, which
        is checked against BDM Figures 908.3-1..-5.  The two permit loads
        have no DB entry and are always user-defined.
    replace:
        Delete every vehicle already in the model first.

    Returns
    -------
    dict
        ``{"pushed": {id: label}, "im_applied": bool, "user_defined": [...],
        "standard_db": [...]}``.
    """
    from civilpy.structural.aashto.vehicles import (
        BDM_908_RATING_LOADS, RATING_VEHICLES)

    length_unit = model_length_unit(client)
    if replace:
        existing = client.request("GET", "db/mvhl").get("MVHL", {})
        for vid in sorted(existing, key=int, reverse=True):
            client.request("DELETE", f"db/mvhl/{vid}")

    assign, user_defined, standard_db = {}, [], []
    next_id = 1

    def _add(label, body, kind):
        nonlocal next_id
        assign[str(next_id)] = body
        (user_defined if kind == "user" else standard_db).append(label)
        next_id += 1

    # The 908.2 design loads ALWAYS go in as standard-DB records, whatever
    # use_standard_db says.  HL-93 is not a vehicle Midas can be handed as
    # an axle train: LRFD 3.6.1.3.1 superimposes the 0.640 klf design lane
    # ON the truck (or tandem), where a user "Truck/Lane" record takes the
    # ENVELOPE of the two.  Writing HL-93 by hand would understate it by
    # the whole lane component.  Only the code-driven DB entry combines
    # them, so that is what gets pushed.
    if include_design:
        for label, (code, type_name) in BDM_908_DESIGN_DB.items():
            # BDM 924.4.C -- no dynamic load allowance on a lane load
            im = 0.0 if label in BDM_908_LANE_LOADS else im_percent
            _add(label, midas_standard_vehicle(
                type_name, name=label, standard_code=code,
                im_percent=im), "db")

    for name in BDM_908_RATING_LOADS:
        db = BDM_908_STANDARD_DB.get(name) if use_standard_db else None
        if db:
            code, type_name = db
            # BDM 924.4.E -- IM may be ignored for permit loads under
            # controlled conditions
            im = 0.0 if name.startswith("S-PL") else im_percent
            _add(name, midas_standard_vehicle(
                type_name, name=name, standard_code=code,
                im_percent=im), "db")
        else:
            _add(name, midas_vehicle_payload(
                RATING_VEHICLES[name], im_percent=im_percent,
                length_unit=length_unit), "user")

    client.request("PUT", "db/mvhl", {"Assign": assign})
    stored = client.request("GET", "db/mvhl").get("MVHL", {})
    return {
        "pushed": {k: v.get("VEHICLE_LOAD_NAME") for k, v in stored.items()},
        "im_applied": bool(standard_db) and not user_defined,
        "user_defined": user_defined,
        "standard_db": standard_db,
        "design_loads": [n for n in BDM_908_DESIGN_DB if n in standard_db],
        "length_unit": length_unit,
    }
