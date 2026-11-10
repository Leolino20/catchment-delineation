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
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point
import whitebox
from matplotlib.colors import LightSource
from scipy.ndimage import binary_dilation


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

    DEM_PATH = (PROJECT_ROOT / 'data' / 'dem_swissalti3d_merged_burti.tif').resolve()
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
    OUTLET_RAW = OUTPUT_DIR / '05_outlet_raw.shp'
    OUTLET_SNAPPED = OUTPUT_DIR / '06_outlet_snapped.shp'
    WATERSHED_RASTER = OUTPUT_DIR / '07_watershed.tif'
    WATERSHED_VECTOR = OUTPUT_DIR / '08_watershed.shp'
    WATERSHED_GPKG = OUTPUT_DIR / 'seyon_watershed.gpkg'

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    print(wbt.version().splitlines()[0])
    print('Input DEM:', DEM_PATH)
    print('Output directory:', OUTPUT_DIR)


    ### Part 3 -------------------------------------------------------------------------------------------------------

    # verify the raster
 #   with rasterio.open(DEM_PATH) as src:
 #       print("CRS:", src.crs)
 #       print("bounds:", src.bounds)
 #       print("nodata:", src.nodata)
 #       print("dtype:", src.dtypes[0])
 #       arr = src.read(1, masked=True)
 #       print("valid pixels:", arr.count(), "of", arr.size)
 #       raw = src.read(1)
 #       print("min/max raw:", raw.min(), raw.max())
 #       print("unique (first 5):", np.unique(raw)[:5])

 #   plt.imshow(arr, cmap = "terrain")
 #   


    ### Part 4 -------------------------------------------------------------------------------------------------------

    STATION_ID = 1
    OUTLET_X_LV95 = 2_502_139.33
    OUTLET_Y_LV95 = 1_156_406.98
    OFFICIAL_AREA_KM2 = 112.0

    with rasterio.open(DEM_PATH) as src:
        dem_crs = src.crs # retrieves the coordinate system of the raster dataset

    outlet_lv95 = gpd.GeoDataFrame(
        {'station_id': [STATION_ID], 'source': ['FOEN']},
        geometry=[Point(OUTLET_X_LV95, OUTLET_Y_LV95)],
        crs='EPSG:2056',
    )
    outlet_dem_crs = outlet_lv95.to_crs(dem_crs)
    outlet_dem_crs.to_file(OUTLET_RAW)

    coordinate_table = pd.DataFrame({
        'CRS': ['LV95 (EPSG:2056)', str(dem_crs)],
        'x': [OUTLET_X_LV95, outlet_dem_crs.geometry.x.iloc[0]],
        'y': [OUTLET_Y_LV95, outlet_dem_crs.geometry.y.iloc[0]],
    })
    coordinate_table.round(2)


    ### Part 5 -------------------------------------------------------------------------------------------------------

    def read_raster(path: Path):
        with rasterio.open(path) as src:
            data = src.read(1, masked=True)
            extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
            profile = src.profile.copy() # metadata of the raster (needed to do identical rasters) (driver, dtype,nodata,widht,height,count,crs,transform)
            bounds = src.bounds
        return data, extent, profile, bounds


    dem, dem_extent, dem_profile, dem_bounds = read_raster(DEM_PATH)
    #cell_width = abs(dem_profile['transform'].a) # pixel width (change in x per column)
    #cell_height = abs(dem_profile['transform'].e) # pixel height (change in y per row)
    cell_width, cell_height = src.res
    cell_area_m2 = cell_width * cell_height

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

    fig, ax = plt.subplots(figsize=(10, 7))
    image = ax.imshow(dem, extent=dem_extent, origin='upper', cmap='terrain')
    outlet_dem_crs.plot(ax=ax, color='#d73027', edgecolor='white', marker='*', markersize=150, label='karstic source')
    ax.set(title='Raw DEM and karstic source', xlabel='Easting (m, EPSG:2056)', ylabel='Northing (m, EPSG:2056)')
    ax.legend(loc='upper right')
    ax.locator_params(axis = "x", nbins = 4)
    fig.colorbar(image, ax=ax, label='Elevation (m a.s.l.)', shrink=0.8)
    


    ### Part 6 -------------------------------------------------------------------------------------------------------
    status = wbt.fill_depressions(str(DEM_PATH), str(FILLED_DEM), fix_flats=True)
    if not FILLED_DEM.exists():
        raise RuntimeError(f'WhiteboxTools did not create {FILLED_DEM}. Status: {status}')

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

    fig, axes = plt.subplots(1, 3, figsize=(17, 5), constrained_layout=True)
    raw_image = axes[0].imshow(dem, extent=dem_extent, origin='upper', cmap='terrain')
    axes[0].set_title('Raw DEM')
    filled_image = axes[1].imshow(filled_dem, extent=dem_extent, origin='upper', cmap='terrain', vmin=dem.min(), vmax=dem.max())
    axes[1].set_title('Depression-filled DEM')
    diff_display = np.ma.masked_where(fill_depth <= 1e-6, fill_depth)
    difference_image = axes[2].imshow(diff_display, extent=dem_extent, origin='upper', cmap='magma')
    axes[2].set_title('Elevation added during filling')
    for axis in axes:
        axis.set_xlabel('Easting (m)')
        axis.set_ylabel('Northing (m)')
    fig.colorbar(raw_image, ax=axes[:2], label='Elevation (m a.s.l.)', shrink=0.8)
    if changed_values.size:
        fig.colorbar(difference_image, ax=axes[2], label='Fill depth (m)', shrink=0.8)
    


    ### Part 7 -------------------------------------------------------------------------------------------------------

    status = wbt.d8_pointer(str(FILLED_DEM), str(D8_POINTER))
    if not D8_POINTER.exists():
        raise RuntimeError(f'WhiteboxTools did not create {D8_POINTER}. Status: {status}')

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

    pointer_display = np.ma.masked_where(~np.isin(pointer, direction_codes), pointer)
    boundaries = [0.5, 1.5, 3, 6, 12, 24, 48, 96, 160]
    cmap = ListedColormap(direction_colors)
    norm = BoundaryNorm(boundaries, cmap.N)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(pointer_display, extent=dem_extent, origin='upper', cmap=cmap, norm=norm)
    ax.set(title='D8 flow direction', xlabel='Easting (m)', ylabel='Northing (m)')
    legend_handles = [Patch(facecolor=color, label=f'{code}: {name}') for code, name, color in zip(direction_codes, direction_names, direction_colors)]
    ax.legend(handles=legend_handles, title='Whitebox D8 code', ncol=2, loc='upper right')
    ax.locator_params(axis = "x", nbins = 4)
    

    ### Part 8 -------------------------------------------------------------------------------------------------------

    status = wbt.d8_flow_accumulation(
        str(FILLED_DEM),
        str(FLOW_ACCUM),
        out_type='cells',
        log=False,
    )
    if not FLOW_ACCUM.exists():
        raise RuntimeError(f'WhiteboxTools did not create {FLOW_ACCUM}. Status: {status}')

    accumulation, _, _, _ = read_raster(FLOW_ACCUM)
    accumulation_positive = np.ma.masked_less_equal(accumulation, 0)
    contributing_area_km2 = accumulation * cell_area_m2 / 1e6

    print(f'Maximum accumulation: {float(accumulation.max()):,.0f} cells')
    print(f'Maximum contributing area: {float(contributing_area_km2.max()):,.1f} km2')

    fig, axes = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)
    axes[0].imshow(filled_dem, extent=dem_extent, origin='upper', cmap='Greys_r')
    acc_image = axes[0].imshow(
        accumulation_positive,
        extent=dem_extent,
        origin='upper',
        cmap='viridis',
        norm=LogNorm(vmin=1, vmax=float(accumulation_positive.max())),
    )
    axes[0].set_title('Flow accumulation')
    axes[0].locator_params(axis = "x", nbins = 4)
    fig.colorbar(acc_image, ax=axes[0], label='Upstream cells (log scale)', shrink=0.8)

    area_image = axes[1].imshow(
        np.ma.masked_less_equal(contributing_area_km2, 0),
        extent=dem_extent,
        origin='upper',
        cmap='cividis',
        norm=LogNorm(vmin=cell_area_m2 / 1e6, vmax=float(contributing_area_km2.max())),
    )
    axes[1].set_title('Contributing area')
    fig.colorbar(area_image, ax=axes[1], label='Contributing area (km2, log scale)', shrink=0.8)
    axes[1].locator_params(axis = "x", nbins = 4)
    for axis in axes:
        axis.set_xlabel('Easting (m)')
        axis.set_ylabel('Northing (m)')
    

    ### Part 9 -------------------------------------------------------------------------------------------------------

    # cell size is needed so the slopes are computed with the right proportions
    dx, dy = cell_width, cell_height

    # LightSource can't handle masked arrays well: fill nodata with NaN
    dem_arr = filled_dem.astype('float64').filled(np.nan)

    ls = LightSource(azdeg=315, altdeg=45)
    hillshade = ls.hillshade(dem_arr, vert_exag=2, dx=dx, dy=dy)

    ### Part 10 -------------------------------------------------------------------------------------------------------

    STREAM_THRESHOLD_KM2 = 0.01

    stream_threshold_cells = STREAM_THRESHOLD_KM2 * 1e6 / cell_area_m2

    status = wbt.extract_streams(
        str(FLOW_ACCUM),
        str(STREAMS),
        threshold=stream_threshold_cells,
        zero_background=True,
    )
    if not STREAMS.exists():
        raise RuntimeError(f'WhiteboxTools did not create {STREAMS}. Status: {status}')

    streams, _, _, _ = read_raster(STREAMS)
    stream_mask = np.ma.masked_where(streams <= 0, streams)
    stream_cell_count = int(np.sum(streams > 0))
    approximate_stream_length_km = stream_cell_count * cell_width / 1000

    print(f'Threshold: {stream_threshold_cells:,.0f} cells = {STREAM_THRESHOLD_KM2:.2f} km2')
    print(f'Stream cells: {stream_cell_count:,}')
    print(f'Approximate raster stream length in the DEM extent: {approximate_stream_length_km:.1f} km')

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(hillshade, extent=dem_extent, origin='upper', cmap='Greys_r', alpha=0.6)
    ax.imshow(stream_mask, extent=dem_extent, origin='upper', cmap=ListedColormap(["#ff0400"]), alpha=1)
    outlet_dem_crs.plot(ax=ax, color='#d73027', edgecolor='white', marker='*', markersize=150, label='Measured outlet')
    ax.set(title=f'Modeled streams: threshold = {STREAM_THRESHOLD_KM2:g} km2', xlabel='Easting (m)', ylabel='Northing (m)')
    ax.locator_params(axis = "x", nbins = 4)
    ax.legend()
    
    

    ### Part 11 -------------------------------------------------------------------------------------------------------


    SNAP_DISTANCE_M = 10.0
    status = wbt.snap_pour_points(
        str(OUTLET_RAW),
        str(FLOW_ACCUM),
        str(OUTLET_SNAPPED),
        snap_dist=SNAP_DISTANCE_M,
    )
    if not OUTLET_SNAPPED.exists():
        raise RuntimeError(f'WhiteboxTools did not create {OUTLET_SNAPPED}. Status: {status}')

    outlet_snapped = gpd.read_file(OUTLET_SNAPPED)
    snap_displacement_m = outlet_dem_crs.geometry.iloc[0].distance(outlet_snapped.geometry.iloc[0])

    snap_table = pd.DataFrame({
        'point': ['measured', 'snapped'],
        'x': [outlet_dem_crs.geometry.x.iloc[0], outlet_snapped.geometry.x.iloc[0]],
        'y': [outlet_dem_crs.geometry.y.iloc[0], outlet_snapped.geometry.y.iloc[0]],
    })
    display(snap_table.round(2))
    print(f'Snap displacement: {snap_displacement_m:.1f} m')

    x0, y0 = outlet_dem_crs.geometry.x.iloc[0], outlet_dem_crs.geometry.y.iloc[0]
    zoom = 600
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(
        accumulation_positive,
        extent=dem_extent,
        origin='upper',
        cmap='viridis',
        norm=LogNorm(vmin=1, vmax=float(accumulation_positive.max())),
    )
    outlet_dem_crs.plot(ax=ax, color='#d73027', edgecolor='white', marker='*', markersize=180, label='Measured outlet')
    outlet_snapped.plot(ax=ax, color='#00ffff', edgecolor='black', marker='X', markersize=110, label='Snapped outlet')
    ax.plot(
        [outlet_dem_crs.geometry.x.iloc[0], outlet_snapped.geometry.x.iloc[0]],
        [outlet_dem_crs.geometry.y.iloc[0], outlet_snapped.geometry.y.iloc[0]],
        color='white', linewidth=1.5, linestyle='--',
    )
    left, right, bottom, top = dem_extent
    ax.set_xlim(max(x0 - zoom, left), min(x0 + zoom, right))
    ax.set_ylim(max(y0 - zoom, bottom), min(y0 + zoom, top))
    ax.set(title='Measured and snapped outlet', xlabel='Easting (m)', ylabel='Northing (m)')
    ax.legend()
    
    

    ### Part 12 -------------------------------------------------------------------------------------------------------

    status = wbt.watershed(str(D8_POINTER), str(OUTLET_SNAPPED), str(WATERSHED_RASTER))
    if not WATERSHED_RASTER.exists():
        raise RuntimeError(f'WhiteboxTools did not create {WATERSHED_RASTER}. Status: {status}')

    watershed_raster, _, _, _ = read_raster(WATERSHED_RASTER)
    watershed_mask = np.ma.masked_where(watershed_raster <= 0, watershed_raster)
    watershed_cells = int(np.sum(watershed_raster > 0))
    watershed_raster_area_km2 = watershed_cells * cell_area_m2 / 1e6

    print(f'Watershed cells: {watershed_cells:,}')
    print(f'Raster area: {watershed_raster_area_km2:.2f} km2')

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(hillshade, extent=dem_extent, origin='upper', cmap='Greys_r', alpha = 0.6)
    ax.imshow(watershed_mask, extent=dem_extent, origin='upper', cmap=ListedColormap(['#56b4e9']), alpha=0.65)
    ax.imshow(stream_mask, extent=dem_extent, origin='upper', cmap=ListedColormap(['#004c6d']), alpha=0.9)
    outlet_snapped.plot(ax=ax, color='#d73027', edgecolor='black', marker='X', markersize=100, label='Snapped outlet')
    ax.set(title='D8 watershed raster', xlabel='Easting (m)', ylabel='Northing (m)')
    ax.locator_params(axis = "x", nbins = 4)
    ax.legend()
    
    

    ### Part 13 -------------------------------------------------------------------------------------------------------

    status = wbt.raster_to_vector_polygons(str(WATERSHED_RASTER), str(WATERSHED_VECTOR))
    if not WATERSHED_VECTOR.exists():
        raise RuntimeError(f'WhiteboxTools did not create {WATERSHED_VECTOR}. Status: {status}')

    watershed_parts = gpd.read_file(WATERSHED_VECTOR)
    watershed = watershed_parts.dissolve().reset_index(drop=True)
    watershed['station_id'] = STATION_ID
    watershed['area_km2'] = watershed.geometry.area / 1e6
    watershed.to_file(WATERSHED_GPKG, layer='watershed', driver='GPKG')

    modeled_area_km2 = float(watershed['area_km2'].iloc[0])
    area_difference_km2 = modeled_area_km2 - OFFICIAL_AREA_KM2
    relative_difference_percent = 100 * area_difference_km2 / OFFICIAL_AREA_KM2

    evaluation = pd.Series({
        'modeled topographic area (km2)': modeled_area_km2,
        'FOEN reference area (km2)': OFFICIAL_AREA_KM2,
        'difference (km2)': area_difference_km2,
        'relative difference (%)': relative_difference_percent,
        'outlet displacement (m)': snap_displacement_m,
    })
    evaluation.to_frame('value').round(2)

    ### Part 14 -------------------------------------------------------------------------------------------------------
    
    stream_in_watershed = np.ma.masked_where((streams <= 0) | (watershed_raster <= 0), streams)

    stream_bool = ~np.ma.getmaskarray(stream_in_watershed)        # True where a stream is in the watershed
    stream_thick = binary_dilation(stream_bool, iterations=2)     # more iterations = thicker
    stream_plot = np.ma.masked_where(~stream_thick, stream_thick)
    halo = binary_dilation(stream_bool, iterations=3)
    halo = np.ma.masked_where(~halo, halo)

    fig, ax = plt.subplots(figsize=(11, 8))
    ax.imshow(hillshade, extent=dem_extent, origin='upper', cmap='Greys_r', alpha=0.6)
    ax.imshow(halo, extent=dem_extent, origin='upper',
            cmap=ListedColormap(['white']), alpha=0.9,
            interpolation='nearest', zorder=2)
    ax.imshow(stream_plot, extent=dem_extent, origin='upper',
            cmap=ListedColormap(['#0050ff']), alpha=1,
            interpolation='nearest', zorder=3)
    watershed.boundary.plot(ax=ax, color='black', linewidth=2.0, label='Delineated catchment')
    outlet_dem_crs.plot(ax=ax, color='#f0e442', edgecolor='black', marker='*', markersize=170, label='Measured outlet')
    outlet_snapped.plot(ax=ax, color='#d55e00', edgecolor='black', marker='X', markersize=90, label='Snapped outlet')

    minx, miny, maxx, maxy = watershed.total_bounds
    pad = 0.1 * max(maxx - minx, maxy - miny)   # proportional margin
    xlim = (max(minx - pad, left),   min(maxx + pad, right))
    ylim = (max(miny - pad, bottom), min(maxy + pad, top))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)


    # scale bar sized to the visible area
    view_w = xlim[1] - xlim[0]
    view_h = ylim[1] - ylim[0]
    candidates = [100, 200, 250, 500, 1_000, 2_000, 5_000]
    scale_length = max(c for c in candidates if c <= 0.3 * view_w)  # at most ~30% of width
    scale_x = xlim[0] + 0.05 * view_w
    scale_y = ylim[0] + 0.05 * view_h


    ax.plot([scale_x, scale_x + scale_length], [scale_y, scale_y],
            color='black', linewidth=3, solid_capstyle='butt')
    ax.text(scale_x + scale_length / 2, scale_y + 0.01 * view_h,
            f'{scale_length / 1000:g} km' if scale_length >= 1000 else f'{scale_length} m',
            ha='center', va='bottom')
    ax.annotate('N', xy=(0.06, 0.91), xytext=(0.06, 0.80), xycoords='axes fraction',
                ha='center', va='center', fontweight='bold',
                arrowprops=dict(facecolor='black', width=3, headwidth=10))

    ax.set(
        title=f'Catchment area of karstic source: {modeled_area_km2:.2f} km2',
        xlabel='Easting (m, EPSG:2056)',
        ylabel='Northing (m, EPSG:2056)',
    )
    ax.legend(loc='upper right')
    fig.savefig(OUTPUT_DIR / 'final_catchment_map_S5.png', dpi=200, bbox_inches='tight')
    #plt.show()

    ### Part 15 -------------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    do_catchment_analysis()
