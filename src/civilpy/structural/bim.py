#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrIM attribute schema: the per-component BIM record the Rhino "source of
truth" model carries as user text, and that MIDAS / quantity estimating read
back.

Every component gets a **typed** attribute set (not the blanket ``gdr.*``):

* shared ``bim.type`` (girder / deck / parapet / bearing / load_plate / haunch /
  shear_stud / rebar / diaphragm) and a unique ``bim.id``;
* where the part is a standard detail, ``bim.scd`` + ``bim.scd_year`` -- the
  highest-value BIM keys, since the SCD implies most of the rest;
* a **pay item** (``pay.*``) so quantities roll straight into an estimate;
* a **material** block (``mat.*``): spec/grade/treatment for steel, f'c/class
  for concrete, coating/size for reinforcing.

Builders return a flat ``{key: str}`` dict ready to write to Rhino user text (or
IFC property sets).  Values are strings so they survive the .3dm round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass


# ── pay items ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PayItem:
    """An ODOT pay item.  ``level`` is the estimating detail level; ``unit`` the
    quantity unit (lb, ea, cy, ft, sf)."""

    code: str
    description: str
    unit: str
    category: str          # leading item number, e.g. "513" structural steel
    level: int = 1


#: Seed catalog. The two studs/steel items are confirmed from Dane; the concrete
#: and reinforcing items are typical ODOT numbers flagged CONFIRM until verified
#: against the current ODOT Construction & Material Specs item master.
PAY_ITEMS: dict[str, PayItem] = {
    "513E10220": PayItem("513E10220", "Structural steel members, Level 1",
                         "lb", "513", 1),
    "513E20000": PayItem("513E20000", "Shear connectors (welded studs)",
                         "ea", "513", 1),
    "509E00200": PayItem("509E00200", "Epoxy coated reinforcing steel [CONFIRM]",
                         "lb", "509", 1),
    "509E00100": PayItem("509E00100", "Reinforcing steel, black [CONFIRM]",
                         "lb", "509", 1),
    "509E00300": PayItem("509E00300", "GFRP deformed bars [CONFIRM]",
                         "lb", "509", 1),
    "511E12100": PayItem("511E12100", "Class QC2 concrete, superstructure (deck) [CONFIRM]",
                         "cy", "511", 1),
    "512E10000": PayItem("512E10000", "Concrete, parapet/railing [CONFIRM]",
                         "cy", "512", 1),
    "516E10000": PayItem("516E10000", "Elastomeric bearing [CONFIRM]",
                         "ea", "516", 1),
    "511E40000": PayItem("511E40000",
                         "Class QC1 concrete, substructure [CONFIRM]",
                         "cy", "511", 1),
    "507E10000": PayItem("507E10000",
                         "Steel piles HP, furnished and driven [CONFIRM]",
                         "ft", "507", 1),
    "515E10000": PayItem("515E10000",
                         "Prestressed concrete box beam member [CONFIRM]",
                         "ea", "515", 1),
    "515E20000": PayItem("515E20000",
                         "Prestressed concrete I-beam member [CONFIRM]",
                         "ea", "515", 1),
    "515E30000": PayItem("515E30000",
                         "Intermediate diaphragms [CONFIRM]",
                         "ea", "515", 1),
    "526E10000": PayItem("526E10000",
                         "Reinforced concrete approach slabs [CONFIRM]",
                         "sy", "526", 1),
    "516E13000": PayItem("516E13000",
                         "Strip seal expansion joint, including gland and extrusions [CONFIRM]",
                         "ft", "516", 1),
    "607E23000": PayItem("607E23000",
                         "Vandal protection fence [CONFIRM]",
                         "ft", "607", 1),
}


def pay_item(code: str) -> PayItem:
    return PAY_ITEMS[code]


#: Planning-level unit prices ($ per pay-item unit) for the seed catalog —
#: round numbers in the range of recent ODOT bid tabulations, meant to rank
#: alternatives and sanity-check a budget, **not** to replace a district
#: estimate.  Override any entry (or add items) through the ``prices``
#: argument of :func:`cost_estimate`.
DEFAULT_UNIT_PRICES: dict[str, float] = {
    "513E10220": 2.25,       # structural steel, fabricated + erected, $/lb
    "513E20000": 10.0,       # welded shear stud, $/ea
    "509E00200": 1.60,       # epoxy coated reinforcing, $/lb
    "509E00100": 1.40,       # black reinforcing, $/lb
    "509E00300": 3.00,       # GFRP deformed bar, $/lb
    "511E12100": 950.0,      # QC2 superstructure (deck) concrete, $/cy
    "511E40000": 850.0,      # QC1 substructure concrete, $/cy
    "512E10000": 1200.0,     # parapet/railing concrete, $/cy
    "516E10000": 2000.0,     # elastomeric bearing, $/ea
    "507E10000": 75.0,       # HP pile furnished + driven, $/ft
    "515E10000": 22000.0,    # PS box beam member, $/ea
    "515E20000": 30000.0,    # PS I-beam member, $/ea
    "515E30000": 1500.0,     # PS intermediate diaphragm, $/ea
    "526E10000": 120.0,      # RC approach slab, $/sy
    "516E13000": 400.0,      # strip seal expansion joint, $/ft [CONFIRM]
    "607E23000": 60.0,       # vandal protection fence, $/ft [CONFIRM]
}


@dataclass(frozen=True)
class CostEstimate:
    """A priced pay-item rollup.  ``rows`` extends the quantity records
    (``{"desc", "unit", "qty", "objects"}``) with ``unit_price`` and
    ``cost``; items the price book doesn't know are listed in ``unpriced``
    (their ``cost`` is ``None``) and excluded from ``total``."""

    rows: dict[str, dict]
    total: float
    unpriced: tuple[str, ...] = ()

    def __str__(self) -> str:
        lines = [f"{'item':<12}{'qty':>14} {'unit':<5}{'unit $':>10}"
                 f"{'cost $':>14}  description"]
        for item, r in self.rows.items():
            up = f"{r['unit_price']:,.2f}" if r["unit_price"] is not None else "--"
            c = f"{r['cost']:,.0f}" if r["cost"] is not None else "--"
            lines.append(f"{item:<12}{r['qty']:>14,.1f} {r['unit']:<5}"
                         f"{up:>10}{c:>14}  {r['desc']}")
        lines.append(f"{'total':<12}{'':>14} {'':<5}{'':>10}"
                     f"{self.total:>14,.0f}")
        return "\n".join(lines)


def cost_estimate(quantities: dict[str, dict],
                  prices: dict[str, float] | None = None) -> CostEstimate:
    """Price a quantity rollup (the ``{item: {"desc", "unit", "qty", ...}}``
    dict that ``pay_item_quantities`` / ``read_bim_quantities`` produce).

    Unit prices come from :data:`DEFAULT_UNIT_PRICES` updated with
    ``prices``; see the caveat there — these are planning numbers."""
    book = {**DEFAULT_UNIT_PRICES, **(prices or {})}
    rows: dict[str, dict] = {}
    total = 0.0
    unpriced: list[str] = []
    for item, rec in sorted(quantities.items()):
        up = book.get(item)
        cost = None if up is None else round(rec["qty"] * up, 2)
        if cost is None:
            unpriced.append(item)
        else:
            total += cost
        rows[item] = {**rec, "unit_price": up, "cost": cost}
    return CostEstimate(rows=rows, total=round(total, 2),
                        unpriced=tuple(unpriced))


def _pay_tags(code: str | None, quantity: float | None = None) -> dict:
    if code is None:
        return {}
    p = PAY_ITEMS.get(code)
    if p is None:
        return {"pay.item": code}
    tags = {"pay.item": p.code, "pay.category": p.category,
            "pay.desc": p.description, "pay.unit": p.unit,
            "pay.level": str(p.level)}
    if quantity is not None:
        tags["pay.qty"] = f"{quantity:g}"
    return tags


# ── material blocks ─────────────────────────────────────────────────────────

def steel_mat(spec: str = "ASTM A709", grade: str = "50W",
              treatment: str = "none") -> dict:
    """Structural-steel material block.  ``grade`` is 36/50/50W/70; ``50W`` and
    ``70W`` are weathering. ``treatment`` = none / galvanized / painted."""
    weathering = grade.upper().endswith("W")
    return {"mat.spec": spec, "mat.grade": grade,
            "mat.type": "weathering steel" if weathering else "carbon steel",
            "mat.treatment": treatment}


def concrete_mat(fc_psi: float, cls: str = "QC2") -> dict:
    """Concrete material block."""
    return {"mat.spec": "concrete", "mat.class": cls,
            "mat.fc_psi": f"{fc_psi:g}"}


def rebar_mat(size: int, coating: str = "epoxy") -> dict:
    """Reinforcing material block.  ``coating`` = epoxy / GFRP / stainless /
    black; ``size`` the bar number (#), diameter in eighths of an inch.
    The tabulated weight is **steel** (C&MS 509); GFRP bars carry the spec
    reference instead (C&MS 705.28) since their weight is producer-specific."""
    dia_in = size / 8.0
    tags = {"rebar.size": f"#{size}", "rebar.dia_in": f"{dia_in:g}",
            "rebar.coating": coating}
    if coating.upper() == "GFRP":
        tags["mat.spec"] = "GFRP, C&MS 705.28"
        return tags
    tags["mat.spec"] = "reinforcing steel"
    weight_plf = {3: 0.376, 4: 0.668, 5: 1.043, 6: 1.502, 7: 2.044,
                  8: 2.670, 9: 3.400, 10: 4.303, 11: 5.313}.get(size)
    if weight_plf is not None:
        tags["rebar.weight_plf"] = f"{weight_plf:g}"
    return tags


#: Reinforcing pay item by coating (see :data:`PAY_ITEMS`).
REBAR_PAY_ITEM = {"epoxy": "509E00200", "black": "509E00100",
                  "gfrp": "509E00300"}


# ── component tag builders ──────────────────────────────────────────────────

def _base(btype: str, bid: str, scd: str | None = None,
          scd_year: str | int | None = None) -> dict:
    tags = {"bim.type": btype, "bim.id": bid}
    if scd is not None:
        tags["bim.scd"] = scd
    if scd_year is not None:
        tags["bim.scd_year"] = str(scd_year)
    return tags


def girder_tags(bid: str, shape: str, *, grade: str = "50W",
                spec: str = "ASTM A709", treatment: str = "none",
                weight_lb: float | None = None) -> dict:
    return {**_base("girder", bid), "girder.shape": shape,
            **steel_mat(spec, grade, treatment),
            **_pay_tags("513E10220", weight_lb)}


def shear_stud_tags(bid: str, *, dia_in: float = 0.875, length_in: float = 6.0,
                    count: int | None = None) -> dict:
    return {**_base("shear_stud", bid), "shear_stud.dia_in": f"{dia_in:g}",
            "shear_stud.length_in": f"{length_in:g}",
            **_pay_tags("513E20000", count)}


def deck_tags(bid: str, *, thickness_in: float, slope_pct: float,
              crown_offset_ft: float, fc_psi: float = 4500.0,
              cls: str = "QC2", volume_cy: float | None = None) -> dict:
    return {**_base("deck", bid), "deck.thickness_in": f"{thickness_in:g}",
            "deck.slope_pct": f"{slope_pct:g}",
            "deck.crown_offset_ft": f"{crown_offset_ft:g}",
            **concrete_mat(fc_psi, cls), **_pay_tags("511E12100", volume_cy)}


def parapet_tags(bid: str, scd: str, *, scd_year: str | int | None = None,
                 height_in: float | None = None, fc_psi: float = 4500.0,
                 length_ft: float | None = None,
                 volume_cy: float | None = None) -> dict:
    tags = {**_base("parapet", bid, scd=scd, scd_year=scd_year),
            **concrete_mat(fc_psi, "QC1"), **_pay_tags("512E10000", volume_cy)}
    if height_in is not None:
        tags["parapet.height_in"] = f"{height_in:g}"
    if length_ft is not None:
        tags["parapet.length_ft"] = f"{length_ft:g}"
    return tags


def approach_slab_tags(bid: str, scd: str = "AS-1-15", *,
                       scd_year: str | int | None = None,
                       length_ft: float, width_ft: float,
                       thickness_in: float, skew_deg: float = 0.0,
                       fc_psi: float = 4500.0,
                       area_sy: float | None = None) -> dict:
    """Approach slab concrete.  ITEM 526 measures the plan **area** (sy)
    and includes the slab reinforcing (anchor bars into the abutment are
    the exception — they measure under the ITEM 509 reinforcing items)."""
    return {**_base("approach_slab", bid, scd=scd, scd_year=scd_year),
            "approach_slab.length_ft": f"{length_ft:g}",
            "approach_slab.width_ft": f"{width_ft:g}",
            "approach_slab.thickness_in": f"{thickness_in:g}",
            "approach_slab.skew_deg": f"{skew_deg:g}",
            **concrete_mat(fc_psi, "QC1"), **_pay_tags("526E10000", area_sy)}


def bearing_tags(bid: str, *, fixity: str, kind: str = "elastomeric",
                 plies: int | None = None, ply_thickness_in: float | None = None,
                 total_thickness_in: float | None = None) -> dict:
    tags = {**_base("bearing", bid), "bearing.kind": kind,
            "bearing.fixity": fixity, **_pay_tags("516E10000", 1)}
    if plies is not None:
        tags["bearing.plies"] = str(plies)
    if ply_thickness_in is not None:
        tags["bearing.ply_thickness_in"] = f"{ply_thickness_in:g}"
    if total_thickness_in is not None:
        tags["bearing.total_thickness_in"] = f"{total_thickness_in:g}"
    return tags


def load_plate_tags(bid: str, *, thickness_in: float, grade: str = "50",
                    spec: str = "ASTM A709", weight_lb: float | None = None) -> dict:
    return {**_base("load_plate", bid), "load_plate.thickness_in": f"{thickness_in:g}",
            **steel_mat(spec, grade), **_pay_tags("513E10220", weight_lb)}


def haunch_tags(bid: str, *, depth_in: float, width_in: float,
                fc_psi: float = 4500.0,
                volume_cy: float | None = None) -> dict:
    """Haunch concrete is conventionally measured with the superstructure
    (deck) concrete item, so a ``volume_cy`` rolls into ``511E12100``."""
    tags = {**_base("haunch", bid), "haunch.depth_in": f"{depth_in:g}",
            "haunch.width_in": f"{width_in:g}", **concrete_mat(fc_psi, "QC2")}
    if volume_cy is not None:
        tags.update(_pay_tags("511E12100", volume_cy))
    return tags


#: Substructure concrete component types (one Rhino layer each).
SUBSTRUCTURE_CONCRETE_TYPES = (
    "pier_cap", "abutment_cap", "beam_seat", "column", "footing",
    "backwall", "wingwall", "foreslope_wall", "cutoff_wall", "headwall", "wall")


def substructure_concrete_tags(btype: str, bid: str, *,
                               fc_psi: float = 4000.0, cls: str = "QC1",
                               volume_cy: float | None = None,
                               **dims: float) -> dict:
    """Tag block for a cast-in-place substructure concrete component.

    ``btype`` is one of :data:`SUBSTRUCTURE_CONCRETE_TYPES`; extra ``dims``
    keywords flatten to ``"<btype>.<key>"`` string tags (e.g.
    ``depth_ft=5.0`` on a ``pier_cap`` becomes ``pier_cap.depth_ft``).
    All substructure concrete measures into the one Class QC1 substructure
    item, the way haunches roll into the deck item."""
    if btype not in SUBSTRUCTURE_CONCRETE_TYPES:
        raise ValueError(f"unknown substructure component type {btype!r}")
    tags = {**_base(btype, bid), **concrete_mat(fc_psi, cls),
            **_pay_tags("511E40000", volume_cy)}
    for k, v in dims.items():
        tags[f"{btype}.{k}"] = f"{v:g}"
    return tags


def box_beam_tags(bid: str, *, box: str, depth_in: float, beam_type: str,
                  part: str, span_ft: float, scd: str | None = "PSBD-1-25",
                  scd_year: str | int | None = 2025,
                  fc_psi: float = 6000.0, n_strands: int | None = None,
                  concrete_cy: float | None = None,
                  count: int | None = None) -> dict:
    """Prestressed box-beam member.  The member is drawn as several
    ``part`` prisms (top/bottom flange, webs) sharing a beam id prefix;
    exactly one part per beam carries ``count`` so the 515 member item
    counts each beam once (strands, tie rods, and precast diaphragms are
    included in the member)."""
    tags = {**_base("box_beam", bid, scd=scd, scd_year=scd_year),
            "box_beam.box": box, "box_beam.depth_in": f"{depth_in:g}",
            "box_beam.beam_type": beam_type, "box_beam.part": part,
            "box_beam.span_ft": f"{span_ft:g}",
            **concrete_mat(fc_psi, "prestressed")}
    if n_strands is not None:
        tags["box_beam.n_strands"] = str(n_strands)
    if concrete_cy is not None:
        tags["box_beam.concrete_cy"] = f"{concrete_cy:g}"
    if count is not None:
        tags.update(_pay_tags("515E10000", count))
    return tags


def ps_i_beam_tags(bid: str, *, section: str, depth_in: float,
                   span_ft: float, scd: str | None = "PSID-1-13",
                   scd_year: str | int | None = 2025,
                   fc_psi: float = 5500.0, n_strands: int | None = None,
                   n_debonded: int | None = None,
                   concrete_cy: float | None = None,
                   count: int | None = None) -> dict:
    """Prestressed I-beam member (PSID-1-13).  One prism per beam; the
    member carries the 515 I-beam item (strands, embedded sole plates,
    and anchorage-zone steel are included in the member per sheet 10)."""
    tags = {**_base("ps_i_beam", bid, scd=scd, scd_year=scd_year),
            "ps_i_beam.section": section,
            "ps_i_beam.depth_in": f"{depth_in:g}",
            "ps_i_beam.span_ft": f"{span_ft:g}",
            **concrete_mat(fc_psi, "prestressed")}
    if n_strands is not None:
        tags["ps_i_beam.n_strands"] = str(n_strands)
    if n_debonded is not None:
        tags["ps_i_beam.n_debonded"] = str(n_debonded)
    if concrete_cy is not None:
        tags["ps_i_beam.concrete_cy"] = f"{concrete_cy:g}"
    if count is not None:
        tags.update(_pay_tags("515E20000", count))
    return tags


def tendon_tags(bid: str, *, strands: int, row_in: float,
                debonded: int | None = None) -> dict:
    """One schematic prestressing-strand row (paid with the member).
    ``debonded`` counts the row's strands debonded at each beam end."""
    tags = {**_base("tendon", bid), "tendon.strands": str(strands),
            "tendon.row_in": f"{row_in:g}",
            "mat.spec": "prestressing strand, AASHTO M203 Gr 270"}
    if debonded:
        tags["tendon.debonded"] = str(debonded)
    return tags


def tie_rod_tags(bid: str, *, diameter_in: float,
                 station_ft: float) -> dict:
    """Transverse tie rod (paid with the members)."""
    return {**_base("tie_rod", bid), "tie_rod.diameter_in": f"{diameter_in:g}",
            "tie_rod.station_ft": f"{station_ft:g}",
            **steel_mat("ASTM A307", "307A")}


def diaphragm_tags(bid: str, *, thickness_in: float, fc_psi: float = 4500.0,
                   volume_cy: float | None = None, pay: bool = True,
                   item: str = "511E12100",
                   count: float | None = None) -> dict:
    """Concrete end/intermediate diaphragm.  Integral and semi-integral
    end diaphragms are cast with (and move with) the superstructure, so
    their concrete measures into the superstructure item like the
    haunches; a box beam's precast diaphragms are included in the member
    (``pay=False``).  A PS I-beam bridge's intermediate diaphragms have
    their own 515 each-measured item (PSID-1-13 sheet 10) — pass
    ``item="515E30000"`` with ``count`` instead of ``volume_cy``."""
    tags = {**_base("diaphragm", bid),
            "diaphragm.thickness_in": f"{thickness_in:g}",
            **concrete_mat(fc_psi, "QC2")}
    if pay:
        tags.update(_pay_tags(item, count if count is not None
                              else volume_cy))
    return tags


def cross_frame_tags(bid: str, *, frame_type: str, member_shape: str,
                     grade: str = "50", weight_lb: float | None = None) -> dict:
    """Intermediate cross-frame / steel diaphragm bay (build plan §3a).  Its
    members are fabricated structural steel measured by weight into the 513
    item like the girders."""
    return {**_base("cross_frame", bid), "cross_frame.type": frame_type,
            "cross_frame.member": member_shape, **steel_mat(grade=grade),
            **_pay_tags("513E10220", weight_lb)}


def stiffener_tags(bid: str, *, kind: str, thickness_in: float,
                   grade: str = "50", weight_lb: float | None = None) -> dict:
    """Web/bearing/longitudinal stiffener plate (§3a).  ``kind`` is
    ``transverse`` / ``bearing`` / ``longitudinal``; measured by weight into
    the 513 structural-steel item."""
    return {**_base("stiffener", bid), "stiffener.kind": kind,
            "stiffener.thickness_in": f"{thickness_in:g}",
            **steel_mat(grade=grade), **_pay_tags("513E10220", weight_lb)}


def field_splice_tags(bid: str, *, bolt_count: int, grade: str = "50",
                      weight_lb: float | None = None) -> dict:
    """Bolted field splice (§3a): the splice plates are structural steel by
    weight (513); the high-strength bolts are incidental, carried as a count."""
    return {**_base("field_splice", bid), "field_splice.bolts": str(bolt_count),
            **steel_mat(grade=grade), **_pay_tags("513E10220", weight_lb)}


def pile_tags(bid: str, *, shape: str, length_ft: float, grade: str = "50",
              spec: str = "ASTM A572") -> dict:
    """Driven steel HP pile: pay quantity is the furnished+driven length
    (ft) below cutoff."""
    return {**_base("pile", bid), "pile.shape": shape,
            "pile.length_ft": f"{length_ft:g}", **steel_mat(spec, grade),
            **_pay_tags("507E10000", length_ft)}


def rebar_tags(bid: str, *, size: int, coating: str = "epoxy", mat: str = "top",
               bend: str = "straight", length_ft: float | None = None,
               scd: str | None = None, spacing_in: float | None = None,
               count: int | None = None, host: str | None = None) -> dict:
    """``spacing_in``/``count``/``host`` describe the *run* this bar belongs
    to (c/c spacing, bars in the run, host component) so a viewer can build
    the construction callout — ``18 #5 bars @ 16" O.C.`` — from the tags of
    any single bar."""
    tags = {**_base("rebar", bid, scd=scd), "rebar.mat": mat,
            "rebar.bend": bend, **rebar_mat(size, coating)}
    if spacing_in is not None:
        tags["rebar.spacing_in"] = f"{spacing_in:g}"
    if count is not None:
        tags["rebar.count"] = str(count)
    if host is not None:
        tags["rebar.host"] = host
    if length_ft is not None:
        tags["rebar.length_ft"] = f"{length_ft:g}"
        item = REBAR_PAY_ITEM.get(coating.lower())
        wpf = tags.get("rebar.weight_plf")
        if item is not None and wpf is not None:
            tags.update(_pay_tags(item, float(wpf) * length_ft))
        elif item is not None:
            # GFRP: item known, weight producer-specific -> qty left off
            tags.update(_pay_tags(item))
    return tags


# ── riveted truss ───────────────────────────────────────────────────────────

#: ``bim.type`` values for the members of a riveted truss span.  Each is its
#: own type (rather than one "truss_member" with a subtype) so the model tree
#: in a viewer groups the way an inspector reads the bridge -- and so the
#: gusset plates, which is where a truss rating usually turns, are one click
#: away.
TRUSS_MEMBER_TYPES = (
    "truss_chord_top", "truss_chord_bottom", "truss_vertical",
    "truss_diagonal", "truss_end_post", "truss_strut",
)

#: Riveted members of the 1900-1940 era are silicon or carbon steel; MBE
#: Table 6A.6.2.1-1 gives Fy 45 / Fu 80 ksi for silicon steel built 1917-1936
#: and Fy 30 / Fu 60 for carbon steel of the same years.
HISTORIC_STEEL = {
    "silicon 1917-1936": (45.0, 80.0),
    "carbon 1917-1936": (30.0, 60.0),
    "carbon pre-1905": (26.0, 52.0),
}


def historic_steel_mat(kind: str = "silicon 1917-1936") -> dict:
    """Material block for an as-built riveted member, with the MBE yield and
    tensile values that a load rating of that vintage uses."""
    fy, fu = HISTORIC_STEEL.get(kind, HISTORIC_STEEL["silicon 1917-1936"])
    return {"mat.spec": "as-built riveted steel", "mat.grade": kind,
            "mat.type": "carbon steel", "mat.treatment": "painted",
            "mat.fy_ksi": f"{fy:g}", "mat.fu_ksi": f"{fu:g}",
            "mat.source": "MBE Table 6A.6.2.1-1"}


def truss_member_tags(bid: str, *, role: str, spec: str,
                      length_ft: float | None = None,
                      weight_lb: float | None = None,
                      line: str | None = None, span: str | None = None,
                      steel: str = "silicon 1917-1936",
                      piece: str | None = None,
                      fabrication: object = None) -> dict:
    """A truss chord / vertical / diagonal / strut.

    ``role`` is one of :data:`TRUSS_MEMBER_TYPES`; ``spec`` the plan-sheet
    built-up shorthand (``"2P24x9/16 4L6x4x3/8"``) that
    :mod:`civilpy.structural.builtup` decomposes.  ``piece`` names the single
    plate or angle leg this solid represents when the member is drawn at
    LOD 400 -- the whole member is then several objects sharing one
    ``bim.id``, and only the first carries the pay quantity so the takeoff
    does not double-count.

    ``fabrication`` is the member's :class:`~civilpy.structural.laced_member.
    LacedMember` -- what the shop actually built, as against the section the
    designer sized.  It is emitted as a ``fab.*`` block so that a member
    drawn at LOD 300, as one enveloping box for a browser, still *records*
    its real makeup: LOD 400 is a statement about the attributes, not only
    about the geometry, and a box labelled with its lacing, tie plates, piece
    counts and fabricated weight carries the information even where drawing
    every bar would not open."""
    if role not in TRUSS_MEMBER_TYPES:
        raise ValueError("unknown truss member role %r; expected one of %s"
                         % (role, ", ".join(TRUSS_MEMBER_TYPES)))
    tags = {**_base(role, bid), "truss.spec": spec,
            **historic_steel_mat(steel)}
    if line is not None:
        tags["truss.line"] = line
    if span is not None:
        tags["truss.span"] = str(span)
    if length_ft is not None:
        tags["truss.length_ft"] = f"{length_ft:.4g}"
    if piece is not None:
        tags["truss.piece"] = piece
    if fabrication is not None:
        tags.update(fabrication_tags(fabrication))
    tags.update(_pay_tags("513E10220", weight_lb))
    return tags


def fabrication_tags(lm) -> dict:
    """The ``fab.*`` block: what the shop built, from a ``LacedMember``.

    Kept compact on purpose -- one line per thing a reviewer would ask about
    (what is the lacing, what ties it, how many pieces, what does it really
    weigh) rather than a dump of every bar."""
    try:
        summary = lm.summary()
    except Exception:
        return {}
    tags = {"fab.pieces": ", ".join(
        "%d %s" % (v["count"], k) for k, v in sorted(summary["pieces"].items()))}
    if getattr(lm, "lacing", None) is not None:
        tags["fab.lacing"] = lm.lacing.label
        if getattr(lm.lacing, "source", ""):
            tags["fab.lacing_source"] = lm.lacing.source
    ties = getattr(lm, "tie_plates", ()) or ()
    if ties:
        t = ties[0]
        tags["fab.tie_plates"] = "%d off %s x %s x %s" % (
            len(ties), _frac_in(t.width_in), _frac_in(t.thickness_in),
            _frac_in(t.length_ft * 12.0))
        if getattr(t, "source", ""):
            tags["fab.tie_plate_source"] = t.source
    tags["fab.rivet_dia_in"] = f"{lm.rivet_dia_in:.4g}"
    tags["fab.rivet_hole_in"] = f"{lm.rivet_hole_in:.4g}"
    tags["fab.bare_lb"] = f"{summary['bare_lb']:.6g}"
    tags["fab.fabricated_lb"] = f"{summary['fabricated_lb']:.6g}"
    tags["fab.buildup_ratio"] = f"{summary['fabricated_lb'] / summary['bare_lb']:.4g}"         if summary["bare_lb"] else "0"
    if getattr(lm, "source", ""):
        tags["fab.source"] = lm.source
    return tags


def _frac_in(v: float) -> str:
    """``21``, ``1/2``, ``46`` -- inches the way a shop bill writes them."""
    whole = int(v)
    rem = v - whole
    # 1/64 in of slack: a length carried as 23.9583 ft is a rounded decimal
    # of 23'-11 1/2", and the bill wrote the fraction, not the decimal.
    for den in (2, 4, 8, 16):
        num = round(rem * den)
        if abs(rem - num / den) < 1.0 / 64.0:
            if num == den:                       # rounded up a whole inch
                return str(whole + 1)
            if num == 0:
                return str(whole)
            if whole == 0:
                return "%d/%d" % (num, den)
            return "%d-%d/%d" % (whole, num, den)
    return f"{v:.4g}"


def gusset_plate_tags(bid: str, *, joint: str, thickness_in: float,
                      face: str = "outside", area_in2: float | None = None,
                      weight_lb: float | None = None,
                      members: str | None = None,
                      t_remaining_in: float | None = None,
                      rating_rf: float | None = None,
                      governing: str | None = None,
                      steel: str = "silicon 1917-1936") -> dict:
    """One gusset plate at one panel point.

    ``joint`` is the panel-point id the plate belongs to and ``face`` which
    side of the truss it is on, so the two plates of a joint are
    distinguishable; ``members`` lists the member ends it connects.
    ``t_remaining_in`` records measured section loss, and ``rating_rf`` /
    ``governing`` carry the rating write-back so a viewer can colour the
    model by rating factor."""
    tags = {**_base("gusset_plate", bid), "gusset.joint": joint,
            "gusset.face": face, "gusset.thickness_in": f"{thickness_in:g}",
            **historic_steel_mat(steel)}
    if members is not None:
        tags["gusset.members"] = members
    if area_in2 is not None:
        tags["gusset.area_in2"] = f"{area_in2:.6g}"
    if t_remaining_in is not None:
        tags["gusset.t_remaining_in"] = f"{t_remaining_in:g}"
        tags["gusset.loss_in"] = f"{thickness_in - t_remaining_in:g}"
    if rating_rf is not None:
        tags["gusset.rf"] = f"{rating_rf:.4g}"
    if governing is not None:
        tags["gusset.governing"] = governing
    tags.update(_pay_tags("513E10220", weight_lb))
    return tags


#: ``bim.type`` values for the floor system and bracing of a truss span.
TRUSS_FRAMING_TYPES = ("floor_beam", "stringer", "lateral_brace",
                       "sway_brace", "portal_brace")


def truss_framing_tags(bid: str, *, role: str, section: str,
                       length_ft: float | None = None,
                       weight_lb: float | None = None,
                       level: str | None = None, span: str | None = None,
                       steel: str = "silicon 1917-1936") -> dict:
    """A floor beam, stringer, or bracing member.  ``level`` distinguishes
    the decks of a two-level floor system (``"upper"`` / ``"utility"``)."""
    if role not in TRUSS_FRAMING_TYPES:
        raise ValueError("unknown truss framing role %r; expected one of %s"
                         % (role, ", ".join(TRUSS_FRAMING_TYPES)))
    tags = {**_base(role, bid), "framing.section": section,
            **historic_steel_mat(steel)}
    if level is not None:
        tags["framing.level"] = level
    if span is not None:
        tags["framing.span"] = str(span)
    if length_ft is not None:
        tags["framing.length_ft"] = f"{length_ft:.4g}"
    tags.update(_pay_tags("513E10220", weight_lb))
    return tags


def panel_point_tags(bid: str, *, joint: str, line: str, span: str,
                     chord: str, pp: int, depth_ft: float | None = None) -> dict:
    """The work-point marker at a panel point: no geometry to pay for, but it
    anchors the joint id that the gusset plates, the member ends and the
    2012 rating tables all key on."""
    tags = {**_base("panel_point", bid), "pp.joint": joint, "pp.line": line,
            "pp.span": str(span), "pp.chord": chord, "pp.index": str(pp)}
    if depth_ft is not None:
        tags["pp.truss_depth_ft"] = f"{depth_ft:.4g}"
    return tags


def rivet_tags(bid: str, *, host: str, diameter_in: float = 1.0,
               grip_in: float | None = None, member: str = "",
               row: int | None = None, col: int | None = None,
               kind: str = "rivet") -> dict:
    """One driven rivet (or the bolt that replaced it) in a connection.

    ``host`` is the ``bim.id`` of the plate it passes through and ``member``
    the member end it connects, so a reviewer can select a member's whole
    rivet group.  Rivets are producer-counted, not measured, so the pay block
    carries the count rather than a length or a weight."""
    tags = {**_base("rivet", bid), "rivet.host": host,
            "rivet.diameter_in": f"{diameter_in:g}", "rivet.kind": kind}
    if member:
        tags["rivet.member"] = member
    if grip_in is not None:
        tags["rivet.grip_in"] = f"{grip_in:g}"
    if row is not None:
        tags["rivet.row"] = str(row)
    if col is not None:
        tags["rivet.col"] = str(col)
    return tags


# -- review overlay ---------------------------------------------------------

def repair_tags(bid: str, *, item: str, target: str, sheet: str = "",
                plan_set: str = "", scope: str = "", status: str = "proposed",
                target_type: str = "", quantity: str = "") -> dict:
    """A proposed repair located on the element it acts on.

    ``item`` is the plan callout (``"LC-1"``, ``"PR/SP-72"``), ``target`` the
    ``bim.id`` it applies to, ``sheet`` where to read it.  Carried both as its
    own overlay object *and* as ``repair.*`` on the target element, so a
    reviewer can either isolate the proposed work or pick a chord and see
    what is being done to it.  No pay block: the overlay is commentary, and
    pricing it here would double-count against the plan quantities."""
    tags = {**_base("repair", bid), "repair.item": item,
            "repair.target": target, "repair.status": status}
    for key, val in (("sheet", sheet), ("plan_set", plan_set),
                     ("scope", scope), ("target_type", target_type),
                     ("quantity", quantity)):
        if val:
            tags["repair." + key] = str(val)
    return tags


def finding_tags(bid: str, *, target: str, summary: str, year: str = "",
                 severity: str = "", source: str = "", element: str = "",
                 condition_state: str = "", quantity: str = "") -> dict:
    """An inspection finding located on the element it was found on.

    ``summary`` is the inspector's words, ``year`` the report, ``source`` the
    document.  Like :func:`repair_tags` this is commentary -- it carries no
    pay block and no material, and it is the *record* of a finding, not an
    assessment of one."""
    tags = {**_base("finding", bid), "finding.target": target,
            "finding.summary": summary}
    for key, val in (("year", year), ("severity", severity),
                     ("source", source), ("element", element),
                     ("condition_state", condition_state),
                     ("quantity", quantity)):
        if val:
            tags["finding." + key] = str(val)
    return tags


def member_piece_tags(bid: str, *, role: str, spec: str, piece_kind: str,
                      label: str, designation: str = "", length_ft: float = None,
                      weight_lb: float = None, face: str = "",
                      source: str = "", line: str = "", span: str = "",
                      steel: str = "silicon 1917-1936") -> dict:
    """One fabricated piece of a built-up member -- a web plate, an angle, a
    cover plate, a lacing bar, a tie plate.

    This is what makes a truss model LOD 400 rather than LOD 300: the member
    is not a prism with a spec written on it, it is the pieces a shop cut and
    riveted, each with its own size, length and catalogue designation, and
    each answerable on its own.  ``source`` records the sheet the dimension
    was read from, so a value that came from a drawing can be told from one
    that did not.

    All the pieces of a member share its ``bim.id``; only the first carries a
    pay quantity so a takeoff does not multiply the member by its piece
    count."""
    tags = {**_base(role, bid), "truss.spec": spec,
            "piece.kind": piece_kind, "piece.label": label,
            **historic_steel_mat(steel)}
    if designation:
        tags["piece.designation"] = designation
    if face:
        tags["piece.face"] = face
    if source:
        tags["piece.source"] = source
    if length_ft is not None:
        tags["piece.length_ft"] = f"{length_ft:.4g}"
    if line:
        tags["truss.line"] = line
    if span:
        tags["truss.span"] = str(span)
    tags.update(_pay_tags("513E10220", weight_lb))
    return tags
