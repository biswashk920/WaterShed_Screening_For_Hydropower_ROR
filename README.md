# Watershed Hydropower Screening (Run-of-River)

A reproducible, three-notebook GIS and hydrology workflow for screening potential run-of-river hydropower reaches in a user-selected watershed. The workflow obtains a 30 m digital elevation model (DEM), projects and delineates the basin, and searches its river network for winding reaches with useful elevation drop and gradient.

This is a **screening tool, not a feasibility or engineering study**. Results are locations for further investigation, not confirmed viable hydropower sites.

## Workflow

Run the notebooks in order:

1. **`notebook/01_GEE_Data_Acquisation.ipynb` — acquire inputs.** Authenticate to Google Earth Engine, draw one rectangular area of interest that contains the full basin and one outlet point inside it, then download the Copernicus GLO-30 DEM at 30 m. Large downloads are recursively divided into temporary tiles, mosaicked into one DEM, and the temporary tiles are removed. The raw DEM, outlet shapefile, and AOI are saved in `data/`.
2. **`notebook/02_watershedDelineation.ipynb` — prepare and delineate.** Project the DEM to the UTM zone covering the largest share of the AOI, resample to 30 m, remove edge NoData, condition the DEM, calculate flow routing, snap the outlet, and delineate the watershed. The projected DEM, NoData-free rectangular DEM, watershed-clipped DEM, boundary, outlet, routing rasters, and preview maps are written to `results/preprocessing/`. Preview maps retain the projected aspect ratio, crop blank NoData margins, and show UTM axis ticks in thousands of metres. Reusable map drawing code is in `notebook/helper.py`.
3. **`notebook/03_Hydropower_Screening.ipynb` — screen reaches.** Reuse the delineated watershed products rather than repeating projection, conditioning, flow routing, outlet snapping, or watershed delineation. Build the stream network, sample river reaches, screen and deduplicate candidates, and export the results. Its five final figures use bounded raster previews and the Pillow renderer in `notebook/helper.py`, avoiding full-raster plotting allocations.

The acquisition and delineation notebooks currently use UTM, which is defined between 80°S and 84°N. The delineation notebook reports an error for AOIs outside that range or those too broad for a suitable UTM zone.

## Project layout

```text
notebook/
  01_GEE_Data_Acquisation.ipynb
  02_watershedDelineation.ipynb
  helper.py                     # reusable DEM preview-map rendering
  03_Hydropower_Screening.ipynb
data/
  sourceDEM.tif                 # raw, unprojected 30 m DEM
  outlet.*                      # outlet point shapefile and sidecars
  watershedAOI.geojson          # drawn rectangular extent
results/
  preprocessing/
    projectedDEM.tif
    rectangularDEM.tif           # NoData-free projected rectangular DEM
    watershedDEM.tif              # projected, watershed-clipped analysis DEM
    watershedBoundary.shp
    filledDEM.tif
    flowPointer.tif
    flowAccumulation.tif
    watershed.tif
    outlet_snapped.*
  candidate_reaches.csv
  candidate_reaches.gpkg        # directed lines, ordered upstream to downstream
  candidate_sites.gpkg          # point at each reach's upstream end
  river_network.gpkg
  river_points.gpkg
  candidate_sites.html
  figures/
```

Input DEMs, shapefiles, preprocessing rasters, and other generated results are local products and are not committed to the repository. The interactive `results/candidate_sites.html` map is included so it can be published with the project. It loads Leaflet and OpenStreetMap tiles from external services, so an internet connection is required to display the map. The acquisition notebook creates and cleans its temporary tile directory under `data/`.

## Environment

Use a Python 3.11 environment. Install the geospatial stack with Conda, then install the remaining Python packages:

```bash
conda create -n watershed-screening python=3.11 -y
conda activate watershed-screening
conda install -c conda-forge rasterio geopandas fiona shapely pyproj gdal numpy pandas matplotlib networkx scipy ipykernel -y
pip install -r requirements.txt
python -m ipykernel install --user --name watershed-screening --display-name "Python (watershed-screening)"
```

The first notebook requires a Google Earth Engine account with access to the Copernicus GLO-30 dataset. After drawing the AOI and outlet, run each notebook from top to bottom. The notebook code handles project-root detection when the working directory is either the repository root or the `notebook/` folder.

## Screening method and interpretation

The stream-initiation threshold (1 km² contributing area), major-reach cutoff (100 km²), search cap (10 km), route-length ratio (2.0), elevation-drop floor (30 m), Euclidean-gradient floor (3%), and deduplication radius (1,500 m) are explicit screening choices. They were selected for the original example basin and are **not universal hydropower design criteria**; review them for each new watershed.

Candidate reach lines are ordered from the upstream site point to the downstream point. The final candidate map draws an upstream dot and a thin arrowed line toward downstream. The CSV retains both endpoint coordinates and the screening measurements.

## Limitations

- No discharge modelling, geotechnical assessment, land-use constraints, environmental-flow analysis, or engineering feasibility study is performed.
- Results depend on the DEM source and quality. Global elevation products can contain voids, artifacts, and vertical error, especially in steep terrain.
- A candidate indicates a reach worth further study; it does not establish that a hydropower project is viable.
