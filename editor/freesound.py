"""Freesound API helpers (CC0 only, so no attribution is ever required)."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import requests

API = "https://freesound.org/apiv2"


def search_cc0(query: str, key: str, max_dur: float = 6.0, page_size: int = 30) -> list[dict]:
    params = {
        "query": query,
        "filter": f'license:"Creative Commons 0" duration:[0.05 TO {max_dur}]',
        "fields": "id,name,tags,duration,previews,license",
        "sort": "downloads_desc",
        "page_size": page_size,
        "token": key,
    }
    r = requests.get(f"{API}/search/text/", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])


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
    return os.environ.get("FREESOUND_API_KEY") or None
