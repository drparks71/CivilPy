#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Span-curve lookups on synthetic curves in the neutral schema (the real
NSBA curves are validated where they are kept, snbi_ui
utils/manuals/NSBA/validation/span_curves)."""

import pytest

from civilpy.structural.span_curves import SpanDepthCurves, SpanWeightCurves, spacing_class

WEIGHT = {
    "Single Span — All Girder Spacing": {"span_ft": [50, 100, 200], "psf": [20, 30, 60]},
    "Single Span — 9 ft to 11 ft Girder Spacing": {"span_ft": [50, 150], "psf": [22, 40]},
    "Two Span — All Girder Spacing": {"span_ft": [50, 300], "psf": [18, 70]},
    "Three or More Spans — All Girder Spacing": {"span_ft": [100, 400], "psf": [25, 85]},
}
DEPTH = {
    "Single-span, All Girder Spacings": {"span_ft": [80, 300], "girder_in": [38, 136], "total_in": [51, 150]},
    "Three-span Continuous, All Girder Spacings": {"span_ft": [150, 300], "girder_in": [58, 100],
                                                   "total_in": [71, 120]},
    "Four-span Continuous, All Girder Spacings": {"span_ft": [150, 300], "girder_in": [57, 95],
                                                  "total_in": [70, 112]},
}


@pytest.mark.parametrize("s,band", [(None, "All"), (6, "All"), (8, "7 ft"), (9.5, "9 ft"), (12, "11 ft")])
def test_spacing_bands(s, band):
    assert spacing_class(s).startswith(band)


def test_weight_lookup_and_fallbacks():
    w = SpanWeightCurves(WEIGHT)
    assert w.psf(75)["psf"] == pytest.approx(25.0)
    banded = w.psf(100, 10.0)
    assert banded["curve"].endswith("9 ft to 11 ft Girder Spacing") and banded["psf"] == pytest.approx(31.0)
    # the band stops at 150 ft: back to all spacings
    assert w.psf(180, 10.0)["curve"] == "Single Span — All Girder Spacing"
    # a missing band uses all spacings; the maximum span of a unit governs
    two = w.psf([120, 175.0], 8.0)
    assert two["curve"] == "Two Span — All Girder Spacing" and two["span_ft"] == 175
    assert w.psf([100] * 5)["curve"].startswith("Three or More")
    out = w.psf(250)
    assert out["psf"] is None and not out["in_range"]
    ext = w.psf(250, extrapolate=True)
    assert ext["psf"] == pytest.approx(75.0) and not ext["in_range"]


def test_depth_lookup():
    d = SpanDepthCurves(DEPTH)
    r = d.depth(190)
    assert r["girder_in"] == pytest.approx(38 + 98 * 110 / 220) and r["in_range"]
    assert d.depth([200, 250, 200])["curve"].startswith("Three-span")
    assert d.depth([150] * 6)["curve"].startswith("Four-span")
    assert d.depth(60)["girder_in"] is None


def test_load_from_file(tmp_path):
    import json
    p = tmp_path / "w.json"
    p.write_text(json.dumps(WEIGHT))
    assert SpanWeightCurves.load(p).psf(100)["psf"] == pytest.approx(30.0)
