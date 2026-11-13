from pathlib import Path
import importlib.util
import subprocess
import sys
import shutil
import geopandas as gpd
try:
    from IPython.display import display
except ImportError:
    display = print
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap, LightSource, LogNorm
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point
import whitebox
from matplotlib.colors import LightSource
from scipy.ndimage import binary_dilation
from rasterio.features import geometry_mask
from rasterio.transform import xy



def do_catchment_analysis():

    ### Part 1 -------------------------------------------------------------------------------------------------------

    PROJECT_ROOT = Path.cwd().parent.resolve()
    REQUIREMENTS = PROJECT_ROOT / 'requirements.txt'

    try:
        from IPython import get_ipython
        ipython = get_ipython()
    except ImportError:
        ipython = None

    if ipython is not None:
        # %pip installs into the Python environment used by the active Jupyter kernel.
        ipython.run_line_magic('pip', f'install -r \"{REQUIREMENTS}\"')
    else:
        required_modules = ['whitebox', 'geopandas', 'matplotlib', 'numpy', 'pandas', 'pyproj', 'rasterio', 'shapely']
        missing_modules = [name for name in required_modules if importlib.util.find_spec(name) is None]
        if missing_modules:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS)])

    print('Project root:', PROJECT_ROOT)

    ### Part 2 -------------------------------------------------------------------------------------------------------

    DEM_PATH = (PROJECT_ROOT / 'data' / 'dem_nostreet.tif').resolve()
    POLYGON_PATH = (PROJECT_ROOT / 'data' / 'Inventar_Burti_outerpolygon.shp').resolve()
    OUTPUT_DIR = (PROJECT_ROOT / 'outputs').resolve()

    RESET_OUTPUTS = True
    if RESET_OUTPUTS and OUTPUT_DIR.exists():
        if OUTPUT_DIR.parent != PROJECT_ROOT:
            raise RuntimeError('Refusing to reset an output directory outside the repository.')
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    FILLED_DEM = OUTPUT_DIR / '01_dem_filled.tif'
    D8_POINTER = OUTPUT_DIR / '02_d8_pointer.tif'
    FLOW_ACCUM = OUTPUT_DIR / '03_flow_accumulation_cells.tif'
    STREAMS = OUTPUT_DIR / '04_streams.tif'
    WATERSHED_GPKG = OUTPUT_DIR / 'watershed.gpkg'
    CATCH_PIXEL_TIF = OUTPUT_DIR / '06_catchment_area_per_pixel_km2.tif'
    POLY_PTS_TIF = OUTPUT_DIR / '07_polygon_pourpoints.tif'
    POLY_WS_TIF  = OUTPUT_DIR / '08_polygon_catchment.tif'
    POLY_WS_SHP  = OUTPUT_DIR / '08_polygon_catchment.shp'

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    print(wbt.version().splitlines()[0])
    print('Input DEM:', DEM_PATH)
    print('Output directory:', OUTPUT_DIR)


    ### Part 3 -------------------------------------------------------------------------------------------------------

    # read_raster function based on rasterio.open
    def read_raster(path: Path):
        with rasterio.open(path) as src:
            data = src.read(1, masked=True)
            extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
            profile = src.profile.copy() # metadata of the raster (needed to do identical rasters) (driver, dtype,nodata,widht,height,count,crs,transform)
            bounds = src.bounds
        return data, extent, profile, bounds

    # read the dem in DEM_PATH
    dem, dem_extent, dem_profile, dem_bounds = read_raster(DEM_PATH)
    cell_width = abs(dem_profile['transform'].a) # pixel width (change in x per column)
    cell_height = abs(dem_profile['transform'].e) # pixel height (change in y per row)
    cell_area_m2 = cell_width * cell_height

    # dem extent needed for plotting later
    left, right, bottom, top = dem_extent

    # dem crs needed for later
    dem_crs = dem_profile["crs"]

    # show the metadata of the dem raster
    metadata = pd.Series({
        'CRS': str(dem_profile['crs']),
        'rows': dem_profile['height'],
        'columns': dem_profile['width'],
        'cell width (m)': cell_width,
        'cell height (m)': cell_height,
        'minimum elevation (m)': float(dem.min()),
        'maximum elevation (m)': float(dem.max()),
    })
    display(metadata.to_frame('value'))

    # plot the dem 
    # fig, ax = plt.subplots(figsize=(10, 7))
    # image = ax.imshow(dem, extent=dem_extent, origin='upper', cmap='terrain')
    # outlets_dem_crs.plot(ax=ax, color='#d73027', edgecolor='white', marker='*', markersize=150, label='karstic source')
    # ax.set(title='Raw DEM and karstic source', xlabel='Easting (m, EPSG:2056)', ylabel='Northing (m, EPSG:2056)')
    # ax.legend(loc='upper right')
    # ax.locator_params(axis = "x", nbins = 4)
    # fig.colorbar(image, ax=ax, label='Elevation (m a.s.l.)', shrink=0.8)
    


    ### Part 4 -------------------------------------------------------------------------------------------------------

    # fill the depression to not impact the flow path calculations
    status = wbt.fill_depressions(str(DEM_PATH), str(FILLED_DEM), fix_flats=True)
    if not FILLED_DEM.exists():
        raise RuntimeError(f'WhiteboxTools did not create {FILLED_DEM}. Status: {status}')

    # the created tif needs to be read in 
    filled_dem, _, _, _ = read_raster(FILLED_DEM)
    fill_depth = np.ma.array(filled_dem - dem, mask=np.ma.getmaskarray(dem) | np.ma.getmaskarray(filled_dem))
    changed = fill_depth > 1e-6
    changed_values = fill_depth[changed].compressed()

    fill_summary = pd.Series({
        'changed cells': int(changed.sum()),
        'changed area (km2)': float(changed.sum() * cell_area_m2 / 1e6),
        'maximum fill depth (m)': float(changed_values.max()) if changed_values.size else 0.0,
        'median positive fill depth (m)': float(np.median(changed_values)) if changed_values.size else 0.0,
    })
    display(fill_summary.to_frame('value').round(4))

    # plot the result
    # fig, axes = plt.subplots(1, 3, figsize=(17, 5), constrained_layout=True)
    # raw_image = axes[0].imshow(dem, extent=dem_extent, origin='upper', cmap='terrain')
    # axes[0].set_title('Raw DEM')
    # filled_image = axes[1].imshow(filled_dem, extent=dem_extent, origin='upper', cmap='terrain', vmin=dem.min(), vmax=dem.max())
    # axes[1].set_title('Depression-filled DEM')
    # diff_display = np.ma.masked_where(fill_depth <= 1e-6, fill_depth)
    # difference_image = axes[2].imshow(diff_display, extent=dem_extent, origin='upper', cmap='magma')
    # axes[2].set_title('Elevation added during filling')
    # for axis in axes:
    #     axis.set_xlabel('Easting (m)')
    #     axis.set_ylabel('Northing (m)')
    # fig.colorbar(raw_image, ax=axes[:2], label='Elevation (m a.s.l.)', shrink=0.8)
    # if changed_values.size:
    #     fig.colorbar(difference_image, ax=axes[2], label='Fill depth (m)', shrink=0.8)
    


    ### Part 5 -------------------------------------------------------------------------------------------------------

    # calculate the flow directions in each pixel
    status = wbt.d8_pointer(str(FILLED_DEM), str(D8_POINTER))
    if not D8_POINTER.exists():
        raise RuntimeError(f'WhiteboxTools did not create {D8_POINTER}. Status: {status}')

    # read in the tif file 
    pointer, _, _, _ = read_raster(D8_POINTER)
    direction_codes = [1, 2, 4, 8, 16, 32, 64, 128]
    direction_names = ['NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'N']
    direction_colors = ['#e41a1c', '#ff7f00', '#ffd92f', '#4daf4a', '#00a6a6', '#377eb8', '#6a51a3', '#984ea3']
    direction_counts = pd.DataFrame({
        'code': direction_codes,
        'direction': direction_names,
        'cell count': [int(np.sum(pointer == code)) for code in direction_codes],
    })
    display(direction_counts)

    # checks which cells have which pointer and assigns a colour to them
    pointer_display = np.ma.masked_where(~np.isin(pointer, direction_codes), pointer)
    boundaries = [0.5, 1.5, 3, 6, 12, 24, 48, 96, 160]
    cmap = ListedColormap(direction_colors)
    norm = BoundaryNorm(boundaries, cmap.N)

    # plot it
    # fig, ax = plt.subplots(figsize=(10, 7))
    # ax.imshow(pointer_display, extent=dem_extent, origin='upper', cmap=cmap, norm=norm)
    # ax.set(title='D8 flow direction', xlabel='Easting (m)', ylabel='Northing (m)')
    # legend_handles = [Patch(facecolor=color, label=f'{code}: {name}') for code, name, color in zip(direction_codes, direction_names, direction_colors)]
    # ax.legend(handles=legend_handles, title='Whitebox D8 code', ncol=2, loc='upper right')
    # ax.locator_params(axis = "x", nbins = 4)
    

    ### Part 6 -------------------------------------------------------------------------------------------------------

    # calculate for each cell how much water it gets from the uphill cells
    status = wbt.d8_flow_accumulation(
        str(FILLED_DEM),
        str(FLOW_ACCUM),
        out_type='cells',
        log=False,
    )
    if not FLOW_ACCUM.exists():
        raise RuntimeError(f'WhiteboxTools did not create {FLOW_ACCUM}. Status: {status}')

    # read in the tif
    accumulation, _, _, _ = read_raster(FLOW_ACCUM)
    accumulation_positive = np.ma.masked_less_equal(accumulation, 0) # all values equal or below 0 are masked
    contributing_area_km2 = accumulation * cell_area_m2 / 1e6

    print(f'Maximum accumulation: {float(accumulation.max()):,.0f} cells')
    print(f'Maximum contributing area: {float(contributing_area_km2.max()):,.1f} km2')

    # plot
    # fig, axes = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)
    # axes[0].imshow(filled_dem, extent=dem_extent, origin='upper', cmap='Greys_r')
    # acc_image = axes[0].imshow(
    #     accumulation_positive,
    #     extent=dem_extent,
    #     origin='upper',
    #     cmap='viridis',
    #     norm=LogNorm(vmin=1, vmax=float(accumulation_positive.max())),
    # )
    # axes[0].set_title('Flow accumulation')
    # axes[0].locator_params(axis = "x", nbins = 4)
    # fig.colorbar(acc_image, ax=axes[0], label='Upstream cells (log scale)', shrink=0.8)

    # area_image = axes[1].imshow(
    #     np.ma.masked_less_equal(contributing_area_km2, 0),
    #     extent=dem_extent,
    #     origin='upper',
    #     cmap='cividis',
    #     norm=LogNorm(vmin=cell_area_m2 / 1e6, vmax=float(contributing_area_km2.max())),
    # )
    # axes[1].set_title('Contributing area')
    # fig.colorbar(area_image, ax=axes[1], label='Contributing area (km2, log scale)', shrink=0.8)
    # axes[1].locator_params(axis = "x", nbins = 4)
    # for axis in axes:
    #     axis.set_xlabel('Easting (m)')
    #     axis.set_ylabel('Northing (m)')
    

    ### Part 7 -------------------------------------------------------------------------------------------------------

    # cell size is needed so the slopes are computed with the right proportions
    dx, dy = cell_width, cell_height

    # LightSource can't handle masked arrays well: fill nodata with NaN
    dem_arr = filled_dem.astype('float64').filled(np.nan)

    ls = LightSource(azdeg=315, altdeg=45)
    hillshade = ls.hillshade(dem_arr, vert_exag=2, dx=dx, dy=dy)

    ### Part 8 -------------------------------------------------------------------------------------------------------

    # cells over a threshold of accumulation are couted as streams
    STREAM_THRESHOLD_KM2 = 0.01

    stream_threshold_cells = STREAM_THRESHOLD_KM2 * 1e6 / cell_area_m2

    # this extracts only those cells that are higher than this threshold
    status = wbt.extract_streams(
        str(FLOW_ACCUM),
        str(STREAMS),
        threshold=stream_threshold_cells,
        zero_background=True,
    )
    if not STREAMS.exists():
        raise RuntimeError(f'WhiteboxTools did not create {STREAMS}. Status: {status}')

    # read in the tif
    streams, _, _, _ = read_raster(STREAMS)
    stream_mask = np.ma.masked_where(streams <= 0, streams)
    stream_cell_count = int(np.sum(streams > 0))
    approximate_stream_length_km = stream_cell_count * cell_width / 1000

    print(f'Threshold: {stream_threshold_cells:,.0f} cells = {STREAM_THRESHOLD_KM2:.2f} km2')
    print(f'Stream cells: {stream_cell_count:,}')
    print(f'Approximate raster stream length in the DEM extent: {approximate_stream_length_km:.1f} km')

    # plot the network
    # fig, ax = plt.subplots(figsize=(10, 7))
    # ax.imshow(hillshade, extent=dem_extent, origin='upper', cmap='Greys_r', alpha=0.6)
    # ax.imshow(stream_mask, extent=dem_extent, origin='upper', cmap=ListedColormap(["#ff0400"]), alpha=1)
    # outlets_dem_crs.plot(ax=ax, color='#d73027', edgecolor='white', marker='*', markersize=150, label='Measured outlet')
    # ax.set(title=f'Modeled streams: threshold = {STREAM_THRESHOLD_KM2:g} km2', xlabel='Easting (m)', ylabel='Northing (m)')
    # ax.locator_params(axis = "x", nbins = 4)
    # ax.legend()
    

    ### Part 9 -------------------------------------------------------------------------------------------------------
    # Catchment of every DEM pixel inside the polygon

    # 1) polygon -> boolean mask on the DEM grid (polygon is reprojected to the DEM CRS)
    polygon = gpd.read_file(POLYGON_PATH).to_crs(dem_crs)
    transform = dem_profile['transform']

    # cutting out the dem where it overlaps the polygon
    poly_mask = ~geometry_mask(
        polygon.geometry,
        out_shape=dem.shape,
        transform=transform,
        all_touched=False,          # True = also include cells only touched by the polygon edge
    )
    poly_mask &= ~np.ma.getmaskarray(dem)   # ignore nodata cells
    print(f'Pixels inside polygon: {poly_mask.sum():,}')

    # 2) per-pixel catchment size (upstream cells / area), only inside the polygon
    acc_arr = np.ma.filled(accumulation, np.nan).astype('float64') # convert the raster into into a numopy array
    catch_cells = np.where(poly_mask, acc_arr, np.nan) # takes the accumulation cells that align with the polygon
    catch_km2 = catch_cells * cell_area_m2 / 1e6

    # save as raster
    out_profile = dem_profile.copy()
    out_profile.update(dtype='float32', nodata=np.nan, count=1)
    with rasterio.open(CATCH_PIXEL_TIF, 'w', **out_profile) as dst:
        dst.write(catch_km2.astype('float32'), 1)

    # save as table + point layer (one row per pixel)
    rows, cols = np.where(poly_mask)
    xs, ys = xy(transform, rows, cols)          # cell centres
    pixel_df = pd.DataFrame({
        'row': rows, 'col': cols, 'x': xs, 'y': ys,
        'upstream_cells': catch_cells[rows, cols],
        'catchment_km2': catch_km2[rows, cols],
    })
    pixel_df.to_csv(OUTPUT_DIR / 'catchment_per_pixel.csv', index=False)
    pixel_gdf = gpd.GeoDataFrame(pixel_df, geometry=gpd.points_from_xy(pixel_df.x, pixel_df.y), crs=dem_crs)
    pixel_gdf.to_file(WATERSHED_GPKG, layer='pixel_catchments', driver='GPKG')

    display(pixel_df[['upstream_cells', 'catchment_km2']].describe().round(4))

    # 3) combined catchment of the whole polygon (union of all upstream areas)

    pp_profile = dem_profile.copy()
    pp_profile.update(dtype='int32', nodata=0, count=1)
    with rasterio.open(POLY_PTS_TIF, 'w', **pp_profile) as dst:
        dst.write(poly_mask.astype('int32'), 1)      # every polygon cell = pour point with ID 1

    wbt.watershed(str(D8_POINTER), str(POLY_PTS_TIF), str(POLY_WS_TIF))
    wbt.raster_to_vector_polygons(str(POLY_WS_TIF), str(POLY_WS_SHP))
    poly_ws = gpd.read_file(POLY_WS_SHP).dissolve().reset_index(drop=True)[['geometry']]
    poly_ws['area_km2'] = poly_ws.geometry.area / 1e6
    poly_ws.to_file(WATERSHED_GPKG, layer='polygon_catchment', driver='GPKG')
    print(f'Total catchment draining through the polygon: {poly_ws.area_km2.iloc[0]:.3f} km2')

    # 4) plot
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.imshow(hillshade, extent=dem_extent, origin='upper', cmap='Greys_r', alpha=0.6)
    poly_ws.boundary.plot(ax=ax, color='black', linewidth=2, label='Catchment of polygon')
    polygon.boundary.plot(ax=ax, color='red', linewidth=1.5, label='Polygon')
    im = ax.imshow(np.ma.masked_invalid(catch_km2), extent=dem_extent, origin='upper',
                   cmap='viridis', norm=LogNorm(vmin=cell_area_m2 / 1e6, vmax=np.nanmax(catch_km2)),
                   interpolation='nearest', zorder=3)
    fig.colorbar(im, ax=ax, label='Catchment area per pixel (km2, log)', shrink=0.8)

    minx, miny, maxx, maxy = poly_ws.total_bounds
    pad = 0.05 * max(maxx - minx, maxy - miny)
    ax.set_xlim(max(minx - pad, left), min(maxx + pad, right))
    ax.set_ylim(max(miny - pad, bottom), min(maxy + pad, top))
    ax.set(title='Catchment area of each pixel inside the polygon',
           xlabel='Easting (m, EPSG:2056)', ylabel='Northing (m, EPSG:2056)')
    ax.legend(loc='upper right')
    fig.savefig(OUTPUT_DIR / 'catchment_per_pixel.png', dpi=200, bbox_inches='tight')



if __name__ == "__main__":
    do_catchment_analysis()