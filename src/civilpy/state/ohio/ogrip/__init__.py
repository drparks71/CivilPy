"""OGRIP (Ohio Geographically Referenced Information Program) data access.

This module provides tools to discover and download LiDAR and imagery data from
the Ohio Statewide Imagery Program (OSIP) / 3DEP program.

Live-verified 2026-07-13 against the OGRIP geodata download portal
(https://gis1.oit.ohio.gov/geodatadownload/): the tile index is the
``OGRIP/3DepTiles`` MapServer on ``maps.ohio.gov`` and the tiles themselves
are ZIP archives (containing the LAS) on ``gis1.oit.ohio.gov``, at a root
directory that depends on the collection year.
"""

#  CivilPy
#  Copyright (C) 2025-2026 Dane Parks
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import requests
from pathlib import Path

#: LiDAR tile index (statewide OSIP + 3DEP flights).  Fields per feature:
#: ``TileName``, ``County`` (portal directory name), ``Year``, ``Block``,
#: ``note`` ("OSIP" | "3DEP").  Native SR is EPSG:6549 (NAD83(2011) / Ohio North,
#: US survey ft, statewide extent), so queries must
#: declare their input SR explicitly.
OSIP_TILE_SERVICES = {
    "3DEP": "https://maps.ohio.gov/arcgis/rest/services/OGRIP/3DepTiles/MapServer/0",
}

#: ZIP-archive roots by collection year — mirrors ``GetRootURL`` in the
#: portal's download page.  Each tile lives at ``{root}{County}/{TileName}.zip``.
_LIDAR_ROOTS = {
    "2016": "https://gis1.oit.ohio.gov/ZIPARCHIVES_II/ELEVATION/LIDAR/Lower_Maumee/",
    "2017": "https://gis1.oit.ohio.gov/ZIPARCHIVES_III/ELEVATION/LIDAR/",
    "2018": "https://gis1.oit.ohio.gov/ZIPARCHIVES_III/ELEVATION/LIDAR/",
}
_LIDAR_ROOT_DEFAULT = "https://gis1.oit.ohio.gov/ZIPARCHIVES_III/ELEVATION/3DEP/LIDAR/"

#: Portal quirks: a couple of pre-3DEP blocks store their tiles under a
#: different directory than the County attribute says.
_COUNTY_FOLDER_FIXUPS = {
    "Maumee": "TILED_CLASS",
    "Chippewa": "ChippewaSB",
}


def tile_download_url(tile):
    """Construct the LiDAR ZIP download URL for a tile-index feature.

    Parameters
    ----------
    tile : dict
        Attribute dict from :func:`find_las_tiles` (needs ``TileName``,
        ``County`` and ``Year``).

    Returns
    -------
    str
        URL of the ZIP archive holding the tile's LAS file, e.g.
        ``https://gis1.oit.ohio.gov/ZIPARCHIVES_III/ELEVATION/3DEP/LIDAR/FRA/BS18270730.zip``.
    """
    year = str(tile.get("Year", "")).strip()
    county = str(tile.get("County", "")).strip()
    county = _COUNTY_FOLDER_FIXUPS.get(county, county)
    root = _LIDAR_ROOTS.get(year, _LIDAR_ROOT_DEFAULT)
    return f"{root}{county}/{tile['TileName']}.zip"


def find_las_tiles(bbox_wgs84, service="3DEP"):
    """Find OGRIP/3DEP LiDAR tiles intersecting the given WGS84 bbox.

    Parameters
    ----------
    bbox_wgs84 : tuple
        (xmin, ymin, xmax, ymax) in decimal degrees.
    service : str
        Key into :data:`OSIP_TILE_SERVICES` (default "3DEP") or a layer URL.

    Returns
    -------
    list[dict]
        Tile attribute dicts (``TileName``, ``County``, ``Year``, ``note``,
        ...) with the constructed download URL added under ``LAS_URL``.
        Overlapping flights both appear (e.g. a 2019 OSIP and a 2021 3DEP
        tile over the same ground); filter on ``note``/``Year`` to pick one.
    """
    xmin, ymin, xmax, ymax = bbox_wgs84
    url = OSIP_TILE_SERVICES.get(service, service)

    params = {
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",           # layer's native SR is EPSG:6549 (OH North ftUS)
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }

    resp = requests.get(f"{url}/query", params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"tile index query failed: {data['error']}")

    tiles = []
    for feat in data.get("features", []):
        attrs = feat["attributes"]
        attrs["LAS_URL"] = tile_download_url(attrs)
        tiles.append(attrs)

    return tiles


def download_las_tile(tile_url, out_path):
    """Download a LiDAR tile archive from the given OGRIP URL."""
    resp = requests.get(tile_url, stream=True, timeout=300)
    resp.raise_for_status()

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return path
