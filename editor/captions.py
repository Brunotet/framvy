"""Word timestamps -> short caption chunks (Shorts style: 1-3 words at a time)."""
from __future__ import annotations
import re


def words_from_scenes(scenes: list[dict]) -> list[dict]:
    """Fallback when the voiceover has no word timings: spread each scene's text evenly."""
    out = []
    for s in scenes:
        toks = (s.get("text") or "").split()
        if not toks:
            continue
        dur = max(0.2, s["end"] - s["start"])
        step = dur / len(toks)
        for i, t in enumerate(toks):
            out.append({"w": t, "start": s["start"] + i * step, "end": s["start"] + (i + 1) * step})
    return out


def build_chunks(words: list[dict], max_words: int = 3, max_chars: int = 22, gap: float = 0.45) -> list[dict]:
    chunks, cur = [], []

    def flush():
        nonlocal cur
        if cur:
            chunks.append({"start": cur[0]["start"], "end": cur[-1]["end"], "words": cur})
            cur = []

    for w in words:
        if cur:
            too_long = len(" ".join(x["w"] for x in cur + [w])) > max_chars
            if len(cur) >= max_words or too_long or (w["start"] - cur[-1]["end"]) > gap:
                flush()
        cur.append({"w": w["w"], "start": float(w["start"]), "end": float(w["end"])})
        if re.search(r"[.!?,;:]$", w["w"]):
            flush()
    flush()
    # hold each chunk until the next one starts (no flicker), capped at +0.35s
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1]["start"] if i + 1 < len(chunks) else c["end"] + 0.35
        c["end"] = min(nxt, c["end"] + 0.35)
    return chunks
