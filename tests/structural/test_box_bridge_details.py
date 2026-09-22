import math

import pytest

from civilpy.structural.box_bridge_details import BoxDetailInput, detailed_box_bridge_emit
from civilpy.structural.rebar_clash import check_clearance, segment_distance
from civilpy.structural.rhino_bim import EmitObject


@pytest.mark.parametrize("points,expected", [
    (((0,0,0), (2,0,0), (1,-1,0), (1,1,0)), 0),
    (((0,0,0), (2,0,0), (0,1,0), (2,1,0)), 1),
    (((0,0,0), (0,0,0), (1,0,0), (1,1,0)), 1),
    (((0,0,0), (1,0,0), (2,1,0), (2,2,0)), math.sqrt(2)),
    (((0,0,0), (1,0,0), (0,1,1), (1,1,1)), math.sqrt(2)),
])
def test_segment_distance(points, expected):
    assert segment_distance(*points) == pytest.approx(expected)
    assert segment_distance(*points[2:], *points[:2]) == pytest.approx(expected)


def test_bar_diameters_and_tangency():
    a = EmitObject("polyline", "steel", ((0,0,0), (2,0,0)),
                   {"bim.id":"a", "clash.group":"a", "rebar.dia_in":"1"})
    def b(y):
        return EmitObject("polyline", "steel", ((0,y,0), (2,y,0)),
                   {"bim.id":"b", "clash.group":"b", "rebar.dia_in":"1"})
    assert not check_clearance((a, b(1/12)), (("a","b"),))
    assert check_clearance((a, b(.5/12)), (("a","b"),))[0].clearance_in == pytest.approx(-.5)
    assert check_clearance((a, b(1.5/12)), (("a","b"),), required_clearance_in=1)


@pytest.mark.parametrize("kind", ["integral", "semi-integral", "seat"])
def test_model_physical_inventory(kind):
    model = detailed_box_bridge_emit(BoxDetailInput(abutment=kind))
    assert len(model.of_type("bearing")) == 32
    assert len(model.of_type("pile")) == (12 if kind == "integral" else 0)
    assert bool(model.of_type("spread_footing")) == (kind != "integral")
    assert len(model.of_type("deck")) == 1
    assert len(model.of_type("approach_slab")) == 4
    assert len(model.of_type("sleeper")) == 4
    assert len(model.of_type("underdrain")) == 2
    ids = [o.tags['bim.id'] for o in model.objects]
    assert len(ids) == len(set(ids))
    assert all(math.isfinite(c) for o in model.objects for p in o.points for c in p)
    anchors = [o for o in model.objects if o.tags.get('clash.group') == 'rail_anchors']
    assert anchors
    assert all(math.dist(*o.points) == pytest.approx(.65+15/12) for o in anchors)
    assert not check_clearance(model.objects, (("rail_anchors","beam_rebar"), ("rail_anchors","deck_rebar")))
    # Deliberately retained catalog clashes must remain visible in QA output.
    assert check_clearance(model.objects, (("approach_anchors","approach_rebar"),))


def test_rejects_outside_example_envelope():
    with pytest.raises(ValueError):
        detailed_box_bridge_emit(BoxDetailInput(crossfall_pct=4))
    with pytest.raises(ValueError):
        detailed_box_bridge_emit(BoxDetailInput(profile_rise_in=float('nan')))
    with pytest.raises(ValueError, match="flexible piles"):
        detailed_box_bridge_emit(BoxDetailInput(foundation="spread"))


def test_tst_comparison_and_shaft_foundation():
    model = detailed_box_bridge_emit(BoxDetailInput(abutment="seat", foundation="shafts", railing="TST-2", terminal="trailing_t"))
    assert not model.of_type("pile")
    assert len(model.of_type("drilled_shaft")) == 6
    anchors = [o for o in model.objects if o.tags.get('clash.group') == 'rail_anchors']
    assert anchors and all(math.dist(*o.points) == pytest.approx(32/12) for o in anchors)
    treatments = model.of_type("terminal")
    assert len(treatments) == 4
    assert {o.tags['terminal_type'] for o in treatments if o.tags['end']=='S'} == {'buried'}
    assert {o.tags['terminal_type'] for o in treatments if o.tags['end']=='E'} == {'trailing_t'}
    assert len(model.of_type("rounded_terminal")) == 2


def test_solid_deck_volume_and_roundtrip(tmp_path):
    import json
    r3 = pytest.importorskip("rhino3dm")
    from dataclasses import replace
    from civilpy.structural.rhino_bim import emit_to_3dm, emit_to_json
    model = detailed_box_bridge_emit(BoxDetailInput(terminal="type_a"))
    deck, = model.of_type("deck")
    # One object is insufficient: unwelded station edges still look like
    # separate planks in Rhino. Every interior transverse edge is shared.
    from collections import Counter
    edges = Counter(tuple(sorted((a,b))) for face in deck.faces
                    for a,b in zip(face, face[1:]+face[:1]))
    transverse = [count for (a,b),count in edges.items()
                  if deck.points[a][0] == deck.points[b][0]
                  and 0 < deck.points[a][0] < 60]
    assert transverse and all(count == 2 for count in transverse)
    # Independent signed-volume check: prism thickness plus parabolic profile.
    volume = 0.
    for face in deck.faces:
        for k in range(1,len(face)-1):
            a,b,c = (deck.points[i] for i in (face[0],face[k],face[k+1]))
            volume += (a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    assert volume == pytest.approx(60*32*(7/12+2/3/12),rel=3e-5)
    assert 'faces' in json.loads(emit_to_json(replace(model,objects=(deck,))))['objects'][0]
    # Include formed terminal geometry, not only the simple slab mesh.
    selected = tuple(o for o in model.objects if o.kind == 'mesh')
    emit_to_3dm(replace(model,objects=selected), tmp_path/'surfaces.3dm',mesh=True)
    doc = r3.File3dm.Read(str(tmp_path/'surfaces.3dm'))
    assert len(doc.Objects) == len(selected)
    assert all(o.Geometry.IsValid and o.Geometry.IsClosed for o in doc.Objects)
    assert len(model.of_type('terminal_anchor')) == 4
