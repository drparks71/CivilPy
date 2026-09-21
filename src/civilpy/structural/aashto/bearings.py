#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Bridge-bearing suitability screening.

``BearingSuitability`` compares candidate bearing types (elastomeric, HLMR,
…) against load, movement, and rotation demands following the guidance of
AASHTO LRFD Section 14.
"""

import pandas as pd
from .durometer import get_strain_from_stress

class BearingSuitability:
    """
    A class to assist determining suitability of various types of bearings for various types of loading
    Situations.  The class is intended to be used as follows.

    As Reference:
        bearing_table = BearingSuitability().table
        print(bearing_table)

    As Code:
        if BearingSuitability(type, movement, axis):
            perform_action()
        else:
            continue
    """
    def __init__(self, type='rectangular', movement='fixed', axis='x'):
        """Initialise a BearingSuitability checker and build the lookup table.

        Args:
            type (str): Bearing type descriptor (e.g. ``'rectangular'``).
            movement (str): Expected movement type (``'fixed'`` or
                ``'expansion'``).
            axis (str): Principal movement axis (``'x'`` longitudinal or
                ``'y'`` transverse).
        """
        self.type = type
        self.movement = movement
        self.axis = axis
        self.table = self.get_table()

    def get_table(self):
        """Build and return the AASHTO bearing suitability reference table.

        Suitability ratings are derived from AASHTO LRFD Bridge Design
        Specifications, Table 14.6.2-1 (Bearing Suitability).

        The table maps movement/rotation/load categories to bearing types with
        suitability codes: ``'S'`` = suitable, ``'U'`` = unsuitable,
        ``'R'`` = requires special consideration, ``'L'`` = suitable for
        limited applications.

        Returns:
            pandas.DataFrame: Rows are bearing types; columns are movement,
            rotation, and load categories.
        """
        table = {
            'Movement:Longitudinal': {
                'Plain Elastomeric Pad': 'S',
                'Fiberglass-Reinforced Pad': 'S',
                'Cotton-duck-reinforced Pad': 'U',
                'Steel-Reinforced Elastomeric Bearing': 'S',
                'Plane Sliding Bearing': 'S',
                'Curved Sliding Spherical Bearing': 'R',
                'Curved Sliding Cylindrical Bearing': 'R',
                'Disc Bearing': 'R',
                'Double Cylindrical Bearing': 'R',
                'Pot Bearing': 'R',
                'Rocker Bearing': 'S',
                'Knuckle Pinned Bearing': 'U',
                'Single Roller Bearing': 'S',
                'Multiple Roller Bearing': 'S',
            },
            'Movement:Transverse': {
                'Plain Elastomeric Pad': 'S',
                'Fiberglass-Reinforced Pad': 'S',
                'Cotton-duck-reinforced Pad': 'U',
                'Steel-Reinforced Elastomeric Bearing': 'S',
                'Plane Sliding Bearing': 'S',
                'Curved Sliding Spherical Bearing': 'R',
                'Curved Sliding Cylindrical Bearing': 'R',
                'Disc Bearing': 'R',
                'Double Cylindrical Bearing': 'R',
                'Pot Bearing': 'R',
                'Rocker Bearing': 'U',
                'Knuckle Pinned Bearing': 'U',
                'Single Roller Bearing': 'U',
                'Multiple Roller Bearing': 'U',
            },
            'Rotation:Longitudinal': {
                'Plain Elastomeric Pad': 'S',
                'Fiberglass-Reinforced Pad': 'S',
                'Cotton-duck-reinforced Pad': 'U',
                'Steel-Reinforced Elastomeric Bearing': 'S',
                'Plane Sliding Bearing': 'U',
                'Curved Sliding Spherical Bearing': 'S',
                'Curved Sliding Cylindrical Bearing': 'U',
                'Disc Bearing': 'S',
                'Double Cylindrical Bearing': 'S',
                'Pot Bearing': 'S',
                'Rocker Bearing': 'U',
                'Knuckle Pinned Bearing': 'U',
                'Single Roller Bearing': 'U',
                'Multiple Roller Bearing': 'U',
            },
            'Rotation:Transverse': {
                'Plain Elastomeric Pad': 'S',
                'Fiberglass-Reinforced Pad': 'S',
                'Cotton-duck-reinforced Pad': 'U',
                'Steel-Reinforced Elastomeric Bearing': 'S',
                'Plane Sliding Bearing': 'U',
                'Curved Sliding Spherical Bearing': 'S',
                'Curved Sliding Cylindrical Bearing': 'S',
                'Disc Bearing': 'S',
                'Double Cylindrical Bearing': 'S',
                'Pot Bearing': 'S',
                'Rocker Bearing': 'S',
                'Knuckle Pinned Bearing': 'S',
                'Single Roller Bearing': 'S',
                'Multiple Roller Bearing': 'U',
            },
            'Rotation:Vertical': {
                'Plain Elastomeric Pad': 'L',
                'Fiberglass-Reinforced Pad': 'L',
                'Cotton-duck-reinforced Pad': 'U',
                'Steel-Reinforced Elastomeric Bearing': 'L',
                'Plane Sliding Bearing': 'S',
                'Curved Sliding Spherical Bearing': 'S',
                'Curved Sliding Cylindrical Bearing': 'U',
                'Disc Bearing': 'L',
                'Double Cylindrical Bearing': 'U',
                'Pot Bearing': 'L',
                'Rocker Bearing': 'U',
                'Knuckle Pinned Bearing': 'U',
                'Single Roller Bearing': 'U',
                'Multiple Roller Bearing': 'U',
            },
            'Load Resistance:Longitudinal': {
                'Plain Elastomeric Pad': 'L',
                'Fiberglass-Reinforced Pad': 'L',
                'Cotton-duck-reinforced Pad': 'L',
                'Steel-Reinforced Elastomeric Bearing': 'L',
                'Plane Sliding Bearing': 'R',
                'Curved Sliding Spherical Bearing': 'R',
                'Curved Sliding Cylindrical Bearing': 'R',
                'Disc Bearing': 'S',
                'Double Cylindrical Bearing': 'R',
                'Pot Bearing': 'S',
                'Rocker Bearing': 'R',
                'Knuckle Pinned Bearing': 'S',
                'Single Roller Bearing': 'U',
                'Multiple Roller Bearing': 'U',
            },
            'Load Resistance:Transverse': {
                'Plain Elastomeric Pad': 'L',
                'Fiberglass-Reinforced Pad': 'L',
                'Cotton-duck-reinforced Pad': 'L',
                'Steel-Reinforced Elastomeric Bearing': 'L',
                'Plane Sliding Bearing': 'R',
                'Curved Sliding Spherical Bearing': 'R',
                'Curved Sliding Cylindrical Bearing': 'R',
                'Disc Bearing': 'S',
                'Double Cylindrical Bearing': 'R',
                'Pot Bearing': 'S',
                'Rocker Bearing': 'R',
                'Knuckle Pinned Bearing': 'R',
                'Single Roller Bearing': 'R',
                'Multiple Roller Bearing': 'U',
            },
            'Load Resistance:Vertical': {
                'Plain Elastomeric Pad': 'L',
                'Fiberglass-Reinforced Pad': 'L',
                'Cotton-duck-reinforced Pad': 'S',
                'Steel-Reinforced Elastomeric Bearing': 'S',
                'Plane Sliding Bearing': 'S',
                'Curved Sliding Spherical Bearing': 'S',
                'Curved Sliding Cylindrical Bearing': 'S',
                'Disc Bearing': 'S',
                'Double Cylindrical Bearing': 'S',
                'Pot Bearing': 'S',
                'Rocker Bearing': 'S',
                'Knuckle Pinned Bearing': 'S',
                'Single Roller Bearing': 'S',
                'Multiple Roller Bearing': 'S',
            },
        }

        df = pd.DataFrame(table)
        return df

class MethodABearing:
    """
    Represents a Method A designed elastomeric bearing pad used in structural applications.

    The MethodABearing class is utilized to evaluate the compliance of an elastomeric bearing pad
    structured to Method A design checks. The assessment involves evaluating critical parameters
    such as internal and external layer thickness, shape factors, and edge cover, based on defined
    design specifications. Various checks are performed to ensure the pad satisfies these structural
    criteria.

    Attributes:
        width (float): The width of the bearing pad in inches.
        length (float): The length of the bearing pad in inches.
        durometer (float): The durometer hardness value of the elastomeric material.
        internal_t (float): The thickness of the internal elastomeric layers in inches.
        external_t (float): The thickness of the external elastomeric layers in inches.
        steel_t (float): The thickness of the steel reinforcing shims in inches.
        plys (int): The number of steel layers in the bearing pad.
        span (float): The span of the bridge section from bearing to bearing in ft.
        expansion_length (float): The expansion length of the bridge section (fixed bearing to fixed) in ft.
        loads (dict): A dictionary containing the loads applied to the bearing pad. - format to be updated
        max_dl_delta (float): The maximum deflection of the dead load in inches (from software/analysis).
        max_ll_delta (float): The maximum deflection of the live load in inches (from software/analysis).
        max_ll_loc (float): The location of the maximum live load in feet (from software/analysis).
        deck_slope (float): The slope of the deck in percent grade.
        plate_bev (float): The plate bevel in percent.
        edge_cover (float): The edge cover dimension in inches, default is 0.25 inches.
        checks (dict): A dictionary storing the results of various design validation checks.
        internal_shape_factor (float): The shape factor of the internal elastomeric layers.
        type (str): The shape type of the bearing pad, default is 'rectangular', alternative is 'circular'.
        holes (bool): Indicates if the bearing pad has holes, default is False.
        steel_yield_strength (float): The yield strength of the steel reinforcing shims in ksi (defaults to 60).
        shear_modulus (float): The shear modulus of the elastomeric material in ksi (defaults to 0.095).
        exp_coeff (float): The expansion coefficient of the elastomeric material in 1/in (defaults to 0.000006).
        temp_min (float): The minimum temperature of the bearing pad in degrees Fahrenheit (defaults to 15).
        temp_max (float): The maximum temperature of the bearing pad in degrees Fahrenheit (defaults to 95).
    """
    def __init__(self, width, length, durometer, internal_t, external_t, steel_t,
                 plys, span, expansion_length, loads, max_dl_delta, max_ll_delta, max_ll_loc, deck_slope, plate_bev,
                 edge_cover=.25, type='rectangular', holes=False, steel_yield_strength = 60, shear_modulus=0.095,
                 exp_coeff=.000006, temp_min=-30, temp_max=120, rotation_st=None, rotation_cy=None):
        """
        Initialize a Method A elastomeric bearing and compute derived geometry.

        Args:
            width (float): Bearing pad width, in.
            length (float): Bearing pad length, in.
            durometer (float): Elastomer hardness (Shore A durometer value).
            internal_t (float): Internal elastomer layer thickness, in.
            external_t (float): External (cover) elastomer layer thickness, in.
            steel_t (float): Steel reinforcing shim thickness, in.
            plys (int): Number of steel reinforcing layers.
            span (float): Span length from bearing to bearing, ft.
            expansion_length (float): Length from fixed bearing to expansion bearing, ft.
            loads (dict): Applied loads dictionary (format defined per project use).
            max_dl_delta (float): Maximum dead load deflection from analysis, in.
            max_ll_delta (float): Maximum live load deflection from analysis, in.
            max_ll_loc (float): Location of maximum live load, ft from bearing.
            deck_slope (float): Deck slope, percent grade.
            plate_bev (float): Sole plate bevel, percent.
            edge_cover (float): Edge cover dimension, in. Defaults to ``0.25``.
            type (str): Bearing geometry — ``'rectangular'`` (default) or ``'circular'``.
            holes (bool): ``True`` if the bearing pad has holes. Defaults to ``False``.
            steel_yield_strength (float): Shim yield strength, ksi. Defaults to ``60``.
            shear_modulus (float): Elastomer shear modulus, ksi. Defaults to ``0.095``.
            exp_coeff (float): Thermal expansion coefficient, 1/°F. Defaults to ``0.000006``.
            temp_min (float): Minimum design temperature, °F. Defaults to ``-30``.
            temp_max (float): Maximum design temperature, °F. Defaults to ``120``.
        """
        self.width = width
        self.length = length
        self.durometer = durometer
        self.internal_t = internal_t
        self.external_t = external_t
        self.steel_t = steel_t
        self.plys = plys
        self.shear_modulus = shear_modulus
        self.exp_coeff = exp_coeff
        self.height = 2 * self.external_t + (self.plys - 1) * self.internal_t + (self.plys) * self.steel_t
        self.total_laminate_thickness = self.plys * self.steel_t
        self.total_elastomer_thickness = round(2 * self.external_t + (self.plys - 1) * self.internal_t, 2)
        self.span = span
        self.expansion_length = expansion_length
        self.f_y = steel_yield_strength  # (of the laminate layers)
        self.loads = loads
        self.sigma_l = None
        self.sigma_s = None
        self.delta_t = None
        self.delta_s = None
        self.dl_deflection = None
        self.ll_deflection = None
        self.added_dl_deflection = max_dl_delta
        self.added_ll_deflection = max_ll_delta
        self.ll_location = max_ll_loc
        self.deck_slope = deck_slope
        self.plate_bev = plate_bev
        self.temp_range = (temp_min, temp_max)
        # bearing rotations from the structural analysis (rad), static (dead
        # load) and cyclic (live load); when given they replace the
        # deflection/slope proxies in the combined-strain checks (#18/#19).
        self.rotation_st = rotation_st
        self.rotation_cy = rotation_cy
        self.get_deflections()
        self.edge_cover = edge_cover
        self.checks = {}
        self.internal_shape_factor = self.get_shape_factors(self.internal_t)
        self.service_ll = self.loads["total_load"] / (self.length * self.width)
        self.service_dl = self.loads["total_dead_load"] / (self.length * self.width)

        self.run_checks()

    def get_shape_factors(self, thickness):
        """Calculate the AASHTO shape factor S for a single elastomer layer.

        Per AASHTO 14.7.5.1, S = LW / [2t_ri(L + W)].

        Args:
            thickness (float): Thickness of a single internal elastomer layer
                t_ri (inches).

        Returns:
            float: Dimensionless shape factor S.
        """
        return (self.width * self.length) / (2 * thickness * (self.length + self.width))

    def run_checks(self):
        """Execute all AASHTO Method A elastomeric bearing design checks.

        Runs checks #2 through #19 per AASHTO LRFD 14.7.6. Results are stored
        in ``self.checks`` as ``1`` (pass) or ``0`` (fail). Failed checks also
        print a descriptive message.

        Checks performed include service stress limits, deflection limits,
        shear deformation, combined strain, stability, and reinforcement
        checks.
        """
        # Each check below corresponds to an AASHTO 14.7.6 check; results stored in self.checks
        self.check_edge_cover()
        self.check_layer_thickness()
        # Excel Check '1' - Not Carried forward, see "Bearings - Notes" Notebook
        # Excel Check '2' (AASHTO 14.7.6.3.2-7)
        if self.service_ll <= 1.25 * self.shear_modulus * self.internal_shape_factor:
            self.checks['#2 - Service LL Check'] = 1
        else:
            self.checks['#2 - Service LL Check'] = 0
            print("Service LL Check Failed - Service LL > 1.25 * G * S_i")

        # Excel Check '3' (AASHTO 14.7.6.3.2-8)
        if self.service_ll <= 1.25:
            self.checks['#3 - Service LL < 1.25 ksi'] = 1
        else:
            self.checks['#3 - Service LL < 1.25 ksi'] = 0
            print("Service LL Check Failed - Service LL > 1.25 ksi")

        # Excel Check '5' (AASHTO 14.7.6.3.3 & 14.7.5.3.6)
        # Uses get_strain_from_stress (inverted power-law, AASHTO Table approach).
        # Alternative: direct formula from AASHTO C14.7.5.3.6 may be more transparent.
        # get_strain_from_stress returns the percent strain of Figure
        # C14.7.6.3.3-1; the deflection is that strain over the elastomer.
        self.ll_strain = get_strain_from_stress(self.sigma_l, self.durometer, self.internal_shape_factor)
        self.ll_deflection = self.ll_strain / 100.0 * self.total_elastomer_thickness

        if self.ll_deflection <= 0.125:
            self.checks['#5 - LL Deflection < 0.125'] = 1
        else:
            self.checks['#5 - LL Deflection < 0.125'] = 0
            print("LL Deflection Limit Check Failed - LL Deflection > 0.125")

        # Excel Check '6' (AASHTO 14.7.6.3.3 & 14.7.5.3.6)
        self.dl_strain = get_strain_from_stress(self.service_dl, self.durometer, self.internal_shape_factor)
        self.dl_deflection = self.dl_strain / 100.0 * self.total_elastomer_thickness
        total_deflection = self.ll_deflection + self.dl_deflection

        if total_deflection / self.plys <= .09 * self.internal_t:
            self.checks["#6 - Single Layer's Δ < 0.09 * h_ri"] = 1
        else:
            self.checks["#6 - Single Layer's Δ < 0.09 * h_ri"] = 0
            print("Total Deflection / Number of Plies > 0.09 * h_ri")

        # Excel Check '7' (AASHTO 14.7.6.3.3)
        creep_deflection = self.dl_deflection * rubber_creep_values[self.durometer]

        final_deflection = total_deflection + creep_deflection
        if final_deflection / self.plys <= .09 * self.internal_t:
            self.checks["#7 - Single Layer's Δ < 0.09 * h_ri - Due to Long term Creep"] = 1
        else:
            self.checks["#7 - Single Layer's Δ < 0.09 * h_ri"] = 0
            print("Total Deflection / Number of Plies > 0.09 * h_ri - Due to Long term Creep")

        # Excel Check '8' (AASHTO 14.7.6.3.4)
        self.delta_t = self.exp_coeff * self.expansion_length * (self.temp_range[1] - self.temp_range[0]) * 12
        self.delta_s = self.delta_t
        if 2 * self.delta_s <= self.total_elastomer_thickness:
            self.checks['#8 - Thermal Expansion'] = 1
        else:
            self.checks['#8 - Thermal Expansion'] = 0
            print("Thermal expansion check failed, 2 * delta_s > h_ri")

        # Excel Check '9' (BDM 306.4)
        if self.total_elastomer_thickness < 5:
            self.checks['#9 - Maximum Elastomer height > 5\"'] = 1
        else:
            self.checks['#9 - Maximum Elastomer height > 5\"'] = 0
            print("Maximum Elastomer height check failed, total elastomer height > 5\"")

        # Excel Check '10' (BDM 306.4)
        if self.total_laminate_thickness < 1:
            self.checks['#10 - Maximum laminate height < 1\"'] = 1
        else:
            self.checks['#10 - Maximum laminate height < 1\"'] = 0
            print("Maximum laminate height check failed, total laminate height > 1\"")

        # Excel Check '11' (AASHTO 14.7.6.3.6)
        if self.width / 3 > self.total_laminate_thickness:
            self.checks['#11 - Laminate Width / 3 > Total Laminate Thickness'] = 1
        else:
            self.checks['#11 - Laminate Width / 3 > Total Laminate Thickness'] = 0
            print("Geometry Check Failed, Laminate Width / 3 > Total Laminate Thickness")

        # Excel Check '12' (AASHTO 14.7.6.3.6)
        if self.length / 3 > self.total_laminate_thickness:
            self.checks['#12 - Bearing Length / 3 > Total Laminate Thickness'] = 1
        else:
            self.checks['#12 - Bearing Length / 3 > Total Laminate Thickness'] = 0
            print("Geometry Check Failed, Bearing Length / 3 > Total Laminate Thickness")

        # Excel Check '13'
        if self.length * self.width < 1000:
            self.checks['#13 - Bearing Area < 1000'] = 1
        else:
            self.checks['#13 - Bearing Area < 1000'] = 0
            print("Geometry Check Failed, Bearing Length / 3 > Total Laminate Thickness")

        # Excel Check '14'
        if self.total_elastomer_thickness < 8:
            self.checks['#14 - Total elastomer thickness < 8\"'] = 1
        else:
            self.checks['#14 - Total elastomer thickness < 8\"'] = 0
            print("Geometry Check Failed, Bearing Length / 3 > Total Laminate Thickness")

        # Excel Check '15'
        H = self.shear_modulus * self.length * self.width * self.delta_t / self.total_elastomer_thickness
        if H < self.loads['total_dead_load']:
            self.checks['#15 - Total Dead Load'] = 1
        else:
            self.checks['#15 - Total Dead Load'] = 0
            print('Anchorage Check Failed, H < Total Dead Load, Anchorage is required')

        # Excel Check '16'
        if self.steel_t >= 3 * self.internal_t * self.sigma_s / self.f_y:
            self.checks['#16 - Steel Reinforcement - Service Limit State'] = 1
        else:
            self.checks['#16 - Steel Reinforcement - Service Limit State'] = 0
            print('Steel laminate service limit state check failed')

        # Excel Check 17
        if self.steel_t >= 2 * self.internal_t * self.sigma_l / 24:
            self.checks['#17 - Steel Reinforcement - Service Limit State'] = 1
        else:
            self.checks['#17 - Steel Reinforcement - Service Limit State'] = 0
            print('Steel laminate fatigue limit state check failed')

        # Excel Check 18
        gamma_a_st = 1.4 * self.sigma_s / (self.shear_modulus * 8)
        gamma_a_cy = 1.4 * self.sigma_l / (self.shear_modulus * 8)
        # static rotation: analysis value + the 0.005 rad allowance of
        # 14.4.2.1, or the legacy proxy (dead-load deflection / span + grade)
        theta_st = (abs(self.rotation_st) + 0.005 if self.rotation_st is not None
                    else abs(self.dl_deflection / (self.span * 12) + self.deck_slope) + 0.005)
        gamma_r_st = 0.5 * (self.length / self.internal_t) ** 2 * theta_st / self.plys
        # AASHTO 14.7.6.3.5: γ_r,cy = 0.5*(L/t_ri)² * θ_L/n
        # θ_L estimated as LL_deflection / ll_location (distance to max LL point, ft→in)
        # Note: AASHTO recommends using the bearing rotation from structural analysis;
        # this approximation may under-predict end rotation for mid-span loading.
        theta_cy = (abs(self.rotation_cy) if self.rotation_cy is not None
                    else abs(self.ll_deflection / (self.ll_location * 12)))
        gamma_r_cy = 0.5 * (self.length / self.internal_t) ** 2 * theta_cy / self.plys
        gamma_s_st = self.delta_s / self.total_elastomer_thickness
        # γ_s,cy = Δ_cy / h_ri (AASHTO 14.7.6.3.5). For non-sliding (fixed) bearings
        # with no cyclic horizontal deformation, γ_s,cy = 0 is correct per AASHTO.
        # Override this value if cyclic shear deformation is present.
        gamma_s_cy = 0

        total_strains = (
                (gamma_a_st + gamma_r_st + gamma_s_st) + 1.75 * (
                    gamma_a_cy + gamma_r_cy + gamma_s_cy
                )
            )

        if total_strains < 5.0:
            self.checks['#18 - Total Strain'] = 1
        else:
            self.checks['#18 - Total Strain'] = 0
            print('Combined Strain Check Failed')

        # Excel Check 19
        # with the sole plate bevelled the grade drops out of the static rotation
        theta_st2 = (abs(self.rotation_st) + 0.005 if self.rotation_st is not None
                     else abs(self.dl_deflection / (self.span * 12) + (self.deck_slope - self.plate_bev)) + 0.005)
        gamma_r_st = 0.5 * (self.length / self.internal_t) ** 2 * theta_st2 / self.plys

        total_strains = (
                (gamma_a_st + gamma_r_st + gamma_s_st) + 1.75 * (
                gamma_a_cy + gamma_r_cy + gamma_s_cy
        )
        )
        if total_strains < 5.0:
            self.checks['#19 - Total Strain Check 2'] = 1
        else:
            self.checks['#19 - Total Strain Check 2'] = 0
            print('Combined Strain Check 2 Failed')

    def check_edge_cover(self):
        """Verify steel laminate edge cover meets the 1/4-inch minimum.

        Per AASHTO 14.7.6.1, edge cover must be at least 0.25 inches.
        Updates ``self.checks['Steel Laminate Edge Cover Check']`` with
        ``1`` (pass) or ``0`` (fail).
        """
        if self.edge_cover < .25:
            self.checks['Steel Laminate Edge Cover Check'] = 0
            print("Steel Laminate Edge Cover > 1/4\" - Failed")
        else:
            self.checks['Steel Laminate Edge Cover Check'] = 1

    def check_layer_thickness(self):
        """Verify external elastomer layer thickness constraints.

        Per AASHTO 14.7.6.1, the external layer must not exceed 5/16 inch
        and must not exceed 70 % of the internal layer thickness. Updates
        ``self.checks`` with ``1`` (pass) or ``0`` (fail) for each sub-check.
        """
        if self.external_t > 5/16:
            self.checks['External Thickness Check > 5/16\"'] = 0
            print("External Thickness Check Failed > 5/16\"")
        elif self.external_t > .7 * self.internal_t:
            self.checks['External Thickness > 70% Internal'] = 0
            print("External Thickness Check Failed - > 70% of Internal Thickness")
        else:
            self.checks['External Thickness Check > 5/16\"'] = 1
            self.checks['External Thickness > 70% Internal'] = 1

    def get_deflections(self):
        """Calculate service compressive stress values from applied loads.

        Divides live and total dead loads by the bearing plan area to obtain
        bearing pressures, stored as ``self.sigma_l`` (live load stress, ksi)
        and ``self.sigma_s`` (dead load stress, ksi).
        """
        self.sigma_l = self.loads['live'] / (self.width * self.length)
        self.sigma_s = self.loads['total_dead_load'] / (self.width * self.length)


def get_bearing_strain(stress, shape_factor, hardness):
    if hardness == 50:
        return stress / (4.8 * .1125 * shape_factor ** 2)
    elif hardness == 60:
        return stress / (4.8 * .1125 * shape_factor ** 2)
    elif hardness == 70:
        return stress / (4.8 * .1125 * shape_factor ** 2)
    else:
        return "Error: Hardness not supported, please use 50, 60, or 70"

rubber_creep_values = {
    50: .25,
    60: .35,
    70: .45
}
