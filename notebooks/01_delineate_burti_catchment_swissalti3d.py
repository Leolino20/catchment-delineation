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

    DEM_PATH = (PROJECT_ROOT / 'data' / 'dem_nostreet.tif').resolve()
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
    WATERSHED_GPKG = OUTPUT_DIR / 'watershed.gpkg'

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    print(wbt.version().splitlines()[0])
    print('Input DEM:', DEM_PATH)
    print('Output directory:', OUTPUT_DIR)


    ### Part 3 -------------------------------------------------------------------------------------------------------

    OUTLETS = [
        {'station_id': 1, 'x': 2_502_174.15, 'y': 1_156_761.21, 'color': '#e41a1c'},
        {'station_id': 2, 'x': 2_502_087.39,  'y': 1_156_690.95, 'color': '#377eb8'}, 
        {'station_id': 3, 'x': 2_502_341.69,  'y': 1_156_960.69,  'color': '#4daf4a'},
    ]
 
    WORK_DIR = OUTLET_RAW.parent   # per-outlet files are written next to your existing outlet file
 
    with rasterio.open(DEM_PATH) as src:
        dem_crs = src.crs
 
    outlets_lv95 = gpd.GeoDataFrame(
        {'station_id': [o['station_id'] for o in OUTLETS]},
        geometry=[Point(o['x'], o['y']) for o in OUTLETS],
        crs='EPSG:2056',
    )
    outlets_dem_crs = outlets_lv95.to_crs(dem_crs)

    ### Part 4 -------------------------------------------------------------------------------------------------------

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
    


    ### Part 6 -------------------------------------------------------------------------------------------------------

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
    


    ### Part 7 -------------------------------------------------------------------------------------------------------

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
    

    ### Part 8 -------------------------------------------------------------------------------------------------------

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
    

    ### Part 9 -------------------------------------------------------------------------------------------------------

    # cell size is needed so the slopes are computed with the right proportions
    dx, dy = cell_width, cell_height

    # LightSource can't handle masked arrays well: fill nodata with NaN
    dem_arr = filled_dem.astype('float64').filled(np.nan)

    ls = LightSource(azdeg=315, altdeg=45)
    hillshade = ls.hillshade(dem_arr, vert_exag=2, dx=dx, dy=dy)

    ### Part 10 -------------------------------------------------------------------------------------------------------

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
    
    

    ### Part 11 -------------------------------------------------------------------------------------------------------


    SNAP_DISTANCE_M = 10.0
    results = []


    for outlet, (_, row) in zip(OUTLETS, outlets_dem_crs.iterrows()):
        sid = int(outlet['station_id'])
        raw_path     = WORK_DIR / f'outlet_{sid}_raw.shp'
        snapped_path = WORK_DIR / f'outlet_{sid}_snapped.shp'
        ws_raster_p  = WORK_DIR / f'watershed_{sid}.tif'
        ws_vector_p  = WORK_DIR / f'watershed_{sid}.shp'
 
        # raw outlet as its own file
        gpd.GeoDataFrame({'station_id': [sid]}, geometry=[row.geometry], crs=dem_crs).to_file(raw_path)
 
        # snap to the flow accumulation
        status = wbt.snap_pour_points(str(raw_path), str(FLOW_ACCUM), str(snapped_path), snap_dist=SNAP_DISTANCE_M)
        if not snapped_path.exists():
            raise RuntimeError(f'Snapping failed for station {sid}. Status: {status}')
        snapped = gpd.read_file(snapped_path)
        snap_dist = row.geometry.distance(snapped.geometry.iloc[0])
 
        # watershed raster
        status = wbt.watershed(str(D8_POINTER), str(snapped_path), str(ws_raster_p))
        if not ws_raster_p.exists():
            raise RuntimeError(f'Watershed failed for station {sid}. Status: {status}')
        ws_raster, _, _, _ = read_raster(ws_raster_p)
        ws_bool = np.ma.filled(ws_raster, 0) > 0
 
        # watershed polygon
        status = wbt.raster_to_vector_polygons(str(ws_raster_p), str(ws_vector_p))
        if not ws_vector_p.exists():
            raise RuntimeError(f'Vectorizing failed for station {sid}. Status: {status}')
        ws = gpd.read_file(ws_vector_p).dissolve().reset_index(drop=True)
        ws = ws[['geometry']].copy()          # drops FID, VALUE and other columns from Whitebox
        ws['station_id'] = sid
        ws['area_km2'] = ws.geometry.area / 1e6
 
        modeled = float(ws['area_km2'].iloc[0])
        results.append({
            'station_id': sid,
            'color': outlet['color'],
            'modeled_km2': modeled,
            'snap_m': snap_dist,
            'measured': row.geometry,
            'snapped': snapped.geometry.iloc[0],
            'ws': ws,
            'ws_bool': ws_bool,
        })
 
    watersheds = pd.concat([r['ws'] for r in results], ignore_index=True)
    watersheds.to_file(WATERSHED_GPKG, layer='watersheds', driver='GPKG')
 
    evaluation = pd.DataFrame([
        {k: r[k] for k in ('station_id', 'modeled_km2', 'snap_m')}
        for r in results
    ]).set_index('station_id')
    display(evaluation.round(2))

    # total area = area of the union, so overlapping (nested) catchments are not counted twice
    total_area_km2 = float(watersheds.union_all().area / 1e6)
    print(f'Total catchment area: {total_area_km2:.2f} km2')
    ### Part 14 -------------------------------------------------------------------------------------------------------
    
    # streams that lie inside any of the three catchments
    any_ws = np.any([r['ws_bool'] for r in results], axis=0)
    stream_bool = (np.ma.filled(streams, 0) > 0) & any_ws
    stream_thick = binary_dilation(stream_bool, iterations=2)
    stream_plot = np.ma.masked_where(~stream_thick, stream_thick)
    halo_bool = binary_dilation(stream_bool, iterations=3)
    halo = np.ma.masked_where(~halo_bool, halo_bool)
 
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.imshow(hillshade, extent=dem_extent, origin='upper', cmap='Greys_r', alpha=0.6)
 
    # large catchments first, so nested smaller ones stay visible on top
    for r in sorted(results, key=lambda r: r['modeled_km2'], reverse=True):
        r['ws'].plot(ax=ax, facecolor=r['color'], edgecolor='none', alpha=0.25)
 
    ax.imshow(halo, extent=dem_extent, origin='upper', cmap=ListedColormap(['white']),
              alpha=0.9, interpolation='nearest', zorder=2)
    ax.imshow(stream_plot, extent=dem_extent, origin='upper', cmap=ListedColormap(['#0050ff']),
              alpha=1, interpolation='nearest', zorder=3)
 
    for r in results:
        r['ws'].boundary.plot(ax=ax, color=r['color'], linewidth=2.2, zorder=4,
                              label=f"Station {r['station_id']}: {r['modeled_km2']:.2f} km2 ")
        mx, my = r['measured'].x, r['measured'].y
        sx, sy = r['snapped'].x, r['snapped'].y
        ax.scatter(mx, my, marker='*', s=170, c='#f0e442', edgecolors='black', zorder=5)
        ax.scatter(sx, sy, marker='X', s=90, c=r['color'], edgecolors='black', zorder=6)
        ax.annotate(str(r['station_id']), (sx, sy), xytext=(6, 6), textcoords='offset points',
                    fontweight='bold', zorder=7,
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=0.8))
 
    # legend entries for the markers
    ax.scatter([], [], marker='*', s=170, c='#f0e442', edgecolors='black', label='Measured outlet')
    ax.scatter([], [], marker='X', s=90, c='grey', edgecolors='black', label='Snapped outlet')
 
    minx, miny, maxx, maxy = watersheds.total_bounds
    pad = 0.1 * max(maxx - minx, maxy - miny)
    xlim = (max(minx - pad, left),   min(maxx + pad, right))
    ylim = (max(miny - pad, bottom), min(maxy + pad, top))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
 
    # scale bar and north arrow (unchanged)
    view_w = xlim[1] - xlim[0]
    view_h = ylim[1] - ylim[0]
    candidates = [100, 200, 250, 500, 1_000, 2_000, 5_000]
    scale_length = max(c for c in candidates if c <= 0.3 * view_w)
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
 
    ax.set(title='Catchment areas of the ditches',
           xlabel='Easting (m, EPSG:2056)', ylabel='Northing (m, EPSG:2056)')
    ax.legend(loc='upper right')
    fig.savefig(OUTPUT_DIR / 'final_catchment_map_all.png', dpi=200, bbox_inches='tight')


if __name__ == "__main__":
    do_catchment_analysis()