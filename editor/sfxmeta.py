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
