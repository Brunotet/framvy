"""Build data/world.json (projected country paths), data/flags/*.svg and data/icons/*.svg. Run by the build-world workflow (needs internet)."""
import json, math, os, re, sys, urllib.request

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
FLAGS = "https://cdn.jsdelivr.net/gh/lipis/flag-icons@7.2.3/flags/4x3/%s.svg"
ICONS = "https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/icons/%s.svg"
ICON_NAMES = ["coins", "clock", "factory", "ship", "crown", "shopping-cart", "heart-pulse", "scroll-text", "hammer", "scale",
              "bus", "train-front", "plane", "car", "tv", "radio", "megaphone", "newspaper", "briefcase", "building-2",
              "flask-conical", "pill", "apple", "wheat", "beef", "milk", "coffee", "cup-soda", "utensils", "cookie",
              "lightbulb", "bomb", "shield", "flag", "trophy", "graduation-cap", "book-open", "house", "tree-pine", "gift",
              "banknote", "chart-line", "lock", "key-round", "users", "baby", "footprints", "dumbbell", "sun", "moon"]
W = 2000.0


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "framvy-build"})
    return urllib.request.urlopen(req, timeout=60).read()


def proj(lon, lat):
    lat = max(min(lat, 83.0), -58.0)
    x = (lon + 180.0) / 360.0 * W
    y = (math.pi - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))) / (2 * math.pi) * W
    return x, y


def ring_d(ring):
    pts = [proj(lo, la) for lo, la in ring]
    return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"


def main():
    os.makedirs("data", exist_ok=True)
    gj = json.loads(get(NE))
    out = []
    for f in gj["features"]:
        p = f["properties"]
        name = p.get("NAME") or p.get("ADMIN")
        if name == "Antarctica":
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        d, xs, ys = [], [], []
        for poly in polys:
            for ring in poly:
                d.append(ring_d(ring))
            for lo, la in poly[0]:
                x, y = proj(lo, la)
                xs.append(x); ys.append(y)
        a2 = p.get("ISO_A2_EH") or p.get("ISO_A2") or ""
        if a2 in ("-99", ""):
            a2 = ""
        # bbox of the largest polygon only, so far-away islands (France, USA, Russia) do not stretch the camera
        def deg_area(pl):
            r = pl[0]
            a = 0.0
            for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
                a += x1 * y2 - x2 * y1
            mid = sum(la for _, la in r) / max(len(r), 1)
            return abs(a) / 2 * math.cos(math.radians(mid))
        best = max(polys, key=deg_area)
        bx = [proj(lo, la)[0] for lo, la in best[0]]
        by = [proj(lo, la)[1] for lo, la in best[0]]
        out.append({"n": name, "long": p.get("NAME_LONG") or name, "admin": p.get("ADMIN") or name, "a2": a2.lower(),
                    "d": "".join(d), "bb": [round(min(bx), 1), round(min(by), 1), round(max(bx), 1), round(max(by), 1)]})
    json.dump({"w": W, "h": W, "countries": out}, open("data/world.json", "w"), separators=(",", ":"))
    print("countries", len(out), os.path.getsize("data/world.json"))
    os.makedirs("data/flags", exist_ok=True)
    n = 0
    for c in out:
        if c["a2"]:
            try:
                open(f"data/flags/{c['a2']}.svg", "wb").write(get(FLAGS % c["a2"])); n += 1
            except Exception as e:
                print("flag missing", c["a2"], e)
    print("flags", n)
    os.makedirs("data/icons", exist_ok=True)
    k = 0
    for name in ICON_NAMES:
        try:
            open(f"data/icons/{name}.svg", "wb").write(get(ICONS % name)); k += 1
        except Exception as e:
            print("icon missing", name, e)
    print("icons", k)


main()
