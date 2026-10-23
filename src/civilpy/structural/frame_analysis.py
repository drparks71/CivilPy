"""Linear-elastic 3-D frame / truss solver that reads the
:class:`~civilpy.structural.structural_model.StructuralModel` hub.

This is the direct-stiffness spoke off the hub: the same model the MIDAS
serializer, the Rhino readers and the capacity checks share is solved here
without an external program, so a truss can be analyzed with pinned or rigid
joints (secondary moments, AASHTO/NSBA G13.2 Art. 3.5.10), with fabrication
camber strains (G13.2 Art. 4.1.2), or as a full 3-D bridge model.

Model
-----
* Global axes are **Z-up** (the MIDAS convention the hub uses).
* Element local axes at beta = 0 follow MIDAS (and, through
  :func:`civilpy.structural.staad.staad_to_midas_xyz`, STAAD): local x runs
  i -> j; for a non-vertical element local y = Z x x (horizontal) and
  local z = x x y (upward); for a vertical element local y = global +Y.  The
  element's ``beta_deg`` then rotates y and z about x.
* ``SectionProperties.iy`` resists bending in the local x-z plane (``uz`` /
  ``ry``), ``iz`` bending in the x-y plane; shear areas add Timoshenko shear
  deformation.
* ``midas_type`` ``TRUSS`` / ``TENS`` elements are axial only (``TENS`` is
  *not* solved as tension-only -- this is a linear solver); every other line
  element is a 12-DOF beam.  End releases (local flags) are removed by static
  condensation.  A release of the same translation or of torsion at *both*
  ends would leave the element a mechanism, so the j-end release is ignored
  there (as MIDAS and the STAAD adapter do).
* Member loads (uniform or trapezoidal over a segment, or concentrated; global
  or local direction, per unit member length) become consistent nodal loads;
  :class:`~civilpy.structural.structural_model.BodyForce` gives self weight
  from material density x area; :class:`~civilpy.structural.structural_model.
  ElementStrain` gives initial (camber / thermal) axial strains.
* Rigid links tie slave DOFs to the master by rigid-body kinematics.
* DOFs that nothing stiffens (rotations at a node reached only by truss
  elements or fully released ends) are restrained and reported in
  ``Result.notes`` -- they carry no load either way.

Units are whatever the model is in (kips/ft with E in ksf for the hub
default); nothing is converted.

Examples
--------
A propped cantilever, 20 ft, EI from a W-shape-like section, 1 klf:

>>> from civilpy.structural.structural_model import (
...     StructuralModel, SectionProperties, MaterialProperties)
>>> m = StructuralModel()
>>> a, b = m.add_node(0, 0, 0), m.add_node(20, 0, 0)
>>> m.section_properties["S"] = SectionProperties(area=0.1, iy=0.05, iz=0.01, j=0.001)
>>> m.material_properties["steel"] = MaterialProperties(e=4.176e6)
>>> e = m.add_element(a.id, b.id, midas_type="BEAM", section="S", material="steel")
>>> _ = m.add_restraint(a.id, fix_x=True, fix_y=True, fix_z=True, fix_rx=True,
...                     fix_ry=True, fix_rz=True)
>>> _ = m.add_restraint(b.id, fix_y=True, fix_z=True)
>>> _ = m.add_beam_load(e.id, -1.0)
>>> r = solve(m)["default"]
>>> round(r.reactions[b.id][2], 3)          # 3wL/8
7.5
>>> round(r.end_forces[e.id][4], 3)         # wL^2/8 at the fixed end (on the element)
-50.0
>>> round(end_moments(r, e.id)[0], 3)       # sagging positive: hogging at the wall
-50.0
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from civilpy.structural.structural_model import (
    Result,
    StructuralModel,
)

AXIAL_ONLY = ("TRUSS", "TENS", "COMP")

_GAUSS_X, _GAUSS_W = np.polynomial.legendre.leggauss(5)


# ── Element geometry ─────────────────────────────────────────────────────────


def local_axes(pi, pj, beta_deg: float = 0.0, tol: float = 1e-9) -> np.ndarray:
    """3x3 rotation matrix whose rows are the element's local x, y, z unit
    vectors in global (Z-up) coordinates -- see the module docstring."""
    pi, pj = np.asarray(pi, float), np.asarray(pj, float)
    d = pj - pi
    length = float(np.linalg.norm(d))
    if length <= tol:
        raise ValueError("zero-length element")
    ex = d / length
    horiz = math.hypot(ex[0], ex[1])
    if horiz <= tol:                                    # vertical element
        ey = np.array([0.0, 1.0, 0.0])
    else:
        ey = np.cross([0.0, 0.0, 1.0], ex)
        ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    if beta_deg:
        c, s = math.cos(math.radians(beta_deg)), math.sin(math.radians(beta_deg))
        ey, ez = c * ey + s * ez, -s * ey + c * ez
    return np.vstack([ex, ey, ez])


def beta_for_normal(pi, pj, normal, tol: float = 1e-9) -> float:
    """Beta angle (degrees) that turns the element's local y axis onto
    ``normal`` (projected square to the element) -- e.g. a section whose
    width runs along a truss-plane normal.  0 when ``normal`` is parallel
    to the element."""
    r = local_axes(pi, pj, 0.0)
    n = np.asarray(normal, float)
    n = n - r[0] * (n @ r[0])
    if np.linalg.norm(n) <= tol:
        return 0.0
    return math.degrees(math.atan2(n @ r[2], n @ r[1]))


def _transform(rot: np.ndarray) -> np.ndarray:
    t = np.zeros((12, 12))
    for k in range(4):
        t[3 * k:3 * k + 3, 3 * k:3 * k + 3] = rot
    return t


def beam_stiffness(length, e, g, area, iy, iz, j, asy=0.0, asz=0.0) -> np.ndarray:
    """12x12 local stiffness of a 3-D Timoshenko beam, DOFs
    ``(ux uy uz rx ry rz)`` at i then j."""
    L = float(length)
    k = np.zeros((12, 12))
    ea, gj = e * area / L, g * j / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj
    # bending in x-y (uy, rz) on iz
    phy = 12 * e * iz / (g * asy * L * L) if asy and iz else 0.0
    c = e * iz / ((1 + phy) * L ** 3)
    idx = (1, 5, 7, 11)
    m = np.array([[12, 6 * L, -12, 6 * L],
                  [6 * L, (4 + phy) * L * L, -6 * L, (2 - phy) * L * L],
                  [-12, -6 * L, 12, -6 * L],
                  [6 * L, (2 - phy) * L * L, -6 * L, (4 + phy) * L * L]]) * c
    k[np.ix_(idx, idx)] += m
    # bending in x-z (uz, ry) on iy
    phz = 12 * e * iy / (g * asz * L * L) if asz and iy else 0.0
    c = e * iy / ((1 + phz) * L ** 3)
    idx = (2, 4, 8, 10)
    m = np.array([[12, -6 * L, -12, -6 * L],
                  [-6 * L, (4 + phz) * L * L, 6 * L, (2 - phz) * L * L],
                  [-12, 6 * L, 12, 6 * L],
                  [-6 * L, (2 - phz) * L * L, 6 * L, (4 + phz) * L * L]]) * c
    k[np.ix_(idx, idx)] += m
    return k


def truss_stiffness(length, e, area) -> np.ndarray:
    k = np.zeros((12, 12))
    ea = e * area / float(length)
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea
    return k


def _hermite(xi, L):
    return np.array([1 - 3 * xi ** 2 + 2 * xi ** 3,
                     L * (xi - 2 * xi ** 2 + xi ** 3),
                     3 * xi ** 2 - 2 * xi ** 3,
                     L * (-xi ** 2 + xi ** 3)])


def member_load_vector(length, q_local_start, q_local_end=None, start=0.0,
                       end=1.0, point=False, axial_only=False) -> np.ndarray:
    """Consistent 12-vector of nodal loads (local) for a member load.

    ``q_local_*`` are ``(qx, qy, qz)`` in local axes per unit length (or the
    force of a point load at ``start``); linear variation from start to end
    of the loaded segment.  An axial-only element receives the simple-beam
    end shears instead (no rotational DOFs)."""
    L = float(length)
    qa = np.asarray(q_local_start, float)
    qb = qa if q_local_end is None else np.asarray(q_local_end, float)
    f = np.zeros(12)

    def add(xi, q, w):
        if axial_only:
            f[0:3] += (1 - xi) * q * w
            f[6:9] += xi * q * w
            return
        f[0] += (1 - xi) * q[0] * w
        f[6] += xi * q[0] * w
        n = _hermite(xi, L)
        f[1] += n[0] * q[1] * w
        f[5] += n[1] * q[1] * w
        f[7] += n[2] * q[1] * w
        f[11] += n[3] * q[1] * w
        f[2] += n[0] * q[2] * w
        f[4] -= n[1] * q[2] * w
        f[8] += n[2] * q[2] * w
        f[10] -= n[3] * q[2] * w

    if point:
        add(start, qa, 1.0)
        return f
    a, b = start * L, end * L
    if b <= a:
        return f
    for x, w in zip(_GAUSS_X, _GAUSS_W):
        s = (a + b) / 2 + (b - a) / 2 * x
        t = (s - a) / (b - a)
        add(s / L, qa + (qb - qa) * t, w * (b - a) / 2)
    return f


def _effective_releases(rel_i: str, rel_j: str) -> list[int]:
    """Local DOF indices (0-11) to condense out; a translation or torsion
    released at both ends keeps the j end (else the element is a mechanism)."""
    out = [k for k, c in enumerate(rel_i) if c == "1"]
    for k, c in enumerate(rel_j):
        if c != "1":
            continue
        if k in (0, 1, 2, 3) and rel_i[k] == "1":
            continue
        out.append(6 + k)
    return out


def condense(k: np.ndarray, p: np.ndarray, released: list[int]):
    """Static condensation of ``released`` local DOFs: returns the 12x12
    stiffness and 12-load with those rows/columns zeroed, plus the recovery
    pair ``(Krr^-1 Krk, Krr^-1 Pr)`` so ``u_r = b - A u_k``."""
    if not released:
        return k, p, None
    r = np.array(released)
    kept = np.array([i for i in range(12) if i not in set(released)])
    krr = k[np.ix_(r, r)]
    krk = k[np.ix_(r, kept)]
    inv = np.linalg.inv(krr)
    a = inv @ krk
    b = inv @ p[r]
    kc = np.zeros_like(k)
    pc = np.zeros_like(p)
    kc[np.ix_(kept, kept)] = k[np.ix_(kept, kept)] - k[np.ix_(kept, r)] @ a
    pc[kept] = p[kept] - k[np.ix_(kept, r)] @ b
    return kc, pc, (r, kept, a, b)


# ── Assembly and solution ────────────────────────────────────────────────────


class _Elem:
    __slots__ = ("id", "ni", "nj", "rot", "length", "k", "axial", "released",
                 "props", "dofs")


def _resolve(model: StructuralModel, e):
    if e.section is None or e.section not in model.section_properties:
        raise KeyError(f"element {e.id}: no SectionProperties for section "
                       f"{e.section!r}")
    sec = model.section_properties[e.section]
    if e.material is not None:
        if e.material not in model.material_properties:
            raise KeyError(f"element {e.id}: no MaterialProperties for "
                           f"{e.material!r}")
        mat = model.material_properties[e.material]
    elif len(model.material_properties) == 1:
        mat = next(iter(model.material_properties.values()))
    else:
        raise KeyError(f"element {e.id}: no material label and the model has "
                       f"{len(model.material_properties)} materials")
    return sec, mat


def _elements(model: StructuralModel, index: dict[str, int]):
    out = []
    plates = [e.id for e in model.elements.values() if len(e.nodes) > 2
              or e.midas_type == "PLATE"]
    if plates:
        raise ValueError(f"frame_analysis solves line elements only; "
                         f"{len(plates)} plate element(s), e.g. {plates[0]}")
    for e in model.elements.values():
        sec, mat = _resolve(model, e)
        el = _Elem()
        el.id = e.id
        el.ni, el.nj = index[e.node_a], index[e.node_b]
        pi, pj = model.nodes[e.node_a].coords, model.nodes[e.node_b].coords
        el.rot = local_axes(pi, pj, e.beta_deg)
        el.length = math.dist(pi, pj)
        el.axial = e.midas_type.upper() in AXIAL_ONLY
        el.props = (sec, mat)
        if el.axial:
            el.k = truss_stiffness(el.length, mat.e, sec.area)
            el.released = []
        else:
            el.k = beam_stiffness(el.length, mat.e, mat.shear_modulus,
                                  sec.area, sec.iy, sec.iz, sec.j,
                                  sec.asy, sec.asz)
            el.released = _effective_releases(*e.releases)
        el.dofs = np.r_[6 * el.ni:6 * el.ni + 6, 6 * el.nj:6 * el.nj + 6]
        out.append(el)
    return out


def _case_loads(model: StructuralModel, elems, index, case: str, ndof: int):
    """Global nodal load vector plus per-element local fixed-end vectors."""
    f = np.zeros(ndof)
    fixed = {}
    by_id = {el.id: el for el in elems}
    for ld in model.loads_in_case(case):
        n = index[ld.node_id]
        f[6 * n:6 * n + 6] += (ld.fx, ld.fy, ld.fz, ld.mx, ld.my, ld.mz)

    def put(el, vec):
        fixed[el.id] = fixed.get(el.id, np.zeros(12)) + vec

    for bl in model.beam_loads_in_case(case):
        el = by_id[bl.element_id]
        w0 = bl.w_start
        w1 = bl.w_end if bl.w_end is not None else bl.w_start
        axis = "XYZ".index(bl.direction[1])
        if bl.direction[0] == "G":
            ga, gb = np.zeros(3), np.zeros(3)
            ga[axis], gb[axis] = w0, w1
            qa, qb = el.rot @ ga, el.rot @ gb
        else:
            qa, qb = np.zeros(3), np.zeros(3)
            qa[axis], qb[axis] = w0, w1
        put(el, member_load_vector(el.length, qa, qb, bl.start, bl.end,
                                   point=bl.kind == "point",
                                   axial_only=el.axial))
    for bf in (b for b in model.body_forces if b.case == case):
        g = np.array([bf.gx, bf.gy, bf.gz])
        for el in elems:
            sec, mat = el.props
            q = el.rot @ (g * mat.density * sec.area)
            put(el, member_load_vector(el.length, q, axial_only=el.axial))
    for es in (s for s in model.element_strains if s.case == case):
        el = by_id[es.element_id]
        sec, mat = el.props
        n0 = mat.e * sec.area * es.strain
        vec = np.zeros(12)
        vec[0], vec[6] = -n0, n0
        put(el, vec)
    return f, fixed


def _link_transform(model: StructuralModel, index, ndof):
    """Sparse T with u = T q for the rigid links (identity without links)."""
    if not model.rigid_links:
        return None
    rows, cols, vals = [], [], []
    slaved = {}
    for link in model.rigid_links:
        m = index[link.master]
        pm = np.array(model.nodes[link.master].coords)
        for s_id in link.slaves:
            s = index[s_id]
            r = np.array(model.nodes[s_id].coords) - pm
            for k, c in enumerate(link.dof):
                if c != "1":
                    continue
                expr = {6 * m + k: 1.0}
                if k < 3:
                    # u_s = u_m + theta_m x r
                    cross = {0: ((4, r[2]), (5, -r[1])),
                             1: ((5, r[0]), (3, -r[2])),
                             2: ((3, r[1]), (4, -r[0]))}[k]
                    for rk, coef in cross:
                        expr[6 * m + rk] = expr.get(6 * m + rk, 0.0) + coef
                slaved[6 * s + k] = expr
    free = [d for d in range(ndof) if d not in slaved]
    col_of = {d: i for i, d in enumerate(free)}
    for d in range(ndof):
        if d in slaved:
            for md, coef in slaved[d].items():
                if md in slaved:
                    raise ValueError("a rigid-link master is itself a slave")
                rows.append(d); cols.append(col_of[md]); vals.append(coef)
        else:
            rows.append(d); cols.append(col_of[d]); vals.append(1.0)
    return sp.csr_matrix((vals, (rows, cols)), shape=(ndof, len(free)))


def solve(model: StructuralModel, cases=None, *, store: bool = True,
          tol: float = 1e-9, spring: float = 1e-10) -> dict[str, Result]:
    """Solve every load case (or the named ``cases``) and return
    ``{case: Result}`` with displacements, reactions, local end forces and the
    axial force per element (tension positive, at the i end).  ``store``
    also writes the results into ``model.results``."""
    node_ids = list(model.nodes)
    index = {nid: k for k, nid in enumerate(node_ids)}
    ndof = 6 * len(node_ids)
    elems = _elements(model, index)

    rows, cols, vals = [], [], []
    for el in elems:
        kc, _, _ = condense(el.k, np.zeros(12), el.released)
        t = _transform(el.rot)
        kg = t.T @ kc @ t
        r, c = np.meshgrid(el.dofs, el.dofs, indexing="ij")
        rows.append(r.ravel()); cols.append(c.ravel()); vals.append(kg.ravel())
    k = sp.csr_matrix((np.concatenate(vals) if vals else [],
                       (np.concatenate(rows) if rows else [],
                        np.concatenate(cols) if cols else [])),
                      shape=(ndof, ndof))

    restrained = np.zeros(ndof, bool)
    for nid, rs in model.restraints.items():
        n = index[nid]
        restrained[6 * n:6 * n + 6] |= np.array(rs.flags())

    tmat = _link_transform(model, index, ndof)
    kr = (tmat.T @ k @ tmat).tocsr() if tmat is not None else k
    nq = kr.shape[0]
    fixed_q = np.zeros(nq, bool)
    if tmat is None:
        fixed_q[:] = restrained
    else:
        tc = tmat.tocsc()
        for q in range(nq):
            col = tc.getcol(q)
            if col.nnz == 1 and restrained[col.indices[0]]:
                fixed_q[q] = True
            elif any(restrained[i] for i in col.indices if tc[i, q] == 1.0):
                fixed_q[q] = True
    notes = []
    diag = np.abs(kr.diagonal())
    scale = diag.max() if diag.size else 1.0
    weak = (~fixed_q) & (diag <= tol * scale)
    if weak.any():
        names = []
        for q in np.flatnonzero(weak)[:8]:
            d = q if tmat is None else int(tmat.tocsc().getcol(q).indices[0])
            names.append(f"{model.nodes[node_ids[d // 6]].label or node_ids[d // 6]}"
                         f":{'x y z rx ry rz'.split()[d % 6]}")
        notes.append(f"restrained {int(weak.sum())} unstiffened DOF(s) "
                     f"(e.g. {', '.join(names)})")
        fixed_q |= weak
    free = np.flatnonzero(~fixed_q)
    kff = kr[free][:, free].tocsc()
    try:
        lu = spla.splu(kff)
    except RuntimeError:
        # a mechanism the diagonal test cannot see (e.g. a chain of pinned
        # bracing): tie every free DOF to ground with a spring of
        # ``spring * max stiffness`` -- what MIDAS/STAAD's automatic
        # constraints amount to.  Unloaded mechanisms stay put; check the
        # equilibrium of the reactions if loads reach them.
        eps = spring * float(np.abs(kff.diagonal()).max())
        lu = spla.splu((kff + sp.identity(kff.shape[0], format="csc") * eps).tocsc())
        notes.append(f"stiffness matrix singular: added soft springs "
                     f"({spring:g} x max stiffness) to every free DOF")

    # per element: end forces = G @ u_e (+ load correction), where G folds the
    # transformation and the recovery of condensed DOFs
    ne = len(elems)
    g_all = np.zeros((ne, 12, 12))
    d_all = np.zeros((ne, 12), dtype=int)
    zero_mask = np.zeros((ne, 12), bool)
    t_all = []
    for n, el in enumerate(elems):
        t = _transform(el.rot)
        t_all.append(t)
        smat = np.eye(12)
        if el.released:
            _, _, (r_idx, kept, a, _) = condense(el.k, np.zeros(12), el.released)
            smat[np.ix_(r_idx, kept)] = -a
            smat[r_idx, r_idx] = 0.0
            zero_mask[n, el.released] = True
        g_all[n] = el.k @ smat @ t
        d_all[n] = el.dofs

    wanted = list(cases) if cases is not None else model.cases()
    loads = []
    fmat = np.zeros((ndof, len(wanted)))
    for c, case in enumerate(wanted):
        f, fixed = _case_loads(model, elems, index, case, ndof)
        corr = {}
        for n, el in enumerate(elems):
            p = fixed.get(el.id)
            if p is None:
                continue
            _, pc, rec = condense(el.k, p, el.released)
            f[el.dofs] += t_all[n].T @ pc
            s0 = np.zeros(12)
            if rec is not None:
                s0[rec[0]] = rec[3]
            corr[n] = el.k @ s0 - p
        fmat[:, c] = f
        loads.append(corr)
    fr = tmat.T @ fmat if tmat is not None else fmat
    qmat = np.zeros((nq, len(wanted)))
    if free.size and len(wanted):
        qmat[free] = lu.solve(np.ascontiguousarray(fr[free]))
    umat = tmat @ qmat if tmat is not None else qmat
    resid_all = k @ umat - fmat

    results: dict[str, Result] = {}
    restrained_nodes = list(model.restraints)
    for c, case in enumerate(wanted):
        u = umat[:, c]
        res = Result(case=case, notes=list(notes))
        disp = u.reshape(-1, 6)
        for n, nid in enumerate(node_ids):
            res.displacements[nid] = tuple(disp[n].tolist())
        resid = resid_all[:, c].reshape(-1, 6)
        for nid in restrained_nodes:
            res.reactions[nid] = tuple(resid[index[nid]].tolist())
        fe = np.einsum("eij,ej->ei", g_all, u[d_all])
        for n, corr in loads[c].items():
            fe[n] += corr
        fe[zero_mask] = 0.0
        rows = fe.tolist()
        for n, el in enumerate(elems):
            res.end_forces[el.id] = tuple(rows[n])
            res.element_forces[el.id] = -rows[n][0]
        results[case] = res
        if store:
            model.results[case] = res
    return results


def end_moments(result: Result, element_id: str, axis: str = "y"):
    """Internal bending moments ``(M_i, M_j)`` about local ``axis`` with the
    beam sign convention: positive puts the local -z (for ``"y"``) or local
    -y (for ``"z"``) fiber in tension, i.e. sagging for a beam with z up."""
    f = result.end_forces[element_id]
    if axis == "y":
        return f[4], -f[10]
    if axis == "z":
        return -f[5], f[11]
    raise ValueError("axis must be 'y' or 'z'")


def reaction_totals(result: Result) -> tuple[float, float, float]:
    """Sum of the reaction forces (global X, Y, Z) -- the equilibrium check."""
    tot = np.zeros(3)
    for r in result.reactions.values():
        tot += r[:3]
    return tuple(float(v) for v in tot)


def combine(results: dict[str, Result], factors, name: str = "combination") -> Result:
    """Linear combination ``sum(factor * result)`` of solved cases.
    ``factors`` is ``{case: factor}`` or a list of ``(case, factor)`` pairs
    (the form ``staad.to_structural_model`` stores in
    ``hub.metadata["combinations"]``)."""
    pairs = list(factors.items()) if isinstance(factors, dict) else list(factors)
    out = Result(case=name)

    def acc(target, source, f):
        for key, val in source.items():
            if isinstance(val, tuple):
                prev = target.get(key, (0.0,) * len(val))
                target[key] = tuple(a + f * b for a, b in zip(prev, val))
            else:
                target[key] = target.get(key, 0.0) + f * val

    for case, f in pairs:
        r = results[case]
        acc(out.element_forces, r.element_forces, f)
        acc(out.reactions, r.reactions, f)
        acc(out.end_forces, r.end_forces, f)
        acc(out.displacements, r.displacements, f)
        out.notes.extend(n for n in r.notes if n not in out.notes)
    return out
