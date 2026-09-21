"""MethodABearing sanity: a 24 x 21 in, 50-durometer, 3 x 5/8 in pad under 360 kip DL + 165 kip LL
(S = 8.96, sigma = 1.06 ksi) with analysis rotations passes the Method A stress, shear, stability,
reinforcement and combined-strain checks when the movement is taken by a slider, and fails the shear
deformation check as a plain pad on a 355-ft expansion length."""
import io, contextlib
from civilpy.structural.aashto.bearings import MethodABearing


def _pad(expansion_length, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return MethodABearing(width=24.0, length=21.0, durometer=50, internal_t=0.625, external_t=0.413,
                              steel_t=0.1046, plys=4, span=187, expansion_length=expansion_length,
                              loads={"live": 165.0, "total_dead_load": 360.0, "total_load": 525.0},
                              max_dl_delta=4.4, max_ll_delta=1.5, max_ll_loc=94, deck_slope=0.045, plate_bev=0.045,
                              rotation_st=0.002, rotation_cy=0.0022, **kw)


def test_strain_table_is_percent_and_deflection_in_inches():
    b = _pad(0.0)
    assert 3.0 < b.dl_strain < 6.0            # percent strain from Figure C14.7.6.3.3-1
    assert 0.05 < b.dl_deflection < 0.2       # inches over h_rt = 2.7 in


def test_slider_pad_passes_method_a():
    b = _pad(0.0)
    assert b.checks["#2 - Service LL Check"] == 1 and b.checks["#3 - Service LL < 1.25 ksi"] == 1
    assert b.checks["#8 - Thermal Expansion"] == 1
    assert b.checks["#18 - Total Strain"] == 1 and b.checks["#19 - Total Strain Check 2"] == 1
    assert b.checks["#16 - Steel Reinforcement - Service Limit State"] == 1


def test_plain_pad_fails_shear_deformation_on_long_expansion_length():
    b = _pad(355.0)
    assert b.checks["#8 - Thermal Expansion"] == 0
    assert 2 * b.delta_s > b.total_elastomer_thickness
