#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""DIGGS lithology layers, material groups, scour-resistant rock and
scour carried through the strata.  DIGGS documents are generated from
random layer stacks in the ODOT export's shape (a SOIL and a ROCK
LithologySystem per hole, rock intervals logged in both)."""

import random

import pytest

from civilpy.geotech.boring import Borehole, Layer, material_group
from civilpy.geotech.boring_io import parse_diggs
from civilpy.water_resources.scour import scour_through_strata

SOIL = ["A-1-A", "A-1-B", "A-2-4", "A-3A", "A-4A", "A-4B", "A-6A", "A-6B", "A-7-6"]
ROCK = [("SHALE", "very weak", "highly", None), ("LIMESTONE", "strong", "slightly", 85.0),
        ("SANDSTONE", "moderately strong", "moderately", 62.0), ("SHALE", "weak to slightly strong", "moderately", 40.0)]


def obs(top, bot, graphic, *, strength=None, weathering=None, rqd=None, consistency=None, major=None):
    extra = ""
    if strength:
        extra += f"<rockStrength>{strength}</rockStrength><rockWeathering>{weathering}</rockWeathering>"
    if rqd is not None:
        extra += f'<unitRecoveryLength uom="ft">95</unitRecoveryLength><unitRQDLength uom="ft">{rqd}</unitRQDLength>'
    if consistency:
        extra += f"<consistency>{consistency}</consistency>"
    con = f"<constituent><Constituent><codeValue>{major}</codeValue><abundanceCode>Major</abundanceCode></Constituent></constituent>" if major else ""
    return f"""
      <lithologyObservation><LithologyObservation>
        <location><LinearExtent><gml:posList srsDimension="1">{top} {bot}</gml:posList></LinearExtent></location>
        <primaryLithology><Lithology>
          <classificationCode codeSpace="USCS"></classificationCode><lithDescription></lithDescription>{con}
          <fieldProperties><FieldProperties>{extra}
            <otherFieldProperty><Parameter><parameterName>Graphic</parameterName>
              <parameterValue>{graphic}</parameterValue></Parameter></otherFieldProperty>
          </FieldProperties></fieldProperties>
        </Lithology></primaryLithology>
      </LithologyObservation></lithologyObservation>"""


def diggs(holes):
    """holes: [(name, collar, depth_to_rock or None, [(top, bot, kind, spec)])]"""
    feats, systems = [], []
    for name, collar, dtr, layers in holes:
        dtr_xml = "" if dtr is None else str(dtr)
        feats.append(f"""
  <samplingFeature><Borehole gml:id="Borehole_{name}"><gml:name>{name}</gml:name>
    <otherSamplingFeatureProperty><Parameter><parameterName>Depth to Rock</parameterName>
      <parameterValue>{dtr_xml}</parameterValue></Parameter></otherSamplingFeatureProperty>
    <referencePoint><PointLocation><gml:pos srsDimension="3">-83.0 40.0 {collar}</gml:pos></PointLocation></referencePoint>
    <totalMeasuredDepth uom="ft">{layers[-1][1]}</totalMeasuredDepth>
  </Borehole></samplingFeature>""")
        soil = "".join(obs(t, b, spec[0] if k == "rock" else spec, consistency=None if k == "rock" else "stiff")
                       for t, b, k, spec in layers)
        rock = "".join(obs(t, b, spec[0], strength=spec[1], weathering=spec[2], rqd=spec[3], major=spec[0])
                       for t, b, k, spec in layers if k == "rock")
        for kind, body in (("SOIL", soil), ("ROCK", rock)):
            systems.append(f"""
  <observation><LithologySystem gml:id="Litho_{kind}_{name}">
    <samplingFeatureRef xlink:href="#Borehole_{name}"/>
    <lithologyClassificationType>{kind}</lithologyClassificationType>{body}
  </LithologySystem></observation>""")
    return f"""<?xml version="1.0"?>
<Diggs xmlns="http://diggsml.org/schemas/2.6" xmlns:gml="http://www.opengis.net/gml/3.2"
       xmlns:xlink="http://www.w3.org/1999/xlink">{''.join(feats)}{''.join(systems)}
</Diggs>"""


def random_hole(rng, name):
    depth, layers = 0.0, []
    rock_at = rng.choice([None, rng.uniform(15, 50)])
    while depth < 70:
        th = round(rng.uniform(1.5, 9), 1)
        top, bot = round(depth, 1), round(depth + th, 1)
        if rock_at is not None and top >= rock_at:
            layers.append((top, bot, "rock", rng.choice(ROCK)))
        else:
            layers.append((top, bot, "soil", rng.choice(SOIL)))
        depth = bot
    return (name, round(rng.uniform(600, 900), 1), None, layers)


@pytest.mark.parametrize("seed", range(6))
def test_layers_roundtrip_and_merge(seed):
    rng = random.Random(seed)
    holes = [random_hole(rng, f"B-00{i}-0-21") for i in range(1, 4)]
    got = {h.boring_id: h for h in parse_diggs(diggs(holes))}
    for name, collar, _, layers in holes:
        bh = got[name]
        assert bh.ground_elevation_ft == pytest.approx(collar)
        assert len(bh.layers) == len(layers)                      # rock logged twice, merged once
        for lay, (top, bot, kind, spec) in zip(bh.layers, layers):
            assert (lay.depth_top_ft, lay.depth_bottom_ft) == (pytest.approx(top), pytest.approx(bot))
            assert (lay.group == "rock") == (kind == "rock")
            if kind == "rock":
                assert lay.rock_strength == spec[1] and lay.rqd_pct == spec[3]
                assert lay.constituents[0] == spec[0]
        tops = [t for t, b, k, s in layers if k == "rock"]
        assert bh.rock_top_ft() == (pytest.approx(min(tops)) if tops else None)


def test_header_depth_to_rock_wins():
    hole = ("B-001-0-21", 700.0, 12.5, [(0, 10, "soil", "A-6A"), (10, 20, "rock", ROCK[1])])
    bh = parse_diggs(diggs([hole]))[0]
    assert bh.depth_to_rock_ft == 12.5 and bh.rock_top_ft() == 12.5
    assert bh.resistant_rock_top_ft() == 10


@pytest.mark.parametrize("cls,group", [("A-1-B", "granular"), ("A-2-4", "granular"), ("A-3A", "granular"),
                                       ("A-4A", "silt"), ("A-4B", "silt"), ("A-5", "silt"), ("A-6A", "clay"),
                                       ("A-7-6", "clay"), ("A-8", "organic"), ("SHALE", "rock"),
                                       ("INTERBEDDED SHALE AND LIMESTONE", "rock"), ("PAVEMENT OR BASE", "pavement"),
                                       ("TOPSOIL", "topsoil"), ("", "unknown")])
def test_material_group(cls, group):
    assert material_group(cls) == group


@pytest.mark.parametrize("words,group", [("gray silty clay", "clay"), ("brown gravel and sand", "granular"),
                                         ("sandy silt", "silt"), ("LIMESTONE", "rock")])
def test_group_from_words(words, group):
    assert material_group(None, words) == group


@pytest.mark.parametrize("strength,weathering,rqd,ok", [
    ("strong", "slightly", 80, True), ("strong", "slightly", 30, False), ("very weak", "slightly", 90, False),
    ("weak to slightly strong", "moderately", 70, False), ("moderately strong", "highly", 80, False),
    ("moderately strong", "slightly to severely", 80, False), ("strong", "moderately", None, True),
    (None, None, None, False)])
def test_scour_resistant(strength, weathering, rqd, ok):
    lay = Layer(10, 20, "ROCK", "LIMESTONE", rock_strength=strength, rock_weathering=weathering, rqd_pct=rqd)
    assert lay.scour_resistant() is ok


def test_soil_is_never_resistant():
    assert not Layer(0, 5, "SOIL", "A-1-A", consistency="very dense").scour_resistant()


# ── scour through the strata ──────────────────────────────────────────────

def bh_with(layers, collar=100.0):
    return Borehole("B-1", ground_elevation_ft=collar, total_depth_ft=layers[-1].depth_bottom_ft, layers=layers)


ROCKY = [Layer(0, 6, "SOIL", "A-6A"), Layer(6, 12, "SOIL", "A-1-B"),
         Layer(12, 15, "ROCK", "SHALE", rock_strength="very weak", rock_weathering="highly"),
         Layer(15, 40, "ROCK", "LIMESTONE", rock_strength="strong", rock_weathering="slightly", rqd_pct=80)]


@pytest.mark.parametrize("contraction,local", [(1, 2), (3, 8), (5, 20), (10, 30)])
def test_scour_stops_at_resistant_rock(contraction, local):
    r = scour_through_strata(98.0, contraction_ft=contraction, local_ft=local, borehole=bh_with(ROCKY))
    assert r.unlimited_elev_ft == pytest.approx(98.0 - contraction - local)
    assert r.resistant_rock_elev_ft == pytest.approx(85.0)
    assert r.design_elev_ft == pytest.approx(max(85.0, r.unlimited_elev_ft))
    assert r.limited_by_rock == (r.unlimited_elev_ft < 85.0)
    # strata scoured are contiguous from the bed down to the design line
    if r.strata:
        assert r.strata[0]["top_elev_ft"] == pytest.approx(98.0)
        assert r.strata[-1]["bottom_elev_ft"] == pytest.approx(r.design_elev_ft)
        for a, b in zip(r.strata, r.strata[1:]):
            assert a["bottom_elev_ft"] == pytest.approx(b["top_elev_ft"])
        assert not any(s["scour_resistant"] for s in r.strata)


def test_weak_rock_is_scoured_through():
    r = scour_through_strata(98.0, contraction_ft=4, local_ft=10, borehole=bh_with(ROCKY))
    assert any(s["group"] == "rock" for s in r.strata)
    assert any("erodible" in n for n in r.notes)


@pytest.mark.parametrize("total", [2.0, 10.0, 40.0])
def test_soil_only_is_never_limited(total):
    soil = [Layer(0, 30, "SOIL", "A-4A"), Layer(30, 60, "SOIL", "A-3A")]
    r = scour_through_strata(95.0, contraction_ft=total / 2, local_ft=total / 2, borehole=bh_with(soil))
    assert not r.limited_by_rock and r.design_elev_ft == pytest.approx(95.0 - total)
    assert r.scour_depth_ft == pytest.approx(total)


def test_no_boring_is_unlimited_and_says_so():
    r = scour_through_strata(95.0, contraction_ft=3, local_ft=7, degradation_ft=1)
    assert r.total_ft == 11 and r.design_elev_ft == 84 and r.strata == []
    assert any("no boring" in n for n in r.notes)


def test_boring_too_short_is_flagged():
    short = [Layer(0, 8, "SOIL", "A-6A")]
    r = scour_through_strata(98.0, contraction_ft=5, local_ft=15, borehole=bh_with(short))
    assert any("below the bottom of the boring" in n for n in r.notes)
