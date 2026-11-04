"""Freesound API helpers (CC0 only, so no attribution is ever required).
FREESOUND_API_KEY may hold one key or several separated by commas: the first is the main key,
the others are fallbacks used when the main one is rate-limited (429) or rejected (401/403)."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import requests

API = "https://freesound.org/apiv2"


def _all_keys(first: Optional[str] = None) -> list[str]:
    raw = [first or "", os.environ.get("FREESOUND_API_KEY") or "", os.environ.get("FREESOUND_API_KEY_2") or ""]
    out: list[str] = []
    for chunk in raw:
        for k in chunk.replace(";", ",").replace("\n", ",").split(","):
            k = k.strip()
            if k and k not in out:
                out.append(k)
    return out


def search_cc0(query: str, key: str, max_dur: float = 6.0, page_size: int = 30) -> list[dict]:
    params = {
        "query": query,
        "filter": f'license:"Creative Commons 0" duration:[0.05 TO {max_dur}]',
        "fields": "id,name,tags,duration,previews,license",
        "sort": "downloads_desc",
        "page_size": page_size,
    }
    last: Optional[Exception] = None
    for k in _all_keys(key):
        try:
            r = requests.get(f"{API}/search/text/", params={**params, "token": k}, timeout=30)
            if r.status_code in (401, 403, 429):     # bad key or rate limit -> try the fallback key
                last = RuntimeError(f"Freesound HTTP {r.status_code}")
                continue
            r.raise_for_status()
            return r.json().get("results", [])
        except requests.RequestException as ex:
            last = ex
    if last:
        raise last
    return []


def download_preview(item: dict, dest: Path) -> Optional[Path]:
    url = (item.get("previews") or {}).get("preview-hq-mp3")
    if not url:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = dest / f"freesound_{item['id']}.mp3"
    if out.exists():
        return out
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def key_from_env() -> Optional[str]:
    keys = _all_keys()
    return keys[0] if keys else None
