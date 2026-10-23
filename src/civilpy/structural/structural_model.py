#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""The canonical structural model: a pure, IFC-aligned interchange hub.

It is the in-memory analogue of a tagged
``.3dm`` / an IFC file: a discretized structure (nodes, elements, restraints,
loads, results) carrying **3D geometry, full 6-DOF restraints, multiple load
cases, and stable ids** -- everything the lossy 2D
:class:`~civilpy.structural.strut_and_tie.StrutAndTieModel` throws away.

It holds **no solver**.  By design the package's three analysis paradigms
(pin-jointed method of joints, continuous-beam/frame relaxation, external FEM)
solve different math and stay separate; what they share is this *data*.  The
model is the hub; ``rhino_stm``, the MIDAS serializer, ``.3dm`` write-back, the
future IFC adapter, and the capacity calculators are all spokes off it
(composition, not inheritance).  The direct-stiffness frame solver
:mod:`civilpy.structural.frame_analysis` is one more spoke: it reads the
optional :attr:`StructuralModel.section_properties` /
:attr:`~StructuralModel.material_properties` registries, element releases and
beta angles, member loads, initial strains and body forces, and writes
:class:`Result` objects back.

The vocabulary mirrors the IFC 4.3 ``IfcStructuralAnalysisDomain`` so a future
``from_ifc`` / ``to_ifc`` adapter is a direct mapping (see the entity table in
the design doc):

=========================  ===================================================
hub type                   IFC 4.3 entity
=========================  ===================================================
:class:`Node`              ``IfcStructuralPointConnection``
:class:`Restraint`         ``IfcBoundaryNodeCondition``
:class:`Element`           ``IfcStructuralCurveMember``
:class:`Load`              ``IfcStructuralLoadSingleForce`` (point action)
:class:`LoadCase`          ``IfcStructuralLoadCase``
:class:`Result`            ``IfcStructuralResultGroup`` (reactions / forces)
:class:`StructuralModel`   ``IfcStructuralAnalysisModel``
=========================  ===================================================

Units are carried as labels (default **kips / ft**, matching the rest of
``civilpy.structural`` and the Rhino tag contract); actual unit conversion is an
adapter concern (e.g. ``midas.convert_node_units`` already uses the
``civilpy.general.units`` pint registry), so the hub stays dependency-light.

Examples
--------
>>> m = StructuralModel()
>>> a = m.add_node(0, 0, 0, label="A")
>>> b = m.add_node(27, 0, 0, label="B")
>>> _ = m.add_element(a.id, b.id)
>>> m.add_restraint(a.id, preset="pin").to_constraint_string()
'1100000'
>>> m.add_restraint(b.id, preset="roller-v").to_2d()
(False, True)
>>> _ = m.add_load(b.id, fy=-600)
>>> len(m.nodes), len(m.elements), len(m.loads)
(2, 1, 1)
>>> m.check()           # no structural errors in this little model
[]
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Literal

# ── DOF / restraint conventions ───────────────────────────────────────────────

#: Translational + rotational degrees of freedom, in the order used everywhere
#: in the package -- it matches the ``stm.fix_*`` tag suffixes and the first six
#: characters of the MIDAS ``CONS`` constraint string ``DX DY DZ RX RY RZ RW``.
DOF_NAMES = ("x", "y", "z", "rx", "ry", "rz")

#: ``stm.member`` hint values (contract: ``auto`` is the never-written default;
#: ``tie`` / ``strut`` are optional author overrides).
MEMBER_TYPES = ("auto", "tie", "strut", "beam")

#: Friendly support presets, expressed in the **2D analysis-plane** axes the
#: ``stm.support`` contract uses (x = in-plane horizontal, y = in-plane
#: vertical, z = out-of-plane).  An adapter that knows the drawing plane maps
#: these to global 3D DOF; the 2D STM solver consumes ``fix_x`` / ``fix_y``
#: directly.  ``custom`` leaves everything free for explicit ``fix_*`` flags.
SUPPORT_PRESETS = {
    "pin": {"fix_x": True, "fix_y": True},
    "roller-v": {"fix_y": True},
    "roller-h": {"fix_x": True},
    "fixed": {"fix_x": True, "fix_y": True, "fix_rz": True},
    "custom": {},
}


def _new_id() -> str:
    """A fresh stable object id (hex uuid).  Mirrors the ``stm.id`` GUID the C#
    authoring plugin stamps, so ids survive a Rhino -> hub -> Rhino round trip."""
    return uuid.uuid4().hex


# ── Units ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Units:
    """Unit-system *labels* carried with a model (not a converter).

    Defaults match the package convention and the Rhino tag contract (kips /
    feet).  Conversion between systems is an adapter responsibility -- keep the
    hub free of a numeric-units dependency.
    """

    force: str = "kips"
    length: str = "ft"


# ── Geometry / topology ───────────────────────────────────────────────────────


@dataclass
class Node:
    """A connection point -- IFC ``IfcStructuralPointConnection``.

    ``id`` is stable (defaults to a uuid); ``label`` is the human name an
    importer derives (A, B, C…).  Coordinates are full 3D.
    """

    x: float
    y: float
    z: float = 0.0
    label: str | None = None
    id: str = field(default_factory=_new_id)

    @property
    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class Restraint:
    """A nodal boundary condition -- IFC ``IfcBoundaryNodeCondition``.

    Full 6-DOF booleans (``True`` = fixed).  Built directly or from a
    :data:`SUPPORT_PRESETS` name via :meth:`from_preset`.
    """

    node_id: str
    fix_x: bool = False
    fix_y: bool = False
    fix_z: bool = False
    fix_rx: bool = False
    fix_ry: bool = False
    fix_rz: bool = False
    preset: str | None = None

    @classmethod
    def from_preset(cls, node_id: str, preset: str) -> "Restraint":
        """Build a restraint from a friendly preset (``pin``/``roller-v``/
        ``roller-h``/``fixed``/``custom``)."""
        if preset not in SUPPORT_PRESETS:
            raise ValueError(
                f"unknown support preset {preset!r}; "
                f"choose from {sorted(SUPPORT_PRESETS)}"
            )
        return cls(node_id=node_id, preset=preset, **SUPPORT_PRESETS[preset])

    def flags(self) -> tuple[bool, bool, bool, bool, bool, bool]:
        """The six DOF flags in :data:`DOF_NAMES` order."""
        return (self.fix_x, self.fix_y, self.fix_z,
                self.fix_rx, self.fix_ry, self.fix_rz)

    def to_2d(self) -> tuple[bool, bool]:
        """In-plane translational fixity ``(fix_x, fix_y)`` -- what the 2D
        :class:`StrutAndTieModel` / :class:`Truss` solver consumes."""
        return (self.fix_x, self.fix_y)

    def to_constraint_string(self) -> str:
        """The MIDAS ``CONS`` 7-char flag string ``DX DY DZ RX RY RZ RW``
        (``'1'`` = fixed).  Warping (RW) is always ``0`` here.

        >>> Restraint.from_preset("n", "pin").to_constraint_string()
        '1100000'
        >>> Restraint.from_preset("n", "fixed").to_constraint_string()
        '1100010'
        """
        return "".join("1" if f else "0" for f in (*self.flags(), False))


@dataclass
class Element:
    """A member between nodes -- IFC ``IfcStructuralCurveMember`` or ``IfcStructuralSurfaceMember``.

    ``role`` is the typed-component taxonomy (e.g. ``member``, ``top_chord``,
    ``diagonal``) that later drives capacity-check routing and the MIDAS element
    type.  ``member_type`` is the ``stm.member`` hint: ``auto`` (default; the
    solver classifies by sign) or a forced ``tie`` / ``strut``.  ``midas_type``
    is the export element type (``TRUSS`` / ``BEAM`` / ``TENS`` / ``PLATE``).
    """

    node_a: str
    node_b: str
    role: str = "member"
    member_type: str = "auto"
    midas_type: str = "TRUSS"
    section: str | None = None
    material: str | None = None
    id: str = field(default_factory=_new_id)
    # For area elements (Plate/Shell), more than two nodes are needed.
    nodes: list[str] = field(default_factory=list)
    # free-form source tags (e.g. the authoring ``gdr.line`` / ``gdr.id`` /
    # ``stm.id``) preserved through read -> analysis -> write-back.
    metadata: dict = field(default_factory=dict)
    #: end releases ``(i end, j end)`` as 6-char ``x y z rx ry rz`` flag
    #: strings in the element's *local* axes, ``'1'`` = released (the MIDAS
    #: ``FRLS`` FLAG_I / FLAG_J layout without the warping digit).
    releases: tuple[str, str] = ("000000", "000000")
    #: rotation of the local y/z axes about local x, degrees (MIDAS ``ANGLE``,
    #: STAAD ``BETA``); see :mod:`civilpy.structural.frame_analysis` for the
    #: beta-0 local axes.
    beta_deg: float = 0.0

    def __post_init__(self):
        if self.member_type not in MEMBER_TYPES:
            raise ValueError(
                f"member_type must be one of {MEMBER_TYPES}, "
                f"got {self.member_type!r}"
            )
        if not self.nodes:
            self.nodes = [self.node_a, self.node_b]
        if len(self.releases) != 2:
            raise ValueError(f"releases must be (i end, j end), got {self.releases!r}")
        for flags in self.releases:
            if len(flags) != 6 or set(flags) - {"0", "1"}:
                raise ValueError(f"releases must be two 6-char 0/1 strings, "
                                 f"got {self.releases!r}")

    @property
    def is_released(self) -> bool:
        """True when either end releases any DOF."""
        return "1" in "".join(self.releases)


@dataclass(frozen=True)
class SectionProperties:
    """Stiffness properties of a frame section, in the model's units.

    ``iy`` is about the element's local y axis (the major axis of a girder
    whose web lies in the local x-z plane -- MIDAS ``RYY``), ``iz`` about local
    z, ``j`` the torsion constant.  ``asy`` / ``asz`` are shear areas along
    local y / z (0 = no shear deformation).  ``depth`` (along local z) and
    ``width`` (along local y) are the extreme-fiber dimensions used for
    bending stresses; 0 when unknown.  The registry
    :attr:`StructuralModel.section_properties` is keyed by the same label as
    :attr:`Element.section`.
    """

    area: float
    iy: float = 0.0
    iz: float = 0.0
    j: float = 0.0
    asy: float = 0.0
    asz: float = 0.0
    depth: float = 0.0
    width: float = 0.0


@dataclass(frozen=True)
class MaterialProperties:
    """Linear-elastic material, in the model's units (e.g. ksf and kcf for
    kips/ft).  ``g`` defaults from ``e`` and ``poisson``; ``density`` is the
    weight per unit volume used by :class:`BodyForce`."""

    e: float
    poisson: float = 0.3
    density: float = 0.0
    alpha: float = 0.0
    g: float | None = None

    @property
    def shear_modulus(self) -> float:
        return self.g if self.g is not None else self.e / (2.0 * (1.0 + self.poisson))


# ── Loads ─────────────────────────────────────────────────────────────────────


@dataclass
class BeamLoad:
    """A distributed load on a beam element."""

    element_id: str
    w_start: float  # kip/ft (kips for a point load)
    w_end: float | None = None  # if None, uniform
    case: str = "default"
    #: MIDAS load direction: global ``"GX"``/``"GY"``/``"GZ"`` or element
    #: local ``"LX"``/``"LY"``/``"LZ"``.
    direction: Literal["GX", "GY", "GZ", "LX", "LY", "LZ"] = "GZ"
    id: str = field(default_factory=_new_id)
    #: loaded segment as fractions of the element length (MIDAS ``D``
    #: relative distances); a ``point`` load sits at ``start``.
    start: float = 0.0
    end: float = 1.0
    kind: Literal["uniform", "point"] = "uniform"


@dataclass
class LoadCase:
    """A named load case -- IFC ``IfcStructuralLoadCase``."""

    name: str
    description: str = ""
    factor: float = 1.0


@dataclass
class Load:
    """A nodal force/moment -- IFC ``IfcStructuralLoadSingleForce`` applied via a
    point action.  Full 3D force (and optional moment) vector; ``case`` names the
    :class:`LoadCase` it belongs to (default ``"default"``)."""

    node_id: str
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    mx: float = 0.0
    my: float = 0.0
    mz: float = 0.0
    case: str = "default"
    id: str = field(default_factory=_new_id)

    @property
    def force(self) -> tuple[float, float, float]:
        return (self.fx, self.fy, self.fz)


@dataclass
class ElementStrain:
    """An initial (fabrication or thermal) axial strain on an element,
    elongation positive -- the G13.2 Art. 4.1.2 camber strain.  A member made
    ``strain * L`` longer than its geometric length and forced to fit."""

    element_id: str
    strain: float
    case: str = "default"
    id: str = field(default_factory=_new_id)


@dataclass
class BodyForce:
    """Self weight of every element in ``case``: weight per unit length =
    material ``density`` x section ``area``, times the factors along global
    X/Y/Z (``gz=-1`` is gravity in a Z-up model; STAAD ``SELFWEIGHT``, MIDAS
    ``BODF``)."""

    case: str = "default"
    gx: float = 0.0
    gy: float = 0.0
    gz: float = -1.0


@dataclass
class RigidLink:
    """A rigid (master-slave) constraint -- IFC ``IfcRelConnectsStructuralMember``
    with an infinitely stiff connection.

    ``master`` is the retained node; every node in ``slaves`` is tied to it in
    the DOFs flagged in ``dof`` (a 6-char ``DX DY DZ RX RY RZ`` string, ``'1'``
    = constrained).  This is the deck-to-girder tie of a refined grillage: a
    fully rigid link (``"111111"``) makes the slab act compositely with the
    girder (studs/rebar into the deck); constraining vertical/transverse only
    and freeing longitudinal slip models a non-composite interface.  Exports to
    the MIDAS ``/db/RIGD`` table.
    """

    master: str
    slaves: list[str]
    dof: str = "111111"
    id: str = field(default_factory=_new_id)


# ── Results ───────────────────────────────────────────────────────────────────


@dataclass
class Result:
    """Solved results for one load case -- IFC ``IfcStructuralResultGroup``.

    ``element_forces`` maps element id -> axial force (tension positive, the
    package convention).  ``reactions`` maps node id -> a 6-tuple in
    :data:`DOF_NAMES` order.
    """

    case: str = "default"
    element_forces: dict[str, float] = field(default_factory=dict)
    reactions: dict[str, tuple[float, float, float, float, float, float]] = field(
        default_factory=dict
    )
    #: element id -> local end forces ``(Fx, Fy, Fz, Mx, My, Mz)`` at the i end
    #: then the j end, forces *on* the element (a frame solver fills these).
    end_forces: dict[str, tuple[float, ...]] = field(default_factory=dict)
    #: node id -> 6 displacements in :data:`DOF_NAMES` order.
    displacements: dict[str, tuple[float, ...]] = field(default_factory=dict)
    #: solver notes (e.g. DOFs restrained because nothing stiffens them).
    notes: list[str] = field(default_factory=list)


# ── The hub ───────────────────────────────────────────────────────────────────


@dataclass
class StructuralModel:
    """Canonical structural model -- IFC ``IfcStructuralAnalysisModel``.

    A pure data container plus light add/lookup helpers.  No analysis lives
    here; engines and adapters consume or produce it.  Built incrementally:

    >>> m = StructuralModel()
    >>> n = m.add_node(0, 0, label="A")
    >>> m.add_restraint(n.id, preset="pin").to_2d()
    (True, True)
    """

    nodes: dict[str, Node] = field(default_factory=dict)
    elements: dict[str, Element] = field(default_factory=dict)
    restraints: dict[str, Restraint] = field(default_factory=dict)
    loads: list[Load] = field(default_factory=list)
    beam_loads: list[BeamLoad] = field(default_factory=list)
    rigid_links: list[RigidLink] = field(default_factory=list)
    element_strains: list[ElementStrain] = field(default_factory=list)
    body_forces: list[BodyForce] = field(default_factory=list)
    #: stiffness registries keyed by :attr:`Element.section` /
    #: :attr:`Element.material` labels (needed only by frame solvers).
    section_properties: dict[str, SectionProperties] = field(default_factory=dict)
    material_properties: dict[str, MaterialProperties] = field(default_factory=dict)
    load_cases: dict[str, LoadCase] = field(default_factory=dict)
    results: dict[str, Result] = field(default_factory=dict)
    units: Units = field(default_factory=Units)
    #: free-form model-level tags a builder wants to hand downstream (traffic
    #: lane names and offsets, the dead-load breakdown, ...) -- the model-level
    #: counterpart of :attr:`Element.metadata`.
    metadata: dict = field(default_factory=dict)

    # ── Builders ────────────────────────────────────────────────────────────

    def add_node(self, x: float, y: float, z: float = 0.0, *,
                 label: str | None = None, id: str | None = None) -> Node:
        node = Node(float(x), float(y), float(z), label=label,
                    **({"id": id} if id else {}))
        self.nodes[node.id] = node
        return node

    def add_element(self, node_a: str, node_b: str, *, role: str = "member",
                    member_type: str = "auto", midas_type: str = "TRUSS",
                    section: str | None = None, material: str | None = None,
                    nodes: list[str] | None = None,
                    id: str | None = None,
                    releases: tuple[str, str] = ("000000", "000000"),
                    beta_deg: float = 0.0) -> Element:
        element_nodes = nodes if nodes else [node_a, node_b]
        for n in element_nodes:
            if n not in self.nodes:
                raise KeyError(f"element references unknown node id {n!r}")
        elem = Element(node_a, node_b, role=role, member_type=member_type,
                       midas_type=midas_type, section=section,
                       material=material, nodes=element_nodes,
                       releases=releases, beta_deg=float(beta_deg),
                       **({"id": id} if id else {}))
        self.elements[elem.id] = elem
        return elem

    def add_restraint(self, node_id: str, *, preset: str | None = None,
                      **flags: bool) -> Restraint:
        """Restrain a node, by ``preset`` and/or explicit ``fix_*`` flags.
        Explicit flags override the preset (matching the tag contract)."""
        if node_id not in self.nodes:
            raise KeyError(f"restraint references unknown node id {node_id!r}")
        if preset is not None:
            restraint = Restraint.from_preset(node_id, preset)
            if flags:
                restraint = replace(restraint, **flags)
        else:
            restraint = Restraint(node_id=node_id, **flags)
        self.restraints[node_id] = restraint
        return restraint

    def add_load(self, node_id: str, *, fx: float = 0.0, fy: float = 0.0,
                 fz: float = 0.0, mx: float = 0.0, my: float = 0.0,
                 mz: float = 0.0, case: str = "default",
                 id: str | None = None) -> Load:
        if node_id not in self.nodes:
            raise KeyError(f"load references unknown node id {node_id!r}")
        if case not in self.load_cases:
            self.load_cases[case] = LoadCase(name=case)
        load = Load(node_id, fx=fx, fy=fy, fz=fz, mx=mx, my=my, mz=mz,
                    case=case, **({"id": id} if id else {}))
        self.loads.append(load)
        return load

    def add_rigid_link(self, master: str, slaves: list[str], *,
                       dof: str = "111111", id: str | None = None) -> RigidLink:
        """Tie ``slaves`` to ``master`` rigidly in the DOFs flagged in ``dof``
        (6-char ``DX DY DZ RX RY RZ``).  Used for the deck-to-girder composite
        connection in a refined grillage (see :class:`RigidLink`)."""
        for nid in (master, *slaves):
            if nid not in self.nodes:
                raise KeyError(f"rigid link references unknown node id {nid!r}")
        link = RigidLink(master, list(slaves), dof=dof,
                         **({"id": id} if id else {}))
        self.rigid_links.append(link)
        return link

    def add_beam_load(self, element_id: str, w_start: float,
                      w_end: float | None = None, *,
                      case: str = "default",
                      direction: Literal["GX", "GY", "GZ", "LX", "LY", "LZ"] = "GZ",
                      id: str | None = None, start: float = 0.0,
                      end: float = 1.0,
                      kind: Literal["uniform", "point"] = "uniform") -> BeamLoad:
        if element_id not in self.elements:
            raise KeyError(f"beam load references unknown element id {element_id!r}")
        if not 0.0 <= start <= end <= 1.0 and kind == "uniform":
            raise ValueError("need 0 <= start <= end <= 1 (fractions of the length)")
        if case not in self.load_cases:
            self.load_cases[case] = LoadCase(name=case)
        load = BeamLoad(element_id, w_start=w_start, w_end=w_end,
                        case=case, direction=direction, start=float(start),
                        end=float(end), kind=kind,
                        **({"id": id} if id else {}))
        self.beam_loads.append(load)
        return load

    def add_element_strain(self, element_id: str, strain: float, *,
                           case: str = "default") -> ElementStrain:
        """Initial axial strain (elongation positive) on an element."""
        if element_id not in self.elements:
            raise KeyError(f"strain references unknown element id {element_id!r}")
        if case not in self.load_cases:
            self.load_cases[case] = LoadCase(name=case)
        es = ElementStrain(element_id, float(strain), case=case)
        self.element_strains.append(es)
        return es

    def add_body_force(self, case: str = "default", *, gx: float = 0.0,
                       gy: float = 0.0, gz: float = -1.0) -> BodyForce:
        """Self weight of every element in ``case`` (see :class:`BodyForce`)."""
        if case not in self.load_cases:
            self.load_cases[case] = LoadCase(name=case)
        bf = BodyForce(case, gx=gx, gy=gy, gz=gz)
        self.body_forces.append(bf)
        return bf

    # ── Lookup ──────────────────────────────────────────────────────────────

    def node_by_label(self, label: str) -> Node:
        for node in self.nodes.values():
            if node.label == label:
                return node
        raise KeyError(f"no node labeled {label!r}")

    def loads_in_case(self, case: str = "default") -> list[Load]:
        return [load for load in self.loads if load.case == case]

    def beam_loads_in_case(self, case: str = "default") -> list[BeamLoad]:
        return [load for load in self.beam_loads if load.case == case]

    def cases(self) -> list[str]:
        """Load-case names actually used by loads (plus any registered)."""
        used = ({load.case for load in self.loads}
                | {load.case for load in self.beam_loads}
                | {s.case for s in self.element_strains}
                | {b.case for b in self.body_forces}
                | set(self.load_cases))
        return sorted(used)

    # ── Integrity ─────────────────────────────────────────────────────────────

    def check(self) -> list[str]:
        """Return a list of structural-integrity problems (empty = clean).

        Pure, geometry-level checks an importer can run *before* handing the
        model to a solver -- they name the offending object, unlike the generic
        determinacy error the solver raises later.  Flags: elements pointing at
        missing nodes, restraints/loads on missing nodes, zero-length elements,
        a model with no restraints, and nodes that no element touches.
        """
        problems: list[str] = []
        node_ids = set(self.nodes)
        touched: set[str] = set()

        for eid, e in self.elements.items():
            for n in e.nodes:
                if n not in node_ids:
                    problems.append(f"element {eid}: unknown node {n!r}")
            touched.update(e.nodes)
            if e.node_a == e.node_b:
                problems.append(f"element {eid}: zero-length (same node both ends)")
            elif e.node_a in node_ids and e.node_b in node_ids:
                if self.nodes[e.node_a].coords == self.nodes[e.node_b].coords:
                    problems.append(f"element {eid}: coincident end nodes")

        for nid in self.restraints:
            if nid not in node_ids:
                problems.append(f"restraint on unknown node {nid!r}")
        for load in self.loads:
            if load.node_id not in node_ids:
                problems.append(f"load {load.id}: unknown node {load.node_id!r}")

        if self.nodes and not self.restraints:
            problems.append("model has no restraints -- it is a mechanism")
        for nid in node_ids - touched:
            label = self.nodes[nid].label or nid
            problems.append(f"node {label}: not connected to any element")

        return problems

    def __repr__(self):
        return (f"<StructuralModel {len(self.nodes)} nodes, "
                f"{len(self.elements)} elements, {len(self.restraints)} "
                f"restraints, {len(self.loads)} loads, "
                f"{len(self.cases())} case(s)>")
