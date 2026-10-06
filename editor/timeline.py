"""
Compile (job + channel profile) into:
  - timeline.json  : what the browser stage renders (visuals, popups, captions, look)
  - sfx plan       : [(path, at, gain)] for the audio mixer
Channels choose their own ingredients: images are OPTIONAL per channel and per scene.
A scene that asks for an image but can't have one (channel has images off, download
failed) quietly becomes a kinetic-text scene, so nothing ever breaks.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from .assets import fetch, valid_image
from .captions import build_chunks, words_from_scenes
from .config import ROOT, resolve_format
from .schema import Job
from .sfx import SfxLibrary
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
        motion = v.motion or (mot_default if mot_default != "auto" else MOTIONS[i % len(MOTIONS)])
        if vis["type"] == "image":
            vis["motion"] = motion
        elif vis["type"] == "text":
            vis["motion"] = "none"

        trans = (s.transition or trans_default) if i > 0 else "cut"
        popups = []
        if popups_on:
            for p in s.popups:
                p_at = p.at if p.at is not None else s.start + p.offset
                popups.append({**p.model_dump(), "at": p_at, "color": p.color or profile.get("accent", "#FFD400")})
                if sfx_on and auto:
                    sfx_cues.append({"query": "pop", "at": p_at, "gain": sfx_gain * 0.8, "until": s.end,
                                     "dur": 0.6, "align": "onset"})
        if sfx_on and auto and i > 0 and trans != "cut":
            sfx_cues.append({"query": sfx_cfg.get("transition_query", "whoosh"),
                             "at": max(0, s.start - 0.06), "gain": sfx_gain, "until": s.end,
                             "dur": trans_dur + 0.45, "align": "onset"})
        if sfx_on:
            for c in s.sfx:
                c_at = c.at if c.at is not None else s.start + c.offset
                sfx_cues.append({"query": c.query, "id": c.id, "at": c_at, "gain": c.gain, "until": s.end,
                                 "dur": c.dur, "align": c.align})

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

    # ---- sfx resolve + sync (anchor the sound's real start/peak/end on the cue, cut to the slot) ----------
    plan = []
    if sfx_on and sfx_cues:
        lib = SfxLibrary(ctx, workdir / "sfx_cache")
        for cue in sorted(sfx_cues, key=lambda c: c["at"]):
            want = cue.get("dur")
            r = lib.resolve(query=cue.get("query"), sfx_id=cue.get("id"), want_len=want)
            if not r:
                continue
            m = r.get("meta") or {}
            onset, peak = float(m.get("onset", 0.0)), float(m.get("peak", 0.0))
            a_end = float(m.get("active_end") or m.get("duration") or 0.0)
            if a_end <= onset:
                a_end = float(m.get("duration") or onset + 1.0)
            align = cue.get("align", "onset")
            anchor = {"peak": peak, "end": a_end}.get(align, onset)
            at = float(cue["at"])
            fs = onset                                  # never play the leading silence
            delay = at - (anchor - fs)                  # video time when the file starts, so `anchor` lands on `at`
            if delay < 0:                               # would have to start before 0:00 -> skip into the file
                fs, delay = fs - delay, 0.0
            limit_abs = float(cue.get("until") or timeline_end(scenes, total))
            if align == "end":
                limit_abs = min(limit_abs, at + 0.35)
            if want:
                limit_abs = min(limit_abs, at + float(want) if align != "end" else limit_abs)
            avail = limit_abs - delay
            natural = max(0.0, a_end - fs + 0.05)
            play = min(natural, avail)
            if play < 0.05:
                ctx.warn(f"sfx '{cue.get('query') or cue.get('id')}' at {at:.2f}s dropped: its scene ends before it can play")
                continue
            fade = 0.03 if play >= natural - 1e-3 else min(0.14, play * 0.5)
            plan.append({"path": str(r["path"]), "delay": delay, "trim": fs, "play": play,
                         "fade": fade, "gain": float(cue["gain"])})
            ctx.credits.append({"at": round(at, 3), "id": r["id"], "name": r.get("name", ""), "source": r["source"],
                                "license": r["license"], "align": align, "played": round(play, 3),
                                "cut": play < natural - 1e-3})

    theme = {k: profile.get(k) for k in ("text_color", "accent", "font_family", "font_file", "font_google", "uppercase")}
    if theme.get("font_file"):
        fp = (ROOT / theme["font_file"]) if not Path(theme["font_file"]).is_absolute() else Path(theme["font_file"])
        theme["font_file"] = fp.resolve().as_uri() if fp.exists() else None
    timeline = {
        "width": W, "height": H, "fps": FPS, "duration": total,
        "theme": theme, "look": profile.get("look") or {},
        "scenes": tl_scenes,
        "captions": {**cap_cfg, "chunks": chunks},
    }
    return timeline, plan, {"voice": voice_path, "music": music_path,
                            "voice_gain": job.voiceover.gain if job.voiceover else 1.0,
                            "music_gain": float(music_cfg.get("gain", 0.14))}


def timeline_end(scenes, total: float) -> float:
    return float(total)
