
import getpass
import requests

API_URL = "https://bhoonidhi-api.nrsc.gov.in/auth/token"

print("Bhoonidhi API authentication diagnostic")
print("Password will not be displayed or saved.\n")

user_id = input("Bhoonidhi user ID: ").strip()
password = getpass.getpass("Bhoonidhi password: ")

payload = {
    "userId": user_id,
    "password": password,
    "grant_type": "password",
}

try:
    response = requests.post(
        API_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    print("\nHTTP status:", response.status_code)
    print("Content-Type:", response.headers.get("Content-Type", "unknown"))

    try:
        data = response.json()
        print("Response fields:", list(data.keys()))

        if response.ok and data.get("access_token"):
            print("Result: Authentication successful.")
            print("Access token received (value hidden).")
        else:
            print("Result: Authentication was not successful.")
            print("Server message:", data.get("Description", data.get("message", "No message provided")))

    except ValueError:
        print("Response was not JSON.")
        print("Response preview:", response.text[:200])

except requests.RequestException as error:
    print("Network/request error:", type(error).__name__)
    print("Details:", str(error)[:300])
