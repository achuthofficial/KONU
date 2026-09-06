# Pincode Boundary Data Sources

Official India Post pincode boundary polygons (GeoJSON), used for offline
reverse geocoding (latitude/longitude → pincode).

| File | Coverage | Source |
|---|---|---|
| `telangana.geojson` | Telangana (675 pincode polygons) | GitHub mirror of data.gov.in dataset |
| `andhra-pradesh.geojson` | Andhra Pradesh | GitHub mirror of data.gov.in dataset |

- Original official dataset: [All India Pincode Boundary GeoJSON — data.gov.in](https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json)
- Mirror used for download: [er-data-storage/postal-code-data](https://github.com/er-data-storage/postal-code-data) (`State Wise Separated/`, Git LFS)

Each GeoJSON feature is a polygon with a `pincode` property. A point-in-polygon
test tells you which pincode zone a coordinate falls in — no API calls, no rate
limits, fully offline.

Used by `Pincode_Filling.ipynb` in the repo root.
