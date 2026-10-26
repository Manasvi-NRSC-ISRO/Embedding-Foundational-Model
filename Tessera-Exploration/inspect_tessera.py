
from pathlib import Path
import rasterio

# West Bengal ke Bardhaman output folder mein GeoTIFF dhoondo
folder = Path("data/west_bengal/bardhaman")
files = list(folder.glob("*.tif"))

if len(files) == 0:
    raise FileNotFoundError(
        f"No GeoTIFF found in {folder}. "
        "Please complete Bardhaman actual download."
    )

if len(files) > 1:
    raise RuntimeError(
        f"Multiple GeoTIFF files found: {files}. "
        "Please Select One File."
    )

path = files[0]
print("Raster file:", path)

with rasterio.open(path) as src:
    print("Width:", src.width)
    print("Height:", src.height)
    print("Bands:", src.count)
    print("CRS:", src.crs)
    print("Bounds:", src.bounds)
    print("Data type:", src.dtypes[0])
    print("NoData value:", src.nodata)
