"""Strengthening an in-service steel member with added plates -- the
locked-in / shared stress method of FHWA HIF-18-042 (Steel Truss Member
Strengthening), with the combined axial + flexure load rating it ends in.

A plate bolted onto a member that is already carrying its dead load does
not share that dead load: the existing material keeps the **locked-in**
dead-load stress it had when the plate went on, and only what is applied
afterwards -- added dead load (a new wearing surface) and live load -- is
**shared** between the old and the new material in proportion to their
areas (axial) and section moduli (flexure).  The strengthened member is
therefore checked as two materials with their own stresses and their own
"allowable" stresses (factored resistance over the section property), and
the existing material usually governs because it carries the whole
original dead load on the weaker steel.

* :func:`interaction_rating_factor` -- the LRFR rating factor for a member
  in combined axial force and flexure: the interaction equation of LRFD
  6.8.2.3-2 / 6.9.2.2-2 solved for the live-load multiplier (LRFR Guide
  Manual 2003, Appendix C.6.2), with the beam-column magnifier delta_b
  iterated on the rated live load for compression members
  (:func:`magnified_rating_factor`).
* :class:`StrengthenedMember` -- existing + added material; its
  :meth:`~StrengthenedMember.stresses`, factored stresses, D/C ratios and
  :meth:`~StrengthenedMember.rating_factor` follow the HIF-18-042
  procedure for a tension member and a compression member.  The example
  scales the shared axial stress by each material's area fraction, which
  understates it (with one modulus every material takes the same shared
  stress); civilpy uses the strain-compatible stress and keeps the
  example's convention behind ``hif_shared_stress=True`` so the published
  numbers can be reproduced.

Units: kips, inches, ksi; moments in kip-in.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math
from dataclasses import dataclass, field

from civilpy.structural.aashto.lrfd.steel import E_STEEL

GAMMAS_STRENGTH_I = (1.25, 1.50, 1.75)      # DC, DW, LL+IM (HL-93 inventory)


@dataclass(frozen=True)
class MemberForces:
    """Unfactored member actions: axial (kip, tension positive) and the
    moment magnitude (kip-in.) for DC, DW and LL+IM."""

    p_dc: float
    p_dw: float
    p_ll: float
    m_dc: float = 0.0
    m_dw: float = 0.0
    m_ll: float = 0.0

    def factored(self, gammas=GAMMAS_STRENGTH_I) -> tuple[float, float]:
        g_dc, g_dw, g_ll = gammas
        return (g_dc * self.p_dc + g_dw * self.p_dw + g_ll * self.p_ll,
                g_dc * self.m_dc + g_dw * self.m_dw + g_ll * self.m_ll)


def interaction_rating_factor(p_r: float, m_r: float, f: MemberForces,
                              gammas=GAMMAS_STRENGTH_I,
                              delta_b: float = 1.0) -> float:
    """RF from the 6.8.2.3-2 / 6.9.2.2-2 interaction (Pu/Pr >= 0.2 form)
    solved for the live-load factor::

        RF = (1 - g_DC (P_DC/Pr + 8/9 db M_DC/Mr) - g_DW (P_DW/Pr + 8/9 db M_DW/Mr))
             / (g_LL (P_LL/Pr + 8/9 db M_LL/Mr))

    ``p_r`` / ``m_r`` are factored resistances; axial magnitudes are used
    (the member's sense is set by its resistance)."""
    g_dc, g_dw, g_ll = gammas

    def term(p, m):
        return abs(p) / p_r + 8.0 / 9.0 * delta_b * abs(m) / m_r

    return ((1.0 - g_dc * term(f.p_dc, f.m_dc) - g_dw * term(f.p_dw, f.m_dw))
            / (g_ll * term(f.p_ll, f.m_ll)))


def beam_column_magnifier(p_u: float, p_e: float, c_m: float = 1.0,
                          phi_k: float = 1.0) -> float:
    """delta_b = Cm / (1 - Pu / (phi_K Pe)) (Eq. 4.5.3.2.2b-3), phi_K = 1.0
    for steel; not floored at 1.0 here (Cm may be taken as 1.0)."""
    return c_m / (1.0 - abs(p_u) / (phi_k * p_e))


def magnified_rating_factor(rf_of_delta, f: MemberForces, p_e: float, *,
                            gammas=GAMMAS_STRENGTH_I, c_m: float = 1.0,
                            iterations: int = 4) -> tuple[float, float, list]:
    """Iterate ``RF = rf_of_delta(delta_b)`` with delta_b computed at the
    rated load ``g_DC P_DC + g_DW P_DW + RF g_LL P_LL`` (HIF-18-042: start
    at RF = 1.0 and refine).  ``iterations`` counts the RF evaluations after
    the first (the example's "after four iterations").  Returns ``(RF,
    delta_b, history)``."""
    g_dc, g_dw, g_ll = gammas

    def delta(rf):
        p_u = g_dc * abs(f.p_dc) + g_dw * abs(f.p_dw) + rf * g_ll * abs(f.p_ll)
        return beam_column_magnifier(p_u, p_e, c_m)

    d = delta(1.0)
    rf = rf_of_delta(d)
    history = [(d, rf)]
    for _ in range(iterations):
        d = delta(rf)
        rf = rf_of_delta(d)
        history.append((d, rf))
    return rf, d, history


@dataclass(frozen=True)
class Material:
    """One material of a strengthened member: gross and net area (in^2) and
    the section modulus to *its own* extreme fiber in the strengthened
    member (in^3), with Fy / Fu (ksi)."""

    a_g: float
    f_y: float
    f_u: float
    a_n: float | None = None
    s: float | None = None


@dataclass
class StrengthenedMember:
    """An existing member with added plates (HIF-18-042).

    ``existing`` holds the *original* member's areas and section modulus
    (``s`` of the unstrengthened section -- the locked-in DC bending stress
    is computed on it); ``added`` the new plates.  ``s_existing`` and
    ``s_added`` are the strengthened section's moduli to the extreme fibers
    of the existing and the new material.  ``u`` is the shear-lag factor of
    the net section.

    Allowable (factored) stresses:

    * tension: ``phi_y Fy`` on the gross and ``phi_u Fu U`` on the net area
      (6.8.2.1) of each material;
    * flexure: ``phi_f Fy`` (yield-moment based, conservative), or the
      given ``fb_allow`` (e.g. phi_f Mn / S of a box section);
    * compression: the existing material's locked-in DC against the
      unstrengthened ``phi_c Pn / Ag`` (``pn_existing``), everything shared
      against the strengthened ``phi_c Pn / Ag`` (``pn_strengthened``),
      both from :func:`~civilpy.structural.aashto.lrfd.steel.
      compression_member_resistance`."""

    existing: Material
    added: Material
    s_existing: float
    s_added: float
    u: float = 1.0
    compression: bool = False
    pn_existing: float | None = None
    pn_strengthened: float | None = None
    fb_allow: tuple[float, float] | None = None     # (existing, added), ksi
    phi_y: float = 0.95
    phi_u: float = 0.80
    phi_c: float = 0.95
    phi_f: float = 1.00
    #: reproduce HIF-18-042's shared axial stress, ``(P / A_total) x
    #: (A_material / A_total)``.  With one modulus both materials take the
    #: same shared stress ``P / A_total`` (strain compatibility); the
    #: example's extra area ratio understates it by that ratio (0.585 /
    #: 0.414 on the tension member), which is why its strengthened RFs (2.18,
    #: 1.13) exceed the correct 1.39 / 0.87.  Off by default.
    hif_shared_stress: bool = False

    @property
    def a_g(self) -> float:
        return self.existing.a_g + self.added.a_g

    @property
    def a_n(self) -> float:
        return (self.existing.a_n or self.existing.a_g) + (self.added.a_n or self.added.a_g)

    # ── stresses ────────────────────────────────────────────────────────

    def stresses(self, f: MemberForces) -> dict[str, dict[str, float]]:
        """Unfactored stresses (ksi, magnitudes) per material and case:
        ``{"existing": {"a_g DC": .., "a_n DW": .., "b DC": .., ...},
        "added": {...}}`` -- DC locked into the existing material, DW and
        LL+IM shared by area (axial) and by the strengthened moduli
        (flexure)."""
        e, n = self.existing, self.added
        a_ne = e.a_n or e.a_g
        a_nn = n.a_n or n.a_g
        out = {"existing": {}, "added": {}}
        out["existing"]["a_g DC"] = abs(f.p_dc) / e.a_g
        out["existing"]["a_n DC"] = abs(f.p_dc) / a_ne
        out["existing"]["b DC"] = abs(f.m_dc) / e.s
        out["added"].update({"a_g DC": 0.0, "a_n DC": 0.0, "b DC": 0.0})
        if self.hif_shared_stress:
            kg = {"existing": e.a_g / self.a_g, "added": n.a_g / self.a_g}
            kn = {"existing": a_ne / self.a_n, "added": a_nn / self.a_n}
        else:
            kg = kn = {"existing": 1.0, "added": 1.0}
        for case, p, m in (("DW", f.p_dw, f.m_dw), ("LL", f.p_ll, f.m_ll)):
            for key in ("existing", "added"):
                out[key][f"a_g {case}"] = abs(p) / self.a_g * kg[key]
                out[key][f"a_n {case}"] = abs(p) / self.a_n * kn[key]
            out["existing"][f"b {case}"] = abs(m) / self.s_existing
            out["added"][f"b {case}"] = abs(m) / self.s_added
        return out

    def allowables(self) -> dict[str, dict[str, float]]:
        """Factored resistances as stresses (ksi) per material."""
        out = {}
        for key, mat in (("existing", self.existing), ("added", self.added)):
            d = {}
            if self.compression:
                d["a_g locked"] = self.phi_c * self.pn_existing / self.existing.a_g
                d["a_g shared"] = self.phi_c * self.pn_strengthened / self.a_g
            else:
                d["a_g"] = self.phi_y * mat.f_y
                d["a_n"] = self.phi_u * mat.f_u * self.u
            d["b"] = (self.fb_allow[0 if key == "existing" else 1]
                      if self.fb_allow else self.phi_f * mat.f_y)
            out[key] = d
        return out

    def ratios(self, f: MemberForces, gammas=GAMMAS_STRENGTH_I,
               delta_b: float = 1.0) -> dict[str, dict[str, float]]:
        """Strength D/C ratios per material: axial on the gross and (tension)
        net areas, flexure, and the 6.8.2.3 / 6.9.2.2 interaction (the
        axial ratio picks the equation; moments magnified by ``delta_b``)."""
        g_dc, g_dw, g_ll = gammas
        st, al = self.stresses(f), self.allowables()
        out = {}
        for key in ("existing", "added"):
            s, a = st[key], al[key]
            r = {}
            if self.compression:
                r["axial"] = (g_dc * s["a_g DC"] / a["a_g locked"]
                              + (g_dw * s["a_g DW"] + g_ll * s["a_g LL"]) / a["a_g shared"])
            else:
                r["axial gross"] = sum(g * s[f"a_g {c}"] for g, c in
                                       zip(gammas, ("DC", "DW", "LL"))) / a["a_g"]
                r["axial net"] = sum(g * s[f"a_n {c}"] for g, c in
                                     zip(gammas, ("DC", "DW", "LL"))) / a["a_n"]
                r["axial"] = max(r["axial gross"], r["axial net"])
            r["flexure"] = delta_b * sum(g * s[f"b {c}"] for g, c in
                                         zip(gammas, ("DC", "DW", "LL"))) / a["b"]
            if r["axial"] < 0.2:
                r["interaction"] = r["axial"] / 2.0 + r["flexure"]
            else:
                r["interaction"] = r["axial"] + 8.0 / 9.0 * r["flexure"]
            out[key] = r
        return out

    def rating_factor(self, f: MemberForces, gammas=GAMMAS_STRENGTH_I, *,
                      material: str = "existing", p_e: float | None = None,
                      c_m: float = 1.0, iterations: int = 4):
        """Strength rating factor of one material, by the stress form of
        :func:`interaction_rating_factor` (HIF-18-042): the existing
        material's DC terms are its locked-in stresses over the locked-in
        allowable, everything else the shared stresses over the shared
        allowable.  Tension members use the gross-area axial terms (the
        governing D/C in the example); compression members iterate delta_b
        with ``p_e`` of the strengthened member.  Returns ``RF`` (tension)
        or ``(RF, delta_b)`` (compression)."""
        g_dc, g_dw, g_ll = gammas
        s, a = self.stresses(f)[material], self.allowables()[material]

        def rf(db):
            if self.compression:
                ax_dc = s["a_g DC"] / a["a_g locked"]
                ax_dw = s["a_g DW"] / a["a_g shared"]
                ax_ll = s["a_g LL"] / a["a_g shared"]
            else:
                ax_dc, ax_dw, ax_ll = (s[f"a_g {c}"] / a["a_g"] for c in ("DC", "DW", "LL"))
            b = a["b"]
            num = (1.0 - g_dc * (ax_dc + 8 / 9 * db * s["b DC"] / b)
                   - g_dw * (ax_dw + 8 / 9 * db * s["b DW"] / b))
            return num / (g_ll * (ax_ll + 8 / 9 * db * s["b LL"] / b))

        if not self.compression:
            return rf(1.0)
        if p_e is None:
            raise ValueError("compression members need p_e of the strengthened member")
        value, db, _ = magnified_rating_factor(rf, f, p_e, gammas=gammas, c_m=c_m,
                                               iterations=iterations)
        return value, db


def staggered_net_width(gross_width: float, hole: float, n_holes: int,
                        staggers=()) -> float:
    """Net width across a chain of holes (6.8.3): the gross width less the
    holes in the chain plus ``s^2 / 4g`` for each staggered link
    ``(s, g)``."""
    return gross_width - n_holes * hole + sum(s * s / (4.0 * g) for s, g in staggers)


def rivets_removed_capacity(n_remaining: int, r_rivet: float,
                            sides: int = 2) -> float:
    """Factored resistance of a connection while rivets are out (kips):
    ``sides x remaining fasteners per side x resistance per fastener``."""
    return sides * n_remaining * r_rivet


def fasteners_to_develop(p_r: float, r_fastener: float) -> int:
    """Fasteners needed to develop a plate force ``p_r`` (rounded up)."""
    return math.ceil(p_r / r_fastener - 1e-9)


# ── plate-girder flexural strengthening (FHWA HIF-18-043) ──────────────────


@dataclass(frozen=True)
class Piece:
    """A rectangle (or negative area: section loss, bolt holes) of a girder
    cross section: area (in^2, negative to remove), centroid ``y`` (in.,
    any datum), own moment of inertia ``io`` (in^4)."""

    area: float
    y: float
    io: float = 0.0
    label: str = ""

    @classmethod
    def plate(cls, b: float, t: float, y: float, label: str = "") -> "Piece":
        return cls(b * t, y, b * t ** 3 / 12.0, label)


def section_from_pieces(pieces) -> dict:
    """``{"A", "y", "I"}`` of a set of :class:`Piece` (parallel axis about
    the net centroid)."""
    a = sum(p.area for p in pieces)
    y = sum(p.area * p.y for p in pieces) / a
    i = sum(p.io + p.area * (p.y - y) ** 2 for p in pieces)
    return {"A": a, "y": y, "I": i}


def effective_net_width(gross_width: float, hole: float, n_holes: int,
                        staggers=(), cap: float = 0.85) -> float:
    """Net width of a bolted plate for section properties, no more than
    ``cap`` times the gross width (LRFD 6.13.5.2's 0.85 Ag limit, as
    HIF-18-043 applies it to cover-plated flanges)."""
    return min(staggered_net_width(gross_width, hole, n_holes, staggers),
               cap * gross_width)


@dataclass
class StrengthenedGirder:
    """A girder in flexure with plates added in service (HIF-18-043).

    ``existing`` are the pieces of the as-inspected section (section loss
    and the new bolt holes as negative pieces), ``added`` the new plates
    (with their holes).  The DC moment is locked into ``existing``; DW and
    LL+IM act on the whole.  ``fibers`` names the extreme fibers checked,
    ``{name: (y, material)}`` with material ``"existing"`` or ``"added"``.
    Stresses are moment / (I / |y - y_bar|), ksi for kip-ft moments."""

    existing: list[Piece]
    added: list[Piece]
    fibers: dict
    fy_existing: float
    fy_added: float
    phi_f: float = 1.0
    #: the strengthened section's pieces when they are not simply
    #: ``existing + added`` (e.g. the bolt holes of the combined plies
    #: replace the existing section's own hole pieces)
    strengthened: list[Piece] | None = None

    def stresses(self, m_dc: float, m_dw: float, m_ll: float) -> dict:
        e = section_from_pieces(self.existing)
        s = section_from_pieces(self.strengthened if self.strengthened is not None
                                else self.existing + self.added)
        out = {}
        for name, (y, mat) in self.fibers.items():
            s_e = e["I"] / abs(y - e["y"])
            s_s = s["I"] / abs(y - s["y"])
            out[name] = {"material": mat,
                         "S_existing": s_e, "S_strengthened": s_s,
                         "f_DC": (m_dc * 12.0 / s_e) if mat == "existing" else 0.0,
                         "f_DW": m_dw * 12.0 / s_s, "f_LL": m_ll * 12.0 / s_s}
        return out

    def rating_factors(self, m_dc: float, m_dw: float, m_ll: float,
                       gammas=GAMMAS_STRENGTH_I) -> dict:
        """RF at every fiber, ``(phi_f Fy - g_DC f_DC - g_DW f_DW) /
        (g_LL f_LL)`` with each material's own Fy."""
        g_dc, g_dw, g_ll = gammas
        out = {}
        for name, st in self.stresses(m_dc, m_dw, m_ll).items():
            fy = self.fy_existing if st["material"] == "existing" else self.fy_added
            f_r = self.phi_f * fy
            st["f_u"] = g_dc * st["f_DC"] + g_dw * st["f_DW"] + g_ll * st["f_LL"]
            st["RF"] = (f_r - g_dc * st["f_DC"] - g_dw * st["f_DW"]) / (g_ll * st["f_LL"])
            out[name] = st
        return out


def eccentric_bolt_group(bolts, v: float, m: float) -> dict:
    """Elastic (vector) method for a bolt group under direct shear ``v``
    (kip, vertical) and moment ``m`` (kip-in.) about the group centroid:
    ``bolts`` are ``(x, y)`` from the centroid.  Returns the polar moment
    ``J = sum(x^2 + y^2)`` and the largest resultant bolt force."""
    n = len(bolts)
    j = sum(x * x + y * y for x, y in bolts)
    worst = (0.0, None)
    for x, y in bolts:
        fx = -m * y / j
        fy = v / n + m * x / j
        r = math.hypot(fx, fy)
        if r > worst[0]:
            worst = (r, (x, y))
    return {"J": j, "R_max": worst[0], "bolt": worst[1], "n": n}


def shear_flow_bolt_force(v: float, q: float, i: float, pitch: float,
                          bolts_per_row: int = 1) -> float:
    """Force per bolt from horizontal shear flow ``V Q / I`` over one
    ``pitch``, shared by ``bolts_per_row``."""
    return v * q / i * pitch / bolts_per_row


def splice_web_design_shear(v_u: float, phi_vn: float) -> float:
    """Design shear for a web splice (LRFD 6.13.6.1.4b): 1.5 V_u when
    V_u < 0.5 phi_v V_n, else the average 0.5 (V_u + phi_v V_n)."""
    return 1.5 * v_u if v_u < 0.5 * phi_vn else 0.5 * (v_u + phi_vn)


# ── composite action by retrofit: post-installed shear connectors ──────────


def post_installed_connector_strength(d: float, f_u: float) -> float:
    """Static strength (kips) of one post-installed shear connector -- a
    double-nut bolt, high-tension friction-grip bolt or adhesive anchor
    through the existing deck into the top flange -- taken as
    ``0.5 F_u A_sc`` (Kwon, Engelhardt and Klingner, J. Bridge Eng. 2010;
    TxDOT 0-4124), the basis of the partial-composite retrofits in the
    UT Austin study the NSBA library carries."""
    return 0.5 * f_u * math.pi * d * d / 4.0


@dataclass(frozen=True)
class PartialCompositeResult:
    mp: float                 # kip-in.
    c_slab: float             # slab compression force, kips
    composite_ratio: float    # c_slab over the full-composite slab force
    y_pna: float              # PNA depth below the top of the slab, in.
    a: float                  # depth of the concrete stress block, in.


def partial_composite_plastic_moment(*, b_c: float, t_c: float, d_web: float, t_w: float,
                                     b_t: float, t_t: float, f_y: float, b_s: float,
                                     t_s: float, f_c: float, sum_qn: float,
                                     t_haunch: float = 0.0) -> PartialCompositeResult:
    """Plastic moment of an I-girder (top flange ``b_c x t_c``, web
    ``d_web x t_w``, bottom flange ``b_t x t_t``, one ``f_y``) composite
    with a slab through connectors of total strength ``sum_qn`` between the
    points of zero and maximum moment.  The slab force is the least of the
    connector strength, the slab's ``0.85 f'c b_s t_s`` and the steel's
    ``A_s F_y`` (the AISC 360 I3.2a plastic stress distribution, which
    reduces to LRFD Appendix D6.1 at full composite action and to the
    steel plastic moment with no connectors)."""
    a_c, a_w, a_t = b_c * t_c, d_web * t_w, b_t * t_t
    a_s = a_c + a_w + a_t
    c_full = min(0.85 * f_c * b_s * t_s, a_s * f_y)
    c = max(0.0, min(sum_qn, c_full))
    a = c / (0.85 * f_c * b_s) if c > 0 else 0.0
    top = t_s + t_haunch                       # top of steel below the slab top
    # steel above the PNA in compression: A_above = (A_s Fy - C) / (2 Fy)
    a_above = (a_s * f_y - c) / (2.0 * f_y)
    pieces = [(a_c, top, top + t_c), (a_w, top + t_c, top + t_c + d_web),
              (a_t, top + t_c + d_web, top + t_c + d_web + t_t)]
    remaining, y_pna = a_above, top
    for area, y0, y1 in pieces:
        if remaining <= area + 1e-12:
            y_pna = y0 + (y1 - y0) * (remaining / area if area else 0.0)
            break
        remaining -= area
    m = c * (y_pna - a / 2.0)
    for area, y0, y1 in pieces:
        h = y1 - y0
        above = min(max(y_pna - y0, 0.0), h)
        below = h - above
        w = area / h
        # compression part above the PNA, tension part below it
        m += f_y * w * above * (y_pna - (y0 + above / 2.0))
        m += f_y * w * below * ((y0 + above + below / 2.0) - y_pna)
    return PartialCompositeResult(m, c, c / c_full if c_full else 0.0, y_pna, a)
