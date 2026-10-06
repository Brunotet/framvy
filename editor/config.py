"""Channel profiles: defaults < channels/<name>.yaml < job.style."""
from __future__ import annotations
import copy
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_profile(channel: str, job_style: dict | None = None) -> dict:
    prof = _load(ROOT / "channels" / "default.yaml")
    if channel and channel != "default":
        prof = deep_merge(prof, _load(ROOT / "channels" / f"{channel}.yaml"))
    return deep_merge(prof, job_style or {})


ASPECTS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5), "5:4": (5, 4),
           "3:4": (3, 4), "4:3": (4, 3), "21:9": (21, 9), "2:3": (2, 3), "3:2": (3, 2)}
RES = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2k": 1440, "4k": 2160}


def _side(res) -> int:
    if res is None:
        return 1080
    if isinstance(res, (int, float)):
        return int(res)
    return RES.get(str(res).lower().strip(), int(str(res).lower().replace("p", "") or 1080))


def resolve_format(profile_fmt: dict | None, job_fmt: dict | None, aspect=None, resolution=None) -> dict:
    """Priority: job width+height > job aspect/resolution > profile. 'resolution' = length of the SHORT side."""
    pf, jf = profile_fmt or {}, job_fmt or {}
    fps = int(jf.get("fps") or pf.get("fps") or 30)
    if jf.get("width") and jf.get("height"):
        w, h = int(jf["width"]), int(jf["height"])
    else:
        asp = aspect or jf.get("aspect") or pf.get("aspect")
        res = resolution or jf.get("resolution") or pf.get("resolution")
        if asp:
            if asp not in ASPECTS:
                a, b = (int(x) for x in str(asp).split(":"))
            else:
                a, b = ASPECTS[asp]
            side = _side(res)
            w, h = (side, round(side * b / a)) if a <= b else (round(side * a / b), side)
        else:
            w, h = int(pf.get("width", 1080)), int(pf.get("height", 1920))
    return {"width": w - w % 2, "height": h - h % 2, "fps": fps}
