#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""
SNBI (Specifications for the National Bridge Inventory) data-validation models.

These Pydantic models implement the FHWA SNBI data validation rules as published
in the FHWA "SNBI Data Validation Rules" workbook. They are intentionally
*generic* (national) rather than Ohio-specific: any valid SNBI submission for any
State should validate.

Mapping of the workbook's severity levels onto Pydantic:

* ``Critical`` / ``Error`` objective data-quality checks (data type, length,
  numeric magnitude, character set, date format, enumerated value, and the
  cross-field consistency checks) are enforced and raise ``ValidationError``.
* Fields the workbook marks "must be reported for all bridges" are required;
  fields that are conditionally required ("...when B.F.01 begins with H...") or
  only ``Flag``-level when missing are optional but still range/format-checked
  when a value is present.
* ``Flag``-only advisories that depend on engineering judgement (e.g. latitude
  polarity hints, "FHWA prefers a name") are not raised.

Checks that reference external SNBI code tables not contained in the workbook
(owner codes, span material/type codes, element numbers in Table 22, railing
codes in Table 6, etc.) are enforced as data-type/length checks only; their
allowed-value lists are noted in comments. Enumerations the workbook spells out
inline ARE enforced. ``State Code`` (B.L.01) is validated against civilpy's
``NBIS_state_codes`` table.

Several items are FHWA-calculated and must NOT be reported (B.G.16 Calculated
Deck Area, B.C.12 Bridge Condition Classification, B.C.13 Lowest Condition
Rating, B.IE.06 Inspection Due Date) -- supplying a value for these raises.
"""

import re
from datetime import datetime
from typing import Optional, List, Annotated

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from civilpy.state.ohio.DOT.TIMS import state_code_conversion

# ---------------------------------------------------------------------------
# Shared constants / helpers
# ---------------------------------------------------------------------------

# Condition-rating valid values (B.C.01-B.C.11, B.C.14, B.C.15): 0 through 9 and N
_COND_RATINGS = {str(n) for n in range(10)} | {"N"}

# Character sets defined inline in the workbook (data format checks)
_CHARSET_BID = r"^[A-Za-z0-9 .*&_()+\-]+$"          # B.ID.01 / B.ID.03 / B.H.18
_CHARSET_BORDER = r"^[A-Za-z0-9 .*&_()+/\-]+$"       # B.L.07 (adds /)
_CHARSET_ROUTE_NUM = r"^[A-Za-z0-9 .*&_()|+\-]+$"    # B.RT.02 (adds |)
_CHARSET_ALNUM = r"^[A-Za-z0-9]+$"                   # B.IE.04
_CHARSET_NOTE = r"^[A-Za-z0-9 .*&_()+/\-]+$"         # B.IE.11
_CHARSET_LOAD_CFG = r"^[A-Za-z0-9\-]+$"              # B.EP.01

# Strings that the workbook treats as "no value reported"
_EMPTY = {None, "", "0"}


def _require_date(value, item):
    """Validate an 8-digit YYYYMMDD value that is also a real calendar date."""
    if value is None:
        return value
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{8}", text):
        raise ValueError(f"{item} must be numeric in YYYYMMDD format")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        raise ValueError(f"{item} is not a valid calendar date (YYYYMMDD)")
    return text


def _require_in(value, allowed, item):
    """Validate that a (stripped) value is within an enumerated set, if present."""
    if value is None:
        return value
    text = str(value).strip()
    if text not in allowed:
        raise ValueError(
            f"{item} value {text!r} is not valid; allowed values: "
            f"{', '.join(sorted(allowed))}"
        )
    return text


def _require_charset(value, pattern, item):
    if value is None:
        return value
    if not re.fullmatch(pattern, str(value)):
        raise ValueError(f"{item} contains invalid characters")
    return value


def _one_decimal(value, item):
    """Validate that a numeric value carries at most one decimal place.

    The SNBI workbook requires several measurements to be "numeric with one
    decimal place" (e.g. B.G.15, B.H.16). Float storage cannot distinguish
    ``12`` from ``12.0``, so this enforces the practical constraint: no more
    than one fractional digit (12.5 ok, 12.55 rejected).
    """
    if value is None:
        return value
    if abs(round(float(value), 1) - float(value)) > 1e-9:
        raise ValueError(f"{item} must be numeric with one decimal place")
    return value


def _is_valid_state_or_country(text):
    """True if ``text`` is a valid SNBI State code or the border countries MX/CA."""
    upper = str(text).strip().upper()
    if upper in {"MX", "CA"}:
        return True
    try:
        state_code_conversion(f"{int(upper):02d}")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# SNBI coded-value tables (FHWA SNBI, March 2022 publication). Base codes only;
# the helpers below also accept any "<base>-T" transition-period value (valid
# 2026-2027), which is not in the March 2022 publication but appears in the
# data during the transition window.
# ---------------------------------------------------------------------------

def _seq(prefix, lo, hi):
    """{'P01','P02',...}: ``prefix`` + zero-padded width-2 numbers lo..hi."""
    return {f"{prefix}{n:02d}" for n in range(lo, hi + 1)}


# Owner / Maintenance Responsibility share one table (B.CL.01 / B.CL.02).
_AGENCY = (
    {"S01", "S02", "S03", "SX"}
    | {"L01", "L02", "L03", "L04", "L05", "LX"}
    | _seq("F", 1, 9) | {"FX"}
    | {"FL01", "FL02", "FL03", "FL04", "FL05", "FL06", "FL07", "FL0X"}
    | {"I"} | _seq("D", 1, 5) | {"DX"}
    | {"T", "P", "R", "U", "X"}
)

# Federal/Tribal Land Access (B.CL.03) — pipe-delimited multi-value.
_LAND_ACCESS = {"N", "BIA", "BLM", "NPS", "USACE", "USBR", "USFS", "USFWS", "X"}

_SNBI_CODES = {
    # Classification
    "BCL01": _AGENCY,
    "BCL02": _AGENCY,
    # Geometry
    "BG12": {"CU", "CP", "CK", "N"},
    # Loads / load rating
    "BLR01": {"H10", "H15", "H20", "HS15", "HS20", "HS20M", "HS20Plus",
              "HL93", "HL93Plus", "RR", "U", "X"},
    "BLR02": {"ASD", "LFD", "LRFD", "U", "X"},
    "BLR04": {"LFR", "ASR", "LRFR", "LT", "AR", "EJ", "N"},
    # Inspection
    "BIE01": {str(n) for n in range(1, 10)},
    # Features
    "BF02": {"C", "A", "B", "T", "L"},
    "BH01": {str(n) for n in range(1, 8)},
    "BRR01": {"F", "FE", "P", "PE", "M", "ME", "I"},
    # Routes
    "BRT03": {"NB", "EB", "SB", "WB", "NS", "EW"},
    # Posting status (B.PS.01, Table 15) & posting type (B.EP.03)
    "BPS01": {"N", "PO", "PA", "PP", "PR", "PD", "PM",
              "TO", "TA", "TP", "TR", "TD", "TM",
              "SO", "SA", "SP", "SR", "SD", "SM", "C"},
    "BEP03": {"G", "A", "D", "T", "C", "S", "L", "V", "X"},
    # Span sets
    "BSP04": ({"A01", "CX", "FX", "I01", "I02", "M01", "M02", "P01", "PX",
               "SX", "TX", "X"} | _seq("C", 1, 5) | _seq("F", 1, 3)
              | _seq("S", 1, 5) | _seq("T", 1, 4)),
    "BSP06": (_seq("A", 1, 5) | _seq("B", 1, 4) | _seq("F", 1, 4)
              | _seq("G", 1, 10) | {"GX"} | _seq("L", 1, 3) | {"LX"}
              | _seq("M", 1, 3) | {"MX", "P01", "P02", "S01", "S02"}
              | _seq("T", 1, 3) | _seq("X", 1, 3) | {"X"}),
    "BSP07": ({"0"} | _seq("A", 1, 5) | {"AX"} | _seq("C", 1, 4) | {"CX"}
              | {"E01", "EX"} | _seq("M", 1, 3) | {"MU", "MX", "P01",
              "S01", "S02", "SX", "T01", "U", "X"}),
    "BSP08": {"CS", "CU", "IM", "NC"},
    "BSP09": ({"0", "A01", "CX", "FX", "SX", "TX", "X"} | _seq("C", 1, 5)
              | _seq("F", 1, 3) | _seq("S", 1, 5) | _seq("T", 1, 4)),
    "BSP10": ({"0", "B01", "CX", "CU", "E01", "P01", "P02", "PX", "S01",
               "T01", "X"} | _seq("C", 1, 7)),
    "BSP11": ({"0"} | _seq("A", 1, 5) | {"AX"} | _seq("C", 1, 3) | {"CX"}
              | _seq("M", 1, 3) | {"MU", "MX", "P01", "X"}),
    "BSP12": ({"0"} | _seq("C", 1, 3) | {"CX"} | _seq("R", 1, 7) | {"RX"}
              | {"S01", "S02", "SX", "X"}),
    "BSP13": {"0", "C01", "C02", "F01", "M01", "T01", "X"},
    # Substructure sets
    "BSB03": ({"0", "A01", "CX", "E01", "FX", "I01", "I02", "M01", "M02",
               "P01", "PX", "SX", "TX", "X"} | _seq("C", 1, 5)
              | _seq("F", 1, 3) | _seq("S", 1, 6) | _seq("T", 1, 4)),
    "BSB04": ({"0", "AX", "BX", "PX", "U", "X"} | _seq("A", 1, 12)
              | _seq("B", 1, 4) | _seq("P", 1, 8)),
    "BSB05": ({"0"} | _seq("A", 1, 5) | {"AX"} | _seq("C", 1, 3) | {"CX"}
              | {"E01", "EX", "P01", "S01", "S02", "SX", "T01", "X"}),
    "BSB06": ({"E01", "PX", "U", "X"} | _seq("F", 1, 3) | _seq("P", 1, 9)
              | _seq("S", 1, 3)),
    "BSB07": ({"0"} | _seq("A", 1, 5) | {"AX"} | _seq("C", 1, 3) | {"CX"}
              | {"E01", "EX", "P01", "S01", "S02", "SX", "T01", "U", "X"}),
    # Appraisal. Ohio reports "N" (not applicable / not scour-critical) on ~6,000
    # bridges and FHWA accepts it (flags 0), so it is a valid code here.
    "BAP03": {"0", "N", "A", "B", "C", "D", "E", "U"},
    "BAP05": {"0", "N", "A", "B", "C", "D"},
}

# Sequential designation patterns (letter + 2-digit number): B.F.01, B.SP.01,
# B.SB.01.
_PATTERN_CODES = {
    "BF01": r"(?:H|R|P|W|F|B|D|X)\d{2}",
    "BSP01": r"(?:M|A|C|V|W)\d{2}",
    "BSB01": r"(?:A|P|W)\d{2}",
}


def _is_transitional(text):
    """True for a 2026-2027 transition code ('<base>-T') not in the 2022 spec."""
    return text.endswith("-T") and len(text) > 2


def _require_code(value, allowed, item):
    """Validate an enumerated SNBI code; accepts '-T' transition codes."""
    if value is None:
        return value
    text = str(value).strip()
    if text in allowed or _is_transitional(text):
        return text
    raise ValueError(
        f"{item} value {text!r} is not a valid SNBI code; allowed values: "
        f"{', '.join(sorted(allowed))} (or a '-T' transition code)"
    )


def _require_pattern_code(value, pattern, item):
    """Validate a sequential designation code (e.g. 'M01'); accepts '-T'."""
    if value is None:
        return value
    text = str(value).strip()
    if re.fullmatch(pattern, text) or _is_transitional(text):
        return text
    raise ValueError(
        f"{item} value {text!r} is not a valid SNBI designation code"
    )


def _require_multi_code(value, allowed, item):
    """Validate a pipe-delimited multi-value SNBI code field (B.CL.03)."""
    if value is None:
        return value
    text = str(value).strip()
    for part in (p.strip() for p in text.split("|") if p.strip()):
        if part not in allowed and not _is_transitional(part):
            raise ValueError(
                f"{item} value {part!r} is not a valid SNBI code; allowed "
                f"values: {', '.join(sorted(allowed))}"
            )
    return text


# ---------------------------------------------------------------------------
# Child datasets
# ---------------------------------------------------------------------------
class Element(BaseModel):
    """SNBI element record (B.E / B.CS). Element numbers are validated against
    SNBI Table 22 by FHWA; here only length/range and the total-quantity
    reconciliation (B.E.03-3) are enforced."""

    BE01: Annotated[str, StringConstraints(max_length=4, min_length=1, strip_whitespace=True)]
    # B.E.02 (Element Parent Number) is only reported for child elements (defects,
    # protective systems) nested under a parent; top-level NBE elements have no
    # parent, so it is optional.
    BE02: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BE03: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None
    BCS01: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None
    BCS02: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None
    BCS03: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None
    BCS04: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None

    @model_validator(mode="after")
    def _total_equals_condition_state_sum(self):
        # B.E.03-3 (Critical): total quantity must equal the sum of CS1-CS4
        states = [self.BCS01, self.BCS02, self.BCS03, self.BCS04]
        if self.BE03 is not None and all(s is not None for s in states):
            if self.BE03 != sum(states):
                raise ValueError(
                    "BE03 Element Total Quantity must equal the sum of "
                    "BCS01-BCS04"
                )
        return self


class Route(BaseModel):
    """SNBI route record (B.RT). Required for every 'highway' feature."""

    # B.RT.01 is optional: AssetWise reports the route number/direction but omits
    # the designation on many routes, and FHWA flags that omission 0 times. When
    # present it must still be a valid designation (begins with "R", <= 3 chars).
    BRT01: Optional[Annotated[str, StringConstraints(max_length=3, min_length=1, strip_whitespace=True)]] = None
    # B.RT.02 (route number) is reported for every route. BRT03/04/05 are
    # back to optional + enum-checked: FHWA flags their nulls far less often
    # than our API data omits them (see the BG03 note above).
    BRT02: Annotated[str, StringConstraints(max_length=15, strip_whitespace=True)]
    BRT03: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BRT04: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BRT05: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None

    @field_validator("BRT01")
    @classmethod
    def _designation_starts_with_r(cls, v):
        # B.RT.01: valid route designations begin with "R" (optional; skip if absent)
        if v is not None and not v.upper().startswith("R"):
            raise ValueError('BRT01 Route Designation must begin with "R"')
        return v

    @field_validator("BRT02")
    @classmethod
    def _route_number_charset(cls, v):
        return _require_charset(v, _CHARSET_ROUTE_NUM, "BRT02 Route Number")

    @field_validator("BRT04")
    @classmethod
    def _route_type(cls, v):
        # B.RT.04: 1 through 7 and X
        return _require_in(v, {str(n) for n in range(1, 8)} | {"X"}, "BRT04 Route Type")

    @field_validator("BRT05")
    @classmethod
    def _service_type(cls, v):
        # B.RT.05: 1 through 8 and X
        return _require_in(v, {str(n) for n in range(1, 9)} | {"X"}, "BRT05 Service Type")

    @field_validator("BRT03")
    @classmethod
    def _route_direction(cls, v):
        return _require_code(v, _SNBI_CODES["BRT03"], "BRT03 Route Direction")


class Feature(BaseModel):
    """SNBI feature record (B.F / B.H / B.RR / B.N).

    Conditional-required highway sub-items ("...when B.F.02 = C") are not forced
    here (they need the feature-location context and HPMS lookups); range and
    enumeration checks apply when a value is present.
    """

    BF01: Annotated[str, StringConstraints(max_length=3, min_length=1, strip_whitespace=True)]
    BF02: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BF03: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None

    # Highway sub-items
    BH01: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BH02: Optional[Annotated[str, StringConstraints(max_length=5, strip_whitespace=True)]] = None
    BH03: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BH04: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BH05: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BH06: Optional[Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)]] = None
    BH07: Optional[Annotated[float, Field(ge=0, le=99999999)]] = None
    BH08: Optional[Annotated[int, Field(ge=0, le=99)]] = None
    BH09: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None
    BH10: Optional[Annotated[int, Field(ge=0, le=99999999)]] = None
    BH11: Optional[Annotated[int, Field(ge=0, le=9999)]] = None
    BH12: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BH13: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BH14: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BH15: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BH16: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BH17: Optional[Annotated[int, Field(ge=0, le=999)]] = None
    BH18: Optional[Annotated[str, StringConstraints(max_length=15, strip_whitespace=True)]] = None

    # Railroad sub-items
    BRR01: Optional[Annotated[str, StringConstraints(max_length=2, strip_whitespace=True)]] = None
    BRR02: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BRR03: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None

    # Navigable-waterway sub-items
    BN01: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BN02: Optional[Annotated[float, Field(ge=0, le=999.9)]] = None
    BN03: Optional[Annotated[float, Field(ge=0, le=999.9)]] = None
    BN04: Optional[Annotated[float, Field(ge=0, le=9999.9)]] = None
    BN05: Optional[Annotated[float, Field(ge=0, le=9999.9)]] = None
    BN06: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None

    Routes: Optional[List[Route]] = None

    @field_validator("BH03")
    @classmethod
    def _nhs(cls, v):
        return _require_in(v, {"Y", "N"}, "BH03 NHS Designation")

    @field_validator("BH04")
    @classmethod
    def _nhfn(cls, v):
        return _require_in(v, {"1", "2", "3", "4", "N", "1-T"}, "BH04 NHFN")

    @field_validator("BH05")
    @classmethod
    def _strahnet(cls, v):
        return _require_in(v, {"1", "2", "N"}, "BH05 STRAHNET Designation")

    @field_validator("BH18")
    @classmethod
    def _crossing_bridge_charset(cls, v):
        return _require_charset(v, _CHARSET_BID, "BH18 Crossing Bridge Number")

    @field_validator("BN01")
    @classmethod
    def _navigable(cls, v):
        return _require_in(v, {"Y", "N", "U"}, "BN01 Navigable Waterway")

    @field_validator("BN06")
    @classmethod
    def _nav_protection(cls, v):
        return _require_in(v, {str(n) for n in range(6)} | {"1-T"}, "BN06 Substructure Navigation Protection")

    # BF01 (feature type) is required + used by the conditional validators below
    # via its leading letter, but NOT pattern-checked: the strict 'letter + two
    # digits' pattern rejected valid Ohio feature codes FHWA accepts.
    @field_validator("BF02")
    @classmethod
    def _feature_location(cls, v):
        return _require_code(v, _SNBI_CODES["BF02"], "BF02 Feature Location")

    @field_validator("BH01")
    @classmethod
    def _functional_class(cls, v):
        return _require_code(v, _SNBI_CODES["BH01"], "BH01 Functional Classification")

    @field_validator("BRR01")
    @classmethod
    def _railroad_service(cls, v):
        return _require_code(v, _SNBI_CODES["BRR01"], "BRR01 Railroad Service Type")

    @field_validator("BH02")
    @classmethod
    def _urban_code(cls, v):
        # B.H.02: numeric Census urban-area code (e.g. 99999 for rural). The
        # full Census UACE code table is not reproduced here; this enforces the
        # numeric format and catches blanks.
        if v is None:
            return v
        if not re.fullmatch(r"[0-9]{1,5}", str(v).strip()):
            raise ValueError("BH02 Urban Code must be a numeric Census urban-area code")
        return v

    @field_validator("BH16")
    @classmethod
    def _usable_surface_width(cls, v):
        return _one_decimal(v, "BH16 Highway Maximum Usable Surface Width")

    @model_validator(mode="after")
    def _feature_type_conditionals(self):
        ftype = (self.BF01 or "").upper()
        # Highway sub-items FHWA flags when null. FHWA's processing report (OH,
        # 5/6/2026, ODOT-owned rows) checks six of them only on the feature the
        # bridge CARRIES (B.F.02 C / T / L): BH02 544 carried vs 8 under, BH06
        # 90/0, BH09 48/0, BH11 42/0, BH13 44/0, BH17 70/0. BH16 is the one item
        # it also checks on highway features UNDER the bridge (54 carried, 222
        # under). Checking the carried-only items on under-features reported
        # ~1,200 bridges per item FHWA never flags (2026-10-26).
        carried = (self.BF02 or "").strip().upper() in ("C", "T", "L")
        highway_required = ("BH02", "BH06", "BH09", "BH11", "BH13", "BH16", "BH17") if carried else ("BH16",)
        # NOTE: SNBI makes B.RT.01 (a Route dataset) critical for every highway
        # feature, but FHWA's processing report flags it 0 times while our API
        # read omits the Route sub-datasets on ~7,300 bridges (the "export FHWA
        # data" feed carries them, the REST read does not). A highway feature that
        # came back without a Route also came back without its BH* detail block,
        # so we only enforce the highway sub-item requiredness on features that
        # were fully retrieved (have a Route with BRT01). Otherwise we would just
        # re-report the one data-source gap thousands of times across BH02/06/... .
        if ftype.startswith("H") and self.Routes and any(r.BRT01 for r in self.Routes):
            missing = [f for f in highway_required if getattr(self, f) is None]
            if missing:
                raise ValueError(
                    "A highway feature (BF01 begins with 'H') must report "
                    + ", ".join(missing)
                )
        # B.N (Critical): waterway features must report navigable-waterway code
        if ftype.startswith("W"):
            if self.BN01 is None:
                raise ValueError(
                    "A waterway feature (BF01 begins with 'W') must report BN01 "
                    "Navigable Waterway (Y, N, or U)"
                )
            # Navigable waterways must report navigation clearances.
            if self.BN01.upper() == "Y":
                nav_missing = [f for f in ("BN02", "BN04", "BN06")
                               if getattr(self, f) is None]
                if nav_missing:
                    raise ValueError(
                        "A navigable waterway feature (BN01 = 'Y') must report "
                        + ", ".join(nav_missing)
                    )
        return self


class Inspection(BaseModel):
    """SNBI inspection event record (B.IE)."""

    BIE01: Annotated[str, StringConstraints(max_length=1, min_length=1, strip_whitespace=True)]
    BIE02: str  # Inspection Begin Date - YYYYMMDD (required for each inspection)
    BIE03: Optional[str] = None  # Inspection Completion Date - YYYYMMDD
    BIE04: Optional[Annotated[str, StringConstraints(max_length=15, strip_whitespace=True)]] = None
    BIE05: Optional[Annotated[int, Field(ge=0, le=99)]] = None
    BIE06: Optional[str] = None  # Inspection Due Date - FHWA-CALCULATED, do not report
    BIE07: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BIE08: Optional[str] = None  # QC Date - YYYYMMDD
    BIE09: Optional[str] = None  # QA Date - YYYYMMDD
    BIE10: Optional[str] = None  # Data Update Date - YYYYMMDD
    BIE11: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None
    BIE12: Optional[Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)]] = None

    @field_validator("BIE02", "BIE03", "BIE08", "BIE09", "BIE10")
    @classmethod
    def _dates(cls, v, info):
        return _require_date(v, info.field_name)

    @field_validator("BIE04")
    @classmethod
    def _inspector_charset(cls, v):
        return _require_charset(v, _CHARSET_ALNUM, "BIE04 Nationally Certified Bridge Inspector")

    @field_validator("BIE07")
    @classmethod
    def _risk_method(cls, v):
        return _require_in(v, {"1", "2", "N"}, "BIE07 Risk-Based Inspection Interval Method")

    @field_validator("BIE11")
    @classmethod
    def _note_charset(cls, v):
        return _require_charset(v, _CHARSET_NOTE, "BIE11 Inspection Note")

    @field_validator("BIE06")
    @classmethod
    def _due_date_not_reported(cls, v):
        # B.IE.06: FHWA WILL CALCULATE THIS VALUE - do not report
        if v is not None:
            raise ValueError("BIE06 Inspection Due Date is FHWA-calculated; do not report it")
        return v

    @field_validator("BIE01")
    @classmethod
    def _inspection_type(cls, v):
        return _require_code(v, _SNBI_CODES["BIE01"], "BIE01 Inspection Type")


class PostingEvaluation(BaseModel):
    """SNBI load evaluation & posting record (B.EP)."""

    BEP01: Annotated[str, StringConstraints(max_length=15, min_length=1, strip_whitespace=True)]
    BEP02: Optional[Annotated[float, Field(ge=0, le=99.99)]] = None
    BEP03: Optional[Annotated[str, StringConstraints(max_length=17, strip_whitespace=True)]] = None
    BEP04: Optional[Annotated[str, StringConstraints(max_length=15, strip_whitespace=True)]] = None

    @field_validator("BEP01")
    @classmethod
    def _legal_load_charset(cls, v):
        return _require_charset(v, _CHARSET_LOAD_CFG, "BEP01 Legal Load Configuration")

    # BEP03 (posting type) is not enum-checked (Ohio reports codes beyond the
    # published table); its value is still used by the cross-field rule below.
    @model_validator(mode="after")
    def _posting_value_not_reported(self):
        # B.EP.04: do not report a posting value for posting types that carry
        # no numeric value (C, S, L, V).
        if (self.BEP03 or "").upper() in {"C", "S", "L", "V"} and self.BEP04 is not None:
            raise ValueError(
                "BEP04 Posting Value must not be reported when BEP03 Posting "
                "Type is C, S, L, or V")
        return self


class PostingStatus(BaseModel):
    """SNBI load posting status record (B.PS)."""

    BPS01: Annotated[str, StringConstraints(max_length=4, min_length=1, strip_whitespace=True)]
    BPS02: Optional[str] = None  # Posting Status Change Date - YYYYMMDD

    @field_validator("BPS02")
    @classmethod
    def _change_date(cls, v):
        return _require_date(v, "BPS02 Posting Status Change Date")

    @field_validator("BPS01")
    @classmethod
    def _posting_status(cls, v):
        return _require_code(v, _SNBI_CODES["BPS01"], "BPS01 Load Posting Status")


class SpanSet(BaseModel):
    """SNBI span set record (B.SP)."""

    BSP01: Annotated[str, StringConstraints(max_length=3, min_length=1, strip_whitespace=True)]
    BSP02: Optional[Annotated[int, Field(ge=0, le=9999)]] = None
    BSP03: Optional[Annotated[int, Field(ge=0, le=999)]] = None
    BSP04: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BSP05: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSP06: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BSP07: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSP08: Optional[Annotated[str, StringConstraints(max_length=2, strip_whitespace=True)]] = None
    BSP09: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BSP10: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSP11: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BSP12: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSP13: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None

    @field_validator("BSP05")
    @classmethod
    def _span_continuity(cls, v):
        # B.SP.05: 1 through 7 (+ temporary codes valid 2026-2027)
        return _require_in(v, {str(n) for n in range(1, 8)} | {"C-T", "7-T"}, "BSP05 Span Continuity")

    @field_validator("BSP01")
    @classmethod
    def _span_designation(cls, v):
        return _require_pattern_code(v, _PATTERN_CODES["BSP01"],
                                     "BSP01 Span Configuration Designation")

    # Enum-check only the span codes FHWA actually flags as invalid; the others
    # (BSP07/08/10/11/13) rejected valid Ohio codes FHWA accepts.
    @field_validator("BSP04", "BSP06", "BSP09", "BSP12")
    @classmethod
    def _span_codes(cls, v, info):
        return _require_code(v, _SNBI_CODES[info.field_name], info.field_name)

    @model_validator(mode="after")
    def _span_required(self):
        # Reported for every span set (FHWA flags each as null/invalid).
        missing = [f for f in ("BSP02", "BSP04", "BSP05", "BSP06")
                   if getattr(self, f) is None]
        if missing:
            raise ValueError(
                "Span set must report " + ", ".join(missing))
        # Deck material applies only to spans that carry a deck (not pipe
        # culverts). BSP12 (deck reinforcing protective system) is NOT forced
        # here -- FHWA flags its nulls far less often than our data omits it --
        # but it is still enum-checked when present.
        is_pipe_culvert = (self.BSP06 or "").upper() in {"P01", "P02"}
        if not is_pipe_culvert and self.BSP09 is None:
            raise ValueError("A span set with a deck must report BSP09")
        # B.SP.03-2: zero beam lines is only valid for slab/pipe spans (P01/P02).
        if self.BSP03 == 0 and not is_pipe_culvert:
            raise ValueError(
                "BSP03 Number of Beam Lines is 0 but BSP06 Span Type is not "
                "a slab/pipe span (P01 or P02)")
        return self


class SubstructureSet(BaseModel):
    """SNBI substructure set record (B.SB)."""

    BSB01: Annotated[str, StringConstraints(max_length=3, min_length=1, strip_whitespace=True)]
    BSB02: Optional[Annotated[int, Field(ge=1, le=999)]] = None  # must be > 0
    BSB03: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSB04: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSB05: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSB06: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BSB07: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None

    @field_validator("BSB01")
    @classmethod
    def _substructure_designation(cls, v):
        return _require_pattern_code(v, _PATTERN_CODES["BSB01"],
                                     "BSB01 Substructure Configuration Designation")

    # BSB05/06/07 rejected valid Ohio codes FHWA accepts, so only BSB03/04 are
    # enum-checked.
    @field_validator("BSB03", "BSB04")
    @classmethod
    def _substructure_codes(cls, v, info):
        return _require_code(v, _SNBI_CODES[info.field_name], info.field_name)


class Work(BaseModel):
    """SNBI work-event record (B.W.02 / B.W.03)."""

    BW02: Annotated[int, Field(ge=1000, le=9999)]  # Year Work Performed (YYYY)
    BW03: Optional[Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)]] = None


# ---------------------------------------------------------------------------
# Root record
# ---------------------------------------------------------------------------
class Bridge(BaseModel):
    # --- Identification (B.ID) -------------------------------------------------
    BID01: Annotated[str, StringConstraints(max_length=15, min_length=1, strip_whitespace=True)]
    BID02: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None
    BID03: Optional[Annotated[str, StringConstraints(max_length=15, strip_whitespace=True)]] = "0"

    # --- Location (B.L) --------------------------------------------------------
    BL01: int  # State Code - validated against NBIS_state_codes below
    BL02: Optional[Annotated[int, Field(ge=1, le=999)]] = None
    BL03: Optional[Annotated[int, Field(ge=0, le=99999)]] = None
    BL04: Optional[Annotated[str, StringConstraints(max_length=2, strip_whitespace=True)]] = None
    BL05: Annotated[float, Field(ge=-90.0, le=90.0)]   # Latitude
    BL06: Annotated[float, Field(ge=-180.0, le=180.0)]  # Longitude
    BL07: Optional[Annotated[str, StringConstraints(max_length=15, strip_whitespace=True)]] = None
    BL08: Optional[Annotated[str, StringConstraints(max_length=2, strip_whitespace=True)]] = None
    BL09: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BL10: Optional[Annotated[str, StringConstraints(max_length=2, strip_whitespace=True)]] = None
    BL11: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None
    BL12: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None

    # --- Classification (B.CL) -------------------------------------------------
    # BCL01/BCL02 (owner / maintenance responsibility): SNBI reports them for all
    # bridges, but FHWA flags their null 0 times while our API read omits them on
    # ~260 records (data-source gap), so they are optional rather than required.
    BCL01: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BCL02: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BCL03: Annotated[str, StringConstraints(max_length=30, strip_whitespace=True)]  # Land Access (all bridges)
    BCL04: Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]   # Historic (all bridges)
    BCL05: Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]   # Toll (all bridges)
    BCL06: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None

    # --- Railings (B.RH) -------------------------------------------------------
    BRH01: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BRH02: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None

    # --- Geometry (B.G) --------------------------------------------------------
    BG01: Annotated[float, Field(ge=0, le=999999.9)]   # NBIS Bridge Length (> 20 ft to be NBIS)
    # BG02 Total Bridge Length: FHWA flags its null 0 times but our API read omits
    # it on ~600 records (data-source gap), so optional + range-checked, not required.
    BG02: Optional[Annotated[float, Field(ge=0, le=999999.9)]] = None
    # NOTE: BG03/BG07/BG08/BG10/BG11 were briefly made required to match FHWA's
    # "null" findings, but the FHWA processing report flags those nulls far less
    # often than ODOT's API data omits them (FHWA's "export FHWA data" feed
    # differs from our API read), so they are back to optional + range-checked.
    BG03: Optional[Annotated[float, Field(ge=0, le=9999.9)]] = None
    BG04: Optional[Annotated[float, Field(ge=0, le=9999.9)]] = None
    # BG05 Width Out-to-Out: FHWA flags its null 0 times (it only appears in the
    # cross-field out-to-out >= curb-to-curb rule, 21x) while our API read omits it
    # on ~1,600 records, so optional + range-checked, not required. (BG06
    # curb-to-curb stays required -- FHWA does flag its nulls.)
    BG05: Optional[Annotated[float, Field(gt=0, le=999.9)]] = None
    BG06: Annotated[float, Field(gt=0, le=999.9)]      # Width Curb-to-Curb (> 0, all bridges)
    BG07: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    BG08: Optional[Annotated[float, Field(ge=0, le=99.9)]] = None
    # BG09 Approach Roadway Width: FHWA flags its null 0 times but our API read
    # omits it on ~880 records (data-source gap), so optional + range-checked.
    BG09: Optional[Annotated[float, Field(gt=0, le=999.9)]] = None
    BG10: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BG11: Optional[Annotated[int, Field(ge=0, le=99)]] = None
    BG12: Optional[Annotated[str, StringConstraints(max_length=2, strip_whitespace=True)]] = None
    BG13: Optional[Annotated[int, Field(ge=0, le=9999)]] = None
    BG14: Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]   # Sidehill (all bridges)
    BG15: Optional[Annotated[float, Field(ge=0, le=999999999.9)]] = None
    BG16: Optional[float] = None  # Calculated Deck Area - FHWA-CALCULATED, do not report

    # --- Load rating (B.LR) ----------------------------------------------------
    BLR01: Optional[Annotated[str, StringConstraints(max_length=8, strip_whitespace=True)]] = None
    BLR02: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BLR03: Optional[str] = None  # Load Rating Date - YYYYMMDD
    BLR04: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BLR05: Optional[Annotated[float, Field(ge=0, le=99.99)]] = None
    BLR06: Optional[Annotated[float, Field(ge=0, le=99.99)]] = None
    BLR07: Optional[Annotated[float, Field(ge=0, le=99.99)]] = None
    BLR08: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None

    # --- Inspection requirements (B.IR) ---------------------------------------
    BIR01: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BIR02: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BIR03: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BIR04: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None

    # --- Condition (B.C) -------------------------------------------------------
    BC01: Annotated[str, StringConstraints(max_length=1, min_length=1, strip_whitespace=True)]
    BC02: Annotated[str, StringConstraints(max_length=1, min_length=1, strip_whitespace=True)]
    BC03: Annotated[str, StringConstraints(max_length=1, min_length=1, strip_whitespace=True)]
    BC04: Annotated[str, StringConstraints(max_length=1, min_length=1, strip_whitespace=True)]
    BC05: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC06: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC07: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC08: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC09: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC10: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC11: Optional[Annotated[str, StringConstraints(max_length=4, strip_whitespace=True)]] = None
    BC12: Optional[str] = None  # Bridge Condition Classification - FHWA-CALCULATED
    BC13: Optional[str] = None  # Lowest Condition Rating Code - FHWA-CALCULATED
    BC14: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BC15: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None

    # --- Appraisal (B.AP) ------------------------------------------------------
    BAP01: Optional[Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]] = None
    BAP02: Optional[Annotated[str, StringConstraints(max_length=5, strip_whitespace=True)]] = None
    BAP03: Optional[Annotated[str, StringConstraints(max_length=5, strip_whitespace=True)]] = None
    BAP04: Optional[Annotated[str, StringConstraints(max_length=3, strip_whitespace=True)]] = None
    BAP05: Annotated[str, StringConstraints(max_length=1, strip_whitespace=True)]   # Seismic vulnerability (all bridges)

    # --- Year built (B.W.01) ---------------------------------------------------
    BW01: Optional[Annotated[int, Field(ge=1000, le=9999)]] = None

    # --- One-to-many relationships --------------------------------------------
    Elements: Optional[List[Element]] = None
    Features: Optional[List[Feature]] = None
    Inspections: Optional[List[Inspection]] = None
    PostingEvaluations: Optional[List[PostingEvaluation]] = None
    PostingStatuses: Optional[List[PostingStatus]] = None
    SpanSets: Optional[List[SpanSet]] = None
    SubstructureSets: Optional[List[SubstructureSet]] = None
    Works: Optional[List[Work]] = None

    # === Field validators =====================================================
    @field_validator("BID01", "BID03")
    @classmethod
    def _bridge_number_charset(cls, v, info):
        return _require_charset(v, _CHARSET_BID, f"{info.field_name} Bridge Number")

    @field_validator("BL01")
    @classmethod
    def _valid_state_code(cls, v):
        # B.L.01-1 (Critical): must be a valid SNBI State code
        try:
            state_code_conversion(f"{int(v):02d}")
        except Exception:
            raise ValueError(f"BL01 State Code {v!r} is not a valid SNBI state code")
        return v

    @field_validator("BL04")
    @classmethod
    def _district_charset(cls, v):
        # B.L.04-3: alphanumeric (A-Z, a-z, 0-9) - NOT numeric-only
        return _require_charset(v, _CHARSET_ALNUM, "BL04 Highway Agency District")

    @field_validator("BL07")
    @classmethod
    def _border_number_charset(cls, v):
        return _require_charset(v, _CHARSET_BORDER, "BL07 Border Bridge Number")

    @field_validator("BL08", "BL10")
    @classmethod
    def _border_state(cls, v, info):
        if v is None:
            return v
        if not _is_valid_state_or_country(v):
            raise ValueError(
                f"{info.field_name} must be a valid SNBI State code or MX/CA"
            )
        return str(v).strip().upper()

    @field_validator("BL09")
    @classmethod
    def _border_insp_resp(cls, v):
        # B.L.09: 0 through 2
        return _require_in(v, {"0", "1", "2"}, "BL09 Border Bridge Inspection Responsibility")

    @field_validator("BCL04")
    @classmethod
    def _historic(cls, v):
        # B.CL.04: 1 through 7, N (T = temporary, valid 2026-2027)
        return _require_in(v, {str(n) for n in range(1, 8)} | {"N", "T"}, "BCL04 Historic Significance")

    @field_validator("BCL05")
    @classmethod
    def _toll(cls, v):
        # B.CL.05: 1 through 4 and N
        return _require_in(v, {str(n) for n in range(1, 5)} | {"N"}, "BCL05 Toll")

    @field_validator("BCL06")
    @classmethod
    def _emergency_evac(cls, v):
        return _require_in(v, {"Y", "N"}, "BCL06 Emergency Evacuation Designation")

    @field_validator("BG10")
    @classmethod
    def _median(cls, v):
        # B.G.10: 0 through 3
        return _require_in(v, {"0", "1", "2", "3"}, "BG10 Bridge Median")

    @field_validator("BG14")
    @classmethod
    def _sidehill(cls, v):
        return _require_in(v, {"Y", "N"}, "BG14 Sidehill Bridge")

    @field_validator("BG16")
    @classmethod
    def _calc_deck_area_not_reported(cls, v):
        if v is not None:
            raise ValueError("BG16 Calculated Deck Area is FHWA-calculated; do not report it")
        return v

    @field_validator("BG15")
    @classmethod
    def _irregular_deck_area(cls, v):
        return _one_decimal(v, "BG15 Irregular Deck Area")

    @field_validator("BLR03")
    @classmethod
    def _load_rating_date(cls, v):
        return _require_date(v, "BLR03 Load Rating Date")

    @field_validator("BLR08")
    @classmethod
    def _routine_permit(cls, v):
        # B.LR.08: A, B, C, or N
        return _require_in(v, {"A", "B", "C", "N"}, "BLR08 Routine Permit Loads")

    @field_validator("BIR01", "BIR02", "BIR03", "BIR04")
    @classmethod
    def _yes_no(cls, v, info):
        return _require_in(v, {"Y", "N"}, info.field_name)

    # BCL01/BCL02 (owner / maintenance responsibility) are NOT enum-checked:
    # FHWA accepts agency codes beyond the published table, so enforcing the
    # table produced false positives FHWA never reports.
    @field_validator("BG12", "BLR01", "BLR02", "BLR04", "BAP03", "BAP05")
    @classmethod
    def _bridge_coded_values(cls, v, info):
        return _require_code(v, _SNBI_CODES[info.field_name], info.field_name)

    @field_validator("BCL03")
    @classmethod
    def _land_access(cls, v):
        return _require_multi_code(v, _LAND_ACCESS,
                                   "BCL03 Federal or Tribal Land Access")

    @field_validator("BC01", "BC02", "BC03", "BC04", "BC05", "BC06", "BC07",
                     "BC08", "BC09", "BC10", "BC14", "BC15")
    @classmethod
    def _condition_rating(cls, v, info):
        # 0 through 9 and N
        return _require_in(v, _COND_RATINGS, f"{info.field_name} Condition Rating")

    @field_validator("BC11")
    @classmethod
    def _scour_rating(cls, v):
        # B.C.11: 0-9, N (+ temporary codes valid 2026-2027)
        return _require_in(v, _COND_RATINGS | {"MA-T", "MI-T", "MO-T"}, "BC11 Scour Condition Rating")

    @field_validator("BC12", "BC13")
    @classmethod
    def _calculated_condition_not_reported(cls, v, info):
        if v is not None:
            raise ValueError(f"{info.field_name} is FHWA-calculated; do not report it")
        return v

    @field_validator("BAP01")
    @classmethod
    def _approach_alignment(cls, v):
        return _require_in(v, {"G", "F", "P"}, "BAP01 Approach Roadway Alignment")

    @field_validator("BAP02")
    @classmethod
    def _overtopping(cls, v):
        return _require_in(v, {str(n) for n in range(7)} | {"VLM-T", "HVH-T"}, "BAP02 Overtopping Likelihood")

    # BAP04 (Scour Plan of Action) is not enum-checked: Ohio reports codes beyond
    # {0, Y, N} and FHWA flags them 0 times (data-source gap), so we accept as-is.

    # === Cross-field model validators =========================================
    @model_validator(mode="after")
    def _required_datasets(self):
        # Critical "at least one ... dataset" rules
        if not self.Features:
            raise ValueError("At least one Features dataset (BF01) must be reported")
        if not self.PostingStatuses:
            raise ValueError("At least one Load Posting Status dataset (BPS01) must be reported")
        if not self.SpanSets:
            raise ValueError("At least one Span dataset (BSP01) must be reported")
        if not self.Works:
            raise ValueError("At least one Work dataset (BW02) must be reported")

        # B.SB (Critical): substructure required unless ALL spans are buried
        # pipe culverts (BSP06 = P01 or P02)
        all_culvert_pipe = bool(self.SpanSets) and all(
            (s.BSP06 or "").upper() in {"P01", "P02"} for s in self.SpanSets
        )
        if not all_culvert_pipe and not self.SubstructureSets:
            raise ValueError("At least one Substructure dataset (BSB01) must be reported")
        return self

    @model_validator(mode="after")
    def _length_consistency(self):
        # B.G.02-3 (Critical): NBIS length must not exceed total length
        if self.BG01 is not None and self.BG02 is not None and self.BG01 > self.BG02:
            raise ValueError("BG01 NBIS Bridge Length must not exceed BG02 Total Bridge Length")
        return self

    @model_validator(mode="after")
    def _previous_number_differs(self):
        # B.ID.03-4: previous bridge number must differ from current
        if self.BID03 not in _EMPTY and self.BID03 == self.BID01:
            raise ValueError("BID03 Previous Bridge Number must not equal BID01 Bridge Number")
        return self

    @model_validator(mode="after")
    def _calculated_condition_dependencies(self):
        # B.C.14-2 / B.C.15-2: do not report when the inspection is not required
        if (self.BIR01 or "").upper() != "Y" and self.BC14 is not None:
            raise ValueError("BC14 NSTM Inspection Condition must not be reported when BIR01 != 'Y'")
        if (self.BIR03 or "").upper() != "Y" and self.BC15 is not None:
            raise ValueError("BC15 Underwater Inspection Condition must not be reported when BIR03 != 'Y'")
        return self

    @model_validator(mode="after")
    def _posting_evaluation_required(self):
        # B.EP (Critical): when not closed and controlling legal rating < 1.0,
        # at least one Load Evaluation & Posting dataset must be reported
        open_to_traffic = any(
            (ps.BPS01 or "").upper() != "C" for ps in (self.PostingStatuses or [])
        )
        if open_to_traffic and self.BLR07 is not None and self.BLR07 < 1.0:
            if not self.PostingEvaluations:
                raise ValueError(
                    "A Load Evaluation and Posting dataset (BEP01) is required when "
                    "the bridge is open and BLR07 Controlling Legal Load Rating Factor < 1.0"
                )
        return self

    @model_validator(mode="after")
    def _safety_checks(self):
        statuses = {(ps.BPS01 or "").upper() for ps in (self.PostingStatuses or [])}
        closed = "C" in statuses

        # Safety - Closed Bridge: operating rating very low but not closed
        if self.BLR06 is not None and self.BLR06 < 0.1 and not closed:
            raise ValueError(
                "Safety check: BLR06 Operating Load Rating Factor < 0.1 but the "
                "bridge is not posted closed (BPS01 = 'C')"
            )
        # Safety - Closed Bridge: a controlling condition rating below 2 but not closed
        for item in ("BC01", "BC02", "BC03", "BC04"):
            value = getattr(self, item)
            if value is not None and value.isdigit() and int(value) < 2 and not closed:
                raise ValueError(
                    f"Safety check: {item} Condition Rating < 2 but the bridge is "
                    "not posted closed (BPS01 = 'C')"
                )
        # Safety - Posted Bridge: legal rating < 1.0 without an appropriate posting
        posted_or_closed = {"PP", "TP", "SP", "PR", "TR", "SR", "C"}
        if (
            self.BLR07 is not None
            and self.BLR07 < 1.0
            and not (statuses & posted_or_closed)
        ):
            raise ValueError(
                "Safety check: BLR07 Controlling Legal Load Rating Factor < 1.0 but "
                "the bridge is not posted/restricted/closed"
            )
        return self

    @model_validator(mode="after")
    def _width_consistency(self):
        # B.G.05-3: out-to-out width must exceed curb-to-curb width, except on
        # sidehill bridges (BG14 = 'Y').
        if (
            self.BG05 is not None
            and self.BG06 is not None
            and (self.BG14 or "").upper() != "Y"
            and self.BG05 < self.BG06
        ):
            raise ValueError(
                "BG05 Bridge Width Out-to-Out must not be less than BG06 Bridge "
                "Width Curb-to-Curb (except on a Sidehill Bridge)")
        return self

    @model_validator(mode="after")
    def _channel_rating_consistency(self):
        # B.C.09: channel condition rating must be 'N' when the bridge has no
        # waterway/relief-waterway feature, and 0-9 when it does.
        has_waterway = any(
            (f.BF01 or "").upper().startswith("W") for f in (self.Features or [])
        )
        if has_waterway:
            if self.BC09 is None or self.BC09 == "N":
                raise ValueError(
                    "BC09 Channel Condition Rating must be 0-9 for a bridge with "
                    "a waterway feature")
        else:
            if self.BC09 != "N":
                raise ValueError(
                    "BC09 Channel Condition Rating must be 'N' for a bridge with "
                    "no waterway feature")
        return self

    @model_validator(mode="after")
    def _crossing_bridge_number_differs(self):
        # B.H.18: a highway feature's crossing bridge number must not equal this
        # bridge's own number (BID01).
        for feature in (self.Features or []):
            if feature.BH18 is not None and feature.BH18 == self.BID01:
                raise ValueError(
                    "BH18 Crossing Bridge Number must not equal BID01 Bridge Number")
        return self

    @model_validator(mode="after")
    def _work_year_not_before_built(self):
        # B.W.02-2: year work performed must not predate the year built.
        if self.BW01 is not None:
            for work in (self.Works or []):
                if work.BW02 is not None and work.BW02 < self.BW01:
                    raise ValueError(
                        "BW02 Year Work Performed must not be earlier than BW01 "
                        "Year Built")
        return self
