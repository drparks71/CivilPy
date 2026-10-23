#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Design-year / spec-edition handling for historical bridge designs.

Checks in this package implement the **current** LRFD edition by default.
Bridges are long-lived, so checks whose governing *values* changed between
editions accept an optional ``design_year``; passing the year the bridge
was designed selects the values in force at that time.  Checks without a
``design_year`` parameter are value-stable across the editions this package
tracks (equation renumbering alone doesn't matter — functions are keyed to
current numbering).

Known value changes wired into checks so far:

========== ======================= ====================================
Year       Article (current num.)  Change
========== ======================= ====================================
2005       5.6.7                   z-factor crack check replaced by the
                                   max-spacing method (use
                                   ``rc_crack_control_z_factor`` for
                                   pre-2005 designs)
2008       4.6.2.6                 effective flange width became simply S
2012       5.6.3.3                 1.2*Mcr replaced by gamma_1*gamma_3
2015       5.4.2.3                 ktd time-development factor revised
2015       6.9.4.1.1               phi_c for steel columns 0.90 -> 0.95
2016       5.9.2.3.1a              transfer compression 0.60 -> 0.65 f'ci
2017       6.13.2.7                bolt shear C 0.48 / 0.38 -> 0.56 / 0.45
2024       6.10.8.2.3a             Lp 1.0 -> 1.1 rt sqrt(E/Fyc); LTB
                                   Fyr 0.5 Fyc welded / 0.7 Fyc rolled
2024       6.10.6.2.3              lambda_rw 5.7 -> c_rw sqrt(E/Fyc),
                                   c_rw = 3.1 + 5/a_wc in 4.6..5.7
2024       6.10.1.6                first-order f_l limit 1.2 -> 1.1 Lp
2024       6.10.8.2.3b             C_b from M_max, M_A, M_B, M_C
                                   (:func:`moment_gradient_factor`)
========== ======================= ====================================
"""

from __future__ import annotations

# (first publication year, label) for each LRFD edition
LRFD_EDITIONS = [
    (1994, "1st"),
    (1998, "2nd"),
    (2004, "3rd"),
    (2007, "4th"),
    (2010, "5th"),
    (2012, "6th"),
    (2014, "7th"),
    (2017, "8th"),
    (2020, "9th"),
    (2024, "10th"),
]


def lrfd_edition(design_year: int | None = None) -> str:
    """Label of the LRFD edition in force for a given design year (the
    latest edition published in or before that year).  ``None`` means
    current."""
    if design_year is None:
        return LRFD_EDITIONS[-1][1]
    label = LRFD_EDITIONS[0][1]
    for year, name in LRFD_EDITIONS:
        if design_year >= year:
            label = name
    return label
