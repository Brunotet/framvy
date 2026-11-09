"""Code-drawn world map helpers: country lookup, camera views, flag/icon files. Data comes from data/ (built by the build-world workflow)."""
from __future__ import annotations
import json, re
from functools import lru_cache
from pathlib import Path

from .config import ROOT

DATA = ROOT / "data"
ALIASES = {
    "usa": "united states of america", "us": "united states of america", "u s": "united states of america", "america": "united states of america",
    "united states": "united states of america", "uk": "united kingdom", "britain": "united kingdom", "great britain": "united kingdom",
    "england": "united kingdom", "scotland": "united kingdom", "wales": "united kingdom", "ussr": "russia", "soviet union": "russia",
    "holland": "netherlands", "czech republic": "czechia", "ivory coast": "ivory coast", "burma": "myanmar", "persia": "iran",
    "prussia": "germany", "west germany": "germany", "east germany": "germany", "the netherlands": "netherlands",
    "south korea": "south korea", "north korea": "north korea", "korea": "south korea", "uae": "united arab emirates",
    "turkiye": "turkey", "swaziland": "eswatini", "macedonia": "north macedonia", "siam": "thailand", "ceylon": "sri lanka",
}


def _n(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower().replace("-", " ")).strip()


@lru_cache(maxsize=1)
def world() -> dict | None:
    p = DATA / "world.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def find(place: str) -> int | None:
    w = world()
    if not w or not place:
        return None
    q = _n(place)
    q = ALIASES.get(q, q)
    cs = w["countries"]
    for i, c in enumerate(cs):
        if q in (_n(c["n"]), _n(c["long"]), _n(c["admin"])) or q == c["a2"]:
            return i
    for i, c in enumerate(cs):
        if len(q) > 3 and (_n(c["n"]).startswith(q) or q.startswith(_n(c["n"]))):
            return i
    return None


def view_for(idx: int, aspect: float, pad: float = 1.9, min_w: float = 150.0, max_w: float = 1700.0):
    """viewBox [x, y, w, h] that frames country idx for a viewport of width/height = aspect."""
    x0, y0, x1, y1 = world()["countries"][idx]["bb"]
    bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    vw = min(max(bw * pad, bh * pad * aspect, min_w), max_w)
    vh = vw / aspect
    return [round((x0 + x1) / 2 - vw / 2, 1), round((y0 + y1) / 2 - vh / 2, 1), round(vw, 1), round(vh, 1)]


def wide_view(aspect: float):
    vw = 1500.0
    vh = vw / aspect
    return [round(1000 - vw / 2, 1), round(640 - vh / 2, 1), vw, round(vh, 1)]


def flag_file(idx: int) -> Path | None:
    a2 = world()["countries"][idx]["a2"]
    p = DATA / "flags" / f"{a2}.svg"
    return p if a2 and p.exists() else None


def icon_svg(name: str) -> str | None:
    name = re.sub(r"[^a-z0-9-]", "", (name or "").lower())
    p = DATA / "icons" / f"{name}.svg"
    if not p.exists():
        return None
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r'\s(width|height)="[^"]*"', "", s, count=2)
    return s.replace("<svg", '<svg width="100%" height="100%"', 1).replace('stroke-width="2"', 'stroke-width="2.2"')
