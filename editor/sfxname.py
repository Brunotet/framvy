"""
Turn messy library paths into clean names + searchable tags.
Handles the Sonniss/UCS layout:  <Vendor - Pack Vol. N>/<CatID>_<Description>_<Creator>_<Source>.wav
  e.g. "344 Audio - Cinematic Fight Vol. 1/FGHTImpt_4 x Punch, Body 02_344 Audio.wav"
       -> category fight/impact, tags [fight, impact, punch, body, cinematic, ...]
"""
from __future__ import annotations
import re
from pathlib import Path

# UCS category ids (prefix of the file name) -> words. Partial on purpose: unknown ids fall back to the
# folder name + description, which already carry most of the meaning.
UCS_CATS = {
    "AIR": "air", "ALRM": "alarm", "AMB": "ambience", "ANML": "animal", "ARCH": "architecture", "BEEP": "beep",
    "BELL": "bell", "BIRD": "bird", "BOAT": "boat", "BOOM": "boom impact", "BRAK": "brake", "CART": "cartoon",
    "CERM": "ceremony", "CHAT": "chatter", "CLTH": "cloth", "COMM": "communication", "CRWD": "crowd",
    "DOOR": "door", "DSGN": "designed", "ELEC": "electric", "EXPL": "explosion", "FGHT": "fight",
    "FIRE": "fire", "FOLY": "foley", "FRWK": "fireworks", "GAME": "game", "GLAS": "glass", "GUN": "gun",
    "HORN": "horn", "HUMN": "human", "IMPT": "impact", "LASR": "laser", "LTHR": "leather", "MAGC": "magic",
    "MECH": "mechanism", "METL": "metal", "MOVE": "movement", "MUSC": "music", "OBJ": "object", "PAPR": "paper",
    "PLAS": "plastic", "RAIN": "rain", "ROCK": "rock", "SCIFI": "scifi", "SPRT": "sports", "SWSH": "swish",
    "TOOL": "tool", "TRNS": "transition", "VEH": "vehicle", "VOX": "voice", "WATR": "water", "WEAP": "weapon",
    "WHSH": "whoosh swoosh", "WIND": "wind", "WOOD": "wood", "ZAP": "zap",
}
UCS_SUBS = {
    "Impt": "impact hit", "Grab": "grab", "Misc": "", "Rsr": "riser", "Hit": "hit", "Whsh": "whoosh",
    "Swsh": "swish", "Pnch": "punch", "Kick": "kick", "Slap": "slap", "Drop": "drop", "Down": "downer",
    "Stng": "sting", "Bld": "build", "Gltch": "glitch", "Tmbl": "tumble", "Brk": "break", "Crsh": "crash",
    "Clik": "click", "Pop": "pop", "Ding": "ding", "Hrt": "heartbeat", "Scrm": "scream", "Gasp": "gasp",
}
STOP = {"the", "and", "of", "a", "to", "in", "on", "x", "vol", "volume", "sfx", "fx", "sound", "sounds", "effect",
        "effects", "wav", "mp3", "audio", "sonniss", "com", "gdc", "game", "bundle", "stereo", "mono", "final",
        "master", "v1", "v2", "part", "ver", "version", "take", "layer", "mix"}
_CATS_BY_LEN = sorted(UCS_CATS, key=len, reverse=True)


def _words(s: str) -> list[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)  # camelCase -> camel Case
    return re.findall(r"[a-z]+", s.lower())


def _tokens(*parts: str, vendor_words: set[str] = frozenset()) -> list[str]:
    out: list[str] = []
    for p in parts:
        for t in _words(p):
            if len(t) > 2 and t not in STOP and t not in vendor_words and t not in out:
                out.append(t)
    return out


def parse(rel_path: str) -> dict:
    """rel_path: path relative to the bundle root (folders + file name)."""
    p = Path(rel_path)
    folders = list(p.parts[:-1])
    pack_raw = folders[-1] if folders else ""
    vendor, pack = "", pack_raw
    if " - " in pack_raw:
        vendor, pack = pack_raw.split(" - ", 1)
    vendor_words = set(_words(vendor))
    stem = p.stem
    parts = stem.split("_")
    cat_words, sub_words, desc = "", "", stem
    cat_id = ""
    if len(parts) >= 2 and re.match(r"^[A-Z]{2,}[A-Za-z]*$", parts[0]):
        head = parts[0]
        for c in _CATS_BY_LEN:
            if head.startswith(c):
                cat_id = c
                cat_words = UCS_CATS[c]
                sub = head[len(c):]
                sub_words = UCS_SUBS.get(sub, " ".join(_words(sub)))
                break
        if cat_id:
            desc = parts[1]
        else:
            desc = "_".join(parts[1:2])
    elif len(parts) >= 3 and re.search(r"\d", parts[-1]) is None:
        desc = "_".join(parts[:-1])
    # clean human name: "4 x Punch, Body 02" -> "4x Punch, Body"
    name = re.sub(r"\s+\d{1,3}$", "", desc).strip()
    name = re.sub(r"\b(\d+)\s*x\b", r"\1x", name, flags=re.I)
    tags = _tokens(cat_words, sub_words, desc, pack, " ".join(folders[:-1]), vendor_words=vendor_words)
    category = "/".join(x for x in [cat_words.split()[0] if cat_words else "", sub_words.split()[0] if sub_words else ""] if x)
    return {"name": name[:90] or stem[:90], "tags": tags[:18], "category": category,
            "pack": pack.strip(), "vendor": vendor.strip()}
