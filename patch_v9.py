src = open("bhoonidhi_fullyear.py", encoding="utf-8").read()

def sub(old, new):
    global src
    assert src.count(old) == 1, f"patch target not found exactly once:\n{old}"
    src = src.replace(old, new)

# 1) refresh-token raasta band, hamesha password login
sub('BASE = "https://bhoonidhi-api.nrsc.gov.in"\n',
    'BASE = "https://bhoonidhi-api.nrsc.gov.in"\nUSE_REFRESH = False\n')
sub("            data = None\n            if self.refresh:\n",
    "            data = None\n            if self.refresh and USE_REFRESH:\n")

# 2) 401 par wait + fresh login (2,4,6,8 min), scene-wise
sub("    attempt = -1\n", "    attempt = -1\n    n401 = 0\n")
sub("""        if r.status_code == 401:
            try:
                sess.renew(h)
            except SessionDead as e:
                return sid, f"ABORT: {e}"
            continue
""", """        if r.status_code == 401:
            r.close()
            n401 += 1
            if n401 > 4:
                sess.reauths += 1
                if sess.reauths >= 3:
                    sess.dead = "3 scenes in a row kept returning 401 even after waiting + fresh login."
                    return sid, f"ABORT: {sess.dead}"
                return sid, f"FAILED: 401 persisted after 4 waits ({last})"
            wait = 120 * n401
            print(f"  [{sid}] 401 -> waiting {wait // 60} min, then fresh password login", file=sys.stderr)
            time.sleep(wait)
            with sess.lock:
                sess.refresh = None
                sess.access = None
            sess.ensure()
            attempt -= 1            # 401 retries retries use nahi karte
            continue
""")

# 3) adhuri file ko zip banne se roko
sub("""                os.replace(path + ".part", path)
                sess.reauths = 0
""", """                exp = int(r.headers.get("Content-Length", 0) or 0)
                got = os.path.getsize(path + ".part")
                if exp and got != exp and not r.headers.get("Content-Encoding"):
                    raise requests.exceptions.ChunkedEncodingError(f"size {got} != expected {exp}")
                os.replace(path + ".part", path)
                sess.reauths = 0
""")

open("bhoonidhi_v9.py", "w", encoding="utf-8").write(src)
print("wrote bhoonidhi_v9.py")