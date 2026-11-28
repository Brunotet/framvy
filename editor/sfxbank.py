"""
Small, fixed sound-effect vocabulary. No network, no API keys, nothing is generated at render time.

Every file in assets/sfx/ is a CC0 (public domain) Freesound clip that was already part of this repo's old
sfx_library, trimmed, converted to mono mp3 and level-matched (about -16 dB mean, peak <= -3 dBFS) so the
volumes in hf_compose.py behave the same for every sound. Sources are listed in assets/sfx/CREDITS.json.

`resolve("heavy impact")` maps the planner's free text to a vocabulary name (or None = stay silent).
"""
from __future__ import annotations
import re
from pathlib import Path

from .config import ROOT

SFX_DIR = ROOT / "assets" / "sfx"

# name -> (file, length s, onset s, peak s, active end s, align). Volumes live in hf_compose.py (SFX_VOL), not here.
# align: "onset" = the sound starts at the cue, "peak" = its loudest moment lands on the cue,
#        "end" = the sound finishes on the cue (riser builds UP to the reveal).
VOCAB: dict[str, tuple[str, float, float, float, float, str]] = {
    "whoosh":        ("whoosh.mp3",        1.30, 0.24, 0.95, 1.24, "peak"),    # scene transitions (soft)
    "impact":        ("impact.mp3",        1.30, 0.01, 0.04, 1.24, "onset"),   # soft low thud / emphasis
    "pop":           ("pop.mp3",           0.24, 0.07, 0.09, 0.12, "onset"),   # pop-ups, small reveals
    "click":         ("click.mp3",         0.16, 0.00, 0.03, 0.13, "onset"),   # UI tap, selection
    "ding":          ("ding.mp3",          1.60, 0.04, 0.11, 0.85, "onset"),   # right answer, idea, notification
    "heartbeat":     ("heartbeat.mp3",     2.60, 0.01, 1.83, 2.48, "onset"),   # tension, fear, health
    "paper":         ("paper.mp3",         1.13, 0.26, 0.86, 0.95, "onset"),   # documents, pages, notes
    "coins":         ("coins.mp3",         1.70, 0.33, 0.50, 0.59, "onset"),   # money, savings, rewards
    "cash_register": ("cash_register.mp3", 1.45, 0.13, 0.45, 0.95, "onset"),   # sales, profit, purchase
    "shutter":       ("shutter.mp3",       0.29, 0.00, 0.18, 0.27, "onset"),   # photo, snapshot, paparazzi
    "crowd":         ("crowd.mp3",         2.50, 0.81, 0.98, 2.40, "onset"),   # crowd gasp / reaction
    "riser":         ("riser.mp3",         3.00, 0.77, 2.52, 2.82, "peak"),    # build-up that peaks on the reveal
    "buzzer":        ("buzzer.mp3",        0.60, 0.00, 0.08, 0.59, "onset"),   # wrong, error, myth busted
    "cheer":         ("cheer.mp3",         2.50, 0.10, 0.36, 2.44, "onset"),   # win, celebration, applause
}

# free text word -> vocabulary name (first match in order of the multi-word list, then single words)
PHRASES = {
    "cash register": "cash_register", "ka ching": "cash_register", "cha ching": "cash_register",
    "camera shutter": "shutter", "camera flash": "shutter", "heart beat": "heartbeat",
    "wrong answer": "buzzer", "paper rustle": "paper", "page turn": "paper", "crowd murmur": "crowd",
}
WORDS = {
    "whoosh": "whoosh", "swoosh": "whoosh", "swish": "whoosh", "swipe": "whoosh", "transition": "whoosh",
    "sweep": "whoosh", "slide": "whoosh",
    "impact": "impact", "hit": "impact", "boom": "impact", "thud": "impact", "punch": "impact", "slam": "impact",
    "drop": "impact", "bass": "impact", "stab": "impact", "braam": "impact", "bang": "impact", "heavy": "impact",
    "pop": "pop", "bubble": "pop", "blip": "pop", "plop": "pop", "appear": "pop", "reveal": "pop",
    "click": "click", "tap": "click", "tick": "click", "button": "click", "select": "click", "ui": "click",
    "ding": "ding", "bell": "ding", "chime": "ding", "ping": "ding", "notification": "ding", "success": "ding",
    "correct": "ding", "idea": "ding", "bing": "ding",
    "heartbeat": "heartbeat", "heart": "heartbeat", "pulse": "heartbeat", "tension": "heartbeat", "fear": "heartbeat",
    "nervous": "heartbeat", "suspense": "heartbeat",
    "paper": "paper", "rustle": "paper", "page": "paper", "document": "paper", "notes": "paper",
    "letter": "paper", "book": "paper",
    "coin": "coins", "coins": "coins", "money": "coins", "cash": "cash_register", "register": "cash_register",
    "sale": "cash_register", "profit": "cash_register", "purchase": "cash_register", "price": "cash_register",
    "camera": "shutter", "shutter": "shutter", "photo": "shutter", "snapshot": "shutter",
    "crowd": "crowd", "murmur": "crowd", "gasp": "crowd", "audience": "crowd", "chatter": "crowd", "shock": "crowd",
    "riser": "riser", "rise": "riser", "build": "riser", "buildup": "riser", "swell": "riser", "upward": "riser",
    "buzzer": "buzzer", "wrong": "buzzer", "error": "buzzer", "fail": "buzzer", "incorrect": "buzzer",
    "cheer": "cheer", "applause": "cheer", "clap": "cheer", "win": "cheer", "celebrate": "cheer", "victory": "cheer",
}


def resolve(query: str | None) -> str | None:
    """Planner free text -> vocabulary name, or None when nothing fits (the cue is then skipped)."""
    q = " ".join(re.findall(r"[a-z0-9]+", (query or "").lower()))
    if not q:
        return None
    if q in VOCAB:
        return q
    for ph, name in PHRASES.items():
        if ph in q:
            return name
    for tok in q.split():
        if tok in VOCAB:
            return tok
    for tok in q.split():
        if tok in WORDS:
            return WORDS[tok]
    return None


def info(name: str) -> dict | None:
    if name not in VOCAB:
        return None
    f, dur, onset, peak, end, align = VOCAB[name]
    p = SFX_DIR / f
    if not p.exists():
        return None
    return {"name": name, "path": p, "dur": dur, "onset": onset, "peak": peak, "active_end": end, "align": align,
            "license": "CC0", "source": "freesound (assets/sfx/CREDITS.json)"}
