import sys, glob, zipfile, os
import numpy as np, pandas as pd
import rasterio, geopandas as gpd
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from affine import Affine

ROOT = sys.argv[1] if len(sys.argv) > 1 else "bhoonidhi_year"
poly = gpd.read_file(r"boundaries\murshidabad.geojson").to_crs(4326).geometry.iloc[0]
rows = []

for z in sorted(glob.glob(os.path.join(ROOT, "**", "*.zip"), recursive=True)):
    name = os.path.basename(z)[:-4]
    try:
        tifs = [n for n in zipfile.ZipFile(z).namelist() if n.lower().endswith((".tif", ".tiff"))]
        pick = [n for n in tifs if "band4" in n.lower()] or tifs
        inner = pick[0]
        path = "/vsizip/" + os.path.abspath(z).replace("\\", "/") + "/" + inner
        with rasterio.open(path) as ds:
            h, w = ds.height, ds.width
            oh, ow = max(h // 20, 1), max(w // 20, 1)
            a = ds.read(1, out_shape=(oh, ow))
            tr = ds.transform * Affine.scale(w / ow, h / oh)
            g = transform_geom("EPSG:4326", ds.crs, poly.__geo_interface__)
            pm = rasterize([(g, 1)], out_shape=(oh, ow), transform=tr, dtype="uint8").astype(bool)
        valid = a > 0
        cover = (valid & pm).sum() / max(pm.sum(), 1) * 100
        rows.append(dict(scene=name, coll=os.path.basename(os.path.dirname(z)),
                         date=name[3:12] if len(name) > 12 else "",
                         poly_cover_pct=round(cover, 1), band=inner, ok=True))
    except Exception as e:
        rows.append(dict(scene=name, coll=os.path.basename(os.path.dirname(z)),
                         poly_cover_pct=np.nan, band=str(e)[:80], ok=False))

df = pd.DataFrame(rows)
df.to_csv("coverage_check.csv", index=False)
print(df[["scene", "poly_cover_pct", "ok"]].to_string(index=False))
good = df[df.poly_cover_pct >= 1]
print(f"\n{len(df)} zips | {len(good)} polygon ko >=1% cover karte hain | "
      f"{(df.poly_cover_pct < 1).sum()} useless | {(~df.ok).sum()} padhne mein error")