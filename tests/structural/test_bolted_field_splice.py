#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Validation of the AASHTO 6.13.6.1 bolted-field-splice designer against two
independently worked plate-girder splices.  The expected values are plain
numeric results (bolt counts, plate sizes, design forces, member resistances)
hand-checked against the two reference designs; no copyrighted content is
reproduced here.

Design forces carry a small (<1%) offset from the reference numbers because
this module uses the exact AASHTO 6.13.6.1.3b resistance-factor ratio
phi_u/phi_y = 0.80/0.95 where the reference rounds it to 0.84; the tolerance
below absorbs that."""

import pytest

from civilpy.structural.aashto.lrfd import (
    design_splice, SpliceInput, Flange, GirderSide, girder_side_from_w,
    SpliceLoads, BoltSpec, PlatePair, WebPlate,
)


# ---------------------------------------------------------------------------
# Worked design 1 — composite plate girder, flanges resist the splice moment.
# ---------------------------------------------------------------------------

def _design_one():
    left = GirderSide(
        top_flange=Flange("Grade 50W", 1.0, 16.0),
        bottom_flange=Flange("Grade 50W", 1.375, 18.0),
        web_material="Grade 50W", web_thickness=0.5, web_depth=69.0,
        haunch=1.0, stiffener_spacing_ft=17.25, stiffened=True,
    )
    right = GirderSide(
        top_flange=Flange("HPS Grade 70W", 1.0, 18.0),
        bottom_flange=Flange("HPS Grade 70W", 1.0, 20.0),
        web_material="Grade 50W", web_thickness=0.5625, web_depth=69.0,
        haunch=1.0, stiffener_spacing_ft=12.0, stiffened=True,
    )
    loads = SpliceLoads(
        dc1_m=248, dc1_v=-82, dc2_m=50, dc2_v=-12, dw_m=52, dw_v=-11,
        ll_pos_m=2469, ll_pos_v=19, ll_neg_m=-1754, ll_neg_v=-112,
        deck_cast_m=1300, deck_cast_v=-82,
    )
    bolts = BoltSpec(bolt_type="A325", diameter=0.875,
                     flange_threads_excluded=True, web_threads_excluded=False,
                     surface_class="B", hole_type="standard")
    inp = SpliceInput(
        left=left, right=right, loads=loads, bolts=bolts,
        top_plates=PlatePair("Grade 50W", 0.6875, 7.0, 0.625, 16.0, 2),
        bottom_plates=PlatePair("Grade 50W", 0.875, 8.0, 0.75, 18.0, 2),
        web_plate=WebPlate("Grade 50W", 0.3125, 2),
        deck_composite=True, deck_thickness=9.0, deck_eff_width=144.0, fc=4.0,
        top_flange_rows=4, bottom_flange_rows=4, web_rows=2,
        bolt_spacing=3.0, flange_edge=2.0, flange_end=1.5,
        web_edge=2.0, web_end=1.5, web_weld_size=0.3125,
        web_weld_clearance=0.375, girder_gap=0.75, entering_tightening=3.0,
        design_year=2020,
    )
    return design_splice(inp)


class TestDesignOne:
    def setup_method(self):
        self.d = _design_one()

    def test_factored_load_combinations(self):
        m = self.d.factored_moments
        assert m["deck_cast"] == pytest.approx(1820.0)
        assert m["strength_pos"] == pytest.approx(4771.25)
        assert m["strength_neg"] == pytest.approx(-2767.5)
        assert m["service_pos"] == pytest.approx(3559.7, rel=1e-4)
        assert m["service_neg"] == pytest.approx(-1930.2, rel=1e-4)
        assert self.d.factored_shears["service_neg"] == pytest.approx(-250.6)

    def test_bolt_counts_and_rows(self):
        assert (self.d.top_flange.bolt_rows,
                self.d.top_flange.total_bolts) == (4, 12)
        assert (self.d.web.bolt_rows, self.d.web.total_bolts) == (2, 26)
        assert (self.d.bottom_flange.bolt_rows,
                self.d.bottom_flange.total_bolts) == (4, 24)

    def test_flange_design_forces(self):
        # Reference Pfy: top 720.3, bottom 1152.1 (kip); 0.84-vs-exact offset.
        assert self.d.top_flange.design_force == pytest.approx(720.3, rel=0.01)
        assert self.d.bottom_flange.design_force == pytest.approx(
            1152.1, rel=0.01)

    def test_filler_reduction_factor(self):
        # No filler on the top flange, R = 1; bottom flange R = 0.7985.
        assert self.d.top_flange.extra["filler_R"] == pytest.approx(1.0)
        assert self.d.bottom_flange.extra["filler_R"] == pytest.approx(
            0.79851, rel=1e-4)

    def test_flange_layout(self):
        t = self.d.top_flange
        assert (t.gage_bolts, t.gage_groups, t.pitch, t.end) == (3, 6, 3, 1.5)
        assert t.pitch_groups == pytest.approx(3.75)
        b = self.d.bottom_flange
        assert (b.gage_bolts, b.gage_groups) == (4, 6)

    def test_splice_plate_lengths(self):
        assert self.d.top_flange.plate_length == pytest.approx(18.75)
        assert self.d.bottom_flange.plate_length == pytest.approx(36.75)

    def test_web_layout_and_plate(self):
        w = self.d.web
        assert w.pitch == pytest.approx(5.0)
        assert w.plate_length == pytest.approx(63.0)   # splice-plate height
        assert w.plate_width == pytest.approx(14.75)
        assert w.gage_groups == pytest.approx(4.75)
        assert w.design_force == pytest.approx(467.91, rel=1e-3)  # phi*Vn

    def test_web_has_no_moment_force(self):
        # The flanges carry the full splice moment here, so Hw = 0 and the web
        # is governed by the maximum-pitch layout (26 bolts).
        assert self.d.web.extra["hw_strength"] == pytest.approx(0.0)
        assert self.d.web.extra["hw_service"] == pytest.approx(0.0)
        assert self.d.web.total_bolts == 26
        assert self.d.web.strength_bolts == 10

    def test_all_checks_pass(self):
        assert self.d.ok
        top = {c.name: c for c in self.d.top_flange.checks}
        # Block shear on the top flange: Mode 1 = 900.9 kip, Mode 2 governs at
        # 737.45 kip (both factored, reference values).
        assert top["girder flange block shear (Mode 2)"].factored_capacity \
            == pytest.approx(737.45, rel=1e-3)
        assert top["girder flange block shear (Mode 1)"].factored_capacity \
            == pytest.approx(900.9, rel=1e-3)
        # Composite slab crushing resistance 0.85 f'c b ts = 4406.4 kip.
        bottom = {c.name: c for c in self.d.bottom_flange.checks}
        assert bottom["composite slab crushing"].capacity == pytest.approx(
            4406.4)


# ---------------------------------------------------------------------------
# Worked design 2 — deeper girder, unstiffened left web, moment-critical.
# The flanges cannot carry the full negative splice moment, so the excess is
# delivered to the web as a horizontal force Hw (6.13.6.1.3c) that drives the
# web bolt count to 66.  The flanges are also over-stressed at Service II: the
# negative-moment slip check fails (mirrors the reference NOTICE), so the
# overall design is not "ok".  Bolt sizing and layout match the reference.
# ---------------------------------------------------------------------------

def _design_two():
    left = GirderSide(
        top_flange=Flange("Grade 50", 1.0, 19.0),
        bottom_flange=Flange("Grade 50", 1.4375, 20.0),
        web_material="Grade 50W", web_thickness=0.75, web_depth=109.0,
        haunch=2.0, stiffener_spacing_ft=0.0, stiffened=False,
    )
    right = GirderSide(
        top_flange=Flange("Grade 50", 2.0, 22.0),
        bottom_flange=Flange("Grade 50", 2.25, 24.0),
        web_material="Grade 50W", web_thickness=0.75, web_depth=109.0,
        haunch=2.0, stiffener_spacing_ft=27.25, stiffened=True,
    )
    loads = SpliceLoads(
        dc1_m=-1564, dc1_v=-147, dc2_m=-242, dc2_v=-28, dw_m=-315, dw_v=-37,
        ll_pos_m=5627, ll_pos_v=19, ll_neg_m=-7117, ll_neg_v=-126,
        deck_cast_m=3006, deck_cast_v=-79,
    )
    bolts = BoltSpec(bolt_type="A325", diameter=0.875,
                     flange_threads_excluded=True, web_threads_excluded=False,
                     surface_class="B", hole_type="standard")
    inp = SpliceInput(
        left=left, right=right, loads=loads, bolts=bolts,
        top_plates=PlatePair("Grade 50", 0.625, 8.5, 0.5625, 19.0, 2),
        bottom_plates=PlatePair("Grade 50", 0.875, 9.0, 0.8125, 20.0, 2),
        web_plate=WebPlate("Grade 50", 0.4375, 2),
        deck_composite=True, deck_thickness=8.0, deck_eff_width=114.0, fc=4.0,
        top_flange_rows=4, bottom_flange_rows=4, web_rows=2,
        bolt_spacing=3.0, flange_edge=2.0, flange_end=1.125,
        web_edge=2.0, web_end=1.75, web_weld_size=0.3125,
        web_weld_clearance=0.25, girder_gap=0.75, entering_tightening=3.0,
        design_year=2020,
    )
    return design_splice(inp)


class TestDesignTwo:
    def setup_method(self):
        self.d = _design_two()

    def test_flange_bolt_counts(self):
        # Strength (not slip) governs the count: top 20, bottom 28.
        assert self.d.top_flange.total_bolts == 20
        assert self.d.top_flange.strength_bolts == 20
        assert self.d.bottom_flange.total_bolts == 28

    def test_factored_strength_moments(self):
        # Dead load is negative here, so Strength I uses the maximum gamma_p
        # (1.25/1.50) for the negative moment: reference -15184.75 kip-ft.
        m = self.d.factored_moments
        assert m["strength_neg"] == pytest.approx(-15184.75, rel=1e-6)
        assert m["strength_pos"] == pytest.approx(8017.1, rel=1e-5)

    def test_web_moment_force_governs(self):
        # Excess of the negative Strength moment over the flange moment
        # resistance is delivered to the web: Hw ~ 3319 kip (D/4 lever arm),
        # driving the web to 66 bolts.
        w = self.d.web
        assert w.extra["hw_strength"] == pytest.approx(3319.0, rel=0.01)
        assert w.total_bolts == 66
        assert w.strength_bolts == 66
        assert w.pitch == pytest.approx(3.125)
        assert w.plate_length == pytest.approx(103.5)

    def test_flange_layout_and_plates(self):
        t = self.d.top_flange
        assert (t.gage_bolts, t.end) == (4.5, 1.125)
        assert t.plate_length == pytest.approx(29.25)
        b = self.d.bottom_flange
        assert b.gage_bolts == 5
        assert b.plate_length == pytest.approx(41.25)

    def test_filler_on_thinner_flange(self):
        # Top flange has a 1-in filler (t_left=1, t_right=2): R = 2/3.
        assert self.d.top_flange.extra["filler_R"] == pytest.approx(
            2.0 / 3.0, rel=1e-4)

    def test_service_slip_governs_notice(self):
        # Over-stressed flanges: the negative Service II slip check fails,
        # matching the reference NOTICE; the overall design is not ok.
        slip = {c.name: c for c in self.d.top_flange.checks}[
            "top flange Service II slip"]
        assert slip.ok is False
        assert not self.d.ok


# ---------------------------------------------------------------------------
# Synthetic rolled-beam splice: invented loads and plate selections.
# Rolled-section dimensions come from the public AISC shape catalog.

def _design_synthetic_rolled_splice():
    larger = GirderSide(   # W24x131
        top_flange=Flange("Grade 50", 0.960, 12.900),
        bottom_flange=Flange("Grade 50", 0.960, 12.900),
        web_material="Grade 50", web_thickness=0.605, web_depth=22.580,
        haunch=2.0, stiffener_spacing_ft=None, stiffened=False,
    )
    smaller = GirderSide(  # W24x104 (governs)
        top_flange=Flange("Grade 50", 0.750, 12.800),
        bottom_flange=Flange("Grade 50", 0.750, 12.800),
        web_material="Grade 50", web_thickness=0.500, web_depth=22.600,
        haunch=2.0, stiffener_spacing_ft=None, stiffened=False,
    )
    loads = SpliceLoads(
        dc1_m=20.0, dc1_v=-12.0, dc2_m=5.0, dc2_v=-3.0,
        dw_m=8.0, dw_v=-5.0, ll_pos_m=280.0, ll_pos_v=0.0,
        ll_neg_m=-160.0, ll_neg_v=-30.0, deck_cast_m=0.0, deck_cast_v=0.0,
    )
    bolts = BoltSpec(bolt_type="A325", diameter=0.875,
                     flange_threads_excluded=False, web_threads_excluded=False,
                     surface_class="C", hole_type="oversize")
    plates = PlatePair("Grade 50", inner_thickness=0.5, inner_width=5.0,
                       outer_thickness=0.5, outer_width=12.5, shear_planes=2)
    inp = SpliceInput(
        left=larger, right=smaller, loads=loads, bolts=bolts,
        top_plates=plates, bottom_plates=plates,
        web_plate=WebPlate("Grade 50", 0.5, 2),
        deck_composite=True, deck_thickness=8.0, deck_eff_width=96.0, fc=4.0,
        top_flange_rows=2, bottom_flange_rows=2, web_rows=4,
        bolt_spacing=3.0, flange_edge=1.5, flange_end=1.5,
        web_edge=1.5, web_end=1.5, web_weld_size=0.3125, web_weld_clearance=0.375,
        girder_gap=0.75, entering_tightening=3.0, design_year=2016,
        method="stress_based", fcf_top=10.0, fcf_bot=20.0, r_h=1.0, alpha=1.0,
    )
    return design_splice(inp)


class TestSyntheticRolledSplice:
    def setup_method(self):
        self.d = _design_synthetic_rolled_splice()

    def test_flange_design_force(self):
        # Fcf = 0.75*alpha*phi_f*Fyf = 37.5 ksi (the low-stress floor governs);
        # Effective area is the smaller of gross and factored net area.
        # 7/8 in bolt + 1/8 in net-area allowance = 1 in deduction.
        net_area = (12.8 - 2 * 1.0) * 0.75
        force = 37.5 * min(12.8 * 0.75, (0.8 / 0.95) * (65 / 50) * net_area)
        assert self.d.top_flange.design_force == pytest.approx(force)
        assert self.d.bottom_flange.design_force == pytest.approx(
            force)

    def test_flange_bolt_counts(self):
        # 10 bolts per flange per side (2 rows x 5 columns), strength-governed.
        assert self.d.top_flange.total_bolts == 10
        assert self.d.top_flange.strength_bolts == 10
        assert self.d.bottom_flange.total_bolts == 10
        assert self.d.bottom_flange.strength_bolts == 10

    def test_no_filler_reduction(self):
        # Filler is 0.96 - 0.75 = 0.21 in < 1/4 in -> no development penalty.
        assert self.d.top_flange.extra["filler_R"] == pytest.approx(1.0)
        assert self.d.bottom_flange.extra["filler_R"] == pytest.approx(1.0)

    def test_all_flange_checks_pass(self):
        for flange in (self.d.top_flange, self.d.bottom_flange):
            failed = [c.name for c in flange.checks if not c.ok]
            assert failed == [], f"{flange.name}: {failed}"

    def test_overall_ok(self):
        assert self.d.ok

    def test_web_layout_and_capacity(self):
        # Minimum bolt layout for this synthetic case.
        assert self.d.web.total_bolts == 16
        assert self.d.web.design_force == pytest.approx((0.58 * 50 * 0.5 * 22.6), rel=1e-3)


class TestGirderSideFromW:
    """Catalog dimensions and synthetic end-to-end splice checks."""

    def test_from_label_matches_aisc(self):
        gs = girder_side_from_w("W24X104", "Grade 50")
        assert gs.top_flange.width == pytest.approx(12.8)
        assert gs.top_flange.thickness == pytest.approx(0.75)
        assert gs.web_thickness == pytest.approx(0.5)
        assert gs.web_depth == pytest.approx(22.6)      # d - 2*tf = 24.1 - 1.5

    def test_design_from_labels_synthetic_case(self):
        loads = SpliceLoads(
            dc1_m=20.0, dc1_v=-12.0, dc2_m=5.0, dc2_v=-3.0,
            dw_m=8.0, dw_v=-5.0, ll_pos_m=280.0, ll_pos_v=0.0,
            ll_neg_m=-160.0, ll_neg_v=-30.0,
        )
        bolts = BoltSpec(bolt_type="A325", diameter=0.875,
                         flange_threads_excluded=False,
                         web_threads_excluded=False,
                         surface_class="C", hole_type="oversize")
        plates = PlatePair("Grade 50", 0.5, 5.0, 0.5, 12.5, 2)
        inp = SpliceInput(
            left=girder_side_from_w("W24X131", "Grade 50"),
            right=girder_side_from_w("W24X104", "Grade 50"),
            loads=loads, bolts=bolts, top_plates=plates, bottom_plates=plates,
            web_plate=WebPlate("Grade 50", 0.5, 2),
            deck_composite=True, deck_thickness=8.0, deck_eff_width=96.0,
            top_flange_rows=2, bottom_flange_rows=2, web_rows=4,
            bolt_spacing=3.0, flange_edge=1.5, flange_end=1.5,
            web_edge=1.5, web_end=1.5, design_year=2016,
            method="stress_based", fcf_top=10.0, fcf_bot=20.0,
        )
        d = design_splice(inp)
        net_area = (12.8 - 2 * 1.0) * 0.75
        force = 37.5 * min(12.8 * 0.75, (0.8 / 0.95) * (65 / 50) * net_area)
        assert d.top_flange.design_force == pytest.approx(force)
        assert d.top_flange.total_bolts == 10
        assert d.bottom_flange.total_bolts == 10
        assert d.ok
