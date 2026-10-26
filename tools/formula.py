import rasterio, numpy as np
z = r"D:\Embedding-Foundational-Model\bhoonidhi_year\ResourceSat-2_AWIFS_BOA\R2W01JAN2025071113010900053PSANSTLCSRHTDC.zip".replace("\\", "/")
n = "R2W01JAN2025071113010900053PSANSTLCSRHTDC/BAND4.tif"
with rasterio.open(f"/vsizip/{z}/{n}") as ds:
    a = ds.read(1, out_shape=(ds.height // 16, ds.width // 16))
v = a[a > 0]
print("min", a.min(), "max", a.max(), "zero frac", (a == 0).mean(), ">10000 frac", (a > 10000).mean())
print("percentiles 1/50/99 of nonzero:", np.percentile(v, [1, 50, 99]) if v.size else "no nonzero")