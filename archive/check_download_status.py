
from pystac_client import Client
import csv
from collections import Counter

client = Client.open("https://bhoonidhi-stac.ecotrakr.in")

bbox = [87.821, 23.725, 88.767, 24.839]
date_range = "2025-06-01/2025-07-31"

collections = [
    "resourcesat-2-liss3",
    "resourcesat-2a-liss3",
    "resourcesat-2-awifs",
    "resourcesat-2a-awifs",
    "eos-04-sar-mrs",
    "eos-04-sar-frs1",
]

rows = []

for collection in collections:
    print(f"\nChecking {collection} ...")

    search = client.search(
        collections=[collection],
        bbox=bbox,
        datetime=date_range,
    )

    count = 0

    for item in search.items():
        props = item.properties or {}

        rows.append({
            "collection": collection,
            "scene_id": item.id,
            "datetime": (
                item.datetime.isoformat()
                if item.datetime else ""
            ),
            "downloadable": props.get("bhoonidhi:downloadable", ""),
            "downloaded": props.get("bhoonidhi:downloaded", ""),
            "product_type": props.get("bhoonidhi:product_type", ""),
            "bbox": str(item.bbox),
        })

        count += 1

    print(f"  Scanned {count} scenes")

filename = "murshidabad_download_status.csv"
fields = [
    "collection", "scene_id", "datetime",
    "downloadable", "downloaded", "product_type", "bbox"
]

with open(filename, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

print("\n========== SUMMARY ==========")
print("Total scanned:", len(rows))

for field in ["downloadable", "downloaded", "product_type"]:
    print(f"\n{field}:")
    counts = Counter(
        str(row[field]) if row[field] != "" else "(missing)"
        for row in rows
    )
    for value, number in counts.items():
        print(f"  {value}: {number}")

print(f"\nSaved report: {filename}")
