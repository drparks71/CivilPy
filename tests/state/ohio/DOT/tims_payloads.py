#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Canned ODOT TIMS payloads for the TIMS tests -- no network.

Shapes follow what the ArcGIS REST endpoints really return: a MapServer
layer ``?f=json`` metadata document, ``/query`` feature sets
(``{"features": [{"attributes": {...}}]}``), the ``f=html`` id listing the
legacy ``gis.dot.state.oh.us`` scraper walks, and the ``?f=pjson`` single
feature (``{"feature": {"attributes": {...}}}``). The attribute key lists
are the full column sets the legacy ``TimsBridge`` / ``Project`` records
read, so a builder here produces a row those constructors accept.
"""

from __future__ import annotations

import json

# every TIMS Bridge Inventory column the legacy TimsBridge record reads
BRIDGE_KEYS = (
    'OBJECTID', 'SFN', 'STR_LOC_CARRIED', 'RTE_ON_BRG_CD', 'DISTRICT',
    'COUNTY_CD', 'INVENT_SPCL_DSGT', 'FIPS_CD', 'INVENT_ON_UND_CD',
    'INVENT_HWY_SYS_CD', 'INVENT_HWY_DSGT_CD', 'INVENT_DIR_SFX_CD',
    'INVENT_FEAT', 'STR_LOC', 'LATITUDE_DD', 'LONGITUDE_DD', 'BRDR_BRG_STATE',
    'BRDR_BRG_PCT_RESP', 'BRDR_BRG_SFN', 'MAIN_STR_MTL_CD',
    'MAIN_STR_TYPE_CD', 'APPRH_STR_MTL_CD', 'APPRH_STR_TYPE_CD', 'MAIN_SPANS',
    'APPRH_SPANS', 'DECK_CD', 'DECK_PROT_EXTL_CD', 'DECK_PROT_INT_CD',
    'WEAR_SURF_DT', 'WEARING_SURF_CD', 'WEARING_SURF_THCK', 'PAINT_DT',
    'YR_BUILT', 'MAJ_RECON_DT', 'TYPE_SERV1_CD', 'TYPE_SERV2_CD', 'LANES_ON',
    'LANES_UND', 'INVENT_RTE_ADT', 'BYPASS_LEN', 'NBIS_LEN_SW',
    'INVENT_NHS_CD', 'FUNC_CLAS_CD', 'DFNS_HWY_DSGT_SW', 'PARALLEL_STR_CD',
    'DIR_TRAFFIC_CD', 'TEMP_STR_SW', 'DSGT_NATL_NETW_SW', 'TOLL_CD',
    'ROUTINE_RESP_CD', 'ROUTINE_RESP_CD_2', 'MAINT_RESP_CD',
    'MAINT_RESP_CD_2', 'INSP_RESP_CD', 'INSP_RESP_CD_2', 'HIST_SGN_CD',
    'NAV_CONTROL_SW', 'NAV_VRT_CLR', 'NAV_HORIZ_CLR', 'SUBS_FENDERS',
    'MIN_NAV_VRT_CLR', 'INSP_DT', 'DSGT_INSP_FREQ', 'FRAC_CRIT_INSP_SW',
    'FRACCRIT_INSP_FREQ', 'FRAC_CRIT_INSP_DT', 'DIVE_INSP_SW',
    'DIVE_INSP_FREQ', 'DIVE_INSP_DT', 'SPCL_INSP_SW', 'SPCL_INSP_FREQ',
    'SPCL_INSP_DT', 'SNOOPER_INSP_SW', 'DECK_SUMMARY', 'DECK_WEAR_SURF',
    'DECK_EXPN_JOINTS', 'SUPS_SUMMARY', 'PAINT', 'SUBS_SUMMARY',
    'CHAN_SUMMARY', 'SUBS_SCOUR', 'CULVERT_SUMMARY', 'GEN_APPRAISAL',
    'DESIGN_LOAD_CD', 'RAT_OPR_LOAD_FACT', 'RAT_INV_LOAD_CD',
    'RAT_INV_LOAD_FACT', 'GEN_OPR_STATUS', 'BRG_POSTING', 'CALC_STR_EVAL',
    'CALC_DECK_GEOM', 'CALC_UNDC', 'WW_ADEQUACY_CD', 'APPRH_ALGN_CD',
    'SURVEY_RAILING', 'SURVEY_TRANSITION', 'SURVEY_GUARDRAIL',
    'SURVEY_RAIL_ENDS', 'SCOUR_CRIT_CD', 'MAX_SPAN_LEN', 'OVRL_STR_LEN',
    'SIDW_WD_L', 'SIDW_WD_R', 'BRG_RDW_WD', 'DECK_WD', 'APPRH_RDW_WD',
    'MEDIAN_CD', 'SKEW_DEG', 'FLARED_SW', 'MIN_HORIZ_CLR_C',
    'MINVRT_UNDCLR_C', 'IMPR_TYP_WORK_CD', 'IMPR_TYP_MEANS_CD', 'IMPR_LNG',
    'IMPR_BRG_COST', 'IMPR_RDW_COST', 'IMPR_TOT_PROJ_COST',
    'IMPR_COST_EST_YR', 'FUTURE_ADT', 'FUTURE_ADT_YR', 'DEDICATED_NME',
    'INVENT_PREF_RTE', 'MAJOR_BRG_SW', 'INVENT_COUNTY', 'SEISMIC_SUSCEPT_CD',
    'GASB_34_SW', 'APERTURE_FABR_SW', 'APERTURE_ORIG_SW', 'APERTURE_REP_SW',
    'ORIG_PROJ_NBR', 'STD_DRW_NBR', 'MICROFILM_NBR', 'REMARKS',
    'UTL_ELECTRIC_SW', 'UTL_GAS_SW', 'UTL_SEWER_SW', 'NBIS_BRIDGE_LENGTH',
    'RTE_UND_BRG_CD', 'LOAD_RAT_PCT', 'LOAD_RAT_YR', 'RATING_SOFT_CD',
    'CATWALKS_SW', 'RETIRE_REASON_CD', 'REC_ADD_DT', 'MPO_CD',
    'TEMP_SUBDECKING_SW', 'APPRH_SLAB_SW', 'MEDIAN_TYP1_CD', 'MEDIAN_TYP2_CD',
    'MEDIAN_TYP3_CD', 'RAILING_TYP_CD', 'COMPOSITE_STR_CD',
    'ELAS_STRP_TROU2_SW', 'ELAS_STRP_TROU3_SW', 'FENCING_SW',
    'GLARE_SCREEN_SW', 'NOISE_BARRIER_SW', 'DECK_AREA', 'CURB_SIDW_MTL_L',
    'CURB_SIDW_MTL_R', 'CURB_SIDW_TYP_L', 'CURB_SIDW_TYP_R', 'HINGE_CD',
    'DECK_DRN_CD', 'DECK_CONC_TYP_CD', 'EXPN_JOINT1_CD', 'EXPN_JOINT2_CD',
    'EXPN_JOINT3_CD', 'HORIZ_CRV_RADIUS', 'BEARING_DEVICE1_CD',
    'BEARING_DEVICE2_CD', 'FRAMING_TYP_CD', 'HAUNCH_GIRD_SW',
    'LONG_MEMB_TYP_CD', 'MAIN_MEM_CD', 'STR_STEEL_PROT_CD',
    'PRED_STR_STEEL_TYP', 'PAINT_SURFACE_AREA', 'STR_STEEL_PAINT_CD',
    'POST_TENSION_SW', 'ABUT_FWD_TYP_CD', 'ABUT_FWD_MATL_CD', 'ABUT_FWD_CD',
    'ABUT_REAR_TYP_CD', 'ABUT_REAR_MATL_CD', 'ABUT_REAR_CD',
    'PRED_PIER_TYP_CD', 'PRED_PIER_MATL_CD', 'PIER_PRED_CD', 'PIER_1_TYP_CD',
    'PIER_1_MATL_CD', 'PIER_OTH1_CD', 'SLOPE_PROT_TYP_CD', 'CULVERT_TYP_CD',
    'CULVERT_LEN', 'CULVERT_FILL_DEPTH', 'SCENIC_WATERWAY_SW',
    'CHAN_PROT_TYPE_CD', 'STREAM_VELOCITY', 'HIST_TYP_CD', 'HIST_BUILDER_CD',
    'SUFF_RATING', 'DEFIC_FUNC_RATING', 'MAIN_STR_DESCR_CD',
    'APPRH_STR_DESCR_CD', 'HIST_BUILD_YR', 'NLFID', 'CTL_BEGIN_NBR',
    'ROUTE_TYPE', 'ROUTE_NBR', 'ROUTE_SUFFIX', 'ROUTINE_INSP_DUE',
    'FRAC_CRIT_INSP_DUE', 'DIVE_INSP_DUE', 'SPCL_INSP_DUE', 'BIA_REPORT',
    'STATE_ROUTE_BR_PHOTOS', 'JURISDICTION', 'DIVIDED_HWY', 'ACCESS_CONTROL',
    'URBAN_AREA_CODE', 'BASE_TYPE', 'FUNCTIONAL_CLASS', 'HPMS_SAMPLE_ID',
    'LANES', 'MAINTENANCE_AUTHORITY', 'NHS', 'PRIORITY_SYSTEM',
    'SURFACE_TYPE', 'SURFACE_WIDTH', 'ESAL_TOTAL', 'PAVE_TYPE', 'PCR_YEAR',
    'ROADWAY_WIDTH_NBR', 'created_user', 'created_date', 'last_edited_user',
    'last_edited_date',
)

# every TIMS Projects column the legacy Project record reads
PROJECT_KEYS = (
    'ObjectID', 'GIS_ID', 'PID_NBR', 'DISTRICT_NBR', 'LOCALE_SHORT_NME',
    'COUNTY_NME', 'PROJECT_NME', 'CONTRACT_TYPE', 'PRIMARY_FUND_CATEGORY_TXT',
    'PROJECT_MANAGER_NME', 'RESERVOIR_YEAR', 'TIER', 'ODOT_LETTING',
    'SCHEDULE_TYPE_SHORT_NME', 'ENV_PROJECT_MANAGER_NME', 'AREA_ENGINEER_NME',
    'PROJECT_ENGINEER_NME', 'DESIGN_AGENCY', 'SPONSORING_AGENCY',
    'PDP_SHORT_NAME', 'PRIMARY_WORK_CATEGORY', 'PROJECT_STATUS',
    'FISCAL_YEAR', 'INHOUSE_DESIGN_FULL_NME', 'EST_TOTAL_CONSTR_COST',
    'STATE_PROJECT_NBR', 'CONSTR_VENDOR_NME', 'STIP_FLAG',
    'CURRENT_STIP_CO_AMT', 'PROJECT_PLANS_URL', 'PROJECT_ADDENDA_URL',
    'PROJECT_PROPOSAL_URL', 'FMIS_PROJ_DESC', 'AWARD_MILESTONE_DT',
    'BEGIN_CONSTR_MILESTONE_DT', 'END_CONSTR_MILESTONE_DT', 'OPEN_TRAFFIC_DT',
    'CENTRAL_OFFICE_CLOSE_DT', 'SOURCE_LAST_UPDATED', 'COD_LAST_UPDATED',
    'PRESERV_FUNDS_IND', 'MAJOR_BRG_FUNDS_IND', 'MAJOR_NEW_FUNDS_IND',
    'MAJOR_REHAB_FUNDS_IND', 'MPO_FUNDS_IND', 'SAFETY_FUNDS_IND',
    'LOCAL_FUNDS_IND', 'OTHER_FUNDS_IND', 'NLF_ID', 'CTL_BEGIN', 'CTL_END',
    'GIS_FEATURE_TYPE', 'ROUTE_TYPE', 'ROUTE_ID', 'STRUCTURE_FILE_NBR',
    'MAIN_STRUCTURE_TYPE', 'SUFFICIENCY_RATING', 'OVRL_STRUCTURE_LENGTH',
    'DECK_AREA', 'DECK_WIDTH', 'FEATURE_INTERSECT', 'YEAR_BUILT',
    'LONGITUDE_BEGIN_NBR', 'LATITUDE_BEGIN_NBR', 'LONGITUDE_END_NBR',
    'LATITUDE_END_NBR', 'COUNTY_CD_WORK_LOCATION', 'COUNTY_NME_WORK_LOCATION',
    'DISTRICT_WORK_LOCATION', 'PAVEMENT_TREATMENT_TYPE',
    'PAVEMENT_TREATMENT_CATEGORY', 'created_user', 'created_date',
    'last_edited_user', 'last_edited_date',
)

# a real-looking row: SFN 2102374, I-71 NB over TR 105 (Plumb Rd), Delaware Co.
BRIDGE_ROW_OVERRIDES = {
    "OBJECTID": 12345,
    "SFN": "2102374",
    "STR_LOC_CARRIED": "I-71 NB",
    "DISTRICT": "06",
    "COUNTY_CD": "DEL",
    "INVENT_ON_UND_CD": "1",
    "INVENT_FEAT": "TR 105 (PLUMB RD.)",
    "LATITUDE_DD": 40.209175,
    "LONGITUDE_DD": -82.930444,
    "MAIN_STR_MTL_CD": "4",
    "MAIN_STR_TYPE_CD": "02",
    "YR_BUILT": -331516800000,          # 1959-07-01 in epoch ms (pre-1970)
    "LANES_ON": 3,
    "SUFF_RATING": 84.3,
    "DECK_SUMMARY": "6",
    "SUPS_SUMMARY": "7",
    "SUBS_SUMMARY": "6",
    "NLFID": "SDELIR00071**C",
    "ROUTE_TYPE": "IR",
    "ROUTE_NBR": "00071",
    "MAX_SPAN_LEN": 35.0,
    "DESIGN_LOAD_CD": "6",
}

PROJECT_ROW_OVERRIDES = {
    "ObjectID": 777,
    "GIS_ID": "P-96213-1",
    "PID_NBR": 96213,
    "DISTRICT_NBR": 6,
    "COUNTY_NME": "DELAWARE",
    "PROJECT_NME": "DEL-71-12.34",
    "STRUCTURE_FILE_NBR": "2102374",
    "LATITUDE_BEGIN_NBR": 40.2091,
    "LONGITUDE_BEGIN_NBR": -82.9304,
}


def bridge_attributes(**overrides) -> dict:
    """A full Bridge Inventory attribute row (every key the legacy record reads)."""
    row = {k: None for k in BRIDGE_KEYS}
    row.update(BRIDGE_ROW_OVERRIDES)
    row.update(overrides)
    return row


def project_attributes(**overrides) -> dict:
    """A full Projects-layer attribute row."""
    row = {k: None for k in PROJECT_KEYS}
    row.update(PROJECT_ROW_OVERRIDES)
    row.update(overrides)
    return row


def feature_set(rows) -> dict:
    """``/query?f=json`` response: ``{"features": [{"attributes": row}, ...]}``."""
    return {"features": [{"attributes": dict(r)} for r in rows]}


def arcgis_error(code=400, message="Unable to complete operation.") -> dict:
    return {"error": {"code": code, "message": message, "details": []}}


def layer_metadata(fields) -> dict:
    """The MapServer layer ``?f=json`` document (only what get_tims_data reads)."""
    return {"id": 0, "name": "Bridge Inventory", "maxRecordCount": 1000,
            "fields": [{"name": f, "type": "esriFieldTypeString"} for f in fields]}


def html_id_listing(hrefs) -> bytes:
    """The ``f=html`` id listing the gis.dot.state.oh.us scraper reads: a page
    of ``<a href="/arcgis/rest/services/.../5/123">123</a>`` links, with the
    usual breadcrumb links before them (the scraper takes the LAST anchor)."""
    anchors = ['<a href="/arcgis/rest/services">Services</a>',
               '<a href="/arcgis/rest/services/TIMS/Assets/MapServer">Assets</a>']
    anchors += [f'<a href="{h}">{h.rsplit("/", 1)[-1]}</a>' for h in hrefs]
    return ("<html><body><div class='restBody'>" + "<br/>".join(anchors)
            + "</div></body></html>").encode()


def pjson_feature(attributes) -> bytes:
    return json.dumps({"feature": {"attributes": attributes, "geometry": {}}}).encode()
