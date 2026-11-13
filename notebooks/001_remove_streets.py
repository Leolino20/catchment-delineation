"""
Remove a street from a DEM (mask + interpolate), condition the DEM, run D8.

Requires: rasterio, geopandas, numpy, shapely, whitebox
    pip install rasterio geopandas numpy shapely whitebox
"""
import os
import numpy as np
from pathlib import Path
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.fill import fillnodata
from shapely.geometry import box
from whitebox import WhiteboxTools
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

def remove_streets():

    parent_dir = Path.cwd().parent
    print(parent_dir)
    # ---------------------------------------------------------------- CONFIG
    DEM_PATH      = parent_dir/"data/dem_swissalti3d_merged_burti.tif"
    TLM_PATH      = "/home/tleona/Documents/burtigniere/gis/catchment_analysis/streets/SWISSTLM3D_2026_LV95_LN02.gpkg"
    TLM_LAYER     = "tlm_strassen_strasse"
    OUT_DIR       = parent_dir/"data/"

    HALF_WIDTH_M  = 12.0    # half of the street width (curb to curb), measure in your DEM
    MARGIN_M      = 2.0    # extra buffer to also cover curbs / embankments
    SMOOTH_ITERS  = 2      # smoothing iterations applied to the interpolated cells
    BREACH_DIST   = 20     # max breach search distance in cells (WhiteboxTools)
    # ----------------------------------------------------------------------

    os.makedirs(OUT_DIR, exist_ok=True)
    nostreet_path = os.path.join(OUT_DIR, "dem_nostreet.tif")
    breached_path = os.path.join(OUT_DIR, "dem_breached.tif")
    d8_path       = os.path.join(OUT_DIR, "d8_pointer.tif")
    diff_path     = os.path.join(OUT_DIR, "diff_filled_minus_dem.tif")

    # 1. Read DEM -------------------------------------------------------------
    with rasterio.open(DEM_PATH) as src:
        dem = src.read(1, masked=True).astype("float32")
        profile = src.profile.copy()
        transform, crs, bounds = src.transform, src.crs, src.bounds

    nodata = profile.get("nodata")
    if nodata is None:
        nodata = -9999.0
    cell = abs(transform.a)

    # 2. Load street geometry from swissTLM3D ---------------------------------
    print(gpd.list_layers(TLM_PATH))
    roads = gpd.read_file(TLM_PATH, layer=TLM_LAYER, bbox=tuple(bounds)).to_crs(crs)
    roads = roads[roads.intersects(box(*bounds))]

    # Inspect: make sure only your street is in here. Drop other rows or
    # bridge/tunnel segments (KUNSTBAUTE) here if needed, e.g.:
    # roads = roads.drop(index=[...])
    cols = [c for c in ("OBJEKTART", "BREITENKLASSE", "KUNSTBAUTE") if c in roads.columns]
    print(f"{len(roads)} road segment(s) in DEM extent")
    print(roads[cols])

    if roads.empty:
        raise SystemExit("No road geometry found in the DEM extent.")

    # 3. Buffer and rasterize into a street mask ------------------------------
    buffer_m = HALF_WIDTH_M + MARGIN_M
    geoms = roads.buffer(buffer_m)

    street = features.rasterize(
        ((g, 1) for g in geoms),
        out_shape=dem.shape,
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)

    # 4. Remove street cells and interpolate over them -------------------------
    orig_nodata = np.ma.getmaskarray(dem)
    valid = (~street) & (~orig_nodata)        # 1 = keep, 0 = interpolate
    work = dem.filled(nodata).astype("float32")

    search_px = int(np.ceil(buffer_m / cell)) + 2   # must cover half the mask width

    filled = fillnodata(
        work,
        mask=valid.astype("uint8"),
        max_search_distance=search_px,
        smoothing_iterations=SMOOTH_ITERS,
    )

    # Keep the original NoData as NoData (only the street gets interpolated)
    filled[orig_nodata] = nodata

    profile.update(dtype="float32", nodata=nodata)
    with rasterio.open(nostreet_path, "w", **profile) as dst:
        dst.write(filled.astype("float32"), 1)


    # 5. Difference raster to check the result --------------------------------
    diff = np.where(orig_nodata, nodata, filled - dem.filled(nodata)).astype("float32")
    with rasterio.open(diff_path, "w", **profile) as dst:
        dst.write(diff, 1)

    # 6. Condition DEM and run D8 ----------------------------------------------
    wbt = WhiteboxTools()
    wbt.set_working_dir(os.path.abspath(OUT_DIR))
    wbt.verbose = False

    wbt.breach_depressions_least_cost(
        os.path.abspath(nostreet_path),
        os.path.abspath(breached_path),
        dist=BREACH_DIST,
        fill=True,
    )
    wbt.d8_pointer(
        os.path.abspath(breached_path),
        os.path.abspath(d8_path),
    )

    print("Done. Outputs in:", os.path.abspath(OUT_DIR))
    print("Check:", diff_path, "should show a clear band along the street,")
    print("       and the street should no longer appear in", d8_path)


if __name__ == "__main__":
    remove_streets()
