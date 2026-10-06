"""
Narration via your Chatterbox TTS on Modal. This is the SAME get_tts / get_tts_safe / assign_timing logic
as your proven pipelines (render_pipeline.py / chatterbox_modal.py), ported so every channel shares one
implementation. Subtitles use the TTS word timestamps directly, so they stay in sync with the audio.
"""
from __future__ import annotations
import base64, difflib, os, re, time
from pathlib import Path
from typing import Optional
import requests

DEFAULT_TTS_URL = "https://simonmood123--chatterbox-tts-chatterboxservice-tts.modal.run"
_PUNCT_RE = re.compile(r"[^\w']")


def _tts_url() -> str:
    return os.environ.get("MODAL_TTS_URL") or DEFAULT_TTS_URL


def _norm_tok(tok: str) -> str:
    return _PUNCT_RE.sub("", tok).lower()


def get_tts(text, out_path: Path, voice=None, exaggeration=0.5, repetition_penalty=1.5, speed=1.0,
            exaggerations=None, pause_after_ms=None, strict_short_sentences=False) -> dict:
    payload = {"text": text, "exaggeration": exaggeration, "repetition_penalty": repetition_penalty}
    if voice:
        payload["voice"] = voice
    if speed and speed != 1.0:
        payload["speed"] = speed
    if exaggerations:
        payload["exaggerations"] = exaggerations
    if pause_after_ms:
        payload["pause_after_ms"] = pause_after_ms
    if strict_short_sentences:
        payload["strict_short_sentences"] = True
    last = None
    for attempt in range(3):  # Modal cold starts can time out once
        try:
            resp = requests.post(_tts_url(), json=payload, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise ValueError(f"Chatterbox TTS error: {data['error']}")
            break
        except Exception as ex:  # noqa
            last = ex
            print(f"[tts] attempt {attempt + 1} failed: {ex}", flush=True)
            time.sleep(4 * (attempt + 1))
    else:
        raise RuntimeError(f"TTS failed after retries: {last}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(data["audio_base64"]))
    words = data.get("words", [])
    return {"audio_path": out_path, "words": words, "duration": words[-1]["end"] if words else 10.0}


def _detect_repetition(script_text: str, words: list, min_ngram: int = 4) -> bool:
    expected = [_norm_tok(t) for t in script_text.split() if _norm_tok(t)]
    actual = [_norm_tok(w["word"]) for w in words]

    def ngrams(seq, n):
        return [tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)]

    exp_c, act_c = {}, {}
    for g in ngrams(expected, min_ngram):
        exp_c[g] = exp_c.get(g, 0) + 1
    for g in ngrams(actual, min_ngram):
        act_c[g] = act_c.get(g, 0) + 1
    return any(c > exp_c.get(g, 0) for g, c in act_c.items())


def get_tts_safe(text, out_path: Path, max_retries: int = 2, **kw) -> dict:
    result = None
    for attempt in range(max_retries + 1):
        result = get_tts(text, out_path, **kw)
        if not _detect_repetition(text, result["words"]):
            return result
        print(f"[tts] repetition artifact on attempt {attempt + 1}, retrying...", flush=True)
    print("[tts] repetition still present after retries - using last attempt", flush=True)
    return result


def assign_timing(segments: list, words: list, debug: bool = False) -> list:
    """difflib alignment of the flat word list onto segment (beat) boundaries. Unchanged from render_pipeline.py."""
    expected_tokens = []
    for seg in segments:
        for tok in seg["text"].split():
            n = _norm_tok(tok)
            if n:
                expected_tokens.append(n)
    actual_tokens = [_norm_tok(w["word"]) for w in words]
    sm = difflib.SequenceMatcher(None, expected_tokens, actual_tokens, autojunk=False)
    e2a = [None] * len(expected_tokens)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                e2a[i1 + k] = j1 + k
        elif tag == "replace":
            span_e, span_a = i2 - i1, j2 - j1
            if span_a == 0:
                continue
            for k in range(span_e):
                e2a[i1 + k] = j1 + min(k * span_a // span_e, span_a - 1)
    seg_ranges, cursor = [], 0
    for seg in segments:
        n = len([t for t in seg["text"].split() if _norm_tok(t)])
        seg_ranges.append((cursor, cursor + n - 1) if n else (cursor, cursor - 1))
        cursor += n
    result, last_end = [], 0.0
    for i, seg in enumerate(segments):
        lo, hi = seg_ranges[i]
        idxs = [e2a[k] for k in range(lo, hi + 1) if hi >= lo and e2a[k] is not None]
        if idxs:
            start, end = words[min(idxs)]["start"], words[max(idxs)]["end"]
            start = max(start, last_end)
            if end < start:
                end = start + 0.4
        else:
            start, end = last_end, last_end + 0.4
            if debug:
                print(f"[timing] beat{i} '{seg['text'][:40]}' -> no match, fallback {start:.2f}-{end:.2f}")
        result.append({**seg, "start": start, "end": end})
        last_end = end
    return result


def narrate(script: str, beats: list[dict], vo, out_dir: Path) -> dict:
    """ONE TTS call for the whole script (natural prosody, cheapest), then time every beat against it."""
    tts = get_tts_safe(
        script, out_dir / "voice.wav", voice=vo.voice, exaggeration=vo.exaggeration,
        repetition_penalty=vo.repetition_penalty, speed=vo.speed, exaggerations=vo.exaggerations,
        pause_after_ms=vo.pause_after_ms, strict_short_sentences=vo.strict_short_sentences)
    if not tts["words"]:
        raise ValueError("Chatterbox returned no word timestamps")
    timed = assign_timing(beats, tts["words"], debug=os.environ.get("DEBUG_TIMING") == "1")
    words = [{"w": w["word"], "start": float(w["start"]), "end": float(w["end"])} for w in tts["words"]]
    return {"audio_path": tts["audio_path"], "words": words, "beats": timed}
