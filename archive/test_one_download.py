
import csv
import getpass
import re
from pathlib import Path

import requests

API = "https://bhoonidhi-api.nrsc.gov.in"
INVENTORY = Path("data/bhoonidhi/murshidabad/inventory.csv")
OUT_DIR = Path("data/bhoonidhi/murshidabad/test_download")
COLLECTION = "ResourceSat-2_LISS3_BOA"


def safe_name(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value))


# Select exactly one LISS-III BOA record from the inventory.
with INVENTORY.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

candidates = [
    row for row in rows
    if row.get("collection") == COLLECTION
    and row.get("online", "").strip().upper() == "Y"
]

if not candidates:
    raise SystemExit(f"No Online=Y records found for {COLLECTION}")

scene = candidates[0]
scene_id = scene["id"]

print("One-scene download test")
print("Collection:", COLLECTION)
print("Scene ID:", scene_id)
print("Acquisition time:", scene.get("datetime", "unknown"))
print("Only this one scene will be requested.")

username = input("Bhoonidhi user ID: ").strip()
password = getpass.getpass("Bhoonidhi password (hidden): ")

with requests.Session() as session:
    # Authenticate; never print or save the token.
    auth = session.post(
        f"{API}/auth/token",
        json={
            "userId": username,
            "password": password,
            "grant_type": "password",
        },
        timeout=(20, 60),
    )

    password = None

    if auth.status_code != 200:
        print("Login failed:", auth.status_code)
        try:
            print(auth.json().get("Description", "Authentication error"))
        except ValueError:
            print(auth.text[:250])
        raise SystemExit("Stopped; no download attempted.")

    token = auth.json().get("access_token")
    if not token:
        raise SystemExit("Login response had no access token.")

    session.headers.update({"Authorization": f"Bearer {token}"})
    print("Login successful.")

    try:
        with session.get(
            f"{API}/download",
            params={"id": scene_id, "collection": COLLECTION},
            stream=True,
            timeout=(20, 120),
        ) as response:

            print("Download endpoint HTTP status:", response.status_code)
            content_type = response.headers.get("Content-Type", "")
            print("Response content type:", content_type)

            if response.status_code != 200:
                print("Download request failed:", response.text[:400])
                raise SystemExit("No raster file saved.")

            if "json" in content_type.lower() or "text/html" in content_type.lower():
                print("Server returned a message, not a raster file:")
                print(response.text[:400])
                raise SystemExit("No raster file saved.")

            OUT_DIR.mkdir(parents=True, exist_ok=True)
            filename = safe_name(scene_id) + ".download"
            path = OUT_DIR / filename
            temp_path = path.with_suffix(path.suffix + ".part")

            try:
                with temp_path.open("wb") as f:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)

                size = temp_path.stat().st_size
                if size == 0:
                    raise RuntimeError("Server returned an empty file.")

                temp_path.replace(path)
                print("\nSUCCESS: one response saved.")
                print("File:", path.resolve())
                print(f"Size: {size:,} bytes")
                print("Note: .download is a temporary extension; inspect the")
                print("file signature before renaming it to .tif or .zip.")

            finally:
                if temp_path.exists():
                    temp_path.unlink()

    except requests.RequestException as exc:
        print("Network/download error:", str(exc))
        raise SystemExit("Check the connection and retry later.")
