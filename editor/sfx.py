"""
Sound-effect resolver. Order (a render never breaks on a missing sound, and nothing is ever generated):
  1. exact id in the library index
  2. tag/name match in the library (sfx_library/ in the repo)
  3. live Freesound search (CC0 only) if the FREESOUND_API_KEY secret is set
  4. otherwise the cue is skipped: silence, never a generated beep
"""
from __future__ import annotations
import hashlib, json, os, random, re
from pathlib import Path
from typing import Optional
import requests

from .config import ROOT
from .freesound import download_preview, key_from_env, search_cc0
from .sfxmeta import cached as _meta_cached
from .util import Ctx

SYNONYMS = {
    "whoosh": ["whoosh", "swoosh", "swish", "swipe", "transition", "sweep", "air"],
    "pop": ["pop", "click", "ui", "bubble", "tick", "blip"],
    "hit": ["hit", "impact", "boom", "thud", "punch", "slam", "braam", "smash"],
    "riser": ["riser", "rise", "build", "tension", "swell", "upward"],
    "ding": ["ding", "bell", "notification", "chime", "success"],
    "drop": ["drop", "downer", "downlifter", "fall", "bass"],
    "glitch": ["glitch", "digital", "error", "static", "stutter"],
}
def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _expand(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for group in SYNONYMS.values():
        if tokens & set(group):
            out |= set(group)
    return out


class SfxLibrary:
    def __init__(self, ctx: Ctx, cache_dir: Path):
        self.ctx = ctx
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.local_dir = ROOT / "sfx_library"
        self.base_url = (os.environ.get("SFX_BASE_URL") or "").rstrip("/")
        self.fs_key = key_from_env()
        self.rng = random.Random(ctx.job_id)
        self.index: list[dict] = self._load_index()
        self._memo: dict[str, Optional[dict]] = {}

    # ---- index -------------------------------------------------------
    def _load_index(self) -> list[dict]:
        entries: dict[str, dict] = {}
        p = self.local_dir / "index.json"
        if p.exists():
            try:
                for e in json.loads(p.read_text(encoding="utf-8")):
                    entries[e["id"]] = {**e, "_where": "local"}
            except Exception as ex:
                self.ctx.warn(f"bad local sfx index: {ex}")
        if self.base_url:
            try:
                r = requests.get(f"{self.base_url}/index.json", timeout=30)
                r.raise_for_status()
                for e in r.json():
                    entries.setdefault(e["id"], {**e, "_where": "remote"})
            except Exception as ex:
                self.ctx.warn(f"remote sfx index unavailable ({ex}); using fallbacks")
        return list(entries.values())

    def _file_for(self, e: dict) -> Optional[Path]:
        local = self.local_dir / "files" / e["file"]
        if local.exists():
            return local
        if self.base_url:
            dest = self.cache / "lib" / e["file"]
            if dest.exists():
                return dest
            try:
                r = requests.get(f"{self.base_url}/files/{e['file']}", timeout=60)
                r.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                return dest
            except Exception as ex:
                self.ctx.warn(f"sfx file fetch failed {e['file']}: {ex}")
        return None

    # ---- resolution --------------------------------------------------
    def _entry_result(self, e: dict, f: Path) -> dict:
        meta = {k: e[k] for k in ("onset", "peak", "active_end", "duration") if k in e}
        if "onset" not in meta:
            meta = _meta_cached(f, self.cache / "meta")
        return {"path": f, "id": e["id"], "source": e.get("source", "library"),
                "license": e.get("license", "royalty-free"), "meta": meta, "name": e.get("name", "")}

    def _from_library(self, query: str, want_len: Optional[float] = None) -> Optional[dict]:
        raw = _tokens(query)
        toks = _expand(raw)
        scored = []
        for e in self.index:
            tags = set(e.get("tags", []))
            name_t = _tokens(e.get("name", "")) | _tokens(e.get("category", "")) | _tokens(e.get("pack", ""))
            hit_raw = len(raw & (tags | name_t))
            score = 3 * len(toks & tags) + 2 * len(toks & name_t) + 4 * hit_raw
            if len(raw) > 1 and raw <= (tags | name_t):
                score += 6                      # every word of a multi-word query matched
            if score < 3:
                continue
            if want_len:                        # prefer sounds that naturally fit the slot
                act = e.get("active_end") or e.get("duration") or 0
                if act and act <= want_len * 1.4:
                    score += 3
                elif act and act > want_len * 3:
                    score -= 2
            scored.append((score, e))
        if not scored:
            return None
        scored.sort(key=lambda x: -x[0])
        top = [e for sc, e in scored if sc >= scored[0][0] - 2][:4]
        self.rng.shuffle(top)
        for e in top:
            f = self._file_for(e)
            if f:
                return self._entry_result(e, f)
        return None

    def _from_freesound(self, query: str) -> Optional[dict]:
        if not self.fs_key:
            return None
        try:
            results = search_cc0(query, self.fs_key)[:5]
            self.rng.shuffle(results)
            for item in results:
                f = download_preview(item, self.cache / "freesound")
                if f:
                    return {"path": f, "id": f"freesound:{item['id']}", "source": "freesound",
                            "license": "CC0", "meta": _meta_cached(f, self.cache / "meta"), "name": item.get("name", "")}
        except Exception as ex:
            self.ctx.warn(f"freesound fallback failed for '{query}': {ex}")
        return None

    def resolve(self, query: Optional[str] = None, sfx_id: Optional[str] = None,
                want_len: Optional[float] = None) -> Optional[dict]:
        memo_key = f"{sfx_id}|{query}"
        # same query repeated -> allow variety, so only memoize id lookups
        if sfx_id:
            if memo_key in self._memo:
                return self._memo[memo_key]
            for e in self.index:
                if e["id"] == sfx_id:
                    f = self._file_for(e)
                    if f:
                        res = self._entry_result(e, f)
                        self._memo[memo_key] = res
                        return res
            self.ctx.warn(f"sfx id '{sfx_id}' not found; falling back to query")
        q = query or "pop"
        found = self._from_library(q, want_len) or self._from_freesound(q)
        if not found:
            self.ctx.warn(f"no sound found for '{q}' (library + Freesound): skipped, nothing is generated")
        return found
