
from pystac_client import Client
from urllib.parse import urlparse

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

for collection in collections:
    print("\n" + "=" * 60)
    print("COLLECTION:", collection)

    try:
        search = client.search(
            collections=[collection],
            bbox=bbox,
            datetime=date_range,
            max_items=1,
        )

        items = list(search.items())

        if not items:
            print("No items found.")
            continue

        item = items[0]
        print("Scene ID:", item.id)
        print("Acquired:", item.datetime)
        print("Scene bbox:", item.bbox)
        print("Assets:")

        if not item.assets:
            print("  No assets listed.")
            continue

        for name, asset in item.assets.items():
            href = asset.href or ""
            host = urlparse(href).netloc if href else "(no URL)"

            print(f"  Name: {name}")
            print(f"    Type: {asset.media_type}")
            print(f"    Roles: {asset.roles}")
            print(f"    Host: {host}")

    except Exception as exc:
        print("Inspection error:", type(exc).__name__, str(exc)[:250])

print("Selected properties:")

for key, value in item.properties.items():
    if any(word in key.lower() for word in [
        "online", "download", "order", "product",
        "processing", "cloud", "platform", "instrument"
    ]):
        print(f"  {key}: {value}")