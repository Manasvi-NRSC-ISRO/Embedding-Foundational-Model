from geotessera import GeoTesseraZarr

# Existing TESSERA embeddings dataset se connect karo
gt = GeoTesseraZarr()

# Bardhaman, West Bengal: longitude, latitude
points = [(87.85, 23.25)]

# 2024 ke embeddings retrieve karo
embeddings = gt.sample_points(points, year=2024)

print("Study area: Bardhaman, West Bengal")
print("Embedding shape:", embeddings.shape)
print("Embedding values:", embeddings)

