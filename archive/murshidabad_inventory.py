from pystac_client import Client
import csv

client = Client.open("https://bhoonidhi-stac.ecotrakr.in")

# Murshidabad approximate bbox
bbox = [87.821, 23.725, 88.767, 24.839]

# Example 2-month window
date_range = "2025-06-01/2025-07-31"

keywords = ["LISS3", "AWIFS", "EOS-04", "RISAT"]

collections = []
for col in client.get_collections():
    cid = col.id.upper()
    if any(k in cid for k in keywords):
        collections.append(col.id)

print(f"Found {len(collections)} matching collections\n")

rows = []

for cid in collections:
    print("Searching:", cid)

    search = client.search(
        collections=[cid],
        bbox=bbox,
        datetime=date_range
    )

    items = list(search.items())

    print("  Scenes:", len(items))

    for item in items:
        rows.append({
            "collection": cid,
            "scene_id": item.id,
            "datetime": item.datetime.isoformat() if item.datetime else "",
            "bbox": str(item.bbox)
        })

with open("murshidabad_inventory.csv","w",newline="",encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f,fieldnames=["collection","scene_id","datetime","bbox"])
    writer.writeheader()
    writer.writerows(rows)

print("\nTotal scenes:",len(rows))
print("Saved -> murshidabad_inventory.csv")