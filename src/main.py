import os, sys, json, re, time, html, uuid, hashlib, tempfile, subprocess, datetime as dt
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo, wiki, story, video

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STATE_FILE = os.path.join(ROOT, "state", "posted.json")
MAX_PER_DAY, ATTEMPTS = 3, 6
MIN_FACTS, MIN_PHOTOS = 4, 2


def upload(mp4, title, desc, tags, token):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=token, token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:95], "description": desc[:4900], "tags": tags[:15], "categoryId": "19"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(mp4, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


EMPTY = {"done": [], "done_q": [], "fail": {}, "recent": [], "day": "", "count": 0}
RUN_ID = uuid.uuid4().hex[:12]        # بصمة فريدة لكل تشغيل: تمنع التزامين متطابقين من تشغيلين متزامنين


def _git(*a, check=True):
    return subprocess.run(["git", *a], cwd=ROOT, check=check, capture_output=True, text=True)


def _remote_state(branch):
    """None = الخادم غير متاح (لا نشر)؛ {} = الخادم متاح لكن الملف غير موجود بعد."""
    try:
        _git("fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    except Exception as e:
        print("remote unreachable:", str(e)[:120]); return None
    try:
        return json.loads(_git("show", f"origin/{branch}:state/posted.json").stdout)
    except Exception:
        return {}


def merge_states(remote, local):
    """اتحاد قوائم المنشور (لا شيء يُنسى أبداً)؛ العدّاد اليومي الأكبر؛ الإخفاقات الأكبر."""
    out = json.loads(json.dumps(remote or {}))
    for ch, l in local.items():
        r = out.setdefault(ch, json.loads(json.dumps(EMPTY)))
        r.pop("_claim", None)
        for k in ("done", "done_q"):
            lst = r.setdefault(k, [])
            lst.extend(x for x in l.get(k, []) if x not in lst)
        for t, n in l.get("fail", {}).items():
            r.setdefault("fail", {})[t] = max(n, r["fail"].get(t, 0))
        if l.get("day") == r.get("day"):
            r["count"] = max(l.get("count", 0), r.get("count", 0))
        elif l.get("day", "") > r.get("day", ""):
            r["day"], r["count"] = l.get("day", ""), l.get("count", 0)
        if l.get("recent"):
            r["recent"] = l["recent"]
        if l.get("_claim"):
            r["_claim"] = l["_claim"]
    return out


def _assign(state, merged):
    for k in [k for k in state if k not in merged]:
        del state[k]
    for k, v in merged.items():
        if isinstance(state.get(k), dict):
            state[k].clear(); state[k].update(v)         # نفس الكائن، فيرى st القيم الجديدة
        else:
            state[k] = v


def _in(state, claim):
    ch, title, qid = claim; s = state.get(ch, {})
    return title in s.get("done", []) or qid in s.get("done_q", [])


def _claim(state, claim):
    ch, title, qid = claim
    s = state.setdefault(ch, json.loads(json.dumps(EMPTY)))
    if title not in s.setdefault("done", []): s["done"].append(title)
    if qid not in s.setdefault("done_q", []): s["done_q"].append(qid)
    s["_claim"] = [title, qid, "building", RUN_ID]


def _release(state, claim):
    ch, title, qid = claim; s = state.get(ch, {})
    if title in s.get("done", []): s["done"].remove(title)
    if qid in s.get("done_q", []): s["done_q"].remove(qid)


def sync_from_remote(state):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    remote = _remote_state(os.environ.get("GITHUB_REF_NAME") or "main")
    if remote is not None:
        _assign(state, merge_states(remote, state))


def persist(state, note="state", claim=None, release=None):
    """يحفظ الحالة ويدفعها فوراً فوق آخر نسخة في الخادم. يرجع True أو "dup" (حجزه تشغيل آخر) أو False (تعذّر الحفظ)."""
    def write(s):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        json.dump(s, open(STATE_FILE, "w"), indent=0)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        if claim:
            if _in(state, claim): return "dup"
            _claim(state, claim)
        if release: _release(state, release)
        write(state); return True
    branch = os.environ.get("GITHUB_REF_NAME") or "main"
    today = str(dt.datetime.now(dt.timezone.utc).date())
    for _ in range(5):
        try:
            _git("config", "user.name", "pod-bot"); _git("config", "user.email", "bot@users.noreply.github.com")
            remote = _remote_state(branch)
            if remote is None:                                   # لا نتحقق من الخادم = لا نعتمد أي شيء (فشل مغلق)
                time.sleep(4); continue
            merged = merge_states(remote, state)
            if release: _release(merged, release)
            if claim:
                if _in(merged, claim):
                    _assign(state, merged); return "dup"
                _claim(merged, claim)
            _git("reset", "--hard", f"origin/{branch}")
            write(merged); open(os.path.join(ROOT, "state", "heartbeat.txt"), "w").write(today)
            _git("add", "state")
            if _git("diff", "--cached", "--quiet", check=False).returncode != 0:
                _git("commit", "-m", f"{note} {dt.datetime.now(dt.timezone.utc):%F-%H%M%S} {RUN_ID}")
                _git("push", "origin", f"HEAD:{branch}")
            _assign(state, merged); return True
        except subprocess.CalledProcessError as e:
            print("persist retry:", (e.stderr or "")[:300]); time.sleep(4)
        except Exception as e:
            print("persist error:", e); time.sleep(2)
    return False


def order(places, today):
    return sorted(places, key=lambda p: hashlib.md5(f"pod-v2|{today}|{p['t']}".encode()).hexdigest())


def candidates(places, st, today=""):
    left = [p for p in order(places, today) if p["t"] not in st["done"] and st["fail"].get(p["t"], 0) < 3]
    recent = st["recent"][-2:]
    pref = [p for p in left if p["c"] not in recent]       # تنويع القارات
    return pref + [p for p in left if p not in pref]


def recent_titles(channel_id):
    """عناوين آخر فيديوهات القناة من خلاصتها العامة (بلا مفتاح): حماية إضافية من التكرار."""
    if not channel_id:
        return []
    try:
        r = requests.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}, headers=wiki.UA, timeout=30)
        r.raise_for_status()
        return [html.unescape(t).lower() for t in re.findall(r"<entry>.*?<title>(.*?)</title>", r.text, re.S)]
    except Exception as e:
        print("channel feed check skipped:", e)
        return []


def title_seen(name, titles):
    n = (name or "").lower().strip()
    return bool(n) and any(n in t for t in titles)


L10N = {
    "en": {"title": "{name} — {c} | Where in the world?", "title1": "{name} | Where in the world?", "loc": "Location",
           "credits": "Photo credits (Wikimedia Commons):", "foot": "Map data: Natural Earth (public domain). Facts: Wikidata (CC0). Voice: synthesized.",
           "tags": ["geography", "travel", "places", "where in the world", "world facts"], "hash": "#geography #travel #places #shorts"},
    "ar": {"title": "{name} — {c} | أين هذا المكان؟", "title1": "{name} | أين هذا المكان؟", "loc": "الموقع",
           "credits": "حقوق الصور (ويكيميديا كومنز):", "foot": "الخرائط: Natural Earth (ملك عام). المعلومات: Wikidata (CC0). الصوت مُولَّد صناعياً.",
           "tags": ["جغرافيا", "سفر", "أماكن", "معلومات عامة", "أين هذا المكان"], "hash": "#جغرافيا #سفر #أماكن #shorts"},
}


def meta(p, parts, photos, lang="en"):
    hook, reveal, facts, closing = parts
    lat, lon = p["lat"], p["lon"]; T = L10N[lang]
    country = (" و" if lang == "ar" else " & ").join(p["countries"])
    title = (T["title"] if country else T["title1"]).format(name=p["name"], c=country)
    desc = [reveal] + facts + [
        "", f"{T['loc']}: {lat:.4f}, {lon:.4f}",
        f"Google Maps: https://www.google.com/maps/search/?api=1&query={lat:.5f},{lon:.5f}",
        f"OpenStreetMap: https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=12/{lat:.5f}/{lon:.5f}", "",
        T["credits"]] + [f"- {r['artist']} · {r['lic']} · {r['page']}" for r in photos] + ["", T["foot"], T["hash"]]
    return title, "\n".join(desc), [t for t in T["tags"] + [p["name"], country] if t]


def make_one(cand, ch, world, workdir, st, recent_t, state, silent=False):
    p, why = wiki.fetch_place(cand["t"], ch["lang"], world)
    if not p:
        return None, why
    if p["qid"] in st["done_q"] or title_seen(p["name"], recent_t):      # نُشر من قبل، حتى لو ضاعت الحالة
        if cand["t"] not in st["done"]: st["done"].append(cand["t"])
        if p["qid"] not in st["done_q"]: st["done_q"].append(p["qid"])
        persist(state, "dedupe")
        return None, "already published (dedupe)"
    parts = story.sentences(p, ch["lang"])
    if len(parts[2]) < MIN_FACTS:
        return None, f"thin facts ({len(parts[2])})"
    photos = wiki.photos(p)
    if len(photos) < MIN_PHOTOS:
        return None, f"not enough licensed photos ({len(photos)})"
    # حجز المكان ودفع الحالة قبل أي عمل مكلف؛ ولا نشر إن لم تُحفظ الحالة (فشل مغلق)
    res = persist(state, "claim", claim=(ch["id"], cand["t"], p["qid"]))
    if res == "dup":
        return None, "already published (claimed by another run)"
    if not res:
        raise RuntimeError("cannot save state: refusing to publish (would risk duplicates)")
    out = os.path.join(workdir, "final.mp4")
    total = video.build_video(p, photos, world, parts, ch["lang"], workdir, out, silent)
    return (p, parts, photos, out, total), None


def fake_photo(seed, w=2400, h=1600):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):
        k = y / h; d.line([(0, y), (w, y)], fill=(int(40 + 160 * k + seed * 10) % 255, int(90 + 80 * (1 - k)), int(180 - 90 * k)))
    d.polygon([(0, h), (w * .4, h * .35), (w * .62, h * .7), (w * .8, h * .5), (w, h)], fill=(30 + seed * 15, 45, 40))
    return im


def main():
    world = geo.World(DATA)
    places = json.load(open(os.path.join(DATA, "places.json"), encoding="utf-8"))
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
    if "--demo" in sys.argv:
        ar = lang == "ar"
        p = {"name": "جبل إيفرست" if ar else "Demo Mountain", "lat": 27.9881, "lon": 86.925, "countries": ["نيبال", "الصين"] if ar else ["Nepal", "China"],
             "admin": None, "kinds": ["جبل"] if ar else ["mountain"], "elev": 8848.86, "height": None, "length": None, "area": None, "pop": None,
             "inception": None, "architects": [], "named_after": "السير جورج إيفرست" if ar else None, "is_wh": True, "heritage": 1979,
             "nearest": world.nearest_city(27.9881, 86.925, lang)}
        photos = [{"img": fake_photo(i), "artist": "Test Author", "lic": "CC BY 4.0", "page": "https://commons.wikimedia.org/"} for i in range(3)]
        out = f"/tmp/pod_demo_{lang}.mp4"
        parts = story.sentences(p, lang)
        t = video.build_video(p, photos, world, parts, lang, tempfile.mkdtemp(), out, silent=True)
        print(meta(p, parts, photos, lang)[0]); print("demo ok", round(t, 1), "s"); return
    if "--check" in sys.argv:                                  # فحص المصادر الحية (شغّله يدوياً أول مرة)
        for ch in json.load(open(os.path.join(ROOT, "channels.json"), encoding="utf-8")):
            for t in ("Eiffel Tower", "Machu Picchu", "Toubkal"):
                try:
                    p, why = wiki.fetch_place(t, ch["lang"], world)
                    if not p: print("REJECT", t, why); continue
                    ph = wiki.photos(p); parts = story.sentences(p, ch["lang"])
                    print("OK", ch["lang"], t, "->", p["name"], "| facts:", len(parts[2]), "| photos:", [(r["lic"], r["artist"][:20]) for r in ph])
                except Exception as e:
                    print("FAIL", t, e)
        return
    if "--list" in sys.argv:
        st = {"done": [], "fail": {}, "recent": []}; print([p["t"] for p in candidates(places, st, str(dt.date.today()))[:9]]); return
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    now = dt.datetime.now(dt.timezone.utc); today = str(now.date())
    sync_from_remote(state)                                    # لا نبدأ أبداً من نسخة قديمة
    open(os.path.join(ROOT, "state", "heartbeat.txt"), "w").write(today)
    for ch in json.load(open(os.path.join(ROOT, "channels.json"), encoding="utf-8")):
        token = os.environ.get("YT_REFRESH_" + ch["id"].upper())
        if not token:
            print("no token for", ch["id"]); continue
        st = state.setdefault(ch["id"], {"done": [], "fail": {}, "recent": [], "day": today, "count": 0})
        st.setdefault("done_q", []); st.pop("_claim", None)      # حجز قديم = اعتبره منشوراً (الأحوط)
        if st["day"] != today:
            st["day"], st["count"] = today, 0
        if st["count"] >= MAX_PER_DAY:
            print("daily cap reached"); continue
        recent_t = recent_titles(ch.get("channel_id"))
        for cand in candidates(places, st, today)[:ATTEMPTS]:   # يجرّب مكاناً بعد آخر حتى ينجح واحد
            try:
                wd = tempfile.mkdtemp()
                res, why = make_one(cand, ch, world, wd, st, recent_t, state)
                if not res:
                    print("skip", cand["t"], "-", why)
                    if not why.startswith("already published"):
                        st["fail"][cand["t"]] = st["fail"].get(cand["t"], 0) + 1
                    continue
                p, parts, photos, out, total = res
                title, desc, tags = meta(p, parts, photos, ch["lang"])
                if ch.get("desc_footer"): desc += "\n\n" + ch["desc_footer"]
                st["_claim"][2] = "uploading"
                vid = upload(out, title, desc, tags, token)
                print("posted", cand["t"], round(total), "s", vid)
                st["recent"] = (st["recent"] + [cand["c"]])[-6:]; st["count"] += 1; st.pop("_claim", None)
                if not persist(state, "posted"):
                    print("WARNING: posted but state push failed")
                break
            except Exception as e:
                print("failed", cand["t"], str(e)[:200])
                c = st.get("_claim"); rel = None
                if c and c[0] == cand["t"] and c[2] == "building":    # لم يبدأ الرفع: أفرج عن الحجز
                    rel = (ch["id"], c[0], c[1])
                st.pop("_claim", None)
                st["fail"][cand["t"]] = st["fail"].get(cand["t"], 0) + 1
                persist(state, "fail", release=rel)
                if "cannot save state" in str(e):
                    raise SystemExit(1)                          # يُظهر فشلاً أحمر بدل نشر مكرر صامت
    persist(state, "final")


if __name__ == "__main__":
    main()
