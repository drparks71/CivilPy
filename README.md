# CivilPy

![PyPI - License](https://img.shields.io/pypi/l/civilpy)
<img alt="Pipeline" src="https://daneparks.com/Dane/civilpy/badges/master/pipeline.svg">
<img alt="Coverage" src="https://daneparks.com/Dane/civilpy/badges/master/coverage.svg">
<img alt="PyPI - Python Version" src="https://img.shields.io/pypi/pyversions/civilpy">
[![PyPI Downloads](https://static.pepy.tech/badge/civilpy/month)](https://pepy.tech/projects/civilpy)

Python tools for civil and structural engineering, with a focus on bridges. CivilPy covers
AASHTO LRFD design checks and MBE load rating, steel bridge evaluation and repair, line-girder
and 3-D frame analysis, hydraulics and scour, geotechnical design, roadway geometry, LiDAR
scan-to-CAD, MIDAS Civil NX and Rhino interchange, and Ohio DOT standards and data. Results
carry the specification article they come from, so a calculation can be checked against the
code by hand.

**[Source](https://daneparks.com/Dane/civilpy) · [Docs](https://dane.daneparks.com/civilpy) · [PyPI](https://pypi.org/project/civilpy/) · [Changelog](CHANGELOG.md)**

---

## What's in the package

| Area | Modules | Highlights |
|------|---------|------------|
| Steel shapes and sections | `structural.steel`, `section_properties`, `builtup` | Every AISC shape and the historic (pre-1970) tables with Pint units; built-up and riveted members |
| AASHTO LRFD | `structural.aashto.lrfd` | Steel I-girders (Ch. 6, Appendices A6 / B6 / D6, 9th and 10th Editions by `design_year`), bolted field splices, composite sections, distribution factors, concrete and prestressed concrete, decks, columns, strut-and-tie, timber, railings, pins and eyebars, gusset plates, stability bracing |
| Load rating | `aashto.lrfd.lrfr`, `rating_ratios` | MBE 6A rating factors for inventory, operating, legal, permit and emergency vehicles; steel member rating flow |
| Analysis | `beam_bending`, `continuous_beam`, `influence_lines`, `frame_analysis`, `moment_distribution`, `truss` | Determinate and continuous beams, influence lines with HL-93 (incl. the dual-truck / dual-tandem negative-moment loading) and HS20-44, a 3-D frame / truss solver, Hardy Cross |
| Steel bridge evaluation and repair | `member_strengthening`, `aashto.irm`, `aashto.cif`, `aashto.fatigue_retrofit`, `heat_straightening`, `heat_curving` | Plates added to in-service members, internal redundancy, constraint-induced fracture, fatigue retrofits, heat straightening and heat curving |
| Bearings and substructure | `aashto.bearings`, `abutment`, `pier` | Elastomeric bearings (Method A), retaining walls and abutments, multi-column piers |
| Wood and concrete | `structural.wood`, `structural.concrete` | NDS sawn lumber and glulam with member checks; ACI 318-19 anchors |
| Model interchange | `midas`, `midas_models`, `staad`, `structural_model`, `rhino_*`, `ifc_emit` | MIDAS Civil NX API, STAAD.Pro decks to MIDAS, Rhino `.3dm` and IFC model emit |
| Water resources | `water_resources` | HDS-5 culverts, HEC-18 scour, open-channel and pipe flow, NOAA Atlas 14 / MRMS rainfall, USGS StreamStats, FEMA NFHL, NWS alerts |
| Geotechnical | `geotech` | Borings and SPT correlations, shallow and deep foundations, lateral earth pressure, p-y and t-z / q-z curves, DIGGS export |
| Transportation | `transportation` | Horizontal and vertical curves, composed alignments, LandXML, terrain |
| Scan-to-CAD | `scan` | LiDAR point clouds to decks, piers, spans and clearances |
| Ohio DOT | `state.ohio`, `state.ohio.DOT` | L&D Vol. 2 drainage (rainfall, inlets, storm sewers, ditches, culvert sizing), SNBI data validation, TIMS data, plan-set and ProjectWise tools |

---

## Installation

```bash
pip install civilpy
```

Python 3.10 or newer. Optional dependency groups for heavier tools:

| Extra | What it adds |
|-------|-------------|
| `civilpy[db]` | PostgreSQL / Oracle connectors, SSH tunnel |
| `civilpy[pdf]` | PDF extraction (PyMuPDF, Camelot, Tesseract OCR) |
| `civilpy[geo]` | Folium maps, GeoTIFF tools, pyproj |
| `civilpy[web]` | Selenium, Plotly |
| `civilpy[jupyter]` | Notebook utilities, ipywidgets |
| `civilpy[validation]` | Pydantic models for SNBI data validation |
| `civilpy[rhino]` | rhino3dm, for the `.3dm` model writers |
| `civilpy[ifc]` | IfcOpenShell, for IFC model emit |
| `civilpy[fem]` | Meshing and finite elements (pygmsh, scikit-fem) |
| `civilpy[lidar]` | LAS/LAZ reading (laspy) and Open3D reconstruction for `civilpy.scan` |
| `civilpy[mcp]` | The `civilpy-pw-mcp` ProjectWise MCP server |
| `civilpy[cande]` | CANDE soil-structure interaction for box culverts |
| `civilpy[gui]`, `civilpy[ai]`, `civilpy[llm]` | Desktop helpers, PyTorch plan-sheet models, Gemini extraction |
| `civilpy[full]` | db, pdf, geo, web, jupyter, validation, rhino, fem, ifc, gui, mcp |
| `civilpy[all]` | Everything, including the heavy wheels (torch, open3d) |

---

## AISC Steel Shapes

Every shape in the AISC Steel Construction Manual is available as a Python class. Properties
carry [Pint](https://pint.readthedocs.io/) units so dimensional arithmetic is automatic.

```python
from civilpy.structural.steel import W, HSS, C, L, Pipe, HP, WT, TwoL

# Wide-flange beam - all standard AISC section properties
beam = W("W36X150")
print(beam.depth)               # 35.9 inch
print(beam.flange_width)        # 12.0 inch
print(beam.I_x)                 # 9040.0 inch ** 4
print(beam.Z_x)                 # 581.0 inch ** 3  (plastic section modulus)
print(beam.S_x)                 # 504.0 inch ** 3  (elastic section modulus)
print(beam.r_x, beam.J, beam.Cw)
print(beam.slenderness_ratio_web)   # h/tw = 51.9

col = HSS("HSS12X8X.500")       # rectangular and round HSS
print(col.tdes)                 # design wall thickness

ch = C("C15X50")                # channels
ang = L("L4X4X1/2")             # angles
pile = HP("HP14X117")           # bearing piles
tee = WT("WT18X151")            # tees cut from W shapes
dang = TwoL("2L6X4X7/16SLBB")   # double angles

# Pipes use the EDI nomenclature (Pipe6SCH40 is the manual's Pipe6STD)
pipe = Pipe("Pipe6SCH40")
print(pipe.OD, pipe.ID)         # 6.625 inch 6.07 inch
```

### Units and dimensional math

```python
from civilpy.general import units
from civilpy.structural.steel import W

beam = W("W24X76")

# Bending stress from a moment in kip-ft
M = 400 * units("kip*ft")
fb = (M.to("kip*in") / beam.S_x).to("ksi")
print(f"Bending stress: {fb:.2f}")   # 27.27 kip_per_square_inch

# Simple-span deflection under 2 klf over 30 ft - the units resolve themselves
E = 29000 * units("ksi")
L = (30 * units("ft")).to("in")
w = (2 * units("kip/ft")).to("kip/in")
delta = (5 * w * L**4) / (384 * E * beam.I_x)
print(delta.to("in"))                # 0.599 inch
```

### Historic shapes

Shapes from before AISC standardization, for evaluating older bridges, come from the AISC
historic shapes tables. `HistoricSteelSection` is the base class; `WF` is the historic
wide-flange with its full dimensions. A size published in more than one edition needs the
`designation` column to pick one:

```python
from civilpy.structural.steel import WF, historic_steel_tables

# Which tables list a 36WF150?
print(historic_steel_tables.query("Name == '36WF150'")[["Name", "Designation"]])

section = WF("36WF150", designation="36WF_B36")
print(section.depth, section.flange_width, section.I_x)   # 35.84 inch, 11.972 inch, 9012.1 inch ** 4
```

### Bolt weights

```python
from civilpy.structural.steel import get_bolt_weights

# A325 bolt, 1.5 in. long, 3/4 in. diameter, 2 washers
weight = get_bolt_weights(length=1.5, diameter=0.75, no_of_washers=2)
print(weight)   # 0.618 pound
```

---

## Built-Up Section Properties

`CrossSection` assembles a built-up section by stacking rectangular plates from the bottom up.
Each call to the instance appends the next component. It also accepts rolled shapes.

```python
from civilpy.structural.section_properties import CrossSection
from civilpy.structural.steel import W

# Plate girder: bottom flange + web + top flange
section = CrossSection(label="bottom flange", dimensions=(16, 1.5))
section(label="web",        dimensions=(0.5625, 54))
section(label="top flange", dimensions=(16, 1.5))

print(f"Area:         {section.area:.2f} in²")      # 78.38
print(f"Neutral axis: {section.n:.2f} in from bottom")
print(f"I (strong):   {section.I_n:.2f} in⁴")

# Cover-plated rolled beam: start from a W shape, then add plates
comp = CrossSection(label="W33X201", shape=W("W33X201"))
comp(label="top cover plate", dimensions=(12, 0.75))
print(f"Composite I: {comp.I_n:.2f} in⁴")
```

---

## AASHTO LRFD, Influence Lines and Load Rating

The `structural.aashto.lrfd` checks return `CheckResult` objects that carry the article,
capacity, demand and the intermediate values. Edition changes are handled by `design_year`
(for example, the 10th Edition steel I-girder provisions apply from 2024 and the 9th Edition
forms before).

```python
from civilpy.structural.aashto.lrfd.distribution import moment_df_interior
from civilpy.structural.aashto.lrfd.lrfr import rating_factor
from civilpy.structural.continuous_beam import ContinuousBeam

# Live-load distribution, interior girder (Table 4.6.2.2.2b-1)
df = moment_df_interior(s_ft=9.0, l_ft=100.0, t_s=8.5, k_g=1.2e6)
print(f"DF {df.governing:.3f} lanes/girder, within the table's limits: {df.applicable}")

# Two 100-ft continuous spans: HL-93 at the pier, including the 3.6.1.3.1
# two-truck loading where the section is in the negative-moment region
beam = ContinuousBeam([0.0, 100.0, 200.0])
il = beam.continuous_moment_influence_line(100.0)
neg = il.hl93_effect(sign=-1, dual_truck="contraflexure")
print(f"HL-93 pier moment {neg['total']:.0f} kip-ft per lane, dual truck governs: {neg['dual_truck_governs']}")

# MBE 6A inventory rating of the pier section
rf = rating_factor(nominal_capacity=9000.0, dc=2400.0, dw=350.0,
                   ll_im=abs(neg["total"]) * df.governing, level="inventory")
print(f"RF {rf.capacity:.2f} ({rf.article})")   # RF 1.92 (6A.4.2.1)
```

Also in this area:

- **Steel I-girders** (`lrfd.steel`, `appendix_a6`, `appendix_b6`, `composite`): flexure,
  shear, constructability, web bend-buckling, fatigue, studs, stiffeners, moment
  redistribution.
- **Bolted field splices** (`lrfd.bolted_field_splice`, `lrfd.splices`): a splice designer
  checked against the NSBA Steel Bridge Design Handbook and the AISC-NSBA Standard Plans.
- **Concrete** (`lrfd.concrete`, `prestressed`, `deck`, `columns`, `stm`): flexure, shear,
  prestress losses, deck strip design, columns, strut-and-tie.
- **Steel evaluation and repair**: `lrfr.steel_member_rating`, `member_strengthening`
  (FHWA HIF-18-042), `aashto.irm`, `aashto.cif`, `aashto.fatigue_retrofit`,
  `heat_straightening`, `heat_curving`, `lrfd.pins`, `lrfd.gusset`, `lrfd.stability_bracing`.
- **Analysis**: `frame_analysis` (3-D frame / truss, direct stiffness),
  `InfluenceLine.hs20_44_effect` for Standard Specifications ratings, `moment_distribution`,
  `truss` (method of joints).

---

## Beam Analysis

Shear, moment and deflection diagrams for statically determinate beams, following AISC
Table 3-23 sign conventions. Supports may be placed anywhere in the span (overhangs).

```python
from civilpy.structural.beam_bending import Beam, PointLoadV, DistributedLoadV

# 30 ft simple span: 15 kip point load at 10 ft + 2 klf uniform
beam = Beam(span=30)
beam.pinned_support = 0
beam.rolling_support = 30
beam.add_loads([
    PointLoadV(15, 10),            # 15 kips down at x = 10 ft
    DistributedLoadV(2, (0, 30)),  # 2 kips/ft over the full span
])

axial, R1, R2 = beam.get_reaction_forces()
print(R1, R2)                      # 40.0, 35.0 kips

beam.plot_all()                    # beam diagram + V + M (+ deflection) figure
```

`CantileverBeam`, `ProppedCantileverBeam` and `FixedFixedBeam` cover the other support
conditions; continuous beams are in `civilpy.structural.continuous_beam`.

---

## Wood Design (NDS)

Sawn lumber and glulam sections with NDS reference design values, adjustment factors, and
ASD/LRFD member checks:

```python
from civilpy.structural.wood import LumberSection, GlulamSection, WoodMemberCheck
from civilpy.general import units

beam = LumberSection("6x12", "Douglas Fir-Larch", "No. 1")
print(beam.b, beam.d)        # 5.5 inch, 11.25 inch (dressed)
print(beam.Fb, beam.E)       # 1350 psi, 1.6e6 psi

gl = GlulamSection("6.75x30", "24F-V4", "Douglas Fir")
print(gl.Fb_pos, gl.Fb_neg)  # 2400 psi positive face, 1850 psi negative

# Full NDS adjustment-factor chain, demand/capacity per check
check = WoodMemberCheck(beam, method="ASD", wet_service=False, load_duration="normal")
bend = check.check_bending(9600 * units("lbf*ft"))
print(bend["ratio"], bend["status"])      # 0.736 OK
check.check_shear(2400 * units("lbf"))
check.check_deflection(200 * units("lbf/ft"), 16 * units("ft"), limit="L/360")
check.summary()                            # DataFrame of all checks run

col = LumberSection("6x6", "Douglas Fir-Larch", "No. 1")
comp = WoodMemberCheck(col).check_compression(15000 * units("lbf"), le_strong=10 * units("ft"))
print(round(comp["Cp"], 3), comp["ratio"])  # 0.692 0.717
```

Also included: `TimberBridgeDeck` and `TimberStringer` for AASHTO LRFD timber bridges and
MBE rating, and `BoltConnection` for NDS Chapter 12 bolted connections (European Yield Model).

---

## Concrete Anchor Design (ACI 318-19)

Chapter 17 anchor checks for cast-in anchors: steel strength, concrete breakout, pullout,
side-face blowout, shear, and interaction, with a calc-sheet style summary.

```python
from civilpy.structural.concrete import AnchorBolts

# 2x2 group of 3/4" F1554 Gr 36 headed anchors, 12" embedment,
# 4000 psi concrete, 6" edge distances
group = AnchorBolts(
    f_c=4000, h_a=24,
    d_a=0.75, h_ef=12,
    f_ya=36000, f_uta=58000,   # ASTM F1554 Gr 36
    n_x=2, n_y=2, s_x=6, s_y=6,
    c_a1=6, c_a2=6,
    A_brg=0.654,               # heavy hex head bearing area
    N_ua=5000, V_ua=3000,      # factored demands (lbs)
)

results = group.check_all()    # dict of every limit state
print(group.summary())         # formatted table: phi Sn, demand, DCR, OK/NG
```

`ShearLugCheck` covers shear lugs per ACI 318-19 17.11.

---

## Water Resources and Drainage

```python
from civilpy.water_resources.culvert import Culvert, BarrelShape
from civilpy.water_resources.scour import pier_scour_csu
from civilpy.state.ohio.DOT import idf

# FHWA HDS-5 culvert: 6 ft concrete pipe, square-edge headwall, 150 cfs
pipe = Culvert(BarrelShape.circular(6.0), length_ft=80, inlet_invert=101.0,
               outlet_invert=100.2, n=0.013, inlet="concrete_pipe_square_headwall")
r = pipe.headwater(150.0, tailwater_elev=102.0)
print(f"HW {r.headwater_elev:.2f} ft, {r.control} control")    # HW 105.92 ft, inlet control

# FHWA HEC-18 (CSU equation) local pier scour
print(f"{pier_scour_csu(approach_velocity_fps=6.0, approach_depth_ft=8.0, pier_width_ft=3.0):.1f} ft")

# ODOT L&D Vol. 2: Figure 1101-1 overland flow time, then the Figure 1101-2 rainfall
tc = idf.overland_flow_chart_minutes(0.50, 200, 0.2)   # C, length (ft), slope (%)
i = idf.intensity(tc, 10, "B")                         # duration (min), AEP (%), zone
print(f"tc {tc:.1f} min, i {i:.2f} in/hr")             # tc 20.0 min, i 3.68 in/hr
```

Also in `water_resources`: open-channel flow in surveyed or LiDAR cross sections, pipe
energy and hydraulic grade lines, contraction and abutment scour, NOAA Atlas 14 and MRMS
rainfall, USGS StreamStats, NHDPlus, FEMA NFHL flood zones, NWS alerts and post-storm scour
screening. `state.ohio.DOT.roadway_drainage` and `culvert_design` carry the L&D Vol. 2
ditch, inlet spacing, storm sewer and culvert sizing rules.

---

## Geotechnical and Roadway Geometry

```python
from civilpy.geotech.shallow_foundation import ultimate_bearing_capacity
from civilpy.transportation.curves import HorizontalCurve, VerticalCurve

# 8 x 12 ft spread footing, 4 ft deep, on sand (AASHTO LRFD 10.6.3.1.2, Vesic factors)
q = ultimate_bearing_capacity(b=8, l=12, d=4, gamma=120, phi_deg=32)
print(f"q_ult {q.q_ult:,.0f} psf")

hc = HorizontalCurve(radius_ft=1200, delta_deg=32, pi_station_ft=12_500)
print(f"PC {hc.pc_station:.2f}, PT {hc.pt_station:.2f}, L {hc.length_ft:.2f} ft")

vc = VerticalCurve(g1_pct=3.0, g2_pct=-2.0, length_ft=600, pvi_station_ft=15_000, pvi_elevation_ft=820.0)
print(f"K {vc.k_value:.0f}, high point {vc.high_low_point()}")   # K 120, (15060.0, 816.4)
```

`geotech` also reads boring logs (including DIGGS and ODOT gINT PDFs) into one boring model,
derives soil parameters from SPT counts, and covers deep foundations, lateral earth pressure,
p-y, t-z and q-z curves and LPILE files. `transportation` adds composed alignments, LandXML
and terrain surfaces.

---

## MIDAS Civil NX, STAAD and Rhino

Connect to a running MIDAS Civil NX through its API (REST API enabled). Store your key in
`~/secrets.json` as `{"MIDAS_API_KEY": "your-key-here"}`.

```python
from civilpy.structural.midas import midas_api, get_api_key, get_elements, get_nodes

get_api_key()                      # loads the key from ~/secrets.json
elements = get_elements()
nodes = get_nodes()

# Direct calls for anything the helpers do not cover
response = midas_api("GET", "db/elem")
midas_api("PUT", "db/stld", body={"Assign": {"1": {"NAME": "Dead Load (DC)"}}})
```

`midas_models` builds model payloads for girder, truss and composite bridges; `staad` reads a
STAAD.Pro `.std` deck and translates it to MIDAS tables. The `rhino_*` modules write Rhino
`.3dm` models on one shared layer taxonomy (install `civilpy[rhino]`), and `ifc_emit` writes
IFC. Box-beam coordination examples are available through
`civilpy-box-bridges --output ./bridge_examples`; see the
[generation and Rhino workflow](docs/Box_Bridge_Details.md).

---

## AASHTO and AREMA References

```python
from civilpy.structural.aashto.bearings import BearingSuitability
from civilpy.structural.aashto.load_definitions import load_combinations
from civilpy.structural.aashto.vehicles import HL93Load

# Bearing suitability, LRFD Table 14.6.2-1 (S suitable, U unsuitable, R special consideration)
print(BearingSuitability().table)

# Limit-state load factors
gamma_ll = load_combinations["Strength I"]["LL"]["gamma"]   # 1.75

truck = HL93Load()
print(truck.axels)   # 8 k front, 32 k drive, 32 k rear at 14-30 ft
```

`MethodABearing` runs the LRFD 14.7.6 elastomeric bearing checks. In
`structural.arema.rail_tpg_design`, `GlobalDefinitions` and `LoadDefinitions` hold the AREMA
Chapter 15 material constants and Cooper E80 loading for through plate girder floor systems.

---

## SNBI Bridge Inspection Data

Pydantic models for the FHWA Specification for the National Bridge Inventory (SNBI), for
validating records before submission or building tools that read and write them. Codes are
checked against the SNBI code tables (install `civilpy[validation]`).

```python
from pydantic import ValidationError
from civilpy.state.ohio.snbi import Element, SpanSet, Inspection

# Element quantities must reconcile: BE03 = BCS01 + BCS02 + BCS03 + BCS04
element = Element(BE01="12", BE02="0", BE03=100, BCS01=70, BCS02=20, BCS03=10, BCS04=0)

span = SpanSet(BSP01="M01", BSP02=2, BSP04="S01", BSP05="1", BSP06="G01", BSP09="C01", BSP12="R01")
inspection = Inspection(BIE01="1", BIE02="20240801", BIE03="20240801", BIE05=24)

try:
    Element(BE01="12", BE02="0", BE03=100, BCS01=70, BCS02=20, BCS03=5, BCS04=0)
except ValidationError as e:
    print(e.errors()[0]["msg"])   # Value error, BE03 Element Total Quantity must equal the sum of BCS01-BCS04
```

`civilpy snbi validate records.json` runs the same checks over a JSON file and exits nonzero on any violation, so a submission can be gated in CI.

---

## ODOT TIMS Bridge Data

Live bridge records from the ODOT TIMS ArcGIS REST service. No credentials required.

```python
from civilpy.state.ohio.DOT.TIMS import TIMSBridge, get_tims_data

bridge = TIMSBridge("2102374")
print(bridge)                       # route, location, year built, type, condition summary
print(bridge.deck_area, bridge.suff_rating, bridge.lanes_on)

# Bulk download of the bridge layer as a DataFrame (TIMS column names)
df = get_tims_data("Bridge")
district_5 = df[df["DISTRICT"].astype(int) == 5]
```

---

## Scan-to-CAD (LiDAR point clouds)

`civilpy.scan` turns a terrestrial or mobile LiDAR scan of a bridge site into engineering
features: ground, deck and wall planes, columns, substructure units with span lengths,
per-span under-clearance, crease edges, and a Rhino `.3dm` / DXF on civilpy's layer
taxonomy. The core is `numpy` / `scipy`; `laspy` streams multi-gigabyte `.las` files through
a voxel grid so they never have to fit in memory (install `civilpy[lidar]`).

```python
from civilpy.scan import read_las, extract_features

cloud = read_las("bridge.las", voxel=0.25)          # 330M points -> ~2M voxels
res = extract_features(cloud, voxel=0.25)
print(res.summary()["span_lengths"], res.deck.extent_v)
res.export_3dm("bridge_as_scanned.3dm")             # deck, piers, edges on Deck::/Substructure:: layers
```

---

## Command Line

`civilpy` with no arguments opens an interactive shell (Tab completion, `/help`). Command
groups:

| Group | Commands |
|-------|----------|
| `boring` | `pdf2diggs`, `parse`, `batch` |
| `hydro` | `channel`, `scour-pier` |
| `road` | `vcurve`, `hcurve` |
| `snbi` | `validate` |
| `odot` | `photos`, `slab`, `bridge`, `tiff-join`, `tiff-split` |
| `photos` | `exif`, `rename`, `resize`, `stamp` |
| `pdf` | `tag` |
| `report` | `notebook` |
| `spanwire` | `catalog`, `simple`, `wye`, `system` |
| `scan` | `info`, `extract` |

For example, `civilpy road vcurve --help` or `civilpy scan extract site.las --voxel 0.25 --dxf features.dxf`.

---

## Package Structure

```mermaid
graph TD
    A[Does the function relate to a specific state<br>requirement/system, or a branch of civil engineering?]
    A --> |State| B("Does it apply statewide<br>or to a specific department?")
    A --> |Branch| C("Which engineering branch?")
    C --> |structural| E(civilpy.structural)
    C --> |geotechnical| F(civilpy.geotech)
    C --> |transportation| H(civilpy.transportation)
    C --> |water_resources| I(civilpy.water_resources)
    A --> |Neither| P(civilpy.general)
    E --> K("Standard-specific?")
    K --> |AASHTO| N(civilpy.structural.aashto)
    K --> |AREMA| NA(civilpy.structural.arema)
    K --> |No| O(civilpy.structural)
    B --> |Statewide| L(civilpy.[state])
    B --> |Department| M(civilpy.[state].DOT)
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — includes setup instructions, the four-role QA/QC
review process, and the AI use policy.

Security issues: [SECURITY.md](SECURITY.md)

Bugs and feature requests: [issue tracker](https://daneparks.com/Dane/civilpy/issues)
