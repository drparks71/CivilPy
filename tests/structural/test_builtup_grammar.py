"""The 1938 additions to the built-up shorthand: explicit width, a cover on
the top face only, two-channel members, rolled I members, web reinforcing
plates.  Catalogue checks use the historic Carnegie/Bethlehem shapes the
HAM-50-2180N shop sheets name."""
import math

import pytest

from civilpy.structural import builtup, laced_member

CHORD_TOP = "2P14x3/8 1P16x3/8 4L3.5x3.5x3/8 W16"     # sheet 301 style: cover on top, laced below
CHORD_BOT = "2C15x0.52x3.52x0.65 W16.5"                # sheet 313: 2-C15x40, laced both faces
CHORD_BOT_REINF = "2C15x0.52x3.52x0.65 2P12x7/16 W16.5"
POST = "I15.86x0.407x8.464x0.645"                       # 16WF58


def test_explicit_width_overrides_the_assumed_one():
    assert builtup.envelope("2P24x9/16 4L6x4x3/8")[0] == 18.0
    assert builtup.envelope("2P24x9/16 4L6x4x3/8 W22")[0] == 22.0
    # width token does not swallow a rolled-shape name
    with pytest.raises(ValueError):
        builtup.parse("W24x76")


def test_an_odd_cover_count_sits_on_top_only():
    rects, (d, B, tw, angles, covers) = builtup.rects(CHORD_TOP)
    tops = [r for r in rects if r[3] > d / 2]
    bots = [r for r in rects if r[3] < -d / 2]
    assert len(tops) == 1 and not bots
    assert tops[0][0] == 16.0 and tops[0][1] == pytest.approx(0.375)
    assert builtup.envelope(CHORD_TOP) == (16.0, 14.375)
    # area = 2 webs + cover + 4 sharp-cornered L3.5x3.5x3/8 (TranSystems 2009: 26.4375)
    assert builtup.properties(CHORD_TOP)["A"] == pytest.approx(26.42, abs=0.03)
    assert len(builtup.piece_labels(CHORD_TOP)) == len(rects)
    assert builtup.piece_labels(CHORD_TOP)[-1].startswith("cover plate 16x0.375 top")


def test_an_even_cover_count_still_splits_top_and_bottom():
    rects, (d, *_rest) = builtup.rects("4P24x1/2 2P16x7/16 4L4x4x1/2")
    assert sum(1 for r in rects if abs(r[3]) > d / 2) == 2
    open_j = builtup.properties("2P24x1/2 4L4x4x1/2")["J"]
    assert builtup.properties("4P24x1/2 2P16x7/16 4L4x4x1/2")["J"] > 20 * open_j
    # one cover does not close the box
    assert builtup.properties(CHORD_TOP)["J"] < 5 * builtup.properties("2P14x3/8 4L3.5x3.5x3/8 W16")["J"]


def test_two_channels_are_the_catalogue_channels_toes_in():
    rects, (d, B, tw, angles, covers) = builtup.rects(CHORD_BOT)
    assert (d, B, tw, angles, covers) == (15.0, 16.5, 0.52, None, None)
    assert len(rects) == 6
    # each channel = C15x40 (catalogue 11.8 in^2; sharp corners 11.7)
    assert builtup.properties(CHORD_BOT)["A"] == pytest.approx(2 * 11.7, abs=0.1)
    webs = [r for r in rects if r[1] == 15.0]
    assert sorted(round(r[2], 3) for r in webs) == [-7.99, 7.99]
    flanges = [r for r in rects if r[1] == 0.65]
    assert all(abs(r[2]) < 7.99 for r in flanges)          # toes turned in
    assert builtup.envelope(CHORD_BOT) == (16.5, 15.0)
    webs_only, _c, ang = builtup.parse(CHORD_BOT)
    assert webs_only == (2, 15.0, 0.52) and ang is None


def test_web_reinforcing_plates_sit_inside_the_channel_webs():
    plain = builtup.properties(CHORD_BOT)
    reinf = builtup.properties(CHORD_BOT_REINF)
    assert reinf["A"] == pytest.approx(plain["A"] + 2 * 12 * 0.4375)
    assert reinf["ASz"] == pytest.approx(plain["ASz"] + 2 * 12 * 0.4375)
    assert builtup.envelope(CHORD_BOT_REINF) == builtup.envelope(CHORD_BOT)
    assert len(builtup.piece_labels(CHORD_BOT_REINF)) == len(builtup.rects(CHORD_BOT_REINF)[0]) == 8


def test_a_rolled_i_is_web_plus_two_flanges():
    rects, (d, B, tw, angles, covers) = builtup.rects(POST)
    assert (d, B, tw) == (15.86, 8.464, 0.407) and angles is None
    assert len(rects) == 3
    p = builtup.properties(POST)
    # TranSystems' table for U0-L0: Agross 16.8486 (web + flanges, corners sharp)
    assert p["A"] == pytest.approx(16.8486, abs=0.01)
    assert p["H"] == 15.86 and p["B"] == 8.464
    assert p["ASz"] == pytest.approx(0.407 * (15.86 - 2 * 0.645))
    # strong axis: 16WF58 catalogue Ix = 746 in^4 (fillets add a little)
    assert p["Iy"] == pytest.approx(746.0, rel=0.03)


def test_laced_member_handles_channels_and_refuses_to_lace_an_i():
    lm = laced_member.LacedMember(CHORD_BOT, length_ft=21.0,
                                  lacing=laced_member.LacingSpec(2.5, 0.375, double=False,
                                                                 inclination_deg=60.0))
    assert lm.lacing_gauge_in() == pytest.approx(16.5 - 2 * 3.52)
    pieces = lm.pieces()
    kinds = {p.kind for p in pieces}
    assert {"channel web", "channel flange", "lacing bar"} <= kinds
    assert {p.face for p in pieces if p.kind == "lacing bar"} == {"top", "bottom"}
    assert lm.weight_lb() > lm.bare_weight_lb() > 0
    assert math.isclose(lm.bare_weight_lb(), builtup.weight_plf(CHORD_BOT) * 21.0, rel_tol=1e-9)
    post = laced_member.LacedMember(POST, length_ft=30.0)
    assert [p.kind for p in post.pieces()] == ["rolled I web", "rolled I flange", "rolled I flange"]
    with pytest.raises(ValueError):
        laced_member.LacedMember(POST, length_ft=30.0,
                                 lacing=laced_member.LacingSpec(2.5, 0.375)).lacing_gauge_in()


def test_a_top_covered_member_laces_the_bottom_only():
    lm = laced_member.LacedMember(CHORD_TOP, length_ft=21.0,
                                  lacing=laced_member.LacingSpec(2.5, 0.375, double=False))
    assert {p.face for p in lm.pieces() if p.kind == "lacing bar"} == {"bottom"}
