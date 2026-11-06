#!/usr/bin/env python3
"""
Study a reference video so the framvy channel can reproduce its STYLE (pacing, cuts, sfx, structure).

  python analyzer/analyze.py --url <youtube url> [--video local.mp4] [--out analysis]

Outputs analysis/<video_id>/ :
  status.json        what worked / what failed (always written)
  meta.json          title, channel, duration, views ...
  cuts.json          every scene-cut timestamp + shot-length stats
  scenes.json        one row per shot: start, duration, spoken words, frame file, audio hit at the cut
  transcript.txt     [mm:ss] lines      transcript.json  words with timestamps
  audio_report.json  voice/music levels, speech pace, sfx candidates + guessed type
  frames/            one screenshot per shot (first N shots)
  sheets/            contact sheets: one image per 60 s, a frame every 2 s (6 x 5 tiles)
  sfx_clips/         short mp3 clips around detected sound-effect hits
  summary.md         human/AI readable digest of everything above

Analysis only. Nothing here republishes the source video.
"""
from __future__ import annotations
import argparse, bisect, json, math, re, shutil, subprocess, sys, traceback, wave
from pathlib import Path
import numpy as np


def _js(o):
    return o.item() if hasattr(o, "item") else str(o)


_dumps = json.dumps
json.dumps = lambda *a, **k: _dumps(*a, **{"default": _js, **k})


# ----------------------------------------------------------------------------- helpers
def sh(cmd, check=True):
    return subprocess.run([str(c) for c in cmd], check=check, capture_output=True, text=True)


def video_id(url: str) -> str:
    m = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else re.sub(r"\W+", "_", url)[-16:]


def mmss(t: float) -> str:
    t = max(0, float(t))
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def probe_duration(path: Path) -> float:
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], check=False)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ----------------------------------------------------------------------------- download
CLIENTS = [None, "tv", "mweb", "web_safari", "android_vr", "ios"]


def download(url: str, work: Path, cookies: Path | None, status: dict) -> Path | None:
    work.mkdir(parents=True, exist_ok=True)
    errors = []
    for client in CLIENTS:
        for f in work.glob("video.*"):
            f.unlink()
        cmd = ["yt-dlp", "--no-playlist", "--no-warnings",
               "-f", "bv*[height<=720]+ba/b[height<=720]/b",
               "--merge-output-format", "mp4", "--write-info-json",
               "-o", work / "video.%(ext)s"]
        if cookies and cookies.exists():
            cmd += ["--cookies", cookies]
        if client:
            cmd += ["--extractor-args", f"youtube:player_client={client}"]
        cmd.append(url)
        r = sh(cmd, check=False)
        vids = [p for p in work.glob("video.*") if p.suffix in (".mp4", ".mkv", ".webm")]
        if r.returncode == 0 and vids:
            status["download"] = {"ok": True, "client": client or "default"}
            return vids[0]
        errors.append({"client": client or "default", "error": (r.stderr or r.stdout)[-500:]})
    status["download"] = {"ok": False, "attempts": errors}
    return None


def read_meta(work: Path, url: str, vid: str) -> dict:
    meta = {"id": vid, "url": f"https://youtu.be/{vid}"}
    info = work / "video.info.json"
    if info.exists():
        d = json.loads(info.read_text(encoding="utf-8"))
        for k in ("title", "channel", "uploader", "duration", "view_count", "like_count", "comment_count",
                  "upload_date", "categories", "tags", "chapters", "width", "height", "fps", "channel_follower_count"):
            if d.get(k) is not None:
                meta[k] = d[k]
        meta["description"] = (d.get("description") or "")[:1500]
    else:  # oEmbed usually still works from cloud IPs
        try:
            import urllib.request
            q = f"https://www.youtube.com/oembed?url=https://youtu.be/{vid}&format=json"
            with urllib.request.urlopen(q, timeout=20) as r:
                o = json.loads(r.read())
            meta.update(title=o.get("title"), channel=o.get("author_name"))
        except Exception as ex:  # noqa
            meta["oembed_error"] = str(ex)[:200]
    return meta


# ----------------------------------------------------------------------------- cuts + frames
def detect_cuts(video: Path, thr: float, duration: float) -> list[float]:
    r = sh(["ffmpeg", "-hide_banner", "-i", video, "-vf", f"scale=320:-2,select='gt(scene,{thr})',showinfo",
            "-an", "-f", "null", "-"], check=False)
    ts = sorted(float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr))
    cuts = [0.0]
    for t in ts:
        if t - cuts[-1] >= 0.12 and (duration <= 0 or t < duration - 0.05):
            cuts.append(round(t, 3))
    return cuts


def shot_stats(lengths: list[float]) -> dict:
    if not lengths:
        return {}
    a = np.array(lengths)
    return {"shots": len(a), "mean_s": round(float(a.mean()), 2), "median_s": round(float(np.median(a)), 2),
            "p10_s": round(float(np.percentile(a, 10)), 2), "p90_s": round(float(np.percentile(a, 90)), 2),
            "min_s": round(float(a.min()), 2), "max_s": round(float(a.max()), 2)}


def grab_frames(video: Path, scenes: list[dict], out: Path, max_shots: int, from_sec: float):
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in scenes:
        if s["start"] < from_sec:
            continue
        if n >= max_shots:
            break
        t = s["start"] + min(0.25, s["dur"] * 0.5)
        name = f"s{s['i']:03d}_{t:07.2f}.jpg"
        r = sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                "-vf", "scale=540:-2", "-q:v", "4", out / name], check=False)
        if r.returncode == 0 and (out / name).exists():
            s["frame"] = name
            n += 1


def contact_sheets(video: Path, duration: float, out: Path, max_windows: int):
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for w in range(0, int(min(duration, max_windows * 60)), 60):
        name = f"sheet_{w // 60:02d}.jpg"
        r = sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", w, "-t", 60, "-i", video,
                "-vf", "fps=1/2,scale=270:-2,tile=6x5:padding=4:margin=4:color=black",
                "-frames:v", "1", "-q:v", "5", out / name], check=False)
        if r.returncode == 0 and (out / name).exists():
            made.append(name)
    return made


# ----------------------------------------------------------------------------- transcript
def transcribe(video: Path, model_size: str):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(video), word_timestamps=True, vad_filter=True, beam_size=1)
    segments, words = [], []
    for s in segs:
        segments.append({"start": round(float(s.start), 2), "end": round(float(s.end), 2), "text": s.text.strip()})
        for w in (s.words or []):
            words.append({"w": w.word.strip(), "start": round(float(w.start), 2), "end": round(float(w.end), 2)})
    return {"language": info.language, "segments": segments, "words": words}


def fallback_transcript(vid: str):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        t = api.fetch(vid)
        segs = [{"start": round(x.start, 2), "end": round(x.start + x.duration, 2), "text": x.text} for x in t]
        return {"language": "?", "segments": segs, "words": []}
    except Exception as ex:  # noqa
        return {"error": str(ex)[:300]}


# ----------------------------------------------------------------------------- audio
def extract_wav(video: Path, wav: Path, sr: int = 22050):
    wav.parent.mkdir(parents=True, exist_ok=True)
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vn", "-ac", "1", "-ar", sr, "-c:a", "pcm_s16le", wav])


def read_wav(path: Path):
    with wave.open(str(path)) as w:
        sr, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


def frame_features(x: np.ndarray, sr: int, n_fft=1024, hop=256):
    """Chunked STFT -> per-frame rms(dB), hf spectral flux, centroid, flatness, frame time."""
    win = np.hanning(n_fft).astype(np.float32)
    n = 1 + max(0, (len(x) - n_fft) // hop)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    hf = freqs >= 1500
    band = (freqs >= 100) & (freqs <= 10000)
    rms, flux, cent, flat = (np.zeros(n, np.float32) for _ in range(4))
    prev = None
    CH = 1500
    for a in range(0, n, CH):
        b = min(n, a + CH)
        idx = hop * np.arange(a, b)[:, None] + np.arange(n_fft)[None, :]
        fr = x[idx] * win
        mag = np.abs(np.fft.rfft(fr, axis=1)) + 1e-7
        lg = 20 * np.log10(mag)
        rms[a:b] = 20 * np.log10(np.sqrt((x[idx] ** 2).mean(axis=1)) + 1e-7)
        d = np.diff(lg, axis=0, prepend=(prev if prev is not None else lg[:1]))
        flux[a:b] = np.maximum(d, 0)[:, hf].sum(axis=1)
        cent[a:b] = (mag * freqs[None, :]).sum(axis=1) / mag.sum(axis=1)
        mb = mag[:, band]
        flat[a:b] = np.exp(np.log(mb).mean(axis=1)) / mb.mean(axis=1)
        prev = lg[-1:]
    t = (hop * np.arange(n) + n_fft / 2) / sr
    return t, rms, flux, cent, flat


def merge_speech(words: list[dict], pad=0.06, gap=0.25) -> list[list[float]]:
    iv = []
    for w in words:
        s, e = w["start"] - pad, w["end"] + pad
        if iv and s - iv[-1][1] <= gap:
            iv[-1][1] = max(iv[-1][1], e)
        else:
            iv.append([s, e])
    return iv


def in_speech(t: float, iv: list[list[float]]) -> bool:
    i = bisect.bisect_right([a for a, _ in iv], t) - 1
    return bool(i >= 0 and iv[i][0] <= t <= iv[i][1])


def guess_kind(dur, cent, flat, peak_db, strength, speech):
    if speech and not (strength >= 2.5 and flat > 0.2):
        return "voice onset (ignore)"
    if dur < 0.18 and cent > 2500:
        return "click/pop"
    if flat > 0.25 and 0.2 <= dur <= 1.1:
        return "whoosh/swipe (noise sweep)"
    if cent < 900 and dur > 0.35:
        return "boom/impact"
    if flat < 0.08 and cent > 1800 and dur > 0.35:
        return "ding/chime (tonal)"
    return "other transient"


def audio_analysis(video: Path, wav: Path, words: list[dict], cuts: list[float], clips_dir: Path, max_clips: int):
    extract_wav(video, wav)
    x, sr = read_wav(wav)
    t, rms, flux, cent, flat = frame_features(x, sr)
    hop_s = float(t[1] - t[0]) if len(t) > 1 else 0.0116
    iv = merge_speech(words)

    k = np.ones(3) / 3
    f = np.convolve(flux, k, mode="same")
    thr = max(float(np.percentile(f, 96)), float(f.mean() + 2 * f.std()), 1e-6)
    w = max(1, int(0.07 / hop_s))
    onsets = []
    for i in range(w, len(f) - w):
        if f[i] > thr and f[i] == f[i - w:i + w + 1].max() and (not onsets or t[i] - onsets[-1]["t"] >= 0.12):
            j0, j1 = i, min(len(t), i + int(0.3 / hop_s))
            peak_db = float(rms[j0:j1].max())
            tail_end = min(len(t), i + int(1.2 / hop_s))
            seg = rms[i:tail_end]
            below = np.where(seg < peak_db - 20)[0]
            dur = float((below[0] if len(below) else len(seg)) * hop_s)
            q = slice(i, min(len(t), i + int(0.25 / hop_s)))
            c, fl = float(np.median(cent[q])), float(np.median(flat[q]))
            sp = in_speech(float(t[i]), iv) if iv else False
            strength = float(f[i] / thr)
            onsets.append({"t": round(float(t[i]), 2), "strength": round(strength, 2), "peak_db": round(peak_db, 1),
                           "decay_s": round(dur, 2), "centroid_hz": int(c), "flatness": round(fl, 3),
                           "during_speech": sp, "guess": guess_kind(dur, c, fl, peak_db, strength, sp)})

    # hit at each cut
    hits = {}
    ot = [o["t"] for o in onsets]
    for ci, c in enumerate(cuts):
        if ci == 0:
            continue
        lo, hi = bisect.bisect_left(ot, c - 0.15), bisect.bisect_right(ot, c + 0.30)
        cand = [o for o in onsets[lo:hi] if not o["guess"].startswith("voice")]
        if cand:
            b = max(cand, key=lambda o: o["strength"])
            hits[ci] = {"offset_s": round(b["t"] - c, 2), "strength": b["strength"], "guess": b["guess"]}

    # speech / gap levels (music bed estimate)
    speech_mask = np.zeros(len(t), bool)
    for a, b in iv:
        speech_mask[(t >= a) & (t <= b)] = True
    gap_mask = ~speech_mask
    sp_db = float(np.median(rms[speech_mask])) if speech_mask.any() else None
    gp_db = float(np.median(rms[gap_mask])) if gap_mask.any() else None
    gp_flat = float(np.median(flat[gap_mask])) if gap_mask.any() else None

    # pace
    pace = {}
    if words:
        dur_s = max(words[-1]["end"] - words[0]["start"], 1)
        pauses = [words[i + 1]["start"] - words[i]["end"] for i in range(len(words) - 1)]
        pace = {"words": len(words), "words_per_min": round(len(words) / dur_s * 60),
                "pauses_over_0.35s": int(sum(p > 0.35 for p in pauses)),
                "median_pause_s": round(float(np.median(pauses)), 2) if pauses else None}

    # sfx candidates -> clips
    cands = [o for o in onsets if (not o["during_speech"]) or (o["strength"] >= 2.5 and o["flatness"] > 0.2)]
    cands = [o for o in cands if not o["guess"].startswith("voice")]
    cands = sorted(cands, key=lambda o: -o["strength"])[:max_clips]
    cands.sort(key=lambda o: o["t"])
    clips_dir.mkdir(parents=True, exist_ok=True)
    for n, o in enumerate(cands, 1):
        name = f"{n:02d}_t{o['t']:07.2f}_{re.sub(r'[^a-z]+', '-', o['guess'].lower()).strip('-')}.mp3"
        r = sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0, o['t'] - 0.15):.3f}", "-t", "1.6", "-i", video,
                "-vn", "-ac", "1", "-b:a", "64k", clips_dir / name], check=False)
        if r.returncode == 0:
            o["clip"] = name

    report = {
        "levels": {"speech_rms_db": None if sp_db is None else round(sp_db, 1),
                   "gap_rms_db": None if gp_db is None else round(gp_db, 1),
                   "gap_flatness": None if gp_flat is None else round(gp_flat, 3),
                   "music_or_ambience_bed_likely": bool(gp_db is not None and gp_db > -45),
                   "bed_below_voice_db": None if (sp_db is None or gp_db is None) else round(sp_db - gp_db, 1)},
        "pace": pace,
        "onset_threshold": round(thr, 2),
        "onsets_total": len(onsets),
        "cuts_with_audio_hit": len(hits),
        "cuts_total": max(0, len(cuts) - 1),
        "hit_offsets_median_s": round(float(np.median([h["offset_s"] for h in hits.values()])), 2) if hits else None,
        "sfx_candidates": cands,
    }
    return report, hits


# ----------------------------------------------------------------------------- summary
def build_summary(meta, stats, scenes, report, sheets, transcript, status) -> str:
    L = [f"# {meta.get('title', meta['id'])}", "",
         f"- id: `{meta['id']}`  channel: {meta.get('channel', '?')}  duration: {meta.get('duration', '?')}s  "
         f"views: {meta.get('view_count', '?')}  upload: {meta.get('upload_date', '?')}",
         f"- status: {json.dumps(status)[:400]}", ""]
    if stats:
        L += ["## Cuts", f"- {json.dumps(stats)}"]
        buckets: dict[int, int] = {}
        for s in scenes:
            buckets[int(s['start'] // 10)] = buckets.get(int(s['start'] // 10), 0) + 1
        L.append("- cuts per 10 s window: " + " ".join(f"{k * 10}s:{v}" for k, v in sorted(buckets.items())[:30]))
        wps = [len(s.get("text", "").split()) for s in scenes if s.get("text") is not None]
        if wps:
            L.append(f"- words spoken per shot: mean {np.mean(wps):.1f}, median {np.median(wps):.0f}")
        L.append("")
    if report:
        L += ["## Audio", f"- levels: {json.dumps(report['levels'])}", f"- pace: {json.dumps(report['pace'])}",
              f"- cuts with an audio hit near the cut: {report['cuts_with_audio_hit']} / {report['cuts_total']} "
              f"(median offset {report['hit_offsets_median_s']} s)",
              f"- sfx candidates saved as clips: {len(report['sfx_candidates'])}", ""]
        kinds: dict[str, int] = {}
        for o in report["sfx_candidates"]:
            kinds[o["guess"]] = kinds.get(o["guess"], 0) + 1
        L += ["- guessed sfx types: " + json.dumps(kinds), ""]
    if sheets:
        L += ["## Contact sheets", "One file per 60 s, 6 columns x 5 rows, one frame every 2 s (read left-to-right, top-to-bottom).",
              ", ".join(sheets), ""]
    L += ["## First shots", "| # | start | dur | words | audio hit | frame |", "|---|---|---|---|---|---|"]
    for s in scenes[:80]:
        h = s.get("audio_hit")
        ht = f"{h['guess']} ({h['offset_s']:+}s, x{h['strength']})" if h else ""
        L.append(f"| {s['i']} | {mmss(s['start'])} | {s['dur']:.2f} | {(s.get('text') or '')[:70]} | {ht} | {s.get('frame', '')} |")
    return "\n".join(L)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--video", default="", help="analyse a local file instead of downloading")
    ap.add_argument("--out", default="analysis")
    ap.add_argument("--work", default="workdir")
    ap.add_argument("--cookies", default="cookies.txt")
    ap.add_argument("--cut-threshold", type=float, default=0.25)
    ap.add_argument("--max-shots", type=int, default=80)
    ap.add_argument("--from-sec", type=float, default=0.0)
    ap.add_argument("--max-sheets", type=int, default=10)
    ap.add_argument("--max-clips", type=int, default=40)
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--skip-transcribe", action="store_true")
    a = ap.parse_args()

    vid = video_id(a.url) if a.url else Path(a.video).stem
    out = Path(a.out) / vid
    work = Path(a.work) / vid
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    status: dict = {"video_id": vid}

    def stage(name, fn):
        try:
            return fn()
        except Exception as ex:  # noqa
            status[name] = {"ok": False, "error": f"{type(ex).__name__}: {ex}"[:400]}
            traceback.print_exc()
            return None

    video = Path(a.video) if a.video else download(a.url, work, Path(a.cookies), status)
    meta = read_meta(work, a.url, vid)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if not video:
        tr = fallback_transcript(vid)
        status["fallback_transcript"] = "error" not in tr
        if "error" not in tr:
            (out / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
            (out / "transcript.txt").write_text("\n".join(f"[{mmss(s['start'])}] {s['text']}" for s in tr["segments"]), encoding="utf-8")
        else:
            status["fallback_transcript_error"] = tr["error"]
        status["result"] = "download_failed"
        (out / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        print(json.dumps(status, indent=2))
        return 0

    duration = probe_duration(video) or float(meta.get("duration") or 0)
    meta["duration"] = round(duration, 2)

    cuts = stage("cuts", lambda: detect_cuts(video, a.cut_threshold, duration)) or [0.0]
    ends = cuts[1:] + [duration]
    scenes = [{"i": i + 1, "start": round(s, 3), "dur": round(max(e - s, 0.01), 3)} for i, (s, e) in enumerate(zip(cuts, ends))]
    stats = shot_stats([s["dur"] for s in scenes])
    status["cuts"] = {"ok": True, "count": len(scenes)}
    (out / "cuts.json").write_text(json.dumps({"threshold": a.cut_threshold, "cuts": cuts, "stats": stats}, indent=1), encoding="utf-8")

    stage("frames", lambda: grab_frames(video, scenes, out / "frames", a.max_shots, a.from_sec))
    sheets = stage("sheets", lambda: contact_sheets(video, duration, out / "sheets", a.max_sheets)) or []

    tr = None
    if not a.skip_transcribe:
        tr = stage("transcript", lambda: transcribe(video, a.whisper_model))
    if tr:
        status["transcript"] = {"ok": True, "language": tr["language"], "words": len(tr["words"])}
        (out / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
        (out / "transcript.txt").write_text("\n".join(f"[{mmss(s['start'])}] {s['text']}" for s in tr["segments"]), encoding="utf-8")
        starts = [s["start"] for s in scenes]
        for s in scenes:
            s["text"] = ""
        for w in tr["words"]:
            i = max(0, bisect.bisect_right(starts, w["start"]) - 1)
            scenes[i]["text"] = (scenes[i]["text"] + " " + w["w"]).strip()

    report, hits = None, {}
    res = stage("audio", lambda: audio_analysis(video, work / "audio.wav", (tr or {}).get("words", []), cuts, out / "sfx_clips", a.max_clips))
    if res:
        report, hits = res
        status["audio"] = {"ok": True, "onsets": report["onsets_total"], "sfx_clips": len(report["sfx_candidates"])}
        (out / "audio_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        for ci, h in hits.items():
            scenes[ci]["audio_hit"] = h  # cut index ci == start of scene index ci

    (out / "scenes.json").write_text(json.dumps(scenes, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    status["result"] = "ok"
    (out / "summary.md").write_text(build_summary(meta, stats, scenes, report, sheets, tr, status), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
