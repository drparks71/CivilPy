#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""BrIM tag builders in ``civilpy.structural.bim`` that the Rhino / IFC tests
only touch in passing: the LOD 400 ``member_piece_tags``, ``rivet_tags``, the
review overlay (``repair_tags`` / ``finding_tags``), the riveted-truss family
(gusset, framing, panel point, fabrication block), the prestressed member
tags, the pay-item helpers and the ``CostEstimate`` text table.  Every test
pins the exact ``{key: str}`` payload a builder writes to Rhino user text,
including which optional keys are *absent*, since a viewer keys on them.
"""

import pytest

from civilpy.structural import bim
from civilpy.structural.bim import (
    DEFAULT_UNIT_PRICES,
    HISTORIC_STEEL,
    PAY_ITEMS,
    TRUSS_FRAMING_TYPES,
    TRUSS_MEMBER_TYPES,
    CostEstimate,
    PayItem,
    _frac_in,
    _pay_tags,
    cost_estimate,
    fabrication_tags,
    finding_tags,
    gusset_plate_tags,
    historic_steel_mat,
    member_piece_tags,
    panel_point_tags,
    pay_item,
    repair_tags,
    rivet_tags,
    truss_framing_tags,
    truss_member_tags,
)

STEEL_513 = {"pay.item": "513E10220", "pay.category": "513",
             "pay.desc": "Structural steel members, Level 1",
             "pay.unit": "lb", "pay.level": "1"}
SILICON = {"mat.spec": "as-built riveted steel", "mat.grade": "silicon 1917-1936",
           "mat.type": "carbon steel", "mat.treatment": "painted",
           "mat.fy_ksi": "45", "mat.fu_ksi": "80", "mat.source": "MBE Table 6A.6.2.1-1"}


def _pay_keys(tags):
    return {k for k in tags if k.startswith("pay.")}


# ── member pieces (LOD 400) ────────────────────────────────────────────────

def test_member_piece_tags_full_payload():
    t = member_piece_tags("L0L1", role="truss_chord_bottom", spec="2P24x9/16 4L6x4x3/8",
                          piece_kind="angle", label="L 6 x 4 x 3/8",
                          designation="L6X4X3/8", length_ft=23.9583, weight_lb=300.0,
                          face="near", source="D-3", line="L", span=1)
    assert t == {
        "bim.type": "truss_chord_bottom", "bim.id": "L0L1",
        "truss.spec": "2P24x9/16 4L6x4x3/8",
        "piece.kind": "angle", "piece.label": "L 6 x 4 x 3/8",
        "piece.designation": "L6X4X3/8", "piece.face": "near",
        "piece.source": "D-3", "piece.length_ft": "23.96",
        "truss.line": "L", "truss.span": "1",
        **SILICON, **STEEL_513, "pay.qty": "300",
    }
    assert all(isinstance(v, str) for v in t.values())


def test_member_piece_tags_minimal_omits_optional_keys_but_keeps_pay_block():
    t = member_piece_tags("U0U1", role="truss_chord_top", spec="2P24x9/16",
                          piece_kind="web plate", label="PL 24 x 9/16")
    for k in ("piece.designation", "piece.face", "piece.source", "piece.length_ft",
              "truss.line", "truss.span", "pay.qty"):
        assert k not in t
    assert _pay_keys(t) == set(STEEL_513)                   # item without a quantity
    assert t["bim.id"] == "U0U1" and t["piece.kind"] == "web plate"


def test_member_piece_tags_only_first_piece_carries_the_quantity():
    first = member_piece_tags("L0L1", role="truss_chord_bottom", spec="S", piece_kind="angle",
                              label="a", weight_lb=120.5)
    rest = member_piece_tags("L0L1", role="truss_chord_bottom", spec="S", piece_kind="angle",
                             label="b")
    assert first["bim.id"] == rest["bim.id"]
    assert first["pay.qty"] == "120.5" and "pay.qty" not in rest


def test_member_piece_tags_carbon_steel_material():
    t = member_piece_tags("X", role="truss_vertical", spec="S", piece_kind="angle",
                          label="a", steel="carbon 1917-1936")
    assert (t["mat.fy_ksi"], t["mat.fu_ksi"]) == ("30", "60")
    assert t["mat.grade"] == "carbon 1917-1936"


# ── rivets ─────────────────────────────────────────────────────────────────

def test_rivet_tags_full_payload():
    t = rivet_tags("R-L1-017", host="GP-L1-out", diameter_in=0.875, grip_in=1.5,
                   member="L0L1", row=2, col=3, kind="bolt")
    assert t == {"bim.type": "rivet", "bim.id": "R-L1-017", "rivet.host": "GP-L1-out",
                 "rivet.diameter_in": "0.875", "rivet.kind": "bolt",
                 "rivet.member": "L0L1", "rivet.grip_in": "1.5",
                 "rivet.row": "2", "rivet.col": "3"}


def test_rivet_tags_defaults_and_zero_row_col_are_kept():
    t = rivet_tags("R1", host="GP", row=0, col=0)
    assert t["rivet.diameter_in"] == "1" and t["rivet.kind"] == "rivet"
    assert t["rivet.row"] == "0" and t["rivet.col"] == "0"   # 0 is a real index
    assert "rivet.member" not in t and "rivet.grip_in" not in t
    assert _pay_keys(t) == set()                             # no pay block on a rivet


# ── review overlay ─────────────────────────────────────────────────────────

def test_repair_tags_full_payload_has_no_pay_or_material_block():
    t = repair_tags("RPR-1", item="LC-1", target="L0L1", sheet="S-12",
                    plan_set="2024 rehab", scope="replace lacing", status="approved",
                    target_type="truss_chord_bottom", quantity=3)
    assert t == {"bim.type": "repair", "bim.id": "RPR-1", "repair.item": "LC-1",
                 "repair.target": "L0L1", "repair.status": "approved",
                 "repair.sheet": "S-12", "repair.plan_set": "2024 rehab",
                 "repair.scope": "replace lacing",
                 "repair.target_type": "truss_chord_bottom", "repair.quantity": "3"}
    assert not _pay_keys(t) and not any(k.startswith("mat.") for k in t)


def test_repair_tags_defaults_drop_blank_fields():
    t = repair_tags("RPR-2", item="PR/SP-72", target="U3U4")
    assert t == {"bim.type": "repair", "bim.id": "RPR-2", "repair.item": "PR/SP-72",
                 "repair.target": "U3U4", "repair.status": "proposed"}


def test_finding_tags_full_payload():
    t = finding_tags("FND-7", target="L0L1", summary="section loss at the lower lacing",
                     year=2025, severity="CS3", source="2025 routine inspection",
                     element="107", condition_state="3", quantity="2 ft")
    assert t == {"bim.type": "finding", "bim.id": "FND-7", "finding.target": "L0L1",
                 "finding.summary": "section loss at the lower lacing",
                 "finding.year": "2025", "finding.severity": "CS3",
                 "finding.source": "2025 routine inspection", "finding.element": "107",
                 "finding.condition_state": "3", "finding.quantity": "2 ft"}
    assert not _pay_keys(t)


def test_finding_tags_minimal():
    t = finding_tags("FND-1", target="GP-L1", summary="pack rust")
    assert t == {"bim.type": "finding", "bim.id": "FND-1", "finding.target": "GP-L1",
                 "finding.summary": "pack rust"}


# ── historic steel / truss members / gussets / framing / panel points ──────

def test_historic_steel_mat_values_and_fallback():
    assert HISTORIC_STEEL["silicon 1917-1936"] == (45.0, 80.0)
    assert historic_steel_mat() == SILICON
    pre = historic_steel_mat("carbon pre-1905")
    assert (pre["mat.fy_ksi"], pre["mat.fu_ksi"], pre["mat.grade"]) == ("26", "52", "carbon pre-1905")
    fallback = historic_steel_mat("mystery")
    assert (fallback["mat.fy_ksi"], fallback["mat.fu_ksi"]) == ("45", "80")
    assert fallback["mat.grade"] == "mystery"              # the label is kept


def test_truss_member_tags_role_validation_and_optionals():
    with pytest.raises(ValueError, match="unknown truss member role"):
        truss_member_tags("X", role="truss_hanger", spec="S")
    t = truss_member_tags("L0L1", role="truss_chord_bottom", spec="2P24x9/16",
                          length_ft=23.9583, weight_lb=1500.0, line="L", span=2,
                          piece="web plate")
    assert t["truss.length_ft"] == "23.96" and t["truss.piece"] == "web plate"
    assert (t["truss.line"], t["truss.span"], t["pay.qty"]) == ("L", "2", "1500")
    assert set(TRUSS_MEMBER_TYPES) >= {"truss_chord_top", "truss_end_post", "truss_strut"}


def test_gusset_plate_tags_section_loss_and_rating_write_back():
    t = gusset_plate_tags("GP-L1-out", joint="L1", thickness_in=0.5, face="outside",
                          area_in2=1234.5678, weight_lb=175.0, members="L0L1 L1L2 L1U1",
                          t_remaining_in=0.4375, rating_rf=0.9123456, governing="shear")
    assert t["bim.type"] == "gusset_plate" and t["gusset.joint"] == "L1"
    assert t["gusset.face"] == "outside" and t["gusset.thickness_in"] == "0.5"
    assert t["gusset.area_in2"] == "1234.57"
    assert t["gusset.members"] == "L0L1 L1L2 L1U1"
    assert t["gusset.t_remaining_in"] == "0.4375" and t["gusset.loss_in"] == "0.0625"
    assert t["gusset.rf"] == "0.9123" and t["gusset.governing"] == "shear"
    assert t["pay.qty"] == "175" and t["mat.source"] == "MBE Table 6A.6.2.1-1"
    bare = gusset_plate_tags("GP", joint="L1", thickness_in=0.5)
    for k in ("gusset.members", "gusset.area_in2", "gusset.t_remaining_in",
              "gusset.loss_in", "gusset.rf", "gusset.governing", "pay.qty"):
        assert k not in bare


def test_truss_framing_tags():
    with pytest.raises(ValueError, match="unknown truss framing role"):
        truss_framing_tags("X", role="truss_chord_top", section="W")
    assert set(TRUSS_FRAMING_TYPES) == {"floor_beam", "stringer", "lateral_brace",
                                        "sway_brace", "portal_brace"}
    t = truss_framing_tags("FB-3", role="floor_beam", section="2P30x3/8 4L6x6x1/2",
                           length_ft=28.0, weight_lb=2200.0, level="utility", span=1)
    assert t["bim.type"] == "floor_beam" and t["framing.section"] == "2P30x3/8 4L6x6x1/2"
    assert (t["framing.level"], t["framing.span"], t["framing.length_ft"]) == ("utility", "1", "28")
    assert t["pay.qty"] == "2200" and t["mat.fy_ksi"] == "45"
    bare = truss_framing_tags("S-1", role="stringer", section="S15x42.9")
    assert "framing.level" not in bare and "framing.span" not in bare and "pay.qty" not in bare


def test_panel_point_tags():
    t = panel_point_tags("PP-L3", joint="L3", line="L", span=1, chord="bottom", pp=3,
                         depth_ft=31.25)
    assert t == {"bim.type": "panel_point", "bim.id": "PP-L3", "pp.joint": "L3",
                 "pp.line": "L", "pp.span": "1", "pp.chord": "bottom", "pp.index": "3",
                 "pp.truss_depth_ft": "31.25"}
    assert "pp.truss_depth_ft" not in panel_point_tags("PP", joint="L0", line="L", span="1",
                                                       chord="bottom", pp=0)
    assert not _pay_keys(t)


# ── fabrication block from a (stub) LacedMember ────────────────────────────

class _Lacing:
    label = "single lacing 2-1/2 x 3/8 @ 60 deg"
    source = "D-4"


class _Tie:
    def __init__(self, width_in, thickness_in, length_ft, source=""):
        self.width_in, self.thickness_in, self.length_ft, self.source = (
            width_in, thickness_in, length_ft, source)


class _Laced:
    """The attributes ``fabrication_tags`` reads from a LacedMember."""

    lacing = _Lacing()
    tie_plates = (_Tie(21.0, 0.5, 46.0 / 12.0, "D-4"), _Tie(21.0, 0.5, 46.0 / 12.0))
    rivet_dia_in = 0.875
    rivet_hole_in = 0.9375
    source = "1930 shop bill"

    def summary(self):
        return {"pieces": {"web plate": {"count": 2}, "angle": {"count": 4},
                           "lacing bar": {"count": 40}},
                "bare_lb": 2000.0, "fabricated_lb": 2300.0}


def test_fabrication_tags_from_a_laced_member():
    t = fabrication_tags(_Laced())
    assert t == {
        "fab.pieces": "4 angle, 40 lacing bar, 2 web plate",
        "fab.lacing": "single lacing 2-1/2 x 3/8 @ 60 deg",
        "fab.lacing_source": "D-4",
        "fab.tie_plates": "2 off 21 x 1/2 x 46",
        "fab.tie_plate_source": "D-4",
        "fab.rivet_dia_in": "0.875", "fab.rivet_hole_in": "0.9375",
        "fab.bare_lb": "2000", "fab.fabricated_lb": "2300",
        "fab.buildup_ratio": "1.15", "fab.source": "1930 shop bill",
    }


def test_fabrication_tags_without_lacing_ties_or_sources_and_zero_bare_weight():
    class Plain:
        rivet_dia_in = 1.0
        rivet_hole_in = 1.0625
        lacing = None
        tie_plates = ()

        def summary(self):
            return {"pieces": {"angle": {"count": 2}}, "bare_lb": 0.0, "fabricated_lb": 0.0}

    t = fabrication_tags(Plain())
    assert t["fab.buildup_ratio"] == "0"
    assert "fab.lacing" not in t and "fab.tie_plates" not in t and "fab.source" not in t


def test_fabrication_tags_is_empty_when_the_member_cannot_summarise():
    class Broken:
        def summary(self):
            raise RuntimeError("no section")

    assert fabrication_tags(Broken()) == {}


def test_truss_member_tags_embeds_the_fabrication_block():
    t = truss_member_tags("L0L1", role="truss_chord_bottom", spec="S", fabrication=_Laced())
    assert t["fab.fabricated_lb"] == "2300" and t["fab.pieces"].startswith("4 angle")


@pytest.mark.parametrize("v, s", [(21.0, "21"), (0.5, "1/2"), (46.0, "46"),
                                  (2.5, "2-1/2"), (0.375, "3/8"), (1.9375, "1-15/16"),
                                  (23.9583 * 12 - 23 * 12, "11-1/2"),
                                  (0.999, "1"), (0.3, "5/16"), (0.1, "0.1")])
def test_frac_in_shop_bill_fractions(v, s):
    assert _frac_in(v) == s


# ── pay items, prices, cost table ──────────────────────────────────────────

def test_pay_item_lookup():
    p = pay_item("513E10220")
    assert isinstance(p, PayItem)
    assert (p.unit, p.category, p.level) == ("lb", "513", 1)
    assert pay_item("513E20000").unit == "ea"
    with pytest.raises(KeyError):
        pay_item("000E00000")
    assert set(DEFAULT_UNIT_PRICES) <= set(PAY_ITEMS)


def test_pay_tags_none_and_unknown_codes():
    assert _pay_tags(None) == {}
    assert _pay_tags(None, 5.0) == {}
    assert _pay_tags("999E99999") == {"pay.item": "999E99999"}
    assert _pay_tags("513E20000", 128) == {"pay.item": "513E20000", "pay.category": "513",
                                           "pay.desc": "Shear connectors (welded studs)",
                                           "pay.unit": "ea", "pay.level": "1",
                                           "pay.qty": "128"}


def test_cost_estimate_totals_and_text_table():
    q = {"513E10220": {"desc": "steel", "unit": "lb", "qty": 1000.0, "objects": 2},
         "999E99999": {"desc": "mystery", "unit": "ea", "qty": 3.0, "objects": 3},
         "513E20000": {"desc": "studs", "unit": "ea", "qty": 10.0, "objects": 1}}
    ce = cost_estimate(q, prices={"513E20000": 12.5})
    assert isinstance(ce, CostEstimate)
    assert ce.total == 2250.0 + 125.0
    assert ce.unpriced == ("999E99999",)
    assert ce.rows["999E99999"]["cost"] is None and ce.rows["999E99999"]["unit_price"] is None
    assert ce.rows["513E10220"] == {"desc": "steel", "unit": "lb", "qty": 1000.0,
                                    "objects": 2, "unit_price": 2.25, "cost": 2250.0}
    lines = str(ce).splitlines()
    assert lines[0].startswith("item") and lines[-1].startswith("total")
    assert lines[-1].rstrip().endswith("2,375")
    mystery = next(ln for ln in lines if "mystery" in ln)
    assert mystery.count("--") == 2                          # no unit price, no cost
    steel = next(ln for ln in lines if "  steel" in ln)
    assert "2.25" in steel and "2,250" in steel
