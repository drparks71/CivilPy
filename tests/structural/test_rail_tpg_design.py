#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

from unittest import TestCase
from civilpy.general import units
from civilpy.structural.arema.rail_tpg_design import TPG, ThroughPlateGirderFloorbeam


class TestTPG(TestCase):
    t = TPG()

    def test_run_calcs(self):
        self.assertLessEqual(self.t.fb_deflection, self.t.max_deflection)


class TestThroughPlateGirderFloorbeam(TestCase):
    def test_not_rolled_shape(self):
        # Covers lines 144-151: if not rolled_shape: branch
        fb = ThroughPlateGirderFloorbeam(rolled_shape=False)
        self.assertEqual(fb.shape, "W24x250")
        self.assertEqual(fb.depth.units, units("inch").units)
