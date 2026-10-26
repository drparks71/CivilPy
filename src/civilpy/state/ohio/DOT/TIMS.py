#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

# Use this section to extract data from TIMs and Assetwise to QA the data
"""ODOT TIMS (Transportation Information Mapping System) data access.

Queries the public TIMS REST endpoints for bridge inventory records and
cross-checks them against AssetWise data for QA, including NBI material and
design/construction-type code dictionaries.
"""

from __future__ import annotations

import json
import re
import time
import requests
import pandas as pd
from datetime import datetime, timedelta


# NBI Code Dictionaries for Material and Design/Construction Type
NBI_MATERIAL_CODES = {
    '1': 'Concrete',
    '2': 'Concrete Continuous',
    '3': 'Steel',
    '4': 'Steel Continuous',
    '5': 'Prestressed Concrete',
    '6': 'Prestressed Concrete Continuous',
    '7': 'Wood or Timber',
    '8': 'Masonry',
    '9': 'Aluminum, Wrought Iron, or Cast Iron',
    '0': 'Other',
}

NBI_DESIGN_TYPE_CODES = {
    '01': 'Slab',
    '02': 'Stringer/Multi-beam or Girder',
    '03': 'Girder and Floorbeam System',
    '04': 'Tee Beam',
    '05': 'Box Beam or Girders - Multiple',
    '06': 'Box Beam or Girders - Single or Spread',
    '07': 'Frame',
    '08': 'Orthotropic',
    '09': 'Truss - Deck',
    '10': 'Truss - Thru',
    '11': 'Arch - Deck',
    '12': 'Arch - Thru',
    '13': 'Suspension',
    '14': 'Stayed Girder',
    '15': 'Movable - Lift',
    '16': 'Movable - Bascule',
    '17': 'Movable - Swing',
    '18': 'Tunnel',
    '19': 'Culvert',
    '20': 'Mixed types',
    '21': 'Segmental Box Girder',
    '22': 'Channel Beam',
    '00': 'Other',
}


class TIMSDownloadError(RuntimeError):
    """A TIMS layer download stopped before the last page.

    Raised instead of returning the rows fetched so far, so a dropped
    connection can never pass for a complete inventory. ``partial`` holds
    those rows (a DataFrame) for a caller that wants to inspect them.
    """

    def __init__(self, message, partial):
        super().__init__(message)
        self.partial = partial


def get_tims_data(data_source='Roadway', where='1=1', retries=3, backoff=2.0):
    """
    Download records from an ODOT TIMS ArcGIS MapServer layer into a DataFrame.

    Paginates through the service in batches of 1000 records until all matching
    features are retrieved. Prints progress to stdout. A page that fails
    (connection dropped, HTTP error, or an ArcGIS ``{"error": ...}`` body) is
    retried; if it still fails the download raises rather than returning a
    partial table.

    Args:
        data_source (str): Which TIMS layer to query. One of:

            - ``'Roadway'`` — Road Inventory layer (default)
            - ``'Bridge'`` — Bridge Inventory layer

        where (str): A SQL ``WHERE`` clause used to filter the layer server-side.
            Defaults to ``'1=1'`` (all records). Pass a filter to pull a small,
            fast subset, e.g. ``"COUNTY_CD='ATH'"`` for one county's bridges.
        retries (int): Extra attempts per page after the first fails.
        backoff (float): Seconds to wait before the first retry; doubles on
            each further retry.

    Returns:
        pandas.DataFrame: All matching feature attributes, one row per feature.
        Returns an empty DataFrame if no records are found.

    Raises:
        TIMSDownloadError: A page still failed after ``retries`` retries. The
            rows fetched before it are on the exception's ``partial``.

    Example:
        >>> df = get_tims_data('Bridge', where="COUNTY_CD='ATH'")
        >>> 'SFN' in df.columns
        True
    """
    types = {
        'Roadway': "https://tims.dot.state.oh.us/ags/rest/services/Roadway_Information/Road_Inventory/MapServer/0",
        'Bridge': "https://tims.dot.state.oh.us/ags/rest/services/Assets/Bridge_Inventory/MapServer/0"
    }

    metadata_url = types[data_source]
    query_url = metadata_url + "/query"

    data = requests.get(f"{metadata_url}?f=json").json()
    all_fields = [field['name'] for field in data.get('fields', [])]

    # Set the batch size (MaxRecordCount limit)
    # BATCH_SIZE = int(data['maxRecordCount'])
    BATCH_SIZE = 1000

    # Initialize an empty list to store all feature attributes
    all_attributes = []
    offset = 0

    while True:
        params = {
            'where': where,
            'outFields': ','.join(all_fields),
            'resultOffset': offset,
            'resultRecordCount': BATCH_SIZE,
            'returnGeometry': False,
            'f': 'json'
        }

        for attempt in range(retries + 1):
            try:
                response = requests.post(query_url, data=params)
                response.raise_for_status()
                data = response.json()
                if 'error' in data:
                    # ArcGIS reports query failures in a 200 response body
                    raise requests.exceptions.HTTPError(f"ArcGIS error: {data['error']}")
                break
            except Exception as err:
                if attempt == retries:
                    raise TIMSDownloadError(
                        f"TIMS {data_source} download failed at offset {offset} after "
                        f"{retries + 1} attempts ({len(all_attributes)} records fetched): {err}",
                        pd.DataFrame(all_attributes)) from err
                wait = backoff * 2 ** attempt
                print(f"Error at offset {offset}: {err}. Retrying in {wait:g} s "
                      f"({attempt + 1}/{retries})")
                time.sleep(wait)

        # Check for features in the response
        features = data.get('features', [])

        if not features:
            print(f"No more features found. Fetched {len(all_attributes)} total records.")
            break

        # Extract attributes and add to the main list
        attributes_list = [feature['attributes'] for feature in features]
        all_attributes.extend(attributes_list)

        print(f"Fetched {len(attributes_list)} records. Total so far: {len(all_attributes)}")

        # Increment the offset for the next loop iteration
        offset += BATCH_SIZE

    # Build the final DataFrame from all collected attributes
    df = pd.DataFrame(all_attributes)
    if all_attributes:
        print("DataFrame successfully created with shape:", df.shape)
    else:
        print("No records matched.")

    return df

class TIMSBridge:
    """
    Represents a single bridge from the TIMS database, fetched by its SFN.
    Attributes are dynamically created from the fetched data keys (converted to lowercase).

    Example:
        bridge = TIMSBridge('2102374')
        print(bridge.lanes)  # Access data as attributes
    """
    _API_URL = "https://tims.dot.state.oh.us/ags/rest/services/Assets/Bridge_Inventory/MapServer/0/query"

    def __init__(self, sfn: str):
        """
        Initializes the TIMSBridge object by fetching data for the given SFN.

        Args:
            sfn (str): The Structure File Number (SFN) of the bridge to fetch.

        Raises:
            ValueError: If no bridge is found for the specified SFN.
            RuntimeError: If there is a network or API error.
        """
        self.sfn = sfn  # Store the original SFN
        data = self._fetch_bridge_data()

        if not data:
            raise ValueError(f"No bridge found with SFN '{sfn}'")

        # Dynamically assign attributes from the fetched data, converting keys to lowercase
        # for Pythonic attribute access (e.g., bridge.deck_area instead of bridge['DECK_AREA'])
        for key, value in data.items():
            setattr(self, key.lower(), value)

    def _fetch_bridge_data(self) -> dict | None:
        """
        Internal method to query the TIMS API for the bridge data.
        """
        params = {
            "where": f"SFN = '{self.sfn}'",
            "outFields": "*",
            "f": "json",
            "returnGeometry": "true",
            "resultRecordCount": 1,
        }
        try:
            resp = requests.get(self._API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                # Raise a specific error that includes the API's message
                raise RuntimeError(f"TIMS/ArcGIS API error: {data['error']}")

            features = data.get("features", [])
            if not features:
                return None

            return features[0].get("attributes", {})
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Network error fetching bridge data for SFN '{self.sfn}': {e}") from e

    def __repr__(self) -> str:
        """
        Provides a nicely formatted, developer-friendly representation of the TIMSBridge object.
        """
        # Helper to safely get attributes that might not exist on all records
        def get(attr, default='N/A'):
            return getattr(self, attr, default)

        # Convert timestamp for 'yr_built' to just the year if it exists
        year_built_str = 'N/A'
        if hasattr(self, 'yr_built') and self.yr_built is not None:
            try:
                # The epoch for many systems is 1970-01-01.
                # Adding the timestamp (in seconds) as a timedelta to the epoch
                # correctly handles pre-1970 (negative) timestamps on all platforms.
                epoch = datetime(1970, 1, 1)
                dt = epoch + timedelta(seconds=self.yr_built / 1000)
                year_built_str = dt.strftime('%Y')
            except (ValueError, TypeError, OSError):
                # Fallback for unexpected formats
                year_built_str = str(self.yr_built)

        # Translate material and type codes to descriptions
        material_code = get('main_str_mtl_cd', 'N/A')
        material_desc = NBI_MATERIAL_CODES.get(str(material_code), 'Unknown')

        type_code = get('main_str_type_cd', 'N/A')
        type_desc = NBI_DESIGN_TYPE_CODES.get(str(type_code), 'Unknown')

        material_type_str = f"{material_desc} / {type_desc} ({material_code}/{type_code})"

        # Create a clickable Google Maps link for the coordinates
        lat = get('latitude_dd', 0)
        lon = get('longitude_dd', 0)
        map_url = f"https://www.google.com/maps?q={lat},{lon}"

        repr_str = (
            f"<TIMSBridge SFN: '{self.sfn}'>\n"
            f"  Route Carried: {get('str_loc_carried')}\n"
            f"  NLFID:         {get('nlfid')}\n"
            f"  Location:      {get('county_cd')} County, District {get('district')}\n"
            f"  Location Map:  {map_url}\n"
            f"\n"
            f"  -- Characteristics --\n"
            f"  Lanes On:      {get('lanes_on')}\n"
            f"  Year Built:    {year_built_str}\n"
            f"  Material/Type: {material_type_str} (Main Span)\n"
            f"\n"
            f"  -- Condition Ratings --\n"
            f"  Sufficiency:   {get('suff_rating')}\n"
            f"  Deck:          {get('deck_summary')}\n"
            f"  Superstructure:{get('sups_summary')}\n"
            f"  Substructure:  {get('subs_summary')}\n"
            f"\nFor a full list of available attributes, use help(TIMSBridge)."
        )
        return repr_str


def get_bridge_sfns_by_district(district=None,
                                url = "https://tims.dot.state.oh.us/ags/rest/services/Assets/Bridge_Inventory/MapServer/0/query"
                                ):
    """
    Queries the TIMS API for bridges in a specific district and returns a list of SFNs.

    Args:
        district (int, optional): The district number (1-12).
                                 If None, all bridges are queried. Defaults to None.

    Returns:
        list: A list of SFNs (as strings or numbers, whatever the API returns),
              or an empty list if no records are found or an error occurs.
    """

    # 1. Define query parameters based on district input
    out_fields = 'SFN'  # Only query the SFN field for efficiency
    return_geometry = False

    if district is not None and 1 <= district <= 12:
        # Format district as a two-digit string (e.g., 6 -> '06', 12 -> '12')
        district_str = str(district).zfill(2)
        where_clause = f"DISTRICT = '{district_str}'"
        print(f"Querying API for District {district_str}...")
    else:
        where_clause = "1=1"
        print("No district specified, gathering all bridges...")

    # 2. Define the API Parameters
    params = {
        'where': where_clause,
        'outFields': out_fields,
        'returnGeometry': str(return_geometry).lower(),
        'f': 'json'
    }

    # 3. Make the API Request
    print(f"URL: {url}")
    print(f"Filter: {where_clause}")

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()  # Raise an exception for bad status codes

        data = response.json()

        # 4. Process the Response
        if 'features' in data and data['features']:
            features = data['features']
            print(f"\nSuccess! Found {len(features)} features.")

            # Extract just the SFN from each feature's attributes
            # This is a list comprehension, which is very efficient.
            sfn_list = [
                feature['attributes']['SFN']
                for feature in features
                if 'attributes' in feature and 'SFN' in feature['attributes']
            ]
            return sfn_list

        elif 'error' in data:
            print(f"API returned an error: {data['error']['message']}")
        else:
            print("Query was successful, but no features were found matching the criteria.")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the API request: {e}")
        print("Please check the URL and your network connection.")
    except json.JSONDecodeError:
        print("Error: Could not decode the response from the server. The service might be down.")
    except KeyError:
        # This would happen if a feature is missing 'attributes' or 'SFN'
        print("Error: Data was returned but was missing the 'SFN' field in 'attributes'.")

    # Return an empty list if any issues occurred
    return []


# ---------------------------------------------------------------------------
# Folded in from the retired ``DOT/legacy.py`` (2026-07).
#
# ODOT plan-sheet label dictionaries, county/district reference data, and the
# older ``TimsBridge``/``Project`` record objects. ``TimsBridge`` predates
# ``TIMSBridge`` above and duplicates it field-for-field; it is kept because
# ``search_tools.D6BridgeLookup`` subclasses it for ``get_map``.
# ---------------------------------------------------------------------------

def help_function():
    """
    To use the dicts, import them into python, and then use the two-letter code to get the translations, i.e.
    basemap_labels['BA'] will return "Aerial Mapping"

    General Notes:

    General File Naming Format::

        nnnnn(n)_aa###.dgn where:
            nnnnnn - 5 (or 6) digit PID
            aa     - Two-letter code signifying sheet type (see dicts)
            ###    - Three digit number identifying the number of drawings of the same type

    Bridge Design File Naming Format:
        nnnnnn_SFNyyyyyyy_aa###.dgn where:
            nnnnnn   - PID
            yyyyyyy  - 7 digit SFN of the structure
            aa       - Two character bridge plan sheet type
            ###      - Three digit number identifying the number of drawings of the same type

    Culvert Design File Naming Format:
        nnnnnn_CFNyyyyyyy_aa###.dgn where:
            nnnnnn  - PID
            yyyyyyy - 7 digit CFN number of the culvert
            aa      - Two character drainage plan sheet type
            ###     - Three digit number identifying the number of drawings of the same type

    Wall Design File Naming Format:
        nnnnnn_WALLyyy_aa###.dgn where:
            nnnnnn  - PID
            yyy     - Three digit wall number
            aa      - Two digit wall plan sheet type
            ###     - Three digit number identifying the number of drawings of the same type
    """


basemap_labels = {
    "KB": "3D Model KB",
    "KM": "3D Modeling KM",
    "BC": "Aerial and Ground Combined",
    "BA": "Aerial Mapping",
    "BS": "Bridge",
    "KD": "Digital Terrain Model",
    "BD": "Drainage",
    "FD": "Field Digital Terrain Model",
    "BK": "Geometry",
    "BI": "Geotechnical",
    "BL": "Landscaping",
    "BH": "Lighting",
    "BM": "MOT",
    "PC": "Point Cloud",
    "BR": "Right-of-Way",
    "BP": "Roadway",
    "BG": "Signals",
    "KS": "Superelevation",
    "FB": "Survey Field Book",
    "BT": "Traffic Control",
    "BU": "Utilities",
    "BW": "Wall",
}


bridge_labels = {
    "SB": "Bearing",
    "SD": "Deck Plan",
    "SQ": "Estimated Quantities",
    "SX": "Expansion Device Details",
    "SF": "Forward Abutment",
    "SO": "Foundation Plan",
    "SN": "General Notes",
    "SG": "General Plan",
    "SM": "Miscellaneous Details",
    "SI": "Piers",
    "SA": "Railing",
    "SR": "Rear Abutment",
    "SL": "Reinforcing Steel List",
    "SV": "Removal",
    "SH": "Sheeting",
    "SP": "Site Plan",
    "SC": "Staged Construction Details",
    "SS": "Superstructure Details",
    "ST": "Transverse Section",
}


drainage_labels = {
    "XD": "Channel Cross Sections",
    "DC": "Culvert Details",
    "DD": "Details",
    "DE": "Erosion Control",
    "DM": "Miscellaneous Details",
    "DN": "Notes",
    "DP": "Plan and Profile or Plan",
    "DF": "Profile",
    "DQ": "Quantity Table",
    "DB": "Schematic Plan",
    "DS": "Sub-Summary",
}


geotechnical_labels = {
    "YL": "Geohazard Boring Logs",
    "YC": "Geohazard Cover",
    "YX": "Geohazard Cross Sections",
    "YD": "Geohazard Lab Data",
    "YP": "Geohazard Plan and Profile",
    "YF": "Geohazard Profile",
    "IC": "Soil Profile Cover",
    "IX": "Soil Profile Cross Sections",
    "ID": "Soil Profile Lad Data",
    "IP": "Soil Profile, Plan and Profile or Plan",
    "IF": "Soil Profile, Profile Only",
    "ZL": "Structure Foundation Exploration Boring Logs",
    "ZC": "Structure Foundation Exploration Cover",
    "ZD": "Structure Foundation Exploration Lab Data",
    "ZP": "Structure Foundation Exploration Plan and Profile",
    "ZF": "Structure Foundation Exploration Profile",
}


landscaping_labels = {
    "PD": "Details",
    "PM": "Miscellaneous Details",
    "PN": "Notes",
    "PP": "Plan",
    "PB": "Schematic Plan",
    "PS": "Sub-Summary",
}


lighting_labels = {
    "LC": "Circuit Diagrams",
    "LD": "Details",
    "LE": "Elevation Views",
    "LG": "General Summary",
    "LM": "Miscellaneous",
    "LN": "Notes",
    "LP": "Plan",
    "LQ": "Quantity Table",
    "LB": "Schematic Plan",
    "LS": "Sub-Summary",
}


mot_labels = {
    "XM": "Cross Sections",
    "MD": "Detour Plan",
    "MM": "Miscellaneous",
    "MN": "Notes",
    "MP": "Phase Plan and Profile or Plan",
    "MH": "Phase Details",
    "MF": "Profile",
    "MQ": "Quantity Table",
    "MB": "Schematic Plan",
    "MS": "Sub-Summary",
    "MY": "Typical Sections",
}


row_labels = {
    "RC": "Centerline Plat",
    "RL": "Legend",
    "RM": "Property Map",
    "RR": "Railroad Plat",
    "RB": "RW Boundary",
    "RD": "RW Detail",
    "RT": "RW Topo",
    "RS": "Summary of Additional RW",
}


roadway_labels = {
    "GC": "Calculations/Computations",
    "XS": "Cross Sections",
    "GD": "Drive Details",
    "GX": "Fencing Plan",
    "GN": "General Notes",
    "GG": "General Summary",
    "XG": "Grading Plan",
    "GR": "Guardrail/Barrier Details",
    "GI": "Intersection/Interchange Details",
    "GJ": "Maintenance Data",
    "GM": "Miscellaneous",
    "GA": "Pavement Details",
    "GP": "Plan and Profile or Plan",
    "GF": "Profile",
    "GQ": "Quantity Table",
    "GB": "Schematic Plan",
    "GS": "Sub-Summary",
    "GE": "Superelevation Table",
    "GT": "Title Sheet",
    "GY": "Typical Sections",
}


signal_labels = {
    "CD": "Details",
    "CG": "General Summary",
    "CM": "Miscellaneous",
    "CN": "Notes",
    "CP": "Plan",
    "CQ": "Quantity Table",
    "CS": "Sub-Summary",
}


traffic_control_labels = {
    "TC": "Calculations/Computations",
    "TD": "Details",
    "TE": "Elevation Views",
    "TN": "General Notes",
    "TG": "General Summary",
    "TM": "Miscellaneous",
    "TP": "Plan",
    "TQ": "Quantity Table",
    "TB": "Schematic Plan",
    "TS": "Sub-Summary",
}


utility_labels = {
    "UC": "Calculations/Computations",
    "UD": "Details",
    "UE": "Elevation Views",
    "UG": "General Summary",
    "UM": "Miscellaneous",
    "UN": "Notes",
    "UP": "Plan and Profile or Plan",
    "UF": "Profile",
    "UQ": "Quantity Table",
    "UB": "Schematic Plan",
    "US": "Sub-Summary",
}


wall_labels = {
    "WC": "Calculations/Computations",
    "WX": "Cross Sections",
    "WD": "Details",
    "WE": "Elevation",
    "WQ": "Estimated Quantities",
    "WT": "Foundation",
    "WM": "Miscellaneous",
    "WN": "Notes",
    "WP": "Plan and Profile or Plan",
    "WF": "Profile",
    "WB": "Schematic Plan",
    "WH": "Sheeting",
    "WL": "Steel List",
    "WS": "Sub-Summary",
    "WY": "Typical Section",
}


all_labels = {
    "basemap_labels": basemap_labels,
    "bridge_labels": bridge_labels,
    "drainage_labels": drainage_labels,
    "geotechnical_labels": geotechnical_labels,
    "landscaping_labels": landscaping_labels,
    "lighting_labels": lighting_labels,
    "mot_labels": mot_labels,
    "row_labels": row_labels,
    "roadway_labels": roadway_labels,
    "signal_labels": signal_labels,
    "traffic_control_labels": traffic_control_labels,
    "utility_labels": utility_labels,
    "wall_labels": wall_labels,
}


gen_file_pattern = re.compile(r"\d{5,6}_\w{2}\d{3}.dgn$")


bridge_file_pattern = re.compile(r"\d{5,6}_SFN\d{7}_\w{2}\d{3}.dgn$")


culvert_file_pattern = re.compile(r"\d{5,6}_CFN\d{7}_\w{2}\d{3}.dgn$")


wall_file_pattern = re.compile(r"\d{5,6}_WALL\d{3}_\w{2}\d{3}.dgn$")


def filter_files_by_category(file_list, label_set):
    """
    Takes a list of files, and determines if any of them contain the labels specific to bridge files from ODOT CADD
    standards.

    :param file_list:
        An unfiltered list of all files to be searched
    :param label_set:
        The category of file you want returned, from the keys in the "all_labels" dictionary above
    :return category_files: a list of files containing relevant category info
    """

    temp_list = []
    category_files = []

    # Builds a list of all files containing the strings in 'bridge labels'
    for file in file_list:
        for label in label_set:
            if label in os.path.basename(file):
                temp_list.append(file)
            else:
                pass

    # Drop "EngData" folder files, generally contains reference files, not project ones
    for file in temp_list:
        if "EngData" not in file:
            category_files.append(file)
        else:
            pass

    return category_files


odot_counties_by_district = {
    1: [
        "ALLEN",
        "DEFIANCE",
        "HANCOCK",
        "HARDIN",
        "PAULDING",
        "PUTNAM",
        "VAN WERT",
        "WYANDOT",
    ],
    2: ["FULTON", "HENRY", "LUCAS", "OTTAWA", "SANDUSKY", "SENECA", "WILLIAMS", "WOOD"],
    3: [
        "ASHLAND",
        "CRAWFORD",
        "ERIE",
        "HURON",
        "LORAIN",
        "MEDINA",
        "RICHLAND",
        "WAYNE",
    ],
    4: ["ASHTABULA", "MAHONING", "PORTAGE", "STARK", "SUMMIT", "TRUMBULL"],
    5: ["COSHOCTON", "FAIRFIELD", "GUERNSEY", "KNOX", "LICKING", "MUSKINGUM", "PERRY"],
    6: [
        "DELAWARE",
        "FAYETTE",
        "FRANKLIN",
        "MADISON",
        "MARION",
        "MORROW",
        "PICKAWAY",
        "UNION",
    ],
    7: [
        "AUGLAIZE",
        "CHAMPAIGN",
        "CLARK",
        "DARKE",
        "LOGAN",
        "MERCER",
        "MIAMI",
        "MONTGOMERY",
        "SHELBY",
    ],
    8: ["BUTLER", "CLERMONT", "CLINTON", "GREENE", "HAMILTON", "PREBLE", "WARREN"],
    9: ["ADAMS", "BROWN", "HIGHLAND", "JACKSON", "LAWRENCE", "PIKE", "ROSS", "SCIOTO"],
    10: [
        "ATHENS",
        "GALLIA",
        "HOCKING",
        "MEIGS",
        "MONROE",
        "MORGAN",
        "NOBLE",
        "VINTON",
        "WASHINGTON",
    ],
    11: [
        "BELMONT",
        "CARROLL",
        "COLUMBIANA",
        "HARRISON",
        "HOLMES",
        "JEFFERSON",
        "TUSCARAWAS",
    ],
    12: ["CUYAHOGA", "GEAUGA", "LAKE"],
}


ohio_counties = {
    "ADAMS": "ADA",
    "ALLEN": "ALL",
    "ASHLAND": "ASD",
    "ASHTABULA": "ATB",
    "ATHENS": "ATH",
    "AUGLAIZE": "AUG",
    "BELMONT": "BEL",
    "BROWN": "BRO",
    "BUTLER": "BUT",
    "CARROLL": "CAR",
    "CHAMPAIGN": "CHP",
    "CLARK": "CLA",
    "CLERMONT": "CLE",
    "CLINTON": "CLI",
    "COLUMBIANA": "COL",
    "COSHOCTON": "COS",
    "CRAWFORD": "CRA",
    "CUYAHOGA": "CUY",
    "DARKE": "DAR",
    "DEFIANCE": "DEF",
    "DELAWARE": "DEL",
    "ERIE": "ERI",
    "FAIRFIELD": "FAI",
    "FAYETTE": "FAY",
    "FRANKLIN": "FRA",
    "FULTON": "FUL",
    "GALLIA": "GAL",
    "GEAUGA": "GEA",
    "GREENE": "GRE",
    "GUERNSEY": "GUE",
    "HAMILTON": "HAM",
    "HANCOCK": "HAN",
    "HARDIN": "HAR",
    "HARRISON": "HAS",
    "HENRY": "HEN",
    "HIGHLAND": "HIG",
    "HOCKING": "HOC",
    "HOLMES": "HOL",
    "HURON": "HUR",
    "JACKSON": "JAC",
    "JEFFERSON": "JEF",
    "KNOX": "KNO",
    "LAKE": "LAK",
    "LAWRENCE": "LAW",
    "LICKING": "LIC",
    "LOGAN": "LOG",
    "LORAIN": "LOR",
    "LUCAS": "LUC",
    "MADISON": "MAD",
    "MAHONING": "MAH",
    "MARION": "MAR",
    "MEDINA": "MED",
    "MEIGS": "MEG",
    "MERCER": "MER",
    "MIAMI": "MIA",
    "MONROE": "MOE",
    "MONTGOMERY": "MOT",
    "MORGAN": "MRG",
    "MORROW": "MRW",
    "MUSKINGUM": "MUS",
    "NOBLE": "NOB",
    "OTTAWA": "OTT",
    "PAULDING": "PAU",
    "PERRY": "PER",
    "PICKAWAY": "PIC",
    "PIKE": "PIK",
    "PORTAGE": "POR",
    "PREBLE": "PRE",
    "PUTNAM": "PUT",
    "RICHLAND": "RIC",
    "ROSS": "ROS",
    "SANDUSKY": "SAN",
    "SCIOTO": "SCI",
    "SENECA": "SEN",
    "SHELBY": "SHE",
    "STARK": "STA",
    "SUMMIT": "SUM",
    "TRUMBULL": "TRU",
    "TUSCARAWAS": "TUS",
    "UNION": "UNI",
    "VAN WERT": "VAN",
    "VINTON": "VIN",
    "WARREN": "WAR",
    "WASHINGTON": "WAS",
    "WAYNE": "WAY",
    "WILLIAMS": "WIL",
    "WOOD": "WOO",
    "WYANDOT": "WYA",
}


NBIS_state_codes = {
    "014": "Alabama",
    "308": "Montana",
    "020": "Alaska",
    "317": "Nebraska",
    "049": "Arizona",
    "329": "Nevada",
    "056": "Arkansas",
    "331": "New Hampshire",
    "069": "Californ",
    "342": "New Jersey",
    "088": "Colorado",
    "356": "New Mexico",
    "091": "Connecti",
    "362": "New York",
    "103": "Delaware",
    "374": "North Carolina",
    "113": "District of Columbia",
    "388": "North Dakota",
    "124": "Florida",
    "395": "Ohio",
    "134": "Georgia",
    "406": "Oklahoma",
    "159": "Hawaii",
    "410": "Oregon",
    "160": "Idaho",
    "423": "Pennsylvania",
    "175": "Illinois",
    "441": "Rhode Island",
    "185": "Indiana",
    "454": "South Carolina",
    "197": "Iowa",
    "468": "South Dakota",
    "207": "Kansas",
    "474": "Tennessee",
    "214": "Kentucky",
    "486": "Texas",
    "226": "Louisiana",
    "498": "Utah",
    "231": "Maine",
    "501": "Vermont",
    "243": "Maryland",
    "513": "Virginia",
    "251": "Massachusetts",
    "530": "Washington",
    "265": "Michigan",
    "543": "West Virginia",
    "275": "Minnesota",
    "555": "Wisconsin",
    "284": "Mississippi",
    "568": "Wyoming",
    "297": "Missouri",
    "721": "Puerto Rico",
}


def get_bridge_data_from_tims(sfn: str = "6500609"):
    """
    Function to return Bridge data from ODOT TIMS REST server

    :param:
        sfn (str): Bridge structure file number

    :return: A dictionary containing all the values relevant to the desired bridge
    """

    url_1 = f"https://gis.dot.state.oh.us/arcgis/rest/services/TIMS/Assets/MapServer/5/query?where=sfn%3D{sfn}&text=&ob"
    url_2 = "jectIds=&time=&geometry=&geometryType=esriGeometryEnvelope&inSR=&spatialRel=esriSpatialRelIntersects&relat"
    url_3 = "ionParam=&outFields=&returnGeometry=true&returnTrueCurves=false&maxAllowableOffset=&geometryPrecision=&out"
    url_4 = "SR=&having=&returnIdsOnly=true&returnCountOnly=false&orderByFields=&groupByFieldsForStatistics=&outStatist"
    url_5 = "ics=&returnZ=false&returnM=false&gdbVersion=&historicMoment=&returnDistinctValues=false&resultOffset=&resu"
    url_6 = "ltRecordCount=&queryByDistance=&returnExtentOnly=false&datumTransformation=&parameterValues=&rangeValues=&"
    url_7 = "quantizationParameters=&featureEncoding=esriDefault&f=html"

    url = url_1 + url_2 + url_3 + url_4 + url_5 + url_6 + url_7

    s = requests.Session()
    page = s.get(url, timeout=5)
    soup = BeautifulSoup(page.content, "html5lib")
    s.close()

    bridge_link = soup.find_all("a")

    full_data_url = "https://gis.dot.state.oh.us/" + bridge_link[-1].get("href")
    full_data_url_json = full_data_url + "?f=pjson"

    print(f"\nRetrieving data from url at {full_data_url_json}\n")

    page = s.get(full_data_url_json)
    data_json = json.loads(page.content)
    s.close()

    extracted_data = data_json["feature"]["attributes"]

    return extracted_data


class TimsBridge:
    """
    General Bridge object to hold data from ODOT TIMS REST SERVER, also contains
    mapping function which can be used in jupyter to determine location
    """

    def __init__(self, sfn):
        print("\nTIMS Bridge Initiated\n")
        self.SFN = sfn

        raw_data = get_bridge_data_from_tims(sfn)

        # This could be replaced with a looped function, but it was breaking IDE autocompletes in an annoying way
        self.objectid = raw_data["OBJECTID"]
        self.sfn = raw_data["SFN"]
        self.str_loc_carried = raw_data["STR_LOC_CARRIED"]
        self.rte_on_brg_cd = raw_data["RTE_ON_BRG_CD"]
        self.district = raw_data["DISTRICT"]
        self.county_cd = raw_data["COUNTY_CD"]
        self.invent_spcl_dsgt = raw_data["INVENT_SPCL_DSGT"]
        self.fips_cd = raw_data["FIPS_CD"]
        self.invent_on_und_cd = raw_data["INVENT_ON_UND_CD"]
        self.invent_hwy_sys_cd = raw_data["INVENT_HWY_SYS_CD"]
        self.invent_hwy_dsgt_cd = raw_data["INVENT_HWY_DSGT_CD"]
        self.invent_dir_sfx_cd = raw_data["INVENT_DIR_SFX_CD"]
        self.invent_feat = raw_data["INVENT_FEAT"]
        self.str_loc = raw_data["STR_LOC"]
        self.latitude_dd = raw_data["LATITUDE_DD"]
        self.longitude_dd = raw_data["LONGITUDE_DD"]
        self.brdr_brg_state = raw_data["BRDR_BRG_STATE"]
        self.brdr_brg_pct_resp = raw_data["BRDR_BRG_PCT_RESP"]
        self.brdr_brg_sfn = raw_data["BRDR_BRG_SFN"]
        self.main_str_mtl_cd = raw_data["MAIN_STR_MTL_CD"]
        self.main_str_type_cd = raw_data["MAIN_STR_TYPE_CD"]
        self.apprh_str_mtl_cd = raw_data["APPRH_STR_MTL_CD"]
        self.apprh_str_type_cd = raw_data["APPRH_STR_TYPE_CD"]
        self.main_spans = raw_data["MAIN_SPANS"]
        self.apprh_spans = raw_data["APPRH_SPANS"]
        self.deck_cd = raw_data["DECK_CD"]
        self.deck_prot_extl_cd = raw_data["DECK_PROT_EXTL_CD"]
        self.deck_prot_int_cd = raw_data["DECK_PROT_INT_CD"]
        self.wear_surf_dt = raw_data["WEAR_SURF_DT"]
        self.wearing_surf_cd = raw_data["WEARING_SURF_CD"]
        self.wearing_surf_thck = raw_data["WEARING_SURF_THCK"]
        self.paint_dt = raw_data["PAINT_DT"]
        self.yr_built = raw_data["YR_BUILT"]
        self.maj_recon_dt = raw_data["MAJ_RECON_DT"]
        self.type_serv1_cd = raw_data["TYPE_SERV1_CD"]
        self.type_serv2_cd = raw_data["TYPE_SERV2_CD"]
        self.lanes_on = raw_data["LANES_ON"]
        self.lanes_und = raw_data["LANES_UND"]
        self.invent_rte_adt = raw_data["INVENT_RTE_ADT"]
        self.bypass_len = raw_data["BYPASS_LEN"]
        self.nbis_len_sw = raw_data["NBIS_LEN_SW"]
        self.invent_nhs_cd = raw_data["INVENT_NHS_CD"]
        self.func_clas_cd = raw_data["FUNC_CLAS_CD"]
        self.dfns_hwy_dsgt_sw = raw_data["DFNS_HWY_DSGT_SW"]
        self.parallel_str_cd = raw_data["PARALLEL_STR_CD"]
        self.dir_traffic_cd = raw_data["DIR_TRAFFIC_CD"]
        self.temp_str_sw = raw_data["TEMP_STR_SW"]
        self.dsgt_natl_netw_sw = raw_data["DSGT_NATL_NETW_SW"]
        self.toll_cd = raw_data["TOLL_CD"]
        self.routine_resp_cd = raw_data["ROUTINE_RESP_CD"]
        self.routine_resp_cd_2 = raw_data["ROUTINE_RESP_CD_2"]
        self.maint_resp_cd = raw_data["MAINT_RESP_CD"]
        self.maint_resp_cd_2 = raw_data["MAINT_RESP_CD_2"]
        self.insp_resp_cd = raw_data["INSP_RESP_CD"]
        self.insp_resp_cd_2 = raw_data["INSP_RESP_CD_2"]
        self.hist_sgn_cd = raw_data["HIST_SGN_CD"]
        self.nav_control_sw = raw_data["NAV_CONTROL_SW"]
        self.nav_vrt_clr = raw_data["NAV_VRT_CLR"]
        self.nav_horiz_clr = raw_data["NAV_HORIZ_CLR"]
        self.subs_fenders = raw_data["SUBS_FENDERS"]
        self.min_nav_vrt_clr = raw_data["MIN_NAV_VRT_CLR"]
        self.insp_dt = raw_data["INSP_DT"]
        self.dsgt_insp_freq = raw_data["DSGT_INSP_FREQ"]
        self.frac_crit_insp_sw = raw_data["FRAC_CRIT_INSP_SW"]
        self.fraccrit_insp_freq = raw_data["FRACCRIT_INSP_FREQ"]
        self.frac_crit_insp_dt = raw_data["FRAC_CRIT_INSP_DT"]
        self.dive_insp_sw = raw_data["DIVE_INSP_SW"]
        self.dive_insp_freq = raw_data["DIVE_INSP_FREQ"]
        self.dive_insp_dt = raw_data["DIVE_INSP_DT"]
        self.spcl_insp_sw = raw_data["SPCL_INSP_SW"]
        self.spcl_insp_freq = raw_data["SPCL_INSP_FREQ"]
        self.spcl_insp_dt = raw_data["SPCL_INSP_DT"]
        self.snooper_insp_sw = raw_data["SNOOPER_INSP_SW"]
        self.deck_summary = raw_data["DECK_SUMMARY"]
        self.deck_wear_surf = raw_data["DECK_WEAR_SURF"]
        self.deck_expn_joints = raw_data["DECK_EXPN_JOINTS"]
        self.sups_summary = raw_data["SUPS_SUMMARY"]
        self.paint = raw_data["PAINT"]
        self.subs_summary = raw_data["SUBS_SUMMARY"]
        self.chan_summary = raw_data["CHAN_SUMMARY"]
        self.subs_scour = raw_data["SUBS_SCOUR"]
        self.culvert_summary = raw_data["CULVERT_SUMMARY"]
        self.gen_appraisal = raw_data["GEN_APPRAISAL"]
        self.design_load_cd = raw_data["DESIGN_LOAD_CD"]
        self.rat_opr_load_fact = raw_data["RAT_OPR_LOAD_FACT"]
        self.rat_inv_load_cd = raw_data["RAT_INV_LOAD_CD"]
        self.rat_inv_load_fact = raw_data["RAT_INV_LOAD_FACT"]
        self.gen_opr_status = raw_data["GEN_OPR_STATUS"]
        self.brg_posting = raw_data["BRG_POSTING"]
        self.calc_str_eval = raw_data["CALC_STR_EVAL"]
        self.calc_deck_geom = raw_data["CALC_DECK_GEOM"]
        self.calc_undc = raw_data["CALC_UNDC"]
        self.ww_adequacy_cd = raw_data["WW_ADEQUACY_CD"]
        self.apprh_algn_cd = raw_data["APPRH_ALGN_CD"]
        self.survey_railing = raw_data["SURVEY_RAILING"]
        self.survey_transition = raw_data["SURVEY_TRANSITION"]
        self.survey_guardrail = raw_data["SURVEY_GUARDRAIL"]
        self.survey_rail_ends = raw_data["SURVEY_RAIL_ENDS"]
        self.scour_crit_cd = raw_data["SCOUR_CRIT_CD"]
        self.max_span_len = raw_data["MAX_SPAN_LEN"]
        self.ovrl_str_len = raw_data["OVRL_STR_LEN"]
        self.sidw_wd_l = raw_data["SIDW_WD_L"]
        self.sidw_wd_r = raw_data["SIDW_WD_R"]
        self.brg_rdw_wd = raw_data["BRG_RDW_WD"]
        self.deck_wd = raw_data["DECK_WD"]
        self.apprh_rdw_wd = raw_data["APPRH_RDW_WD"]
        self.median_cd = raw_data["MEDIAN_CD"]
        self.skew_deg = raw_data["SKEW_DEG"]
        self.flared_sw = raw_data["FLARED_SW"]
        self.min_horiz_clr_c = raw_data["MIN_HORIZ_CLR_C"]
        self.minvrt_undclr_c = raw_data["MINVRT_UNDCLR_C"]
        self.impr_typ_work_cd = raw_data["IMPR_TYP_WORK_CD"]
        self.impr_typ_means_cd = raw_data["IMPR_TYP_MEANS_CD"]
        self.impr_lng = raw_data["IMPR_LNG"]
        self.impr_brg_cost = raw_data["IMPR_BRG_COST"]
        self.impr_rdw_cost = raw_data["IMPR_RDW_COST"]
        self.impr_tot_proj_cost = raw_data["IMPR_TOT_PROJ_COST"]
        self.impr_cost_est_yr = raw_data["IMPR_COST_EST_YR"]
        self.future_adt = raw_data["FUTURE_ADT"]
        self.future_adt_yr = raw_data["FUTURE_ADT_YR"]
        self.dedicated_nme = raw_data["DEDICATED_NME"]
        self.invent_pref_rte = raw_data["INVENT_PREF_RTE"]
        self.major_brg_sw = raw_data["MAJOR_BRG_SW"]
        self.invent_county = raw_data["INVENT_COUNTY"]
        self.seismic_suscept_cd = raw_data["SEISMIC_SUSCEPT_CD"]
        self.gasb_34_sw = raw_data["GASB_34_SW"]
        self.aperture_fabr_sw = raw_data["APERTURE_FABR_SW"]
        self.aperture_orig_sw = raw_data["APERTURE_ORIG_SW"]
        self.aperture_rep_sw = raw_data["APERTURE_REP_SW"]
        self.orig_proj_nbr = raw_data["ORIG_PROJ_NBR"]
        self.std_drw_nbr = raw_data["STD_DRW_NBR"]
        self.microfilm_nbr = raw_data["MICROFILM_NBR"]
        self.remarks = raw_data["REMARKS"]
        self.utl_electric_sw = raw_data["UTL_ELECTRIC_SW"]
        self.utl_gas_sw = raw_data["UTL_GAS_SW"]
        self.utl_sewer_sw = raw_data["UTL_SEWER_SW"]
        self.nbis_bridge_length = raw_data["NBIS_BRIDGE_LENGTH"]
        self.rte_und_brg_cd = raw_data["RTE_UND_BRG_CD"]
        self.load_rat_pct = raw_data["LOAD_RAT_PCT"]
        self.load_rat_yr = raw_data["LOAD_RAT_YR"]
        self.rating_soft_cd = raw_data["RATING_SOFT_CD"]
        self.catwalks_sw = raw_data["CATWALKS_SW"]
        self.retire_reason_cd = raw_data["RETIRE_REASON_CD"]
        self.rec_add_dt = raw_data["REC_ADD_DT"]
        self.mpo_cd = raw_data["MPO_CD"]
        self.temp_subdecking_sw = raw_data["TEMP_SUBDECKING_SW"]
        self.apprh_slab_sw = raw_data["APPRH_SLAB_SW"]
        self.median_typ1_cd = raw_data["MEDIAN_TYP1_CD"]
        self.median_typ2_cd = raw_data["MEDIAN_TYP2_CD"]
        self.median_typ3_cd = raw_data["MEDIAN_TYP3_CD"]
        self.railing_typ_cd = raw_data["RAILING_TYP_CD"]
        self.composite_str_cd = raw_data["COMPOSITE_STR_CD"]
        self.elas_strp_trou2_sw = raw_data["ELAS_STRP_TROU2_SW"]
        self.elas_strp_trou3_sw = raw_data["ELAS_STRP_TROU3_SW"]
        self.fencing_sw = raw_data["FENCING_SW"]
        self.glare_screen_sw = raw_data["GLARE_SCREEN_SW"]
        self.noise_barrier_sw = raw_data["NOISE_BARRIER_SW"]
        self.deck_area = raw_data["DECK_AREA"]
        self.curb_sidw_mtl_l = raw_data["CURB_SIDW_MTL_L"]
        self.curb_sidw_mtl_r = raw_data["CURB_SIDW_MTL_R"]
        self.curb_sidw_typ_l = raw_data["CURB_SIDW_TYP_L"]
        self.curb_sidw_typ_r = raw_data["CURB_SIDW_TYP_R"]
        self.hinge_cd = raw_data["HINGE_CD"]
        self.deck_drn_cd = raw_data["DECK_DRN_CD"]
        self.deck_conc_typ_cd = raw_data["DECK_CONC_TYP_CD"]
        self.expn_joint1_cd = raw_data["EXPN_JOINT1_CD"]
        self.expn_joint2_cd = raw_data["EXPN_JOINT2_CD"]
        self.expn_joint3_cd = raw_data["EXPN_JOINT3_CD"]
        self.horiz_crv_radius = raw_data["HORIZ_CRV_RADIUS"]
        self.bearing_device1_cd = raw_data["BEARING_DEVICE1_CD"]
        self.bearing_device2_cd = raw_data["BEARING_DEVICE2_CD"]
        self.framing_typ_cd = raw_data["FRAMING_TYP_CD"]
        self.haunch_gird_sw = raw_data["HAUNCH_GIRD_SW"]
        self.long_memb_typ_cd = raw_data["LONG_MEMB_TYP_CD"]
        self.main_mem_cd = raw_data["MAIN_MEM_CD"]
        self.str_steel_prot_cd = raw_data["STR_STEEL_PROT_CD"]
        self.pred_str_steel_typ = raw_data["PRED_STR_STEEL_TYP"]
        self.paint_surface_area = raw_data["PAINT_SURFACE_AREA"]
        self.str_steel_paint_cd = raw_data["STR_STEEL_PAINT_CD"]
        self.post_tension_sw = raw_data["POST_TENSION_SW"]
        self.abut_fwd_typ_cd = raw_data["ABUT_FWD_TYP_CD"]
        self.abut_fwd_matl_cd = raw_data["ABUT_FWD_MATL_CD"]
        self.abut_fwd_cd = raw_data["ABUT_FWD_CD"]
        self.abut_rear_typ_cd = raw_data["ABUT_REAR_TYP_CD"]
        self.abut_rear_matl_cd = raw_data["ABUT_REAR_MATL_CD"]
        self.abut_rear_cd = raw_data["ABUT_REAR_CD"]
        self.pred_pier_typ_cd = raw_data["PRED_PIER_TYP_CD"]
        self.pred_pier_matl_cd = raw_data["PRED_PIER_MATL_CD"]
        self.pier_pred_cd = raw_data["PIER_PRED_CD"]
        self.pier_1_typ_cd = raw_data["PIER_1_TYP_CD"]
        self.pier_1_matl_cd = raw_data["PIER_1_MATL_CD"]
        self.pier_oth1_cd = raw_data["PIER_OTH1_CD"]
        self.slope_prot_typ_cd = raw_data["SLOPE_PROT_TYP_CD"]
        self.culvert_typ_cd = raw_data["CULVERT_TYP_CD"]
        self.culvert_len = raw_data["CULVERT_LEN"]
        self.culvert_fill_depth = raw_data["CULVERT_FILL_DEPTH"]
        self.scenic_waterway_sw = raw_data["SCENIC_WATERWAY_SW"]
        self.chan_prot_type_cd = raw_data["CHAN_PROT_TYPE_CD"]
        self.stream_velocity = raw_data["STREAM_VELOCITY"]
        self.hist_typ_cd = raw_data["HIST_TYP_CD"]
        self.hist_builder_cd = raw_data["HIST_BUILDER_CD"]
        self.suff_rating = raw_data["SUFF_RATING"]
        self.defic_func_rating = raw_data["DEFIC_FUNC_RATING"]
        self.main_str_descr_cd = raw_data["MAIN_STR_DESCR_CD"]
        self.apprh_str_descr_cd = raw_data["APPRH_STR_DESCR_CD"]
        self.hist_build_yr = raw_data["HIST_BUILD_YR"]
        self.nlfid = raw_data["NLFID"]
        self.ctl_begin_nbr = raw_data["CTL_BEGIN_NBR"]
        self.route_type = raw_data["ROUTE_TYPE"]
        self.route_nbr = raw_data["ROUTE_NBR"]
        self.route_suffix = raw_data["ROUTE_SUFFIX"]
        self.routine_insp_due = raw_data["ROUTINE_INSP_DUE"]
        self.frac_crit_insp_due = raw_data["FRAC_CRIT_INSP_DUE"]
        self.dive_insp_due = raw_data["DIVE_INSP_DUE"]
        self.spcl_insp_due = raw_data["SPCL_INSP_DUE"]
        self.bia_report = raw_data["BIA_REPORT"]
        self.state_route_br_photos = raw_data["STATE_ROUTE_BR_PHOTOS"]
        self.jurisdiction = raw_data["JURISDICTION"]
        self.divided_hwy = raw_data["DIVIDED_HWY"]
        self.access_control = raw_data["ACCESS_CONTROL"]
        self.urban_area_code = raw_data["URBAN_AREA_CODE"]
        self.base_type = raw_data["BASE_TYPE"]
        self.functional_class = raw_data["FUNCTIONAL_CLASS"]
        self.hpms_sample_id = raw_data["HPMS_SAMPLE_ID"]
        self.lanes = raw_data["LANES"]
        self.maintenance_authority = raw_data["MAINTENANCE_AUTHORITY"]
        self.nhs = raw_data["NHS"]
        self.priority_system = raw_data["PRIORITY_SYSTEM"]
        self.surface_type = raw_data["SURFACE_TYPE"]
        self.surface_width = raw_data["SURFACE_WIDTH"]
        self.esal_total = raw_data["ESAL_TOTAL"]
        self.pave_type = raw_data["PAVE_TYPE"]
        self.pcr_year = raw_data["PCR_YEAR"]
        self.roadway_width_nbr = raw_data["ROADWAY_WIDTH_NBR"]
        self.created_user = raw_data["created_user"]
        self.created_date = raw_data["created_date"]
        self.last_edited_user = raw_data["last_edited_user"]
        self.last_edited_date = raw_data["last_edited_date"]

        self.photo_url = ""
        self.plan_sets_list = []

        self.latitude = self.latitude_dd
        self.longitude = self.longitude_dd

        self.map = self.get_map()

    def get_map(self):
        """
        Mapping function using folium JS package,

        :return:
            Folium javascript map object
        """
        import folium

        f = folium.Figure(width=1500, height=700)

        m = folium.Map(
            width=1500,
            height=700,
            location=[self.latitude, self.longitude],
            zoom_start=14,
        ).add_to(f)

        folium.Marker(
            location=[self.latitude, self.longitude],
            popup=f"{self.sfn}<br><br>Lat: {self.latitude}<br>Long: {self.longitude}",
            tooltip=self.sfn,
            icon=folium.Icon(icon="info-sign"),
        ).add_to(m)

        return m


def get_3_digit_st_cd_from_2(code):
    for key, value in NBIS_state_codes.items():
        if key[:-1] == str(code):
            code = key

    return code


def state_code_conversion(code):
    """
    Takes in a bridge number, returns converted state code from index lookup

    returns converted value, since this is written for Ohio, 39
    """
    if len(str(code)) == 2:
        state_code = NBIS_state_codes[get_3_digit_st_cd_from_2(code)]
    else:
        state_code = NBIS_state_codes[code]

    return state_code


def get_project_data_from_tims(pid: str = "96213"):
    """
    Uses the TIMS REST API to return json values for a given bridge sfn.

    :parameter
        pid (str): Project ID number used to look up project points (PID)

    :returns:
        dict containing the project points and the number of points
    """

    url_1 = f"https://gis.dot.state.oh.us/arcgis/rest/services/TIMS/Projects/MapServer/0/query?where=PID_NBR%3D{pid}&te"
    url_2 = "xt=&objectIds=&time=&geometry=&geometryType=esriGeometryEnvelope&inSR=&spatialRel=esriSpatialRelIntersects"
    url_3 = "&relationParam=&outFields=&returnGeometry=true&returnTrueCurves=false&maxAllowableOffset=&geometryPrecisio"
    url_4 = "n=&outSR=&having=&returnIdsOnly=true&returnCountOnly=false&orderByFields=&groupByFieldsForStatistics=&outS"
    url_5 = "tatistics=&returnZ=false&returnM=false&gdbVersion=&historicMoment=&returnDistinctValues=false&resultOffset"
    url_6 = "&resultRecordCount=&queryByDistance=&returnExtentOnly=false&datumTransformation=&parameterValues=&rangeVal"
    url_7 = "ues=&quantizationParameters=&featureEncoding=esriDefault&f=html"

    url = url_1 + url_2 + url_3 + url_3 + url_4 + url_5 + url_6 + url_7

    s = requests.Session()
    page = s.get(url)
    url_base = "https://gis.dot.state.oh.us"
    soup = BeautifulSoup(page.content, "html5lib")
    s.close()

    all_page_links = soup.find_all("a")
    project_point_links = {}
    counter = 0

    for link in all_page_links:
        if link.text.isnumeric():
            counter += 1
            full_data_url = url_base + link.get("href") + "?f=pjson"
            print(f"\nRetrieving data from url at {full_data_url}")

            page = s.get(full_data_url)
            # Added ordered dict value to attempt to return values in same order
            # noinspection PyTypeChecker
            data_json = page.json(object_pairs_hook=OrderedDict)
            s.close()

            try:
                extracted_data = data_json["feature"]["attributes"]
            except KeyError:
                return data_json

            project_point_links[link.text] = extracted_data

        else:
            pass

    project_point_links["no_of_pts"] = counter

    return project_point_links


class Project:
    def __init__(self, pid: str = "96213"):
        self.PID = pid
        raw_data = get_project_data_from_tims(pid)
        # Uses the first point returned from the query to set the general class attributes
        single_dict = raw_data[list(raw_data.keys())[0]]

        self.objectid = single_dict["ObjectID"]
        self.gis_id = single_dict["GIS_ID"]
        self.pid_nbr = single_dict["PID_NBR"]
        self.district_nbr = single_dict["DISTRICT_NBR"]
        self.locale_short_nme = single_dict["LOCALE_SHORT_NME"]
        self.county_nme = single_dict["COUNTY_NME"]
        self.project_nme = single_dict["PROJECT_NME"]
        self.contract_type = single_dict["CONTRACT_TYPE"]
        self.primary_fund_category_txt = single_dict["PRIMARY_FUND_CATEGORY_TXT"]
        self.project_manager_nme = single_dict["PROJECT_MANAGER_NME"]
        self.reservoir_year = single_dict["RESERVOIR_YEAR"]
        self.tier = single_dict["TIER"]
        self.odot_letting = single_dict["ODOT_LETTING"]
        self.schedule_type_short_nme = single_dict["SCHEDULE_TYPE_SHORT_NME"]
        self.env_project_manager_nme = single_dict["ENV_PROJECT_MANAGER_NME"]
        self.area_engineer_nme = single_dict["AREA_ENGINEER_NME"]
        self.project_engineer_nme = single_dict["PROJECT_ENGINEER_NME"]
        self.design_agency = single_dict["DESIGN_AGENCY"]
        self.sponsoring_agency = single_dict["SPONSORING_AGENCY"]
        self.pdp_short_name = single_dict["PDP_SHORT_NAME"]
        self.primary_work_category = single_dict["PRIMARY_WORK_CATEGORY"]
        self.project_status = single_dict["PROJECT_STATUS"]
        self.fiscal_year = single_dict["FISCAL_YEAR"]
        self.inhouse_design_full_nme = single_dict["INHOUSE_DESIGN_FULL_NME"]
        self.est_total_constr_cost = single_dict["EST_TOTAL_CONSTR_COST"]
        self.state_project_nbr = single_dict["STATE_PROJECT_NBR"]
        self.constr_vendor_nme = single_dict["CONSTR_VENDOR_NME"]
        self.stip_flag = single_dict["STIP_FLAG"]
        self.current_stip_co_amt = single_dict["CURRENT_STIP_CO_AMT"]
        self.project_plans_url = single_dict["PROJECT_PLANS_URL"]
        self.project_addenda_url = single_dict["PROJECT_ADDENDA_URL"]
        self.project_proposal_url = single_dict["PROJECT_PROPOSAL_URL"]
        self.fmis_proj_desc = single_dict["FMIS_PROJ_DESC"]
        self.award_milestone_dt = single_dict["AWARD_MILESTONE_DT"]
        self.begin_constr_milestone_dt = single_dict["BEGIN_CONSTR_MILESTONE_DT"]
        self.end_constr_milestone_dt = single_dict["END_CONSTR_MILESTONE_DT"]
        self.open_traffic_dt = single_dict["OPEN_TRAFFIC_DT"]
        self.central_office_close_dt = single_dict["CENTRAL_OFFICE_CLOSE_DT"]
        self.source_last_updated = single_dict["SOURCE_LAST_UPDATED"]
        self.cod_last_updated = single_dict["COD_LAST_UPDATED"]
        self.preserv_funds_ind = single_dict["PRESERV_FUNDS_IND"]
        self.major_brg_funds_ind = single_dict["MAJOR_BRG_FUNDS_IND"]
        self.major_new_funds_ind = single_dict["MAJOR_NEW_FUNDS_IND"]
        self.major_rehab_funds_ind = single_dict["MAJOR_REHAB_FUNDS_IND"]
        self.mpo_funds_ind = single_dict["MPO_FUNDS_IND"]
        self.safety_funds_ind = single_dict["SAFETY_FUNDS_IND"]
        self.local_funds_ind = single_dict["LOCAL_FUNDS_IND"]
        self.other_funds_ind = single_dict["OTHER_FUNDS_IND"]
        self.nlf_id = single_dict["NLF_ID"]
        self.ctl_begin = single_dict["CTL_BEGIN"]
        self.ctl_end = single_dict["CTL_END"]
        self.gis_feature_type = single_dict["GIS_FEATURE_TYPE"]
        self.route_type = single_dict["ROUTE_TYPE"]
        self.route_id = single_dict["ROUTE_ID"]
        self.structure_file_nbr = single_dict["STRUCTURE_FILE_NBR"]
        self.main_structure_type = single_dict["MAIN_STRUCTURE_TYPE"]
        self.sufficiency_rating = single_dict["SUFFICIENCY_RATING"]
        self.ovrl_structure_length = single_dict["OVRL_STRUCTURE_LENGTH"]
        self.deck_area = single_dict["DECK_AREA"]
        self.deck_width = single_dict["DECK_WIDTH"]
        self.feature_intersect = single_dict["FEATURE_INTERSECT"]
        self.year_built = single_dict["YEAR_BUILT"]
        self.longitude_begin_nbr = single_dict["LONGITUDE_BEGIN_NBR"]
        self.latitude_begin_nbr = single_dict["LATITUDE_BEGIN_NBR"]
        self.longitude_end_nbr = single_dict["LONGITUDE_END_NBR"]
        self.latitude_end_nbr = single_dict["LATITUDE_END_NBR"]
        self.county_cd_work_location = single_dict["COUNTY_CD_WORK_LOCATION"]
        self.county_nme_work_location = single_dict["COUNTY_NME_WORK_LOCATION"]
        self.district_work_location = single_dict["DISTRICT_WORK_LOCATION"]
        self.pavement_treatment_type = single_dict["PAVEMENT_TREATMENT_TYPE"]
        self.pavement_treatment_category = single_dict["PAVEMENT_TREATMENT_CATEGORY"]
        self.created_user = single_dict["created_user"]
        self.created_date = single_dict["created_date"]
        self.last_edited_user = single_dict["last_edited_user"]
        self.last_edited_date = single_dict["last_edited_date"]
