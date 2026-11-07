"""Measure WHEN a sound actually happens inside its file (leading silence, loudest hit, real end)."""
from __future__ import annotations
import json, subprocess
from pathlib import Path


def analyze(path: Path) -> dict:
    """Returns seconds: onset (first audible moment), peak (loudest 10 ms window), active_end, duration."""
    import numpy as np
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000",
                              "-f", "s16le", "-"], capture_output=True, check=True).stdout
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        return {"onset": 0.0, "peak": 0.0, "active_end": 0.0, "duration": 0.0}
    dur = len(x) / 8000.0
    win = 80  # 10 ms
    n = len(x) // win
    if n < 2:
        return {"onset": 0.0, "peak": 0.0, "active_end": dur, "duration": dur}
    env = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1))
    top = float(env.max())
    if top < 1e-4:
        return {"onset": 0.0, "peak": 0.0, "active_end": dur, "duration": dur}
    thr = top * 0.08                      # relative to this sound's own loudness (works for very quiet files too)
    idx = np.where(env >= thr)[0]
    if idx.size == 0:
        return {"onset": 0.0, "peak": round(float(env.argmax() * 0.01), 3), "active_end": dur, "duration": dur}
    onset = max(0.0, idx[0] * 0.01 - 0.01)
    return {"onset": round(float(onset), 3), "peak": round(float(env.argmax() * 0.01), 3),
            "active_end": round(float((idx[-1] + 1) * 0.01), 3), "duration": round(dur, 3)}


def cached(path: Path, cache_dir: Path) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / (path.name + ".json")
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    m = analyze(path)
    f.write_text(json.dumps(m))
    return m


def loudness(path: Path, start: float, dur: float) -> dict:
    """Perceived level of the part of the file that will actually play.
    rms_db = power average of the 50 ms frames within 18 dB of the loudest one (ignores tails/silence),
    peak_db = absolute sample peak. Returns {} if it cannot be measured."""
    import numpy as np
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.05, dur):.3f}",
                              "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             capture_output=True, check=True).stdout
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        return {}
    if x.size < 800:
        return {}
    peak = float(np.abs(x).max())
    if peak < 1e-5:
        return {}
    win = 800
    n = max(1, len(x) // win)
    p = (x[: n * win].reshape(n, win) ** 2).mean(axis=1) if len(x) >= win else np.array([float((x ** 2).mean())])
    top = float(p.max())
    act = p[p >= top * 10 ** (-1.8)]
    rms = float(np.sqrt(act.mean()))
    return {"rms_db": 20 * np.log10(max(rms, 1e-6)), "peak_db": 20 * np.log10(peak)}


def norm_gain_db(m: dict, target_db: float = -21.0, peak_ceiling_db: float = -2.0,
                 lo: float = -20.0, hi: float = 24.0) -> float:
    """dB to add so every effect lands at the same perceived level: loud ones are pulled down,
    quiet ones pushed up, never past the peak ceiling (so boosting can't clip)."""
    if not m:
        return 0.0
    g = target_db - m["rms_db"]
    g = min(g, peak_ceiling_db - m["peak_db"])
    return max(lo, min(hi, g))
