"""نص الرواية: جمل أصلية بقوالب من الحقائق فقط (لا نسخ نصوص ويكيبيديا، ولا اختلاق)."""
import re
from geo import compass, compass_i

PRON = {"a": "an", "e": "an", "i": "an", "o": "an", "u": "an"}


def art(w):
    return (PRON.get(w[0].lower(), "a")) + " " + w


def num(x):
    if x >= 1e6: return f"{x/1e6:.1f} million".replace(".0 ", " ")
    if x >= 10000: return f"{round(x, -3):,.0f}"
    if x >= 100: return f"{round(x):,}"
    return f"{x:.1f}".rstrip("0").rstrip(".")


def year_txt(y, prec):
    yy, = (y,)
    if prec == 7: return f"the {abs(yy)//100 + 1}th century" + (" BCE" if yy < 0 else "")
    return f"{abs(yy)} BCE" if yy < 0 else str(yy)


def sentences(p, lang="en"):
    if lang == "ar":
        return sentences_ar(p)
    return sentences_en(p)


def sentences_en(p):
    """يرجع (hook, reveal, facts[], closing)."""
    c = " and ".join(p["countries"]) if p["countries"] else "our planet"
    kind = p["kinds"][0] if p["kinds"] else "place"
    loc = (p["admin"] + ", " if p["admin"] else "") + c
    reveal = f"This is {p['name']}, {art(kind)} in {loc}."
    facts = []
    nm, km, br = p["nearest"]
    ns = abs(p["lat"]); ew = abs(p["lon"])
    facts.append(f"Its coordinates are {ns:.4f} degrees {'north' if p['lat'] >= 0 else 'south'}, "
                 f"{ew:.4f} degrees {'east' if p['lon'] >= 0 else 'west'}.")
    if km >= 2 and nm.lower() != p["name"].lower():
        facts.append(f"It lies about {num(km)} kilometers, or {num(km*0.621)} miles, {compass(br)} of {nm}.")
    tower = any(w in " ".join(p["kinds"]).lower() for w in ("mountain", "peak", "volcano", "hill"))
    if p["elev"] and p["elev"] > 5:
        facts.append(f"It {'rises' if tower else 'sits'} {num(p['elev'])} meters above sea level, about {num(p['elev']*3.28084)} feet.")
    if p["height"] and p["height"] > 5:
        facts.append(f"It stands {num(p['height'])} meters tall, about {num(p['height']*3.28084)} feet.")
    if p["length"] and p["length"] > 1000:
        facts.append(f"It stretches about {num(p['length']/1000)} kilometers.")
    if p["area"] and p["area"] > 0.05:
        facts.append(f"It covers roughly {num(p['area'])} square kilometers.")
    if p["pop"] and p["pop"] > 500:
        facts.append(f"About {num(p['pop'])} people live there.")
    if p["inception"]:
        y, prec = p["inception"]
        if prec >= 7:
            kk = " ".join(p["kinds"]).lower()
            verb = ("was founded in" if any(w in kk for w in ("city", "town", "village", "municipality"))
                    else "was completed in" if any(w in kk for w in ("tower", "bridge", "castle", "palace", "dam", "mosque", "building", "skyscraper", "fort", "monument", "stadium"))
                    else "was established in" if any(w in kk for w in ("park", "reserve")) else "dates back to")
            facts.append(f"It {verb} {year_txt(y, prec)}.")
    if p["architects"]:
        facts.append(f"It was designed by {' and '.join(p['architects'])}.")
    if p["named_after"]:
        facts.append(f"It is named after {p['named_after']}.")
    if p["is_wh"]:
        facts.append("It is a UNESCO World Heritage Site" + (f", listed since {p['heritage']}." if p["heritage"] else "."))
    return "Where in the world is this place?", reveal, facts, "Follow for a new place every day."


# ---------------- العربية ----------------
AR_DIRS = ["الشمال", "الشمال الشرقي", "الشرق", "الجنوب الشرقي", "الجنوب", "الجنوب الغربي", "الغرب", "الشمال الغربي"]


def n_ar(x):
    if x >= 1e6:
        return f"{x/1e6:.1f} مليون".replace(".0 ", " ")
    if x >= 10000:
        return f"{round(x, -3):,.0f}"
    if x >= 100:
        return f"{round(x):,}"
    return f"{x:.1f}".rstrip("0").rstrip(".")


def unit_ar(n, sing, plur):
    r = round(n)
    if abs(n - r) < 0.05 and 3 <= r <= 10:
        return f"{r} {plur}"
    return f"{n_ar(n)} {sing}"


def year_ar(y, prec):
    bce = " قبل الميلاد" if y < 0 else ""
    return (f"القرن {abs(y)//100 + 1}" if prec == 7 else f"عام {abs(y)}") + bce


def sentences_ar(p):
    """جمل بلا ضمائر مذكرة/مؤنثة: كل جملة تكرر اسم المكان، فتصح لغوياً لأي مكان."""
    nm = p["name"]
    c = " و".join(p["countries"]) if p["countries"] else "كوكبنا"
    kind = p["kinds"][0] if p["kinds"] and not re.search(r"[A-Za-z]", p["kinds"][0]) else "مكان"
    loc = (p["admin"] + "، " if p["admin"] else "") + c
    reveal = f"هذا هو {nm}، {kind} في {loc}."
    f = []
    ns, ew = abs(p["lat"]), abs(p["lon"])
    f.append(f"إحداثيات {nm}: {ns:.4f} درجة {'شمالاً' if p['lat'] >= 0 else 'جنوباً'}، و{ew:.4f} درجة {'شرقاً' if p['lon'] >= 0 else 'غرباً'}.")
    city, km, br = p["nearest"]
    if km >= 2 and city.lower() != nm.lower():
        f.append(f"{nm} على بعد نحو {unit_ar(km, 'كيلومتراً', 'كيلومترات')} إلى {AR_DIRS[compass_i(br)]} من {city}.")
    if p["elev"] and p["elev"] > 5:
        f.append(f"يبلغ ارتفاع {nm} {unit_ar(p['elev'], 'متراً', 'أمتار')} فوق سطح البحر.")
    if p["height"] and p["height"] > 5:
        f.append(f"يبلغ علو {nm} نحو {unit_ar(p['height'], 'متراً', 'أمتار')}.")
    if p["length"] and p["length"] > 1000:
        f.append(f"يبلغ طول {nm} نحو {unit_ar(p['length'] / 1000, 'كيلومتراً', 'كيلومترات')}.")
    if p["area"] and p["area"] > 0.05:
        f.append(f"تبلغ مساحة {nm} نحو {n_ar(p['area'])} كيلومتراً مربعاً.")
    if p["pop"] and p["pop"] > 500:
        f.append(f"يبلغ عدد سكان {nm} نحو {n_ar(p['pop'])} نسمة.")
    if p["inception"] and p["inception"][1] >= 7:
        f.append(f"يعود تاريخ {nm} إلى {year_ar(*p['inception'])}.")
    if p["architects"]:
        f.append(f"{nm} من تصميم {' و'.join(p['architects'])}.")
    if p["named_after"]:
        f.append(f"اسم {nm} مأخوذ من {p['named_after']}.")
    if p["is_wh"]:
        f.append(f"{nm} من مواقع التراث العالمي لليونسكو" + (f" منذ عام {p['heritage']}." if p["heritage"] else "."))
    return "هل تعرف أين يقع هذا المكان في العالم؟", reveal, f, "تابعنا لتكتشف مكاناً جديداً كل يوم."
