import rasterio
from rasterio.warp import transform_bounds
from rasterio.merge import merge
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from rasterio.plot import show



def do_crop_merge_dem():

    # define your box (in LV95)
    lon_min = 2501690.17
    lat_min = 1155001.27
    lon_max = 2503639.05
    lat_max = 1158009.32

    # create a tuple with all bounds in LV03
    left, bottom, right, top = (
        lon_min, lat_min, lon_max, lat_max
    )

    bounds = left, bottom, right, top

    # set a wd to the tif files
    tif_paths = sorted(Path("/home/tleona/Documents/burtigniere/gis/catchment_analysis").glob("*.tif"))
    srcs = [rasterio.open(p) for p in tif_paths]

    # merge all opened srcs within the bounds
    mosaic, mosaic_transform = merge(srcs, bounds = bounds)

    # make sure the same formatting is used
    profile = srcs[0].profile.copy()
    profile.update(
        driver="GTiff",
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        transform=mosaic_transform,
        compress="deflate",
        tiled=True,
    )

    # save the file 
    with rasterio.open("dem_swissalti3d_merged_burti.tif", "w", **profile) as dst:
        dst.write(mosaic)

    for s in srcs:
        s.close()

    # plot the dem
    dem = mosaic[0]
    dem_plot = np.ma.masked_equal(dem, profile["nodata"]) if profile.get("nodata") is not None else dem

    fig, ax = plt.subplots(figsize=(8, 6))
    im = show(dem_plot, transform=mosaic_transform, ax=ax, cmap="terrain")
    fig.colorbar(im.get_images()[0], ax=ax, label="Elevation (m)")
    ax.set_title("Merged swissALTI3D")
    #ax.locator_params(axis="x", nbins=4)
    ax.ticklabel_format(axis="x", style="plain", useOffset=False)
    plt.show()
    


if __name__ == "__main__":
    do_crop_merge_dem()

