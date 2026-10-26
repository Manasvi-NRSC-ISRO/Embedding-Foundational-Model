import sys, os, re, glob, zipfile, time, csv
from datetime import datetime
from collections import defaultdict
import numpy as np
import rasterio, geopandas as gpd
from rasterio.warp import reproject, Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin

PATTERN = sys.argv[1] if len(sys.argv) > 1 else r"bhoonidhi_year\ResourceSat-2*_LISS3_BOA\*.zip"
OUT = "stack_liss3"
os.makedirs(OUT, exist_ok=True)
CRS, RES = "EPSG:32645", 30.0
BANDS = ["BAND2", "BAND3", "BAND4", "BAND5"]   # G, R, NIR, SWIR

poly = gpd.read_file(r"boundaries\murshidabad.geojson").to_crs(CRS)
minx, miny, maxx, maxy = poly.total_bounds
x0 = np.floor(minx / RES) * RES
y1 = np.ceil(maxy / RES) * RES
W = int(np.ceil((maxx - x0) / RES))
H = int(np.ceil((y1 - miny) / RES))
tr = from_origin(x0, y1, RES, RES)
pmask = rasterize([(g, 1) for g in poly.geometry], out_shape=(H, W), transform=tr,
                  dtype="uint8").astype(bool)
print(f"grid {W} x {H} @ {RES:.0f} m | polygon pixels: {pmask.sum():,}")

with rasterio.open(os.path.join(OUT, "aoi_mask.tif"), "w", driver="GTiff", height=H, width=W,
                   count=1, dtype="uint8", crs=CRS, transform=tr, compress="deflate") as o:
    o.write(pmask.astype("uint8"), 1)

groups = defaultdict(list)
for z in sorted(glob.glob(PATTERN)):
    m = re.search(r"\d{2}[A-Z]{3}20\d{2}", os.path.basename(z))
    if m:
        groups[datetime.strptime(m.group(0), "%d%b%Y").date()].append(z)
print(f"{len(groups)} dates, {sum(len(v) for v in groups.values())} scenes\n")

def warp_band(zpath, band):
    inner = [n for n in zipfile.ZipFile(zpath).namelist() if n.endswith(f"/{band}.tif")][0]
    src = "/vsizip/" + os.path.abspath(zpath).replace("\\", "/") + "/" + inner
    dst = np.zeros((H, W), np.float32)
    with rasterio.open(src) as ds:
        dn = ds.read(1)
        reproject(dn, dst, src_transform=ds.transform, src_crs=ds.crs, src_nodata=0,
                  dst_transform=tr, dst_crs=CRS, dst_nodata=0, resampling=Resampling.bilinear)
    return dst

log_path = os.path.join(OUT, "log.csv")
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        csv.writer(f).writerow(["date", "n_scenes", "valid_pct", "saved", "seconds", "note"])

for k, (d, zips) in enumerate(sorted(groups.items()), 1):
    path = os.path.join(OUT, f"liss3_{d}.tif")
    if os.path.exists(path):
        print(f"[{k}/{len(groups)}] {d}: already done")
        continue
    t0 = time.time()
    try:
        acc = np.zeros((4, H, W), np.float32)
        cnt = np.zeros((4, H, W), np.float32)
        for z in zips:
            for i, b in enumerate(BANDS):
                dn = warp_band(z, b)
                ok = dn > 0                       # DN==0 -> nodata
                acc[i] += np.where(ok, dn, 0)
                cnt[i] += ok
        mos = np.where(cnt > 0, acc / np.maximum(cnt, 1), 0)
        mos[:, ~pmask] = 0
        mos = np.clip(np.rint(mos), 0, 10000).astype(np.uint16)
        valid_pct = float(((mos[2] > 0) & pmask).sum() / pmask.sum() * 100)
        saved = valid_pct >= 1
        if saved:
            with rasterio.open(path, "w", driver="GTiff", height=H, width=W, count=4,
                               dtype="uint16", crs=CRS, transform=tr, nodata=0,
                               compress="deflate", tiled=True, blockxsize=256, blockysize=256) as o:
                o.write(mos)
                o.update_tags(date=str(d), n_scenes=len(zips),
                              scenes=",".join(os.path.basename(z)[:-4] for z in zips))
        note = "" if saved else "valid<1%, not saved"
    except Exception as e:
        valid_pct, saved, note = float("nan"), False, f"ERROR {str(e)[:100]}"
    sec = time.time() - t0
    print(f"[{k}/{len(groups)}] {d} | {len(zips)} scenes | valid {valid_pct:.1f}% | {sec:.0f}s {note}")
    with open(log_path, "a", newline="") as f:
        csv.writer(f).writerow([d, len(zips), round(valid_pct, 1), saved, round(sec), note])

print("\ndone. log:", log_path)