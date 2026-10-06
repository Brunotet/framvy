"""Fetch job inputs (URL or local path) into the workdir."""
from __future__ import annotations
import hashlib, mimetypes, shutil, time
from pathlib import Path
from typing import Optional
import requests

from .util import Ctx

_EXT_FALLBACK = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                 "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
                 "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/aac": ".aac"}


def download(url: str, dest_dir: Path, ctx: Ctx, tries: int = 3, timeout: int = 60) -> Optional[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    for existing in dest_dir.glob(key + ".*"):
        return existing
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, timeout=timeout, stream=True, headers={"User-Agent": "video-editor/1.0"})
            r.raise_for_status()
            ctype = r.headers.get("content-type", "").split(";")[0].strip()
            ext = Path(url.split("?")[0]).suffix.lower()
            if not ext or len(ext) > 5:
                ext = _EXT_FALLBACK.get(ctype) or mimetypes.guess_extension(ctype) or ".bin"
            out = dest_dir / f"{key}{ext}"
            with open(out, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
            return out
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    ctx.warn(f"download failed: {url} ({last})")
    return None


def fetch(url: Optional[str], path: Optional[str], dest_dir: Path, ctx: Ctx) -> Optional[Path]:
    if url:
        if url.startswith(("http://", "https://")):
            return download(url, dest_dir, ctx)
        path = url
    if path:
        p = Path(path)
        if not p.exists():
            ctx.warn(f"local file not found: {path}")
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / (hashlib.sha1(str(p.resolve()).encode()).hexdigest()[:16] + p.suffix.lower())
        if not out.exists():
            shutil.copy(p, out)
        return out
    return None


def valid_image(path: Path) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False
