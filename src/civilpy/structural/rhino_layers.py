#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Shared Rhino layer taxonomy for civilpy's ``.3dm`` writers.

Every civilpy module that writes a ``.3dm`` (``rhino_gdr``, ``rhino_deck``,
``rhino_barrier``, ``rhino_box_beam``, and the ODOT SCD Grasshopper
components) should bake into these layers instead of inventing its own
flat names, so a file civilpy writes and the C# ``RhinoODOTExtension``
plugin reads (or vice versa) resolve to the *same* nested layer instead of
silently duplicating it under a differently-spelled one.

**Deck / Superstructure / Substructure are authoritative and pinned to the
C# side** -- transcribed byte-for-byte from
``ODOT Rhino Plugin/Core/Gdr.cs`` (``RhinoODOTExtension`` repo,
commit ``34f7051``, "GirderDeck command + Deck/Superstructure/Substructure
layer groups"). This mirrors NBIS/SNBI's three inspection groups (deck,
superstructure, substructure condition ratings), so the layer tree reads
the way a bridge is actually inspected and the same grouping can carry
straight through to Midas/BrR/AssetWise/IFC element groups later --
that alignment is the point of a shared layer taxonomy, not an
afterthought.

**Culvert and Site are civilpy-side PROPOSED additions** (not yet in
``Gdr.cs``) for the ODOT SCD standard-drawing components that are neither
deck, superstructure, nor substructure: headwalls/box culverts (Culvert)
and off-structure roadway items like approach slabs, portable barrier, and
drainage strips (Site). See the dated "PROPOSED" section in
``docs/Rhino Design Philosophy.md`` for the reconciliation request; do not
treat these two as frozen until the C# side signs off, same as every other
``gdr.*`` contract addition.
"""

# ── existing groups (authoritative -- Gdr.cs) ────────────────────────────

LAYER_DECK_GROUP = "Deck"
LAYER_BRIDGE_DECK = "Deck::Bridge Deck"
LAYER_BARRIERS = "Deck::Traffic Barriers"
LAYER_REBAR = "Deck::Rebar"
LAYER_LANE_MARKINGS = "Deck::Lane Markings"

LAYER_SUPERSTRUCTURE = "Superstructure"
LAYER_GIRDERS = "Superstructure::Girders"
LAYER_SPLICES = "Superstructure::Splices"
LAYER_BEARINGS = "Superstructure::Bearings"
LAYER_DISPLAY = "Superstructure::Display"
LAYER_BOX_BEAMS = "Superstructure::Box Beams"
LAYER_TENDONS = "Superstructure::Tendons"
LAYER_DIAPHRAGMS = "Superstructure::Diaphragms"
LAYER_TIE_RODS = "Superstructure::Tie Rods"

#: Reserved -- no elements are generated yet (matches Gdr.cs's own comment).
LAYER_SUBSTRUCTURE = "Substructure"

# ── PROPOSED groups (civilpy-side; pending C#-side reconciliation) ───────

LAYER_CULVERT = "Culvert"
LAYER_SITE = "Site"

#: PROPOSED leaves for the BCHW headwall/wingwall emit (rhino_bchw).
LAYER_CULVERT_BOX = "Culvert::Box"
LAYER_CULVERT_WINGWALLS = "Culvert::Wingwalls"
LAYER_CULVERT_WALLS = "Culvert::Foreslope Walls"
LAYER_CULVERT_FOOTINGS = "Culvert::Footings"
LAYER_CULVERT_REBAR = "Culvert::Rebar"

#: PROPOSED leaves for the AS-1-15 approach slab emit (rhino_approach_slab):
#: human-readable hierarchy under Deck (the slab rides with the roadway
#: surface), rebar on its own toggleable/estimable sub-layer.
LAYER_APPROACH_SLAB = "Deck::Approach Slab"
LAYER_APPROACH_SLAB_REBAR = "Deck::Approach Slab::Rebar"

#: PROPOSED leaves for the BrIM source-of-truth model (rhino_bim): concrete
#: haunches, welded shear studs, and bearing load plates get their own layers
#: under Superstructure so the composite-connection and bearing hardware can
#: be toggled/estimated independently of the girders.
LAYER_HAUNCHES = "Superstructure::Haunches"
LAYER_SHEAR_STUDS = "Superstructure::Shear Studs"
LAYER_LOAD_PLATES = "Superstructure::Load Plates"

#: PROPOSED leaves for a riveted truss span (:mod:`civilpy.structural.
#: rhino_truss`).  Real superstructure geometry -- unlike the ``Gusset``
#: analysis overlay -- so it lives under Superstructure beside the girder
#: leaves, one layer per member family the way an inspector walks a truss:
#: chords, verticals, diagonals, end posts, the struts across the pier
#: towers, the gusset plates, and the floor system and bracing.
LAYER_TRUSS_CHORDS = "Superstructure::Truss Chords"
LAYER_TRUSS_VERTICALS = "Superstructure::Truss Verticals"
LAYER_TRUSS_DIAGONALS = "Superstructure::Truss Diagonals"
LAYER_TRUSS_END_POSTS = "Superstructure::Truss End Posts"
LAYER_TRUSS_STRUTS = "Superstructure::Truss Struts"
LAYER_GUSSET_PLATES = "Superstructure::Gusset Plates"
LAYER_FLOOR_BEAMS = "Superstructure::Floor Beams"
LAYER_STRINGERS = "Superstructure::Stringers"
LAYER_LATERAL_BRACING = "Superstructure::Lateral Bracing"
LAYER_SWAY_BRACING = "Superstructure::Sway Bracing"
LAYER_PANEL_POINTS = "Superstructure::Panel Points"
LAYER_RIVETS = "Superstructure::Rivets"

#: PROPOSED review overlay (:mod:`civilpy.structural.rhino_truss`): what a
#: proposed repair set touches, and what past inspections found, located on
#: the model instead of described in prose.  Like ``Gusset`` and
#: ``Substructure::STM`` this is an overlay -- non-pay, excluded from every
#: estimate rollup -- and it is deliberately top-level rather than under
#: Superstructure so a reviewer can switch the whole commentary on and off.
LAYER_REVIEW = "Review"
LAYER_REVIEW_REPAIRS = "Review::Proposed Repairs"
LAYER_REVIEW_FINDINGS = "Review::Inspection Findings"

#: PROPOSED leaves under the (reserved) Substructure group, mirroring the
#: Superstructure taxonomy one component per layer: cap beams, the stepped
#: beam seats on top of them, columns, footings, driven piles, abutment
#: backwalls and wingwalls, the substructure reinforcing cage, and an STM
#: layer holding the strut-and-tie *analysis* overlay (non-pay — excluded
#: from every estimate rollup).
LAYER_SUB_CAPS = "Substructure::Caps"
LAYER_SUB_SEATS = "Substructure::Beam Seats"
LAYER_SUB_COLUMNS = "Substructure::Columns"
LAYER_SUB_FOOTINGS = "Substructure::Footings"
LAYER_SUB_PILES = "Substructure::Piles"
LAYER_SUB_BACKWALLS = "Substructure::Backwalls"
LAYER_SUB_WINGWALLS = "Substructure::Wingwalls"
LAYER_SUB_REBAR = "Substructure::Rebar"
LAYER_SUB_STM = "Substructure::STM"
LAYER_SUB_STM_TIES = "Substructure::STM::Ties"
LAYER_SUB_STM_STRUTS = "Substructure::STM::Struts"

#: PROPOSED leaves for the truss gusset-plate rating overlay
#: (:mod:`civilpy.structural.rhino_gusset`).  Like ``Substructure::STM``
#: this is an *analysis* overlay -- non-pay, excluded from every estimate
#: rollup -- and unlike every other group here it is drawn in the plate's
#: own 2-D coordinate system (inches, x right / y up, z the plate normal),
#: not bridge coordinates, so a reviewer can toggle one failure mechanism
#: at a time against the plate outline the way the 2012 rating sheet's failure-plane
#: sheets are drawn.
LAYER_GUSSET = "Gusset"
LAYER_GUSSET_OUTLINE = "Gusset::Outline"
LAYER_GUSSET_FASTENERS = "Gusset::Fasteners"
LAYER_GUSSET_WORKLINES = "Gusset::WorkLines"
LAYER_GUSSET_WHITMORE = "Gusset::Whitmore"
LAYER_GUSSET_UNBRACED = "Gusset::Unbraced"
LAYER_GUSSET_BLOCKSHEAR = "Gusset::BlockShear"
LAYER_GUSSET_SECTIONS = "Gusset::Sections"
LAYER_GUSSET_LOSS = "Gusset::Loss"
LAYER_GUSSET_SCANDEPTH = "Gusset::ScanDepth"
LAYER_GUSSET_TEXT = "Gusset::Text"

#: Default RGBA colors, keyed by full layer path -- kept alongside the path
#: constants so every writer paints the same layer the same color.
DEFAULT_COLORS: dict[str, tuple[int, int, int, int]] = {
    LAYER_DECK_GROUP: (170, 170, 175, 255),
    LAYER_BRIDGE_DECK: (170, 170, 175, 255),
    LAYER_BARRIERS: (150, 150, 155, 255),
    LAYER_REBAR: (60, 120, 200, 255),
    LAYER_LANE_MARKINGS: (245, 225, 70, 255),
    # approach slab reads as light-blue concrete with orange rebar (also
    # the GH component's preview colors — keep them in sync here)
    LAYER_APPROACH_SLAB: (173, 216, 230, 255),
    LAYER_APPROACH_SLAB_REBAR: (255, 140, 0, 255),
    LAYER_SUPERSTRUCTURE: (40, 40, 40, 255),
    LAYER_GIRDERS: (40, 40, 40, 255),
    LAYER_SPLICES: (200, 30, 30, 255),
    LAYER_BEARINGS: (0, 110, 200, 255),
    LAYER_DISPLAY: (110, 125, 140, 255),
    LAYER_BOX_BEAMS: (140, 140, 145, 255),
    LAYER_TENDONS: (200, 160, 20, 255),
    LAYER_DIAPHRAGMS: (100, 100, 180, 255),
    LAYER_TIE_RODS: (180, 60, 60, 255),
    LAYER_SUBSTRUCTURE: (120, 90, 70, 255),
    LAYER_CULVERT: (130, 150, 150, 255),
    LAYER_CULVERT_BOX: (170, 170, 175, 255),
    LAYER_CULVERT_WINGWALLS: (145, 135, 120, 255),
    LAYER_CULVERT_WALLS: (150, 150, 155, 255),
    LAYER_CULVERT_FOOTINGS: (110, 110, 115, 255),
    "Culvert::Headwalls": (150, 150, 155, 255),
    "Culvert::Pipe": (110, 125, 140, 255),
    "Deck::Expansion Joints": (200, 30, 30, 255),
    "Deck::Vandal Fence": (90, 90, 100, 255),
    LAYER_CULVERT_REBAR: (60, 120, 200, 255),
    LAYER_SITE: (150, 140, 120, 255),
    LAYER_HAUNCHES: (200, 200, 190, 255),
    LAYER_SHEAR_STUDS: (200, 120, 40, 255),
    LAYER_LOAD_PLATES: (90, 90, 100, 255),
    # riveted truss: the three member families read apart at a glance, the
    # gusset plates hot so they stand out at every panel point
    LAYER_TRUSS_CHORDS: (55, 70, 90, 255),
    LAYER_TRUSS_VERTICALS: (80, 100, 120, 255),
    LAYER_TRUSS_DIAGONALS: (100, 120, 140, 255),
    LAYER_TRUSS_END_POSTS: (45, 55, 70, 255),
    LAYER_TRUSS_STRUTS: (120, 130, 145, 255),
    LAYER_GUSSET_PLATES: (200, 90, 30, 255),
    LAYER_FLOOR_BEAMS: (90, 110, 100, 255),
    LAYER_STRINGERS: (120, 140, 125, 255),
    LAYER_LATERAL_BRACING: (150, 150, 110, 255),
    LAYER_SWAY_BRACING: (140, 130, 150, 255),
    LAYER_PANEL_POINTS: (230, 200, 60, 255),
    LAYER_RIVETS: (60, 60, 65, 255),
    # review overlay: proposed work hot magenta, past findings amber
    LAYER_REVIEW: (200, 40, 160, 255),
    LAYER_REVIEW_REPAIRS: (220, 40, 170, 255),
    LAYER_REVIEW_FINDINGS: (245, 170, 40, 255),
    LAYER_SUB_CAPS: (155, 145, 130, 255),
    LAYER_SUB_SEATS: (170, 160, 145, 255),
    LAYER_SUB_COLUMNS: (140, 130, 115, 255),
    LAYER_SUB_FOOTINGS: (120, 110, 95, 255),
    LAYER_SUB_PILES: (70, 70, 80, 255),
    LAYER_SUB_BACKWALLS: (150, 140, 125, 255),
    LAYER_SUB_WINGWALLS: (145, 135, 120, 255),
    LAYER_SUB_REBAR: (60, 120, 200, 255),
    LAYER_SUB_STM: (150, 150, 150, 255),
    LAYER_SUB_STM_TIES: (200, 40, 40, 255),
    LAYER_SUB_STM_STRUTS: (40, 80, 200, 255),
    # gusset rating overlay: outline near-black, each failure mechanism its
    # own hue so a screenshot reads without a legend
    LAYER_GUSSET: (40, 40, 40, 255),
    LAYER_GUSSET_OUTLINE: (40, 40, 40, 255),
    LAYER_GUSSET_FASTENERS: (95, 95, 100, 255),
    LAYER_GUSSET_WORKLINES: (0, 110, 200, 255),
    LAYER_GUSSET_WHITMORE: (0, 160, 80, 255),
    LAYER_GUSSET_UNBRACED: (215, 165, 20, 255),
    LAYER_GUSSET_BLOCKSHEAR: (200, 30, 30, 255),
    LAYER_GUSSET_SECTIONS: (150, 60, 180, 255),
    LAYER_GUSSET_LOSS: (170, 80, 20, 255),
    LAYER_GUSSET_SCANDEPTH: (60, 120, 200, 255),
    LAYER_GUSSET_TEXT: (20, 20, 20, 255),
}


def ensure_layer(f, full_path: str, color: tuple = None) -> int:
    """Ensure a nested ``"Group::Leaf"`` layer exists in an offline
    ``rhino3dm.File3dm``, creating any missing parents -- the Python-side
    mirror of the plugin's ``StmDocument.EnsureLayer`` (same "walk the
    ``::``-separated path, create what's missing" logic, since standalone
    ``rhino3dm`` has no ``FindByFullPath``, only parent-scoped
    ``FindName``).  Returns the leaf layer's index.

    ``color`` defaults to :data:`DEFAULT_COLORS`\\ ``[full_path]`` if not
    given and the path is one of the constants above."""
    import rhino3dm as r3

    parts = full_path.split("::")
    parent_id = None
    idx = -1
    accum = ""
    for part in parts:
        accum = part if not accum else f"{accum}::{part}"
        existing = f.Layers.FindName(part, parent_id)
        if existing.Index >= 0:
            idx = existing.Index
        else:
            lyr = r3.Layer()
            lyr.Name = part
            lyr.Color = color or DEFAULT_COLORS.get(accum, (128, 128, 128, 255))
            if parent_id is not None:
                lyr.ParentLayerId = parent_id
            idx = f.Layers.Add(lyr)
        parent_id = f.Layers[idx].Id
    return idx
