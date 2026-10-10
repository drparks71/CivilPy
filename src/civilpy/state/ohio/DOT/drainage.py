#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""ODOT Location & Design Manual Volume 2 (Drainage Design) - the rules a
bridge or culvert hydraulics screen has to follow, as functions.

Edition: **July 2026** (``LD2_EDITION``).  LD2 is re-issued every January
and July; the section numbers below are cited so a later edition can be
checked against them (``manage.py ld2_check`` in SNBI_UI does the probe).

* :func:`design_aep` - the hydraulic design flood by road class (1004.2);
* :func:`scour_floods` - the scour design / check floods for that design
  flood (Table 1008-1);
* :func:`flood_clearance` - the 1004.1 clearances;
* :func:`culvert_headwater_controls` - the design- and check-storm
  headwater limits for Type A conduits (1006.2);
* :func:`rcp_type` - rock channel protection at a bridge by channel mean
  velocity (Table 1107-2);
* :func:`taf_standard_discharge` - the Temporary Access Fill flow (1010);
* :func:`water_quality_volume` - WQv for post-construction BMPs (1111.4);
* :func:`file_number_kind` - SFN vs CFN by opening (1002.2.5);
* :func:`conduit_end_of_life` - the GA rating that ends a conduit's service
  life (1002.2.2);
* :func:`floodplain_documents` - what the ODOT self-compliance process
  needs in each FEMA zone (1005.1.3 / 1005.1.4), and
  :func:`flood_hazard_evaluation_required` (1005.2.1);
* :func:`hh_model_extent_ft` - how far the H&H model reaches (Table 1107-1)
  and :func:`prefer_2d` (C1107.2.1).
"""

from __future__ import annotations

from dataclasses import dataclass

LD2_EDITION = "July 2026"
LD2_URL = "https://dam.assets.ohio.gov/image/upload/transportation.ohio.gov/hydraulic/ld2/archive/2026-07-LD2.pdf"

#: AEP (percent) <-> recurrence interval (years), 1004.1.
AEP_TO_RI = {50.0: 2, 20.0: 5, 10.0: 10, 4.0: 25, 2.0: 50, 1.0: 100, 0.2: 500}

#: Functional classification codes that are interstates, freeways or
#: expressways: SNBI B.H.01 (FHWA 2013 classes 1 Interstate, 2 Other Freeway
#: or Expressway) and the legacy NBI item 26 codes 01 / 11 and 02 / 12.
FREEWAY_CLASSES = {"1", "2", "11", "12"}


def is_freeway_class(func_class) -> bool:
    code = str(func_class or "").strip().lstrip("0")
    return code in FREEWAY_CLASSES

#: Table 1008-1: hydraulic design flood -> (scour design flood, scour check flood), AEP percent.
SCOUR_FLOODS = {10.0: (4.0, 2.0), 4.0: (2.0, 1.0), 2.0: (1.0, 0.2)}


@dataclass
class DesignFlood:
    aep_pct: float
    road_class: str          # how the class was decided
    basis: str               # LD2 citation
    scour_design_pct: float
    scour_check_pct: float

    @property
    def recurrence_yr(self) -> int:
        return AEP_TO_RI[self.aep_pct]


def design_aep(func_class=None, aadt=None, *, freeway: bool | None = None, ramp: bool = False,
               bikeway: bool = False) -> DesignFlood:
    """The hydraulic design flood, 1004.2: interstates, freeways and
    expressways 2 %; other highways with 3,000 ADT or more and freeway ramps
    4 %; other highways under 3,000 ADT 10 %; bicycle pathways 20 % (unless
    OHE approves otherwise).  ``func_class`` is the FHWA code (B.H.01);
    ``freeway`` overrides it; an unknown class with unknown ADT is treated as
    an other highway of 3,000 ADT or more (the conservative 4 %)."""
    if bikeway:
        return _flood(20.0, "bicycle pathway", "1004.2 (*unless approved by OHE)")
    is_fwy = freeway if freeway is not None else is_freeway_class(func_class)
    if is_fwy:
        return _flood(2.0, "interstate / freeway / expressway", "1004.2; 23 CFR 650.115(a)(2)")
    if ramp:
        return _flood(4.0, "freeway ramp", "1004.2")
    try:
        adt = float(aadt) if aadt is not None else None
    except (TypeError, ValueError):
        adt = None
    if adt is not None and adt < 3000:
        return _flood(10.0, f"other highway, {adt:,.0f} ADT (under 3,000)", "1004.2")
    label = f"other highway, {adt:,.0f} ADT (3,000 and over)" if adt is not None else \
        "other highway, ADT unknown (assumed 3,000 and over)"
    return _flood(4.0, label, "1004.2")


def _flood(aep, road_class, basis):
    d, c = scour_floods(aep)
    return DesignFlood(aep, road_class, basis, d, c)


def scour_floods(design_aep_pct: float) -> tuple:
    """(scour design flood, scour check flood) in AEP percent for a hydraulic
    design flood, Table 1008-1.  A design flood rarer than the table (bikeway
    20 %) is rounded to the nearest row."""
    key = min(SCOUR_FLOODS, key=lambda k: abs(k - design_aep_pct))
    return SCOUR_FLOODS[key]


def flood_clearance(design_wse_ft: float, *, travelled_way_low_ft: float | None = None,
                    low_chord_ft: float | None = None) -> dict:
    """1004.1: on a new crossing the low edge of the travelled way clears the
    design water surface by 3 ft and the bridge low chord clears it.  Returns
    the margins (ft) and whether each is met; None where the elevation is
    not known."""
    out = {"design_wse_ft": design_wse_ft, "basis": "1004.1"}
    if travelled_way_low_ft is not None:
        m = travelled_way_low_ft - design_wse_ft
        out.update(travelled_way_margin_ft=round(m, 2), travelled_way_ok=m >= 3.0, travelled_way_required_ft=3.0)
    if low_chord_ft is not None:
        m = low_chord_ft - design_wse_ft
        out.update(low_chord_margin_ft=round(m, 2), low_chord_ok=m >= 0.0)
    return out


def culvert_headwater_controls(*, pavement_low_edge_ft: float, inlet_crown_ft: float, drainage_area_acres: float,
                               deep_ravine: bool = False, bikeway: bool = False, rise_ft: float | None = None,
                               occupied_building_ground_ft: float | None = None) -> dict:
    """Allowable headwater elevations for a Type A conduit, 1006.2.  Design
    storm: the lowest of (A) 2 ft below the near low pavement edge for 1,000
    acres and more, 1 ft below under 1,000 acres (bikeways 1 ft), (B) 2 ft
    above the inlet crown, or (C) 4 ft above it in a deep ravine (B and C
    are secondary; 1006.2.3).  Check storm: 2 ft below the ground at an
    occupied building for the 2 % storm; the 1 % headwater depth at most
    twice the rise (1006.2.2)."""
    below = 1.0 if (bikeway or drainage_area_acres < 1000) else 2.0
    a = pavement_low_edge_ft - below
    crown = inlet_crown_ft + (4.0 if deep_ravine else 2.0)
    out = {"design": {"A_pavement_ft": round(a, 2), "BC_crown_ft": round(crown, 2),
                      "allowable_ft": round(min(a, crown), 2), "controls": "A" if a <= crown else ("C" if deep_ravine else "B"),
                      "basis": "1006.2.1"},
           "check": {"basis": "1006.2.2"}}
    if occupied_building_ground_ft is not None:
        out["check"]["building_2pct_ft"] = round(occupied_building_ground_ft - 2.0, 2)
    if rise_ft is not None:
        out["check"]["max_1pct_depth_ft"] = round(2.0 * rise_ft, 2)
    return out


def rcp_type(channel_mean_velocity_fps: float) -> dict:
    """Rock channel protection at a bridge from the channel mean velocity at
    the scour design flood, Table 1107-2; contact OHE above 12 fps."""
    v = float(channel_mean_velocity_fps)
    if v <= 8.0:
        t, thick = "C", 24
    elif v <= 10.0:
        t, thick = "B", 30
    else:
        t, thick = "A", 36
    return {"type": t, "thickness_in": thick, "velocity_fps": round(v, 2), "basis": "1107.3 Table 1107-2",
            "contact_ohe": v > 12.0}


def taf_standard_discharge(drainage_area_sq_mi: float, *, max_mean_monthly_cfs: float | None = None) -> dict:
    """Temporary Access Fill, 1010: the Standard Temporary Discharge is twice
    the largest mean monthly flow; without StreamStats monthly flows the
    March mean Q = 2.01 A^1.01 (A in sq mi) stands in.  A hydraulic analysis
    is required when the STD is 10 cfs or more; 2D is suggested above 100
    sq mi or with controlling features."""
    a = float(drainage_area_sq_mi)
    if max_mean_monthly_cfs is not None:
        qm, source = float(max_mean_monthly_cfs), "StreamStats maximum mean monthly flow"
    else:
        qm, source = 2.01 * a ** 1.01, "Q_Mar = 2.01 A^1.01 (no StreamStats monthly flows)"
    std = 2.0 * qm
    return {"max_mean_monthly_cfs": round(qm, 1), "standard_temporary_discharge_cfs": round(std, 1),
            "source": source, "analysis_required": std >= 10.0, "suggest_2d": a > 100.0, "basis": "1010.1"}


def water_quality_volume(drainage_area_acres: float, impervious_fraction: float, *, precip_in: float = 0.90) -> dict:
    """WQv (acre-ft) = Rv P A / 12 with Rv = 0.05 + 0.9 i, P = 0.90 in, 1111.4.
    Existing ODOT right-of-way counts as impervious."""
    i = min(max(float(impervious_fraction), 0.0), 1.0)
    rv = 0.05 + 0.9 * i
    wqv = rv * precip_in * float(drainage_area_acres) / 12.0
    return {"rv": round(rv, 3), "wqv_acre_ft": round(wqv, 4), "wqv_cu_ft": round(wqv * 43560.0, 0), "basis": "1111.4"}


def large_river(drainage_area_sq_mi: float | None, stream_order: int | None) -> bool:
    """C1111.3: a large river drains over 100 sq mi or is fourth order or
    greater - discharging to one waives water-quantity treatment."""
    return bool((drainage_area_sq_mi or 0) > 100.0 or (stream_order or 0) >= 4)


def file_number_kind(opening_ft: float | None) -> str | None:
    """1002.2.5: an opening of 10 ft or more along the roadway centreline
    needs a Structure File Number; 12 in to under 120 in a Culvert File
    Number; smaller needs neither."""
    if opening_ft is None:
        return None
    if opening_ft >= 10.0:
        return "SFN"
    if opening_ft >= 1.0:
        return "CFN"
    return None


CONDUIT_SERVICE_LIFE_YR = 75
CONDUIT_END_OF_LIFE_GA = 4


def conduit_end_of_life(general_appraisal) -> bool | None:
    """1002.2.2: a conduit has reached the end of its service life when its
    General Appraisal rating is 4 (plan rehabilitation or replacement)."""
    try:
        ga = int(general_appraisal)
    except (TypeError, ValueError):
        return None
    return ga <= CONDUIT_END_OF_LIFE_GA


# ── floodplains (1005) ────────────────────────────────────────────────────

EXEMPT_WORK = ("bridge painting",
               "deck or superstructure replacement where the existing low chord has freeboard over the BFE "
               "plus the allowable surcharge",
               "bridge or culvert maintenance that does not change the alignment, grade or hydraulic capacity "
               "(District Hydraulic Engineer decides)")


def floodplain_documents(zone: str, *, floodway: bool, exempt: bool = False) -> dict:
    """The ODOT self-compliance paperwork for work in a FEMA zone, 1005.1.3 /
    1005.1.4: the letters (Appendix B forms LD-50..53), the calculations and
    who is coordinated with.  ``zone`` is the FEMA zone at the crossing
    (A, AE, A1-A30, X ...)."""
    z = (zone or "").strip().upper()
    detailed = z == "AE" or (z.startswith("A") and z[1:].isdigit())
    sfha = z.startswith("A") or z.startswith("V")
    base = {"zone": z or "unmapped", "basis": "1005.1.4", "surcharge_ft": 1.0,
            "surcharge_note": "NFIP allows 1.0 ft; the Local Floodplain Coordinator may allow less (1005.1.1)"}
    if not sfha:
        return dict(base, documents=[], coordination=[], note="outside the SFHA: no floodplain self-compliance "
                                                                 "documentation; a Flood Hazard Evaluation still applies (1005.2.1)")
    if exempt:
        return dict(base, basis="1005.1.3", documents=["LD-53 Letter of Notification of SFHA Exemption"],
                    coordination=["Local Floodplain Coordinator (copy to the project file)"],
                    note="exempt work: " + "; ".join(EXEMPT_WORK))
    docs = ["LD-52 Letter of Notification", "LD-51 Letter of Compliance (note any variance from local standards)"]
    coord = ["Local Floodplain Coordinator (early, for local standards stricter than FEMA)"]
    if not detailed:
        docs.append("calculations demonstrating the stream's carrying capacity is maintained")
        return dict(base, documents=docs, coordination=coord,
                    note="Zone A: no BFE established; surcharge limited to the local requirement or 1 ft, whichever is less")
    docs.append("hydrologic and hydraulic calculations")
    coord += ["FEMA", "ODNR Floodplain Management Program"]
    if floodway:
        docs.append("LD-50 No-Rise Certification (if applicable)")
        return dict(base, documents=docs, coordination=coord, surcharge_ft=0.0,
                    note="Zone AE with a floodway: span the floodway if feasible; any rise above the BFE in the "
                         "floodway needs a variance and a CLOMR / LOMR (1005.1.2, 1006.4)")
    return dict(base, documents=docs, coordination=coord,
                note="Zone AE without a floodway: the cumulative rise may not exceed BFE + the allowable surcharge; "
                     "more needs a variance and a CLOMR / LOMR (1005.1.2)")


def flood_hazard_evaluation_required(zone: str, *, minimum_size_culvert: bool = False) -> bool:
    """1005.2.1: a Flood Hazard Evaluation (design and 1 % water surfaces,
    inundation limits, upstream impacts) is required for every watercourse
    except FEMA Zones A / AE / A1-A30 and culverts sized only to the minimum."""
    z = (zone or "").strip().upper()
    detailed_or_a = z == "A" or z == "AE" or (z.startswith("A") and z[1:].isdigit())
    return not (detailed_or_a or minimum_size_culvert)


def fis_discharge_governs(in_fis_reach: bool) -> str | None:
    """1003.1.2: in a Flood Insurance Study reach the FIS base discharge Q1 %
    takes precedence over every calculated discharge."""
    return ("the FIS Q1% governs over the StreamStats estimate for the waterway opening (1003.1.2)"
            if in_fis_reach else None)


# ── the H&H model (1107.2) ────────────────────────────────────────────────

def hh_model_extent_ft(two_d: bool, floodplain_width_ft: float | None = None) -> float:
    """Table 1107-1: cross sections 500 ft up- and downstream for a 1D model;
    500 ft or twice the floodplain width, whichever is greater, for 2D."""
    if two_d and floodplain_width_ft:
        return max(500.0, 2.0 * float(floodplain_width_ft))
    return 500.0


def prefer_2d(drainage_area_sq_mi: float | None, *, wide_floodplain: bool = False, split_flow: bool = False,
              skewed: bool = False, pressure_flow: bool = False, in_sfha: bool = False) -> dict:
    """C1107.2.1: 2D (SRH-2D) for drainage areas over 100 sq mi [Che 2022]
    and where 1D cannot describe the flow; FEMA Region 5 does not accept 2D
    for map revisions unless the effective model was 2D."""
    reasons = []
    if (drainage_area_sq_mi or 0) > 100.0:
        reasons.append("drainage area over 100 sq mi")
    for flag, why in ((wide_floodplain, "wide floodplain with overbank flow"), (split_flow, "split flows / multiple openings"),
                      (skewed, "abutments skewed to the flow"), (pressure_flow, "pressure flow at the design storm")):
        if flag:
            reasons.append(why)
    out = {"two_d": bool(reasons), "reasons": reasons, "software": "Aquaveo SMS / SRH-2D", "basis": "C1107.2.1"}
    if in_sfha:
        out["fema_note"] = ("FEMA Region 5 will not accept 2D modelling for an SFHA map revision unless the current "
                            "effective model is 2D: keep a 1D HEC-RAS duplicate-effective model for the no-rise / CLOMR")
    return out
