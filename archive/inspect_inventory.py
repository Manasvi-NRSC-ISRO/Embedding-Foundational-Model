
import csv
from collections import Counter

FILE = "murshidabad_inventory.csv"

with open(FILE, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

print("Total records:", len(rows))
print("Unique scene IDs:", len({
    r["scene_id"] for r in rows if r["scene_id"]
}))

print("\nRecords by collection:")
for collection, count in Counter(
    r["collection"] for r in rows
).items():
    print(f"  {collection}: {count}")

dates = sorted(
    r["datetime"][:10]
    for r in rows if r["datetime"]
)

print("\nEarliest acquisition:", dates[0] if dates else "Unknown")
print("Latest acquisition:", dates[-1] if dates else "Unknown")

print("\nSample records:")
for row in rows[:5]:
    print(row["collection"], "|", row["scene_id"], "|", row["datetime"])
