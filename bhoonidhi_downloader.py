
import argparse
import csv
import getpass
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from email.message import Message

import requests

# Official Bhoonidhi API
API = "https://bhoonidhi-api.nrsc.gov.in"
AUTH_URL = f"{API}/auth/token"
SEARCH_URL = f"{API}/data/search"
DOWNLOAD_URL = f"{API}/download"

# Approximate Murshidabad bounding box: west, south, east, north.
BBOX = [87.821, 23.725, 88.767, 24.839]

# Initial pilot period; edit these dates if needed.
DATETIME = "2025-06-01T00:00:00Z/2025-07-31T23:59:59Z"

COLLECTIONS = [
    "ResourceSat-2_AWIFS_L2",
    "ResourceSat-2_AWIFS_BOA",
    "ResourceSat-2_LISS3_L2",
    "ResourceSat-2_LISS3_BOA",
    "ResourceSat-2A_AWIFS_L2",
    "ResourceSat-2A_AWIFS_BOA",
    "ResourceSat-2A_LISS3_L2",
    "ResourceSat-2A_LISS3_BOA",
    "EOS-04_SAR-MRS_L2A",
    "EOS-04_SAR-MRS_L2B",
    "EOS-04_SAR-MRS_SM",
    "EOS-04_SAR-FRS1_L2A",
    "EOS-04_SAR-FRS2_L2A",
]

OUT = Path("data") / "bhoonidhi" / "murshidabad"
TIMEOUT = (20, 120)


def safe_name(value):
    """Make a filename safe for Windows."""
    value = str(value or "unknown_scene")
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")


def get_filename(response, scene_id):
    """Use server filename if supplied; otherwise use the scene ID."""
    disposition = response.headers.get("Content-Disposition", "")
    message = Message()
    message["content-disposition"] = disposition
    name = message.get_filename()

    if name:
        return safe_name(name)

    content_type = response.headers.get("Content-Type", "").lower()
    extension = ".zip" if "zip" in content_type else ".bin"
    return safe_name(scene_id) + extension


def login(session, username, password):
    print("\n[1/3] Testing Bhoonidhi API login...")
    try:
        response = session.post(
            AUTH_URL,
            json={
                "userId": username,
                "password": password,
                "grant_type": "password",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"Could not reach the authentication service: {exc}")
        return None

    if response.status_code != 200:
        print(f"Login failed: HTTP {response.status_code}")
        try:
            # Only print the server's error response, never the password.
            print(response.json().get("Description", response.text[:300]))
        except (ValueError, AttributeError):
            print(response.text[:300])
        print("\nNo search or download was started.")
        print("Check the exact account ID/password and whether this account")
        print("is enabled for API access. Do not share the password here.")
        return None

    try:
        payload = response.json()
    except ValueError:
        print("Login response was not valid JSON.")
        return None

    token = payload.get("access_token")
    if not token:
        print("Login response did not contain an access_token.")
        print("Check the API response format with Bhoonidhi support.")
        return None

    session.headers.update({"Authorization": f"Bearer {token}"})
    print("Login successful. Token kept in memory only.")
    return token


def search_items(session):
    print("\n[2/3] Searching the selected collections...")
    body = {
        "collections": COLLECTIONS,
        "bbox": BBOX,
        "datetime": DATETIME,
        "limit": 500,
        "filter": {
            "op": "eq",
            "args": [{"property": "Online"}, "Y"],
        },
        "filter-lang": "cql2-json",
    }

    items = []
    url = SEARCH_URL
    first_request = True
    page_number = 0

    while url:
        page_number += 1
        try:
            if first_request:
                response = session.post(url, json=body, timeout=TIMEOUT)
                first_request = False
            else:
                # Only follow pagination links on the official API host.
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.netloc != "bhoonidhi-api.nrsc.gov.in":
                    print("Stopped: pagination link was not on the official API host.")
                    break
                response = session.get(url, timeout=TIMEOUT)

            if response.status_code != 200:
                print(f"Search failed: HTTP {response.status_code}")
                print(response.text[:500])
                break

            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"Search request failed: {exc}")
            break

        page_items = data.get("features", [])
        items.extend(page_items)
        print(f"  Page {page_number}: {len(page_items)} records")

        next_links = [
            link.get("href")
            for link in data.get("links", [])
            if link.get("rel") == "next" and link.get("href")
        ]
        url = urljoin(url, next_links[0]) if next_links else None

        # Keep the service request rate low.
        if url:
            time.sleep(0.4)

    # De-duplicate records by collection + item ID.
    unique = {}
    for item in items:
        key = (item.get("collection", ""), item.get("id", ""))
        unique[key] = item

    results = list(unique.values())
    print(f"Total unique catalogue records returned: {len(results)}")
    return results


def save_inventory(items):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "inventory.csv"

    fields = [
        "id", "collection", "datetime", "online",
        "product_type", "cloud_cover", "bbox",
    ]

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        for item in items:
            props = item.get("properties") or {}
            writer.writerow({
                "id": item.get("id", ""),
                "collection": item.get("collection", ""),
                "datetime": props.get("datetime", ""),
                "online": props.get("Online", props.get("online", "")),
                "product_type": props.get("ProductType", props.get("productType", "")),
                "cloud_cover": props.get("eo:cloud_cover", ""),
                "bbox": json.dumps(item.get("bbox", [])),
            })

    print(f"Inventory saved: {path.resolve()}")
    return path


def download_items(session, items):
    download_dir = OUT / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "download_log.csv"

    with log_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file, fieldnames=["id", "collection", "status", "file", "message"]
        )
        writer.writeheader()

        for index, item in enumerate(items, start=1):
            scene_id = item.get("id")
            collection = item.get("collection")
            props = item.get("properties") or {}
            online = props.get("Online", props.get("online"))

            if not scene_id or not collection:
                writer.writerow({
                    "id": scene_id or "",
                    "collection": collection or "",
                    "status": "SKIPPED",
                    "file": "",
                    "message": "Missing scene ID or collection",
                })
                continue

            # Search is filtered to Online=Y. Also check the returned metadata
            # where that field is present.
            if online is not None and str(online).upper() != "Y":
                writer.writerow({
                    "id": scene_id,
                    "collection": collection,
                    "status": "SKIPPED",
                    "file": "",
                    "message": f"Online={online}; not downloaded",
                })
                continue

            params = {"id": scene_id, "collection": collection}
            print(f"[{index}/{len(items)}] Downloading {scene_id}")

            success = False
            message = ""

            for attempt in range(1, 4):
                temp_path = None
                try:
                    with session.get(
                        DOWNLOAD_URL,
                        params=params,
                        stream=True,
                        timeout=TIMEOUT,
                    ) as response:
                        if response.status_code != 200:
                            message = f"HTTP {response.status_code}"
                            try:
                                message += ": " + response.text[:250]
                            except Exception:
                                pass
                            if response.status_code not in (502, 503, 504):
                                break
                            time.sleep(attempt * 3)
                            continue

                        content_type = response.headers.get(
                            "Content-Type", ""
                        ).lower()

                        if "application/json" in content_type:
                            message = "API returned JSON instead of a data file: "
                            message += response.text[:250]
                            break

                        filename = get_filename(response, scene_id)
                        final_path = download_dir / filename

                        # Avoid overwriting an existing file.
                        if final_path.exists():
                            final_path = download_dir / (
                                final_path.stem + "_" + str(index) + final_path.suffix
                            )

                        temp_path = final_path.with_suffix(final_path.suffix + ".part")
                        with temp_path.open("wb") as output:
                            for chunk in response.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    output.write(chunk)

                        if not temp_path.exists() or temp_path.stat().st_size == 0:
                            message = "Empty response file"
                            if temp_path.exists():
                                temp_path.unlink()
                            break

                        temp_path.replace(final_path)
                        print(f"  Saved: {final_path.name} ({final_path.stat().st_size:,} bytes)")
                        writer.writerow({
                            "id": scene_id,
                            "collection": collection,
                            "status": "DOWNLOADED",
                            "file": str(final_path),
                            "message": "",
                        })
                        file.flush()
                        success = True
                        break

                except requests.RequestException as exc:
                    message = str(exc)
                    time.sleep(attempt * 3)
                except OSError as exc:
                    message = str(exc)
                    break
                finally:
                    if temp_path and temp_path.exists():
                        try:
                            temp_path.unlink()
                        except OSError:
                            pass

            if not success:
                print(f"  FAILED: {message}")
                writer.writerow({
                    "id": scene_id,
                    "collection": collection,
                    "status": "FAILED",
                    "file": "",
                    "message": message[:500],
                })
                file.flush()

            # Sequential downloads; no parallel download flood.
            time.sleep(0.5)

    print(f"\nDownload log saved: {log_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="Search and optionally download Murshidabad data via Bhoonidhi API."
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Actually download Online=Y products. Without this flag, only inventory is saved.",
    )
    args = parser.parse_args()

    print("Bhoonidhi official API — Murshidabad pilot")
    print("Password input is hidden. No password/token is written to files.")
    username = input("Bhoonidhi user ID: ").strip()
    if not username:
        print("User ID cannot be blank.")
        sys.exit(1)

    password = getpass.getpass("Bhoonidhi password (input will be invisible): ")
    if not password:
        print("Password cannot be blank.")
        sys.exit(1)

    session = requests.Session()
    token = login(session, username, password)

    # Drop the local password reference as soon as login is complete.
    password = None

    if not token:
        sys.exit(1)

    items = search_items(session)
    save_inventory(items)

    if not items:
        print("\nNo records returned. Check the date range, bbox, collections,")
        print("and account permissions before changing anything else.")
        return

    print("\nInventory-only mode: no satellite files have been downloaded.")
    if not args.download:
        print("Review inventory.csv first.")
        print("When ready, run: python bhoonidhi_downloader.py --download")
        return

    online_items = []
    for item in items:
        props = item.get("properties") or {}
        online = props.get("Online", props.get("online"))
        # Server-side search filter is Online=Y. If field is missing, retain
        # the result because some STAC responses may omit the filter property.
        if online is None or str(online).upper() == "Y":
            online_items.append(item)

    print(f"\nReady to download up to {len(online_items)} records.")
    print("Downloads may be large and may use your account's daily quota.")
    confirm = input("Type DOWNLOAD to continue: ").strip()
    if confirm != "DOWNLOAD":
        print("Cancelled. Inventory is saved; no downloads started.")
        return

    download_items(session, online_items)
    session.close()


if __name__ == "__main__":
    main()
