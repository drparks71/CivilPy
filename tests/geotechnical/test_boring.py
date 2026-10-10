#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Boring-log schema and DIGGS parser.

The fixture is a hand-built DIGGS 2.5.a fragment that mirrors the real Ohio
DOT TIMS export structure (namespaced GML, ``samplingFeatureRef`` links,
``DriveSet`` SPT increments, ``Grading`` curve points) but is trimmed to a
single borehole so the parser is exercised offline."""

import math

import pytest

from civilpy.geotech.boring import (
    DriveIncrement,
    GradingPoint,
    GradingResult,
    Sample,
    SPTResult,
)
from civilpy.geotech.boring_io import parse_diggs, read_pdf_log

DIGGS_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<Diggs xmlns="http://diggsml.org/schemas/2.5.a"
       xmlns:gml="http://www.opengis.net/gml/3.2"
       xmlns:xlink="http://www.w3.org/1999/xlink">
  <project>
    <Project gml:id="Project_TEST">
      <gml:name>600918</gml:name>
    </Project>
  </project>
  <samplingFeature>
    <Borehole gml:id="Borehole_B-001-0-21">
      <gml:name>B-001-0-21</gml:name>
      <investigationTarget>Natural Ground</investigationTarget>
      <locality>
        <Locality gml:id="L1">
          <station>58193.96</station>
          <offset uom="ft">54.45</offset>
          <offsetDirection>Lt</offsetDirection>
        </Locality>
      </locality>
      <referencePoint>
        <PointLocation gml:id="B-001-pl">
          <gml:pos>-82.51077351 40.69697058 1246.9</gml:pos>
        </PointLocation>
      </referencePoint>
      <whenConstructed>
        <TimeInterval gml:id="T1">
          <start>11/8/2021</start>
          <end>11/8/2021</end>
        </TimeInterval>
      </whenConstructed>
      <totalMeasuredDepth uom="ft">7.5</totalMeasuredDepth>
      <boreholePurpose>Subgrade</boreholePurpose>
    </Borehole>
  </samplingFeature>
  <measurement>
    <Test gml:id="SPT_B-001-0-21_1.5">
      <name>SPT</name>
      <samplingFeatureRef xlink:href="#Borehole_B-001-0-21"/>
      <outcome>
        <TestResult gml:id="TR1">
          <location>
            <LinearExtent gml:id="LE1"><gml:posList>1.5</gml:posList></LinearExtent>
          </location>
        </TestResult>
      </outcome>
      <procedure>
        <DrivenPenetrationTest gml:id="DPT1">
          <penetrationTestType>SPT</penetrationTestType>
          <hammerType>90</hammerType>
          <hammerEfficiency uom="%">CME Automatic</hammerEfficiency>
          <totalPenetration uom="in">18</totalPenetration>
          <driveSet><DriveSet gml:id="d1"><index>1</index><blowCount>12</blowCount><penetration uom="in">6</penetration></DriveSet></driveSet>
          <driveSet><DriveSet gml:id="d2"><index>2</index><blowCount>14</blowCount><penetration uom="in">6</penetration></DriveSet></driveSet>
          <driveSet><DriveSet gml:id="d3"><index>3</index><blowCount>10</blowCount><penetration uom="in">6</penetration></DriveSet></driveSet>
        </DrivenPenetrationTest>
      </procedure>
    </Test>
  </measurement>
  <measurement>
    <Test gml:id="ParticleSize_B-001-0-21_1.5">
      <name>PARTICLE_SIZE</name>
      <samplingFeatureRef xlink:href="#Borehole_B-001-0-21"/>
      <outcome>
        <TestResult gml:id="TR2">
          <location>
            <LinearExtent gml:id="LE2"><gml:posList>1.5</gml:posList></LinearExtent>
          </location>
        </TestResult>
      </outcome>
      <procedure>
        <ParticleSizeTest gml:id="PST1">
          <sieveAnalysis>
            <Grading><particleSize uom="mm">4.75</particleSize><percentPassing uom="%">95</percentPassing></Grading>
            <Grading><particleSize uom="mm">2.0</particleSize><percentPassing uom="%">80</percentPassing></Grading>
            <Grading><particleSize uom="mm">0.425</particleSize><percentPassing uom="%">60</percentPassing></Grading>
            <Grading><particleSize uom="mm">0.075</particleSize><percentPassing uom="%">40</percentPassing></Grading>
          </sieveAnalysis>
        </ParticleSizeTest>
      </procedure>
    </Test>
  </measurement>
  <samplingActivity>
    <SamplingActivity gml:id="SA1">
      <samplingFeatureRef xlink:href="#Borehole_B-001-0-21"/>
      <samplingLocation>
        <LinearExtent gml:id="LE3"><gml:posList>1.5 3.0</gml:posList></LinearExtent>
      </samplingLocation>
      <samplingMethod><Specification gml:id="SP1"><name>SS</name></Specification></samplingMethod>
      <totalSampleRecoveryLength uom="in">18</totalSampleRecoveryLength>
    </SamplingActivity>
  </samplingActivity>
</Diggs>
"""


@pytest.fixture
def hole():
    holes = parse_diggs(DIGGS_FIXTURE)
    assert len(holes) == 1
    return holes[0]


class TestDiggsHeader:
    def test_identity_and_project(self, hole):
        assert hole.boring_id == "B-001-0-21"
        assert hole.project == "600918"
        assert hole.purpose == "Subgrade"
        assert hole.date == "11/8/2021"

    def test_geometry(self, hole):
        assert hole.ground_elevation_ft == pytest.approx(1246.9)
        assert hole.station == "58193.96"
        assert hole.offset_ft == pytest.approx(54.45)
        assert hole.offset_direction == "Lt"
        assert hole.total_depth_ft == pytest.approx(7.5)

    def test_coordinates_lon_lat_order(self, hole):
        # DIGGS pos is lon lat elev; latitude must come out ~40 (Ohio).
        assert hole.latitude == pytest.approx(40.697, abs=1e-3)
        assert hole.longitude == pytest.approx(-82.511, abs=1e-3)

    def test_elevation_at_depth(self, hole):
        assert hole.elevation_at(7.5) == pytest.approx(1239.4)


class TestDiggsSpt:
    def test_spt_parsed(self, hole):
        assert len(hole.spt) == 1
        s = hole.spt[0]
        assert s.depth_ft == pytest.approx(1.5)
        assert [i.blows for i in s.increments] == [12, 14, 10]
        assert s.hammer_type == "90"

    def test_n_value_is_last_two_increments(self, hole):
        # N = 14 + 10 (seating 12 dropped).
        assert hole.spt[0].n_value == 24

    def test_spt_profile_helper(self, hole):
        assert hole.spt_profile() == [(1.5, 24)]
        assert hole.n_at(1.4) == 24

    def test_n60_energy_and_rod_correction(self, hole):
        # 24 * (0.90/0.60) * Cr(1.5 ft -> 0.75) * 1.0 * 1.0 = 27.0
        assert hole.spt[0].n60(0.90) == pytest.approx(27.0)


class TestDiggsGrading:
    def test_grading_parsed(self, hole):
        assert len(hole.grading) == 1
        g = hole.grading[0]
        assert g.depth_ft == pytest.approx(1.5)
        assert len(g.points) == 4

    def test_fines_percent(self, hole):
        assert hole.grading[0].fines_percent == pytest.approx(40.0)

    def test_d50_interpolation(self, hole):
        # 50% passing sits between 0.425 mm (60%) and 0.075 mm (40%);
        # log-linear interpolation gives ~0.18 mm.
        d50 = hole.grading[0].d50
        assert d50 == pytest.approx(0.179, abs=0.01)

    def test_d50_at_helper(self, hole):
        assert hole.d50_at(1.6) == pytest.approx(hole.grading[0].d50)


class TestDiggsSample:
    def test_sample_interval_and_recovery(self, hole):
        assert len(hole.samples) == 1
        s = hole.samples[0]
        assert (s.depth_top_ft, s.depth_bottom_ft) == (1.5, 3.0)
        assert s.method == "SS"
        assert s.recovery_in == pytest.approx(18.0)
        assert s.recovery_percent == pytest.approx(100.0)


class TestScalarModel:
    """Unit behaviour of the dataclasses independent of the parser."""

    def test_spt_refusal_flag(self):
        s = SPTResult(10.0, (DriveIncrement(50, 6), DriveIncrement(50, 2)))
        assert s.refusal is True
        assert s.total_blows == 100

    def test_grading_cu_cc(self):
        pts = (
            GradingPoint(10.0, 100),
            GradingPoint(1.0, 60),
            GradingPoint(0.1, 10),
        )
        g = GradingResult(5.0, pts)
        assert g.d10 == pytest.approx(0.1, abs=1e-9)
        assert g.d60 == pytest.approx(1.0, abs=1e-9)
        assert g.coefficient_of_uniformity == pytest.approx(10.0)

    def test_grading_out_of_range_returns_none(self):
        g = GradingResult(5.0, (GradingPoint(1.0, 40), GradingPoint(0.1, 30)))
        assert g.d50 is None  # 50% finer is above the measured curve
        assert g.percent_passing_at(100.0) is None

    def test_sample_recovery_percent(self):
        s = Sample(0.0, 2.0, "SS", recovery_in=12.0)
        assert s.recovery_percent == pytest.approx(50.0)


def test_pdf_log_rejects_a_file_without_log_sheets(tmp_path):
    pytest.importorskip("fitz")
    f = tmp_path / "log.pdf"
    f.write_bytes(b"%PDF-1.4")
    with pytest.raises(Exception):          # not a readable PDF / no ODOT sheets
        read_pdf_log(f)
