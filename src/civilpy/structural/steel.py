#  CivilPy

#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""AISC steel-shape database lookup and section classes.

Loads the AISC shapes database (current and historic editions, bundled as
CSV under ``structural/res``) and exposes ``SteelSection``-style classes
whose attributes are Pint quantities (``SteelSection("W36X150").I_x``,
``.S_x``, ``.weight``, …), plus bolt-weight reference data for detailing.
"""

import difflib

import numpy as np
import pandas as pd
from sympy.combinatorics.fp_groups import define_schreier_generators

from civilpy.general import units
from civilpy.structural.res.definitions import A325_bolt_weights

import os
import sys
script_dir = os.path.dirname(os.path.abspath(__file__))
csv_filepath = os.path.join(script_dir, "res", "steel_shapes.csv")
historic_csv_filepath = os.path.join(script_dir, "res", "aisc_shapes_historic.csv")

steel_tables = pd.read_csv(csv_filepath)
# A few cells are a lone space (P 1.25 rx/ry); read them as missing so the column stays numeric
historic_steel_tables = pd.read_csv(historic_csv_filepath, low_memory=False, na_values=[" "])
historic_shapes = historic_steel_tables[historic_steel_tables['Edition']=='Historic']

def conv_frac_str(fraction_string: str) -> float:
    try:
        return float(fraction_string)
    except ValueError:
        num, denominator = fraction_string.split("/")
        try:
            leading, num = num.split()
            whole = float(leading)
        except ValueError:
            whole = 0
        frac = float(num) / float(denominator)
        return whole - frac if whole < 0 else whole + frac


def _not_found(label, names, kind):
    """Message for a label missing from a shape table, with the closest names."""
    close = difflib.get_close_matches(label.upper(), names.dropna().str.upper().unique(), n=5)
    hint = f"; did you mean {', '.join(close)}?" if close else ""
    return f"{kind} {label!r} not found{hint}"


class SteelSection:
    """
    Main Steel Section Class, the goal is to make the attributes of various
    steel sections easily accessible in various python scripts.
    """

    def __init__(self, label):
        """
        Initialize a SteelSection from an AISC shape label.

        Looks up the label in the AISC Steel Construction Manual shape table and
        populates standard section properties with Pint units attached.

        Args:
            label (str): AISC standard nomenclature, e.g. ``"W36X150"``, ``"w40x294"``,
                ``"2L8X4X5/8LLBB"``. Case and spaces are normalized automatically.

        Raises:
            KeyError: If the label is in neither the EDI name nor the AISC
                manual label column of the shape database.

        Example:
            >>> s = SteelSection("W36X150")
            >>> float(s.I_x.magnitude)
            9040.0
        """
        self.id = self.clean_user_input(label)
        self.aisc_value = self.get_shape()

        self.special_note = self.aisc_value["T_F"].values[0]
        self.weight = self.W = self.aisc_value["W"].values[0] * units("lbf/ft")
        self.area = self.A = self.aisc_value["A"].values[0] * units("in^2")
        self.I_x = self.aisc_value["Ix"].values[0] * units("in^4")
        self.Z_x = self.aisc_value["Zx"].values[0] * units("in^3")
        self.S_x = self.aisc_value["Sx"].values[0] * units("in^3")
        self.r_x = self.aisc_value["rx"].values[0] * units("in")
        self.I_y = self.aisc_value["Iy"].values[0] * units("in^4")
        self.Z_y = self.aisc_value["Zy"].values[0] * units("in^3")
        self.S_y = self.aisc_value["Sy"].values[0] * units("in^3")
        self.r_y = self.aisc_value["ry"].values[0] * units("in")

    def clean_user_input(self, user_input):
        """
        Eliminates value not found errors by removing lower case letters and
        spaces

        >>> t = SteelSection("W 44X335")
        >>> print(t.clean_user_input('W 44X335'))
        W44X335
        >>> print(t.clean_user_input('w40x294'))
        W40X294
        >>> t.id
        'W40X294'

        :return: cleaned input
        """

        if user_input[0:4].lower() == "pipe":
            no_spaces = user_input.replace(" ", "")
            cleaned_input = no_spaces
            self.id = cleaned_input
        else:
            no_spaces = user_input.replace(" ", "")
            cleaned_input = no_spaces.upper()
            self.id = cleaned_input

        return cleaned_input

    def get_shape(self):
        """
        Searches AISC Steel database table for member label passed to it,
        returns values from table if it finds a match, or prints an error if it
        doesn't

        >>> t = SteelSection("W36X150")
        >>> t.aisc_value['Type'].values[0]
        'W'

        >>> t = SteelSection("2L8X4X5/8LLBB")
        >>> t.aisc_value['W'].values[0]
        48.4

        :param self:
        :return: dataframe of raw values from AISC Shape Table
        """
        label = self.id.upper()
        # EDI name first ("Pipe6SCH40", "HSS24X12X.750"), then the manual
        # label ("Pipe6STD", "HSS24X12X3/4"); the two never collide
        for column in ("EDI_Std_Nomenclature", "AISC_Manual_Label"):
            shape_values = steel_tables[steel_tables[column].str.upper() == label]
            if len(shape_values):
                return shape_values
        raise KeyError(_not_found(self.id, steel_tables["AISC_Manual_Label"], "AISC shape"))


class W(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel W s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = W("W36X150")
    >>> t.weight
    150.0 pound/foot
    """

    def __init__(self, label):
        super(W, self).__init__(label)
        self.depth = conv_frac_str(self.aisc_value["d"].values[0]) * units("in")
        self.detailing_depth = conv_frac_str(self.aisc_value["ddet"].values[0]) * units(
            "in"
        )
        self.flange_width = conv_frac_str(self.aisc_value["bf"].values[0]) * units("in")
        self.detailing_flange_width = conv_frac_str(
            self.aisc_value["bfdet"].values[0]
        ) * units("in")
        self.web_thickness = conv_frac_str(self.aisc_value["tw"].values[0]) * units(
            "in"
        )
        self.detailing_web_thickness = conv_frac_str(
            self.aisc_value["twdet"].values[0]
        ) * units("in")
        self.half_web_detail = conv_frac_str(
            self.aisc_value["twdet/2"].values[0]
        ) * units("in")
        self.flange_thickness = conv_frac_str(self.aisc_value["tf"].values[0]) * units(
            "in"
        )
        self.detailing_flange_thickness = conv_frac_str(
            self.aisc_value["tfdet"].values[0]
        ) * units("in")
        self.k_design = conv_frac_str(self.aisc_value["kdes"].values[0]) * units("in")
        self.k_detailing = conv_frac_str(self.aisc_value["kdet"].values[0]) * units(
            "in"
        )
        self.slenderness_ratio_web = conv_frac_str(self.aisc_value["h/tw"].values[0])
        self.J = conv_frac_str(self.aisc_value["J"].values[0]) * units("in^4")
        self.Cw = conv_frac_str(self.aisc_value["Cw"].values[0]) * units("in^6")
        self.Wno = conv_frac_str(self.aisc_value["Wno"].values[0]) * units("in^2")
        self.Sw1 = conv_frac_str(self.aisc_value["Sw1"].values[0]) * units("in^4")
        self.Qf = conv_frac_str(self.aisc_value["Qf"].values[0]) * units("in^3")
        self.Qw = conv_frac_str(self.aisc_value["Qw"].values[0]) * units("in^3")
        self.radius_of_gyration = self.rts = conv_frac_str(
            self.aisc_value["rts"].values[0]
        ) * units("in")
        self.flange_centroid_distance = conv_frac_str(
            self.aisc_value["ho"].values[0]
        ) * units("in")
        self.exposed_perimeter = conv_frac_str(self.aisc_value["PA"].values[0]) * units(
            "in"
        )
        self.shape_perimeter = conv_frac_str(self.aisc_value["PB"].values[0]) * units(
            "in"
        )
        self.box_perimeter = conv_frac_str(self.aisc_value["PC"].values[0]) * units(
            "in"
        )
        self.exposed_box_perimeter = conv_frac_str(
            self.aisc_value["PD"].values[0]
        ) * units("in")
        self.web_face_depth = self.T = conv_frac_str(
            self.aisc_value["T"].values[0]
        ) * units("in")

        # These values are used in most shapes, but not all, hence the ifs
        self.slenderness_ratio_flange = conv_frac_str(
            self.aisc_value["bf/2tf"].values[0]
        )
        self.k1 = conv_frac_str(self.aisc_value["k1"].values[0]) * units("in")

        self.fastener_workable_gage = conv_frac_str(
            self.aisc_value["WGi"].values[0]
        ) * units("in")


class M(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel M s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = M("M10X9")
    >>> t.weight
    9.0 pound/foot
    """

    def __init__(self, label):
        super(M, self).__init__(label)


class S(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel M s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = S("S24X121")
    >>> t.weight
    121.0 pound/foot
    """

    def __init__(self, label):
        super(S, self).__init__(label)


class HP(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel M s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = HP("HP18X204")
    >>> t.weight
    204.0 pound/foot
    """

    def __init__(self, label):
        super(HP, self).__init__(label)
        self.depth = conv_frac_str(self.aisc_value["d"].values[0]) * units("in")
        self.detailing_depth = conv_frac_str(self.aisc_value["ddet"].values[0]) * units(
            "in"
        )
        self.flange_width = conv_frac_str(self.aisc_value["bf"].values[0]) * units("in")
        self.detailing_flange_width = conv_frac_str(
            self.aisc_value["bfdet"].values[0]
        ) * units("in")
        self.web_thickness = conv_frac_str(self.aisc_value["tw"].values[0]) * units(
            "in"
        )
        self.detailing_web_thickness = conv_frac_str(
            self.aisc_value["twdet"].values[0]
        ) * units("in")
        self.half_web_detail = conv_frac_str(
            self.aisc_value["twdet/2"].values[0]
        ) * units("in")
        self.flange_thickness = conv_frac_str(self.aisc_value["tf"].values[0]) * units(
            "in"
        )
        self.detailing_flange_thickness = conv_frac_str(
            self.aisc_value["tfdet"].values[0]
        ) * units("in")
        self.k_design = conv_frac_str(self.aisc_value["kdes"].values[0]) * units("in")
        self.k_detailing = conv_frac_str(self.aisc_value["kdet"].values[0]) * units(
            "in"
        )
        self.slenderness_ratio_web = conv_frac_str(self.aisc_value["h/tw"].values[0])
        self.J = conv_frac_str(self.aisc_value["J"].values[0]) * units("in^4")
        self.Cw = conv_frac_str(self.aisc_value["Cw"].values[0]) * units("in^6")
        self.Wno = conv_frac_str(self.aisc_value["Wno"].values[0]) * units("in^2")
        self.Sw1 = conv_frac_str(self.aisc_value["Sw1"].values[0]) * units("in^4")
        self.Qf = conv_frac_str(self.aisc_value["Qf"].values[0]) * units("in^3")
        self.Qw = conv_frac_str(self.aisc_value["Qw"].values[0]) * units("in^3")
        self.radius_of_gyration = self.rts = conv_frac_str(
            self.aisc_value["rts"].values[0]
        ) * units("in")
        self.flange_centroid_distance = conv_frac_str(
            self.aisc_value["ho"].values[0]
        ) * units("in")
        self.exposed_perimeter = conv_frac_str(self.aisc_value["PA"].values[0]) * units(
            "in"
        )
        self.shape_perimeter = conv_frac_str(self.aisc_value["PB"].values[0]) * units(
            "in"
        )
        self.box_perimeter = conv_frac_str(self.aisc_value["PC"].values[0]) * units(
            "in"
        )
        self.exposed_box_perimeter = conv_frac_str(
            self.aisc_value["PD"].values[0]
        ) * units("in")
        self.web_face_depth = self.T = conv_frac_str(
            self.aisc_value["T"].values[0]
        ) * units("in")

        # These values are used in most shapes, but not all, hence the ifs
        self.slenderness_ratio_flange = conv_frac_str(
            self.aisc_value["bf/2tf"].values[0]
        )
        self.k1 = conv_frac_str(self.aisc_value["k1"].values[0]) * units("in")

        self.fastener_workable_gage = conv_frac_str(
            self.aisc_value["WGi"].values[0]
        ) * units("in")

class C(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel C s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = C("C15X50")
    >>> t.weight
    50.0 pound/foot
    """

    def __init__(self, label):
        super(C, self).__init__(label)
        self.x = conv_frac_str(self.aisc_value["x"].values[0]) * units("in")
        self.eo = conv_frac_str(self.aisc_value["twdet"].values[0]) * units("in")
        self.xp = conv_frac_str(self.aisc_value["xp"].values[0]) * units("in")
        self.slenderness_ratio = conv_frac_str(self.aisc_value["b/t"].values[0])
        self.warping_moment_2 = conv_frac_str(self.aisc_value["Sw2"].values[0]) * units(
            "in^4"
        )
        self.warping_moment_3 = conv_frac_str(self.aisc_value["Sw3"].values[0]) * units(
            "in^4"
        )
        self.ro = conv_frac_str(self.aisc_value["ro"].values[0]) * units("in")
        self.H = conv_frac_str(self.aisc_value["H"].values[0])


class MC(C):
    """
    Class to provide more specific attributes and functions related to designing
    with steel MC s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = MC("MC18X58")
    >>> t.weight
    58.0 pound/foot
    """

    def __init__(self, label):
        super(MC, self).__init__(label)


class L(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel L s. Splitting values into multiple classes allows dropping
    of empty vain the database.

    >>> t = L("L12x12x1-3/8")
    >>> t.weight
    105.0 pound/foot
    """

    def __init__(self, label):
        super(L, self).__init__(label)
        self.b = conv_frac_str(self.aisc_value["b"].values[0]) * units("in")
        self.t = conv_frac_str(self.aisc_value["t"].values[0]) * units("in")
        self.y = conv_frac_str(self.aisc_value["y"].values[0]) * units("in")
        self.yp = conv_frac_str(self.aisc_value["yp"].values[0])
        self.Iz = conv_frac_str(self.aisc_value["Iz"].values[0]) * units("in^4")
        self.rz = conv_frac_str(self.aisc_value["rz"].values[0]) * units("in")
        self.Sz = conv_frac_str(self.aisc_value["Sz"].values[0]) * units("in^3")
        self.tan_a = conv_frac_str(self.aisc_value["tan(α)"].values[0])
        self.Iw = conv_frac_str(self.aisc_value["Iw"].values[0]) * units("in^4")
        self.zA = conv_frac_str(self.aisc_value["zA"].values[0]) * units("in")
        self.zB = conv_frac_str(self.aisc_value["zB"].values[0]) * units("in")
        self.zC = conv_frac_str(self.aisc_value["zC"].values[0]) * units("in")
        self.wA = conv_frac_str(self.aisc_value["wA"].values[0]) * units("in")
        self.wB = conv_frac_str(self.aisc_value["wB"].values[0]) * units("in")
        self.wC = conv_frac_str(self.aisc_value["wC"].values[0]) * units("in")
        self.SwA = conv_frac_str(self.aisc_value["SwA"].values[0]) * units("in^3")
        self.SwC = conv_frac_str(self.aisc_value["SwC"].values[0]) * units("in^3")
        self.SzA = conv_frac_str(self.aisc_value["SzA"].values[0]) * units("in^3")
        self.SzB = conv_frac_str(self.aisc_value["SzB"].values[0]) * units("in^3")
        self.SzC = conv_frac_str(self.aisc_value["SzC"].values[0]) * units("in^3")
        self.PA2 = conv_frac_str(self.aisc_value["PA2"].values[0]) * units("in")


class WT(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel WT s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = WT("WT22x145")
    >>> t.weight
    145.0 pound/foot
    """

    def __init__(self, label):
        super(WT, self).__init__(label)
        self.d_t = conv_frac_str(self.aisc_value["D/t"].values[0])
        self.ro = conv_frac_str(self.aisc_value["ro"].values[0]) * units("in")
        self.y = conv_frac_str(self.aisc_value["y"].values[0]) * units("in")
        self.yp = conv_frac_str(self.aisc_value["yp"].values[0])
        self.H = conv_frac_str(self.aisc_value["H"].values[0])


class MT(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel WT s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = MT("MT5x4")
    >>> t.weight
    4.0 pound/foot
    """

    def __init__(self, label):
        super(MT, self).__init__(label)


class ST(WT):
    """
    Class to provide more specific attributes and functions related to designing
    with steel ST s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = ST("ST10x48")
    >>> t.weight
    48.0 pound/foot
    """

    def __init__(self, label):
        super(ST, self).__init__(label)


class TwoL(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel 2L s. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = TwoL("2L10X10X1-1/4")
    >>> t.weight
    48.0 pound/foot
    """

    def __init__(self, label):
        super(TwoL, self).__init__(label)
        self.b = conv_frac_str(self.aisc_value["b"].values[0]) * units("in")
        self.t = conv_frac_str(self.aisc_value["t"].values[0]) * units("in")
        self.slenderness_ratio = conv_frac_str(self.aisc_value["b/t"].values[0])


class HSS(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel HSS sections. Splitting values into multiple classes allows dropping
    of empty values in the database.

    >>> t = HSS("HSS20X20X.500")
    >>> t.weight
    130.52 pound/foot
    """

    def __init__(self, label):
        super(HSS, self).__init__(label)
        self.tnom = conv_frac_str(self.aisc_value["tnom"].values[0]) * units("in")
        self.tdes = conv_frac_str(self.aisc_value["tdes"].values[0]) * units("in")
        self.C = conv_frac_str(self.aisc_value["C"].values[0]) * units("in^3")
        if self.aisc_value["OD"].values[0] == "–":
            self.OD = None
        else:  # pragma: no cover
            self.OD = conv_frac_str(self.aisc_value["OD"].values[0]) * units("in")
        if self.aisc_value["ID"].values[0] == "–":
            self.ID = None
        else:  # pragma: no cover
            self.ID = conv_frac_str(self.aisc_value["ID"].values[0]) * units("in")


class Pipe(SteelSection):
    """
    Class to provide more specific attributes and functions related to designing
    with steel Pipe Sections. Splitting values into multiple classes allows
    dropping of empty values in the database.

    >>> t = Pipe("Pipe10SCH140")
    >>> t.weight
    104.0 pound/foot
    """

    def __init__(self, label):
        super(Pipe, self).__init__(label)
        self.OD = conv_frac_str(self.aisc_value["OD"].values[0]) * units("in")
        self.ID = conv_frac_str(self.aisc_value["ID"].values[0]) * units("in")
        self.D_t = conv_frac_str(self.aisc_value["D/t"].values[0])


def get_bolt_weights(length: float, diameter: float, no_of_washers: int) -> float:
    """
    Function to get the bolt weights from the A325_bolt_weights dictionary and calculate the weight per bolt if it's
    not contained in the table.

    Original table from:
    https://www.portlandbolt.com/print/?table=7587

    The A325_bolt_weights dictionary reports the weight indexed by bolt length and diameter, and reports the value in
    lbs/100 bolts. This function simplifies that by reducing the value to that of a single bolt.

    If bolt weights are not contained in the dictionary, the function will utilize the following formula to calculate
    the weight per bolt, if no_of_washers is greater than 0, it will include the weight of the washers in the
    calculation with the following values:

    Per inch Adder (dia):
        0.5: 5.5
        0.625: 8.6
        0.75: 12.4
        0.875: 16.9
        1.0: 22.1
        1.125: 28
        1.25: 34.4
        1.375: 42.5
        1.5: 49.7

    F436 Round Washers
        0.5: 2.1
        0.625: 3.6
        0.75: 4.8
        0.875: 7
        1.0: 9.4
        1.125: 11.3
        1.25: 13.8
        1.375: 16.8
        1.5: 20

    Weight in table includes the weight of nuts.

    Parameters
    -------
    length : float
    diameter : float
    no_of_washers : int

    Returns
    -------
    Weight : float - the weight of the individual bolt
    """

    # Test if the inputs are in the table or if the formula must be used to calculate weight
    if length in A325_bolt_weights.keys() and diameter in A325_bolt_weights[9].keys():
        total_weight = A325_bolt_weights[length][diameter]

    # Make sure user input is one of the available diameters
    elif (
        diameter not in A325_bolt_weights[9].keys()
        or length not in A325_bolt_weights.keys()
    ):
        print(
            "\nNon-existant diameter or length used, please use a value from the following list:"
        )
        print(
            "\n\t0.5\n\t0.625\n\t0.75\n\t0.875\n\t1.0\n\t1.125\n\t1.25\n\t1.375\n\t1.5\n\n"
        )

        return None

    # Calculates the weight of bolts longer than 9", uses 6" bolt to have all dias
    elif diameter in A325_bolt_weights[9].keys() and length > max(  # pragma: no cover
        A325_bolt_weights.keys()
    ):  # pragma: no cover
        length_adder = {
            0.5: 5.5,
            0.625: 8.6,
            0.75: 12.4,
            0.875: 16.9,
            1.0: 22.1,
            1.125: 28,
            1.25: 34.4,
            1.375: 42.5,
            1.5: 49.7,
        }

        added_length = length - 6
        total_weight = (
            A325_bolt_weights[6][diameter] + added_length * length_adder[diameter]
        )

    # Adds washer weight if no of washers > 0
    for washer in range(0, no_of_washers, 1):
        washer_weight = {
            0.5: 2.1,
            0.625: 3.6,
            0.75: 4.8,
            0.875: 7,
            1.0: 9.4,
            1.125: 11.3,
            1.25: 13.8,
            1.375: 16.8,
            1.5: 20,
        }

        total_weight = total_weight + washer_weight[diameter]

    return round((total_weight / 100), 3) * units.lbs


class HistoricSteelSection:
    """
    Main Steel Section Class, the goal is to make the attributes of various
    steel sections easily accessible in various python scripts.
    """

    def __init__(self, label, designation=None):
        """
        Initialize a historic steel section from the AISC historic shapes database.

        Args:
            label (str): Shape label as the historic table's ``Name`` column
                spells it, e.g. ``"18WF96"`` or ``"36WF150"``. Case and spaces
                are normalized automatically.
            designation (str, optional): AISC historic edition designation used to
                disambiguate shapes that were published under multiple editions.
                Example: ``'18WF_B18b'``. Required when the name appears under
                more than one designation.

        Raises:
            KeyError: The name is not in the historic table (the message lists
                close names), or it has no row with ``designation``.
            ValueError: The name is under several designations and none was given.
        """
        self.id = self.clean_user_input(label)
        self.aisc_value = self.get_historical_shape(designation)

        self.weight = self.W = float(self.aisc_value["W"].values[0]) * units("lbf/ft")
        self.area = self.A = self.aisc_value["A"].values[0] * units("in^2")
        self.I_x = self.aisc_value["Ix"].values[0] * units("in^4")
        self.Z_x = self.aisc_value["Zx"].values[0] * units("in^3")
        self.S_x = self.aisc_value["Sx"].values[0] * units("in^3")
        self.r_x = self.aisc_value["rx"].values[0] * units("in")
        self.I_y = self.aisc_value["Iy"].values[0] * units("in^4")
        self.Z_y = self.aisc_value["Zy"].values[0] * units("in^3")
        self.S_y = self.aisc_value["Sy"].values[0] * units("in^3")
        self.r_y = self.aisc_value["ry"].values[0] * units("in")

    def clean_user_input(self, user_input):
        """
        Eliminates value not found errors by removing lower case letters and
        spaces

        >>> t = SteelSection("W 44X335")
        >>> print(t.clean_user_input('W 44X335'))
        W44X335
        >>> print(t.clean_user_input('w40x294'))
        W40X294
        >>> t.id
        'W40X294'

        :return: cleaned input
        """

        if user_input[0:4].lower() == "pipe":  # pragma: no cover
            no_spaces = user_input.replace(" ", "")
            cleaned_input = no_spaces
            self.id = cleaned_input
        else:
            no_spaces = user_input.replace(" ", "")
            cleaned_input = no_spaces.upper()
            self.id = cleaned_input

        return cleaned_input

    def get_historical_shape(self, designation=None):
        """
        Searches AISC Steel database table for member label passed to it,
        returns values from table if it finds a match, or prints an error if it
        doesn't

        >>> t = SteelSection("W36X150")
        >>> t.aisc_value['Type'].values[0]
        'W'

        >>> t = SteelSection("2L8X4X5/8LLBB")
        >>> t.aisc_value['W'].values[0]
        48.4

        :param self:
        :return: dataframe of raw values from AISC Shape Table
        """
        shape_values = historic_steel_tables[historic_steel_tables["Name"] == self.id]
        if shape_values.empty:
            raise KeyError(_not_found(self.id, historic_steel_tables["Name"], "historic shape"))
        designations = shape_values["Designation"].tolist()
        if designation:
            shape_values = shape_values[shape_values["Designation"] == designation]
            if shape_values.empty:
                raise KeyError(f"{self.id} has no designation {designation!r}; "
                               f"choose one of {designations}")
        elif len(shape_values) > 1:
            raise ValueError(f"{self.id} is listed under several designations {designations}; "
                             f"pass designation= to pick one")
        return shape_values


class WF(HistoricSteelSection):
    """
    Historic wide-flange section (pre-AISC W-shape standardization).

    Used for evaluating existing bridges and structures built with pre-1970 steel
    sections. Extends :class:`HistoricSteelSection` with dimensional attributes
    (depth, flange width, web thickness, etc.) from the AISC historic shapes table.

    Example:
        >>> t = WF("18WF96", '18WF_B18b')
        >>> t.weight
        96.0 force_pound/foot
    """

    def __init__(self, label, designation=None):
        """
        Initialize a historic WF section with full dimensional properties.

        Args:
            label (str): Historic shape label, e.g. ``"18WF96"``.
            designation (str, optional): AISC edition designation to disambiguate
                shapes with the same label across multiple editions.
                Example: ``'18WF_B18b'``.
        """
        super(WF, self).__init__(label, designation)
        self.depth = conv_frac_str(self.aisc_value["d"].values[0]) * units("in")
        self.detailing_depth = conv_frac_str(self.aisc_value["ddet"].values[0]) * units(
            "in"
        )
        self.flange_width = conv_frac_str(self.aisc_value["bf"].values[0]) * units("in")
        self.detailing_flange_width = conv_frac_str(
            self.aisc_value["bfdet"].values[0]
        ) * units("in")
        self.web_thickness = conv_frac_str(self.aisc_value["tw"].values[0]) * units(
            "in"
        )
        self.detailing_web_thickness = conv_frac_str(
            self.aisc_value["twdet"].values[0]
        ) * units("in")
       # self.half_web_detail = conv_frac_str(
       #     self.aisc_value["twdet/2"].values[0]
       # ) * units("in")
        self.flange_thickness = conv_frac_str(self.aisc_value["tf"].values[0]) * units(
            "in"
        )
        self.detailing_flange_thickness = conv_frac_str(
            self.aisc_value["tfdet"].values[0]
        ) * units("in")
        self.k_design = conv_frac_str(self.aisc_value["kdes"].values[0]) * units("in")
        self.k_detailing = conv_frac_str(self.aisc_value["kdet"].values[0]) * units(
            "in"
        )
        self.slenderness_ratio_web = conv_frac_str(self.aisc_value["h/tw"].values[0])
        self.J = conv_frac_str(self.aisc_value["J"].values[0]) * units("in^4")
        self.Cw = conv_frac_str(self.aisc_value["Cw"].values[0]) * units("in^6")
        self.Wno = conv_frac_str(self.aisc_value["Wno"].values[0]) * units("in^2")
        # self.Sw1 = conv_frac_str(self.aisc_value["Sw1"].values[0]) * units("in^4")
        self.Qf = conv_frac_str(self.aisc_value["Qf"].values[0]) * units("in^3")
        self.Qw = conv_frac_str(self.aisc_value["Qw"].values[0]) * units("in^3")
        # self.radius_of_gyration = self.rts = conv_frac_str(
        #     self.aisc_value["rts"].values[0]
        # ) * units("in")
        # self.flange_centroid_distance = conv_frac_str(
        #     self.aisc_value["ho"].values[0]
        # ) * units("in")
        # self.exposed_perimeter = conv_frac_str(self.aisc_value["PA"].values[0]) * units(
        #     "in"
        # )
        # self.shape_perimeter = conv_frac_str(self.aisc_value["PB"].values[0]) * units(
        #     "in"
        # )
        # self.box_perimeter = conv_frac_str(self.aisc_value["PC"].values[0]) * units(
        #     "in"
        # )
        # self.exposed_box_perimeter = conv_frac_str(
        #     self.aisc_value["PD"].values[0]
        # ) * units("in")
        self.web_face_depth = self.T = conv_frac_str(
            self.aisc_value["T"].values[0]
        ) * units("in")

        # These values are used in most shapes, but not all, hence the ifs
        self.slenderness_ratio_flange = conv_frac_str(
            self.aisc_value["bf/2tf"].values[0]
        )
        self.k1 = conv_frac_str(self.aisc_value["k1"].values[0]) * units("in")

        # self.fastener_workable_gage = conv_frac_str(
        #     self.aisc_value["WGi"].values[0]
        # ) * units("in")


# ---------------------------------------------------------------------------
# Rebar
# ---------------------------------------------------------------------------

# ASTM A615 / A706 standard rebar properties
# Source: ASTM A615/A615M, Table 1 and Table 2
# Columns: nominal_diameter (in), area (in²), weight (lb/ft)
_REBAR_TABLE = {
    2:  (0.250, 0.05,  0.167),
    3:  (0.375, 0.11,  0.376),
    4:  (0.500, 0.20,  0.668),
    5:  (0.625, 0.31,  1.043),
    6:  (0.750, 0.44,  1.502),
    7:  (0.875, 0.60,  2.044),
    8:  (1.000, 0.79,  2.670),
    9:  (1.128, 1.00,  3.400),
    10: (1.270, 1.27,  4.303),
    11: (1.410, 1.56,  5.313),
    14: (1.693, 2.25,  7.650),
    18: (2.257, 4.00, 13.600),
}


class Rebar:
    """
    Standard deformed reinforcing bar per ASTM A615 / A706.

    Provides nominal diameter, cross-sectional area, and unit weight for
    standard US rebar sizes #2 through #18.  All dimensional properties
    carry Pint units.

    Args:
        bar_number (int): Standard bar designator (2, 3, 4, 5, 6, 7, 8, 9,
            10, 11, 14, or 18).
        grade (int): Yield strength grade in ksi.  Common values are
            40, 60, 75, or 80 per ASTM A615; 60 or 80 per ASTM A706.
            Defaults to ``60``.

    Raises:
        ValueError: If *bar_number* is not a standard ASTM size.

    Example:
        >>> bar = Rebar(5)
        >>> float(bar.area.magnitude)
        0.31
        >>> float(bar.weight.magnitude)
        1.043
        >>> bar.diameter
        0.625 inch

        >>> bar = Rebar(8, grade=60)
        >>> bar.bar_number
        8
    """

    def __init__(self, bar_number: int, grade: int = 60):
        if bar_number not in _REBAR_TABLE:
            raise ValueError(
                f"Bar #{bar_number} is not a standard ASTM rebar size. "
                f"Valid sizes: {sorted(_REBAR_TABLE)}"
            )
        self.bar_number = bar_number
        self.grade = grade
        diameter_in, area_in2, weight_plf = _REBAR_TABLE[bar_number]
        self.diameter = diameter_in * units("in")
        self.area = area_in2 * units("in^2")
        self.weight = weight_plf * units("lb/ft")
        self.f_y = grade * units("ksi")
        # ASTM A615 tensile strength: 90 ksi for Grade 60/75, 100 ksi for 80
        _tensile = {40: 60, 60: 90, 75: 100, 80: 100}
        self.f_u = _tensile.get(grade, 90) * units("ksi")

    def __repr__(self):
        return (
            f"<Rebar #{self.bar_number} Grade {self.grade} | "
            f"d={self.diameter} A={self.area} w={self.weight}>"
        )


# ---------------------------------------------------------------------------
# Steel Material Classes
# ---------------------------------------------------------------------------

class SteelMaterial:
    """
    Structural steel material specification.

    Stores yield strength, tensile strength, and modulus of elasticity for
    common ASTM structural steel grades.  Properties carry Pint units.

    Args:
        designation (str): ASTM material designation, e.g. ``'A36'``,
            ``'A572Gr50'``, ``'A992'``.
        f_y (float): Minimum yield strength, ksi.
        f_u (float): Minimum tensile strength, ksi.
        e_s (float): Modulus of elasticity, ksi.  Defaults to ``29000``.

    Example:
        >>> m = SteelMaterial('A36', f_y=36, f_u=58)
        >>> m.f_y
        36 kip/inch²
    """

    def __init__(self, designation: str, f_y: float, f_u: float,
                 e_s: float = 29000):
        self.designation = designation
        self.f_y = f_y * units("ksi")
        self.f_u = f_u * units("ksi")
        self.E = e_s * units("ksi")

    def __repr__(self):
        return (
            f"<SteelMaterial {self.designation} | "
            f"Fy={self.f_y} Fu={self.f_u}>"
        )


# Pre-built instances for the most common structural grades
# Sources: AISC Steel Construction Manual, Table 2-4
A36       = SteelMaterial("A36",        f_y=36,  f_u=58)
A572Gr50  = SteelMaterial("A572Gr50",   f_y=50,  f_u=65)
A572Gr60  = SteelMaterial("A572Gr60",   f_y=60,  f_u=75)
A572Gr65  = SteelMaterial("A572Gr65",   f_y=65,  f_u=80)
A992      = SteelMaterial("A992",        f_y=50,  f_u=65)   # W-shapes
A500GrB   = SteelMaterial("A500GrB",    f_y=46,  f_u=58)   # HSS rectangular
A500GrC   = SteelMaterial("A500GrC",    f_y=50,  f_u=62)   # HSS rectangular
A53GrB    = SteelMaterial("A53GrB",     f_y=35,  f_u=60)   # Pipe


class BoltMaterial:
    """
    Structural bolt material specification.

    Args:
        designation (str): ASTM bolt designation, e.g. ``'A325'``, ``'A490'``,
            ``'F3125GrA325'``.
        f_y (float): Proof load / yield strength, ksi.
        f_u (float): Minimum tensile strength, ksi.
        f_v (float): Nominal shear strength (ASD allowable or LRFD nominal),
            ksi.  Defaults to ``48`` (A325 threads excluded from shear plane).

    Example:
        >>> b = BoltMaterial('A325', f_y=92, f_u=120, f_v=48)
        >>> b.f_u
        120 kip/inch²
    """

    def __init__(self, designation: str, f_y: float, f_u: float,
                 f_v: float = 48):
        self.designation = designation
        self.f_y = f_y * units("ksi")
        self.f_u = f_u * units("ksi")
        self.f_v = f_v * units("ksi")

    def __repr__(self):
        return (
            f"<BoltMaterial {self.designation} | "
            f"Fu={self.f_u} Fv={self.f_v}>"
        )


# Pre-built instances for common structural bolt grades
# Source: AISC SCM Table J3.2 and ASTM specifications
A325 = BoltMaterial("A325",      f_y=92,  f_u=120, f_v=48)
A490 = BoltMaterial("A490",      f_y=130, f_u=150, f_v=60)
F3125_A325 = BoltMaterial("F3125GrA325", f_y=92,  f_u=120, f_v=48)
F3125_A490 = BoltMaterial("F3125GrA490", f_y=130, f_u=150, f_v=60)


if __name__ == "__main__":  # pragma: no cover
    import doctest

    doctest.testmod()
