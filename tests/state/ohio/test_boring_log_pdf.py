"""ODOT standard boring log sheet reader (civilpy.state.ohio.DOT.boring_log_pdf)
and the DIGGS writer, on a sheet drawn to the gINT geometry with PyMuPDF."""
import pytest

fitz = pytest.importorskip("fitz")

from civilpy.geotech.boring_io import parse_diggs, read_pdf_log  # noqa: E402
from civilpy.geotech.diggs_writer import write_diggs  # noqa: E402
from civilpy.state.ohio.DOT import boring_log_pdf as bl  # noqa: E402

C = bl.DEFAULT_COLUMNS
TOP, BOTTOM = 104.3, 561.5
HEADER_RULE = 82.7


def _y(depth_ft: float, page: int = 0) -> float:
    return TOP + (depth_ft - 30.0 * page) * bl.PT_PER_FT


def _sheet(page, *, hole="B-501-0-25", pageno=1, pages=1, elev=788.1, eob=51.0, continuation=False):
    """Draw the fixed parts of the sheet: header cells and labels, column rules and labels."""
    w = page.rect.width
    black = (0, 0, 0)
    page.draw_line((28.8, HEADER_RULE), (748.8, HEADER_RULE), color=black, width=0.6)
    page.draw_line((28.8, TOP), (748.8, TOP), color=black, width=0.6)
    for x in sorted({a for a, b in C.values()} | {b for a, b in C.values()}):
        if 28.8 < x < 748.8:
            page.draw_line((x, HEADER_RULE), (x, BOTTOM), color=black, width=0.4)
    for x in (190.8, 388.8, 525.6, 712.8):
        page.draw_line((x, 36), (x, HEADER_RULE), color=black, width=0.4)
    fs = 6.5
    if not continuation:
        rows = [
            [(32, "PROJECT:"), (89, "CUY-IR-071/VAR-08.84"), (194, "DRILLING FIRM / OPERATOR:DLZ AD / K. CONRAD"),
             (392, "DRILL RIG: CME 45-ATV"), (529, "STATION / OFFSET:"), (613, "1943+66, 33' LT."), (681, "EXPLORATION ID")],
            [(32, "TYPE:"), (108, "BRIDGE"), (194, "SAMPLING FIRM / LOGGER: DLZ / A. M."), (392, "HAMMER:"), (444, "CME AUTOMATIC"),
             (529, "ALIGNMENT:"), (614, "RAMP O"), (695, hole)],
            [(32, "PID:"), (59, "125149"), (97, "SFN:"), (194, "DRILLING METHOD:"), (299, '3.25" HSA / NQ2'), (392, "CALIBRATION DATE:"),
             (485, "3/24/25"), (529, "ELEVATION:"), (583, f"{elev} (MSL)"), (634, "EOB:"), (671, f"{eob} ft."), (720, "PAGE")],
            [(32, "START:"), (75, "4/8/26"), (112, "END:"), (150, "4/8/26"), (194, "SAMPLING METHOD:"), (313, "SPT / NQ2"),
             (392, "ENERGY RATIO (%):"), (490, "85.5"), (529, "LAT / LONG:"), (603, "41.403371, -81.824078"), (718, f"{pageno} OF {pages}")],
        ]
        ys = (46, 57, 68, 79)
    else:
        rows = [[(32, "PID:"), (56, "125149"), (94, "SFN:"), (191, "PROJECT:"), (244, "CUY-IR-071/VAR-08.84"), (346, "STATION / OFFSET:"),
                 (431, "1943+66, 33' LT."), (504, "START:"), (541, "4/8/26"), (576, "END:"), (609, "4/8/26"), (649, f"PG {pageno} OF {pages}"),
                 (697, hole)]]
        ys = (46,)
    for y, row in zip(ys, rows):
        for x, text in row:
            page.insert_text((x, y), text, fontsize=fs)
    labels = [("MATERIAL", 108.6), ("ELEV.", 289.2), ("DEPTHS", 332.9), ("SPT/", 388.8), ("N60", 415.6), ("REC", 434.3), ("SAMPLE", 455.3),
              ("HP", 494.8), ("ODOT", 688.1), ("HOLE", 721.7)]
    for text, x in labels:
        page.insert_text((x, 93), text, fontsize=fs)
    for text, x in (("GR", 515.7), ("CS", 534.1), ("FS", 552.4), ("SI", 571.4), ("CL", 588.4), ("LL", 606.9), ("PL", 624.5), ("PI", 643.4), ("WC", 660.9)):
        page.insert_text((x, 102), text, fontsize=fs)
    # depth scale ticks
    for d in range(1, 30):
        page.insert_text((366.3, _y(d + 30 * (pageno - 1), pageno - 1) + 3), str(d + 30 * (pageno - 1)), fontsize=fs)


def _layer(page, top, bottom, elev_top, text, pageno=1, notes=()):
    p = pageno - 1
    if top > 30 * p:
        page.draw_line((28.8, _y(top, p)), (266.4, _y(top, p)), width=0.5)
        page.insert_text((290.6, _y(top, p) - 1.5), f"{elev_top:.1f}", fontsize=6.5)
    page.insert_text((36, _y(top, p) + 8), text, fontsize=6.5)
    for k, n in enumerate(notes):
        page.insert_text((36, _y(top, p) + 16 + 8 * k), n, fontsize=6.5)


def _sample(page, sid, top, bottom, blows, *, n60="-", rec="100", hp="-", grad=None, atter=None, wc="-", cls="A-6a", gi="V", pageno=1, rqd=None):
    p = pageno - 1
    ya, yb = _y(top, p), _y(bottom, p)
    page.draw_line((453.6, ya), (489.6, ya), width=0.5)
    page.draw_line((453.6, yb), (489.6, yb), width=0.5)
    yc = 0.5 * (ya + yb) + 2.5
    page.insert_text((460, yc), sid, fontsize=6.5)
    if rqd is not None:
        page.insert_text((393, yc), str(rqd), fontsize=6.5)
    else:
        n = len(blows)
        for k, b in enumerate(blows):
            yk = ya + (k + 0.5) * (yb - ya) / n + 2.5
            page.insert_text((386.6 + 9 * k, yk), b, fontsize=6.5)
    vals = {"n60": n60, "rec": rec, "hp": hp, "wc": wc}
    for key, v in vals.items():
        page.insert_text((C[key][0] + 5, yc), v, fontsize=6.5)
    for key, v in zip(("gr", "cs", "fs", "si", "cl"), grad or ("-",) * 5):
        page.insert_text((C[key][0] + 6, yc), str(v), fontsize=6.5)
    for key, v in zip(("ll", "pl", "pi"), atter or ("-",) * 3):
        page.insert_text((C[key][0] + 6, yc), str(v), fontsize=6.5)
    page.insert_text((680, yc), cls, fontsize=6.5)
    page.insert_text((701, yc), f"({gi})", fontsize=6.5)


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    _sheet(p1, pages=2)
    _layer(p1, 0.0, 1.0, 788.1, 'Asphalt - 6" Aggregate Base - 6"')
    _layer(p1, 1.0, 3.5, 787.1, "FILL: Loose light brown GRAVEL (A-1-a); wet.")
    _layer(p1, 3.5, 6.0, 784.6, "Very stiff mottled brown and gray SILT AND CLAY (A-6a); moist.")
    _layer(p1, 6.0, 16.0, 782.1, "Very stiff brown and gray SILTY CLAY (A-6b); damp to moist.", notes=("@ 11.0' - 16.0', hard.",))
    _layer(p1, 16.0, 30.0, 772.1, "Hard gray SANDY SILT (A-4a); damp.")
    p1.insert_text((332.7, _y(12.5) + 2), "775.6", fontsize=6.5)           # water level in the depths column
    _sample(p1, "SS-1", 1.0, 2.5, ("4", "3", "3"), n60="9", rec="83", cls="A-1-a", gi="V")
    _sample(p1, "SS-2", 3.5, 5.0, ("1", "2", "3"), n60="7", hp="3.50", grad=(1, 3, 12, 39, 45), atter=(33, 19, 14), wc="20", cls="A-6a", gi="10")
    _sample(p1, "SS-3", 6.0, 7.5, ("WOH", "4", "4"), n60="11", hp="2.50", wc="21", cls="A-6b")
    _sample(p1, "SS-4", 28.5, 28.8, ('50/4"',), n60="-", rec="50", cls="Rock")
    p1.insert_text((332, _y(28.5) + 3), "TR", fontsize=6.5)
    p2 = doc.new_page(width=792, height=612)
    _sheet(p2, pageno=2, pages=2, continuation=True)
    _layer(p2, 30.0, 35.0, 758.1, "Hard gray SANDY SILT (A-4a); damp. (continued)", pageno=2)
    _layer(p2, 35.0, 51.0, 753.1, "SHALE, dark gray, slightly strong, unweathered, laminated, moderately fractured.", pageno=2)
    _sample(p2, "NQ2-1", 35.0, 36.0, (), rec="67", cls="CORE", gi="", pageno=2, rqd=67)
    _sample(p2, "NQ2-2", 36.0, 41.0, (), rec="95", cls="CORE", gi="", pageno=2, rqd=52)
    p2.draw_line((28.8, _y(51.0, 1)), (266.4, _y(51.0, 1)), width=0.5)
    p2.insert_text((329, _y(51.0, 1) + 2), "EOB", fontsize=6.5)
    # a page that is not a log sheet
    p3 = doc.new_page(width=792, height=612)
    p3.insert_text((72, 72), "Appendix II - laboratory results", fontsize=10)
    out = tmp_path_factory.mktemp("logs") / "sfe.pdf"
    doc.save(str(out))
    return out


def test_header_fields(pdf):
    logs = bl.read_log_pdf(pdf)
    assert len(logs) == 1 and logs[0].pages == [0, 1]
    h = logs[0].header
    assert h.exploration_id == "B-501-0-25" and h.pid == "125149" and h.project == "CUY-IR-071/VAR-08.84"
    assert h.ground_elevation_ft == 788.1 and h.eob_ft == 51.0 and h.pages == 2
    assert h.station == "1943+66" and h.offset_ft == 33.0 and h.offset_direction == "LT"
    assert h.latitude == 41.403371 and h.longitude == -81.824078
    assert h.hammer == "CME AUTOMATIC" and h.energy_ratio_pct == 85.5 and h.type == "BRIDGE" and h.alignment == "RAMP O"
    assert h.drilling_method == '3.25" HSA / NQ2' and h.start == "4/8/26"


def test_layers_across_pages_with_pseudo_layers_and_notes(pdf):
    log = bl.read_log_pdf(pdf)[0]
    spans = [(lay.depth_top_ft, lay.depth_bottom_ft) for lay in log.layers]
    assert spans == [(0.0, 0.5), (0.5, 1.0), (1.0, 3.5), (3.5, 6.0), (6.0, 16.0), (16.0, 35.0), (35.0, 51.0)]
    assert log.layers[0].description.startswith("Asphalt") and log.layers[1].description.startswith("Aggregate Base")
    assert log.layers[4].notes == ["@ 11.0' - 16.0', hard."]
    assert log.layers[5].description.startswith("Hard gray SANDY SILT") and "(continued)" not in log.layers[5].description
    assert log.layers[2].elevation_top_ft == 787.1
    assert log.water == [{"elevation_ft": 775.6, "depth_ft": 12.5}] and log.top_of_rock_ft == 28.5


def test_sample_rows_as_printed(pdf):
    log = bl.read_log_pdf(pdf)[0]
    rows = {r.sample_id: r for r in log.samples}
    assert list(rows) == ["SS-1", "SS-2", "SS-3", "SS-4", "NQ2-1", "NQ2-2"]
    s2 = rows["SS-2"]
    assert (s2.depth_top_ft, s2.depth_bottom_ft) == (3.5, 5.0) and s2.blows == ("1", "2", "3") and s2.n60 == 7
    assert s2.gradation == {"gr": 1, "cs": 3, "fs": 12, "si": 39, "cl": 45} and (s2.ll, s2.pl, s2.pi, s2.wc) == (33, 19, 14, 20)
    assert s2.odot_class == "A-6a" and s2.group_index == "10" and s2.hp_tsf == 3.5
    assert rows["SS-1"].gradation is None and rows["SS-1"].ll is None and rows["SS-1"].group_index == "V"
    assert rows["SS-3"].blows == ("WOH", "4", "4") and [i.blows for i in rows["SS-3"].increments()] == [0, 4, 4]
    s4 = rows["SS-4"]
    assert s4.blows == ('50/4"',) and s4.increments() == (bl.DriveIncrement(50, 4.0),) and (s4.depth_top_ft, s4.depth_bottom_ft) == (28.5, 28.8)
    c1 = rows["NQ2-1"]
    assert c1.is_core and c1.rqd_pct == 67 and c1.rec_pct == 67 and (c1.depth_top_ft, c1.depth_bottom_ft) == (35.0, 36.0)
    assert (rows["NQ2-2"].depth_top_ft, rows["NQ2-2"].depth_bottom_ft) == (36.0, 41.0)
    assert log.warnings == []


def test_borehole_and_describe(pdf):
    bh = bl.read_log_pdf(pdf)[0].to_borehole()
    assert bh.boring_id == "B-501-0-25" and bh.total_depth_ft == 51.0 and bh.water_strike_depth_ft == 12.5 and bh.depth_to_rock_ft == 28.5
    groups = [lay.group for lay in bh.layers]
    assert groups == ["pavement", "pavement", "granular", "clay", "clay", "silt", "rock"]
    clay = bh.layers[3]
    assert clay.classification == "A-6a" and clay.consistency == "very stiff" and clay.color == "mottled brown and gray"
    assert clay.constituents == ("SILT AND CLAY",) and clay.moisture == "moist"
    rock = bh.layers[-1]
    assert rock.system == "ROCK" and rock.classification == "SHALE" and rock.rock_strength == "slightly strong"
    assert rock.rock_weathering == "unweathered" and rock.color == "dark gray"
    assert rock.recovery_pct == pytest.approx((67 * 1 + 95 * 5) / 6, abs=0.1) and rock.rqd_pct == pytest.approx((67 + 52 * 5) / 6, abs=0.1)
    # SPT: the refusal spoon has one increment (no N); the others two-of-three
    assert [(s.depth_ft, s.n_value) for s in bh.spt] == [(1.0, 6), (3.5, 5), (6.0, 8), (28.5, None)]
    assert bh.spt[0].hammer_type == "CME AUTOMATIC" and bh.spt[0].hammer_efficiency == "85.5" and bh.spt[-1].refusal
    g = bh.grading[0]
    assert g.depth_ft == 3.5 and g.fines_percent == pytest.approx(84.0) and g.percent_passing_at(2.0) == pytest.approx(99.0)
    assert bh.samples[0].recovery_in == pytest.approx(0.83 * 18, abs=0.05)
    d = bl.describe("FILL: Medium dense brown GRAVEL WITH SAND, little silt, trace clay, wet.")
    assert d["consistency"] == "medium dense" and d["color"] == "brown" and d["constituents"][0] == "GRAVEL WITH SAND"
    assert "little silt" in d["constituents"] and d["moisture"] == "wet"
    assert bl.describe("Topsoil - 7\"")["classification"] == "TOPSOIL"


def test_diggs_round_trip(pdf, tmp_path):
    logs = bl.read_log_pdf(pdf)
    out = write_diggs(logs, tmp_path / "x-DIGGS.xml", project="CUY-IR-071/VAR-08.84", pid="125149", county="CUY", route="71")
    text = out.read_text(encoding="utf-8")
    assert 'codeSpace="ODOT_CS">125149<' in text and "<lithologyClassificationType>ROCK<" in text and "ATTERBERG" in text
    back = parse_diggs(str(out))
    assert len(back) == 1
    a, b = logs[0].to_borehole(), back[0]
    assert (b.boring_id, b.ground_elevation_ft, b.latitude, b.longitude, b.total_depth_ft) == (a.boring_id, 788.1, 41.403371, -81.824078, 51.0)
    assert (b.station, b.offset_ft, b.offset_direction, b.water_strike_depth_ft, b.depth_to_rock_ft, b.date, b.purpose) == \
        ("1943+66", 33.0, "LT", 12.5, 28.5, "4/8/26", "BRIDGE")
    assert [(l.depth_top_ft, l.depth_bottom_ft, l.classification, l.consistency, l.moisture, l.color) for l in b.layers] == \
        [(l.depth_top_ft, l.depth_bottom_ft, l.classification, l.consistency, l.moisture, l.color) for l in a.layers]
    assert b.layers[-1].rock_strength == "slightly strong" and b.layers[-1].rqd_pct == a.layers[-1].rqd_pct
    assert [(s.depth_ft, s.n_value, tuple((i.blows, i.penetration_in) for i in s.increments)) for s in b.spt] == \
        [(s.depth_ft, s.n_value, tuple((i.blows, i.penetration_in) for i in s.increments)) for s in a.spt]
    assert [(g.depth_ft, g.d50) for g in b.grading] == pytest.approx([(g.depth_ft, g.d50) for g in a.grading])
    assert [(s.depth_top_ft, s.depth_bottom_ft, s.method, s.recovery_in) for s in b.samples] == \
        [(s.depth_top_ft, s.depth_bottom_ft, s.method, s.recovery_in) for s in a.samples]
    # plain Borehole objects write too
    out2 = write_diggs([a], tmp_path / "plain.xml")
    assert parse_diggs(str(out2))[0].boring_id == a.boring_id


def test_read_pdf_log_entry_point_and_non_log_pdf(pdf, tmp_path):
    holes = read_pdf_log(pdf)
    assert [h.boring_id for h in holes] == ["B-501-0-25"]
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "nothing here")
    other = tmp_path / "other.pdf"
    doc.save(str(other))
    assert bl.read_log_pdf(other) == []
    with pytest.raises(ValueError, match="no ODOT log sheets"):
        read_pdf_log(other)
