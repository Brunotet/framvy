"""Download the whole lucide icon set into data/icons/*.svg (needs internet). Run by the build-icons workflow."""
import json, os, urllib.request
from concurrent.futures import ThreadPoolExecutor

VER = "0.460.0"
LIST = f"https://data.jsdelivr.com/v1/package/npm/lucide-static@{VER}/flat"
ICON = f"https://cdn.jsdelivr.net/npm/lucide-static@{VER}/icons/%s.svg"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "framvy-build"})
    return urllib.request.urlopen(req, timeout=60).read()


def main():
    files = json.loads(get(LIST))["files"]
    names = sorted(f["name"][len("/icons/"):-4] for f in files if f["name"].startswith("/icons/") and f["name"].endswith(".svg"))
    print("lucide icons listed", len(names))
    os.makedirs("data/icons", exist_ok=True)

    def one(n):
        p = f"data/icons/{n}.svg"
        if os.path.exists(p):
            return 1
        try:
            open(p, "wb").write(get(ICON % n)); return 1
        except Exception as e:
            print("missing", n, e); return 0

    with ThreadPoolExecutor(16) as ex:
        ok = sum(ex.map(one, names))
    json.dump(names, open("data/icon_names.json", "w"), separators=(",", ":"))
    print("icons ok", ok)


main()
