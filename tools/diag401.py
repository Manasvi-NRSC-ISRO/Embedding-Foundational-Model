import os, time, getpass, requests

BASE = "https://bhoonidhi-api.nrsc.gov.in"
user = os.environ.get("BHOONIDHI_USER") or input("Bhoonidhi userId: ")
pwd = os.environ.get("BHOONIDHI_PASS") or getpass.getpass("Password: ")
R2 = "ResourceSat-2_LISS3_BOA"
TESTS = [
    ("GOOD (pehle aaya tha)", "R2315JAN2025071312010700055PSANSTUCSRHTDF", R2),
    ("BAD? (401 diya)",       "R2308JUN2025073358010700054PSANSTUCSRHTDF", R2),
    ("BAD? (401 diya)",       "R2306OCT2025075063010700055PSANSTUCSRHTDF", R2),
    ("GOOD (pehle aaya tha)", "R2315JAN2025071312010700054PSANSTUCSRHTDF", R2),
]
http = requests.Session()

def login():
    r = http.post(f"{BASE}/auth/token",
                  json={"userId": user, "password": pwd, "grant_type": "password"}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], d.get("refresh_token")

def probe(token, sid, col):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json",
         "Content-Type": "application/json"}
    r = http.get(f"{BASE}/download", params={"id": sid, "collection": col},
                 headers=h, stream=True, timeout=(30, 120))
    try:
        if r.status_code == 200:
            n = len(next(r.iter_content(1 << 20), b""))
            return f"200 OK (pehla {n/1e6:.1f} MB padha, band kiya)"
        return f"{r.status_code} {r.text[:120]}"
    finally:
        r.close()

def run_round(label):
    print(f"\n=== {label}: fresh password login ===")
    access, refresh = login()
    for tag, sid, col in TESTS:
        print(f"{tag:24s} {sid[:26]}... -> {probe(access, sid, col)}")
        time.sleep(3)
    return refresh

run_round("Round 1")
refresh = run_round("Round 2")
try:
    http.post(f"{BASE}/auth/logout", headers={"Authorization": f"Bearer {refresh}"}, timeout=30)
except Exception:
    pass