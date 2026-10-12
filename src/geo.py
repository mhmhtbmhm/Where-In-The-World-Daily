"""خرائط من بيانات Natural Earth (ملك عام): رسم متجهي بالكامل، لا صور خرائط من أي جهة."""
import json, math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
OCEAN_TOP, OCEAN_BOT = (14, 34, 58), (5, 12, 26)
LAND, LAND_HI, BORDER = (44, 62, 84), (58, 112, 140), (74, 98, 126)


def font(size):
    try:
        return ImageFont.truetype(FONT, size, layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        return ImageFont.load_default()


def merc(lat):
    lat = max(-85.0, min(85.0, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2); dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2); x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def shape_ar(t):
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(t))


def compass_i(b):
    return int((b + 22.5) // 45) % 8


def compass(b):
    return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][int((b + 22.5) // 45) % 8]


def inside(xy, x, y):
    xs, ys = xy[:, 0], xy[:, 1]
    x2, y2 = np.roll(xs, -1), np.roll(ys, -1)
    cond = ((ys > y) != (y2 > y)) & (x < (x2 - xs) * (y - ys) / (y2 - ys + 1e-12) + xs)
    return int(np.count_nonzero(cond)) % 2 == 1


class World:
    def __init__(self, data_dir):
        c = json.load(open(os.path.join(data_dir, "ne_50m_admin_0_countries.geojson"), encoding="utf-8"))
        self.countries = []
        for f in c["features"]:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            rings = []
            for p in polys:
                a = np.array(p[0], dtype=float)[:, :2]
                if len(a) < 4:
                    continue
                my = np.log(np.tan(np.pi / 4 + np.radians(np.clip(a[:, 1], -85, 85)) / 2))
                rings.append({"xy": a, "my": my, "bb": (a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()),
                              "mybb": (my.min(), my.max())})
            pr = f["properties"]
            self.countries.append({"name": pr.get("NAME") or pr.get("ADMIN"), "rings": rings})
        self.places = json.load(open(os.path.join(data_dir, "ne_places.json"), encoding="utf-8"))
        self.p_lon = np.array([x["lon"] for x in self.places]); self.p_lat = np.array([x["lat"] for x in self.places])
        self.p_pop = np.array([x["pop"] for x in self.places])
        self._bg = {}

    def country_at(self, lat, lon):
        for c in self.countries:
            for r in c["rings"]:
                x0, y0, x1, y1 = r["bb"]
                if x0 <= lon <= x1 and y0 <= lat <= y1 and inside(r["xy"], lon, lat):
                    return c["name"]
        return None

    def pname(self, i, lang="en"):
        x = self.places[int(i)]
        return x.get(lang) or x["en"]

    def nearest_city(self, lat, lon, lang="en", min_pop=20000):
        idx = np.where(self.p_pop >= min_pop)[0]
        la, lo = np.radians(self.p_lat[idx]), np.radians(self.p_lon[idx])
        a = np.sin((la - math.radians(lat)) / 2) ** 2 + math.cos(math.radians(lat)) * np.cos(la) * np.sin((lo - math.radians(lon)) / 2) ** 2
        d = 6371 * 2 * np.arcsin(np.sqrt(a)); k = int(np.argmin(d)); j = int(idx[k])
        return self.pname(j, lang), float(d[k]), bearing(float(self.p_lat[j]), float(self.p_lon[j]), lat, lon)

    def background(self, W, H):
        if (W, H) not in self._bg:
            col = np.linspace(OCEAN_TOP, OCEAN_BOT, H).astype("uint8")
            self._bg[(W, H)] = Image.fromarray(np.repeat(col[:, None, :], W, axis=1))
        return self._bg[(W, H)].copy()

    def render(self, W, H, clat, clon, s, highlight=None, accent=(255, 196, 61), pin=1.0, labels=True, lang="en"):
        img = self.background(W, H); d = ImageDraw.Draw(img)
        k = s * 180 / math.pi; cmy = merc(clat)
        lon0, lon1 = clon - W / 2 / s, clon + W / 2 / s
        my0, my1 = cmy - H / 2 / k, cmy + H / 2 / k
        step = max(1, min(12, int(5 / s))) if s < 5 else 1
        for c in self.countries:
            hi = highlight is not None and c["name"] == highlight
            for r in c["rings"]:
                x0, y0, x1, y1 = r["bb"]; m0, m1 = r["mybb"]
                if m1 < my0 or m0 > my1:
                    continue
                for sh in (-360, 0, 360):
                    if x1 + sh < lon0 or x0 + sh > lon1:
                        continue
                    xs = ((r["xy"][:, 0] + sh) - clon) * s + W / 2
                    ys = H / 2 - (r["my"] - cmy) * k
                    pts = np.column_stack((xs, ys))[::step]
                    if len(pts) < 3:
                        continue
                    d.polygon([tuple(p) for p in pts.tolist()], fill=LAND_HI if hi else LAND, outline=BORDER)
        if labels and s > 20:
            m = (self.p_lon > lon0) & (self.p_lon < lon1) & (self.p_lat > -85) & (self.p_pop > 150000)
            idx = np.where(m)[0]
            idx = idx[np.argsort(-self.p_pop[idx])][:7]
            f = font(30); placed = []
            for i in idx:
                x = (self.p_lon[i] - clon) * s + W / 2; y = H / 2 - (merc(float(self.p_lat[i])) - cmy) * k
                if 40 < x < W - 40 and 40 < y < H - 40 and abs(x - W / 2) + abs(y - H / 2) > 80 \
                        and all(abs(x - a) > 220 or abs(y - b) > 50 for a, b in placed):
                    placed.append((x, y))
                    d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(230, 235, 245))
                    nm = shape_ar(self.pname(i, lang)) if lang == "ar" else self.pname(i, lang)
                    d.text((x + 12, y - 16), nm, font=f, fill=(235, 240, 250), stroke_width=3, stroke_fill=(6, 14, 28))
        if pin > 0:
            cx, cy = W / 2, H / 2; r = 16 * pin
            d.ellipse([cx - r * 2.6, cy - r * 2.6, cx + r * 2.6, cy + r * 2.6], outline=accent, width=4)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 90, 70), outline=(255, 255, 255), width=4)
        return img
