"""Exercise the packaged generation path without a Rhino installation."""
import json
import subprocess
import sys

import pytest

rhino3dm = pytest.importorskip("rhino3dm")

from civilpy.structural import box_bridge_gallery as gallery


def test_packaged_module_help():
    result = subprocess.run(
        [sys.executable, '-m', 'civilpy.structural.box_bridge_gallery', '--help'],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--output' in result.stdout


def test_generate_export_and_clash_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, 'SCENARIOS', gallery.SCENARIOS[:1])
    reports = gallery.generate(str(tmp_path))
    report = reports['integral']
    assert report['clash_count'] > 0
    assert report['bearing_count'] == 32
    assert json.loads((tmp_path/'summary.json').read_text()) == json.loads(
        json.dumps(reports))
    data = json.loads((tmp_path/'integral.json').read_text())
    deck, = (o for o in data['objects'] if o['tags'].get('bim.type') == 'deck')
    assert deck['tags']['geometry.native'] == 'station_loft'
    model = rhino3dm.File3dm.Read(str(tmp_path/'Box Bridge Detail Gallery.3dm'))
    assert len(model.Objects) == len(data['objects'])
    assert all(o.Geometry.IsValid for o in model.Objects)
    assert all(o.Geometry.IsClosed for o in model.Objects
               if isinstance(o.Geometry, rhino3dm.Mesh))


def test_rhino_adapter_import_is_lazy():
    # Importing the API on ordinary CPython must not require RhinoCommon.
    from civilpy.structural.rhino_box_slabs import refine, slab_solid
    assert callable(refine) and callable(slab_solid)
