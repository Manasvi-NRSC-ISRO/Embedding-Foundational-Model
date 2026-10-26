import sys, glob, os, re, zipfile
from datetime import datetime
import geopandas as gpd, pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union

FULL = "--full" in sys.argv          # zip CRC test, slow (kuch minute)
aoi = gpd.read_file(r"boundaries\murshidabad.geojson").to_crs(4326).geometry.iloc[0]
KV = re.compile(r"^\s*([A-Za-z0-9_%]+)\s*=\s*(.*?)\s*$", re.M)

rows = []
for z in sorted(glob.glob(r"bhoonidhi_year\ResourceSat-2*_LISS3_BOA\*.zip")):
    name = os.path.basename(z)[:-4]
    r = dict(scene=name, ok=True, note="")
    try:
        zf = zipfile.ZipFile(z)
        names = zf.namelist()
        miss = [b for b in ("BAND2", "BAND3", "BAND4", "BAND5")
                if not any(n.endswith(f"/{b}.tif") for n in names)]
        if miss:
            r.update(ok=False, note=f"missing {miss}")
        if FULL:
            bad = zf.testzip()
            if bad:
                r.update(ok=False, note=f"CRC bad: {bad}")
        meta = [n for n in names if n.endswith("BAND_META.txt")][0]
        kv = dict(KV.findall(zf.read(meta).decode(errors="ignore")))
        pts = [(float(kv[f"Image{c}Lon"]), float(kv[f"Image{c}Lat"])) for c in ("UL", "UR", "LR", "LL")]
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        r["geom"] = poly
        r["date"] = datetime.strptime(re.search(r"\d{2}[A-Z]{3}20\d{2}", name).group(0), "%d%b%Y").date()
        r["scene_cover_pct"] = round(100 * poly.intersection(aoi).area / aoi.area, 1)
    except Exception as e:
        r.update(ok=False, note=str(e)[:80])
    rows.append(r)

bad = [r for r in rows if not r["ok"]]
print(f"{len(rows)} zips | {len(bad)} problem wale")
for r in bad:
    print("  PROBLEM:", r["scene"], r["note"])

df = pd.DataFrame([r for r in rows if "geom" in r])
zero = df[df.scene_cover_pct < 1]
print(f"\nPolygon ko <1% cover karne wale scenes: {len(zero)}")
print(zero[["scene", "scene_cover_pct"]].to_string(index=False))

out = []
for d, g in df.groupby("date"):
    u = unary_union(list(g.geom))
    out.append(dict(date=d, scenes=len(g), polygon_cover_pct=round(100 * u.intersection(aoi).area / aoi.area, 1)))
per = pd.DataFrame(out).sort_values("date")
per.to_csv("per_date_coverage.csv", index=False)
print("\nPer-date polygon coverage (dono scenes milake):")
print(per.to_string(index=False))
print(f"\n{len(per)} dates | >=90% cover: {(per.polygon_cover_pct >= 90).sum()} | <50%: {(per.polygon_cover_pct < 50).sum()}")