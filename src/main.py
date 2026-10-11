import os, sys, json, hashlib, tempfile, datetime as dt
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


def order(places):
    return sorted(places, key=lambda p: hashlib.md5(("pod-v1" + p["t"]).encode()).hexdigest())


def candidates(places, st):
    left = [p for p in order(places) if p["t"] not in st["done"] and st["fail"].get(p["t"], 0) < 3]
    recent = st["recent"][-2:]
    pref = [p for p in left if p["c"] not in recent]       # تنويع القارات
    return pref + [p for p in left if p not in pref]


def meta(p, parts, photos):
    hook, reveal, facts, closing = parts
    lat, lon = p["lat"], p["lon"]; nm, km, _ = p["nearest"]
    country = " & ".join(p["countries"])
    title = f"{p['name']} — {country} | Where in the world?" if country else f"{p['name']} | Where in the world?"
    desc = [reveal] + facts + [
        "", f"Location: {lat:.4f}, {lon:.4f}",
        f"Google Maps: https://www.google.com/maps/search/?api=1&query={lat:.5f},{lon:.5f}",
        f"OpenStreetMap: https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=12/{lat:.5f}/{lon:.5f}", "",
        "Photo credits (Wikimedia Commons):"] + [f"- {r['artist']} · {r['lic']} · {r['page']}" for r in photos] + [
        "", "Map data: Natural Earth (public domain). Facts: Wikidata (CC0). Voice: synthesized.",
        "#geography #travel #places #shorts"]
    tags = ["geography", "travel", "places", p["name"], country, "where in the world", "world facts"]
    return title, "\n".join(desc), [t for t in tags if t]


def make_one(cand, ch, world, workdir, silent=False):
    p, why = wiki.fetch_place(cand["t"], ch["lang"], world)
    if not p:
        return None, why
    parts = story.sentences(p)
    if len(parts[2]) < MIN_FACTS:
        return None, f"thin facts ({len(parts[2])})"
    photos = wiki.photos(p)
    if len(photos) < MIN_PHOTOS:
        return None, f"not enough licensed photos ({len(photos)})"
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
    if "--demo" in sys.argv:
        p = {"name": "Demo Mountain", "lat": 27.9881, "lon": 86.925, "countries": ["Nepal", "China"], "admin": None, "kinds": ["mountain"],
             "elev": 8848.86, "height": None, "length": None, "area": None, "pop": None, "inception": None, "architects": [], "named_after": None,
             "is_wh": True, "heritage": 1979, "nearest": world.nearest_city(27.9881, 86.925)}
        photos = [{"img": fake_photo(i), "artist": "Test Author", "lic": "CC BY 4.0", "page": "https://commons.wikimedia.org/"} for i in range(3)]
        out = "/tmp/pod_demo.mp4"
        t = video.build_video(p, photos, world, story.sentences(p), "en", tempfile.mkdtemp(), out, silent=True)
        print("demo ok", round(t, 1), "s"); return
    if "--check" in sys.argv:                                  # فحص المصادر الحية (شغّله يدوياً أول مرة)
        for t in ("Eiffel Tower", "Machu Picchu", "Toubkal"):
            try:
                p, why = wiki.fetch_place(t, "en", world)
                if not p: print("REJECT", t, why); continue
                ph = wiki.photos(p); parts = story.sentences(p)
                print("OK", t, "| facts:", len(parts[2]), "| photos:", [(r["lic"], r["artist"][:20]) for r in ph])
            except Exception as e:
                print("FAIL", t, e)
        return
    if "--list" in sys.argv:
        st = {"done": [], "fail": {}, "recent": []}; print([p["t"] for p in candidates(places, st)[:9]]); return
    state = json.load(open(STATE_FILE)); now = dt.datetime.now(dt.timezone.utc); today = str(now.date())
    open(os.path.join(ROOT, "state", "heartbeat.txt"), "w").write(today)
    for ch in json.load(open(os.path.join(ROOT, "channels.json"), encoding="utf-8")):
        token = os.environ.get("YT_REFRESH_" + ch["id"].upper())
        if not token:
            print("no token for", ch["id"]); continue
        st = state.setdefault(ch["id"], {"done": [], "fail": {}, "recent": [], "day": today, "count": 0})
        if st["day"] != today:
            st["day"], st["count"] = today, 0
        if st["count"] >= MAX_PER_DAY:
            print("daily cap reached"); continue
        for cand in candidates(places, st)[:ATTEMPTS]:        # يجرّب مكاناً بعد آخر حتى ينجح واحد
            try:
                wd = tempfile.mkdtemp()
                res, why = make_one(cand, ch, world, wd)
                if not res:
                    print("skip", cand["t"], "-", why); st["fail"][cand["t"]] = st["fail"].get(cand["t"], 0) + 1; continue
                p, parts, photos, out, total = res
                title, desc, tags = meta(p, parts, photos)
                if ch.get("desc_footer"): desc += "\n\n" + ch["desc_footer"]
                vid = upload(out, title, desc, tags, token)
                print("posted", cand["t"], round(total), "s", vid)
                st["done"].append(cand["t"]); st["recent"] = (st["recent"] + [cand["c"]])[-6:]; st["count"] += 1
                break
            except Exception as e:
                print("failed", cand["t"], str(e)[:200]); st["fail"][cand["t"]] = st["fail"].get(cand["t"], 0) + 1
    json.dump(state, open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()
