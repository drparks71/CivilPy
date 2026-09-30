#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Ohio coordinate systems: the Ohio County Coordinate System and State Plane.

**OCCS** (ODOT L&D Manual Vol. 4, Jan 2026, Section 2100) is 88 low-distortion
projections, one per county, and "the preferred map projection for all ODOT
projects"; State Plane is used "only at the discretion of the ODOT District
Survey Operations Manager".  Every zone is NAD 83 (2011) on GRS 80, either a
Lambert Conformal Conic with one standard parallel (false N/E 100,000 m /
50,000 m) or a Transverse Mercator (false N/E 0 / 50,000 m), with its own
scale factor.  Parameters are Section 2102; each zone's test point is
Section 2103.  Grids are published in meters; ODOT work uses the U.S. survey
foot, so ``unit="us_ft"`` is the default here.

**State Plane**: the four systems ODOT's seed files use (L&D Vol. 3,
1204.3.5): OH83-NF / OH83-SF (NAD 83, EPSG 3734 / 3735) and OH83-2011-NF /
OH83-2011-SF (NAD 83 (2011), EPSG 6549 / 6551), all U.S. survey feet.

Errata found while checking every zone against its Section 2103 test point
(86 of 88 reproduce to 0.2 mm):

* Geauga (GEA): scale printed ``1.00042``; ``1.000042`` reproduces the test
  point exactly (every other zone is 1.0000xx).  Corrected below.
* Marion (MAR): parameters look regular but the test point misses by
  0.036 m in easting.  Unresolved until ODOT's published PRJ file is
  checked; the zone is kept as printed.
* Published PPM at the Morgan (MRG), Williams (WIL) and Gallia (GAL) test
  points differ from point scale x elevation factor by 4-6 ppm (median
  across all zones: 0.04 ppm); likely height or PPM typos, unresolved.

No datum transformation is applied: OCCS and the 2011 State Plane systems
share NAD 83 (2011); converting between NAD 83 realizations is out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

US_FT = 1200.0 / 3937.0  # meters per U.S. survey foot
UNITS = {"m": 1.0, "us_ft": US_FT}
GEODETIC = "+proj=longlat +ellps=GRS80 +no_defs"

STATE_PLANE_EPSG = {
    "OH83-NF": 3734,
    "OH83-SF": 3735,
    "OH83-2011-NF": 6549,
    "OH83-2011-SF": 6551,
}

_ZONE_ROWS = (
    # num, name, abbr, projection, origin lat (d, m, s), origin lon east (d, m, s), false N (m), false E (m), scale
    (1, 'Adams', 'ADA', 'LCC1', (38, 45, 0), (276, 30, 0), 100000, 50000, '1.000028'),
    (2, 'Allen', 'ALL', 'LCC1', (40, 54, 0), (275, 54, 0), 100000, 50000, '1.000032'),
    (3, 'Ashland', 'ASD', 'TM', (39, 39, 0), (277, 42, 0), 0, 50000, '1.000052'),
    (4, 'Ashtabula', 'ATB', 'LCC1', (41, 51, 0), (279, 15, 0), 100000, 50000, '1.000032'),
    (5, 'Athens', 'ATH', 'LCC1', (39, 21, 0), (277, 54, 0), 100000, 50000, '1.000033'),
    (6, 'Auglaize', 'AUG', 'LCC1', (40, 36, 0), (275, 45, 0), 100000, 50000, '1.000039'),
    (7, 'Belmont', 'BEL', 'TM', (38, 30, 0), (279, 0, 0), 0, 50000, '1.000041'),
    (8, 'Brown', 'BRO', 'TM', (37, 33, 0), (276, 0, 0), 0, 50000, '1.000036'),
    (9, 'Butler', 'BUT', 'TM', (38, 3, 0), (275, 30, 0), 0, 50000, '1.000032'),
    (10, 'Carroll', 'CAR', 'TM', (39, 15, 0), (278, 45, 0), 0, 50000, '1.000043'),
    (11, 'Champaign', 'CHP', 'LCC1', (40, 9, 0), (276, 15, 0), 100000, 50000, '1.000045'),
    (12, 'Clark', 'CLA', 'LCC1', (39, 54, 0), (276, 12, 0), 100000, 50000, '1.000045'),
    (13, 'Clermont', 'CLE', 'TM', (37, 33, 0), (275, 45, 0), 0, 50000, '1.000030'),
    (14, 'Clinton', 'CLI', 'TM', (38, 3, 0), (276, 6, 0), 0, 50000, '1.000043'),
    (15, 'Columbiana', 'COL', 'TM', (39, 24, 0), (279, 21, 0), 0, 50000, '1.000042'),
    (16, 'Coshocton', 'COS', 'LCC1', (40, 15, 0), (278, 6, 0), 100000, 50000, '1.000036'),
    (17, 'Crawford', 'CRA', 'TM', (39, 27, 0), (277, 0, 0), 0, 50000, '1.000040'),
    (18, 'Cuyahoga', 'CUY', 'TM', (40, 9, 0), (278, 15, 0), 0, 50000, '1.000029'),
    (19, 'Darke', 'DAR', 'TM', (38, 45, 0), (275, 24, 0), 0, 50000, '1.000041'),
    (20, 'Defiance', 'DEF', 'LCC1', (41, 21, 0), (275, 30, 0), 100000, 50000, '1.000031'),
    (21, 'Delaware', 'DEL', 'TM', (38, 54, 0), (276, 51, 0), 0, 50000, '1.000041'),
    (22, 'Erie', 'ERI', 'LCC1', (41, 24, 0), (277, 27, 0), 100000, 50000, '1.000027'),
    (23, 'Fairfield', 'FAI', 'LCC1', (39, 45, 0), (277, 21, 0), 100000, 50000, '1.000037'),
    (24, 'Fayette', 'FAY', 'TM', (38, 12, 0), (276, 39, 0), 0, 50000, '1.000040'),
    (25, 'Franklin', 'FRA', 'TM', (38, 24, 0), (276, 54, 0), 0, 50000, '1.000037'),
    (26, 'Fulton', 'FUL', 'LCC1', (41, 30, 0), (275, 51, 0), 100000, 50000, '1.000025'),
    (27, 'Gallia', 'GAL', 'TM', (37, 30, 0), (277, 45, 0), 0, 50000, '1.000025'),
    (28, 'Geauga', 'GEA', 'LCC1', (41, 36, 0), (278, 48, 0), 100000, 50000, '1.000042'),
    (29, 'Greene', 'GRE', 'TM', (38, 15, 0), (276, 6, 0), 0, 50000, '1.000041'),
    (30, 'Guernsey', 'GUE', 'LCC1', (40, 9, 0), (278, 27, 0), 100000, 50000, '1.000041'),
    (31, 'Hamilton', 'HAM', 'LCC1', (39, 6, 0), (275, 24, 0), 100000, 50000, '1.000026'),
    (32, 'Hancock', 'HAN', 'LCC1', (41, 3, 0), (276, 21, 0), 100000, 50000, '1.000030'),
    (33, 'Hardin', 'HAR', 'LCC1', (40, 45, 0), (276, 24, 0), 100000, 50000, '1.000042'),
    (34, 'Harrison', 'HAS', 'TM', (38, 57, 0), (278, 54, 0), 0, 50000, '1.000043'),
    (35, 'Henry', 'HEN', 'TM', (40, 3, 0), (275, 54, 0), 0, 50000, '1.000027'),
    (36, 'Highland', 'HIG', 'LCC1', (39, 9, 0), (276, 24, 0), 100000, 50000, '1.000042'),
    (37, 'Hocking', 'HOC', 'LCC1', (39, 33, 0), (277, 36, 0), 100000, 50000, '1.000034'),
    (38, 'Holmes', 'HOL', 'TM', (39, 12, 0), (278, 6, 0), 0, 50000, '1.000044'),
    (39, 'Huron', 'HUR', 'LCC1', (41, 18, 0), (277, 24, 0), 100000, 50000, '1.000037'),
    (40, 'Jackson', 'JAC', 'LCC1', (39, 3, 0), (277, 24, 0), 100000, 50000, '1.000027'),
    (41, 'Jefferson', 'JEF', 'TM', (39, 0, 0), (279, 24, 0), 0, 50000, '1.000040'),
    (42, 'Knox', 'KNO', 'LCC1', (40, 24, 0), (277, 33, 0), 100000, 50000, '1.000048'),
    (43, 'Lake', 'LAK', 'LCC1', (41, 48, 0), (278, 45, 0), 100000, 50000, '1.000031'),
    (44, 'Lawrence', 'LAW', 'LCC1', (38, 21, 0), (277, 27, 0), 100000, 50000, '1.000019'),
    (45, 'Licking', 'LIC', 'LCC1', (40, 0, 0), (277, 30, 0), 100000, 50000, '1.000041'),
    (46, 'Logan', 'LOG', 'LCC1', (40, 24, 0), (276, 15, 0), 100000, 50000, '1.000046'),
    (47, 'Lorain', 'LOR', 'LCC1', (41, 24, 0), (277, 54, 0), 100000, 50000, '1.000033'),
    (48, 'Lucas', 'LUC', 'LCC1', (41, 36, 0), (276, 21, 0), 100000, 50000, '1.000025'),
    (49, 'Madison', 'MAD', 'TM', (38, 33, 0), (276, 39, 0), 0, 50000, '1.000041'),
    (50, 'Mahoning', 'MAH', 'LCC1', (41, 9, 0), (279, 15, 0), 100000, 50000, '1.000041'),
    (51, 'Marion', 'MAR', 'LCC1', (40, 36, 0), (276, 51, 0), 100000, 50000, '1.000040'),
    (52, 'Medina', 'MED', 'LCC1', (41, 9, 0), (278, 9, 0), 100000, 50000, '1.000046'),
    (53, 'Meigs', 'MEG', 'LCC1', (39, 6, 0), (278, 0, 0), 100000, 50000, '1.000028'),
    (54, 'Mercer', 'MER', 'LCC1', (40, 36, 0), (275, 24, 0), 100000, 50000, '1.000036'),
    (55, 'Miami', 'MIA', 'TM', (38, 39, 0), (275, 45, 0), 0, 50000, '1.000042'),
    (56, 'Monroe', 'MOE', 'LCC1', (39, 36, 0), (278, 54, 0), 100000, 50000, '1.000034'),
    (57, 'Montgomery', 'MOT', 'TM', (38, 18, 0), (275, 39, 0), 0, 50000, '1.000038'),
    (58, 'Morgan', 'MRG', 'LCC1', (39, 30, 0), (278, 9, 0), 100000, 50000, '1.000032'),
    (59, 'Morrow', 'MRW', 'TM', (39, 9, 0), (277, 9, 0), 0, 50000, '1.000050'),
    (60, 'Muskingum', 'MUS', 'LCC1', (39, 57, 0), (278, 0, 0), 100000, 50000, '1.000036'),
    (61, 'Noble', 'NOB', 'LCC1', (39, 45, 0), (278, 30, 0), 100000, 50000, '1.000034'),
    (62, 'Ottawa', 'OTT', 'LCC1', (41, 30, 0), (276, 54, 0), 100000, 50000, '1.000023'),
    (63, 'Paulding', 'PAU', 'LCC1', (41, 6, 0), (275, 27, 0), 100000, 50000, '1.000029'),
    (64, 'Perry', 'PER', 'LCC1', (39, 45, 0), (277, 45, 0), 100000, 50000, '1.000038'),
    (65, 'Pickaway', 'PIC', 'LCC1', (39, 39, 0), (277, 0, 0), 100000, 50000, '1.000033'),
    (66, 'Pike', 'PIK', 'TM', (37, 42, 0), (277, 0, 0), 0, 50000, '1.000030'),
    (67, 'Portage', 'POR', 'TM', (39, 48, 0), (278, 54, 0), 0, 50000, '1.000043'),
    (68, 'Preble', 'PRE', 'TM', (38, 15, 0), (275, 21, 0), 0, 50000, '1.000042'),
    (69, 'Putnam', 'PUT', 'TM', (39, 39, 0), (275, 54, 0), 0, 50000, '1.000030'),
    (70, 'Richland', 'RIC', 'TM', (39, 30, 0), (277, 24, 0), 0, 50000, '1.000050'),
    (71, 'Ross', 'ROS', 'LCC1', (39, 21, 0), (277, 0, 0), 100000, 50000, '1.000033'),
    (72, 'Sandusky', 'SAN', 'LCC1', (41, 24, 0), (276, 54, 0), 100000, 50000, '1.000026'),
    (73, 'Scioto', 'SCI', 'LCC1', (38, 45, 0), (277, 0, 0), 100000, 50000, '1.000025'),
    (74, 'Seneca', 'SEN', 'LCC1', (41, 12, 0), (276, 51, 0), 100000, 50000, '1.000033'),
    (75, 'Shelby', 'SHE', 'TM', (38, 54, 0), (275, 45, 0), 0, 50000, '1.000042'),
    (76, 'Stark', 'STA', 'TM', (39, 24, 0), (278, 39, 0), 0, 50000, '1.000045'),
    (77, 'Summit', 'SUM', 'TM', (39, 48, 0), (278, 24, 0), 0, 50000, '1.000042'),
    (78, 'Trumbull', 'TRU', 'TM', (39, 54, 0), (279, 9, 0), 0, 50000, '1.000040'),
    (79, 'Tuscarawas', 'TUS', 'TM', (39, 3, 0), (278, 36, 0), 0, 50000, '1.000041'),
    (80, 'Union', 'UNI', 'TM', (39, 0, 0), (276, 39, 0), 0, 50000, '1.000040'),
    (81, 'Van Wert', 'VAN', 'LCC1', (40, 54, 0), (275, 24, 0), 100000, 50000, '1.000032'),
    (82, 'Vinton', 'VIN', 'LCC1', (39, 15, 0), (277, 30, 0), 100000, 50000, '1.000034'),
    (83, 'Warren', 'WAR', 'LCC1', (39, 24, 0), (275, 51, 0), 100000, 50000, '1.000035'),
    (84, 'Washington', 'WAS', 'LCC1', (39, 24, 0), (278, 36, 0), 100000, 50000, '1.000031'),
    (85, 'Wayne', 'WAY', 'TM', (39, 27, 0), (278, 6, 0), 0, 50000, '1.000045'),
    (86, 'Williams', 'WIL', 'LCC1', (41, 30, 0), (275, 27, 0), 100000, 50000, '1.000035'),
    (87, 'Wood', 'WOO', 'TM', (40, 9, 0), (276, 21, 0), 0, 50000, '1.000025'),
    (88, 'Wyandot', 'WYA', 'LCC1', (40, 51, 0), (276, 42, 0), 100000, 50000, '1.000036'),
)
_TEST_POINT_ROWS = (
    # abbr, latitude, longitude east, ellipsoid? height (m), northing (m), easting (m), PPM
    ('ADA', '38.818144069', '276.450250281', 214, '107566.1539', '45679.2268', '-4.866'),
    ('ALL', '40.787334908', '275.823570986', 211, '87490.8504', '43548.7888', '0.768'),
    ('ASD', '40.846106458', '277.703218600', 315, '132821.8672', '50271.4405', '2.649'),
    ('ATB', '41.675899042', '279.219112236', 258, '80662.6502', '47427.8867', '-3.880'),
    ('ATH', '39.413903486', '277.812449797', 170, '107098.6310', '42459.9732', '6.881'),
    ('AUG', '40.628950747', '275.861435058', 242, '103220.9704', '59428.3561', '1.131'),
    ('BEL', '40.077837578', '279.052685803', 335, '175181.6416', '54494.1157', '-11.379'),
    ('BRO', '39.218450011', '276.088621839', 263, '185214.6654', '57653.6052', '-4.611'),
    ('BUT', '39.415335978', '275.449719536', 147, '151572.5458', '45669.8245', '9.200'),
    ('CAR', '40.590520414', '278.907910283', 321, '148860.5370', '63368.2704', '-5.149'),
    ('CHP', '40.128332339', '276.251229492', 288, '97593.9738', '50104.7990', '-0.099'),
    ('CLA', '39.892166403', '276.183613378', 278, '99130.3046', '48598.4214', '1.379'),
    ('CLE', '39.088893129', '275.774212894', 214, '170826.4595', '52094.9118', '-3.485'),
    ('CLI', '39.444858150', '276.130226825', 278, '154851.2444', '52602.0777', '-0.480'),
    ('COL', '40.793380828', '279.220727929', 328, '154730.6716', '39089.3171', '-8.497'),
    ('COS', '40.287244572', '278.136545053', 196, '104136.4194', '53107.7199', '5.416'),
    ('CRA', '40.837567139', '277.069439472', 281, '154080.3404', '55856.8565', '-3.596'),
    ('CUY', '41.524743400', '278.337084936', 143, '152674.4080', '57268.7013', '7.183'),
    ('DAR', '40.090334092', '275.392569247', 283, '148814.7388', '49366.2703', '-3.467'),
    ('DEF', '41.307790458', '275.640130925', 180, '95321.5321', '61735.2867', '3.036'),
    ('DEL', '40.281234547', '277.006750399', 254, '153372.1109', '63330.9950', '3.366'),
    ('ERI', '41.396844703', '277.280297302', 156, '99663.4577', '35807.6388', '2.467'),
    ('FAI', '39.702302633', '277.331451507', 241, '94704.1594', '48409.1564', '-0.422'),
    ('FAY', '39.551060457', '276.603147753', 263, '149992.4826', '45972.8671', '-1.075'),
    ('FRA', '39.922738087', '276.987921486', 180, '169062.1703', '57516.6884', '9.429'),
    ('FUL', '41.573299359', '275.892442057', 195, '108142.0162', '53539.8416', '-4.848'),
    ('GAL', '38.985524458', '277.423541242', 185, '164949.6556', '21713.5510', '1.607'),
    ('GEA', '41.470890130', '278.826606377', 329, '85660.2347', '52222.6240', '-7.108'),
    ('GRE', '39.745908237', '276.114042449', 259, '166075.8380', '51203.6210', '0.359'),
    ('GUE', '39.999326833', '278.421217659', 210, '83269.5371', '47542.0316', '11.471'),
    ('HAM', '39.217023512', '275.495056727', 207, '112996.4174', '58209.4373', '-4.449'),
    ('HAN', '40.988278136', '276.27714164', 210, '93147.8762', '43868.7758', '-2.329'),
    ('HAR', '40.716552163', '276.308234874', 270, '96289.5565', '42246.0183', '-0.262'),
    ('HAS', '40.289326269', '278.958832029', 263, '148709.8917', '55002.8415', '2.090'),
    ('HEN', '41.332004131', '275.962062094', 173, '142369.6296', '55195.4569', '0.170'),
    ('HIG', '39.204083234', '276.360765065', 284, '106005.2449', '46610.8602', '-2.126'),
    ('HOC', '39.523096942', '277.621831449', 186, '97013.1942', '51877.2399', '4.961'),
    ('HOL', '40.564318582', '278.045358979', 233, '151491.6378', '45372.4256', '7.672'),
    ('HUR', '41.139926143', '277.416775243', 249, '82221.9470', '51408.4567', '1.819'),
    ('JAC', '39.040212689', '277.377994718', 170, '98913.6498', '48094.7896', '0.315'),
    ('JEF', '40.359676378', '279.298522328', 327, '150973.8061', '41379.7217', '-10.382'),
    ('KNO', '40.338444679', '277.528825757', 285, '93164.6765', '48200.7208', '3.815'),
    ('LAK', '41.654457413', '278.780956885', 274, '83834.8234', '52578.7184', '-8.708'),
    ('LAW', '38.433865277', '277.418694703', 137, '109310.0170', '47266.6024', '-1.500'),
    ('LIC', '40.058444239', '277.50025938', 246, '106489.6347', '50022.1315', '2.872'),
    ('LOG', '40.423218394', '276.259224806', 357, '102578.3894', '50782.8931', '-9.915'),
    ('LOR', '41.313575233', '277.837759689', 209, '90403.1471', '44788.1192', '1.350'),
    ('LUC', '41.691094889', '276.334007235', 158, '110117.9626', '48668.5633', '1.546'),
    ('MAD', '39.939058135', '276.622497158', 272, '154220.1454', '47649.2433', '-1.639'),
    ('MAH', '41.024591628', '279.157043538', 267, '86076.2899', '42181.6607', '1.461'),
    ('MAR', '40.616443558', '276.934270425', 266, '101829.4877', '57131.2979', '-1.873'),
    ('MED', '41.138014092', '278.116340569', 295, '98669.3698', '47173.8430', '-0.229'),
    ('MEG', '39.062339945', '277.981836043', 175, '95819.1324', '48427.8590', '0.821'),
    ('MER', '40.574347277', '275.428730866', 226, '97151.6638', '52432.8483', '0.621'),
    ('MIA', '40.019432502', '275.822864797', 216, '152045.9098', '56220.7034', '8.634'),
    ('MOE', '39.754003274', '278.963935445', 336, '117101.2928', '55479.4410', '-15.055'),
    ('MOT', '39.745999241', '275.665627363', 235, '160535.1715', '51339.4630', '1.086'),
    ('MRG', '39.656414515', '278.190651224', 269, '117367.5267', '53488.8250', '-12.894'),
    ('MRW', '40.559180195', '277.213288524', 333, '156473.6324', '55360.3776', '-1.920'),
    ('MUS', '39.948606770', '278.025515024', 229, '99845.6109', '52180.5373', '0.036'),
    ('NOB', '39.730338935', '278.475513822', 190, '97817.2516', '47900.7575', '4.297'),
    ('OTT', '41.519988653', '276.850598931', 143, '102221.2445', '45876.3737', '0.575'),
    ('PAU', '41.106234807', '275.426409197', 188, '100692.7005', '48018.3163', '-0.482'),
    ('PER', '39.693222939', '277.809412914', 285, '93697.5325', '55096.3247', '-6.226'),
    ('PIC', '39.562892525', '277.059567483', 182, '90330.0867', '55119.1566', '5.597'),
    ('PIK', '39.051449911', '277.083428814', 159, '150023.6330', '57222.1184', '5.676'),
    ('POR', '41.129145927', '278.769327962', 303, '147607.7014', '39026.8982', '-3.091'),
    ('PRE', '39.726178435', '275.341385608', 294, '163885.2619', '49261.4230', '-4.126'),
    ('PUT', '41.028270238', '275.849500298', 187, '153050.5543', '45752.8867', '0.864'),
    ('RIC', '40.747877646', '277.515680798', 323, '138573.9852', '59770.3075', '0.514'),
    ('ROS', '39.386265502', '276.915341066', 202, '104029.8372', '42706.1011', '1.456'),
    ('SAN', '41.334386814', '276.832970183', 163, '92714.9128', '44388.8830', '1.086'),
    ('SCI', '38.839858467', '277.148684344', 167, '109986.0674', '62909.3060', '0.023'),
    ('SEN', '41.096888217', '276.791122364', 203, '88550.0277', '45053.4094', '2.770'),
    ('SHE', '40.380402138', '275.839248975', 284, '164376.4292', '57579.1735', '-1.919'),
    ('STA', '40.782644097', '278.534589962', 313, '153537.1376', '40257.6876', '-2.943'),
    ('SUM', '41.017867794', '278.500007659', 299, '135245.5929', '58412.2441', '-4.024'),
    ('TRU', '41.301900461', '279.247364636', 247, '155686.5357', '58154.6260', '2.075'),
    ('TUS', '40.476535818', '278.511204979', 236, '158398.6929', '42470.1136', '4.664'),
    ('UNI', '40.282782209', '276.649862679', 279, '142430.1301', '49988.3217', '-3.781'),
    ('VAN', '40.851846568', '275.442825566', 206, '94653.2007', '53611.3096', '0.079'),
    ('VIN', '39.327045132', '277.552337248', 257, '108555.2247', '54512.9994', '-5.379'),
    ('WAR', '39.422958783', '275.906504512', 249, '102550.5731', '54865.6778', '-4.063'),
    ('WAS', '39.505651683', '278.530514992', 163, '111732.5574', '44023.6462', '7.121'),
    ('WAY', '40.799407774', '278.015181348', 242, '149844.4485', '42841.8534', '7.717'),
    ('WIL', '41.596816881', '275.444007235', 235, '110753.3196', '49500.3548', '-5.989'),
    ('WOO', '41.421627167', '276.362744488', 170, '141217.5224', '51065.4245', '-1.689'),
    ('WYA', '40.898457510', '276.724310194', 216, '105381.7568', '52048.5529', '2.539'),
)

#: Test points whose published values differ from the published parameters
#: (see module docstring); tolerance in meters.
TEST_POINT_TOLERANCE_M = {"MAR": 0.05}
#: Test points whose published PPM disagrees with their height/scale by > 1 ppm.
TEST_POINT_PPM_UNRESOLVED = frozenset({"MRG", "WIL", "GAL"})


def _dms(d, m, s):
    return d + m / 60.0 + s / 3600.0


@dataclass(frozen=True)
class OCCSZone:
    """One OCCS county zone (L&D Vol. 4 Section 2102)."""

    number: int
    name: str
    abbr: str
    projection: str  # "LCC1" (Lambert, one parallel) or "TM"
    origin_lat: float  # degrees
    origin_lon: float  # degrees, west negative
    false_northing_m: float
    false_easting_m: float
    scale: float

    @property
    def code(self) -> str:
        return f"OCCS-{self.abbr}"

    @property
    def proj4(self) -> str:
        common = (f"+lat_0={self.origin_lat} +lon_0={self.origin_lon} "
                  f"+x_0={self.false_easting_m} +y_0={self.false_northing_m} "
                  f"+ellps=GRS80 +units=m +no_defs")
        if self.projection == "LCC1":
            return f"+proj=lcc +lat_1={self.origin_lat} +k_0={self.scale} {common}"
        return f"+proj=tmerc +k={self.scale} {common}"


@dataclass(frozen=True)
class TestPoint:
    """A zone's published check point (L&D Vol. 4 Section 2103), meters."""

    abbr: str
    lat: float
    lon: float  # west negative
    height_m: float
    northing_m: float
    easting_m: float
    ppm: float


ZONES: dict[str, OCCSZone] = {
    abbr: OCCSZone(num, name, abbr, proj, _dms(*lat), _dms(*lon) - 360.0, float(fn), float(fe), float(k))
    for num, name, abbr, proj, lat, lon, fn, fe, k in _ZONE_ROWS
}
TEST_POINTS: dict[str, TestPoint] = {
    abbr: TestPoint(abbr, float(lat), float(lon) - 360.0, float(h), float(n), float(e), float(ppm))
    for abbr, lat, lon, h, n, e, ppm in _TEST_POINT_ROWS
}


def zone(county) -> OCCSZone:
    """OCCS zone by ODOT county abbreviation ("HAM"), name ("Hamilton") or number (31)."""
    if isinstance(county, int):
        for z in ZONES.values():
            if z.number == county:
                return z
    else:
        key = str(county).strip()
        if key.upper() in ZONES:
            return ZONES[key.upper()]
        for z in ZONES.values():
            if z.name.lower() == key.lower():
                return z
    raise KeyError(f"no OCCS zone for county {county!r}")


def _crs_text(system) -> str:
    """proj string / EPSG code for an OCCS zone, county key or State Plane name."""
    if isinstance(system, OCCSZone):
        return system.proj4
    key = str(system).strip().upper()
    if key in STATE_PLANE_EPSG:
        return f"EPSG:{STATE_PLANE_EPSG[key]}"
    if key.startswith("OCCS-"):
        key = key[5:]
    return zone(key).proj4


def _native_unit_m(system) -> float:
    """Meters per native grid unit (OCCS zones are meters, State Plane US ft)."""
    key = system if isinstance(system, OCCSZone) else str(system).strip().upper()
    return US_FT if isinstance(key, str) and key in STATE_PLANE_EPSG else 1.0


@lru_cache(maxsize=256)
def _transformer(src: str, dst: str):
    from pyproj import Transformer

    return Transformer.from_crs(src, dst, always_xy=True)


def to_grid(lat, lon, system, unit: str = "us_ft"):
    """(northing, easting) in ``unit`` for geodetic lat/lon (degrees, west negative)."""
    e, n = _transformer(GEODETIC, _crs_text(system)).transform(lon, lat)
    f = _native_unit_m(system) / UNITS[unit]
    return n * f, e * f


def to_geodetic(northing, easting, system, unit: str = "us_ft"):
    """(lat, lon) in degrees for grid northing/easting given in ``unit``."""
    f = UNITS[unit] / _native_unit_m(system)
    lon, lat = _transformer(_crs_text(system), GEODETIC).transform(easting * f, northing * f)
    return lat, lon


def grid_scale_factor(lat, lon, system) -> float:
    """Point scale factor k of the projection at lat/lon."""
    from pyproj import Proj

    crs = _crs_text(system)
    proj = Proj(crs if not crs.startswith("EPSG:") else crs)
    f = proj.get_factors(lon, lat)
    return float((f.meridional_scale + f.parallel_scale) / 2.0)


def combined_scale_factor(lat, lon, ellipsoid_height_m, system, earth_radius_m: float = 6371000.0) -> float:
    """Grid-to-ground factor: point scale times the elevation factor R / (R + h)."""
    return grid_scale_factor(lat, lon, system) * earth_radius_m / (earth_radius_m + ellipsoid_height_m)
