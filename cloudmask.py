import glob, os, warnings
import numpy as np, pandas as pd, rasterio
from rasterio.windows import Window
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

IN, OUT, BLK = "stack_liss3", "mask_liss3", 256
T_BRIGHT, VIS_MIN, MIN_OBS = 0.07, 0.15, 5      # shuruaati guess, preview dekhke tune karna
os.makedirs(OUT, exist_ok=True)

files = sorted(glob.glob(os.path.join(IN, "liss3_*.tif")))
dates = [os.path.basename(f)[6:-4] for f in files]
D = len(files)
srcs = [rasterio.open(f) for f in files]
aoi = rasterio.open(os.path.join(IN, "aoi_mask.tif"))
H, W = aoi.height, aoi.width
total_poly = int((aoi.read(1) > 0).sum())
print(f"{D} dates | grid {W} x {H} | polygon pixels {total_poly:,}")

prof = dict(driver="GTiff", height=H, width=W, count=1, dtype="uint8", crs=aoi.crs,
            transform=aoi.transform, nodata=255, compress="deflate",
            tiled=True, blockxsize=256, blockysize=256)
outs = [rasterio.open(os.path.join(OUT, f"mask_{d}.tif"), "w", **prof) for d in dates]
n_clear = np.zeros(D); n_cloud = np.zeros(D); n_nod = np.zeros(D)
clear_count = np.zeros((H, W), np.uint8)

for r0 in range(0, H, BLK):
    h = min(BLK, H - r0)
    win = Window(0, r0, W, h)
    dn = np.stack([s.read(window=win) for s in srcs])          # (D, 4, h, W)
    inpoly = aoi.read(1, window=win) > 0
    valid = (dn > 0).all(axis=1) & inpoly[None]
    sat = (dn >= 9999).any(axis=1)
    refl = dn.astype(np.float32) / 10000.0
    vis = (refl[:, 0] + refl[:, 1]) / 2                         # (green + red) / 2
    med = np.nanmedian(np.where(valid, vis, np.nan), axis=0)    # har pixel ki apni median
    nobs = valid.sum(axis=0)
    cloud = valid & (nobs >= MIN_OBS)[None] & ((vis - med[None]) > T_BRIGHT) & (vis > VIS_MIN)
    cloud |= valid & sat
    m = np.zeros(valid.shape, np.uint8)
    m[valid] = 1
    m[cloud] = 2
    m[:, ~inpoly] = 255
    n_clear += (m == 1).sum(axis=(1, 2))
    n_cloud += (m == 2).sum(axis=(1, 2))
    n_nod += (m == 0).sum(axis=(1, 2))
    clear_count[r0:r0 + h] = (m == 1).sum(axis=0)
    for i in range(D):
        outs[i].write(m[i], 1, window=win)
    print(f"  rows {r0}-{r0 + h} done")

for o in outs:
    o.close()

df = pd.DataFrame(dict(date=dates, clear_pct=100 * n_clear / total_poly,
                       cloud_pct=100 * n_cloud / total_poly,
                       nodata_pct=100 * n_nod / total_poly)).round(1)
df.to_csv(os.path.join(OUT, "mask_stats.csv"), index=False)
print(df.to_string(index=False))

inside = aoi.read(1) > 0
cc = clear_count[inside]
print(f"\nclear dates per pixel (polygon ke andar): 5%/50%/95% = {np.percentile(cc, [5, 50, 95])}")
with rasterio.open(os.path.join(OUT, "clear_count.tif"), "w", **prof) as o:
    o.write(np.where(inside, clear_count, 255).astype(np.uint8), 1)

# preview: pehli, beech ki, aakhri date -> false colour aur cloud mask (laal)
f = 8
sh = (H // f, W // f)
pick = [0, D // 2, D - 1]
fig, ax = plt.subplots(3, 2, figsize=(11, 16))
for r, i in enumerate(pick):
    fc = srcs[i].read([3, 2, 1], out_shape=(3, *sh)).astype(np.float32) / 10000.0
    fc = np.clip(np.moveaxis(fc, 0, -1) / 0.5, 0, 1)
    with rasterio.open(os.path.join(OUT, f"mask_{dates[i]}.tif")) as ms:
        mk = ms.read(1, out_shape=sh)
    ov = fc.copy()
    ov[mk == 2] = [1, 0, 0]
    ax[r, 0].imshow(fc)
    ax[r, 0].set_title(f"{dates[i]} false colour")
    ax[r, 1].imshow(ov)
    ax[r, 1].set_title("cloud/haze = laal")
    ax[r, 0].axis("off")
    ax[r, 1].axis("off")
plt.savefig("mask_preview.png", dpi=110, bbox_inches="tight")
print("saved mask_preview.png")