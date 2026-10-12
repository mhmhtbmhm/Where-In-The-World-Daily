"""بيانات المكان من Wikidata (CC0) وصوره من Wikimedia Commons (بترخيص مقبول فقط)."""
import io, re, requests
from PIL import Image

UA = {"User-Agent": "WhereInTheWorldDailyBot/1.0 (https://github.com/mhmhtbmhm/Where-In-The-World-Daily)"}
S = requests.Session(); S.headers.update(UA)
RELIGIOUS = re.compile(r"church|cathedral|temple|synagogue|monastery|abbey|pagoda|shrine|basilica|stupa|chapel|convent|"
                       r"cemetery|casino|nightclub|red-light|gambling|pilgrimage", re.I)
ALLOWED_LIC = re.compile(r"^(public domain|pd[- ]|cc0|cc[- ]by[- ]\d)", re.I)
BAD_LIC = re.compile(r"(\bsa\b|-sa\b|\bnc\b|-nc\b|\bnd\b|-nd\b|gfdl|fair use|non-free)", re.I)
UNITS_M = {"Q11573": 1.0, "Q174728": 0.01, "Q828224": 1000.0, "Q3710": 0.3048, "Q253276": 1609.344}
UNITS_KM2 = {"Q712226": 1.0, "Q25343": 1e-6, "Q35852": 0.01, "Q232291": 2.58999}
LABEL_Q_ISLAM = "Q432"


def get_json(url, params=None):
    r = S.get(url, params=params, timeout=45); r.raise_for_status(); return r.json()


def resolve_qid(title):
    j = get_json("https://en.wikipedia.org/w/api.php", {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                                                         "redirects": 1, "titles": title, "format": "json"})
    for p in j["query"]["pages"].values():
        q = p.get("pageprops", {}).get("wikibase_item")
        if q:
            return q
    return None


def entity(qid):
    return get_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")["entities"][qid]


def labels(ids, lang="en"):
    out, ids = {}, list(dict.fromkeys(ids))
    for i in range(0, len(ids), 40):
        j = get_json("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "ids": "|".join(ids[i:i + 40]),
                                                             "props": "labels", "languages": f"{lang}|en", "format": "json"})
        for k, v in j.get("entities", {}).items():
            lb = v.get("labels", {}); out[k] = (lb.get(lang) or lb.get("en") or {}).get("value")
    return out


def claims(ent, pid):
    cs = [c for c in ent.get("claims", {}).get(pid, []) if c.get("rank") != "deprecated" and c["mainsnak"].get("snaktype") == "value"]
    pref = [c for c in cs if c.get("rank") == "preferred"]
    return pref or cs


def latest(ent, pid):
    cs = claims(ent, pid)
    if not cs:
        return None
    def when(c):
        q = c.get("qualifiers", {}).get("P585")
        return q[0]["datavalue"]["value"]["time"] if q and q[0].get("datavalue") else ""
    return sorted(cs, key=when)[-1]


def qty(c, units):
    try:
        v = c["mainsnak"]["datavalue"]["value"]; u = v["unit"].rsplit("/", 1)[-1]
        return float(v["amount"]) * units[u] if u in units else None
    except Exception:
        return None


def year_of(c):
    try:
        v = c["mainsnak"]["datavalue"]["value"]; m = re.match(r"([+-])(\d+)-", v["time"])
        y = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        return y, v["precision"]
    except Exception:
        return None


def ids_of(ent, pid):
    return [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims(ent, pid)]


def fetch_place(title, lang, world):
    """يرجع (place, None) أو (None, سبب الرفض)."""
    qid = resolve_qid(title)
    if not qid:
        return None, "no qid"
    e = entity(qid)
    cs = claims(e, "P625")
    if not cs:
        return None, "no coordinates"
    cv = cs[0]["mainsnak"]["datavalue"]["value"]; lat, lon = cv["latitude"], cv["longitude"]
    rel = [r for r in ids_of(e, "P140")]
    if any(r != LABEL_Q_ISLAM for r in rel):
        return None, "religion filter"
    inst, country_ids, admin_ids = ids_of(e, "P31"), ids_of(e, "P17")[:3], ids_of(e, "P131")[:1]
    arch_ids, named_ids = ids_of(e, "P84")[:2], ids_of(e, "P138")[:1]
    her = [c for c in claims(e, "P1435") if c["mainsnak"]["datavalue"]["value"]["id"] == "Q9259"]
    lab = labels(inst + country_ids + admin_ids + arch_ids + named_ids + [qid], lang)
    kinds = [lab.get(i) for i in inst if lab.get(i)]
    if any(RELIGIOUS.search(k) for k in kinds):
        return None, "religious/ethics type: " + ", ".join(kinds)
    name = lab.get(qid) or title
    countries = [lab[i] for i in country_ids if lab.get(i)]
    if not countries:
        c = world.country_at(lat, lon)
        countries = [c] if c else []
    hy = None
    if her:
        q = her[0].get("qualifiers", {}).get("P580")
        if q and q[0].get("datavalue"):
            m = re.match(r"\+(\d+)-", q[0]["datavalue"]["value"]["time"]); hy = int(m.group(1)) if m else None
    pc = latest(e, "P1082"); pop = None
    if pc:
        try: pop = float(pc["mainsnak"]["datavalue"]["value"]["amount"])
        except Exception: pass
    inc = claims(e, "P571"); city = world.nearest_city(lat, lon, lang)
    admin = lab.get(admin_ids[0]) if admin_ids else None
    p = {"qid": qid, "name": name, "lat": lat, "lon": lon, "countries": countries,
         "admin": admin if admin and len(admin) < 30 and not admin[0].isdigit() and admin not in countries and admin != name else None,
         "kinds": kinds, "elev": next((qty(c, UNITS_M) for c in claims(e, "P2044") if qty(c, UNITS_M) is not None), None),
         "height": next((qty(c, UNITS_M) for c in claims(e, "P2048") if qty(c, UNITS_M) is not None), None),
         "length": next((qty(c, UNITS_M) for c in claims(e, "P2043") if qty(c, UNITS_M) is not None), None),
         "area": next((qty(c, UNITS_KM2) for c in claims(e, "P2046") if qty(c, UNITS_KM2) is not None), None),
         "pop": pop, "inception": year_of(inc[0]) if inc else None, "heritage": hy, "is_wh": bool(her),
         "architects": [lab[i] for i in arch_ids if lab.get(i)], "named_after": lab.get(named_ids[0]) if named_ids else None,
         "nearest": city, "commons_cat": (claims(e, "P373")[0]["mainsnak"]["datavalue"]["value"] if claims(e, "P373") else None),
         "p18": [c["mainsnak"]["datavalue"]["value"] for c in claims(e, "P18")]}
    return p, None


def _strip(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h or "")).strip()


def _image_ok(info):
    em = info.get("extmetadata", {})
    lic = em.get("LicenseShortName", {}).get("value", "")
    if not ALLOWED_LIC.search(lic) or BAD_LIC.search(lic):
        return None
    if em.get("Restrictions", {}).get("value") or em.get("NonFree", {}).get("value"):
        return None
    if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 1600:
        return None
    ratio = info["width"] / max(1, info["height"])
    if not 0.55 < ratio < 2.3:
        return None
    cats = em.get("Categories", {}).get("value", "")
    boost = 2 if re.search(r"Featured pictures|Quality images", cats) else 0
    artist = _strip(em.get("Artist", {}).get("value")) or _strip(em.get("Credit", {}).get("value")) or "Unknown author"
    return {"url": info.get("thumburl") or info["url"], "page": info.get("descriptionurl"), "lic": lic,
            "artist": artist[:80], "w": info["width"], "h": info["height"], "boost": boost}


def photos(p, want=4):
    q = {"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920, "format": "json"}
    found = []
    if p["p18"]:
        j = get_json("https://commons.wikimedia.org/w/api.php", dict(q, titles="|".join("File:" + f for f in p["p18"][:5])))
        for pg in j["query"]["pages"].values():
            r = _image_ok((pg.get("imageinfo") or [{}])[0]) if pg.get("imageinfo") else None
            if r: r["boost"] += 3; found.append(r)
    if p["commons_cat"]:
        j = get_json("https://commons.wikimedia.org/w/api.php", dict(q, generator="categorymembers", gcmtitle="Category:" + p["commons_cat"],
                                                                    gcmtype="file", gcmlimit=60))
        for pg in j.get("query", {}).get("pages", {}).values():
            r = _image_ok((pg.get("imageinfo") or [{}])[0]) if pg.get("imageinfo") else None
            if r: found.append(r)
    seen, out = set(), []
    for r in sorted(found, key=lambda r: (-r["boost"], -r["w"] * r["h"])):
        if r["url"] in seen: continue
        seen.add(r["url"]); out.append(r)
    imgs = []
    for r in out[: want + 3]:
        try:
            b = S.get(r["url"], timeout=60).content
            im = Image.open(io.BytesIO(b)).convert("RGB")
            if im.width >= 1200 and len(b) > 80_000:
                r["img"] = im; imgs.append(r)
        except Exception as ex:
            print("image skip:", ex)
        if len(imgs) >= want:
            break
    return imgs
