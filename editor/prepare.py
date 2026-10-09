"""
Turn a 'raw' job from n8n into a fully-resolved one:
  1. voiceover.script  -> narration via Chatterbox, word timestamps, scene start/end from the audio
  2. word/offset cues  -> absolute times for pop-ups and sound effects
  3. image prompts     -> generated in one go (only if the channel uses images)
"""
from __future__ import annotations
import re
from pathlib import Path

from .config import resolve_format
from .images import generate_images
from .schema import Job, Word
from .util import Ctx, probe_duration

_N = re.compile(r"[^\w']")


def _n(s: str) -> str:
    return _N.sub("", s or "").lower()


def prepare(job: Job, profile: dict, workdir: Path, ctx: Ctx) -> None:
    vo, scenes = job.voiceover, job.scenes
    assets = workdir / "assets"

    # 1) narration ------------------------------------------------------------
    if vo and vo.script and not (vo.url or vo.path):
        from .voice import narrate
        print("[prep] narrating script with Chatterbox", flush=True)
        res = narrate(vo.script, [{"text": s.text} for s in scenes], vo, assets)
        vo.path = str(res["audio_path"])
        vo.words = [Word(**w) for w in res["words"]]
        for i, (s, b) in enumerate(zip(scenes, res["beats"])):
            s.start = 0.0 if i == 0 else float(b["start"])
        for i, s in enumerate(scenes):
            s.end = scenes[i + 1].start if i + 1 < len(scenes) else None
        job.duration = max(job.duration or 0, probe_duration(Path(vo.path)) + float(profile.get("tail_seconds", 0.6)))
    else:
        for i, s in enumerate(scenes):
            if s.start is None:
                raise ValueError("scene.start is required unless voiceover.script is provided")

    # 2) relative cues -> absolute times -----------------------------------------
    words = [w.model_dump() for w in vo.words] if (vo and vo.words) else []
    for s in scenes:
        end = s.end if s.end is not None else float("inf")
        sw = [w for w in words if s.start - 0.02 <= w["start"] < end]
        for item in [*s.popups, *s.sfx]:
            if item.at is None:
                at = None
                tok = _n(item.word) if item.word else ""
                if tok:
                    for w in sw:
                        if _n(w["w"]) == tok or tok in _n(w["w"]):
                            at = w["start"]
                            break
                item.at = at if at is not None else s.start + item.offset

    # 3) images (credit-safe) ---------------------------------------------------
    feats = profile.get("features") or {}
    if feats.get("images", True):
        todo = [s for s in scenes if s.visual.type == "image" and s.visual.prompt
                and not (s.visual.url or s.visual.path)]
        if todo:
            fmt = resolve_format(profile.get("format"), job.format, job.aspect, job.resolution)
            key = lambda s: (s.visual.prompt, tuple(s.visual.characters or ()))
            got = generate_images([key(s) for s in todo], profile.get("image") or {}, workdir, ctx,
                                  (fmt["width"], fmt["height"]))
            for s in todo:
                p = got.get(key(s))
                if p:
                    s.visual.path = str(p)
    elif any(s.visual.type == "image" and s.visual.prompt for s in scenes):
        print("[prep] channel has images off: skipping image generation (no credits spent)", flush=True)
