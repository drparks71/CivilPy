"""Property tests for the STAAD .std reader and its MIDAS translation.

Decks are generated (portal frame, Pratt truss, cantilever set) so the checks
hold for any geometry rather than pinning one model."""

import math

import pytest

from civilpy.structural.staad import (applied_totals, expand_list, logical_lines, read_std,
                                      staad_angle_label, staad_to_midas_xyz, to_midas)


def _deck(joints, members, *, supports="", releases="", loads="", table="", props="", extra=""):
    j = "; ".join(f"{k} {x:g} {y:g} {z:g}" for k, (x, y, z) in joints.items())
    mm = "; ".join(f"{k} {a} {b}" for k, (a, b) in members.items())
    return f"""STAAD SPACE
UNIT FEET KIP
JOINT COORDINATES
{j};
MEMBER INCIDENCES
{mm};
SUPPORTS
{supports}
{('MEMBER RELEASE' + chr(10) + releases) if releases else ''}
DEFINE MATERIAL START
ISOTROPIC STEEL
E 4.176e+006
POISSON 0.3
DENSITY 0.489024
END DEFINE MATERIAL
START USER TABLE
TABLE 1
UNIT INCHES KIP
GENERAL
P1
26.4 14 0.75 16 0.38 778.9 1328.6 0.8 90.2 158.6 10.5 6 0 0 0 0
{table}
END
UNIT INCHES KIP
MEMBER PROPERTY AMERICAN
{props or ('1 TO ' + str(max(members)) + ' UPTABLE 1 P1')}
UNIT FEET KIP
{extra}
CONSTANTS
MATERIAL STEEL ALL
{loads}
PERFORM ANALYSIS
FINISH
"""


def portal(h=12.0, w=30.0, z=0.0):
    return {1: (0, 0, z), 2: (0, h, z), 3: (w, h, z), 4: (w, 0, z)}, {1: (1, 2), 2: (2, 3), 3: (3, 4)}


def pratt(n=6, panel=10.0, h=12.0, grade=0.03):
    j, m, k = {}, {}, 1
    for i in range(n + 1):
        j[100 + i] = (i * panel, i * panel * grade, 0)
        j[200 + i] = (i * panel, h + i * panel * grade, 0)
    for i in range(n):
        m[k] = (100 + i, 101 + i); k += 1
        m[k] = (200 + i, 201 + i); k += 1
        m[k] = (100 + i, 201 + i) if i < n / 2 else (200 + i, 101 + i); k += 1
    for i in range(n + 1):
        m[k] = (100 + i, 200 + i); k += 1
    return j, m


GEOMS = {"portal": portal(), "portal_offset_z": portal(15, 40, 7.5), "pratt": pratt(), "pratt_long": pratt(9, 12.5, 15, 0.0)}


# ---------------------------------------------------------------- tokenizing
@pytest.mark.parametrize("tokens,expected", [
    ("1 TO 5", [1, 2, 3, 4, 5]),
    ("1 TO 9 BY 4 20", [1, 5, 9, 20]),
    ("7 3 1 TO 2", [7, 3, 1, 2]),
])
def test_expand_list(tokens, expected):
    assert expand_list(tokens.split()) == expected


def test_continuations_and_separators_are_joined():
    text = "* comment\n1 2 3 -\n4 5; 6 7\n"
    assert list(logical_lines(text)) == ["1 2 3 4 5", "6 7"]


@pytest.mark.parametrize("code,label", [("L40355", "L4X3-1/2X5/16"), ("L35305", "L3-1/2X3X5/16"),
                                        ("L40406", "L4X4X3/8"), ("L40305", "L4X3X5/16")])
def test_angle_codes(code, label):
    assert staad_angle_label(code) == label


# ---------------------------------------------------------------- geometry
@pytest.mark.parametrize("name", GEOMS)
def test_axes_rotation_preserves_lengths_and_keeps_ids(name):
    joints, members = GEOMS[name]
    m = read_std(_deck(joints, members, supports=f"{min(joints)} PINNED"))
    p = to_midas(m)
    assert set(map(int, p["NODE"])) == set(joints)
    assert set(map(int, p["ELEM"])) == set(members)
    for k, (a, b) in members.items():
        na, nb = p["NODE"][str(a)], p["NODE"][str(b)]
        lm = math.dist((na["X"], na["Y"], na["Z"]), (nb["X"], nb["Y"], nb["Z"]))
        assert lm == pytest.approx(math.dist(joints[a], joints[b]), abs=1e-6)
    for k, (x, y, z) in joints.items():
        assert p["NODE"][str(k)]["Z"] == pytest.approx(y)       # STAAD up -> MIDAS up


@pytest.mark.parametrize("p", [(1.0, 2.0, 3.0), (-4.0, 0.5, 9.0)])
def test_rotation_is_right_handed(p):
    ex, ey, ez = (staad_to_midas_xyz(v) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    cross = (ex[1] * ey[2] - ex[2] * ey[1], ex[2] * ey[0] - ex[0] * ey[2], ex[0] * ey[1] - ex[1] * ey[0])
    assert cross == pytest.approx(ez)


@pytest.mark.parametrize("name", GEOMS)
def test_vertical_beta_only_touches_vertical_members(name):
    joints, members = GEOMS[name]
    p = to_midas(read_std(_deck(joints, members, supports=f"{min(joints)} FIXED")), vertical_beta=90.0)
    for k, (a, b) in members.items():
        vertical = joints[a][0] == joints[b][0] and joints[a][2] == joints[b][2]
        assert (p["ELEM"][str(k)]["ANGLE"] != 0) == vertical


# ---------------------------------------------------------------- boundary
@pytest.mark.parametrize("spec,flags", [
    ("PINNED", "1110000"),
    ("FIXED", "1111110"),
    ("FIXED BUT FX MX MY MZ", "0110000"),      # free along X, held in STAAD Y (up) and Z
    ("FIXED BUT FY", "1101110"),                # STAAD FY is MIDAS DZ
    ("FIXED BUT MZ", "1111010"),                # STAAD MZ (about Z) is MIDAS RY
])
def test_support_dofs_map_to_midas(spec, flags):
    joints, members = portal()
    p = to_midas(read_std(_deck(joints, members, supports=f"1 4 {spec}")))
    assert p["CONS"]["1"]["ITEMS"][0]["CONSTRAINT"] == flags


@pytest.mark.parametrize("name", GEOMS)
def test_double_torsion_release_keeps_one_end(name):
    joints, members = GEOMS[name]
    last = max(members)
    p = to_midas(read_std(_deck(joints, members, supports=f"{min(joints)} FIXED",
                                releases=f"{last} START MX MY MZ\n{last} END MX MY MZ")))
    item = p["FRLS"][str(last)]["ITEMS"][0]
    assert item["FLAG_I"][3] == "1" and item["FLAG_J"][3] == "0"
    assert item["FLAG_I"][4:6] == "11" and item["FLAG_J"][4:6] == "11"


def test_joint_with_only_pinned_member_ends_gets_rotations_held():
    joints = {1: (0, 0, 0), 2: (10, 0, 0), 3: (20, 0, 0)}
    members = {1: (1, 2), 2: (2, 3)}
    p = to_midas(read_std(_deck(joints, members, supports="1 3 PINNED",
                                releases="1 END MX MY MZ\n2 START MX MY MZ")))
    assert p["CONS"]["2"]["ITEMS"][0]["CONSTRAINT"][3:6] == "111"


# ---------------------------------------------------------------- loads
LOADS = """LOAD 1 LOADTYPE Dead TITLE SELF WEIGHT
SELFWEIGHT Y -1
LOAD 2 LOADTYPE Dead TITLE MEMBERS
MEMBER LOAD
1 TO 3 UNI GY -0.15
2 CON GY -4 5
LOAD 3 LOADTYPE Dead TITLE JOINTS
JOINT LOAD
{j1} {j2} FY -7.5 FZ 2
LOAD COMB 4 TOTAL
1 1.0 2 1.0 3 1.25
"""


def _loads(joints):
    ks = sorted(joints)
    return LOADS.format(j1=ks[1], j2=ks[2])


def _midas_total_z(p, case_name, model):
    tot = 0.0
    for body in p.get("CNLD", {}).values():
        tot += sum(i["FZ"] for i in body["ITEMS"] if i["LCNAME"] == case_name)
    for k, body in p.get("BMLD", {}).items():
        L = model.length(int(k))
        for i in body["ITEMS"]:
            if i["LCNAME"] != case_name or i["DIRECTION"] != "GZ":
                continue
            tot += i["P"][0] * ((i["D"][1] - i["D"][0]) * L if i["TYPE"] == "UNILOAD" else 1.0)
    return tot


@pytest.mark.parametrize("name", GEOMS)
def test_vertical_load_totals_survive_translation(name):
    joints, members = GEOMS[name]
    m = read_std(_deck(joints, members, supports=f"{min(joints)} FIXED", loads=_loads(joints)))
    p = to_midas(m)
    for lc in m.loads:
        if lc.is_combination or lc.selfweight:
            continue
        assert _midas_total_z(p, f"{lc.number} {lc.title}", m) == pytest.approx(applied_totals(m, lc.number)[1])


def test_lateral_joint_load_flips_to_midas_minus_y():
    joints, members = portal()
    m = read_std(_deck(joints, members, supports="1 4 FIXED", loads=_loads(joints)))
    item = to_midas(m)["CNLD"]["2"]["ITEMS"][0]
    assert (item["FZ"], item["FY"]) == (pytest.approx(-7.5), pytest.approx(-2.0))


def test_selfweight_and_combination():
    joints, members = pratt()
    m = read_std(_deck(joints, members, supports="100 106 PINNED", loads=_loads(joints)))
    p = to_midas(m)
    assert list(p["BODF"].values())[0]["FV"] == [0.0, 0.0, -1.0]
    combo = list(p["LCOM-GEN"].values())[0]
    assert [(c["LCNAME"], c["FACTOR"]) for c in combo["vCOMB"]] == [
        ("1 SELF WEIGHT", 1.0), ("2 MEMBERS", 1.0), ("3 JOINTS", 1.25)]
    sw = applied_totals(m, 1)[1]
    expected = -0.489024 * 26.4 / 144 * sum(m.length(k) for k in members)
    assert sw == pytest.approx(expected)


# ---------------------------------------------------------------- sections
@pytest.mark.parametrize("name", GEOMS)
def test_general_table_maps_staad_axes_to_midas(name):
    joints, members = GEOMS[name]
    p = to_midas(read_std(_deck(joints, members, supports=f"{min(joints)} FIXED")))
    st = list(p["SECT"].values())[0]["SECT_BEFORE"]["SECT_I"]["STIFF"]
    assert st["AREA"] == pytest.approx(26.4 / 144)
    assert st["RYY"] == pytest.approx(778.9 / 12 ** 4)       # STAAD IZ
    assert st["RZZ"] == pytest.approx(1328.6 / 12 ** 4)      # STAAD IY
    assert st["ASZ"] == pytest.approx(10.5 / 144) and st["ASY"] == pytest.approx(6 / 144)


@pytest.mark.parametrize("d0,d1", [(27.14, 27.14), (42.125, 19.125), (30.0, 20.0)])
def test_isection_weight_is_mid_depth_prism(d0, d1):
    joints, members = portal()
    table = f"TABLE 2\nUNIT INCHES KIP\nISECTION\nI1\n{d0} 0.625 {d1} 10 0.75 10 0.375 0 0 0"
    m = read_std(_deck(joints, members, supports="1 4 FIXED", table=table, props="1 TO 3 UPTABLE 2 I1"))
    s = list(m.sections.values())[0]
    dm = (d0 + d1) / 2
    assert s.ax * 144 == pytest.approx((dm - 1.125) * 0.625 + 10 * 0.75 + 10 * 0.375)


@pytest.mark.parametrize("kind,code,sp", [("ST", "W18X50", 0), ("RA", "L35305", 0), ("LD", "L40355", 0.5),
                                          ("LD", "L40406", 0.375)])
def test_catalog_shapes(kind, code, sp):
    joints, members = portal()
    spec = f"TABLE {kind} {code}" + (f" SP {sp}" if sp else "")
    m = read_std(_deck(joints, members, supports="1 4 FIXED", props=f"1 TO 3 {spec}"))
    s = list(m.sections.values())[0]
    assert s.ax > 0 and s.iz > 0 and s.iy > 0
    if kind == "LD":                                          # two angles, gap only adds Iy
        single = read_std(_deck(joints, members, supports="1 4 FIXED", props=f"1 TO 3 TABLE ST {code}"))
        one = list(single.sections.values())[0]
        assert s.ax == pytest.approx(2 * one.ax)
        assert s.iy > 2 * min(one.iy, one.iz)


def test_master_slave_maps_dofs():
    joints = {1: (0, 0, 0), 2: (10, 0, 0), 3: (5, 2, 0)}
    members = {1: (1, 2)}
    m = read_std(_deck(joints, members, supports="1 2 PINNED", extra="SLAVE FY MX MASTER 3 JOINT 1 2"))
    rig = to_midas(m)["RIGD"]["3"]["ITEMS"][0]
    assert rig["DOF"] == int("001100") and rig["S_NODE"] == [1, 2]


@pytest.mark.parametrize("name", GEOMS)
def test_zero_loads_are_dropped(name):
    joints, members = GEOMS[name]
    loads = f"LOAD 1 TITLE Z\nMEMBER LOAD\n1 UNI GY 0\n2 UNI GY -0.1\nJOINT LOAD\n{min(joints)} FY 0\n"
    p = to_midas(read_std(_deck(joints, members, supports=f"{min(joints)} FIXED", loads=loads)))
    assert set(p["BMLD"]) == {"2"} and "CNLD" not in p


@pytest.mark.parametrize("unit,factor", [("FEET", 1.0), ("INCHES", 12.0)])
def test_load_cases_keep_the_unit_in_force(unit, factor):
    joints, members = portal()
    loads = f"UNIT {unit} KIP\nLOAD 1 TITLE U\nMEMBER LOAD\n2 UNI GY -0.1\n"
    m = read_std(_deck(joints, members, supports="1 4 FIXED", loads=loads))
    assert m.loads[0].units == f"{unit} KIP"
    assert m.loads[0].member[0][3] == pytest.approx(-0.1 * factor)
