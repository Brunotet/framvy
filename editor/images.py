"""
Batch image generation against your Qwen Image 2.1 Modal endpoint, built to protect your credits:
  - dedupes identical prompts and caches by prompt hash
  - nothing is generated for channels with images off, or for scenes that already have an image
  - with image.batch_url set (the NEW `generate_images` Modal endpoint): all images go out in chunks of
    image.batch_size per request, each chunk rendered back-to-back on ONE warm GPU container
  - otherwise sequential single calls that reuse the same warm container (image.max_parallel stays 1:
    parallel calls can spin up extra billed containers)
  - images are requested at a size that matches the video's aspect ratio (no ugly square crops for 9:16)
  - tolerant of unknown response shapes (raw image bytes, base64 anywhere in the JSON, or image URLs)
"""
from __future__ import annotations
import base64, hashlib, io, os, re, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator, Optional
import requests

from .util import Ctx

DEFAULT_URL = "https://creatyoasis--qwen-image-2-1-generate-image.modal.run"
_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8")


# Qwen-Image's native resolution buckets (w, h). The nearest one to the video's aspect ratio is requested.
NATIVE_SIZES = [(1328, 1328), (1664, 928), (928, 1664), (1472, 1104), (1104, 1472), (1584, 1056), (1056, 1584)]


def native_size(width: int, height: int) -> tuple[int, int]:
    import math
    target = math.log(width / height)
    return min(NATIVE_SIZES, key=lambda wh: abs(math.log(wh[0] / wh[1]) - target))


def _is_image(b: bytes) -> bool:
    return b[:4] in _MAGIC or b[:2] == b"\xff\xd8"


def _walk(o) -> Iterator[bytes]:
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("error", "message") and isinstance(v, str) and k == "error":
                raise ValueError(f"image endpoint error: {v[:300]}")
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)
    elif isinstance(o, str):
        s = o.strip()
        if s.startswith("http") and re.search(r"\.(png|jpe?g|webp)(\?|$)", s, re.I):
            r = requests.get(s, timeout=120)
            r.raise_for_status()
            yield r.content
        elif len(s) > 200:
            s = s.split(",", 1)[1] if s.startswith("data:") and "," in s else s
            try:
                b = base64.b64decode(s, validate=False)
                if _is_image(b):
                    yield b
            except Exception:
                pass


def _extract(resp: requests.Response) -> list[bytes]:
    if resp.headers.get("content-type", "").startswith("image/") or _is_image(resp.content[:8]):
        return [resp.content]
    try:
        data = resp.json()
    except Exception:
        raise ValueError(f"unrecognised image response: {resp.text[:200]}")
    imgs = list(_walk(data))
    if not imgs:
        raise ValueError(f"no image found in response: {str(data)[:300]}")
    return imgs


def _post(url: str, body: dict, cfg: dict) -> list[bytes]:
    last = None
    for attempt in range(int(cfg.get("retries", 2)) + 1):
        try:
            r = requests.post(url, json=body, timeout=int(cfg.get("timeout", 900)))
            r.raise_for_status()
            return _extract(r)
        except Exception as ex:  # noqa
            last = ex
            print(f"[image] attempt {attempt + 1} failed: {str(ex)[:200]}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(str(last))


def _save(b: bytes, path: Path) -> bool:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(b))
        im.load()
        path.parent.mkdir(parents=True, exist_ok=True)
        im.convert("RGB").save(path, quality=93)
        return True
    except Exception:
        return False


def generate_images(items, cfg: dict, workdir: Path, ctx: Ctx, size: Optional[tuple] = None) -> dict:
    """
    items: list of "prompt" strings OR (prompt, (character names...)) tuples.
    Returns {item: Path}. The key is exactly the item you passed in (a tuple for tuples).
    Scenes with the same characters are sent together (character_names applies to a whole batch).
    """
    url = os.environ.get("QWEN_IMAGE_URL") or cfg.get("url") or DEFAULT_URL
    steps = int(cfg.get("steps", 40))
    pre, suf = cfg.get("prompt_prefix") or "", cfg.get("prompt_suffix") or ""
    out_dir = workdir / "images"
    base = {"steps": steps, **(cfg.get("extra_body") or {})}
    if cfg.get("negative_prompt"):
        base["negative_prompt"] = cfg["negative_prompt"]
    req_size = None
    if cfg.get("send_size") and size:
        req_size = native_size(*size) if cfg.get("size_mode", "native") == "native" else (size[0] - size[0] % 16, size[1] - size[1] % 16)
        kw, kh = (cfg.get("size_keys") or ["width", "height"])[:2]
        base[kw], base[kh] = req_size

    norm = []                                   # (original key, prompt, characters)
    for it in items:
        prompt, chars = (it, ()) if isinstance(it, str) else (it[0], tuple(it[1] or ()))
        norm.append((it, prompt, chars))

    result: dict = {}
    todo = []                                   # (key, final prompt, path, characters)
    seen_keys = set()
    for key, prompt, chars in norm:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        final = f"{pre}{prompt}{suf}".strip()
        h = hashlib.sha1(f"{final}|{steps}|{req_size}|{cfg.get('negative_prompt', '')}|{','.join(chars)}".encode()).hexdigest()[:16]
        path = out_dir / f"{h}.jpg"
        if path.exists():
            result[key] = path
        else:
            todo.append((key, final, path, chars))
    if not todo:
        return result
    print(f"[image] generating {len(todo)} image(s)", flush=True)

    def with_chars(body: dict, chars: tuple) -> dict:
        return {**body, "character_names": list(chars)} if chars else body

    batch_url = os.environ.get("QWEN_BATCH_URL") or cfg.get("batch_url")
    batch_key = cfg.get("batch_key") or "prompts"
    if batch_url:
        n = max(1, int(cfg.get("batch_size", 4)))
        groups: dict = {}
        for t in todo:
            groups.setdefault(t[3], []).append(t)
        for chars, grp in groups.items():
            for i in range(0, len(grp), n):
                chunk = grp[i:i + n]
                try:
                    imgs = _post(batch_url, with_chars({**base, batch_key: [t[1] for t in chunk]}, chars), cfg)
                    if len(imgs) < len(chunk):
                        ctx.warn(f"batch returned {len(imgs)} of {len(chunk)} images; generating the rest one by one")
                    for (key, _, path, _c), b in zip(chunk, imgs):
                        if _save(b, path):
                            result[key] = path
                except Exception as ex:  # noqa
                    ctx.warn(f"batch image call failed ({str(ex)[:300]}); falling back to single calls for this chunk")
    rest = [t for t in todo if t[0] not in result]

    def one(t):
        key, final, path, chars = t
        try:
            b = _post(url, with_chars({**base, "prompt": final}, chars), cfg)[0]
            if _save(b, path):
                return key, path
            ctx.warn("image endpoint returned data PIL could not read")
        except Exception as ex:  # noqa
            ctx.warn(f"image generation failed for a scene ({str(ex)[:300]}); it will use a text visual")
        return key, None

    if rest:
        outs = [one(rest[0])]  # warm the container with one call, then (optionally) go parallel
        mp = max(1, int(cfg.get("max_parallel", 1)))
        if len(rest) > 1:
            with ThreadPoolExecutor(max_workers=mp) as ex:
                outs += list(ex.map(one, rest[1:]))
        for key, path in outs:
            if path:
                result[key] = path
    return result
