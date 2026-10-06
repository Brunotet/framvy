"""
Timeline -> HyperFrames project (index.html with data-attributes + one paused GSAP timeline).
Everything is deterministic (no wall-clock animation), so HyperFrames can seek frame-exact.

Transitions: native GSAP ones (fade, whip, zoom, flash, cut) work for any pattern of cuts.
GPU-style shader transitions (HyperShader) are used when a scene's `transition` is a shader
name (e.g. "glitch", "light-leak", "cinematic-zoom"). HyperShader needs ONE contiguous run of
shader boundaries, so the longest run is used and the rest fall back to "flash".
"""
from __future__ import annotations
import html, json, math, shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import ROOT

SHADERS = {"domain-warp", "ridged-burn", "whip-pan", "sdf-iris", "ripple-waves", "gravitational-lens",
           "cinematic-zoom", "chromatic-split", "swirl-vortex", "thermal-distortion",
           "flash-through-white", "cross-warp-morph", "light-leak", "glitch"}
NATIVE = {"cut", "fade", "whip", "zoom", "flash"}
GRADES = {"warm": "contrast(1.08) saturate(1.15) sepia(.10)", "cool": "contrast(1.08) saturate(1.05) hue-rotate(-8deg)",
          "punchy": "contrast(1.15) saturate(1.3)", "none": "none"}
VENDOR = {  # file -> source inside node_modules
    "gsap.min.js": "gsap/dist/gsap.min.js",
    "hyperframe.runtime.iife.js": "@hyperframes/core/dist/hyperframe.runtime.iife.js",
    "shader-transitions.js": "@hyperframes/shader-transitions/dist/index.global.js",
}


def available() -> bool:
    return all((ROOT / "node_modules" / src).exists() for src in VENDOR.values())


def _uri_to_path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def _copy_asset(uri: str, assets: Path, seen: dict) -> str:
    if uri in seen:
        return seen[uri]
    src = _uri_to_path(uri)
    name = f"{len(seen):03d}_{src.name}"
    shutil.copy(src, assets / name)
    seen[uri] = f"assets/{name}"
    return seen[uri]


def _f(x: float) -> str:
    return f"{x:.3f}"


def _motion_js(sel: str, motion: str, st: float, dur: float, H: int, L: list):
    d = _f(dur)
    if motion == "zoom_in":
        L.append(f'tl.fromTo("{sel}",{{scale:1.04}},{{scale:1.22,duration:{d},ease:"none"}},{_f(st)});')
    elif motion == "zoom_out":
        L.append(f'tl.fromTo("{sel}",{{scale:1.22}},{{scale:1.04,duration:{d},ease:"none"}},{_f(st)});')
    elif motion in ("pan_left", "pan_right"):
        a, b = (5, -5) if motion == "pan_left" else (-5, 5)
        L.append(f'tl.fromTo("{sel}",{{scale:1.16,xPercent:{a}}},{{xPercent:{b},duration:{d},ease:"sine.inOut"}},{_f(st)});')
    elif motion == "float":
        n = max(0, int(dur / 1.6) - 1)
        L.append(f'tl.fromTo("{sel}",{{scale:1.1,yPercent:-1.5}},{{yPercent:1.5,duration:1.6,ease:"sine.inOut",yoyo:true,repeat:{n}}},{_f(st)});')
    elif motion == "push":
        L.append(f'tl.fromTo("{sel}",{{scale:1.02}},{{scale:1.2,duration:0.55,ease:"expo.out"}},{_f(st)});')
        L.append(f'tl.to("{sel}",{{scale:1.27,duration:{_f(max(0.1, dur - 0.55))},ease:"none"}},{_f(st + 0.55)});')
    elif motion == "shake":
        L.append(f'tl.fromTo("{sel}",{{scale:1.12}},{{scale:1.22,duration:{d},ease:"none"}},{_f(st)});')
        for k in range(23):
            amp = 26 * math.exp(-k * 0.18) + 3
            dx, dy = math.sin(k * 2.1) * amp, math.cos(k * 1.7 + 0.8) * amp * 0.8
            L.append(f'tl.to("{sel}",{{x:{dx:.1f},y:{dy:.1f},duration:0.04,ease:"none"}},{_f(st + k * 0.04)});')
        L.append(f'tl.to("{sel}",{{x:0,y:0,duration:0.12,ease:"power2.out"}},{_f(st + 23 * 0.04)});')


def build(timeline: dict, project: Path) -> Path:
    W, H, total = timeline["width"], timeline["height"], timeline["duration"]
    theme, look = timeline.get("theme") or {}, timeline.get("look") or {}
    scenes, caps = timeline["scenes"], timeline.get("captions") or {}
    if project.exists():
        shutil.rmtree(project)
    assets = project / "assets"
    vendor = project / "vendor"
    assets.mkdir(parents=True)
    vendor.mkdir()
    for name, src in VENDOR.items():
        shutil.copy(ROOT / "node_modules" / src, vendor / name)
    seen: dict = {}

    # ---- transitions: split shader run vs native ------------------------
    bounds = []  # per scene i>0: resolved transition
    for i, sc in enumerate(scenes):
        t = (sc["transition"]["type"] if i > 0 else "cut")
        bounds.append(t if (t in NATIVE or t in SHADERS) else "flash")
    runs, cur = [], []
    for i, t in enumerate(bounds):
        if i > 0 and t in SHADERS:
            if cur and cur[-1] == i - 1:
                cur.append(i)
            else:
                if cur:
                    runs.append(cur)
                cur = [i]
    if cur:
        runs.append(cur)
    shader_run = max(runs, key=len) if runs else []
    for r in runs:
        if r is not shader_run:
            for i in r:
                bounds[i] = "flash"
    anchors = set()
    if shader_run:
        anchors = set(range(shader_run[0] - 1, shader_run[-1] + 1))

    # ---- HTML ----------------------------------------------------------
    uc = "uppercase" if theme.get("uppercase") else "none"
    fam = theme.get("font_family") or "'DejaVu Sans', Arial, sans-serif"
    head_fonts, font_face = "", ""
    if theme.get("font_google"):
        g = theme["font_google"].replace(" ", "+")
        head_fonts = f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={g}&display=swap">'
    if theme.get("font_file"):
        font_face = f"@font-face{{font-family:'ChannelFont';src:url('{_copy_asset(theme['font_file'], assets, seen)}')}}"
        fam = f"'ChannelFont', {fam}"
    text_c, accent = theme.get("text_color") or "#fff", theme.get("accent") or "#FFD400"

    scene_html, popup_html, cap_html, L = [], [], [], []
    for i, sc in enumerate(scenes):
        sid = f"s{i + 1}"
        st, en = sc["start"], sc["end"]
        nxt_t = bounds[i + 1] if i + 1 < len(scenes) else "cut"
        ov = 0.0 if (nxt_t == "cut" or (i + 1) in shader_run or i + 1 >= len(scenes)) else float(scenes[i + 1]["transition"]["dur"])
        dur = (en - st) + ov
        style = "" if i == 0 else ' style="visibility:hidden;"'
        if i in anchors:
            style = ' style="opacity:0;"'
        vis = sc["visual"]
        inner = [f'<div class="bg" id="{sid}-bg" style="background:linear-gradient(160deg,{sc["bg"][0]},{sc["bg"][-1]})"></div>']
        content = []
        if vis["type"] == "image":
            rel = _copy_asset(vis["src"], assets, seen)
            content.append(f'<div class="vis"><img class="vimg" id="{sid}-img" src="{rel}" style="object-fit:{vis.get("fit", "cover")}"></div>'
                           '<div class="shade"></div>')
            _motion_js(f"#{sid}-img", vis.get("motion") or "zoom_in", st, dur, H, L)
        elif vis["type"] == "text":
            words = (vis.get("text") or "").split()
            n = len(" ".join(words))
            size = round(H * (0.085 if n <= 20 else 0.065 if n <= 50 else 0.05))
            spans = "".join(f'<span class="w">{html.escape(w)}</span> ' for w in words)
            content.append(f'<div class="vis"><div class="ktext" id="{sid}-txt" style="font-size:{size}px">{spans}</div></div>')
            L.append(f'tl.from("#{sid}-txt .w",{{y:60,autoAlpha:0,scale:.75,duration:.45,ease:"back.out(1.7)",stagger:.07}},{_f(st + .08)});')
            L.append(f'tl.fromTo("#{sid}-txt",{{yPercent:1.5}},{{yPercent:-1.5,duration:{_f(dur)},ease:"sine.inOut"}},{_f(st)});')
            L.append(f'tl.fromTo("#{sid}-bg",{{scale:1.05}},{{scale:1.18,duration:{_f(dur)},ease:"none"}},{_f(st)});')
        ch = sc.get("character")
        if ch:
            rel = _copy_asset(ch["src"], assets, seen)
            side = "right" if ch["side"] == "right" else "left"
            content.append(f'<div class="chwrap {side}"><img class="char" id="{sid}-ch" src="{rel}" style="height:{round(H * ch["scale"])}px"></div>')
            sgn = 1 if side == "right" else -1
            if ch["action"] in ("enter", "bounce"):
                L.append(f'tl.from("#{sid}-ch",{{xPercent:{sgn * 130},duration:.5,ease:"back.out(1.5)"}},{_f(st + .12)});')
            if ch["action"] == "bounce":
                n = max(0, int(dur / 0.3) - 2)
                L.append(f'tl.to("#{sid}-ch",{{y:{-round(H * 0.012)},duration:.3,ease:"sine.inOut",yoyo:true,repeat:{n}}},{_f(st + .6)});')
        scene_html.append(
            f'<div class="scene clip" id="{sid}" data-start="{_f(st)}" data-duration="{_f(dur)}" data-track-index="0"{style}>'
            f'<div class="scene-inner">{"".join(inner)}<div class="scene-content">{"".join(content)}</div></div></div>')

        # visibility toggles (non-anchors) + entry transition
        if i not in anchors:
            if i > 0:
                L.append(f'tl.set("#{sid}",{{autoAlpha:1}},{_f(st)});')
            if i + 1 < len(scenes):
                L.append(f'tl.set("#{sid}",{{autoAlpha:0}},{_f(st + dur)});')
        elif i == shader_run[0] - 1 or True:
            pass
        if i > 0 and bounds[i] in NATIVE and bounds[i] != "cut":
            d, sel, t = _f(scenes[i]["transition"]["dur"]), f"#{sid} .scene-inner", bounds[i]
            if t == "fade":
                L.append(f'tl.from("{sel}",{{autoAlpha:0,duration:{d},ease:"power2.out"}},{_f(st)});')
            elif t == "whip":
                L.append(f'tl.from("{sel}",{{xPercent:100,duration:{d},ease:"power4.out"}},{_f(st)});')
                L.append(f'tl.fromTo("{sel}",{{filter:"blur(14px)"}},{{filter:"blur(0px)",duration:{d},ease:"power2.out"}},{_f(st)});')
            elif t == "zoom":
                L.append(f'tl.from("{sel}",{{scale:1.35,autoAlpha:0,duration:{d},ease:"power3.out"}},{_f(st)});')
            elif t == "flash":
                scene_html[-1] = scene_html[-1].replace("</div></div></div>", f'</div></div><div class="flash" id="{sid}-fl"></div></div>')
                L.append(f'tl.fromTo("#{sid}-fl",{{autoAlpha:1}},{{autoAlpha:0,duration:{_f(float(d) * 1.6)},ease:"power2.out"}},{_f(st)});')
                L.append(f'tl.from("{sel}",{{scale:1.12,duration:{d},ease:"power3.out"}},{_f(st)});')
        if i in anchors and i == shader_run[0] - 1:
            L.append(f'tl.set("#{sid}",{{opacity:1}},{_f(st)});')

        for j, p in enumerate(sc.get("popups", [])):
            pid = f"p{i + 1}_{j + 1}"
            top = {"top": "18%", "center": "44%", "bottom": "66%"}.get(p["position"], "44%")
            popup_html.append(f'<div class="pwrap" style="top:{top}"><div class="popup" id="{pid}" style="background:{p["color"]}">{html.escape(p["text"])}</div></div>')
            at, pd = p["at"], p["duration"]
            if p["style"] == "stamp":
                L.append(f'tl.fromTo("#{pid}",{{autoAlpha:0,scale:2.4,rotation:-6}},{{autoAlpha:1,scale:1,rotation:-6,duration:.2,ease:"power4.out"}},{_f(at)});')
            elif p["style"] == "slide":
                L.append(f'tl.fromTo("#{pid}",{{autoAlpha:0,y:90}},{{autoAlpha:1,y:0,duration:.3,ease:"power3.out"}},{_f(at)});')
            else:
                L.append(f'tl.fromTo("#{pid}",{{autoAlpha:0,scale:.4}},{{autoAlpha:1,scale:1,duration:.3,ease:"back.out(2.2)"}},{_f(at)});')
            L.append(f'tl.to("#{pid}",{{autoAlpha:0,scale:.9,duration:.15,ease:"power2.in"}},{_f(at + pd - .15)});')

    # captions
    style = caps.get("style", "karaoke")
    for k, c in enumerate(caps.get("chunks", []) if style != "none" else []):
        cid = f"c{k}"
        spans = "".join(f'<span class="cw" id="{cid}w{m}">{html.escape(w["w"])}</span>' for m, w in enumerate(c["words"]))
        cap_html.append(f'<div class="cap" id="{cid}">{spans}</div>')
        L.append(f'tl.set("#{cid}",{{autoAlpha:1}},{_f(c["start"])});')
        L.append(f'tl.from("#{cid}",{{scale:.85,duration:.14,ease:"back.out(2)"}},{_f(c["start"])});')
        L.append(f'tl.set("#{cid}",{{autoAlpha:0}},{_f(c["end"])});')
        if style in ("karaoke", "pop"):
            for m, w in enumerate(c["words"]):
                col = f'color:"{accent}",' if style == "karaoke" else ""
                L.append(f'tl.set("#{cid}w{m}",{{{col}scale:1.14}},{_f(w["start"])});')
                L.append(f'tl.set("#{cid}w{m}",{{color:"{text_c}",scale:1}},{_f(w["end"])});')

    # look overlays
    ov_html = ""
    if look.get("vignette"):
        ov_html += f'<div class="vig" style="background:radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,{look["vignette"]}) 100%)"></div>'
    if look.get("grain"):
        ov_html += f'<div class="grain" id="grain" style="opacity:{min(1, float(look["grain"]) * 3):.2f}"></div>'
        L.append(f'tl.fromTo("#grain",{{backgroundPosition:"0px 0px,1px 2px"}},{{backgroundPosition:"360px 240px,361px 242px",duration:{_f(total)},ease:"steps({max(2, int(total * 12))})"}},0);')
    if look.get("letterbox"):
        h = round(H * float(look["letterbox"]))
        ov_html += f'<div class="bar" style="top:0;height:{h}px"></div><div class="bar" style="bottom:0;height:{h}px"></div>'

    cap_pos = "top:44%;" if caps.get("position") == "center" else "bottom:24%;"
    cap_size = caps.get("size") or round(H * 0.058)
    shader_js = ""
    if shader_run:
        scene_ids = [f"s{i + 1}" for i in sorted(anchors)]
        trs = []
        for i in shader_run:
            tdur = max(0.3, float(scenes[i]["transition"]["dur"]))
            tdur = max(tdur, 0.5)
            trs.append(f'{{time:{_f(scenes[i]["start"] - tdur / 2)},shader:"{bounds[i]}",duration:{_f(tdur)}}}')
        shader_js = (f'window.HyperShader.init({{bgColor:"#000",scenes:{json.dumps(scene_ids)},timeline:tl,'
                     f'transitions:[{",".join(trs)}]}});')
    grade = GRADES.get(look.get("grade", "none"), "none")

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width={W}, height={H}">
<script src="vendor/gsap.min.js"></script>
<script src="vendor/hyperframe.runtime.iife.js"></script>
{'<script src="vendor/shader-transitions.js"></script>' if shader_run else ''}
{head_fonts}
<style>
{font_face}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:#000;font-family:{fam};color:{text_c}}}
.scene{{position:absolute;top:0;left:0;width:{W}px;height:{H}px;overflow:hidden}}
.scene-inner{{position:absolute;inset:0;filter:{grade}}}
.bg{{position:absolute;inset:-6%}}
.scene-content{{position:absolute;inset:0}}
.vis{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden}}
.vimg{{width:100%;height:100%}}
.shade{{position:absolute;inset:0;background:linear-gradient(to bottom,rgba(0,0,0,.18),rgba(0,0,0,0) 35%,rgba(0,0,0,.35))}}
.ktext{{width:84%;text-align:center;font-weight:900;line-height:1.08;text-transform:{uc};text-shadow:0 6px 24px rgba(0,0,0,.55)}}
.w{{display:inline-block}}
.chwrap{{position:absolute;bottom:0;display:flex}} .chwrap.left{{left:3%}} .chwrap.right{{right:3%}}
.char{{display:block}}
.flash{{position:absolute;inset:0;background:#fff;visibility:hidden}}
.pwrap{{position:absolute;left:0;right:0;display:flex;justify-content:center;z-index:40}}
.popup{{font-size:{round(H * 0.062)}px;font-weight:900;color:#111;white-space:nowrap;padding:.18em .5em;border-radius:.3em;
 box-shadow:0 10px 30px rgba(0,0,0,.45);text-transform:{uc};visibility:hidden}}
.cap{{position:absolute;left:6%;right:6%;{cap_pos}display:flex;justify-content:center;flex-wrap:wrap;z-index:45;visibility:hidden;font-size:{cap_size}px}}
.cw{{display:inline-block;margin:0 .14em;font-weight:900;color:{text_c};text-transform:{uc};
 -webkit-text-stroke:{round(cap_size * 0.11)}px #000;paint-order:stroke fill;text-shadow:0 5px 18px rgba(0,0,0,.6)}}
.vig,.grain,.bar{{position:absolute;pointer-events:none;z-index:50}}
.vig{{inset:0}}
.grain{{inset:0;mix-blend-mode:overlay;background-image:radial-gradient(rgba(255,255,255,.08) 1px,transparent 1.2px),radial-gradient(rgba(0,0,0,.18) 1px,transparent 1.2px);background-size:3px 3px,5px 5px}}
.bar{{left:0;right:0;background:#000;z-index:60}}
</style></head>
<body>
<div id="main" data-composition-id="main" data-width="{W}" data-height="{H}" data-start="0" data-duration="{_f(total)}">
{"".join(scene_html)}
{"".join(popup_html)}
{"".join(cap_html)}
{ov_html}
</div>
<script>
window.__timelines = window.__timelines || {{}};
var tl = gsap.timeline({{ paused: true }});
{chr(10).join(L)}
{shader_js}
window.__timelines["main"] = tl;
</script>
</body></html>"""
    (project / "index.html").write_text(doc, encoding="utf-8")
    return project
