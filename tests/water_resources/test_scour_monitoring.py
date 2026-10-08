#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Scour-monitoring building blocks: precipitation (Atlas 14 / MRMS GRIB2),
StreamStats parsing and workflow, irregular-section normal flow, and the
screening score.  Synthetic inputs only - no network."""

import gzip
import io
import math
import struct
from datetime import datetime

import numpy as np
import pytest

from civilpy.water_resources import cross_section as xs
from civilpy.water_resources import precipitation as pr
from civilpy.water_resources import scour_screening as sc
from civilpy.water_resources import streamstats as ss
from civilpy.water_resources.open_channel import RectangularChannel


# ── helpers ───────────────────────────────────────────────────────────────

def _sm32(v):
    return (1 << 31) | (-v) if v < 0 else v


def _sm16(v):
    return (1 << 15) | (-v) if v < 0 else v


def grib2(values_raw, *, la1, lo1, d, r=0.0, e=0, dd=0, packing=41, nbits=16, scan=0, when=datetime(2025, 4, 5, 12)):
    """Build a GRIB2 message for a regular lat/lon grid of integer codes."""
    ny, nx = values_raw.shape
    s1 = struct.pack(">IBHHBBBHBBBBBBBB", 21, 1, 7, 0, 2, 1, 1, when.year, when.month, when.day,
                     when.hour, when.minute, when.second, 0, 1, 0)[:21]
    la2 = la1 - (ny - 1) * d if not scan & 0x40 else la1 + (ny - 1) * d
    lo2 = lo1 + (nx - 1) * d
    s3 = (struct.pack(">IBBIBBH", 72, 3, 0, nx * ny, 0, 0, 0) + bytes([6]) + bytes(15)
          + struct.pack(">II", nx, ny) + struct.pack(">II", 0, 0xFFFFFFFF)
          + struct.pack(">I", _sm32(round(la1 * 1e6))) + struct.pack(">I", _sm32(round(lo1 * 1e6)))
          + bytes([48]) + struct.pack(">I", _sm32(round(la2 * 1e6))) + struct.pack(">I", _sm32(round(lo2 * 1e6)))
          + struct.pack(">II", round(d * 1e6), round(d * 1e6)) + bytes([scan]))
    assert len(s3) == 72
    s4 = struct.pack(">IBHH", 34, 4, 0, 0) + bytes(25)
    s5 = struct.pack(">IBIH", 21, 5, nx * ny, packing) + struct.pack(">f", r) + struct.pack(
        ">HH", _sm16(e), _sm16(dd)) + bytes([nbits, 0])
    s6 = struct.pack(">IBB", 6, 6, 255)
    if packing == 41:
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(values_raw.astype(np.uint16)).save(buf, format="PNG")
        payload = buf.getvalue()
    else:
        bits = ((values_raw.ravel()[:, None].astype(np.uint64) >> np.arange(nbits - 1, -1, -1, dtype=np.uint64)) & 1)
        payload = np.packbits(bits.astype(np.uint8).ravel()).tobytes()
    s7 = struct.pack(">IB", 5 + len(payload), 7) + payload
    body = s1 + s3 + s4 + s5 + s6 + s7 + b"7777"
    return b"GRIB" + b"\x00\x00" + bytes([0, 2]) + struct.pack(">Q", 16 + len(body)) + body


def atlas_table(scale=1.0):
    """A monotone synthetic Atlas 14 table: depth grows with duration and ARI."""
    return [[round(scale * (0.4 + 0.5 * math.log1p(dur)) * (1 + 0.35 * math.log(ari)), 3)
             for ari in pr.ATLAS14_ARIS_YR] for dur in pr.ATLAS14_DURATIONS_H]


# ── precipitation ─────────────────────────────────────────────────────────

class TestAtlas14:
    def test_parse_pfds_roundtrip(self):
        t = atlas_table()
        text = "result = 'values';\nquantiles = " + str([[f"{v:.3f}" for v in row] for row in t]) + ";\nupper = [];"
        got = pr.parse_pfds(text)
        assert len(got) == len(t)
        for row, want in zip(got, t):
            assert row == pytest.approx(want, abs=1e-3)

    def test_parse_pfds_rejects_wrong_shape(self):
        with pytest.raises(ValueError):
            pr.parse_pfds("quantiles = [['1.0', '2.0']];")

    @pytest.mark.parametrize("dur", [1, 3, 6, 24, 72])
    @pytest.mark.parametrize("ari", [2, 7, 10, 40, 100, 350])
    def test_ari_inverts_depth(self, dur, ari):
        f = pr.PrecipFrequency(40, -83, atlas_table())
        assert f.ari(dur, f.depth(dur, ari)) == pytest.approx(ari, rel=1e-6)

    @pytest.mark.parametrize("dur", [1, 6, 24, 48])
    def test_ari_monotone_in_depth(self, dur):
        f = pr.PrecipFrequency(40, -83, atlas_table())
        depths = np.linspace(0.05, 15, 60)
        aris = [f.ari(dur, d) for d in depths]
        assert all(b >= a for a, b in zip(aris, aris[1:]))
        assert aris[-1] == f.aris_yr[-1]
        assert f.ari(dur, 0) == 0

    @pytest.mark.parametrize("dur", [1, 6, 24])
    def test_areal_factor_raises_ari_of_basin_depth(self, dur):
        f = pr.PrecipFrequency(40, -83, atlas_table())
        d = f.depth(dur, 10)
        assert f.ari(dur, d, areal_factor=0.8) > 10

    def test_interpolated_duration_between_rows(self):
        f = pr.PrecipFrequency(40, -83, atlas_table())
        assert f.depth(6, 10) < f.depth(9, 10) < f.depth(12, 10)

    @pytest.mark.parametrize("dur", [1, 6, 24, 72])
    def test_arf_bounds_and_trends(self, dur):
        areas = [0, 1, 10, 100, 400]
        arf = [pr.areal_reduction_factor(a, dur) for a in areas]
        assert arf[0] == 1.0
        assert all(0 < x <= 1 for x in arf)
        assert all(b < a for a, b in zip(arf, arf[1:]))
        assert pr.areal_reduction_factor(100, dur * 2) > pr.areal_reduction_factor(100, dur)

    def test_dict_roundtrip(self):
        f = pr.PrecipFrequency(40, -83, atlas_table())
        g = pr.PrecipFrequency.from_dict(f.as_dict())
        assert g.depth(24, 25) == pytest.approx(f.depth(24, 25))


class TestGrib2:
    @pytest.mark.parametrize("packing", [41, 0])
    @pytest.mark.parametrize("scan", [0x00, 0x40])
    @pytest.mark.parametrize("shape", [(4, 5), (7, 3)])
    def test_decode_roundtrip(self, packing, scan, shape):
        rng = np.random.default_rng(shape[0] * 10 + shape[1])
        raw = rng.integers(0, 4000, size=shape)
        msg = grib2(raw, la1=41.0, lo1=275.5, d=0.01, r=-3.0, e=0, dd=1, packing=packing, scan=scan)
        g = pr.read_grib2_grid(msg, missing_below=None)
        assert g.shape == shape
        assert g.values == pytest.approx((-3.0 + raw) / 10.0, abs=1e-4)
        assert g.lon0 == pytest.approx(-84.5)
        assert g.north_first == (not scan & 0x40)
        assert g.valid_time == datetime(2025, 4, 5, 12)

    def test_gzip_and_missing(self):
        raw = np.array([[0, 10], [20, 30]])
        msg = gzip.compress(grib2(raw, la1=40.0, lo1=-83.0 + 360, d=0.01, r=-3.0))
        g = pr.read_grib2_grid(msg)
        assert math.isnan(g.values[0, 0])          # -3 = no coverage
        assert g.values[1, 1] == pytest.approx(27.0)

    def test_rejects_non_grib(self):
        with pytest.raises(ValueError):
            pr.read_grib2_grid(b"NOTGRIB" + bytes(40))

    def test_mrms_url(self):
        u = pr.mrms_url(24, datetime(2025, 4, 6, 12))
        assert u.endswith("/CONUS/MultiSensor_QPE_24H_Pass2_00.00/20250406/"
                          "MRMS_MultiSensor_QPE_24H_Pass2_00.00_20250406-120000.grib2.gz")


class TestBasinStats:
    def grid(self):
        vals = np.arange(100, dtype=np.float32).reshape(10, 10)
        return pr.Grid(vals, lat0=40.09, lon0=-83.09, dlat=0.01, dlon=0.01)

    @pytest.mark.parametrize("r0,r1,c0,c1", [(0, 3, 0, 3), (2, 8, 4, 9), (5, 6, 1, 7)])
    def test_box_mean_equals_cells_inside(self, r0, r1, c0, c1):
        g = self.grid()
        n, s = g.lat_of_row(r0) + 0.005, g.lat_of_row(r1) - 0.005
        w, e = g.lon_of_col(c0) - 0.005, g.lon_of_col(c1) + 0.005
        poly = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
        st = g.basin_stats(poly)
        cells = g.values[r0:r1 + 1, c0:c1 + 1]
        assert st["cells"] == cells.size
        assert st["mean"] == pytest.approx(float(cells.mean()))
        assert st["max"] == pytest.approx(float(cells.max()))

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_precomputed_cells_match_basin_stats(self, seed):
        g = self.grid()
        rng = np.random.default_rng(seed)
        cx, cy = -83.05 + rng.uniform(-0.02, 0.02), 40.05 + rng.uniform(-0.02, 0.02)
        ring = [[cx + 0.03 * math.cos(a), cy + 0.02 * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 9)]
        poly = {"type": "MultiPolygon", "coordinates": [[ring]]}
        cells = g.cells_in(poly)
        other = pr.Grid(g.values * 2, g.lat0, g.lon0, g.dlat, g.dlon)
        assert g.stats_at(cells)["mean"] == pytest.approx(g.basin_stats(poly)["mean"])
        assert other.stats_at(cells)["mean"] == pytest.approx(2 * g.basin_stats(poly)["mean"])

    def test_hole_excluded(self):
        g = self.grid()
        outer = [[-83.095, 40.0], [-82.995, 40.0], [-82.995, 40.095], [-83.095, 40.095], [-83.095, 40.0]]
        hole = [[-83.055, 40.035], [-83.035, 40.035], [-83.035, 40.055], [-83.055, 40.055], [-83.055, 40.035]]
        full = g.basin_stats({"type": "Polygon", "coordinates": [outer]})
        holed = g.basin_stats({"type": "Polygon", "coordinates": [outer, hole]})
        assert holed["cells"] < full["cells"]

    def test_sub_cell_basin_falls_back_to_point(self):
        g = self.grid()
        lat, lon = float(g.lat_of_row(4)), float(g.lon_of_col(6))
        tiny = {"type": "Polygon", "coordinates": [[[lon + .001, lat + .001], [lon + .002, lat + .001],
                                                    [lon + .002, lat + .002], [lon + .001, lat + .001]]]}
        st = g.basin_stats(tiny, fallback_point=(lat, lon))
        assert st["cells"] == 0 and st["mean"] == pytest.approx(g.values[4, 6])

    def test_crop_keeps_coordinates(self):
        g = self.grid()
        sub = g.crop(-83.05, 40.0, -83.01, 40.05)
        r, c = sub.index_of(40.03, -83.03)
        assert sub.values[r, c] == g.values[g.index_of(40.03, -83.03)]


# ── StreamStats ───────────────────────────────────────────────────────────

FLOWS = {50.0: 29.3, 20.0: 54.1, 10.0: 74.8, 4.0: 106.0, 2.0: 132.0, 1.0: 160.0, 0.2: 237.0}


class TestStreamStatsParsing:
    @pytest.mark.parametrize("code,aep", [("PK50AEP", 50), ("PK1AEP", 1), ("PK0_2AEP", 0.2),
                                          ("PK0_5AEP", 0.5), ("Q7_10", None), ("", None)])
    def test_aep_of_code(self, code, aep):
        assert ss.aep_of_code(code) == aep

    @pytest.mark.parametrize("aep", list(FLOWS))
    def test_flow_passes_through_table(self, aep):
        assert ss.flow_at_aep(FLOWS, aep) == pytest.approx(FLOWS[aep])

    def test_flow_monotone_and_clamped(self):
        aeps = [60, 50, 30, 20, 7, 4, 3, 1.5, 1, 0.5, 0.2, 0.1]
        q = [ss.flow_at_aep(FLOWS, a) for a in aeps]
        assert all(b >= a for a, b in zip(q, q[1:]))
        assert q[0] == pytest.approx(FLOWS[50.0]) and q[-1] == pytest.approx(FLOWS[0.2])

    @pytest.mark.parametrize("aep", [45, 20, 8, 3, 1.2, 0.4])
    def test_aep_of_flow_inverts(self, aep):
        assert ss.aep_of_flow(FLOWS, ss.flow_at_aep(FLOWS, aep)) == pytest.approx(aep, rel=1e-6)

    def test_empty_flows(self):
        assert ss.flow_at_aep({}, 1) is None and ss.aep_of_flow({}, 10) is None

    def test_parse_delineation_area_is_square_metres(self):
        resp = delineation(area_m2=2 * ss.M2_PER_SQ_MI)
        d = ss.parse_delineation(resp)
        assert d["polygon_area_sq_mi"] == pytest.approx(2.0)
        assert d["outlet"] == (40.0, -83.0) and d["huc"] == "05060001"

    def test_parse_delineation_bad(self):
        with pytest.raises(ss.StreamStatsError):
            ss.parse_delineation({"bcrequest": {}})

    def test_parse_estimate_drops_sentinels_prefers_weighted(self):
        est = [{"regressionRegions": [
            {"code": "A", "name": "Region A", "results": [{"code": "PK1AEP", "value": 100.0}]},
            {"code": "W", "name": "Area-Averaged", "results": [{"code": "PK1AEP", "value": 120.0},
                                                               {"code": "PK2AEP", "value": -99999.0}]}]}]
        flows, used = ss.parse_estimate(est)
        assert flows == {1.0: 120.0} and [u["code"] for u in used] == ["A", "W"]

    @pytest.mark.parametrize("da,span,length,flagged", [
        (0.18, 10, 30, False), (224, 92, 300, False), (1038, 10, 30, True),
        (0.001, 10, 30, True), (0.2, 60, 400, True), (None, 20, 40, True)])
    def test_plausibility(self, da, span, length, flagged):
        assert bool(ss.plausibility(da, span, length)) == flagged


def delineation(area_m2, warning=""):
    return {"bcrequest": {"bcLabels": "*", "wsresp": {"featurecollection": [[
        {"name": "globalwatershedpoint", "feature": {"features": [
            {"geometry": {"type": "Point", "coordinates": [-83.0, 40.0]},
             "properties": {"HUCID": "05060001", "WarningMsg": warning}}]}},
        {"name": "globalwatershed", "feature": {"features": [
            {"geometry": {"type": "Polygon", "coordinates": [[[-83.0, 40.0], [-82.9, 40.0], [-82.9, 40.1],
                                                              [-83.0, 40.0]]]},
             "properties": {"GlobalWshd": 1, "Shape_Area": area_m2, "WarningMsg": warning}}]}}]]}}}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        for key, payload in self.routes.items():
            if key in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected call {url}")


class TestStreamStatsWorkflow:
    def routes(self, area_m2=0.18 * ss.M2_PER_SQ_MI, warning=""):
        return {
            "ss-delineate": delineation(area_m2, warning),
            "regressionregions/bylocation": [{"code": "GC1788"}],
            "scenarios/estimate": [{"regressionRegions": [{"code": "GC1788", "name": "Peak_Flow_Reg_A",
                                                          "results": [{"code": f"PK{str(k).replace('.', '_').replace('_0', '')}AEP",
                                                                       "value": v} for k, v in FLOWS.items()]}]}],
            "nssservices/scenarios": [{"statisticGroupID": 2, "regressionRegions": [
                {"code": "GC1788", "parameters": [{"code": "DRNAREA"}, {"code": "CSL1085LFP"}]}]}],
            "basin-characteristics": [{"code": "DRNAREA", "value": 0.18, "unit": "square miles"},
                                      {"code": "CSL1085LFP", "value": 52.0, "unit": "feet per mi"}],
        }

    def test_full_workflow(self):
        s = FakeSession(self.routes())
        b = ss.delineate_basin(40.0, -83.0, session=s)
        assert b.delineated and b.drainage_area_sq_mi == 0.18
        assert b.peak_flows[1.0] == 160.0 and b.q(1.0) == pytest.approx(160.0)
        assert b.characteristics["CSL1085LFP"]["value"] == 52.0
        assert len(s.calls) == 5

    def test_unsnappable_point_stops_after_delineation(self):
        s = FakeSession(self.routes(area_m2=1100.0, warning=", Point not snappable using ss-pourpoint"))
        b = ss.delineate_basin(40.0, -83.0, session=s)
        assert not b.delineated and b.peak_flows == {} and len(s.calls) == 1


# ── cross section ─────────────────────────────────────────────────────────

class TestIrregularSection:
    @pytest.mark.parametrize("width", [10.0, 40.0])
    @pytest.mark.parametrize("q", [50.0, 500.0, 3000.0])
    @pytest.mark.parametrize("slope", [0.0005, 0.005])
    def test_rectangle_matches_rectangular_channel(self, width, q, slope):
        n = 0.035
        # IrregularSection sorts by station, so the walls get distinct stations
        sec = xs.IrregularSection([0, 1e-9, width - 1e-9, width], [100, 0, 0, 100], n_channel=n)
        y = RectangularChannel(width, n=n, slope=slope).normal_depth(q)
        st = sec.normal_flow(q, slope)
        assert st.depth_ft == pytest.approx(y, rel=2e-3)
        assert st.velocity_fps == pytest.approx(q / (width * st.depth_ft), rel=2e-3)

    @pytest.mark.parametrize("slope", [0.001, 0.01])
    def test_depth_and_velocity_grow_with_flow(self, slope):
        sec = xs.IrregularSection([0, 20, 40, 45, 55, 60, 80, 100], [12, 8, 7, 1, 1, 7, 8, 12],
                                  n_channel=0.035, n_overbank=0.08, bank_stations_ft=(40, 60))
        states = [sec.normal_flow(q, slope) for q in (20, 200, 800, 2000)]
        assert all(b.wse_ft > a.wse_ft for a, b in zip(states, states[1:]))
        assert all(s.channel_velocity_fps >= s.velocity_fps * 0.99 for s in states)

    def test_spills_over_low_end(self):
        sec = xs.IrregularSection([0, 10, 20, 30], [5, 0, 0, 8])
        assert sec.normal_flow(5000, 0.002).spills
        assert not sec.normal_flow(5, 0.002).spills

    def test_bad_inputs(self):
        with pytest.raises(ValueError):
            xs.IrregularSection([0, 1], [1, 0])
        with pytest.raises(ValueError):
            xs.IrregularSection([0, 1, 2], [1, 0, 1]).normal_flow(0, 0.01)


# ── screening ─────────────────────────────────────────────────────────────

class TestScreening:
    @pytest.mark.parametrize("code,clean", [("2-T", "2"), (" a ", "A"), (None, ""), ("VLM-T", "VLM")])
    def test_clean_code(self, code, clean):
        assert sc.clean_code(code) == clean

    def test_hazard_bounds(self):
        assert sc.hazard(None) == 0 and sc.hazard(0.5) == 0 and sc.hazard(1) == 0
        assert sc.hazard(10) == pytest.approx(0.5) and sc.hazard(100) == 1 and sc.hazard(1000) == 1

    @pytest.mark.parametrize("bap03", list(sc.SCOUR_VULNERABILITY) + ["", "AB-T"])
    def test_score_monotone_in_event(self, bap03):
        scores = [sc.screen(sc.ScreeningInput(a, bap02="1", bap03=bap03)).score for a in (0.5, 2, 10, 50, 100, 500)]
        assert all(b >= a for a, b in zip(scores, scores[1:]))
        assert all(0 <= s <= 100 for s in scores)

    @pytest.mark.parametrize("ari", [5, 25, 100])
    def test_score_orders_vulnerability(self, ari):
        order = ["A", "B", "0", "E", "C", "D"]
        scores = [sc.screen(sc.ScreeningInput(ari, bap03=c)).score for c in order]
        assert all(b >= a for a, b in zip(scores, scores[1:]))

    @pytest.mark.parametrize("bap02,ari,expect", [("4", 12, True), ("4", 8, False), ("6", 1.5, True),
                                                  ("1", 60, False), ("0", 500, False), ("4-T", 30, True)])
    def test_overtopping_band(self, bap02, ari, expect):
        assert sc.screen(sc.ScreeningInput(ari, bap02=bap02, bap03="A")).overtopping_likely is expect

    def test_terrain_overtopping_and_velocity_raise_score(self):
        base = sc.ScreeningInput(20, bap02="1", bap03="B")
        s0 = sc.screen(base).score
        wet = sc.screen(sc.ScreeningInput(20, bap02="1", bap03="B", wse_ft=101, road_low_ft=100))
        fast = sc.screen(sc.ScreeningInput(20, bap02="1", bap03="B", channel_velocity_fps=9,
                                           critical_velocity_fps=3))
        assert wet.overtopping_likely and wet.score > s0 and fast.score > s0

    @pytest.mark.parametrize("hw,q_over,expect", [(99.0, 0.0, False), (100.4, 120.0, True), (100.0, 0.0, True)])
    def test_culvert_headwater_decides_overtopping(self, hw, q_over, expect):
        """A culvert's headwater replaces the open-channel water surface, either way."""
        r = sc.screen(sc.ScreeningInput(20, bap02="1", bap03="B", wse_ft=95.0 if expect else 105.0, road_low_ft=100,
                                        culvert_headwater_ft=hw, culvert_overtopping_cfs=q_over))
        assert r.overtopping_likely is expect
        assert any(x.startswith("culvert: headwater") for x in r.reasons)
        assert not any(x.startswith("terrain: water surface") for x in r.reasons)

    @pytest.mark.parametrize("v_out", [2.0, 6.0, 12.0])
    def test_culvert_outlet_velocity_counts(self, v_out):
        base = sc.screen(sc.ScreeningInput(20, bap03="B", channel_velocity_fps=2.0, critical_velocity_fps=3.0))
        r = sc.screen(sc.ScreeningInput(20, bap03="B", channel_velocity_fps=2.0, critical_velocity_fps=3.0,
                                        culvert_outlet_velocity_fps=v_out))
        assert (r.score > base.score) == (v_out > 3.0)
        assert r.score >= base.score

    def test_poor_scour_condition_overrides_stable_appraisal(self):
        a = sc.screen(sc.ScreeningInput(50, bap03="A", bc11="9"))
        b = sc.screen(sc.ScreeningInput(50, bap03="A", bc11="3"))
        assert b.vulnerability == 1.0 and b.score > a.score and b.tier == "inspect"

    @pytest.mark.parametrize("ari,bap03,tier", [(1, "D", "none"), (100, "D", "inspect"), (100, "A", "none"),
                                               (30, "0", "watch")])
    def test_tiers(self, ari, bap03, tier):
        assert sc.screen(sc.ScreeningInput(ari, bap03=bap03)).tier == tier
