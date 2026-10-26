# clean_logout.py
import os, getpass, requests
BASE = "https://bhoonidhi-api.nrsc.gov.in"
u = os.environ.get("BHOONIDHI_USER") or input("userId: ")
p = os.environ.get("BHOONIDHI_PASS") or getpass.getpass("Password: ")
r = requests.post(f"{BASE}/auth/token", json={"userId": u, "password": p, "grant_type": "password"}, timeout=60)
print("login:", r.status_code)
d = r.json()
for name, tok in (("refresh", d.get("refresh_token")), ("access", d.get("access_token"))):
    if tok:
        x = requests.post(f"{BASE}/auth/logout", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        print(f"logout with {name} token:", x.status_code, x.text[:150])