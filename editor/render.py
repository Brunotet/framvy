"""Render the timeline in headless Chromium (frame-exact) and pipe frames into ffmpeg."""
from __future__ import annotations
import subprocess
from pathlib import Path
from .util import run

WEB = Path(__file__).resolve().parent / "web"


def render_frames(timeline: dict, silent_mp4: Path):
    from playwright.sync_api import sync_playwright
    W, H, FPS = timeline["width"], timeline["height"], timeline["fps"]
    n = max(1, round(timeline["duration"] * FPS))
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-vcodec", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(silent_mp4)],
        stdin=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--allow-file-access-from-files", "--font-render-hinting=none",
                                              "--disable-gpu", "--no-sandbox"])
            page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            page.goto((WEB / "stage.html").as_uri())
            page.evaluate("tl => window.initStage(tl)", timeline)
            for i in range(n):
                page.evaluate("t => window.seek(t)", i / FPS)
                ff.stdin.write(page.screenshot(type="jpeg", quality=92))
                if i and i % (FPS * 5) == 0:
                    print(f"  rendered {i}/{n} frames", flush=True)
            browser.close()
    finally:
        try:
            ff.stdin.close()
        except Exception:
            pass
        rc = ff.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg frame encode failed (rc={rc})")


def mux(silent_mp4: Path, audio: Path, out: Path, duration: float):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent_mp4), "-i", str(audio),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out)])


def render_hyperframes(timeline: dict, project: Path, out_mp4: Path):
    """Render with HyperFrames (Apache-2.0 CLI, headless Chrome + FFmpeg)."""
    import os
    from . import hf_compose
    from .config import ROOT
    if not hf_compose.available():
        raise RuntimeError("HyperFrames not installed (run `npm install` in the repo root)")
    hf_compose.build(timeline, project)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cli = ROOT / "node_modules" / ".bin" / "hyperframes"
    cmd = [str(cli), "render", str(project), "-o", str(out_mp4.resolve()), "--fps", str(timeline["fps"]),
           "--quality", os.environ.get("HF_QUALITY", "looks"), "--quiet"]
    env = dict(os.environ)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    if r.returncode != 0 or not out_mp4.exists():
        raise RuntimeError(f"hyperframes render failed (rc={r.returncode}): {(r.stderr or r.stdout)[-800:]}")
