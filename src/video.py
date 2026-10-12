import os, math, wave, asyncio, subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import geo
from geo import font

W, H, FPS = 1080, 1920, 25
ACC, WHITE, LIGHT = (255, 196, 61), (255, 255, 255), (214, 224, 238)
VOICES = {"en": ["en-US-AndrewNeural", "en-US-GuyNeural"], "ar": ["ar-SA-HamedNeural", "ar-EG-ShakirNeural"]}
STR = {"en": {"where": "WHERE IN THE WORLD?", "photo": "Photo", "src": "Wikimedia Commons", "sep": " & ", "out": "Map: Natural Earth · Data: Wikidata"},
       "ar": {"where": "أين هذا المكان؟", "photo": "الصورة", "src": "ويكيميديا كومنز", "sep": " و", "out": "الخريطة: Natural Earth · البيانات: Wikidata"}}
GAP, LEAD, TAIL = 0.45, 0.45, 0.5


def shape(s, lang):
    if lang == "ar":
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(s))
    return s


# ---------- الصوت ----------
def write_silence(path, dur):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(b"\x00" * int(dur * 44100) * 4)


def tts(text, lang, path, force_silent=False):
    """يرجع مدة الجملة. عند فشل الصوت: صمت بمدة تقديرية، والترجمة النصية تحمل المعنى."""
    if not force_silent:
        for voice in VOICES.get(lang, VOICES["en"]):
            try:
                import edge_tts
                mp3 = path + ".mp3"
                asyncio.run(edge_tts.Communicate(text, voice, rate="-4%").save(mp3))
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ar", "44100", "-ac", "2",
                                "-sample_fmt", "s16", path], check=True)
                with wave.open(path) as w:
                    return w.getnframes() / w.getframerate()
            except Exception as e:
                print("tts failed:", voice, str(e)[:80])
    dur = max(1.8, len(text.split()) / 2.6)
    write_silence(path, dur)
    return dur


def build_scene_audio(sentences, lang, workdir, tag, silent=False):
    parts, timeline, t = [], [], 0.0
    out = os.path.join(workdir, f"{tag}.wav")
    with wave.open(out, "wb") as o:
        o.setnchannels(2); o.setsampwidth(2); o.setframerate(44100)
        def sil(d):
            o.writeframes(b"\x00" * int(d * 44100) * 4)
        sil(LEAD); t += LEAD
        for i, s in enumerate(sentences):
            f = os.path.join(workdir, f"{tag}_{i}.wav"); d = tts(s, lang, f, silent)
            with wave.open(f) as w:
                o.writeframes(w.readframes(w.getnframes()))
            timeline.append((t, t + d, s)); t += d
            sil(GAP if i < len(sentences) - 1 else TAIL); t += GAP if i < len(sentences) - 1 else TAIL
    return out, timeline, t


# ---------- أدوات الرسم ----------
def fit_font(d, text, size, maxw):
    while size > 26:
        f = font(size)
        if d.textlength(text, font=f) <= maxw:
            return f
        size -= 4
    return font(26)


def text_c(img, y, text, size, fill, lang="en", maxw=980, stroke=5):
    d = ImageDraw.Draw(img); text = shape(text, lang); f = fit_font(d, text, size, maxw)
    d.text(((img.width - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=(4, 10, 22))


def wrap(d, text, f, maxw, lang):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(shape(t, lang), font=f) <= maxw: cur = t
        else: lines.append(cur); cur = w
    lines.append(cur)
    return lines


def subtitle_img(text, lang):
    im = Image.new("RGBA", (W, 520), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    size = 58
    while True:
        f = font(size); lines = wrap(d, text, f, 940, lang)
        if len(lines) <= 4 or size <= 36: break
        size -= 4
    step = int(size * 1.28); y = (520 - step * len(lines)) // 2
    for ln in lines:
        t = shape(ln, lang)
        d.text(((W - d.textlength(t, font=f)) / 2, y), t, font=f, fill=WHITE, stroke_width=6, stroke_fill=(4, 10, 22)); y += step
    return im


def cover(im, w, h):
    s = max(w / im.width, h / im.height)
    r = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def compose_base(photo, name, line2, credit, lang):
    bg = cover(photo, W, H).filter(ImageFilter.GaussianBlur(38))
    bg = ImageEnhance.Brightness(bg).enhance(0.40).convert("RGBA")
    bw, bh = 1040, 1000
    s = min(bw / photo.width, bh / photo.height)
    fg = photo.resize((int(photo.width * s), int(photo.height * s)), Image.LANCZOS)
    x, y = (W - fg.width) // 2, 290 + (bh - fg.height) // 2
    sh = Image.new("RGBA", (fg.width + 120, fg.height + 120), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([60, 60, fg.width + 60, fg.height + 60], fill=(0, 0, 0, 190))
    bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)), (x - 60, y - 46))
    bg.paste(fg, (x, y))
    base = bg.convert("RGB")
    text_c(base, 92, name, 84, WHITE, lang)
    text_c(base, 196, line2, 44, ACC, lang, stroke=4)
    text_c(base, 1838, credit, 26, LIGHT, lang, maxw=1000, stroke=3)
    return base


def kenburns(base, t, T, mv):
    p = min(1.0, t / max(T, 0.1))
    z = [1.0 + 0.07 * p, 1.07 - 0.07 * p, 1.045][mv]
    cw, ch = W / z, H / z
    pan = (p - 0.5) * 36 if mv == 2 else 0
    x0 = (W - cw) / 2 + pan; y0 = (H - ch) / 2
    return base.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))


def fade(img, t, T, d=0.28):
    a = min(1.0, t / d, (T - t) / d); a = max(0.0, a)
    return img if a >= 1 else Image.blend(Image.new("RGB", img.size, (0, 0, 0)), img, a)


def current_sub(tl, t, cache, lang):
    for a, b, s in tl:
        if a - 0.05 <= t <= b + 0.15:
            if s not in cache: cache[s] = subtitle_img(s, lang)
            return cache[s]
    return None


class Encoder:
    def __init__(self, out, wav):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                   "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                                   "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
                                   "-shortest", out], stdin=subprocess.PIPE)
    def write(self, img):
        self.p.stdin.write(img.convert("RGB").tobytes())
    def close(self):
        self.p.stdin.close(); self.p.wait()


def ease(x):
    x = max(0.0, min(1.0, x)); return x * x * (3 - 2 * x)


def end_scale(area):
    return 14 if area and area > 1e6 else 28 if area and area > 1e5 else 50 if area and area > 1e4 else 95


def render_scene(kind, out, wav, tl, T, lang, ctx):
    enc = Encoder(out, wav); n = int(math.ceil(T * FPS)) + 1; cache = {}
    p, world = ctx["place"], ctx["world"]
    if kind in ("map", "outro"):
        s0, s1 = (3.0, ctx["s_end"]) if kind == "map" else (ctx["s_end"], ctx["s_end"] * 1.14)
        country = ctx["highlight"]; reveal_t = tl[1][0] if kind == "map" and len(tl) > 1 else 0
        for i in range(n):
            t = i / FPS; e = ease(t / max(T - 0.15, 0.1))
            s = s0 * (s1 / s0) ** e if kind == "map" else s0 * (s1 / s0) ** e
            img = world.render(W, H, p["lat"], p["lon"], s, country, ACC, pin=1.0 + 0.12 * math.sin(2 * math.pi * t), labels=True, lang=lang)
            if kind == "map" and t < reveal_t - 0.1:
                text_c(img, 150, STR[lang]["where"], 76, WHITE, lang)
            else:
                text_c(img, 120, p["name"], 84, WHITE, lang)
                text_c(img, 226, ctx["line2"], 46, ACC, lang, stroke=4)
                ns, ew = abs(p["lat"]), abs(p["lon"])
                coord = f"{ns:.4f}° {'N' if p['lat'] >= 0 else 'S'},  {ew:.4f}° {'E' if p['lon'] >= 0 else 'W'}"
                text_c(img, 1790, coord, 44, LIGHT, "en", stroke=4)
            if kind == "outro":
                text_c(img, 1850, STR[lang]["out"], 24, LIGHT, lang, stroke=3)
            sub = current_sub(tl, t, cache, lang)
            if sub:
                img = img.convert("RGBA"); img.alpha_composite(sub, (0, 1180)); img = img.convert("RGB")
            enc.write(fade(img, t, T))
    else:
        base, mv = ctx["base"], ctx["mv"]
        for i in range(n):
            t = i / FPS; img = kenburns(base, t, T, mv)
            sub = current_sub(tl, t, cache, lang)
            if sub:
                img = img.convert("RGBA"); img.alpha_composite(sub, (0, 1130)); img = img.convert("RGB")
            enc.write(fade(img, t, T))
    enc.close()


def build_video(place, photos, world, story_parts, lang, workdir, out, silent=False):
    hook, reveal, facts, closing = story_parts
    n = min(len(photos), 4); k = len(facts)
    chunks, i = [], 0
    for j in range(n):
        take = (k - i) // (n - j) + (1 if (k - i) % (n - j) else 0)
        chunks.append(facts[i:i + take]); i += take
    country = place["countries"][0] if place["countries"] else None
    line2 = ((place["admin"] + " · ") if place["admin"] else "") + STR[lang]["sep"].join(place["countries"])
    ctx_common = {"place": place, "world": world, "highlight": country, "line2": line2, "s_end": end_scale(place.get("area"))}
    plan = [("map", [hook, reveal])] + [("photo", c) for c in chunks if c] + [("outro", [closing])]
    clips, total, pi = [], 0.0, 0
    for idx, (kind, sents) in enumerate(plan):
        wav, tl, T = build_scene_audio(sents, lang, workdir, f"s{idx}", silent)
        ctx = dict(ctx_common)
        if kind == "photo":
            ph = photos[pi]; credit = f"{STR[lang]['photo']}: {ph['artist']} · {ph['lic']} · {STR[lang]['src']}"
            ctx["base"] = compose_base(ph["img"], place["name"], line2, credit, lang); ctx["mv"] = pi % 3; pi += 1
        clip = os.path.join(workdir, f"clip{idx}.mp4")
        render_scene(kind, clip, wav, tl, T, lang, ctx); clips.append(clip); total += T
        print(f"scene {idx} {kind}: {T:.1f}s")
    lst = os.path.join(workdir, "list.txt")
    open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                    "-movflags", "+faststart", out], check=True)
    return total
