
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
    print(f"\n{'=' * 65}")
    print("COLLECTION:", collection)

    search = client.search(
        collections=[collection],
        bbox=bbox,
        datetime=date_range
    )

    samples_found = 0

    for item in search.items():
        props = item.properties or {}
        downloadable = props.get("bhoonidhi:downloadable", False)

        if str(downloadable).lower() != "true":
            continue

        print("\nScene ID:", item.id)
        print("Date:", item.datetime)
        print("Product type:", props.get("bhoonidhi:product_type"))
        print("Assets:")

        if not item.assets:
            print("  No assets listed")
        else:
            for key, asset in item.assets.items():
                href = asset.href or ""
                parsed = urlparse(href)

                print(f"  - Name: {key}")
                print(f"    Type: {asset.media_type}")
                print(f"    Roles: {asset.roles}")
                print(f"    Host: {parsed.netloc or '(none)'}")
                print(f"    File: {parsed.path.split('/')[-1] or '(none)'}")

        samples_found += 1

        if samples_found >= 2:
            break

    if samples_found == 0:
        print("No downloadable=True samples found.")
