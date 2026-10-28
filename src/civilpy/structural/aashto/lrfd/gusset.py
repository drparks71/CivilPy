#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.
"""Gusset-plate resistance checks for truss joints.

Two families are provided so historic ratings can be reproduced before the
current provisions are applied to the same geometry:

* **LRFD 6.14.2.8 / MBE 6A.6.12** (2013 interims onward, NCHRP 12-84):
  fastener resistance, Whitmore tension (yield / fracture), Whitmore
  compression (6.14.2.8.4 column with K and Lmid, and the partial-shear-plane
  check for compression chords), plate shear with the Omega = 0.88 shear-yield
  reduction (6.14.2.8.3), block shear (6.13.4), and the edge-slenderness limit
  (6.14.2.8.7).
* **FHWA-IF-09-014 in Load Factor terms** as implemented by the 2012 ODOT
  gusset spreadsheet (``lfr_*`` functions): rivet shear / bearing "rivet
  count" check, Whitmore tension on the effective area An + beta*Ag,
  Whitmore compression as an AASHTO 10.54 column (K = 1.2, Cc), block shear
  1 = phi(0.58 Fy Avg + Fu Atn) and 2 = phi(0.58 Fu Avn + Fy Atg), global
  shear yield with Omega = 0.74 and fracture on the net section, member
  tear-out (block shear in the member's base metal, check 6) and combined
  planes shear rupture (a gusset quadrant, check 7).  The 2012
  ODOT OSE LFR gusset rating sheet (2012) is the reference: its
  joint-42133 and joint-11000 numbers are reproduced in the tests.

All inputs are geometric quantities from
:mod:`civilpy.structural.gusset_geometry` (areas in in^2 already integrated
over the remaining thickness, lengths in inches) plus material strengths in
ksi; results are :class:`~civilpy.structural.aashto.lrfd.core.CheckResult`
with ``capacity`` = nominal resistance (kip) and ``phi`` set, unless the
docstring says the factored resistance is returned.
"""
from __future__ import annotations

import math

from civilpy.structural.aashto.lrfd.core import CheckResult

E_STEEL = 29000.0


# --------------------------------------------------------------------------- #
# rating factors
# --------------------------------------------------------------------------- #
def lfr_rating_factor(capacity_factored: float, dl: float, ll: float,
                      f1: float = 1.3, f2: float = 2.17) -> float:
    """Load-factor rating RF = (C - f1*DL) / (f2*LL).  Inventory f2 = 2.17
    (1.3 x 1.67), operating f2 = 1.3.  ``ll`` must already carry impact and
    multiple presence if the rating wants them (the 2012 ODOT gusset sheet
    applied NEITHER -- it used the STAAD live-load axials as they were)."""
    if ll <= 0:
        return float("inf")
    return (capacity_factored - f1 * abs(dl)) / (f2 * ll)


# --------------------------------------------------------------------------- #
# 2009-guidance / Load Factor versions (2012 ODOT sheet)
# --------------------------------------------------------------------------- #
def lfr_rivet_check(n_fasteners: int, d: float, t_gusset_total: float, t_base_total: float,
                    connection_length: float, fv_rivet: float = 28.0, fy_plate: float = 45.0,
                    omega_shear: float = 0.74, phi_bearing: float = 0.9,
                    long_joint_limit: float = 50.0, long_joint_factor: float = 0.8) -> CheckResult:
    """2012 sheet check 3 "Minimum Rivet Count": factored capacity of the
    member-end fastener group = min(rivet shear n*Ar*(Omega*Fv)*(0.8 if the
    connection is longer than 50 in), bearing on the gussets n*d*t*(phi Fy),
    bearing on the member base metal).  ``capacity`` is the *factored*
    value (phi already inside), ``phi`` = 1.0."""
    a_r = math.pi * d ** 2 / 4.0
    f_v = omega_shear * fv_rivet
    c_shear = n_fasteners * a_r * f_v * (long_joint_factor if connection_length > long_joint_limit else 1.0)
    c_bear = n_fasteners * d * t_gusset_total * phi_bearing * fy_plate
    c_base = n_fasteners * d * t_base_total * phi_bearing * fy_plate
    c = min(c_shear, c_bear, c_base)
    return CheckResult(article="FHWA-09 / AASHTO 10.16.14", name="Rivet shear and bearing (LFR)",
                       capacity=c, phi=1.0,
                       details={"C_shear": c_shear, "C_bearing_gusset": c_bear, "C_bearing_base": c_base,
                                "Fv": f_v, "governing": min((c_shear, "shear"), (c_bear, "bearing_gusset"),
                                                              (c_base, "bearing_base"))[1]})


def lfr_whitmore_tension(a_gross: float, a_net: float, fy: float = 45.0, beta: float = 0.15) -> CheckResult:
    """2012 sheet check 4: tension on the Whitmore section with the effective
    area Ae = An + beta*Ag; capacity = Fy*Ae (the sheet applies no phi
    here).  Areas for both plates."""
    a_e = a_net + beta * a_gross
    return CheckResult(article="FHWA-09 §3.4 (LFR)", name="Whitmore tension (LFR, Ae = An + beta Ag)",
                       capacity=fy * a_e, phi=1.0, details={"Ae": a_e})


def lfr_whitmore_compression(a_gross: float, t: float, lc: float, fy: float = 45.0,
                             k: float = 1.2, phi: float = 0.85) -> CheckResult:
    """2012 sheet check 2: Whitmore section as an AASHTO 10.54 column,
    r = t/sqrt(12), KL/r with K = 1.2 and L = Lc; Fcr = Fy(1 - (KL/r)^2 /
    (2 Cc^2)) for KL/r <= Cc, else pi^2 E/(KL/r)^2.  ``capacity`` is the
    nominal Fcr*Ag; ``phi`` = 0.85."""
    r = t / math.sqrt(12.0)
    klr = k * lc / r
    cc = math.sqrt(2 * math.pi ** 2 * E_STEEL / fy)
    if klr <= cc:
        fcr = fy * (1 - klr ** 2 / (2 * cc ** 2))
    else:
        fcr = math.pi ** 2 * E_STEEL / klr ** 2
    return CheckResult(article="AASHTO 10.54 (LFR)", name="Whitmore compression buckling (LFR)",
                       capacity=fcr * a_gross, phi=phi, details={"KL/r": klr, "Cc": cc, "Fcr": fcr})


def lfr_block_shear(a_vg: float, a_vn: float, a_tg: float, a_tn: float,
                    fy: float = 45.0, fu: float = 70.0, phi: float = 0.85) -> CheckResult:
    """2012 sheet checks 5/6: capacity 1 = phi(0.58 Fy Avg + Fu Atn),
    capacity 2 = phi(0.58 Fu Avn + Fy Atg); the smaller governs.
    ``capacity`` is factored (phi inside), ``phi`` = 1.0."""
    c1 = phi * (0.58 * fy * a_vg + fu * a_tn)
    c2 = phi * (0.58 * fu * a_vn + fy * a_tg)
    return CheckResult(article="FHWA-09 §3.6 (LFR)", name="Block shear (LFR)", capacity=min(c1, c2), phi=1.0,
                       details={"C1": c1, "C2": c2})


def lfr_global_shear(a_gross: float, a_net: float, fy: float = 45.0, fu: float = 70.0,
                     omega: float = 0.74, phi_fracture: float = 0.85) -> CheckResult:
    """2012 sheet check 8: shear yield on the gross section 0.58 Fy Avg
    reduced by Omega = 0.74 and shear fracture phi 0.58 Fu Avn; the smaller
    governs.  Areas for both plates along the full plate width / height."""
    c_y = omega * 0.58 * fy * a_gross
    c_f = phi_fracture * 0.58 * fu * a_net
    return CheckResult(article="FHWA-09 §3.7 (LFR)", name="Global shear yield / fracture (LFR)",
                       capacity=min(c_y, c_f), phi=1.0, details={"C_yield": c_y, "C_fracture": c_f})


def lfr_member_tear_out(shear_gross_len: float, shear_net_len: float, tension_gross_len: float,
                        tension_net_len: float, t_base_total: float, fy: float = 45.0, fu: float = 70.0,
                        phi: float = 0.85) -> CheckResult:
    """2012 sheet check 6 "Members Tear Out (Block Shear)": block shear in
    the MEMBER's base metal along the same fastener-group path as the
    gusset block shear (check 5).  The path lengths (shear planes summed,
    tension plane) are the gusset's; the areas are those lengths times
    ``t_base_total``, the member's base-metal thickness summed over both
    sides.  Capacity 1 = phi(0.58 Fy Avg + Fu Atn), capacity 2 =
    phi(0.58 Fu Avn + Fy Atg); the smaller governs.

    The sheet applies it only to member ends spliced at the joint and not
    milled (an unspliced member is continuous through the joint and cannot
    tear out); the caller makes that call.  ``capacity`` is factored (phi
    inside), ``phi`` = 1.0.  The sheet notes the base-metal thickness is
    conservative (corner angles may add capacity)."""
    a_vg, a_vn = shear_gross_len * t_base_total, shear_net_len * t_base_total
    a_tg, a_tn = tension_gross_len * t_base_total, tension_net_len * t_base_total
    bs = lfr_block_shear(a_vg, a_vn, a_tg, a_tn, fy, fu, phi=phi)
    return CheckResult(article="FHWA-09 §3.6 (LFR), member base metal", name="Member tear-out (LFR)",
                       capacity=bs.capacity, phi=1.0,
                       details={**bs.details, "A_vg": a_vg, "A_vn": a_vn, "A_tg": a_tg, "A_tn": a_tn,
                                "t_base_total": t_base_total})


def lfr_member_tear_out_rf(capacity_factored: float, dl: float, ll_comp: float, ll_tens: float,
                           f1: float = 1.3, f2: float = 2.17) -> float:
    """Rating factor of check 6 the way the 2012 sheet forms it:
    RF = (C - f1 |DL|) / (f2 max(|LL+I compression|, |LL+I tension|)).

    Note the sheet subtracts the ABSOLUTE dead load, so a dead load that
    relieves the tension check still reduces the RF (conservative), and it
    takes the larger live load of either sense.  Unfactored inputs."""
    ll = max(abs(ll_comp), abs(ll_tens))
    if ll <= 0:
        return float("inf")
    return (capacity_factored - f1 * abs(dl)) / (f2 * ll)


def lfr_combined_planes(a_h_gross: float, a_h_net: float, a_v_gross: float, a_v_net: float,
                        fy: float = 45.0, fu: float = 70.0, phi: float = 0.85) -> CheckResult:
    """2012 sheet check 7 "Combined Planes Shear Rupture Resistance" for one
    gusset quadrant: a tension diagonal (alone, or with a tension vertical)
    pulling the quadrant out, its horizontal component resisted on the
    quadrant's horizontal cut and its vertical component on the vertical
    cut.  Areas are for both plates (cut length x the smaller Whitmore
    thickness of the inner plus the outer plate, as the sheet takes them).

    Two cases, each giving a horizontal and a vertical capacity:

    * A - shear yield & tension fracture:  H = phi(0.58 Fy Ahg + Fu Ahn),
      V = phi(0.58 Fy Avg + Fu Avn)
    * B - shear fracture & tension yield:  H = phi(0.58 Fu Ahn + Fy Ahg),
      V = phi(0.58 Fu Avn + Fy Avg)

    As in the sheet, each direction's capacity takes both its shear and its
    tension term from the SAME cut (the horizontal capacity from the
    horizontal cut's gross and net areas).  ``capacity`` = the smallest of
    the four (factored, phi inside), ``phi`` = 1.0; the four are in
    ``details`` for :func:`lfr_combined_planes_rf`."""
    h_a = phi * (0.58 * fy * a_h_gross + fu * a_h_net)
    v_a = phi * (0.58 * fy * a_v_gross + fu * a_v_net)
    h_b = phi * (0.58 * fu * a_h_net + fy * a_h_gross)
    v_b = phi * (0.58 * fu * a_v_net + fy * a_v_gross)
    return CheckResult(article="FHWA-09 (LFR), 2012 ODOT sheet check 7", name="Combined planes shear rupture (LFR)",
                       capacity=min(h_a, v_a, h_b, v_b), phi=1.0,
                       details={"H_A": h_a, "V_A": v_a, "H_B": h_b, "V_B": v_b})


def lfr_combined_planes_rf(check: CheckResult, dl_h: float, dl_v: float, ll_h: float, ll_v: float,
                           f1: float = 1.3, f2: float = 2.17) -> dict:
    """Rating factors of one quadrant (check 7): RF = (C - f1 DL) / (f2 LL)
    for the horizontal and the vertical component in each case.  ``dl_*``
    and ``ll_*`` are the UNFACTORED tension components of the diagonal (or
    the diagonal plus the vertical when both are in tension) in that
    direction, LL with impact; the sheet rates only members in tension or
    reversal.  Returns ``{"H_A", "V_A", "H_B", "V_B", "min"}`` (inf where
    the live-load component is zero)."""
    d = check.details
    out = {}
    for key, dl, ll in (("H_A", dl_h, ll_h), ("V_A", dl_v, ll_v), ("H_B", dl_h, ll_h), ("V_B", dl_v, ll_v)):
        out[key] = float("inf") if ll <= 0 else (d[key] - f1 * dl) / (f2 * ll)
    out["min"] = min(out.values())
    return out


# --------------------------------------------------------------------------- #
# LRFD 6.14.2.8 / MBE 6A.6.12
# --------------------------------------------------------------------------- #
def fastener_shear_resistance(n_fasteners: int, d: float, fu_fastener: float, planes: int = 1,
                              threads_excluded: bool = True, rivet: bool = False,
                              connection_length: float = 0.0) -> CheckResult:
    """Factored shear resistance of the fastener group (6.13.2.7; rivets per
    MBE 6A.6.12.6.1 with the rivet shear strength taken as 0.75 Fu on the
    rivet area, phi_s = 0.80).  Joints longer than 38 in between extreme
    fasteners take the 0.83 reduction."""
    a = math.pi * d ** 2 / 4.0
    if rivet:
        rn = 0.75 * fu_fastener * a * planes * n_fasteners
    else:
        c = 0.56 if threads_excluded else 0.45
        rn = c * fu_fastener * a * planes * n_fasteners
    if connection_length > 38.0:
        rn *= 0.83
    return CheckResult(article="6.13.2.7 / MBE 6A.6.12.6.1", name="Fastener group shear",
                       capacity=rn, phi=0.80, details={"per_fastener": rn / max(n_fasteners, 1)})


def whitmore_tension_resistance(a_gross: float, a_net: float, fy: float, fu: float,
                                u: float = 1.0) -> CheckResult:
    """6.14.2.8.5 / 6.8.2.1: lesser of phi_y Fy Ag (0.95) and phi_u Fu An U
    (0.80).  ``capacity`` holds the governing *factored* value, phi = 1.0."""
    r_y = 0.95 * fy * a_gross
    r_u = 0.80 * fu * a_net * u
    return CheckResult(article="6.14.2.8.5", name="Whitmore tension (yield / fracture)",
                       capacity=min(r_y, r_u), phi=1.0, details={"R_yield": r_y, "R_fracture": r_u})


def whitmore_compression_resistance(a_gross: float, t: float, l_mid: float, fy: float,
                                    k: float = 0.5, phi_cg: float = 0.75) -> CheckResult:
    """6.14.2.8.4: Whitmore section as a column with K = 0.5 (0.75 where the
    gusset is not braced by an adjacent member -- pass ``k``), L = Lmid,
    r = t/sqrt(12); Pn per 6.9.4.1 (Pe >= 0.44 Po: 0.658^(Po/Pe) Po, else
    0.877 Pe); phi_cg = 0.75."""
    r = t / math.sqrt(12.0)
    klr = k * l_mid / r
    po = fy * a_gross
    pe = math.pi ** 2 * E_STEEL * a_gross / klr ** 2 if klr > 0 else float("inf")
    pn = 0.658 ** (po / pe) * po if pe >= 0.44 * po else 0.877 * pe
    return CheckResult(article="6.14.2.8.4", name="Whitmore compression", capacity=pn, phi=phi_cg,
                       details={"KL/r": klr, "Pe": pe, "Po": po})


def partial_shear_plane_resistance(a_vg_partial: float, a_g_compression: float, fy: float,
                                   t: float, l_mid: float, k: float = 0.5, phi_cs: float = 0.75,
                                   omega: float = 0.88) -> CheckResult:
    """6.14.2.8.4 chord-splice / partial shear plane: the compression member
    force is resisted by the sum of shear yield on the partial plane
    (omega 0.58 Fy Avg,partial) and compression on the Whitmore section
    beyond it.  Simplified form: Pr = phi_cs (omega 0.58 Fy Avg_partial) +
    phi_cg Pn(Whitmore).  Returns the *factored* total, phi = 1.0."""
    shear = phi_cs * omega * 0.58 * fy * a_vg_partial
    comp = whitmore_compression_resistance(a_g_compression, t, l_mid, fy, k)
    return CheckResult(article="6.14.2.8.4 (partial shear plane)", name="Partial shear plane + Whitmore compression",
                       capacity=shear + comp.factored_capacity, phi=1.0,
                       details={"R_shear_partial": shear, "R_whitmore": comp.factored_capacity})


def plate_shear_resistance(a_gross: float, a_net: float, fy: float, fu: float,
                           omega: float = 0.88) -> CheckResult:
    """6.14.2.8.3: shear yield phi_vy (1.0) * 0.58 Fy Avg * Omega, shear
    rupture phi_vu (0.80) * 0.58 Fu Avn; the smaller *factored* value is
    returned (phi = 1.0)."""
    r_y = 1.0 * 0.58 * fy * a_gross * omega
    r_u = 0.80 * 0.58 * fu * a_net
    return CheckResult(article="6.14.2.8.3", name="Gusset plate shear", capacity=min(r_y, r_u), phi=1.0,
                       details={"R_yield": r_y, "R_rupture": r_u})


def block_shear_resistance(a_vg: float, a_vn: float, a_tn: float, fy: float, fu: float,
                           u_bs: float = 1.0, r_p: float = 1.0) -> CheckResult:
    """6.13.4 block shear: Rn = Rp(0.58 Fu Avn + Ubs Fu Atn) <= Rp(0.58 Fy
    Avg + Ubs Fu Atn), phi_bs = 0.80."""
    rn = r_p * min(0.58 * fu * a_vn + u_bs * fu * a_tn, 0.58 * fy * a_vg + u_bs * fu * a_tn)
    return CheckResult(article="6.13.4", name="Block shear rupture", capacity=rn, phi=0.80,
                       details={"Rp": r_p, "Ubs": u_bs})


def edge_slenderness_ok(unsupported_edge: float, t: float, fy: float, e: float = E_STEEL) -> CheckResult:
    """6.14.2.8.7: unstiffened free edge L/t <= 2.06 sqrt(E/Fy)."""
    limit = 2.06 * math.sqrt(e / fy)
    return CheckResult(article="6.14.2.8.7", name="Edge slenderness", capacity=limit * t,
                       demand=unsupported_edge, phi=1.0, details={"limit_L_over_t": limit})


def chord_splice_section(h_plate: float, t_plates: float, d_chord: float, t_splice: float = 0.0,
                         chord_at: str = "bottom", edge: float = 0.0) -> dict:
    """Gross section of the plates crossing a chord-splice plane, as an equivalent beam: the gusset plates
    (height ``h_plate`` x total thickness ``t_plates``) plus any splice plates (chord depth ``d_chord`` x total
    thickness ``t_splice``) centred on the chord.  The chord centroid sits ``edge + d_chord/2`` from the plate
    edge named by ``chord_at`` ("bottom" for a lower-chord joint, "top" for an upper one).  Returns ``A``,
    ``S`` (section modulus to the edge on the chord side, where axial and bending stresses add), ``e_p`` (chord
    force to section centroid) and ``y_c`` (section centroid from the plate bottom), all in inches."""
    y_chord = edge + d_chord / 2.0 if chord_at == "bottom" else h_plate - edge - d_chord / 2.0
    parts = [(h_plate * t_plates, h_plate / 2.0, t_plates * h_plate ** 3 / 12.0)]
    if t_splice > 0 and d_chord > 0:
        parts.append((d_chord * t_splice, y_chord, t_splice * d_chord ** 3 / 12.0))
    a = sum(x[0] for x in parts)
    y_c = sum(x[0] * x[1] for x in parts) / a
    i = sum(x[2] + x[0] * (x[1] - y_c) ** 2 for x in parts)
    c = y_c if chord_at == "bottom" else h_plate - y_c          # edge on the chord side
    return {"A": a, "S": i / c if c else float("inf"), "e_p": abs(y_chord - y_c), "y_c": y_c, "I": i}


def chord_splice_resistance(a_g: float, s_g: float, e_p: float, fy: float, *, compression: bool,
                            fu: float | None = None, a_n: float | None = None, s_n: float | None = None,
                            e_pn: float | None = None, l_splice: float | None = None, t: float | None = None,
                            k: float = 0.5, e: float = E_STEEL, phi_cs: float = 0.85, phi_y: float = 0.95,
                            phi_u: float = 0.80) -> CheckResult:
    """MBE 6A.6.12.6.9 / LRFD 6.14.2.8.6 chord splice: the plates crossing the splice plane act as a short beam
    carrying the chord force at eccentricity ``e_p`` from their centroid, so the usable axial resistance is the
    plain-section resistance divided by (1 + e_p A / S).

    Compression (``compression=True``): Pr = phi_cs Fcr Ag / (1 + e_p Ag / Sg); Fcr = Fy when the splice slenderness
    K Lsplice / r (r = t / sqrt(12), K = 0.5, Lsplice between the first fastener lines of the two chords) is 25 or
    less, else the 6.9.4.1 column curve; Fcr = Fy when ``l_splice`` is not given.  Tension: the smaller of
    phi_y Fy Ag / (1 + e_p Ag / Sg) and phi_u Fu An / (1 + e_pn An / Sn).  ``capacity`` is the *factored* value,
    ``phi`` = 1.0.  Verify the resistance factors against the MBE edition in force before reporting."""
    if compression:
        fcr = fy
        if l_splice and t:
            klr = k * l_splice / (t / math.sqrt(12.0))
            if klr > 25.0:
                pe = math.pi ** 2 * e / klr ** 2
                fcr = (0.658 ** (fy / pe)) * fy if pe >= 0.44 * fy else 0.877 * pe
        pr = phi_cs * fcr * a_g / (1.0 + e_p * a_g / s_g)
        return CheckResult(article="MBE 6A.6.12.6.9 / LRFD 6.14.2.8.6", name="Chord splice (compression)", capacity=pr,
                           phi=1.0, details={"Fcr": fcr, "Ag": a_g, "Sg": s_g, "e_p": e_p, "amplifier": 1.0 + e_p * a_g / s_g})
    r_y = phi_y * fy * a_g / (1.0 + e_p * a_g / s_g)
    r_u = float("inf")
    if fu and a_n and s_n:
        r_u = phi_u * fu * a_n / (1.0 + (e_pn if e_pn is not None else e_p) * a_n / s_n)
    return CheckResult(article="MBE 6A.6.12.6.9 / LRFD 6.14.2.8.6", name="Chord splice (tension)", capacity=min(r_y, r_u),
                       phi=1.0, details={"R_yield": r_y, "R_fracture": r_u, "Ag": a_g, "Sg": s_g, "e_p": e_p})


def pin_bearing_resistance(d_pin: float, t_bearing: float, fy: float, phi_b: float = 1.0) -> CheckResult:
    """LRFD 6.7.6.2.2 bearing on a pin: (Pn)b = 1.5 t d Fy over the total plate thickness bearing on the pin;
    phi_b = 1.0 for pins in bored holes (6.5.4.2)."""
    pn = 1.5 * t_bearing * d_pin * fy
    return CheckResult(article="6.7.6.2.2", name="Pin bearing", capacity=pn, phi=phi_b,
                       details={"d": d_pin, "t_bearing": t_bearing})


def pin_shear_resistance(d_pin: float, fy: float, planes: int = 2, phi_v: float = 1.0) -> CheckResult:
    """LRFD 6.7.6.2.1 pin shear: Vn = 0.58 Fy Ap per shear plane (pin material assumed the structure's steel unless
    the plans say otherwise); phi_v = 1.0."""
    ap = math.pi * d_pin ** 2 / 4.0
    return CheckResult(article="6.7.6.2.1", name="Pin shear", capacity=planes * 0.58 * fy * ap, phi=phi_v,
                       details={"Ap": ap, "planes": planes})


def pin_flexure_resistance(d_pin: float, fy: float, phi_f: float = 1.0) -> CheckResult:
    """LRFD 6.7.6.2.1 pin flexure: Mn = Fy D^3 / 6 (the plastic modulus of a round, 6.7.6.2.1-1); phi_f = 1.0."""
    mn = fy * d_pin ** 3 / 6.0
    return CheckResult(article="6.7.6.2.1", name="Pin flexure", capacity=mn, phi=phi_f, details={"Z": d_pin ** 3 / 6.0})


def pin_interaction(m_u: float, m_r: float, v_u: float, v_r: float) -> float:
    """LRFD 6.7.6.2.1-3 combined flexure and shear on a pin: (Mu/Mr)^2 + (Vu/Vr)^2 <= 1.0.  Returns the ratio."""
    return (m_u / m_r) ** 2 + (v_u / v_r) ** 2 if m_r and v_r else float("inf")
