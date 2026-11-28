"""
Compile (job + channel profile) into:
  - timeline.json  : what the browser stage renders (visuals, popups, captions, look)
  - timeline["audio"]: voice / music / speech segments / placed sound effects. HyperFrames plays ALL audio
                     itself (hf_compose.py emits the <audio> tags).
  - sfx plan       : [{path, delay, ...}] ONLY for the legacy ffmpeg mixer (editor/audio.py), used when the old
                     built-in stage renderer is the fallback
Channels choose their own ingredients: images are OPTIONAL per channel and per scene.
A scene that asks for an image but can't have one (channel has images off, download
failed) quietly becomes a kinetic-text scene, so nothing ever breaks.
"""
from __future__ import annotations
import json, re, subprocess
from pathlib import Path
from typing import Optional

from .assets import fetch, valid_image
from .captions import build_chunks, words_from_scenes
from .config import ROOT, resolve_format
from .schema import Job
from . import sfxbank
from .util import Ctx, probe_duration

MOTIONS = ["zoom_in", "pan_left", "zoom_out", "pan_right", "push", "float"]


def _character(profile: dict, scene, ctx: Ctx) -> Optional[dict]:
    spec = scene.character
    name = profile.get("character")
    if not spec or not name:
        return None
    if spec is True:
        spec = {}
    elif isinstance(spec, str):
        spec = {"pose": spec}
    man_path = ROOT / "characters" / name / "manifest.json"
    if not man_path.exists():
        ctx.warn(f"character '{name}' has no manifest; skipped")
        return None
    man = json.loads(man_path.read_text(encoding="utf-8"))
    poses = man.get("poses", {})
    pose = spec.get("pose") or man.get("default_pose") or next(iter(poses), None)
    f = poses.get(pose)
    if not f or not (man_path.parent / f).exists():
        ctx.warn(f"character '{name}' pose '{pose}' image missing; skipped")
        return None
    return {"src": (man_path.parent / f).resolve().as_uri(),
            "side": spec.get("side", man.get("side", "left")),
            "action": spec.get("action", man.get("action", "bounce")),
            "scale": spec.get("scale", man.get("scale", 0.42))}


def compile_job(job: Job, profile: dict, workdir: Path, ctx: Ctx):
    fmt = resolve_format(profile.get("format"), job.format, job.aspect, job.resolution)
    W, H, FPS = fmt["width"], fmt["height"], fmt["fps"]
    assets_dir = workdir / "assets"

    # ---- audio inputs -------------------------------------------------
    voice_path = None
    if job.voiceover and (job.voiceover.url or job.voiceover.path):
        voice_path = fetch(job.voiceover.url, job.voiceover.path, assets_dir, ctx)
        if not voice_path:
            ctx.warn("voiceover could not be fetched; rendering without it")
    voice_dur = probe_duration(voice_path) if voice_path else 0.0

    music_cfg = {**(profile.get("music") or {})}
    if job.music:
        music_cfg.update({k: v for k, v in job.music.model_dump().items() if v is not None})
    music_path = fetch(music_cfg.get("url"), music_cfg.get("path"), assets_dir, ctx) if (
        music_cfg.get("url") or music_cfg.get("path")) else None

    # ---- scene timing -------------------------------------------------
    scenes = sorted(job.scenes, key=lambda s: s.start)
    last_end = max([s.end or 0 for s in scenes] + [scenes[-1].start + 2.0])
    total = max(job.duration or 0, voice_dur, last_end)
    for i, s in enumerate(scenes):
        if s.end is None:
            s.end = scenes[i + 1].start if i + 1 < len(scenes) else total
    scenes[-1].end = max(scenes[-1].end, total)

    feats = profile.get("features") or {}
    images_on = feats.get("images", True)
    popups_on = feats.get("popups", True)
    palette = profile.get("palette") or [["#0f0c29", "#302b63"]]
    mot_default = profile.get("motion_default", "auto")
    trans_default = profile.get("transition_default", "whip")
    trans_dur = float(profile.get("transition_duration", 0.28))

    tl_scenes, sfx_cues = [], []
    sfx_cfg = profile.get("sfx") or {}
    sfx_on = sfx_cfg.get("enabled", True)
    auto = sfx_cfg.get("auto", True)
    sfx_gain = float(sfx_cfg.get("gain", 0.7))

    for i, s in enumerate(scenes):
        sid = s.id or f"s{i + 1}"
        v = s.visual
        vis = {"type": "text", "text": v.text or s.text, "motion": "none"}
        if v.type == "image":
            img = None
            if images_on:
                p = fetch(v.url, v.path, assets_dir, ctx)
                if p and valid_image(p):
                    img = p
                elif v.url or v.path:
                    ctx.warn(f"scene {sid}: image unusable -> text fallback")
            if img:
                vis = {"type": "image", "src": img.resolve().as_uri(), "fit": v.fit}
        elif v.type == "none":
            vis = {"type": "none"}
        mp = None
        if s.map and s.map.get("place") and feats.get("maps", True):
            from . import mapdata
            mi = mapdata.find(str(s.map["place"]))
            if mi is not None:
                mp = {"type": "map", "idx": mi, "place": str(s.map["place"]), "flag": bool(s.map.get("flag", True)),
                      "icons": [str(x) for x in (s.map.get("icons") or [])][:2]}
        if mp:
            vis = mp
        motion = v.motion or (mot_default if mot_default != "auto" else MOTIONS[i % len(MOTIONS)])
        if vis["type"] == "image":
            vis["motion"] = motion
            if isinstance(s.focus, dict) and s.focus.get("at") is not None:
                vis["focus"] = {"at": float(s.focus["at"]), "x": float(s.focus.get("x", 50)), "y": float(s.focus.get("y", 55)),
                                "amount": float(s.focus.get("amount", 0.16))}
        elif vis["type"] == "text":
            vis["motion"] = "none"

        trans = (s.transition or trans_default) if i > 0 else "cut"
        if vis["type"] == "map" and tl_scenes and tl_scenes[-1]["visual"]["type"] == "map":
            trans = "cut"   # the camera keeps flying from the previous country
        popups = []
        if popups_on:
            for p in s.popups:
                p_at = p.at if p.at is not None else s.start + p.offset
                popups.append({**p.model_dump(), "at": p_at, "color": p.color or profile.get("accent", "#FFD400")})
        # sound design: a soft whoosh on every non-cut scene change + AT MOST ONE content sound per scene
        # (the planner's first usable cue, else a pop for the first pop-up)
        if sfx_on and auto and i > 0 and trans != "cut":
            sfx_cues.append({"kind": "transition", "query": sfx_cfg.get("transition_query", "whoosh"),
                             "at": s.start, "scene": i, "until": s.end, "align": "peak", "gain": sfx_gain})
        if sfx_on:
            picked = None
            for c in s.sfx:
                nm = sfxbank.resolve(c.id) or sfxbank.resolve(c.query)
                if nm:
                    c_at = c.at if c.at is not None else s.start + c.offset
                    picked = {"kind": "content", "name": nm, "query": c.query or c.id, "at": c_at, "scene": i,
                              "until": s.end, "align": c.align, "gain": c.gain}
                    break
                ctx.warn(f"scene {sid}: no sound in the sfx vocabulary for '{c.query or c.id}': skipped")
            if not picked and auto and popups:
                picked = {"kind": "content", "name": "pop", "query": "pop", "at": popups[0]["at"], "scene": i,
                          "until": s.end, "align": "onset", "gain": sfx_gain}
            if picked:
                sfx_cues.append(picked)

        tl_scenes.append({
            "id": sid, "start": s.start, "end": s.end, "text": s.text,
            "bg": palette[i % len(palette)], "visual": vis,
            "transition": {"type": trans, "dur": trans_dur},
            "popups": popups, "character": _character(profile, s, ctx),
        })

    # ---- captions -----------------------------------------------------
    cap_cfg = {**(profile.get("captions") or {}), **((profile.get("captions_landscape") or {}) if W > H else {}),
               **(job.captions or {})}
    chunks = []
    if cap_cfg.get("style", "karaoke") != "none":
        words = [w.model_dump() for w in job.voiceover.words] if (job.voiceover and job.voiceover.words) else []
        if not words:
            words = words_from_scenes([{"text": s["text"], "start": s["start"], "end": s["end"]} for s in tl_scenes])
        chunks = build_chunks(words, int(cap_cfg.get("max_words", 3)), int(cap_cfg.get("max_chars", 22)))

    # ---- sound effects: vocabulary lookup + placement (no network; files live in assets/sfx) -------------
    words = [w.model_dump() for w in job.voiceover.words] if (job.voiceover and job.voiceover.words) else []
    plan, placed = [], []
    whoosh_end = {}                                   # scene index -> when its transition whoosh stops being audible
    for cue in sorted(sfx_cues, key=lambda c: (c["kind"] != "transition", c["at"])):   # whooshes first
        name = sfxbank.resolve(cue["query"]) if cue["kind"] == "transition" else cue["name"]
        m = sfxbank.info(name) if name else None
        if not m:
            continue
        at = float(cue["at"])
        if cue["kind"] == "content":
            at = max(at, whoosh_end.get(cue["scene"], 0.0))          # never stack on the transition whoosh
            for _ in range(2):                                        # never land inside a spoken word
                for w in words:
                    if w["start"] - 0.02 <= at < w["end"] - 0.05:
                        at = w["end"] + 0.03
        align = m["align"] if name in ("whoosh", "riser") else cue.get("align", "onset")
        anchor = {"peak": m["peak"], "end": m["active_end"]}.get(align, m["onset"])
        start = max(0.0, at - anchor)
        limit = float(cue["until"] or total) if cue["kind"] == "content" else total
        play = min(m["dur"], limit - start, total - start)
        if play < min(0.2, m["dur"]):
            ctx.warn(f"sfx '{name}' at {at:.2f}s dropped: not enough room before its scene/video ends")
            continue
        cut = play < m["dur"] - 1e-3
        if cue["kind"] == "transition":
            whoosh_end[cue["scene"]] = start + m["active_end"]
        placed.append({"name": name, "src": m["path"].resolve().as_uri(), "start": round(start, 3), "dur": round(play, 3),
                       "cut": cut, "scene": cue["scene"], "kind": cue["kind"]})
        plan.append({"path": str(m["path"]), "delay": start, "trim": 0.0, "play": play,
                     "fade": min(0.14, play * 0.5) if cut else 0.03, "gain": float(cue["gain"])})
        ctx.credits.append({"at": round(at, 3), "id": f"assets/sfx/{name}.mp3", "name": name, "source": m["source"],
                            "license": m["license"], "align": align, "played": round(play, 3), "cut": cut})

    audio_tl = _audio_timeline(voice_path, music_path, music_cfg, job, words, total, placed, ctx)

    theme = {k: profile.get(k) for k in ("text_color", "accent", "font_family", "font_file", "font_google", "uppercase")}
    if theme.get("font_file"):
        fp = (ROOT / theme["font_file"]) if not Path(theme["font_file"]).is_absolute() else Path(theme["font_file"])
        theme["font_file"] = fp.resolve().as_uri() if fp.exists() else None
    timeline = {
        "width": W, "height": H, "fps": FPS, "duration": total,
        "theme": theme, "look": profile.get("look") or {},
        "layout": profile.get("layout") or {}, "header": profile.get("header") or {},
        "scenes": tl_scenes,
        "captions": {**cap_cfg, "chunks": chunks},
        "audio": audio_tl,
    }
    return timeline, plan, {"voice": voice_path, "music": music_path,
                            "voice_gain": job.voiceover.gain if job.voiceover else 1.0,
                            "music_gain": float(music_cfg.get("gain", 0.14))}


def _mean_db(path: Path, seconds: float = 90.0) -> Optional[float]:
    """Mean level in dBFS via ffmpeg volumedetect (None if ffmpeg is unavailable)."""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-t", f"{seconds:.0f}", "-i", str(path), "-af", "volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=120)
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def _speech_segments(voice_path, words: list, total: float) -> list:
    """[(start, end)] where someone is talking: from word timestamps, else ffmpeg silencedetect, else the whole video."""
    segs: list = []
    if words:
        for w in sorted(words, key=lambda w: w["start"]):
            if segs and w["start"] - segs[-1][1] < 0.45:          # short gaps inside a sentence stay one segment
                segs[-1][1] = max(segs[-1][1], w["end"])
            else:
                segs.append([float(w["start"]), float(w["end"])])
        return segs
    if voice_path:
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(voice_path), "-af", "silencedetect=noise=-38dB:d=0.45",
                                "-f", "null", "-"], capture_output=True, text=True, timeout=120)
            t, sil = 0.0, []
            for line in r.stderr.splitlines():
                a = re.search(r"silence_start: (-?[\d.]+)", line)
                b = re.search(r"silence_end: ([\d.]+)", line)
                if a:
                    sil.append([max(0.0, float(a.group(1))), None])
                if b and sil and sil[-1][1] is None:
                    sil[-1][1] = float(b.group(1))
            end = probe_duration(Path(voice_path))
            for a0, b0 in sil:
                if a0 > t:
                    segs.append([t, a0])
                t = b0 if b0 is not None else end
            if t < end:
                segs.append([t, end])
            return [x for x in segs if x[1] - x[0] > 0.05]
        except Exception:
            pass
    return [[0.0, total]] if voice_path else []


def _audio_timeline(voice_path, music_path, music_cfg: dict, job, words: list, total: float, placed: list, ctx: Ctx):
    """Everything HyperFrames needs to play the sound track itself. Volumes are applied in hf_compose.py."""
    if not (voice_path or music_path or placed):
        return None
    out = {"voice": None, "music": None, "speech": _speech_segments(voice_path, words, total), "sfx": placed,
           "voice_db": None, "music_db": None, "music_gain": None}
    if voice_path:
        out["voice"] = {"src": Path(voice_path).resolve().as_uri(), "gain": float(job.voiceover.gain if job.voiceover else 1.0),
                        "dur": probe_duration(Path(voice_path))}
        out["voice_db"] = _mean_db(Path(voice_path))
    if music_path:
        out["music"] = {"src": Path(music_path).resolve().as_uri(), "dur": probe_duration(Path(music_path))}
        out["music_db"] = _mean_db(Path(music_path))
        if job.music and job.music.gain is not None:          # an explicit gain on the job wins over the automatic level
            out["music_gain"] = float(job.music.gain)
    return out


def timeline_end(scenes, total: float) -> float:
    return float(total)
