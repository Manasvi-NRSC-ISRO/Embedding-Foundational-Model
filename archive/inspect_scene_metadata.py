
import requests
from pathlib import Path

base = "https://bhoonidhi.nrsc.gov.in"

scene_id = "R2331JUL2025074111010800055PSANSTUC00GTDF"
metadata_url = f"{base}/" + scene_id + ".meta"

print("Requesting:", metadata_url)

try:
    response = requests.get(metadata_url, timeout=20)
    print("HTTP status:", response.status_code)
    print("Content type:", response.headers.get("Content-Type"))

    if response.ok:
        content = response.text
        output = Path("sample_scene_metadata.txt")
        output.write_text(content, encoding="utf-8")

        print("Metadata saved to:", output.resolve())
        print("\nRelevant lines:")

        keywords = [
            "download", "product", "order", "ftp", "http",
            "file", "size", "path", "format", "access"
        ]

        for line in content.splitlines():
            if any(word in line.lower() for word in keywords):
                print(line[:500])
    else:
        print(response.text[:500])

except requests.RequestException as exc:
    print("Request failed:", exc)
