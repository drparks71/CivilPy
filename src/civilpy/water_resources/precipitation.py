#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Observed rainfall (NOAA MRMS) against precipitation frequency (NOAA Atlas 14).

* :class:`PrecipFrequency` - the Atlas 14 partial-duration depth table at a
  point (19 durations x 10 average recurrence intervals), from the NOAA
  HDSC Precipitation Frequency Data Server, and the inverse lookup
  :meth:`PrecipFrequency.ari` (depth -> return period, log-log interpolation).
* :func:`areal_reduction_factor` - TP-29 depth-area curves (Leclerc & Schaake
  1972 fit) to compare a basin-average depth with the point frequency.
* :func:`read_grib2_grid` - a minimal GRIB2 reader for one regular lat/lon
  field with PNG packing (Grid Definition Template 3.0, Data Representation
  Template 5.41) - what every MRMS QPE product is - so no eccodes / GDAL GRIB
  plugin is needed.  :class:`Grid` gives basin averages
  (:meth:`Grid.basin_stats`).
* :func:`mrms_url` / :func:`fetch_mrms` - the public NOAA MRMS archive on AWS
  (``noaa-mrms-pds``, October 2020 onward).

Depths are inches; MRMS QPE values arrive in millimetres and are converted.
"""

from __future__ import annotations

import ast
import gzip
import io
import math
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

MM_PER_IN = 25.4

#: Atlas 14 PFDS table rows (durations, hours) and columns (ARI, years).
ATLAS14_DURATIONS_H = (5 / 60, 10 / 60, 15 / 60, 30 / 60, 1, 2, 3, 6, 12, 24,
                       48, 72, 96, 168, 240, 480, 720, 1080, 1440)
ATLAS14_ARIS_YR = (1, 2, 5, 10, 25, 50, 100, 200, 500, 1000)

PFDS_URL = "https://hdsc.nws.noaa.gov/cgi-bin/new/cgi_readH5.py"
MRMS_BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"

#: MRMS multi-sensor QPE accumulations (Pass 2 = gauge-corrected, ~1 h latency).
MRMS_QPE_PRODUCTS = {1: "MultiSensor_QPE_01H_Pass2", 3: "MultiSensor_QPE_03H_Pass2",
                     6: "MultiSensor_QPE_06H_Pass2", 12: "MultiSensor_QPE_12H_Pass2",
                     24: "MultiSensor_QPE_24H_Pass2", 48: "MultiSensor_QPE_48H_Pass2",
                     72: "MultiSensor_QPE_72H_Pass2"}


# ── precipitation frequency ───────────────────────────────────────────────

@dataclass
class PrecipFrequency:
    """Atlas 14 partial-duration depths at a point: ``depths_in[d][a]`` for
    ``durations_h[d]`` and ``aris_yr[a]``."""
    lat: float
    lon: float
    depths_in: list
    durations_h: tuple = ATLAS14_DURATIONS_H
    aris_yr: tuple = ATLAS14_ARIS_YR

    def depth(self, duration_h: float, ari_yr: float) -> float:
        """Point depth (in) for a duration and ARI, log-log interpolated."""
        row = self._row(duration_h)
        return float(math.exp(np.interp(math.log(ari_yr), np.log(self.aris_yr), np.log(row))))

    def ari(self, duration_h: float, depth_in: float, *, areal_factor: float = 1.0) -> float:
        """Average recurrence interval (years) of ``depth_in`` falling in
        ``duration_h``.  ``areal_factor`` (<= 1) scales the point depths
        down for a basin average (:func:`areal_reduction_factor`).  Depths
        below the 1-year depth return a value under 1 (proportional, a
        "nothing unusual" marker); above the 1000-year depth return 1000."""
        if depth_in is None or depth_in <= 0:
            return 0.0
        row = np.asarray(self._row(duration_h), float) * areal_factor
        if depth_in <= row[0]:
            return float(depth_in / row[0])
        if depth_in >= row[-1]:
            return float(self.aris_yr[-1])
        return float(math.exp(np.interp(math.log(depth_in), np.log(row), np.log(self.aris_yr))))

    def _row(self, duration_h):
        durs = np.asarray(self.durations_h, float)
        i = int(np.argmin(np.abs(np.log(durs) - math.log(duration_h))))
        if not math.isclose(durs[i], duration_h, rel_tol=0.02):
            # between tabulated durations: interpolate each ARI column in log-log
            lo = int(np.searchsorted(durs, duration_h)) - 1
            lo = min(max(lo, 0), len(durs) - 2)
            t = (math.log(duration_h) - math.log(durs[lo])) / (math.log(durs[lo + 1]) - math.log(durs[lo]))
            a, b = np.log(self.depths_in[lo]), np.log(self.depths_in[lo + 1])
            return list(np.exp(a + t * (b - a)))
        return list(self.depths_in[i])

    def as_dict(self):
        return {"lat": self.lat, "lon": self.lon, "durations_h": list(self.durations_h),
                "aris_yr": list(self.aris_yr), "depths_in": self.depths_in}

    @classmethod
    def from_dict(cls, d):
        return cls(d["lat"], d["lon"], d["depths_in"], tuple(d["durations_h"]), tuple(d["aris_yr"]))


def parse_pfds(text: str) -> list:
    """The ``quantiles`` table from a PFDS ``cgi_readH5.py`` response:
    [[depth per ARI] per duration] as floats."""
    m = re.search(r"quantiles\s*=\s*(\[\[.*?\]\])\s*;", text, re.S)
    if not m:
        raise ValueError("no quantiles table in the PFDS response")
    rows = [[float(v) for v in row] for row in ast.literal_eval(m.group(1))]
    if len(rows) != len(ATLAS14_DURATIONS_H) or any(len(r) != len(ATLAS14_ARIS_YR) for r in rows):
        raise ValueError(f"unexpected PFDS table shape {len(rows)} x {len(rows[0]) if rows else 0}")
    return rows


def fetch_atlas14(lat: float, lon: float, *, session=None, timeout=60) -> PrecipFrequency:
    """Atlas 14 partial-duration depths (English units) at a point."""
    import requests

    s = session or requests
    r = s.get(PFDS_URL, params={"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "type": "pf",
                                "data": "depth", "units": "english", "series": "pds"}, timeout=timeout)
    r.raise_for_status()
    return PrecipFrequency(lat, lon, parse_pfds(r.text))


def areal_reduction_factor(area_sq_mi: float, duration_h: float) -> float:
    """TP-29 areal reduction factor, Leclerc & Schaake (1972) fit:
    ``1 - exp(-1.1 t^0.25) + exp(-1.1 t^0.25 - 0.01 A)`` (t hours, A mi^2).
    1.0 at zero area, falling with area, less reduction for long storms."""
    if area_sq_mi <= 0:
        return 1.0
    k = -1.1 * duration_h ** 0.25
    return float(1.0 - math.exp(k) + math.exp(k - 0.01 * area_sq_mi))


# ── GRIB2 (MRMS) ──────────────────────────────────────────────────────────

def _sm(value: int, bits: int) -> int:
    """GRIB sign-magnitude integer -> int."""
    sign = value >> (bits - 1)
    mag = value & ((1 << (bits - 1)) - 1)
    return -mag if sign else mag


@dataclass
class Grid:
    """A regular lat/lon field.  ``values[row, col]``; row 0 is ``lat0``
    (the north edge for MRMS), latitude steps by ``-dlat`` per row when
    ``north_first``; ``lon0`` is the first column, -180..180."""
    values: np.ndarray
    lat0: float
    lon0: float
    dlat: float
    dlon: float
    north_first: bool = True
    valid_time: datetime | None = None
    meta: dict = field(default_factory=dict)

    @property
    def shape(self):
        return self.values.shape

    def lat_of_row(self, rows):
        rows = np.asarray(rows)
        return self.lat0 - rows * self.dlat if self.north_first else self.lat0 + rows * self.dlat

    def lon_of_col(self, cols):
        return self.lon0 + np.asarray(cols) * self.dlon

    def index_of(self, lat, lon):
        r = (self.lat0 - lat) / self.dlat if self.north_first else (lat - self.lat0) / self.dlat
        return int(round(r)), int(round((lon - self.lon0) / self.dlon))

    def crop(self, west, south, east, north) -> "Grid":
        """Sub-grid covering the box (cells whose centres fall inside)."""
        r_n, c_w = self.index_of(north, west)
        r_s, c_e = self.index_of(south, east)
        r0, r1 = sorted((r_n, r_s))
        r0, c_w = max(r0, 0), max(c_w, 0)
        r1, c_e = min(r1, self.shape[0] - 1), min(c_e, self.shape[1] - 1)
        sub = self.values[r0:r1 + 1, c_w:c_e + 1].copy()
        return Grid(sub, float(self.lat_of_row(r0)), float(self.lon_of_col(c_w)), self.dlat, self.dlon,
                    self.north_first, self.valid_time, dict(self.meta))

    def value_at(self, lat, lon):
        r, c = self.index_of(lat, lon)
        if 0 <= r < self.shape[0] and 0 <= c < self.shape[1]:
            return float(self.values[r, c])
        return float("nan")

    def basin_stats(self, geojson_geometry: dict, *, fallback_point=None) -> dict:
        """Mean and max of the cells whose centres fall in a GeoJSON Polygon /
        MultiPolygon (lon/lat), ignoring NaN.  A basin smaller than a cell
        (no centre inside) takes the cell under ``fallback_point`` (lat, lon)
        or under the polygon's first vertex."""
        from matplotlib.path import Path as MplPath

        polys = _polygons(geojson_geometry)
        xs = [x for p in polys for ring in p for x, _ in ring]
        ys = [y for p in polys for ring in p for _, y in ring]
        sub = self.crop(min(xs) - self.dlon, min(ys) - self.dlat, max(xs) + self.dlon, max(ys) + self.dlat)
        rr, cc = np.mgrid[0:sub.shape[0], 0:sub.shape[1]]
        pts = np.column_stack([sub.lon_of_col(cc.ravel()), sub.lat_of_row(rr.ravel())])
        inside = np.zeros(len(pts), bool)
        for p in polys:
            m = MplPath(np.asarray(p[0])).contains_points(pts)
            for hole in p[1:]:
                m &= ~MplPath(np.asarray(hole)).contains_points(pts)
            inside |= m
        vals = sub.values.ravel()[inside]
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            lat, lon = fallback_point or (ys[0], xs[0])
            v = self.value_at(lat, lon)
            return {"mean": v, "max": v, "cells": 0}
        return {"mean": float(vals.mean()), "max": float(vals.max()), "cells": int(len(vals))}


def _polygons(geom: dict):
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return list(geom["coordinates"])
    if t == "Feature":
        return _polygons(geom["geometry"])
    raise ValueError(f"not a polygon geometry: {t}")


def read_grib2_grid(data: bytes, *, missing_below: float | None = 0.0) -> Grid:
    """First field of a GRIB2 message: regular lat/lon grid (template 3.0),
    PNG packing (5.41) or simple packing (5.0), no bitmap.  Values under
    ``missing_below`` (MRMS uses -3 / -999 for no coverage) become NaN.
    Gzip input is accepted."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data[:4] != b"GRIB" or data[7] != 2:
        raise ValueError("not a GRIB edition 2 message")
    i, end = 16, struct.unpack(">Q", data[8:16])[0]
    grid = rep = None
    when = None
    while i < end - 4 and data[i:i + 4] != b"7777":
        length, num = struct.unpack(">I", data[i:i + 4])[0], data[i + 4]
        sec = data[i:i + length]
        if num == 1:
            y, mo, d, h, mi, s = struct.unpack(">HBBBBB", sec[12:19])
            when = datetime(y, mo, d, h, mi, s)
        elif num == 3:
            tmpl = struct.unpack(">H", sec[12:14])[0]
            if tmpl != 0:
                raise ValueError(f"grid template 3.{tmpl} not supported (regular lat/lon 3.0 only)")
            nx, ny = struct.unpack(">II", sec[30:38])
            la1, lo1 = (_sm(v, 32) / 1e6 for v in struct.unpack(">II", sec[46:54]))
            la2, lo2 = (_sm(v, 32) / 1e6 for v in struct.unpack(">II", sec[55:63]))
            di, dj = (v / 1e6 for v in struct.unpack(">II", sec[63:71]))
            scan = sec[71]
            grid = dict(nx=nx, ny=ny, la1=la1, lo1=lo1, la2=la2, lo2=lo2, di=di, dj=dj, scan=scan)
        elif num == 5:
            tmpl = struct.unpack(">H", sec[9:11])[0]
            r = struct.unpack(">f", sec[11:15])[0]
            e = _sm(struct.unpack(">H", sec[15:17])[0], 16)
            dd = _sm(struct.unpack(">H", sec[17:19])[0], 16)
            rep = dict(tmpl=tmpl, r=r, e=e, d=dd, nbits=sec[19])
        elif num == 6:
            if sec[5] != 255:
                raise ValueError("GRIB2 bitmaps are not supported")
        elif num == 7:
            if grid is None or rep is None:
                raise ValueError("data section before grid / representation sections")
            raw = _unpack(sec[5:], rep, grid["nx"] * grid["ny"])
            vals = (rep["r"] + raw * 2.0 ** rep["e"]) / 10.0 ** rep["d"]
            vals = vals.reshape(grid["ny"], grid["nx"]).astype(np.float32)
            if missing_below is not None:
                vals[vals < missing_below] = np.nan
            if grid["scan"] & 0x80:
                raise ValueError("GRIB2 -i scanning not supported")
            north_first = not (grid["scan"] & 0x40)
            lon0 = grid["lo1"] - 360.0 if grid["lo1"] > 180 else grid["lo1"]
            return Grid(vals, grid["la1"], lon0, grid["dj"], grid["di"], north_first, when,
                        {"lat_last": grid["la2"], "packing": rep["tmpl"]})
        i += length
    raise ValueError("no data section in the GRIB2 message")


def _unpack(payload: bytes, rep: dict, n: int) -> np.ndarray:
    if rep["tmpl"] == 41:
        from PIL import Image

        img = Image.open(io.BytesIO(payload))
        a = np.asarray(img)
        if a.ndim != 2 or a.size != n:
            raise ValueError(f"PNG payload {a.shape} does not match {n} grid points")
        return a.astype(np.float64).ravel()
    if rep["tmpl"] == 0:
        nbits = rep["nbits"]
        if nbits == 0:
            return np.zeros(n)
        bits = np.unpackbits(np.frombuffer(payload, np.uint8))[: n * nbits].reshape(n, nbits)
        return (bits.astype(np.uint64) << np.arange(nbits - 1, -1, -1, dtype=np.uint64)).sum(axis=1).astype(np.float64)
    raise ValueError(f"data representation template 5.{rep['tmpl']} not supported (5.0 / 5.41 only)")


def mrms_url(duration_h: int, valid: datetime, *, product: str | None = None) -> str:
    """Archive URL of an MRMS QPE accumulation ending at ``valid`` (UTC, on the hour)."""
    p = product or MRMS_QPE_PRODUCTS[duration_h]
    day, stamp = valid.strftime("%Y%m%d"), valid.strftime("%Y%m%d-%H%M%S")
    return f"{MRMS_BUCKET}/CONUS/{p}_00.00/{day}/MRMS_{p}_00.00_{stamp}.grib2.gz"


def fetch_mrms(duration_h: int, valid: datetime, *, session=None, timeout=120) -> Grid:
    """Download and decode one MRMS QPE accumulation; values in inches."""
    import requests

    s = session or requests
    r = s.get(mrms_url(duration_h, valid), timeout=timeout)
    r.raise_for_status()
    g = read_grib2_grid(r.content)
    g.values = g.values / MM_PER_IN
    g.meta["duration_h"] = duration_h
    g.meta["units"] = "in"
    return g
