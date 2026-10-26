#!/usr/bin/env python3
"""Probe EOS-04 SAR availability over Murshidabad on Bhoonidhi (read-only, no downloads).

PowerShell:
  $env:BHOONIDHI_USER="..." ; $env:BHOONIDHI_PASS="..."
  python eos04_probe.py            # Murshidabad bbox, 2024-02-01 -> today
  python eos04_probe.py --start 2022-03-01
"""
import argparse, collections, os, sys, time
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://bhoonidhi-api.nrsc.gov.in"
BBOX = [87.8, 23.7, 88.8, 24.9]
COLS = ["EOS-04_SAR-MRS_L2A", "EOS-04_SAR-MRS_L2B", "EOS-04_SAR-MRS_SM",
        "EOS-04_SAR-CRS_L2A", "EOS-04_SAR-CRS_L2B",
        "EOS-04_SAR-FRS1_L2A", "EOS-04_SAR-FRS2_L2A"]

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2024-02-01")
ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
args = ap.parse_args()

user, pwd = os.environ.get("BHOONIDHI_USER"), os.environ.get("BHOONIDHI_PASS")
if not user or not pwd:
    sys.exit("Set BHOONIDHI_USER and BHOONIDHI_PASS first.")

s = requests.Session()
r = s.post(f"{BASE}/auth/token", json={"userId": user, "password": pwd, "grant_type": "password"}, timeout=60)
r.raise_for_status()
H = {"Authorization": f"Bearer {r.json()['access_token']}", "Accept": "application/json"}


def search(body, max_pages=40):
    items, url, b = [], f"{BASE}/data/search", body
    for _ in range(max_pages):
        time.sleep(0.5)
        r = s.post(url, json=b, headers=H, timeout=120)
        if r.status_code == 404 and "NO RESULTS" in r.text.upper():
            return items, "no results"
        if not r.ok:
            return items, f"HTTP {r.status_code}: {r.text[:200]}"
        d = r.json()
        feats = d.get("features", [])
        items += feats
        nxt = next((l for l in d.get("links", []) if l.get("rel") == "next"), None)
        if not feats or not nxt or not nxt.get("body"):
            break
        b = nxt["body"]
    return items, "ok"


def windows(start, end, step=360):
    a = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    z = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    out = []
    while a <= z:
        b = min(a + timedelta(days=step), z)
        out.append(f"{a:%Y-%m-%d}T00:00:00Z/{b:%Y-%m-%d}T23:59:59Z")
        a = b + timedelta(days=1)
    return out


wins = windows(args.start, args.end)
print(f"Window {args.start} -> {args.end} in {len(wins)} chunk(s) (API max 366 days), bbox {BBOX}\n")
for c in COLS:
    # (a) anything at all, anywhere in India, in the most recent chunk?
    anyw, st_any = search({"collections": [c], "datetime": wins[-1], "limit": 1}, max_pages=1)
    # (b) over Murshidabad, all chunks
    items, statuses = [], set()
    for w in wins:
        got, st = search({"collections": [c], "datetime": w, "bbox": BBOX, "limit": 500})
        items += got
        statuses.add(st)
    online = collections.Counter(str(i.get("properties", {}).get("Online", "?")) for i in items)
    months = collections.Counter((i.get("properties", {}).get("datetime") or "")[:7] for i in items)
    print(f"== {c}")
    print(f"   anywhere in India (latest chunk): {'has data' if anyw else st_any}")
    print(f"   Murshidabad : {len(items)} scenes | Online={dict(online)} | status={sorted(statuses)}")
    if items:
        print("   per month   :", dict(sorted(months.items())))
        print("   example id  :", items[0]["id"])
print("\nDone.")