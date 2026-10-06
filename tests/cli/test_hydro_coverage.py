#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``hydro`` branches the end-to-end tests skip: the optional ``--depth``
rows of ``channel``, ``scour-pier`` without a boring (K1/K2 from flags)
and with a boring that has no gradation near the bed."""

import csv

from civilpy.cli.batch import execute

from tests.geotechnical.test_boring import DIGGS_FIXTURE


def _values(path):
    """Quantity → Value from a single-table csv export."""
    with open(path, newline="") as fh:
        return {row["Quantity"]: row["Value"] for row in csv.DictReader(fh)}


def test_channel_depth_adds_profile_rows(capsys):
    assert execute(["hydro", "channel", "200", "--width", "10",
                    "--depth", "1.5"]) == 0
    out = capsys.readouterr().out
    assert "Froude at given depth" in out
    assert "Specific energy at depth" in out
    assert "GVF profile class" in out


def test_scour_pier_without_boring_uses_flag_factors(tmp_path, capsys):
    from civilpy.water_resources import scour

    out = tmp_path / "scour.csv"
    assert execute(["hydro", "scour-pier", "--velocity", "6.2", "--depth", "8",
                    "--pier-width", "3", "--shape", "square",
                    "--pier-length", "12", "--skew", "15", "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "no bed gradation given" in text and "K4 = 1.0" in text
    values = _values(out)
    k2 = scour.angle_of_attack_factor(12.0, 3.0, 15.0)
    assert float(values["K1 (nose shape)"]) == scour.PIER_SHAPE_K1["square"]
    assert float(values["K2 (angle of attack)"]) == k2
    assert round(k2, 2) == 1.57
    assert float(values["K4 (armoring)"]) == 1.0
    assert values["D50"] == "" and values["D95"] == ""
    ys = scour.pier_scour_csu(6.2, 8.0, 3.0, k1=scour.PIER_SHAPE_K1["square"], k2=k2)
    assert float(values["Local pier scour ys"]) == ys


def test_scour_pier_without_boring_and_without_skew(tmp_path, capsys):
    out = tmp_path / "scour.csv"
    assert execute(["hydro", "scour-pier", "--velocity", "6.2", "--depth", "8",
                    "--pier-width", "3", "--pier-length", "12", "-o", str(out)]) == 0
    capsys.readouterr()
    assert float(_values(out)["K2 (angle of attack)"]) == 1.0


def test_scour_pier_boring_without_gradation_notes_k4(tmp_path, capsys):
    text = DIGGS_FIXTURE
    start = text.index("<measurement>\n    <Test gml:id=\"ParticleSize")
    end = text.index("</measurement>", start) + len("</measurement>")
    p = tmp_path / "B-001.xml"
    p.write_text(text[:start] + text[end:])
    assert execute(["hydro", "scour-pier", "--velocity", "6.2", "--depth", "8",
                    "--pier-width", "3", "--boring", str(p)]) == 0
    out = capsys.readouterr().out
    assert "boring has no gradation near the bed depth" in out
    assert "no bed gradation given" not in out
