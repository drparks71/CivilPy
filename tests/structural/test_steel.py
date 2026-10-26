#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

import pandas as pd
import unittest
from src.civilpy.structural.steel import SteelSection, conv_frac_str
from src.civilpy.structural.steel import W, M, S, HP, C, MC, L, WT, MT, ST
from src.civilpy.structural.steel import TwoL, HSS, Pipe
from src.civilpy.general import units

# //TODO - Need to update tests to be more like W Beam and verify each attribute for each type of member gets loaded


class TestGeneralFunctions(unittest.TestCase):
    def test_conv_frac_string(self):
        assert conv_frac_str("1") == 1.0
        assert conv_frac_str("3/2") == 1.5
        assert conv_frac_str("1 1/2") == 1.5
        assert conv_frac_str("-1 1/2") == -1.5
        assert conv_frac_str("26  3/8 ") == 26.375


class TestSteelSectionFunctions(unittest.TestCase):
    def test_general_import(self):
        test_beam = SteelSection("W44X335")  # Correct Name
        test_beam2 = SteelSection("W44x335")  # Lowercase correction
        test_beam3 = SteelSection("W 44x335")  # Space in label

        # Verify all three names are imported identically
        self.assertEqual(test_beam.weight, test_beam2.weight)
        self.assertEqual(test_beam2.weight, test_beam3.weight)

    def test_general_attributes(self):
        test_beam = SteelSection("W44X335")
        self.assertEqual(test_beam.weight, 335 * units("lbf/ft"))
        self.assertEqual(test_beam.area, 98.5 * units("in^2"))
        self.assertEqual(test_beam.special_note, "F")
        self.assertEqual(test_beam.I_x, 31100.0 * units("in^4"))
        self.assertEqual(test_beam.Z_x, 1620.0 * units("in^3"))
        self.assertEqual(test_beam.S_x, 1410.0 * units("in^3"))
        self.assertEqual(test_beam.r_x, 17.8 * units("in"))
        self.assertEqual(test_beam.I_y, 1200.0 * units("in^4"))
        self.assertEqual(test_beam.Z_y, 236.0 * units("in^3"))
        self.assertEqual(test_beam.S_y, 150.0 * units("in^3"))
        self.assertEqual(test_beam.r_y, 3.49 * units("in"))

    def test_WBeam_import(self):
        t = W("W36X150")
        self.assertEqual(t.depth, 35.9 * units.inch)
        self.assertEqual(t.detailing_depth, 35.875 * units.inch)
        self.assertEqual(t.flange_width, 12.0 * units.inch)
        self.assertEqual(t.detailing_flange_width, 12.0 * units.inch)
        self.assertEqual(t.web_thickness, 0.625 * units.inch)
        self.assertEqual(t.detailing_web_thickness, 0.625 * units.inch)
        self.assertEqual(t.half_web_detail, 0.3125 * units.inch)
        self.assertEqual(t.flange_thickness, 0.94 * units.inch)
        self.assertEqual(t.detailing_flange_thickness, 0.9375 * units.inch)
        self.assertEqual(t.k_design, 1.69 * units.inch)
        self.assertEqual(t.k_detailing, 2.1875 * units.inch)
        self.assertEqual(t.k1, 1.5 * units.inch)
        self.assertEqual(t.slenderness_ratio_flange, 6.37)
        self.assertEqual(t.slenderness_ratio_web, 51.9)
        self.assertEqual(t.J, 10.1 * units("in^4"))
        self.assertEqual(t.Cw, 82200.0 * units("in^6"))
        self.assertEqual(t.Wno, 105.0 * units("in^2"))
        self.assertEqual(t.Sw1, 294.0 * units("in^4"))
        self.assertEqual(t.Qf, 93.1 * units("in^3"))
        self.assertEqual(t.Qw, 287.0 * units("in^3"))
        self.assertEqual(t.radius_of_gyration, 3.06 * units("in"))
        self.assertEqual(t.flange_centroid_distance, 35.0 * units("in"))
        self.assertEqual(t.exposed_perimeter, 105.0 * units("in"))
        self.assertEqual(t.shape_perimeter, 117.0 * units("in"))
        self.assertEqual(t.box_perimeter, 83.8 * units("in"))
        self.assertEqual(t.exposed_box_perimeter, 95.8 * units("in"))
        self.assertEqual(t.web_face_depth, 31.5 * units("in"))
        self.assertEqual(t.fastener_workable_gage, 5.5 * units("in"))

    def test_M(self):
        t = M("M10X9")
        self.assertEqual(t.weight, 9.0 * units("lbf/ft"))

    def test_S(self):
        t = S("S24x121")
        self.assertEqual(t.weight, 121.0 * units("lbf/ft"))

    def test_HP(self):
        t = HP("HP18x204")
        self.assertEqual(t.weight, 204.0 * units("lbf/ft"))

    def test_C(self):
        t = C("C15x50")
        self.assertEqual(t.weight, 50.0 * units("lbf/ft"))

    def test_MC(self):
        t = MC("MC18x58")
        self.assertEqual(t.weight, 58.0 * units("lbf/ft"))

    def test_L(self):
        t = L("L12x12x1-3/8")
        self.assertEqual(t.weight, 105.0 * units("lbf/ft"))

    def test_WT(self):
        t = WT("WT22x145")
        self.assertEqual(t.weight, 145 * units("lbf/ft"))

    def test_MT(self):
        t = MT("MT5x4")
        self.assertEqual(t.weight, 4.0 * units("lbf/ft"))

    def test_ST(self):
        t = ST("ST10x48")
        self.assertEqual(t.weight, 48.0 * units("lbf/ft"))

    def test_TwoL(self):
        t = TwoL("2L10x10x1-1/4")
        self.assertEqual(t.weight, 160.0 * units("lbf/ft"))

    def test_HSS(self):
        t = HSS("HSS20x20x.500")
        self.assertEqual(t.weight, 130.52 * units("lbf/ft"))

    def test_pipe(self):
        t = Pipe("Pipe10SCH140")
        self.assertEqual(t.weight, 104.0 * units("lbf/ft"))

    def test_get_bolt_weights_in_table(self):
        from src.civilpy.structural.steel import get_bolt_weights
        result = get_bolt_weights(length=1.5, diameter=0.5, no_of_washers=0)
        self.assertIsNotNone(result)

    def test_get_bolt_weights_with_washers(self):
        from src.civilpy.structural.steel import get_bolt_weights
        result_no_washer = get_bolt_weights(length=1.5, diameter=0.5, no_of_washers=0)
        result_with_washer = get_bolt_weights(length=1.5, diameter=0.5, no_of_washers=1)
        self.assertGreater(result_with_washer, result_no_washer)

    def test_get_bolt_weights_invalid(self):
        from src.civilpy.structural.steel import get_bolt_weights
        result = get_bolt_weights(length=99.0, diameter=99.0, no_of_washers=0)
        self.assertIsNone(result)

    def test_historic_wf_section(self):
        from src.civilpy.structural.steel import WF
        t = WF("18WF96", '18WF_B18b')
        self.assertEqual(t.weight.magnitude, 96.0)

    def test_historic_wf_section_no_designation_multiple(self):
        # Covers line 698: multiple rows found → raises Exception
        from src.civilpy.structural.steel import HistoricSteelSection
        with self.assertRaises(Exception):
            HistoricSteelSection("18WF96")  # 2 rows exist → raises Exception at line 698

    def test_historic_wf_section_no_designation_single(self):
        # Covers line 700: single row found → returns shape_values
        from src.civilpy.structural.steel import HistoricSteelSection
        t = HistoricSteelSection("10WF12")  # Only 1 row → returns it
        assert t.weight.magnitude == 11.5


class TestRebar(unittest.TestCase):
    def test_rebar_no5_properties(self):
        from src.civilpy.structural.steel import Rebar
        bar = Rebar(5)
        self.assertEqual(bar.bar_number, 5)
        self.assertAlmostEqual(bar.diameter.magnitude, 0.625)
        self.assertAlmostEqual(bar.area.magnitude, 0.31)
        self.assertAlmostEqual(bar.weight.magnitude, 1.043)

    def test_rebar_default_grade_60(self):
        from src.civilpy.structural.steel import Rebar
        bar = Rebar(8)
        self.assertEqual(bar.grade, 60)
        self.assertEqual(bar.f_y.magnitude, 60)
        self.assertEqual(bar.f_u.magnitude, 90)

    def test_rebar_grade_40(self):
        from src.civilpy.structural.steel import Rebar
        bar = Rebar(4, grade=40)
        self.assertEqual(bar.grade, 40)
        self.assertEqual(bar.f_y.magnitude, 40)

    def test_rebar_invalid_size(self):
        from src.civilpy.structural.steel import Rebar
        with self.assertRaises(ValueError):
            Rebar(13)

    def test_rebar_all_standard_sizes(self):
        from src.civilpy.structural.steel import Rebar
        for size in [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 18]:
            bar = Rebar(size)
            self.assertGreater(bar.area.magnitude, 0)
            self.assertGreater(bar.weight.magnitude, 0)

    def test_rebar_repr(self):
        from src.civilpy.structural.steel import Rebar
        bar = Rebar(5)
        self.assertIn("#5", repr(bar))


class TestSteelMaterial(unittest.TestCase):
    def test_a36_properties(self):
        from src.civilpy.structural.steel import A36
        self.assertEqual(A36.f_y.magnitude, 36)
        self.assertEqual(A36.f_u.magnitude, 58)
        self.assertEqual(A36.E.magnitude, 29000)

    def test_a572gr50_properties(self):
        from src.civilpy.structural.steel import A572Gr50
        self.assertEqual(A572Gr50.f_y.magnitude, 50)
        self.assertEqual(A572Gr50.f_u.magnitude, 65)

    def test_a992_properties(self):
        from src.civilpy.structural.steel import A992
        self.assertEqual(A992.f_y.magnitude, 50)
        self.assertEqual(A992.f_u.magnitude, 65)

    def test_steel_material_repr(self):
        from src.civilpy.structural.steel import A36
        self.assertIn("A36", repr(A36))


class TestBoltMaterial(unittest.TestCase):
    def test_a325_properties(self):
        from src.civilpy.structural.steel import A325
        self.assertEqual(A325.f_y.magnitude, 92)
        self.assertEqual(A325.f_u.magnitude, 120)
        self.assertEqual(A325.f_v.magnitude, 48)

    def test_a490_properties(self):
        from src.civilpy.structural.steel import A490
        self.assertEqual(A490.f_u.magnitude, 150)
        self.assertEqual(A490.f_v.magnitude, 60)

    def test_bolt_material_repr(self):
        from src.civilpy.structural.steel import A325
        self.assertIn("A325", repr(A325))


import pytest
from src.civilpy.structural.steel import historic_steel_tables


@pytest.mark.parametrize("column", ["A", "Ix", "Zx", "Sx", "rx", "Iy", "Zy", "Sy", "ry"])
def test_historic_property_columns_are_numeric(column):
    # HistoricSteelSection multiplies these straight by units; a text column only
    # worked while pint (< 0.26) parsed numeric strings
    assert pd.api.types.is_numeric_dtype(historic_steel_tables[column])
