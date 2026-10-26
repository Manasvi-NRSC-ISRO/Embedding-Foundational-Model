
from pathlib import Path

import numpy as np
import rasterio
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA

# Input: Bardhaman GeoTIFF
folder = Path("data/west_bengal/bardhaman")
files = list(folder.glob("*.tif"))

if len(files) != 1:
    raise RuntimeError(
        f"Expected exactly one GeoTIFF in {folder}, "
        f"but found {len(files)}. Check the download first."
    )

raster_path = files[0]

# Output: PCA visualization
output_path = folder / "bardhaman_tessera_pca.png"

with rasterio.open(raster_path) as src:
    data = src.read().astype(np.float32)

print("Input raster:", raster_path)
print("Original shape:", data.shape)

# Raster format: (bands, height, width)
# Machine learning format: (pixels, features)
X = data.transpose(1, 2, 0).reshape(-1, data.shape[0])

# Remove pixels containing NaN or infinite values
valid = np.isfinite(X).all(axis=1)
X_valid = X[valid]

print("Valid pixels:", len(X_valid))

if len(X_valid) < 3:
    raise ValueError("Not enough valid pixels for PCA.")

# Reduce 128 embedding features to 3 components
pca = PCA(n_components=3)
reduced = pca.fit_transform(X_valid)

print("Explained variance:", pca.explained_variance_ratio_)
print(
    "Total variance explained:",
    pca.explained_variance_ratio_.sum()
)

# Restore the spatial arrangement of the pixels
height, width = data.shape[1:]
rgb = np.full((height * width, 3), np.nan, dtype=np.float32)
rgb[valid] = reduced
rgb = rgb.reshape(height, width, 3)

# Scale each component for display
for i in range(3):
    band = rgb[:, :, i]
    finite = np.isfinite(band)

    if not finite.any():
        continue

    lo, hi = np.nanpercentile(band, [2, 98])

    if hi > lo:
        band[finite] = np.clip(
            (band[finite] - lo) / (hi - lo), 0, 1
        )

# Save PCA image
plt.figure(figsize=(10, 8))
plt.imshow(rgb)
plt.title("TESSERA PCA — Bardhaman, West Bengal (2024)")
plt.axis("off")
plt.tight_layout()
plt.savefig(output_path, dpi=180, bbox_inches="tight")
plt.close()

print("PCA image saved:", output_path)
