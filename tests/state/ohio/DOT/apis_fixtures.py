#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Canned payload builders for the ``apis`` tests.

Shapes mirror what the live services return: ArcGIS ``/query`` feature
sets (TIMS, NHDPlus HR), Bentley AssetWise ``{"success", "data"}``
envelopes, Midas Civil ``{"NODE": {"1": {...}}}`` tables, USGS StreamStats
and NWIS JSON. Values are a plausible Delaware County SR 3 crossing;
nothing is pulled from a live system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


def epoch_ms(year: int, month: int = 1, day: int = 1) -> int:
    """Milliseconds since the Unix epoch, the way ArcGIS serialises dates."""
    return int((datetime(year, month, day) - datetime(1970, 1, 1)).total_seconds() * 1000)


# --- TIMS Bridge Inventory ---------------------------------------------------

TIMS_SFN = "2102226"

TIMS_RECORD: Dict[str, Any] = {
    "OBJECTID": 4821,
    "SFN": TIMS_SFN,
    "LATITUDE_DD": 40.182,
    "LONGITUDE_DD": -82.949,
    "COUNTY_CD": "DEL",
    "DISTRICT": "06",
    "STR_LOC_CARRIED": "SR 3",
    "STR_LOC": "ALUM CREEK",
    "YR_BUILT": epoch_ms(2005),
    "MAIN_STR_MTL_CD": "3",
    "MAIN_STR_TYPE_CD": "02",
    "TOTAL_SPANS": 3,
    "MAX_SPAN_LEN": 85.0,
    "OVRL_STR_LEN": 240.5,
    "DECK_WD": 44.0,
    "BRG_RDW_WD": 40.0,
    "DECK_AREA": 10582.0,
    "SKEW_DEG": 15,
    "LANES_ON": 2,
    "LANES_UND": 0,
    "INVENT_RTE_ADT": 12500,
    "FUTURE_ADT": 15800,
    "DECK_SUMMARY": "7",
    "SUPS_SUMMARY": "6",
    "SUBS_SUMMARY": "7",
    "CULVERT_SUMMARY": "N",
    "CHAN_SUMMARY": "8",
    "SCOUR_CRIT_CD": "8",
    "SUFF_RATING": "82.4",
    "RAT_INV_LOAD_FACT": "1.12",
    "RAT_OPR_LOAD_FACT": "1.45",
    "DESIGN_LOAD_CD": "6",
    "OWNER_CD": "01",
    "MAINT_RESP_CD": "01",
    "FUNC_CLAS_CD": "03",
    "INVENT_NHS_CD": "1",
    "BYPASS_LEN": "5",
    "FRAC_CRIT_INSP_SW": "N",
    "DIVE_INSP_SW": "Y",
    "MIN_VRT_CLR_BRG": 99.99,
    "APPRH_RDW_WD": "40",
    "DRN_AREA": "188.5",
    "STREAM_VELOCITY": "4.2",
    "WW_ADEQUACY_CD": "8",
}


def tims_record(**overrides) -> Dict[str, Any]:
    rec = dict(TIMS_RECORD)
    rec.update(overrides)
    return rec


def arcgis_features(*records: Dict[str, Any], geometry: bool = True) -> Dict[str, Any]:
    """Wrap attribute dicts the way an ArcGIS ``/query?f=json`` call does."""
    feats: List[Dict[str, Any]] = []
    for rec in records:
        feat: Dict[str, Any] = {"attributes": dict(rec)}
        if geometry:
            feat["geometry"] = {"x": rec.get("LONGITUDE_DD", -82.9),
                                "y": rec.get("LATITUDE_DD", 40.1)}
        feats.append(feat)
    return {
        "displayFieldName": "SFN",
        "fieldAliases": {},
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 4326},
        "features": feats,
    }


def nhd_flowline(name: str = "Alum Creek", order: int = 4, **extra) -> Dict[str, Any]:
    rec = {"GNIS_Name": name, "FType": 460, "FCode": 46006, "StreamOrder": order,
           "LengthKm": 1.84, "Permanent_Identifier": "140001234"}
    rec.update(extra)
    return rec


# --- Bentley AssetWise --------------------------------------------------------

def aw_assets(as_id: int = 555, sfn: str = TIMS_SFN) -> Dict[str, Any]:
    return {"success": True, "message": None,
            "data": [{"as_id": as_id, "as_code": sfn, "as_name": "SR 3 over Alum Creek"}]}


def aw_current_values() -> Dict[str, Any]:
    return {"success": True, "data": [
        {"fe_id": 101, "cv_value": "DEL"},
        {"fe_id": 102, "cv_value": None, "value": "2005"},
        {"fe_id": 103, "cv_value": None, "value": None, "va_value": "7"},
        {"cv_value": "orphan without fe_id"},
    ]}


def aw_reports() -> Dict[str, Any]:
    return {"success": True, "data": [
        {"rp_id": 9001, "rp_date": "2022-06-01T00:00:00"},
        {"rp_id": 9007, "rp_date": "2024-06-15T00:00:00"},
        {"rp_id": 9004, "rp_date": "2023-06-10T00:00:00"},
    ]}


def aw_elements() -> List[Dict[str, Any]]:
    return [
        {"se_display_id": "12", "se_name": "Re Conc Deck", "totalQuantity": 10582,
         "state1": 10000, "state2": 500, "state3": 82, "state4": 0},
        {"se_display_id": "107", "se_name": "Steel Open Girder", "totalQuantity": 720,
         "state1": 700, "state2": 20, "state3": 0, "state4": 0},
    ]


# --- Midas Civil ---------------------------------------------------------------

def midas_tables() -> Dict[str, Dict[str, Any]]:
    """Endpoint path -> payload for a 3-node, 3-element toy model."""
    return {
        "/civil/db/node": {"NODE": {
            "1": {"X": 0.0, "Y": 0.0, "Z": 0.0},
            "2": {"X": 3.0, "Y": 4.0, "Z": 12.0},
            "3": {"X": 10.0, "Y": 0.0, "Z": 0.0},
        }},
        "/civil/db/matl": {"MATL": {
            "1": {"NAME": "Concrete 4.5ksi", "TYPE": "CONC", "ELAST": 3824.0,
                  "POISN": 0.2, "THERMAL": 6e-6, "DENSITY": 0.150},
            "2": {"NAME": "A709 Gr50", "TYPE": "STEEL"},
        }},
        "/civil/db/sect": {"SECT": {
            "1": {"NAME": "W36x150", "SHAPE": "I", "AREA": 44.3, "IYY": 9040.0, "IZZ": 270.0},
            "2": {"NAME": "Deck Strip"},
        }},
        "/civil/db/elem": {"ELEM": {
            "1": {"TYPE": "BEAM", "MATL": 2, "SECT": 1, "NODE": [1, 2]},
            "2": {"TYPE": "TRUSS", "MATL": 2, "iNODE": "2", "jNODE": "3"},
            "3": {"TYPE": "WEIRD", "NODE": [3]},
        }},
        "/civil/db/cons": {"CONS": {
            "1": {"DX": 1, "DY": 1, "DZ": 1, "RX": 0, "RY": 0, "RZ": 0},
            "3": {"DX": 0, "DY": 1, "DZ": 1},
            "42": {"DZ": 1},
        }},
        "/civil/db/stld": {"STLD": {
            "1": {"NAME": "DC", "DESC": "Self weight", "TYPE": "D"},
            "2": {"NAME": "DW", "DESC": "Wearing surface"},
        }},
        "/civil/db/mvld": {"MVLD": {
            "1": {"LCNAME": "HL-93", "DESC": "Design truck + lane"},
        }},
    }


# --- USGS ---------------------------------------------------------------------

def streamstats_payload() -> Dict[str, Any]:
    return {
        "workspaceID": "OH20261003120000000000",
        "parameters": [
            {"ID": 1, "name": "Drainage Area", "code": "DRNAREA", "value": 188.5,
             "unit": "square miles"},
            {"ID": 2, "name": "Stream Slope 10-85", "code": "CSL10_85", "value": 12.3},
            {"ID": 3, "name": "Mean Annual Precip", "code": "PRECIP", "value": None},
        ],
        "flowStatistics": [{
            "StatisticGroupName": "Peak-Flow Statistics",
            "regressionEquations": [{
                "flowStatistics": [
                    {"statisticGroupName": "PK2", "value": 4200.0},
                    {"statisticGroupName": "PK100", "value": 12400.0},
                    {"statisticGroupName": "PK500", "value": None},
                ],
            }],
        }],
        "globalwatershed": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[]]}},
        ]},
    }


def nwis_iv_payload() -> Dict[str, Any]:
    def series(code, values, name="Alum Creek at Columbus OH"):
        return {
            "sourceInfo": {"siteName": name, "siteCode": [{"value": "03229000"}]},
            "variable": {"variableCode": [{"value": code}]},
            "values": [{"value": values}],
        }
    return {"value": {"timeSeries": [
        series("00060", [{"value": "312", "dateTime": "2026-10-03T08:00:00.000-04:00"},
                         {"value": "325", "dateTime": "2026-10-03T08:15:00.000-04:00"}]),
        series("00065", [{"value": "3.41", "dateTime": "2026-10-03T08:15:00.000-04:00"}]),
    ]}}


# --- SNBI ----------------------------------------------------------------------

SNBI_ALL_CODES = ["BID01", "BL01", "BL02", "BL05", "BL06", "BCL01", "BCL02", "BG01", "BG05",
                  "BG06", "BG09", "BLR04", "BLR05", "BLR06", "BLR07", "BC01", "BC02", "BC03",
                  "BC09", "BC11", "BAP03", "BW01", "BIE02", "BIE05", "BIE06", "BF01", "BPS01"]


def snbi_record(**overrides) -> Dict[str, Any]:
    """A complete SNBI record (every 'all'-scope field populated)."""
    rec = {code: "x" for code in SNBI_ALL_CODES}
    rec.update({
        "BID01": TIMS_SFN, "BL01": "39", "BL02": "041", "BL05": 40.182, "BL06": -82.949,
        "BCL01": "01", "BCL02": "01", "BG01": 240.5, "BG05": 44.0, "BG06": 40.0, "BG09": 40.0,
        "BLR04": "3", "BLR05": 1.12, "BLR06": 1.45, "BLR07": 1.3,
        "BC01": "7", "BC02": "6", "BC03": "7", "BC09": "8", "BC11": "8", "BAP03": "8",
        "BW01": 2005, "BIE02": "20240615", "BIE05": "24", "BIE06": "20990615",
        "BF01": "W", "BPS01": "A",
    })
    rec.update(overrides)
    return rec
