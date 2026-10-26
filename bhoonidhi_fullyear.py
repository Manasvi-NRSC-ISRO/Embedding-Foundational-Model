#!/usr/bin/env python3
"""
Bhoonidhi full-year downloader for an embedding-model pilot (Murshidabad, West Bengal)

  Sensors : AWiFS, LISS-III (Resourcesat-2 + 2A), EOS-04 SAR (MRS L2B)
  Product : BOA (surface reflectance) for optical by default; --product L2 for the older L2
  Window  : one calendar year (--year) or explicit --start/--end; searched in monthly chunks
            (the API rejects ranges > 366 days)
  Filters : Online == 'Y' only (offline scenes are listed in offline_scenes.csv, they must be
            ordered through Bhoonidhi Browse & Order). NO scene-level cloud filter by default:
            an embedding model needs the whole time series; mask clouds per pixel later.
            --estimate-cloud records a rough thumbnail-based cloud % in the manifest only.

PowerShell:
  $env:BHOONIDHI_USER = "..."
  $env:BHOONIDHI_PASS = "..."
  python bhoonidhi_fullyear.py --year 2025 --dry-run     # counts + temporal-density table
  python bhoonidhi_fullyear.py --year 2025               # download everything Online
"""
import argparse, collections, csv, getpass, io, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://bhoonidhi-api.nrsc.gov.in"
BBOX_DEFAULT = (87.80, 23.70, 88.80, 24.90)  # Murshidabad, approximate (minx, miny, maxx, maxy)

COLLECTIONS = {
    "LISS3": {"BOA": ["ResourceSat-2_LISS3_BOA", "ResourceSat-2A_LISS3_BOA"],
              "L2": ["ResourceSat-2_LISS3_L2", "ResourceSat-2A_LISS3_L2"]},
    "AWIFS": {"BOA": ["ResourceSat-2_AWIFS_BOA", "ResourceSat-2A_AWIFS_BOA"],
              "L2": ["ResourceSat-2_AWIFS_L2", "ResourceSat-2A_AWIFS_L2"]},
    "EOS04": {"BOA": ["EOS-04_SAR-MRS_L2B"], "L2": ["EOS-04_SAR-MRS_L2B"]},
}


# ----------------------------------------------------------------- auth ----
class SessionDead(Exception):
    pass


class Session:
    def __init__(self, user, password):
        self.user, self.password = user, password
        self.access = self.refresh = None
        self.expiry = 0
        self.lock = threading.Lock()
        self.http = requests.Session()
        self.reauths = 0      # consecutive 401-triggered renewals without a successful download
        self.dead = None      # set to a message when the server keeps rejecting fresh tokens

    def _token_call(self, payload):
        for attempt in range(5):
            r = self.http.post(f"{BASE}/auth/token", json=payload, timeout=60)
            if r.status_code == 429:  # auth limit: 20 per hour
                wait = 60 * (attempt + 1)
                print(f"[auth] 429 rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Auth rate limit keeps failing; try again later.")

    def ensure(self):
        with self.lock:
            if self.access and time.time() < self.expiry - 60:
                return self.access
            data = None
            if self.refresh:
                try:
                    data = self._token_call({"userId": self.user, "refresh_token": self.refresh,
                                             "grant_type": "refresh_token"})
                except requests.HTTPError:
                    data = None
            if data is None:
                data = self._token_call({"userId": self.user, "password": self.password,
                                         "grant_type": "password"})
            self.access = data["access_token"]
            self.refresh = data.get("refresh_token", self.refresh)
            self.expiry = time.time() + int(data.get("expires_in", 1200))
            return self.access

    def headers(self):
        return {"Authorization": f"Bearer {self.ensure()}", "Accept": "application/json",
                "Content-Type": "application/json"}

    def invalidate(self):
        with self.lock:
            self.access = None

    def renew(self, used_headers):
        """Call after an HTTP 401. Gets a new token only if no other thread already did
        (otherwise two workers keep invalidating each other's tokens), and gives up for good
        after repeated failures instead of burning the 20-logins-per-hour quota."""
        bad = used_headers["Authorization"].split(" ", 1)[1]
        with self.lock:
            if self.access and self.access != bad:
                return                      # another thread already renewed
            self.reauths += 1
            if self.reauths > 4:
                self.dead = ("Server keeps answering 401 'Invalid session' even with fresh tokens. "
                             "Likely causes: the same account is logged in elsewhere (Bhoonidhi website, "
                             "another terminal running this script) or the account's API session is stuck.")
                raise SessionDead(self.dead)
            self.access = None
        self.ensure()

    def logout(self):
        try:
            if self.refresh:
                self.http.post(f"{BASE}/auth/logout",
                               headers={"Authorization": f"Bearer {self.refresh}"}, timeout=30)
        except Exception:
            pass


# --------------------------------------------------------------- search ----
def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def month_windows(start, end, chunk_days=31):
    """Split [start, end] into chunks of <= chunk_days (API limit is 366 days per search)."""
    out, a = [], start
    while a <= end:
        b = min(a + timedelta(days=chunk_days - 1), end)
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


def search_all(sess, body, max_pages=100):
    """POST /data/search, follow rel=next. 404 'NO RESULTS' means empty, not an error."""
    items, b = [], dict(body)
    for _ in range(max_pages):
        time.sleep(0.5)  # search limit: 3 req/s
        r = None
        for attempt in range(5):
            r = sess.http.post(f"{BASE}/data/search", json=b, headers=sess.headers(), timeout=120)
            if r.status_code == 401:
                sess.invalidate()
                continue
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            break
        if r.status_code == 404 and "NO RESULTS" in r.text.upper():
            break
        if not r.ok:
            print(f"[search] HTTP {r.status_code}: {r.text[:400]}", file=sys.stderr)
            r.raise_for_status()
        data = r.json()
        feats = data.get("features", [])
        items += feats
        nxt = next((l for l in data.get("links", []) if l.get("rel") == "next"), None)
        if not feats or not nxt or not nxt.get("body"):
            break
        b = nxt["body"]
    return items


def item_dt(it):
    p = it.get("properties", {})
    s = p.get("datetime") or p.get("Imaging_Date") or ""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
    except Exception:
        return None


def is_online(it):
    return str(it.get("properties", {}).get("Online", "Y")).upper() != "N"


# --------------------------------------------- optional thumbnail cloud ----
def cloud_from_thumb(sess, it):
    """Rough % of bright, low-saturation pixels in the browse JPG (whole scene, heuristic)."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    href = it.get("assets", {}).get("thumbnail", {}).get("href")
    if not href:
        return None
    try:
        r = sess.http.get(href, timeout=60)
        if r.status_code in (401, 403):
            r = sess.http.get(href, headers=sess.headers(), timeout=60)
        if not r.ok:
            return None
        a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(int)
    except Exception:
        return None
    valid = a.sum(axis=2) > 30
    if valid.sum() == 0:
        return None
    bright = (a.min(axis=2) > 170) & ((a.max(axis=2) - a.min(axis=2)) < 40) & valid
    return round(100.0 * bright.sum() / valid.sum(), 1)


# ------------------------------------ footprint overlap (from .meta) ----
_META_KV = re.compile(r"^\s*([A-Za-z0-9_%]+)\s*=\s*(.*?)\s*$", re.M)


def _poly_area(p):
    return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1]
                   for i in range(len(p)))) / 2.0


def _clip(poly, inside, inter):
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ia, ib = inside(a), inside(b)
        if ia and ib:
            out.append(b)
        elif ia and not ib:
            out.append(inter(a, b))
        elif not ia and ib:
            out += [inter(a, b), b]
    return out


def aoi_overlap(pts, bbox):
    """Fraction (0..1) of the AOI bbox (minx, miny, maxx, maxy) covered by polygon pts [(lon, lat)]."""
    x0, y0, x1, y1 = bbox
    poly = list(pts)

    def ix(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def iy(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    for inside, inter in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)),
                          (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not poly:
            return 0.0
        poly = _clip(poly, inside, inter)
    return _poly_area(poly) / ((x1 - x0) * (y1 - y0)) if len(poly) >= 3 else 0.0


def scene_overlap(sess, it, bbox):
    """AOI coverage of the scene's TRUE image footprint, read from its 2 KB .meta file.
    The STAC geometry is only the product bounding box; the rotated image inside it can be
    much smaller (a scene can match the search and contain zero pixels of the AOI).
    Returns None if the footprint can't be read (scene is then kept)."""
    href = it.get("assets", {}).get("metadata", {}).get("href")
    if not href:
        return None
    try:
        r = sess.http.get(href, timeout=60)
        if r.status_code in (401, 403):
            r = sess.http.get(href, headers=sess.headers(), timeout=60)
        if not r.ok:
            return None
        kv = dict(_META_KV.findall(r.text))
    except requests.RequestException:
        return None
    for pre in ("Image", "Prod"):  # true image corners first, product corners as fallback
        try:
            pts = [(float(kv[f"{pre}{c}Lon"]), float(kv[f"{pre}{c}Lat"])) for c in ("UL", "UR", "LR", "LL")]
        except (KeyError, ValueError):
            continue
        return aoi_overlap(pts, bbox)
    return None


# ------------------------------------------------------------ download -----
def download_one(sess, it, outdir, retries=4):
    sid, col = it["id"], it["collection"]
    dest_dir = os.path.join(outdir, col)
    os.makedirs(dest_dir, exist_ok=True)
    if any(f.startswith(sid) and not f.endswith(".part") for f in os.listdir(dest_dir)):
        return sid, "skipped (already downloaded)"
    last = "no response"
    busy = 0  # waits caused by the 5-concurrent-downloads limit (HTTP 412) don't use up retries
    attempt = -1
    while attempt + 1 < retries:
        attempt += 1
        if sess.dead:
            return sid, f"ABORT: {sess.dead}"
        try:
            h = sess.headers()
            r = sess.http.get(f"{BASE}/download", params={"id": sid, "collection": col},
                              headers=h, stream=True, timeout=(30, 300))
        except requests.RequestException as e:
            last = f"network error: {e}"
            print(f"  [{sid}] attempt {attempt + 1}: {last}", file=sys.stderr)
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 200:
            cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            fname = m.group(1) if m else f"{sid}.zip"
            path = os.path.join(dest_dir, fname)
            try:
                with open(path + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                os.replace(path + ".part", path)
                sess.reauths = 0
                mb = os.path.getsize(path) / 1e6
                return sid, f"ok {mb:,.0f} MB -> {path}"
            except requests.RequestException as e:
                last = f"download interrupted: {e}"
                print(f"  [{sid}] attempt {attempt + 1}: {last}", file=sys.stderr)
                time.sleep(20)  # portal has no Range support: restart from scratch
                continue
        body = ""
        try:
            body = r.text[:300].replace("\n", " ")
        except Exception:
            pass
        last = f"HTTP {r.status_code} {body}"
        print(f"  [{sid}] attempt {attempt + 1}: {last}", file=sys.stderr)
        if r.status_code == 404:
            return sid, f"not on online storage ({last})"
        if r.status_code == 401:
            try:
                sess.renew(h)
            except SessionDead as e:
                return sid, f"ABORT: {e}"
            continue
        if r.status_code in (412, 429):  # too many concurrent downloads / rate limit
            busy += 1
            if busy > 20:
                return sid, f"FAILED: server still reports concurrent-download limit after ~20 min ({last})"
            attempt -= 1            # don't count as a failed attempt
            time.sleep(60)
            continue
        if r.status_code in (400, 402, 403, 405, 406, 422):
            return sid, f"FAILED ({last})"  # request/permission problem: retrying won't help
        time.sleep(30 * (attempt + 1))
    return sid, f"FAILED after retries (last: {last})"


# ---------------------------------------------------------------- main -----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sensors", nargs="+", default=["AWIFS", "LISS3", "EOS04"],
                    choices=list(COLLECTIONS))
    ap.add_argument("--product", choices=["BOA", "L2"], default="BOA",
                    help="optical product level (default BOA = surface reflectance)")
    ap.add_argument("--year", type=int, help="calendar year, e.g. 2025")
    ap.add_argument("--start", help="YYYY-MM-DD (instead of --year)")
    ap.add_argument("--end", help="YYYY-MM-DD (instead of --year)")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("MINX", "MINY", "MAXX", "MAXY"),
                    default=list(BBOX_DEFAULT), help="AOI bounding box (lon/lat)")
    ap.add_argument("--estimate-cloud", action="store_true",
                    help="record rough thumbnail cloud %% for optical scenes in manifest.csv")
    ap.add_argument("--max-cloud", type=float, default=None,
                    help="optional: drop optical scenes with estimated cloud above this (implies --estimate-cloud)")
    ap.add_argument("--min-overlap", type=float, default=0.05,
                    help="skip scenes whose real image covers less than this fraction of the AOI "
                         "(default 0.05 = 5%%; 0 disables the check)")
    ap.add_argument("--max-scenes", type=int, default=None,
                    help="test run: download only the first N scenes PER COLLECTION (to check file sizes)")
    ap.add_argument("--out", default="./bhoonidhi_year")
    ap.add_argument("--workers", type=int, default=3, help="parallel downloads (max 5)")
    ap.add_argument("--dry-run", action="store_true", help="search + manifest only, no download")
    args = ap.parse_args()

    if args.year:
        start = datetime(args.year, 1, 1, tzinfo=timezone.utc)
        end = datetime(args.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    elif args.start and args.end:
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    else:
        sys.exit("Give --year 2025 or both --start and --end.")
    if args.max_cloud is not None:
        args.estimate_cloud = True

    user = os.environ.get("BHOONIDHI_USER") or input("Bhoonidhi userId: ")
    pwd = os.environ.get("BHOONIDHI_PASS") or getpass.getpass("Password: ")
    sess = Session(user, pwd)
    os.makedirs(args.out, exist_ok=True)

    col_sensor = {}
    for s in args.sensors:
        for c in COLLECTIONS[s][args.product]:
            col_sensor[c] = s
    wins = month_windows(start, end)
    print(f"AOI bbox {args.bbox} | {start:%Y-%m-%d} -> {end:%Y-%m-%d} | {len(wins)} monthly chunks "
          f"| product={args.product}\n")

    # ---- search every collection, every chunk (one query, Online split client-side)
    found = {}
    try:
        for col in col_sensor:
            n_before = len(found)
            for a, b in wins:
                body = {"collections": [col], "datetime": f"{iso(a)}/{iso(b)}",
                        "bbox": args.bbox, "limit": 500}
                for it in search_all(sess, body):
                    found[(it["collection"], it["id"])] = it
            got = [v for k, v in found.items() if k[0] == col]
            on = sum(is_online(i) for i in got)
            print(f"  {col}: {len(got)} scenes ({on} online, {len(got) - on} offline)")
        items = list(found.values())
        if not items:
            sys.exit("\nNothing found. If BOA collections are empty for this year, try --product L2.")

        # ---- temporal density table: unique acquisition dates per month per sensor
        months = []
        m = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
        while m <= end:
            months.append(f"{m:%Y-%m}")
            m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        dens = {s: collections.defaultdict(set) for s in args.sensors}
        for it in items:
            if not is_online(it):
                continue
            d = item_dt(it)
            if d:
                dens[col_sensor[it["collection"]]][f"{d:%Y-%m}"].add(f"{d:%Y-%m-%d}")
        print("\nUnique acquisition DATES per month (online scenes) = temporal density per pixel region")
        print("month    " + "  ".join(f"{s:>6}" for s in args.sensors))
        for mo in months:
            print(f"{mo}   " + "  ".join(f"{len(dens[s].get(mo, ())):>6}" for s in args.sensors))
        print("total    " + "  ".join(
            f"{sum(len(v) for v in dens[s].values()):>6}" for s in args.sensors))

        # ---- optional cloud estimate (manifest only)
        cloud = {}
        if args.estimate_cloud:
            opt = [i for i in items if is_online(i) and col_sensor[i["collection"]] != "EOS04"]
            print(f"\nEstimating cloud from thumbnails for {len(opt)} optical scenes ...")
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(cloud_from_thumb, sess, it): it for it in opt}
                for fu in as_completed(futs):
                    it = futs[fu]
                    cloud[(it["collection"], it["id"])] = fu.result()

        # ---- real footprint overlap with the AOI (reads each scene's small .meta file)
        overlap = {}
        if args.min_overlap > 0:
            cand = [i for i in items if is_online(i)]
            print(f"\nChecking true AOI coverage of {len(cand)} online scenes from their .meta ...")
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(scene_overlap, sess, it, args.bbox): it for it in cand}
                for fu in as_completed(futs):
                    it = futs[fu]
                    overlap[(it["collection"], it["id"])] = fu.result()
            print("collection                         scenes  <thr(skip)  unknown  mean_cover_of_kept")
            for col in col_sensor:
                vals = [v for (c, _), v in overlap.items() if c == col]
                known = [v for v in vals if v is not None]
                low = [v for v in known if v < args.min_overlap]
                kept = [v for v in known if v >= args.min_overlap]
                mean = f"{100 * sum(kept) / len(kept):.0f}%" if kept else "-"
                print(f"{col:34s} {len(vals):6d}  {len(low):10d}  {len(vals) - len(known):7d}  {mean:>18}")

        # ---- selection
        selected = []
        for it in items:
            if not is_online(it):
                continue
            cc = cloud.get((it["collection"], it["id"]))
            if args.max_cloud is not None and cc is not None and cc > args.max_cloud:
                continue
            ov = overlap.get((it["collection"], it["id"]))
            if ov is not None and ov < args.min_overlap:
                continue
            selected.append(it)
        selected.sort(key=lambda i: (item_dt(i) or datetime.min.replace(tzinfo=timezone.utc)))
        if args.max_scenes:
            seen = collections.Counter()
            trimmed = []
            for it in selected:
                if seen[it["collection"]] < args.max_scenes:
                    trimmed.append(it)
                    seen[it["collection"]] += 1
            selected = trimmed

        # ---- manifest + offline list
        sel_ids = {(i["collection"], i["id"]) for i in selected}
        with open(os.path.join(args.out, "manifest.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["collection", "id", "datetime", "path", "row", "online", "cloud_est", "aoi_overlap", "selected"])
            for it in sorted(items, key=lambda i: (i["collection"], str(item_dt(i)))):
                p = it.get("properties", {})
                d = item_dt(it)
                k = (it["collection"], it["id"])
                w.writerow([it["collection"], it["id"], d.isoformat() if d else "", p.get("Path", ""),
                            p.get("Row", ""), p.get("Online", ""), cloud.get(k, ""),
                            "" if overlap.get(k) is None else round(overlap[k], 3), k in sel_ids])
        off = [i for i in items if not is_online(i)]
        if off:
            with open(os.path.join(args.out, "offline_scenes.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["collection", "id", "datetime"])
                for it in off:
                    d = item_dt(it)
                    w.writerow([it["collection"], it["id"], d.isoformat() if d else ""])
            print(f"\n{len(off)} offline scenes -> offline_scenes.csv (order via Browse & Order portal)")
        print(f"\n{len(items)} found | {len(selected)} online & selected | manifest: "
              f"{os.path.join(args.out, 'manifest.csv')}")

        if args.dry_run:
            return

        # ---- download
        workers = max(1, min(args.workers, 5))
        print(f"\nDownloading {len(selected)} scenes with {workers} workers ...")
        aborted = False
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(download_one, sess, it, args.out) for it in selected]
            for fu in as_completed(futs):
                if fu.cancelled():
                    continue
                sid, status = fu.result()
                if status.startswith("ABORT"):
                    if not aborted:
                        aborted = True
                        print(f"\n!! STOPPED: {status}\n"
                              "   Log out of the Bhoonidhi website, close other terminals running this script,\n"
                              "   wait ~20 minutes, then re-run the same command (finished scenes are skipped).\n")
                        for f in futs:
                            f.cancel()
                    continue
                print(f"  {sid}: {status}")
        print("Stopped early." if aborted else "Done.")
    finally:
        sess.logout()


if __name__ == "__main__":
    main()