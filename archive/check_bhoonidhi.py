
import csv
import getpass
import time
from collections import Counter

import requests

# --------------------------------------------------
# MURSHIDABAD: INITIAL CATALOGUE AVAILABILITY CHECK
# --------------------------------------------------

API = "https://bhoonidhi-api.nrsc.gov.in"

# Approximate bounding box: west, south, east, north
# Includes some area outside the exact district boundary.
BBOX = [87.821, 23.725, 88.767, 24.839]

# Example two-month period. Change these to the
# exact dates approved for your project.
START_DATE = "2025-06-01"
END_DATE = "2025-07-31"

COLLECTIONS = [
    "ResourceSat-2_LISS3_L2",
    "ResourceSat-2_LISS3_BOA",
    "ResourceSat-2A_LISS3_L2",
    "ResourceSat-2A_LISS3_BOA",
    "ResourceSat-2_AWIFS_L2",
    "ResourceSat-2_AWIFS_BOA",
    "ResourceSat-2A_AWIFS_L2",
    "ResourceSat-2A_AWIFS_BOA",
    "EOS-04_SAR-MRS_L2A",
    "EOS-04_SAR-MRS_L2B",
    "EOS-04_SAR-CRS_L2A",
    "EOS-04_SAR-CRS_L2B",
]

def main():
    print("Bhoonidhi catalogue availability checker")
    print(f"AOI bbox: {BBOX}")
    print(f"Dates: {START_DATE} to {END_DATE}")
    print("This script searches metadata only; it does not download imagery.\n")

    # Ask locally; credentials are not saved in this script.
    user_id = input("Bhoonidhi user ID: ").strip()
    password = getpass.getpass("Bhoonidhi password: ")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    # 1. Authenticate
    auth_url = f"{API}/auth/token"
    auth_payload = {
        "userId": user_id,
        "password": password,
        "grant_type": "password",
    }

    print("\nAuthenticating...")
    auth_response = session.post(
        auth_url, json=auth_payload, timeout=45
    )

    if not auth_response.ok:
        print("Authentication failed.")
        print("HTTP status:", auth_response.status_code)
        print("Server response:", auth_response.text[:500])
        return

    auth_data = auth_response.json()
    token = auth_data.get("access_token")

    if not token:
        print("No access_token found in authentication response.")
        print("Response keys:", list(auth_data.keys()))
        return

    session.headers.update({
        "Authorization": f"Bearer {token}"
    })
    print("Authentication successful.")

    # 2. Search each collection
    search_url = f"{API}/data/search"
    all_rows = []

    for collection in COLLECTIONS:
        payload = {
            "collections": [collection],
            "bbox": BBOX,
            "datetime": (
                f"{START_DATE}T00:00:00Z/"
                f"{END_DATE}T23:59:59Z"
            ),
            "limit": 500,
        }

        print(f"Searching: {collection}")

        try:
            response = session.post(
                search_url, json=payload, timeout=60
            )

            if not response.ok:
                print(
                    f"  Search failed: HTTP {response.status_code}"
                )
                print(" ", response.text[:250])
                time.sleep(0.5)
                continue

            result = response.json()
            features = result.get("features", [])
            print(f"  Returned: {len(features)} scene(s)")

            for feature in features:
                props = feature.get("properties") or {}

                all_rows.append({
                    "collection": feature.get("collection", collection),
                    "scene_id": feature.get("id", ""),
                    "acquisition_datetime": props.get("datetime", ""),
                    "online": props.get("Online", ""),
                    "cloud_cover": props.get(
                        "eo:cloud_cover",
                        props.get("cloud_cover", "")
                    ),
                    "bbox": str(feature.get("bbox", "")),
                })

        except requests.RequestException as exc:
            print(f"  Network/request error: {exc}")

        except ValueError:
            print("  Could not parse the server response as JSON.")

        # Stay comfortably below the documented search rate limit.
        time.sleep(0.5)

    # 3. Save the inventory
    output_file = "bhoonidhi_murshidabad_inventory.csv"
    columns = [
        "collection",
        "scene_id",
        "acquisition_datetime",
        "online",
        "cloud_cover",
        "bbox",
    ]

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(all_rows)

    print("\n========== SUMMARY ==========")
    counts = Counter(row["collection"] for row in all_rows)

    for collection in COLLECTIONS:
        print(f"{collection}: {counts.get(collection, 0)} scene(s)")

    print(f"\nTotal returned scenes: {len(all_rows)}")
    print(f"Inventory saved to: {output_file}")
    print("No imagery was downloaded.")

    session.close()


if __name__ == "__main__":
    main()
