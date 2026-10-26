src = open("bhoonidhi_fullyear.py", encoding="utf-8").read()

def sub(old, new):
    global src
    assert src.count(old) == 1, f"target not found exactly once:\n{old}"
    src = src.replace(old, new)

sub("    attempt = -1\n", "    attempt = -1\n    n401 = 0\n")

sub("""        if r.status_code == 401:
            try:
                sess.renew(h)
            except SessionDead as e:
                return sid, f"ABORT: {e}"
            continue
""", """        if r.status_code == 401:
            n401 += 1
            if n401 >= 2:   # same scene 401 again after re-login -> scene-specific, skip it
                sess.reauths = 0
                sess.scene401 = getattr(sess, "scene401", 0) + 1
                if sess.scene401 >= 5:
                    return sid, "ABORT: 5 scenes in a row gave 401 even after re-login; session really looks dead."
                return sid, f"FAILED scene-specific 401, skipped and continuing: {last}"
            try:
                sess.renew(h)
            except SessionDead as e:
                return sid, f"ABORT: {e}"
            continue
""")

sub("                sess.reauths = 0\n                mb =",
    "                sess.reauths = 0\n                sess.scene401 = 0\n                mb =")

open("bhoonidhi_v8.py", "w", encoding="utf-8").write(src)
print("wrote bhoonidhi_v8.py")