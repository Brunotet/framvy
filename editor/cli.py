"""
python -m editor.cli --job job.json [--out out] [--dry-run]
  --job       path or URL of the job JSON         --job-json  inline JSON string
  --dry-run   compile + mix audio, skip frame render and upload (fast validation)
"""
from __future__ import annotations
import argparse, json, shutil, sys, traceback
from pathlib import Path

import requests

from .audio import mix_audio
from .config import load_profile
from .prepare import prepare
from .publish import callback, upload_video
from .schema import Job
from .timeline import compile_job
from .util import Ctx


def _load_job(args) -> dict:
    if args.job_json:
        return json.loads(args.job_json)
    if args.job.startswith(("http://", "https://")):
        r = requests.get(args.job, timeout=30)
        r.raise_for_status()
        return r.json()
    return json.loads(Path(args.job).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job")
    ap.add_argument("--job-json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--workdir", default="workdir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--engine", choices=["hyperframes", "stage"], help="override the profile's render engine")
    args = ap.parse_args(argv)
    if not (args.job or args.job_json):
        ap.error("need --job or --job-json")

    raw = _load_job(args)
    ctx = Ctx(str(raw.get("job_id", "job")))
    result = {"job_id": ctx.job_id, "status": "error", "video_url": None, "video_path": None}
    try:
        job = Job.model_validate(raw)
        ctx.job_id = job.job_id
        profile = load_profile(job.channel, job.style)
        out_dir = Path(args.out) / job.job_id
        work = Path(args.workdir) / job.job_id
        for d in (out_dir, work):
            d.mkdir(parents=True, exist_ok=True)

        print(f"[1/4] preparing job (narration, images, cue timing) channel={job.channel}", flush=True)
        prepare(job, profile, work, ctx)
        print("[1/4] compiling timeline", flush=True)
        timeline, sfx_plan, aud = compile_job(job, profile, work, ctx)
        result.update(width=timeline["width"], height=timeline["height"], fps=timeline["fps"])
        (out_dir / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")

        print(f"[2/4] mixing audio ({len(sfx_plan)} sfx)", flush=True)
        audio = mix_audio(work / "mix.wav", timeline["duration"], aud["voice"], aud["music"],
                          aud["voice_gain"], aud["music_gain"], sfx_plan)

        if args.dry_run:
            shutil.copy(audio, out_dir / "mix.wav")
            result.update(status="dry-run-ok", duration=timeline["duration"])
        else:
            from .render import mux, render_frames, render_hyperframes
            silent = work / "silent.mp4"
            engine = args.engine or profile.get("engine", "hyperframes")
            used = engine
            if engine == "hyperframes":
                print("[3/4] rendering with HyperFrames", flush=True)
                try:
                    render_hyperframes(timeline, work / "hf", silent)
                except Exception as ex:  # noqa
                    if not profile.get("engine_fallback", True):
                        raise
                    ctx.warn(f"HyperFrames failed, used built-in renderer instead: {str(ex)[:300]}")
                    used = "stage"
                    render_frames(timeline, silent)
            else:
                print("[3/4] rendering with the built-in stage renderer", flush=True)
                render_frames(timeline, silent)
            result["engine"] = used
            fname = (job.output.get("filename") or f"{job.job_id}.mp4")
            final = out_dir / fname
            mux(silent, audio, final, timeline["duration"])
            result.update(status="ok", video_path=str(final), duration=timeline["duration"])
            if job.output.get("upload", True):
                print("[4/4] publishing", flush=True)
                result["video_url"] = upload_video(final, f"videos/{job.channel}/{fname}", ctx)
        (out_dir / "credits.json").write_text(json.dumps(ctx.credits, indent=2), encoding="utf-8")
    except Exception as ex:  # noqa
        traceback.print_exc()
        result["error"] = f"{type(ex).__name__}: {ex}"
    if raw.get("meta") is not None:
        result["meta"] = raw["meta"]          # passthrough so n8n knows which job finished
    result["warnings"] = ctx.warnings
    result["sfx_used"] = len(ctx.credits)
    try:
        Path(args.out, ctx.job_id).mkdir(parents=True, exist_ok=True)
        Path(args.out, ctx.job_id, "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(result, indent=2))
    callback(raw.get("callback_url"), result, ctx)
    return 0 if result["status"] in ("ok", "dry-run-ok") else 1


if __name__ == "__main__":
    sys.exit(main())
