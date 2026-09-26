# Kali Gandaki Hydropower Screening (Run-of-River)

A reproducible GIS/hydrology pipeline for screening candidate run-of-river (RoR) hydropower sites along the Kali Gandaki river, Nepal, using a DEM-derived drainage network and a **route-length-ratio** approach: identifying reaches where the river channel winds substantially more than the straight-line distance between two points, combined with a meaningful elevation drop and slope — flagging locations where a straight headrace/penstock could plausibly "shortcut" a winding, steep stretch of river.

**This is a screening tool, not a feasibility study.** Results indicate reaches worth further investigation (site visits, discharge gauging, geotechnical assessment) — they are not confirmed viable hydropower sites.

---

## Methodology

### 1. Input validation
DEM and pour-point shapefile are checked for matching CRS (`EPSG:32644`, UTM Zone 44N), valid extent, NoData handling, and that the pour point falls inside the DEM.

### 2–3. DEM preprocessing and depression filling
The DEM is hydrologically conditioned using WhiteboxTools' `FillDepressions`, removing artificial sinks that would otherwise interrupt flow routing.

### 4–5. Flow direction and accumulation
D8 flow direction and flow accumulation are computed from the filled DEM.

### 6. Stream initiation threshold
A contributing-area threshold of **1 km²** was chosen to define the channel network. This value is a **literature-informed choice** (typical for steep, ~30 m-resolution mountainous terrain), not a purely automated derivation — an automated slope-break analysis on the accumulation distribution was inconclusive (noise-affected, bimodal), so the threshold is stated explicitly here rather than presented as objectively derived.

### 7–8. Pour point snapping and watershed delineation
The pour point is snapped onto the thresholded stream network (not raw flow accumulation, which snaps to the *nearest* cell regardless of magnitude and can land on tiny headwater cells — an early version of this pipeline hit exactly that bug). Watershed delineation from the corrected snap point gives a basin area of **~11,870 km²**, consistent with published estimates for the Kali Gandaki basin.

### 9. Stream network vectorization
The thresholded stream raster is converted to vector lines (6,296 segments). **Note:** WhiteboxTools' raster-to-vector conversion drops CRS information — this is corrected by re-assigning `EPSG:32644` after conversion.

### 10. Network graph construction
The vector segments are assembled into a `networkx` graph (nodes = segment endpoints, edges = segments). The result is a connected, cycle-free tree (6,297 nodes, 6,296 edges) — the correct topological structure for a real drainage network.

### 11. River point sampling
Points are sampled every 500 m along the network, using **cumulative graph distance from the outlet** (not per-segment distance) so spacing stays continuous across confluences rather than resetting at every junction.

### 12–13. Elevation and contributing-area extraction
Elevation (from the filled DEM) and contributing area (a discharge proxy, from flow accumulation) are extracted at every sampled point.

### 14. Multi-scale candidate search
For every "major" reach point (contributing area ≥ **100 km²** — chosen to exclude small headwater dendrites with negligible discharge), the pipeline searches **downstream at every 500 m increment, up to a 10 km cap**, and keeps whichever span gives the best route-length ratio for that point. This multi-scale search — rather than only comparing fixed 500 m reaches — is essential: a real loop or meander (e.g., river distance 5 km, straight-line distance 1 km) would be invisible to a fixed-500 m-reach comparison, since the loop only becomes apparent at the larger scale.

The 10 km cap follows practical waterway-length norms cited in the hydropower-siting literature (typical maximum headrace/penstock lengths of 3,000–10,000 m).

### 15. Candidate screening (three criteria)
A reach is flagged as a candidate only if **all three** hold:
- **Route-length ratio ≥ 2.0** (channel at least twice as long as the straight-line alternative)
- **ΔZ ≥ 30 m** (meaningful elevation drop — chosen to stay turbine-agnostic; a higher floor like 50 m would bias toward high-head Pelton-only schemes and exclude viable Francis/Kaplan-range sites)
- **Euclidean gradient ≥ 3%** (ΔZ ÷ straight-line distance — ensures the shortcut itself is meaningfully steep, not just long and winding at a gentle overall slope)

These thresholds are **stated, dataset-calibrated choices**, not universal constants — they were selected by examining the actual distribution of candidates across a range of threshold combinations for this basin, and should be re-examined if applied elsewhere.

### 16. Spatial deduplication
Because the multi-scale search runs independently from every major-reach point, the same physical bend is often re-detected multiple times at different span lengths from nearby starting points. A greedy spatial deduplication step (1,500 m radius, keeping the highest-ratio candidate per cluster) collapses these into distinct physical sites.

### 17. Export
Final candidate sites are exported as `candidate_reaches.csv` and `candidate_reaches.gpkg`.

### 18. Visualization
Five maps, all clipped to the watershed boundary (not the full rectangular DEM extent):
1. DEM + watershed boundary
2. Flow accumulation (log scale)
3. River network, line width scaled by discharge (flow accumulation)
4. Longitudinal elevation profile of the main channel
5. Final candidate sites, labeled, colored by Euclidean gradient, sized by ΔZ

---

## Repository structure

```
Kali-Gandaki-Hydropower-Screening/
│
├── README.md
├── requirements.txt
│
├── notebook/
│   └── KaliGandaki_Hydropower_Screening_v2.ipynb   # consolidated, final pipeline (18 cells)
│
├── data/
│   ├── kali_pourpoint.*        # pour-point shapefile (included)
│   └── kali44N.tif             # input DEM — EXCLUDED, see "Missing data" below
│
└── results/
    ├── candidate_reaches.csv       # final candidate sites (included)
    ├── candidate_reaches.gpkg      # same, as spatial data (included)
    ├── river_network.gpkg          # vectorized stream network (included)
    ├── river_points.gpkg           # sampled river points with attributes (included)
    ├── all_reaches.csv             # full 500m-reach table, exploratory/superseded (included)
    └── figures/                    # all 5 final maps + methodology diagnostic plots (included)
```

## Missing data (excluded from this repository)

The following files are **not included** in this repository, either because they exceed GitHub's file size limits or because they're large, easily-regenerated intermediate products:

| File | Size | Why excluded |
|---|---|---|
| `data/kali44N.tif` | ~127 MB | Exceeds GitHub's 100 MB per-file limit |
| `data/kali44N.tif.ovr` | ~40 MB | Display-only pyramid file, not needed for processing |
| `results/dem_filled.tif` | ~742 MB | Regenerable (Cell 3) |
| `results/flow_direction.tif` | ~186 MB | Regenerable (Cell 4) |
| `results/flow_accumulation.tif` | ~371 MB | Regenerable (Cell 5) |
| `results/watershed.tif`, `kali_gandaki_watershed_v2.tif` | ~371 MB each | Regenerable (Cell 8) |
| `results/stream_network.tif`, `streams_binary.tif` | ~371 MB each | Regenerable (Cell 7, 9) |

**DEM source:** NASA SRTM (Shuttle Radar Topography Mission), original resolution 30 m (1 arc-second), resampled/reprojected to ~29.51 m in EPSG:32644 (UTM Zone 44N) for this analysis. Publicly available via the [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or [NASA Earthdata](https://search.earthdata.nasa.gov/) (SRTMGL1 v3, 1 Arc-Second Global).

**Original DEM extent** (EPSG:32644 / UTM Zone 44N):
`left=596436.62, bottom=3042192.44, right=895312.10, top=3325544.23`
Resolution: ~29.51 m

Anyone wishing to fully reproduce this analysis should obtain a DEM covering this extent (or their own basin of interest) and run the notebook from Cell 1.

## How to run

```bash
conda create -n kaligandaki python=3.11 -y
conda activate kaligandaki
conda install -c conda-forge rasterio geopandas fiona shapely pyproj gdal numpy pandas matplotlib networkx scipy ipykernel -y
pip install whitebox
python -m ipykernel install --user --name kaligandaki --display-name "Python (kaligandaki)"
```

Place your DEM and pour-point shapefile in `data/`, open `notebook/KaliGandaki_Hydropower_Screening_v2.ipynb`, select the `kaligandaki` kernel, and run all cells in order. Outputs are written to `results/`.

## Key limitations (stated explicitly)

- This is a **screening indicator**, not a feasibility or engineering study. No discharge/hydrological modeling, geotechnical assessment, land-use, or environmental-flow constraints are considered.
- Thresholds (stream initiation area, "major reach" cutoff, route-length ratio, ΔZ floor, Euclidean gradient floor, deduplication radius) are **stated choices calibrated to this basin**, not universal values.
- The multi-scale search is capped at 10 km; a small number of candidates were still improving at that cap, meaning some real opportunities beyond 10 km may exist but go undetected.
- 6 of 6,296 stream edges did not resolve an ancestor chain during graph traversal (a minor, unexplained edge case affecting <0.1% of the network) — flagged for transparency, not expected to materially affect results.
- The DEM is derived from SRTM radar interferometry, which has known limitations in steep, high-relief terrain (e.g., radar shadow/layover in narrow gorges, void areas in extreme relief, and vertical accuracy typically cited around ±16 m absolute). These artifacts can affect depression-filling behavior and elevation-drop (ΔZ) calculations at specific reaches, particularly in very steep Himalayan terrain — a known and accepted trade-off of using freely available global DEM data rather than higher-resolution airborne/lidar data.