"""Torsional stability bracing of I-girders by cross-frames, diaphragms and
lean-on bracing -- AASHTO LRFD (10th Ed.) 6.7.4.2.2 with the lean-on
modifications of the NSBA *Lean-On Bracing Reference Guide* (B303, 2025;
Helwig and Wang 2003) and the NSBA Steel Bridge Design Handbook Ch. 13.

Stiffness (Eq. 6.7.4.2.2-1): the system provided, from springs in series
(Eq. 6.7.4.2.2-6),

    1 / (beta_T)act = 1 / beta_br + 1 / beta_sec + 1 / beta_g

must reach (beta_T)req (Eq. 6.7.4.2.2-2 / -3):

* :func:`brace_stiffness` -- beta_br of the common systems (SBDH Ch. 13
  Figs. 9 and 10; Eqs. 6.7.4.2.2-7 to -11): X-frames with tension-only or
  compression diagonals, K-frames, diaphragms in reverse (6 E Ib / S) or
  single (2 E Ib / S) curvature
* :func:`lean_on_brace_stiffness` -- the tension-only X-frame that n_gc
  girders lean on through top and bottom struts (B303 Table 2-1)
* :func:`web_distortion_stiffness` -- beta_sec (Eq. 6.7.4.2.2-12), infinite
  for a brace at least 0.8 of the web depth
* :func:`in_plane_girder_stiffness` -- beta_g (Eq. 6.7.4.2.2-13), halved for
  lean-on bracing (B303)
* skew: braces parallel to a skew of at most 20 deg take beta_br cos^2(theta)
  and M_br / cos(theta) (C6.7.4.2.2)

Strength: M_br (Eq. 6.7.4.2.2-14 / -15), the force couple F_br = M_br / h_b
and its share in the diagonals and struts (:func:`lean_on_member_forces`).
:class:`LeanOnBracing` runs the whole B303 design process for one span or
negative-moment region; :func:`lean_on_layout` checks a framing plan against
the B303 2.1.3 layout recommendations.

Lean-on stiffness (a check beyond B303): the closed form is
``E S^2 h_b^2 A_b / (n_gc L_d^3 + S^3 (m + 1)^2)`` with m the larger number
of girders leaning on the cross-frame from either side -- the stiffness seen
by the girder farthest along a strut chain.  B303's exterior-bay equation is
the m = n_gc - 2 case and its interior-bay equation, (n_gc / 2)^2, the
centered bay of an even n_gc; for an odd n_gc no bay is centered and the
interior equation overstates beta_br (n_gc = 3: 2.25 S^3 instead of 4 S^3),
so :func:`lean_on_brace_stiffness` takes the bay position.

Units: kips and inches; moments in kip-in., stiffness in kip-in./rad.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field

from civilpy.structural.aashto.lrfd.core import CheckResult
from civilpy.structural.aashto.lrfd.steel import (
    compression_member_resistance, tension_member_resistance)

E_STEEL = 29000.0
#: resistance factor for stability bracing (6.5.4.2, 10th Ed.)
PHI_SB = 0.80
#: depth ratio above which beta_sec is infinite and Eq. -2 / -14 apply
FULL_DEPTH_RATIO = 0.8
#: axial-rigidity factor on single-angle and tee members, noncomposite /
#: composite (4.6.3.3.4)
SINGLE_ANGLE_FACTOR = 0.65
SINGLE_ANGLE_FACTOR_COMPOSITE = 0.75
#: largest skew for braces placed parallel to the skew (6.7.4.2.1)
MAX_PARALLEL_SKEW_DEG = 20.0
#: B303 2.1.3: at least one cross-frame for every four girders
MAX_GIRDERS_PER_CROSS_FRAME = 4
#: B303 2.1.3: cross-frames no closer than about 4 ft to the end bearings
MIN_DISTANCE_FROM_BEARING_IN = 48.0
#: secondary-member slenderness limit (6.9.3)
SECONDARY_KL_R_LIMIT = 140.0


# ── required stiffness and strength ─────────────────────────────────────────


def effective_weak_axis_inertia(i_yc: float, i_yt: float = None, c: float = None,
                                t: float = None) -> float:
    """I_yeff: I_y of a doubly symmetric girder (Eq. 6.7.4.2.2-4,
    ``i_yt`` None) or ``I_yc + (t / c) I_yt`` (Eq. -5), c and t the
    distances from the girder centroid to the compression and tension flange
    centroids."""
    if i_yt is None:
        return i_yc
    return i_yc + t / c * i_yt


def _coefficient(full_depth: bool) -> float:
    return 2.4 if full_depth else 3.6


def required_stiffness(l: float, m_u: float, n: int, i_yeff: float, c_b: float = 1.0, *,
                       full_depth: bool = True, phi_sb: float = PHI_SB,
                       e: float = E_STEEL) -> float:
    """(beta_T)req = 2.4 L / (phi_sb n E I_yeff) (M_u / C_b)^2 (Eq.
    6.7.4.2.2-2) for braces at least 0.8 of the girder depth on full-depth
    connection plates, 3.6 L ... otherwise (Eq. -3).  ``l`` is the span (the
    average of the adjacent spans at an interior support), ``n`` the number
    of intermediate brace points in it."""
    return _coefficient(full_depth) * l / (phi_sb * n * e * i_yeff) * (m_u / c_b) ** 2


def required_brace_moment(l: float, m_u: float, n: int, i_yeff: float, l_b: float,
                          h_o: float, c_b: float = 1.0, *, full_depth: bool = True,
                          e: float = E_STEEL) -> float:
    """M_br = 2.4 L / (n E I_yeff) (M_u / C_b)^2 L_b / (500 h_o) (Eq.
    6.7.4.2.2-14; 3.6 for Eq. -15): the brace stiffness without phi_sb
    times the initial twist L_b / (500 h_o).  ``l_b`` is the unbraced length
    (the average of the two segments at a brace)."""
    return (_coefficient(full_depth) * l / (n * e * i_yeff) * (m_u / c_b) ** 2
            * l_b / (500.0 * h_o))


def skewed_stiffness(beta_br: float, skew_deg: float) -> float:
    """beta_br cos^2(theta) for braces parallel to a skew of at most 20 deg
    (C6.7.4.2.2)."""
    _check_skew(skew_deg)
    return beta_br * math.cos(math.radians(skew_deg)) ** 2


def skewed_brace_moment(m_br: float, skew_deg: float) -> float:
    """M_br / cos(theta) for braces parallel to the skew (C6.7.4.2.2)."""
    _check_skew(skew_deg)
    return m_br / math.cos(math.radians(skew_deg))


def _check_skew(skew_deg: float) -> None:
    if abs(skew_deg) > MAX_PARALLEL_SKEW_DEG:
        raise ValueError(f"braces may be parallel to the skew only up to {MAX_PARALLEL_SKEW_DEG:g} deg "
                         f"(6.7.4.2.1); place them normal to the girders at {skew_deg:g} deg")


# ── stiffness provided ──────────────────────────────────────────────────────


def brace_stiffness(system: str, s: float, h_b: float = 0.0, *, a_d: float = 0.0,
                    a_h: float = 0.0, l_d: float | None = None, i_b: float = 0.0,
                    e: float = E_STEEL) -> float:
    """beta_br of one cross-frame or diaphragm between two girders at
    spacing ``s`` (SBDH Ch. 13 Figs. 9-10, Eqs. 6.7.4.2.2-7 to -11):

    * ``"x_tension"`` -- X-frame, tension-only diagonal with top and bottom
      struts: ``E S^2 h_b^2 / (2 L_d^3 / A_d + S^3 / A_h)``
    * ``"x_compression"`` -- X-frame relying on both diagonals (struts carry
      no force): ``A_d E S^2 h_b^2 / L_d^3``
    * ``"k"`` -- K-frame: ``2 E S^2 h_b^2 / (8 L_d^3 / A_d + S^3 / A_h)``,
      L_d the diagonal from a corner to the opposite strut's midpoint
    * ``"diaphragm"`` -- ``6 E I_b / S`` (centroid at or above mid-height,
      reverse curvature); ``"diaphragm_below"`` -- ``2 E I_b / S`` (e.g.
      floor beams of a through girder)

    ``h_b`` is the distance between the strut centroids; ``l_d`` defaults to
    the diagonal of the S x h_b panel (S/2 x h_b for the K-frame).  Single
    angles and tees enter with their areas times :data:`SINGLE_ANGLE_FACTOR`.
    """
    if system == "diaphragm":
        return 6.0 * e * i_b / s
    if system == "diaphragm_below":
        return 2.0 * e * i_b / s
    if system == "x_tension":
        l_d = math.hypot(s, h_b) if l_d is None else l_d
        return e * s ** 2 * h_b ** 2 / (2.0 * l_d ** 3 / a_d + s ** 3 / a_h)
    if system == "x_compression":
        l_d = math.hypot(s, h_b) if l_d is None else l_d
        return a_d * e * s ** 2 * h_b ** 2 / l_d ** 3
    if system == "k":
        l_d = math.hypot(s / 2.0, h_b) if l_d is None else l_d
        return 2.0 * e * s ** 2 * h_b ** 2 / (8.0 * l_d ** 3 / a_d + s ** 3 / a_h)
    raise ValueError(f"unknown brace system {system!r}")


def _leaning(n_gc: int, bay) -> int:
    """m, the larger number of girders leaning on the cross-frame from one
    side: ``bay`` "exterior", "interior" (centered) or the 0-based index of
    the cross-frame bay among the n_gc - 1 bays of the group."""
    if n_gc < 2:
        raise ValueError("a cross-frame connects at least two girders")
    if bay == "exterior":
        return n_gc - 2
    if bay == "interior":
        return math.ceil(n_gc / 2) - 1
    if not 0 <= bay <= n_gc - 2:
        raise ValueError(f"bay index {bay} outside 0..{n_gc - 2}")
    return max(bay, n_gc - 2 - bay)


def lean_on_brace_stiffness(s: float, h_b: float, a_b: float, n_gc: int,
                            bay="exterior", *, l_d: float | None = None, b303: bool = False,
                            e: float = E_STEEL) -> float:
    """beta_br of a tension-only X-frame braced against by ``n_gc`` girders
    (modified Eq. 6.7.4.2.2-7, B303 Table 2-1; diagonals and struts of one
    area ``a_b``): ``E S^2 h_b^2 A_b / (n_gc L_d^3 + S^3 (m + 1)^2)``.

    ``bay`` is "exterior" (m = n_gc - 2, the B303 exterior bay and
    conservative anywhere), "interior" (the centered bay) or the bay index.
    ``b303=True`` with "interior" uses B303's (n_gc / 2)^2 as printed, which
    is exact for an even n_gc only."""
    l_d = math.hypot(s, h_b) if l_d is None else l_d
    if b303 and bay == "interior":
        term = (n_gc / 2.0) ** 2
    else:
        term = (_leaning(n_gc, bay) + 1) ** 2
    return e * s ** 2 * h_b ** 2 * a_b / (n_gc * l_d ** 3 + s ** 3 * term)


def web_distortion_stiffness(d: float, t_w: float, h_b: float, portions=(),
                             *, t_s: float = 0.0, b_s: float = 0.0, e: float = E_STEEL) -> float:
    """beta_sec (Eq. 6.7.4.2.2-12): infinite when the brace depth ``h_b`` is
    at least 0.8 of the web depth ``d``; otherwise springs in series over the
    web ``portions`` (h_i above and below the brace),

        beta_sec_i = 3.3 E / h_i (D / h_i)^2 (1.5 h_i t_w^3 / 12 + t_s b_s^3 / 12)

    with the connection plate t_s x b_s (b_s = 0 where the plate stops
    short, SBDH Ch. 13)."""
    if h_b >= FULL_DEPTH_RATIO * d:
        return math.inf
    if not portions:
        raise ValueError("a brace shallower than 0.8 D needs the web portions h_i")
    flexibility = 0.0
    for h_i in portions:
        beta_i = 3.3 * e / h_i * (d / h_i) ** 2 * (1.5 * h_i * t_w ** 3 / 12.0 + t_s * b_s ** 3 / 12.0)
        flexibility += 1.0 / beta_i
    return 1.0 / flexibility


def in_plane_girder_stiffness(n_g: int, s: float, i_x: float, l: float, *,
                              lean_on: bool = False, e: float = E_STEEL) -> float:
    """beta_g = 24 (n_g - 1)^2 S^2 E I_x / (n_g L^3) (Eq. 6.7.4.2.2-13), one
    half of it (12 ...) with lean-on bracing (B303, Helwig and Wang 2003).
    ``i_x`` is the noncomposite girder inertia at the brace point."""
    coef = 12.0 if lean_on else 24.0
    return coef * (n_g - 1) ** 2 * s ** 2 * e * i_x / (n_g * l ** 3)


def system_stiffness(*components: float) -> float:
    """(beta_T)act from springs in series (Eq. 6.7.4.2.2-6); infinite
    components drop out."""
    return 1.0 / sum(1.0 / b for b in components if not math.isinf(b))


# ── member forces ───────────────────────────────────────────────────────────


def lean_on_member_forces(m_br: float, h_b: float, s: float, n_gc: int, bay="exterior",
                          *, l_d: float | None = None, b303: bool = False) -> dict:
    """Forces in a tension-only X-frame braced against by ``n_gc`` girders
    (B303 2.2.5, Fig. 2-3): the couple F_br = M_br / h_b, the diagonal
    ``n_gc F_br L_d / S`` and the most heavily loaded strut, ``(m + 1) F_br``
    (B303: (n_gc - 1) F_br exterior, (n_gc / 2) F_br interior).  Struts are
    in tension or compression with the direction of twist."""
    l_d = math.hypot(s, h_b) if l_d is None else l_d
    f_br = m_br / h_b
    strut = (n_gc / 2.0 if b303 and bay == "interior" else _leaning(n_gc, bay) + 1) * f_br
    return {"F_br": f_br, "F_diagonal": n_gc * f_br * l_d / s, "F_strut": strut}


def single_angle_slenderness(l_over_rx: float) -> float:
    """(KL/r)_eff of a single angle connected through one leg (Eqs.
    6.9.4.4-1 / -2): 72 + 0.75 l / r_x up to l / r_x = 80, 32 + 1.25 l / r_x
    beyond; r_x about the axis parallel to the connected leg."""
    if l_over_rx <= 80.0:
        return 72.0 + 0.75 * l_over_rx
    return 32.0 + 1.25 * l_over_rx


# ── the design process ──────────────────────────────────────────────────────


@dataclass
class BraceMember:
    """A cross-frame / strut member: gross area, net area, shear-lag U,
    r_x (connected-leg axis, for 6.9.4.4) and r_z (least, for 6.9.3).
    ``single_angle`` applies the 0.65 axial-rigidity factor in stiffness."""

    a_g: float
    f_y: float = 50.0
    f_u: float = 65.0
    a_n: float | None = None
    u: float = 1.0
    r_x: float = 0.0
    r_z: float = 0.0
    single_angle: bool = True

    @property
    def stiffness_area(self) -> float:
        return self.a_g * (SINGLE_ANGLE_FACTOR if self.single_angle else 1.0)


@dataclass
class LeanOnBracing:
    """One span or negative-moment region braced by tension-only X-frames
    with lean-on struts (B303 2.2.2).

    Girder: ``n_g`` girders at spacing ``s``, noncomposite I_x and I_yeff,
    ``h_o`` between flange centroids, web depth ``d`` and thickness ``t_w``.
    Loading: the factored construction moment ``m_u`` (positive regions: the
    peak; negative: at the support), ``c_b``.  Bracing: ``n`` intermediate
    brace lines over the span ``l``, unbraced length ``l_b``, ``n_gc``
    girders per cross-frame in the cross-frame ``bay``, frame depth ``h_b``
    between strut centroids, ``member`` for diagonals and struts, connection
    plate b_s x t_s, ``skew_deg`` for braces parallel to the skew.
    """

    l: float
    n: int
    l_b: float
    n_g: int
    s: float
    i_x: float
    i_yeff: float
    h_o: float
    d: float
    t_w: float
    m_u: float
    h_b: float
    member: BraceMember
    n_gc: int = 2
    bay: object = "exterior"
    c_b: float = 1.0
    skew_deg: float = 0.0
    b_s: float = 0.0
    t_s: float = 0.0
    web_portions: tuple = ()
    l_d: float | None = None
    l_strut: float | None = None
    b303: bool = False
    phi_sb: float = PHI_SB
    e: float = E_STEEL
    notes: list = field(default_factory=list)

    @property
    def full_depth(self) -> bool:
        return self.h_b >= FULL_DEPTH_RATIO * self.d

    @property
    def diagonal_length(self) -> float:
        """Work-point diagonal unless given: the clear panel S - 2 b_s by
        h_b, as B303 measures it."""
        return self.l_d if self.l_d is not None else math.hypot(self.s - 2.0 * self.b_s, self.h_b)

    def stiffness(self) -> dict:
        beta_br = lean_on_brace_stiffness(self.s, self.h_b, self.member.stiffness_area, self.n_gc,
                                          self.bay, l_d=self.diagonal_length, b303=self.b303, e=self.e)
        if self.skew_deg:
            beta_br = skewed_stiffness(beta_br, self.skew_deg)
        beta_sec = web_distortion_stiffness(self.d, self.t_w, self.h_b, self.web_portions,
                                            t_s=self.t_s, b_s=self.b_s, e=self.e)
        beta_g = in_plane_girder_stiffness(self.n_g, self.s, self.i_x, self.l, lean_on=True, e=self.e)
        return {"beta_br": beta_br, "beta_sec": beta_sec, "beta_g": beta_g,
                "beta_T_act": system_stiffness(beta_br, beta_sec, beta_g),
                "beta_T_req": required_stiffness(self.l, self.m_u, self.n, self.i_yeff, self.c_b,
                                                 full_depth=self.full_depth, phi_sb=self.phi_sb,
                                                 e=self.e)}

    def forces(self) -> dict:
        m_br = required_brace_moment(self.l, self.m_u, self.n, self.i_yeff, self.l_b, self.h_o,
                                     self.c_b, full_depth=self.full_depth, e=self.e)
        if self.skew_deg:
            m_br = skewed_brace_moment(m_br, self.skew_deg)
        out = {"M_br": m_br}
        out.update(lean_on_member_forces(m_br, self.h_b, self.s, self.n_gc, self.bay,
                                         l_d=self.diagonal_length, b303=self.b303))
        return out

    def check(self) -> CheckResult:
        """Stiffness (Eq. 6.7.4.2.2-1) as the governing ratio, with the
        diagonal in tension (6.8.2.1), the struts in compression (6.9.4.4
        single angles, 6.9.4.1.1) and the 6.9.3 slenderness of the struts in
        ``details``; ``ok`` needs all of them."""
        k = self.stiffness()
        f = self.forces()
        mbr = self.member
        tension = tension_member_resistance(mbr.a_g, mbr.f_y, mbr.a_n, mbr.f_u, mbr.u)
        l_strut = self.l_strut if self.l_strut is not None else self.s - 2.0 * self.b_s
        details = {**k, **f, "full_depth": self.full_depth, "phi_Pr_tension": tension.capacity,
                   "tension_ok": tension.capacity >= f["F_diagonal"]}
        margins = [k["beta_T_act"] / k["beta_T_req"], tension.capacity / f["F_diagonal"]]
        if mbr.r_x:
            kl_r = (single_angle_slenderness(l_strut / mbr.r_x) if mbr.single_angle
                    else l_strut / mbr.r_x)
            comp = compression_member_resistance(mbr.a_g, mbr.f_y, kl_r)
            phi_pn = comp.capacity * comp.phi
            details.update({"KL_r_eff": kl_r, "phi_Pn_compression": phi_pn,
                            "compression_ok": phi_pn >= f["F_strut"]})
            margins.append(phi_pn / f["F_strut"])
        if mbr.r_z:
            details["KL_r_strut"] = l_strut / mbr.r_z
            details["slenderness_ok"] = l_strut / mbr.r_z <= SECONDARY_KL_R_LIMIT
            margins.append(SECONDARY_KL_R_LIMIT / (l_strut / mbr.r_z))
        notes = list(self.notes)
        if self.n_gc > MAX_GIRDERS_PER_CROSS_FRAME:
            notes.append(f"n_gc = {self.n_gc} exceeds the B303 recommendation of "
                         f"{MAX_GIRDERS_PER_CROSS_FRAME}")
        details["notes"] = notes
        return CheckResult(article="6.7.4.2.2", name="Lean-On Stability Bracing",
                           capacity=min(margins), demand=1.0, details=details)


# ── framing-plan layout ─────────────────────────────────────────────────────


@dataclass
class BraceLine:
    """One discrete line of bracing across the bridge: ``bays`` lists each
    girder bay as ``"x"`` (cross-frame or diaphragm), ``"strut"`` (lean-on
    struts top and bottom) or ``""`` (nothing); ``kind`` is
    ``"support"``, ``"splice"`` (air splice), ``"peak"`` (peak positive
    moment) or ``"intermediate"``; ``station`` along the girders and
    ``distance_from_bearing`` (in.) where it matters."""

    bays: tuple
    kind: str = "intermediate"
    station: float | None = None
    distance_from_bearing: float | None = None

    @property
    def cross_frames(self) -> int:
        return sum(1 for b in self.bays if b == "x")


def lean_on_layout(n_girders: int, lines, *, skew_deg: float = 0.0, parallel_to_skew: bool = False,
                   curved: bool = False, flange_width: float = 0.0,
                   unbraced_length: float | None = None, plate_girder: bool = True,
                   frame_depth: float | None = None, girder_depth: float | None = None) -> list[str]:
    """Findings for a framing plan with lean-on bracing against B303 2.1
    and AASHTO 6.7.4.2 (an empty list passes):

    * horizontally curved girders are outside the method (B303 2.1.1)
    * a full line of cross-frames at every support line (B303 2.1.3)
    * every bay of an intermediate line is braced (cross-frame or struts) and
      the line has at least one cross-frame; n_gc = n_g / N_c of at most 4,
      one design n_gc per span (the largest is reported)
    * cross-frames no closer than about 4 ft to the end bearings and, in
      skewed spans, at least max(4 b_f, 0.4 L_b) (C6.7.4.2.1)
    * braces parallel to the skew only up to 20 deg; cross-frame depth at
      least 0.75 (plate girders) or 0.5 (rolled beams) of the girder depth
    * each girder reached by a cross-frame somewhere (the S-pattern)
    """
    findings = []
    if curved:
        findings.append("lean-on bracing is for straight girders (B303 2.1.1)")
    if parallel_to_skew and abs(skew_deg) > MAX_PARALLEL_SKEW_DEG:
        findings.append(f"braces parallel to a {skew_deg:g} deg skew: limit {MAX_PARALLEL_SKEW_DEG:g} deg")
    if frame_depth is not None and girder_depth:
        need = 0.75 if plate_girder else 0.5
        if frame_depth < need * girder_depth:
            findings.append(f"cross-frame depth {frame_depth:g} < {need:g} x girder depth (6.7.4.2.1)")
    n_bays = n_girders - 1
    braced_girders = set()
    n_gc_values = []
    for k, line in enumerate(lines):
        tag = f"line {k}" + (f" (sta. {line.station:g})" if line.station is not None else "")
        if len(line.bays) != n_bays:
            findings.append(f"{tag}: {len(line.bays)} bays for {n_girders} girders")
            continue
        if line.kind == "support":
            if line.cross_frames != n_bays:
                findings.append(f"{tag}: support lines need cross-frames in every bay (B303 2.1.3)")
            continue
        if any(b not in ("x", "strut") for b in line.bays):
            findings.append(f"{tag}: unbraced bay - every girder must connect to the line")
        if line.cross_frames == 0:
            findings.append(f"{tag}: no cross-frame for the struts to lean on")
            continue
        for b, kind in enumerate(line.bays):
            if kind == "x":
                braced_girders |= {b, b + 1}
        n_gc = n_girders / line.cross_frames
        n_gc_values.append(n_gc)
        if n_gc > MAX_GIRDERS_PER_CROSS_FRAME:
            findings.append(f"{tag}: n_gc = {n_gc:g} > {MAX_GIRDERS_PER_CROSS_FRAME} (B303 2.1.3)")
        d = line.distance_from_bearing
        if d is not None:
            if d < MIN_DISTANCE_FROM_BEARING_IN:
                findings.append(f"{tag}: {d:g} in. from the bearing < about 4 ft (B303 2.1.3)")
            if skew_deg:
                need = max(4.0 * flange_width, 0.4 * (unbraced_length or 0.0))
                if d < need:
                    findings.append(f"{tag}: {d:g} in. from the skewed bearing < max(4 b_f, 0.4 L_b) "
                                    f"= {need:g} in. (C6.7.4.2.1)")
    missing = set(range(n_girders)) - braced_girders
    if missing and any(line.kind != "support" for line in lines):
        findings.append(f"girders {sorted(missing)} have no cross-frame outside the supports "
                        f"(B303 S-pattern)")
    return findings


def design_n_gc(n_girders: int, lines) -> float:
    """The design n_gc of a span: the largest n_g / N_c over its
    intermediate lines (B303 2.1.3)."""
    values = [n_girders / ln.cross_frames for ln in lines
              if ln.kind != "support" and ln.cross_frames]
    return max(values) if values else 1.0
