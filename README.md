# Catchment delineation with WhiteboxTools

This teaching repository contains a step-by-step Jupyter notebook for
delineating a drainage catchment from a digital elevation model (DEM) and an
outlet coordinate. The worked example is the **Seyon at Valangin** hydrometric
station in Switzerland.

The notebook deliberately exposes every intermediate product. It is intended
as a practical hydrology and GIS exercise, not as a one-click delineation
script.

## Learning objectives

After completing the notebook, students should be able to:

- explain why a DEM must be hydrologically conditioned;
- inspect where and by how much depressions were filled;
- interpret a D8 flow-direction raster;
- calculate flow accumulation and convert cells to contributing area;
- extract a stream network using an area threshold;
- explain why an observed outlet is snapped to a modeled drainage path;
- delineate and vectorize the upstream catchment;
- evaluate the result against independent station metadata; and
- discuss uncertainty caused by DEM resolution, outlet placement, routing
  assumptions, and differences between topographic and hydrological divides.

## Worked example

The example uses FOEN hydrometric station **2458, Seyon - Valangin**:

- outlet coordinates: `2,559,353 / 1,206,856` in LV95 (`EPSG:2056`);
- official catchment area: approximately `112 km2`;
- station elevation: `635 m a.s.l.`

Station metadata are available from the
[Federal Office for the Environment](https://www.hydrodaten.admin.ch/en/seen-und-fluesse/stations/2458).

## Use on EPFL Noto

1. Sign in to [EPFL Noto](https://noto.epfl.ch/hub/login?next=%2Fhub%2F).
2. In JupyterLab, open the Git panel and choose **Clone a Repository**.
3. Paste this repository's GitHub URL.
4. Open `notebooks/01_delineate_seyon_catchment.ipynb`.
5. Run the notebook from top to bottom. The setup cell installs any missing
   packages into the active Noto kernel.

The DEM is already included under `data/`; no local paths or separate data
downloads are required. Generated files are written to `outputs/`, which is
ignored by Git.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip install jupyterlab
jupyter lab
```

## Repository contents

```text
data/
  seyon_valangin_dem_eudem25.tif
  README.md
notebooks/
  01_delineate_seyon_catchment.ipynb
outputs/                         # created by the notebook, not versioned
requirements.txt
```

## Expected result

With the supplied parameters, the topographic catchment is approximately
`100.2 km2`, compared with the FOEN reference value of `112 km2`. This
difference is retained intentionally: evaluating why an apparently reasonable
GIS result differs from reference metadata is an important part of the lab.

## Software and documentation

The workflow uses the open-source `whitebox` Python package and WhiteboxTools.
The processing sequence follows the Whitebox hydrology workflow: condition the
DEM, compute D8 flow direction and accumulation, snap the pour point, and
delineate the watershed. See the
[WhiteboxTools documentation](https://www.whiteboxgeo.com/manuals/legacy/tool_help.html)
for tool descriptions.

## License and data acknowledgement

The teaching code and text are released under the MIT License.

The DEM is a spatial subset and modified derivative of EU-DEM v1.1 at 25 m
resolution. Generated using European Union's Copernicus Land Monitoring
Service information. The source product is described in the
[EEA data catalogue](https://cis2.eea.europa.eu/data/42/). The repository is
not endorsed by the European Union, the EEA, FOEN, Whitebox Geospatial, or EPFL.

