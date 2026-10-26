#!/usr/bin/env python3
"""
Bhoonidhi automated downloader
  AOI      : Murshidabad, West Bengal (approx bbox, or pass --geojson for exact boundary)
  Sensors  : LISS-3, LISS-4 (MX70), AWiFS  (Resourcesat-2 + 2A)   [+ optional EOS-04 SAR]
  Window   : 60 days ending at the latest ONLINE scene available over the AOI (auto),
             or explicit --start / --end
  Filter   : cloud <= --max-cloud (API has no cloud field: read from .meta, else estimated
             from the browse JPG), Online == 'Y' only

Usage:
  export BHOONIDHI_USER=your_id
  export BHOONIDHI_PASS=your_password
  python bhoonidhi_download.py --dry-run          # search only, writes catalog CSV
  python bhoonidhi_download.py                    # search + download
  python bhoonidhi_download.py --max-cloud 10 --days 60 --out ./data

API limits (from Bhoonidhi docs): auth 20/hr, search 3 req/s, 5 concurrent downloads.
"""
import argparse, csv, getpass, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://bhoonidhi-api.nrsc.gov.in"

SENSORS = {
    "LISS3": ["ResourceSat-2_LISS3_L2", "ResourceSat-2A_LISS3_L2"],
    "LISS4": ["ResourceSat-2_LISS4-MX70_L2", "ResourceSat-2A_LISS4-MX70_L2"],
    "AWIFS": ["ResourceSat-2_AWIFS_L2", "ResourceSat-2A_AWIFS_L2"],
    # EOS-04 is a SAR satellite (RISAT-1A): no cloud issue, different data type.
    "EOS04": ["EOS-04_SAR-MRS_L2A"],
}

# Murshidabad district, approximate bounding box (lon_min, lat_min, lon_max, lat_max)
MURSHIDABAD_BBOX = (87.80, 23.70, 88.80, 24.90)
MURSHIDABAD_BBOX_LIST = list(MURSHIDABAD_BBOX)

CLOUD_KEYS = ["eo:cloud_cover", "cloud_cover", "CloudCover", "Cloud_Cover",
              "cloudcover", "CLOUD_COVER", "Cloud"]


# ----------------------------------------------------------------- auth ----
class Session:
    def __init__(self, user, password):
        self.user, self.password = user, password
        self.access = self.refresh = None
        self.expiry = 0
        self.lock = threading.Lock()
        self.http = requests.Session()

    def _token_call(self, payload):
        for attempt in range(5):
            r = self.http.post(f"{BASE}/auth/token", json=payload, timeout=60)
            if r.status_code == 429:  # auth limit: 20/hour
                wait = 60 * (attempt + 1)
                print(f"[auth] 429 rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Auth rate limit keeps failing; try again later.")

    def ensure(self):
        """Return a valid access token (reuses, then refreshes, then re-logs in)."""
        with self.lock:
            if self.access and time.time() < self.expiry - 60:
                return self.access
            data = None
            if self.refresh:
                try:
                    data = self._token_call({"userId": self.user,
                                             "refresh_token": self.refresh,
                                             "grant_type": "refresh_token"})
                except requests.HTTPError:
                    data = None
            if data is None:
                data = self._token_call({"userId": self.user,
                                         "password": self.password,
                                         "grant_type": "password"})
            self.access = data["access_token"]
            self.refresh = data.get("refresh_token", self.refresh)
            self.expiry = time.time() + int(data.get("expires_in", 1200))
            return self.access

    def headers(self):
        return {"Authorization": f"Bearer {self.ensure()}",
                "Accept": "application/json",
                "Content-Type": "application/json"}

    def logout(self):
        try:
            if self.refresh:
                self.http.post(f"{BASE}/auth/logout",
                               headers={"Authorization": f"Bearer {self.refresh}"}, timeout=30)
        except Exception:
            pass


# --------------------------------------------------------------- search ----
def aoi_geometry(geojson_path):
    if geojson_path:
        with open(geojson_path) as f:
            gj = json.load(f)
        if gj.get("type") == "FeatureCollection":
            gj = gj["features"][0]
        return gj.get("geometry", gj)
    return None  # None -> use bbox (works reliably with the API)


def search(sess, body, max_pages=200):
    """POST /data/search and follow rel=next links. Respects 3 req/s search limit."""
    items, page = [], 0
    req_body, next_url = dict(body), None
    while page < max_pages:
        time.sleep(0.5)
        for attempt in range(5):
            if next_url:
                r = sess.http.get(next_url, headers=sess.headers(), timeout=120)
            else:
                r = sess.http.post(f"{BASE}/data/search", json=req_body,
                                   headers=sess.headers(), timeout=120)
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            break
        if r.status_code == 404 and "NO RESULTS" in r.text.upper():
            break  # API signals "nothing found" with a 404
        if not r.ok:
            print(f"[search] HTTP {r.status_code}: {r.text[:600]}", file=sys.stderr)
        r.raise_for_status()
        data = r.json()
        feats = data.get("features", [])
        items.extend(feats)
        page += 1
        if not feats:
            break
        nxt = next((l for l in data.get("links", []) if l.get("rel") == "next"), None)
        if not nxt:
            break
        if nxt.get("method", "GET").upper() == "POST" and nxt.get("body"):
            body2 = nxt["body"]
            req_body = {**req_body, **body2} if nxt.get("merge") else body2
            next_url = None
        else:
            next_url = nxt["href"]
    return items


def robust_search(sess, body):
    """Try the full request; if the server rejects it (400/406/422), retry simpler
    variants. Online=Y is then enforced client-side where the property exists."""
    variants = [body]
    no_filter = {k: v for k, v in body.items() if k not in ("filter", "filter-lang")}
    variants.append(no_filter)
    variants.append({**no_filter, "limit": 100})
    variants.append({k: v for k, v in {**no_filter, "limit": 100}.items() if k != "intersects"}
                    | {"bbox": MURSHIDABAD_BBOX_LIST})
    last = None
    for i, b in enumerate(variants):
        try:
            items = search(sess, b)
            if i:
                print(f"[search] worked with fallback variant #{i}", file=sys.stderr)
            return [it for it in items
                    if str(it.get("properties", {}).get("Online", "Y")).upper() != "N"]
        except requests.HTTPError as e:
            last = e
            if e.response is None or e.response.status_code not in (400, 406, 422, 500):
                raise
    raise last


def base_body(collections, dt, geom, online_only=True, limit=500):
    body = {"collections": collections, "datetime": dt, "limit": limit}
    if geom:
        body["intersects"] = geom
    else:
        body["bbox"] = MURSHIDABAD_BBOX_LIST
    if online_only:
        body["filter"] = {"args": [{"property": "Online"}, "Y"], "op": "eq"}
        body["filter-lang"] = "cql2-json"
    return body


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def item_date(it):
    p = it.get("properties", {})
    s = p.get("datetime") or p.get("start_datetime") or p.get("DOP") or ""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def find_latest_date(sess, collections, geom, lookback_days=150):
    """Latest ONLINE scene date over the AOI (so the 2-month window is data that exists)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    items = []
    for c in collections:
        items += robust_search(sess, base_body([c], f"{iso(start)}/{iso(end)}", geom, limit=500))
    dates = [d for d in map(item_date, items) if d]
    return max(dates) if dates else None


# --------------------------------------------------------------- cloud -----
_CLOUD_TAG = re.compile(r"<([^<>/\s]*cloud[^<>/\s]*)>\s*([-+]?\d+(?:\.\d+)?)\s*<", re.I)
_CLOUD_KV = re.compile(r"(cloud\w*)\s*[=:]\s*\"?([-+]?\d+(?:\.\d+)?)", re.I)


def _get(sess, url, **kw):
    r = sess.http.get(url, timeout=60, **kw)
    if r.status_code in (401, 403):
        r = sess.http.get(url, headers=sess.headers(), timeout=60, **kw)
    return r


def cloud_from_meta(sess, it):
    href = it.get("assets", {}).get("metadata", {}).get("href")
    if not href:
        return None, None, ""
    try:
        r = _get(sess, href)
        if not r.ok:
            return None, None, f"meta HTTP {r.status_code}"
        txt = r.text
    except requests.RequestException as e:
        return None, None, f"meta error {e}"
    for rx in (_CLOUD_TAG, _CLOUD_KV):
        m = rx.search(txt)
        if m:
            return float(m.group(2)), "meta", txt
    return None, None, txt


def cloud_from_thumb(sess, it):
    """Rough estimate: % of bright, low-saturation pixels in the browse JPG.
    Heuristic only (whole scene, not just the AOI) -- use for pre-screening."""
    try:
        from PIL import Image
        import numpy as np, io
    except ImportError:
        return None, None
    href = it.get("assets", {}).get("thumbnail", {}).get("href")
    if not href:
        return None, None
    try:
        r = _get(sess, href)
        if not r.ok:
            return None, None
        a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(int)
    except Exception:
        return None, None
    valid = a.sum(axis=2) > 30                    # ignore black no-data border
    if valid.sum() == 0:
        return None, None
    bright = (a.min(axis=2) > 170) & ((a.max(axis=2) - a.min(axis=2)) < 40) & valid
    return round(100.0 * bright.sum() / valid.sum(), 1), "thumb"


def get_cloud(sess, it, use_thumb=True):
    val, src, txt = cloud_from_meta(sess, it)
    if val is not None:
        return val, src, ""
    if use_thumb:
        v, s2 = cloud_from_thumb(sess, it)
        if v is not None:
            return v, s2, txt
    return None, None, txt



# ------------------------------------------------------------ download -----
def download_one(sess, it, outdir, retries=6):
    sid, col = it["id"], it["collection"]
    dest_dir = os.path.join(outdir, col)
    os.makedirs(dest_dir, exist_ok=True)
    existing = [f for f in os.listdir(dest_dir) if f.startswith(sid) and not f.endswith(".part")]
    if existing:
        return sid, "skipped (already downloaded)"
    for attempt in range(retries):
        try:
            r = sess.http.get(f"{BASE}/download", params={"id": sid, "collection": col},
                              headers=sess.headers(), stream=True, timeout=(30, 300))
        except requests.RequestException as e:
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
                return sid, f"ok -> {path}"
            except requests.RequestException:
                time.sleep(20)  # interrupted: restart from scratch (no Range support)
                continue
        if r.status_code == 404:
            return sid, "404 not on online storage (skipped)"
        if r.status_code in (412, 429):  # too many concurrent / rate limit
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 401:
            sess.access = None  # force re-auth next call
            continue
        time.sleep(30 * (attempt + 1))  # 500/504 etc: wait, don't hammer
    return sid, "FAILED after retries"


# ---------------------------------------------------------------- main -----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sensors", nargs="+", default=["LISS3", "LISS4", "AWIFS"],
                    choices=list(SENSORS), help="default: LISS3 LISS4 AWIFS (add EOS04 for SAR)")
    ap.add_argument("--days", type=int, default=60, help="window length in days (default 60)")
    ap.add_argument("--start", help="YYYY-MM-DD (skip auto-window)")
    ap.add_argument("--end", help="YYYY-MM-DD (skip auto-window)")
    ap.add_argument("--max-cloud", type=float, default=20.0, help="max cloud %% (default 20)")
    ap.add_argument("--no-thumb", action="store_true",
                    help="don't estimate cloud from thumbnail JPG when .meta has no cloud value")
    ap.add_argument("--save-thumbs", action="store_true",
                    help="save browse JPGs + thumbs.html contact sheet (to verify cloud by eye)")
    ap.add_argument("--keep-unknown-cloud", action="store_true",
                    help="keep scenes with no cloud value (default: drop them; SAR is always kept)")
    ap.add_argument("--geojson", help="exact AOI polygon (district boundary) instead of bbox")
    ap.add_argument("--out", default="./bhoonidhi_data")
    ap.add_argument("--workers", type=int, default=3, help="parallel downloads (max 5)")
    ap.add_argument("--dry-run", action="store_true", help="search + CSV only, no download")
    args = ap.parse_args()

    user = os.environ.get("BHOONIDHI_USER") or input("Bhoonidhi userId: ")
    pwd = os.environ.get("BHOONIDHI_PASS") or getpass.getpass("Password: ")
    sess = Session(user, pwd)
    os.makedirs(args.out, exist_ok=True)

    geom = aoi_geometry(args.geojson)
    cols = [c for s in args.sensors for c in SENSORS[s]]

    # ---- time window
    if args.start and args.end:
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end).replace(hour=23, minute=59, second=59,
                                                       tzinfo=timezone.utc)
    else:
        optical = [c for s in args.sensors if s != "EOS04" for c in SENSORS[s]] or cols
        latest = find_latest_date(sess, optical, geom)
        if not latest:
            sys.exit("No ONLINE scenes found over the AOI in the last ~13 months.")
        end = latest
        start = end - timedelta(days=args.days)
        print(f"Latest online scene over AOI: {end:%Y-%m-%d}  ->  window {start:%Y-%m-%d} to {end:%Y-%m-%d}")

    # ---- search (online only), per collection
    all_items = []
    for c in cols:
        got = robust_search(sess, base_body([c], f"{iso(start)}/{iso(end)}", geom))
        print(f"  {c}: {len(got)} online scenes")
        all_items += got
    if not all_items:
        sess.logout()
        sys.exit("Nothing found. Try a longer --days or different dates.")

    # ---- cloud cover: API has no cloud field -> read it from .meta / browse JPG
    print("\nSample item properties:", sorted(all_items[0].get("properties", {}).keys()))
    optical_items = [it for it in all_items if not it["collection"].startswith("EOS-04")]
    clouds = {}
    print(f"Fetching cloud info for {len(optical_items)} optical scenes ...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(get_cloud, sess, it, not args.no_thumb): it for it in optical_items}
        for fu in as_completed(futs):
            it = futs[fu]
            clouds[it["id"]] = fu.result()
    srcs = [v[1] for v in clouds.values()]
    print(f"  cloud from .meta: {srcs.count('meta')} | from thumbnail estimate: "
          f"{srcs.count('thumb')} | unknown: {srcs.count(None)}")
    if clouds and srcs.count("meta") == 0:
        sample_txt = next((v[2] for v in clouds.values() if v[2]), "")
        print("NOTE: no cloud tag found in .meta files. First 600 chars of one .meta:\n"
              + sample_txt[:600])

    selected, no_cloud = [], 0
    for it in all_items:
        is_sar = it["collection"].startswith("EOS-04")
        cc = clouds.get(it["id"], (None, None, ""))[0]
        if cc is None:
            no_cloud += 1
            if is_sar or args.keep_unknown_cloud:
                selected.append((it, cc))
        elif cc <= args.max_cloud:
            selected.append((it, cc))
    print(f"\n{len(all_items)} found | {len(selected)} selected (cloud <= {args.max_cloud}%) "
          f"| {no_cloud} without cloud value")

    # ---- catalog CSV
    csv_path = os.path.join(args.out, "catalog.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "collection", "datetime", "cloud_pct", "cloud_src", "selected"])
        sel_ids = {it["id"] for it, _ in selected}
        for it in all_items:
            d = item_date(it)
            cv = clouds.get(it["id"], (None, None, ""))
            w.writerow([it["id"], it["collection"], d.isoformat() if d else "",
                        cv[0], cv[1], it["id"] in sel_ids])
    print(f"Catalog saved: {csv_path}")

    if args.save_thumbs:
        import html as _html
        tdir = os.path.join(args.out, "thumbs")
        os.makedirs(tdir, exist_ok=True)
        cards = []
        def _save(it):
            href = it.get("assets", {}).get("thumbnail", {}).get("href")
            if not href:
                return None
            try:
                r = _get(sess, href)
                if r.ok:
                    fn = f"{it['id']}.jpg"
                    with open(os.path.join(tdir, fn), "wb") as f:
                        f.write(r.content)
                    return fn
            except requests.RequestException:
                pass
            return None
        opt = sorted(optical_items, key=lambda i: (item_date(i) or datetime.min.replace(tzinfo=timezone.utc)))
        with ThreadPoolExecutor(max_workers=4) as ex:
            files = list(ex.map(_save, opt))
        for it, fn in zip(opt, files):
            if not fn:
                continue
            cv = clouds.get(it["id"], (None, None, ""))[0]
            d = item_date(it)
            p = it.get("properties", {})
            cards.append(
                f'<div class="c"><img src="thumbs/{_html.escape(fn)}" loading="lazy">'
                f'<b>{d:%d %b %Y}</b> | est. cloud {cv}%<br>'
                f'{_html.escape(it["collection"])} P{p.get("Path")}/R{p.get("Row")}<br>'
                f'<small>{_html.escape(it["id"])}</small></div>')
        page = ("<html><meta charset=utf-8><style>body{font:13px sans-serif;background:#222;color:#eee}"
                ".g{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}"
                ".c{background:#333;padding:6px}img{width:100%}small{color:#aaa}</style>"
                f"<h3>Browse images ({len(cards)}) - estimated cloud shown, verify by eye</h3>"
                f'<div class="g">{"".join(cards)}</div></html>')
        with open(os.path.join(args.out, "thumbs.html"), "w", encoding="utf-8") as f:
            f.write(page)
        print(f"Contact sheet: {os.path.join(args.out, 'thumbs.html')}  (open in browser)")

    if args.dry_run:
        sess.logout()
        return

    # ---- download
    workers = max(1, min(args.workers, 5))
    print(f"\nDownloading {len(selected)} scenes with {workers} workers ...")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(download_one, sess, it, args.out) for it, _ in selected]
        for fu in as_completed(futs):
            sid, status = fu.result()
            print(f"  {sid}: {status}")
    sess.logout()
    print("Done.")


if __name__ == "__main__":
    main()