import sys, os, zipfile
import numpy as np
import rasterio, geopandas as gpd
from rasterio.warp import reproject, Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

zips = [a for a in sys.argv[1:] if a.lower().endswith(".zip")]
OUT = "out_test"; os.makedirs(OUT, exist_ok=True)
CRS, RES = "EPSG:32645", 30.0
BANDS = ["BAND2", "BAND3", "BAND4", "BAND5"]  # G, R, NIR, SWIR

# --- target grid: Murshidabad polygon bounds, 30 m, snapped ---
poly = gpd.read_file(r"boundaries\murshidabad.geojson").to_crs(CRS)
x0, y0, x1, y1 = poly.total_bounds
x0, y1 = np.floor(x0 / RES) * RES, np.ceil(y1 / RES) * RES
W, H = int(np.ceil((x1 - x0) / RES)), int(np.ceil((y1 - y1 + (y1 - poly.total_bounds[1])) / RES))
tr = from_origin(x0, y1, RES, RES)
pmask = rasterize([(g, 1) for g in poly.geometry], out_shape=(H, W), transform=tr, dtype="uint8").astype(bool)
print(f"grid {W} x {H} @ {RES:.0f} m | polygon pixels: {pmask.sum():,}")

def read_band(zpath, band):
    inner = [n for n in zipfile.ZipFile(zpath).namelist() if n.endswith(f"/{band}.tif")][0]
    src = "/vsizip/" + os.path.abspath(zpath).replace("\\", "/") + "/" + inner
    with rasterio.open(src) as ds:
        dn = ds.read(1)
        dst = np.zeros((H, W), np.float32)
        reproject(dn, dst, src_transform=ds.transform, src_crs=ds.crs, src_nodata=0,
                  dst_transform=tr, dst_crs=CRS, dst_nodata=0, resampling=Resampling.bilinear)
    return dst

for z in zips:   # BAND_META.txt dekhna hai (scale confirm karne ke liye)
    meta = [n for n in zipfile.ZipFile(z).namelist() if n.endswith("BAND_META.txt")][0]
    print(f"\n--- {os.path.basename(z)} / BAND_META.txt ---")
    print(zipfile.ZipFile(z).read(meta).decode(errors="ignore")[:1500])

stack = np.zeros((4, H, W), np.float32); cnt = np.zeros((4, H, W), np.float32)
sat = np.zeros((4, H, W), bool)
for z in zips:
    for i, b in enumerate(BANDS):
        dn = read_band(z, b)
        ok = dn > 0                                  # DN==0 -> invalid
        sat[i] |= dn >= 9999.5                       # DN==10000 -> saturated (flag only)
        stack[i] += np.where(ok, dn * 0.0001, 0)
        cnt[i] += ok
        print(f"  {os.path.basename(z)[:30]} {b}: valid {ok[pmask].mean()*100:.1f}% of polygon")

refl = np.where(cnt > 0, stack / np.maximum(cnt, 1), np.nan).astype(np.float32)
refl[:, ~pmask] = np.nan
g, r, nir, swir = refl
ndvi = (nir - r) / (nir + r)

valid = np.isfinite(ndvi) & pmask
print(f"\nmosaic valid: {valid.sum()/pmask.sum()*100:.1f}% of polygon")
print(f"saturated px (NIR): {(sat[2] & pmask).sum():,}")
print("reflectance percentiles (1/50/99):")
for n, a in zip(["G", "R", "NIR", "SWIR"], refl):
    v = a[np.isfinite(a)]
    print(f"  {n}: {np.percentile(v,1):.3f} / {np.percentile(v,50):.3f} / {np.percentile(v,99):.3f}")
print(f"NDVI percentiles (1/50/99): {np.nanpercentile(ndvi,[1,50,99]).round(3)}")

with rasterio.open(os.path.join(OUT, "mosaic_refl.tif"), "w", driver="GTiff", height=H, width=W,
                   count=5, dtype="float32", crs=CRS, transform=tr, nodata=np.nan) as o:
    o.write(np.concatenate([refl, ndvi[None]]).astype(np.float32))

def stretch(a):
    lo, hi = np.nanpercentile(a, [2, 98]); return np.clip((a - lo) / (hi - lo), 0, 1)
fc = np.dstack([stretch(nir), stretch(r), stretch(g)]); fc[~valid] = 1
fig, ax = plt.subplots(1, 2, figsize=(13, 7))
ax[0].imshow(fc); ax[0].set_title("False colour (NIR-R-G)")
im = ax[1].imshow(np.where(valid, ndvi, np.nan), cmap="RdYlGn", vmin=-0.2, vmax=0.9)
ax[1].set_title("NDVI"); plt.colorbar(im, ax=ax[1], shrink=0.7)
for a in ax: a.axis("off")
plt.savefig(os.path.join(OUT, "preview.png"), dpi=130, bbox_inches="tight")
print(f"\nsaved {OUT}\\mosaic_refl.tif and {OUT}\\preview.png")