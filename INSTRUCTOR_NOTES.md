# Instructor notes

These values provide a quick check that the notebook is running as intended.
Small differences can occur with other WhiteboxTools or geospatial-library
versions.

## Reference outputs

- DEM CRS: `EPSG:3035`
- DEM resolution: `25 m`
- DEM dimensions: `941 x 1053` cells
- transformed outlet: approximately `4,085,464.78 / 2,660,248.45`
- snapped outlet: approximately `4,085,462.50 / 2,660,112.50`
- snapping displacement: approximately `136.0 m`
- watershed cells: approximately `160,258`
- modeled topographic area: approximately `100.16 km2`
- FOEN reference area: approximately `112 km2`
- relative area difference: approximately `-10.6%`

## Points worth discussing

### Depression filling

The EU-DEM surface contains substantial filled areas in this domain, including
some large elevation corrections. This is a useful warning against assuming
that DEM conditioning is a harmless technicality. Ask students to identify
where the largest changes occur and to compare filling with breaching as an
advanced exercise.

### Stream threshold

The default `1 km2` threshold is illustrative, not calibrated. Students should
observe that a stream network is a model output controlled by both terrain and
the chosen initiation threshold.

### Outlet snapping

The measured outlet moves by about 136 m. The displacement is below the 250 m
search radius and moves the point onto a high-accumulation path. Emphasize that
a larger search radius could snap to the wrong river, especially near a
confluence or drainage divide.

### Area mismatch

Do not encourage students to tune parameters only to reproduce the official
area. The discrepancy is an opportunity to distinguish a DEM-derived surface
catchment from an independently mapped hydrological catchment. Possible causes
include terrain resolution, conditioning, routing assumptions, outlet
location, subsurface transfers, artificial drainage, and differences in source
cartography.

## Suggested assessment

- 25%: correct and clearly labelled intermediate maps
- 25%: explanation of hydrological conditioning and D8 routing
- 20%: outlet snapping and catchment validation
- 20%: sensitivity experiments and quantitative comparison
- 10%: concise discussion of limitations and reproducibility
