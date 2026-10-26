import sys, zipfile, rasterio

z = sys.argv[1].replace("\\", "/")
zf = zipfile.ZipFile(z)
names = zf.namelist()
print(names)

for n in names:
    if "META" in n.upper() and not n.lower().endswith((".tif", ".jpg")):
        print("-----", n)
        print(zf.read(n).decode(errors="replace")[:3000])

for n in names:
    if n.lower().endswith(".tif"):
        with rasterio.open(f"/vsizip/{z}/{n}") as ds:
            print(n, ds.crs, ds.res, ds.dtypes[0], "nodata:", ds.nodata,
                  ds.shape, ds.bounds, "scales:", ds.scales)