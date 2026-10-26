import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import box

d = gpd.read_file(r"boundaries\WEST BENGAL_DISTRICTS.geojson")
m = d[d["dtname"].str.lower().str.contains("murshid")]
print("matched:", m["dtname"].tolist())
assert len(m) == 1, "ek hi district match hona chahiye, dtname list dekho"

m.to_file(r"boundaries\murshidabad.geojson", driver="GeoJSON")

minx, miny, maxx, maxy = m.total_bounds
print(f"tight bbox: lon {minx:.3f}-{maxx:.3f}, lat {miny:.3f}-{maxy:.3f}")

# area ke liye metric CRS (UTM 45N)
area_km2 = m.to_crs(32645).geometry.area.iloc[0] / 1e6
old = box(87.8, 23.7, 88.8, 24.9)
old_km2 = gpd.GeoSeries([old], crs=4326).to_crs(32645).area.iloc[0] / 1e6
print(f"Murshidabad polygon: {area_km2:,.0f} km2 | purana bbox: {old_km2:,.0f} km2")
print(f"purane bbox ka {100*area_km2/old_km2:.0f}% hi Murshidabad hai")
print(f"30 m pixels in district: ~{area_km2*1e6/900/1e6:.1f} million")

fig, ax = plt.subplots(figsize=(6, 7))
d.plot(ax=ax, color="#eeeeee", edgecolor="#bbbbbb", linewidth=0.5)
m.plot(ax=ax, color="#4c9be8", edgecolor="k")
gpd.GeoSeries([old], crs=4326).boundary.plot(ax=ax, color="red", linestyle="--")
ax.set_xlim(87.0, 89.6); ax.set_ylim(23.0, 25.5)
ax.set_title("Murshidabad (blue) vs old bbox (red)")
plt.savefig("aoi_map.png", dpi=150, bbox_inches="tight")
print("saved aoi_map.png")