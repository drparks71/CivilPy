"""Heat-straightening repair of damaged steel members (Avent's method) --
damage measurement, the damage-strain limit, vee-heat geometry, plastic
rotation per heat, the number of heats and the jacking limits.

Sources (NSBA library): FHWA-IF-08-999 *Guide for Heat-Straightening of
Damaged Steel Bridge Members* ("Guide", Eq. numbers below) and FHWA-IF-99-004
*Heat-Straightening Repairs of Damaged Steel Bridges, A Technical Guide and
Manual of Practice* ("Manual", whose Examples 3.1, 5.1, 6.1 and 7.1 the tests
reproduce); FHWA-HIF-23-003 updates both without changing these equations.

Damage (Guide 3.3.2.2): the angle of damage phi_d from offsets outside the
yield zone (Eq. 3.1) or from the radius of curvature over the damaged
length (Eqs. 3.2-3.4); the strain ratio mu = E y_max / (R Fy) (Eq. 3.8),
with heat straightening proven up to mu = 100.

Plastic rotation per vee heat at 1,200 F (Guide Eqs. 5.1-5.3, 6.1-6.5):
``phi_p = F_l F_s F_a phi_b`` with ``phi_b = 0.0147 sin(theta / 3)``,
``F_l = 0.6 + 2 M_j / M_p`` (jacking), ``F_s = 1 + (b_s d_s / d^2) / 2``
(stiffening element) and ``F_a = 1 - 2 [1 - (2/3) Z/S] M_j / M_p`` (stress;
Z/S multiplied by F_s for angles); the heats needed are ``phi_d / phi_p``
(Eq. 3.11).  Other temperatures scale the plate rotation by
``F_t = 0.5 + 0.00125 (T - 800)`` (Manual Eq. 5.18).

Angles in radians unless named ``_deg``; lengths in any consistent unit.
"""

from __future__ import annotations

#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import math

E_STEEL = 29000.0
#: largest strain ratio with research support (Guide 3.3.2.2 / 3.4.1)
STRAIN_RATIO_LIMIT = 100.0
#: recommended maximum heating temperature, deg F (AWS D1.5 12.12 range)
MAX_TEMPERATURE_F = 1200.0


# ── damage ──────────────────────────────────────────────────────────────────


def angle_of_damage(y1: float, y2: float, l1: float, y3: float, y4: float, l2: float) -> float:
    """phi_d from offsets taken outside the yield zone (Guide Eq. 3.1):
    ``atan((y2 - y1) / L1) + atan((y3 - y4) / L2)`` -- the change of slope
    between the two straight tangents."""
    return math.atan((y2 - y1) / l1) + math.atan((y3 - y4) / l2)


def radius_of_curvature(y_before: float, y_at: float, y_after: float, spacing: float) -> float:
    """R from three offsets in the yield zone at equal ``spacing`` (Guide
    Eq. 3.2): ``1/R = (y_{r-1} - 2 y_r + y_{r+1}) / L^2``; returned as a
    magnitude."""
    return abs(spacing ** 2 / (y_before - 2.0 * y_at + y_after))


def angle_from_radius(chord: float, radius: float) -> float:
    """phi_d of a uniformly curved damage zone of chord ``chord`` (Guide
    Eq. 3.4): ``2 asin(L / 2R)``.  (The Guide prints ``2 asin(L/R)`` with
    ``sin(phi_d/2) = L/R``, which is the half-chord form.)"""
    return 2.0 * math.asin(chord / (2.0 * radius))


def yield_radius(y_max: float, fy: float, e: float = E_STEEL) -> float:
    """Radius of curvature at first yield, ``E y_max / F_y`` (Guide
    Eq. 3.5)."""
    return e * y_max / fy


def strain_ratio(radius: float, y_max: float, fy: float, e: float = E_STEEL) -> float:
    """mu = eps_max / eps_y = E y_max / (R F_y) (Guide Eq. 3.8)."""
    return e * y_max / (radius * fy)


def straightenable(mu: float) -> bool:
    """Within the research-supported damage-strain range (mu <= 100);
    beyond it the Guide asks for engineering judgment."""
    return mu <= STRAIN_RATIO_LIMIT


# ── vee heats ───────────────────────────────────────────────────────────────


def vee_angle(open_width: float, plate_width: float) -> float:
    """Vee angle (radians) for an open end ``V`` on a plate of width ``W``
    (Guide Eq. 3.9): ``2 atan(V / 2W)``.  Rule of thumb: V from 1/3 to 1/2
    of W and at most 10 in., about 20-30 degrees."""
    return 2.0 * math.atan(open_width / (2.0 * plate_width))


def temperature_factor(t_f: float) -> float:
    """F_t(T) = 0.5 + 0.00125 (T - 800), T in deg F, 1.0 at 1,200 F
    (Manual Eq. 5.18; 750-1,200 F)."""
    if t_f > MAX_TEMPERATURE_F:
        raise ValueError("heating above 1,200 F is outside the method (and AWS D1.5)")
    return 0.5 + 0.00125 * (t_f - 800.0)


def basic_plastic_rotation(theta_deg: float, t_f: float = 1200.0) -> float:
    """phi_b = 0.0147 sin(theta / 3) radians at 1,200 F (Guide Eq. 6.2),
    scaled by :func:`temperature_factor` at other temperatures."""
    return 0.0147 * math.sin(math.radians(theta_deg) / 3.0) * temperature_factor(t_f)


def jacking_factor(jacking_ratio: float) -> float:
    """F_l = 0.6 + 2 M_j / M_p (Guide Eqs. 5.2 / 6.4)."""
    return 0.6 + 2.0 * jacking_ratio


def shape_factor(b_s: float, d_s: float, d: float) -> float:
    """F_s = 1 + (b_s d_s / d^2) / 2 for a stiffening element of width
    ``b_s`` meeting the vee-heated element of depth ``d`` at ``d_s`` from
    the vee apex (Guide Eq. 6.5)."""
    return 1.0 + 0.5 * b_s * d_s / d ** 2


def stress_factor(z_over_s: float, jacking_ratio: float, *, angle_shape_factor: float | None = None) -> float:
    """F_a = 1 - 2 [1 - (2/3)(Z/S)] M_j / M_p (Guide Eq. 6.3); for angles
    Z/S is multiplied by the shape factor."""
    zs = z_over_s * (angle_shape_factor if angle_shape_factor is not None else 1.0)
    return 1.0 - 2.0 * (1.0 - 2.0 / 3.0 * zs) * jacking_ratio


def plastic_rotation(theta_deg: float, jacking_ratio: float, *, z_over_s: float | None = None,
                     b_s: float = 0.0, d_s: float = 0.0, d: float = 1.0, angle: bool = False,
                     t_f: float = 1200.0) -> float:
    """Plastic rotation per vee heat (radians).  A plate (``z_over_s`` None):
    ``F_l phi_b`` (Guide Eq. 5.3); a rolled shape: ``F_l F_s F_a phi_b``
    (Eq. 6.1)."""
    phi_b = basic_plastic_rotation(theta_deg, t_f)
    f_l = jacking_factor(jacking_ratio)
    if z_over_s is None:
        return f_l * phi_b
    f_s = shape_factor(b_s, d_s, d) if b_s else 1.0
    f_a = stress_factor(z_over_s, jacking_ratio, angle_shape_factor=f_s if angle else None)
    return f_l * f_s * f_a * phi_b


def heats_required(phi_d: float, phi_p: float) -> int:
    """Number of heating cycles, phi_d / phi_p rounded up (Guide Eq. 3.11)."""
    return math.ceil(phi_d / phi_p - 1e-9)


# ── jacking limits ──────────────────────────────────────────────────────────


def jacking_moment_limit(m_p: float, *, first_two_heats: bool = False,
                         residuals_computed: bool = True) -> float:
    """Largest jacking moment: M_p / 2 (Guide Eq. 3.10), or M_p / 4 for
    the first two heats when residual moments are not computed."""
    if first_two_heats and not residuals_computed:
        return 0.25 * m_p
    return 0.5 * m_p


def composite_flange_distribution(d_over_tw: float) -> float:
    """gamma, the share of a lateral jacking moment that reaches the lower
    flange of a composite girder through web-flange interaction (Manual
    Eq. 7.16): ``(d/t_w) / 10,000 [15 + 2.75 d/t_w]``."""
    return d_over_tw / 10_000.0 * (15.0 + 2.75 * d_over_tw)


def composite_jacking_moment(m_p_flange: float, d_over_tw: float, residual: float = 0.0) -> float:
    """Apparent jacking moment for the lower flange of a composite girder:
    the flange moment limited to M_p / 3 (Manual Eq. 7.21) less the
    residual moment, divided by :func:`composite_flange_distribution`."""
    return (m_p_flange / 3.0 - residual) / composite_flange_distribution(d_over_tw)
