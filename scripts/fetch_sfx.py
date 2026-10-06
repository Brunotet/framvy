#!/usr/bin/env python3
"""
Build the sound-effect library ONCE, in bulk.

  python scripts/fetch_sfx.py ingest --raw "C:\\Users\\you\\Downloads\\Sonniss.com-GDC2026-GameAudioBundle*"
        # accepts unzipped folders, zips, or globs (several allowed). Reads the folder/pack names and the UCS file
        # names ("FGHTImpt_4 x Punch, Body 02_344 Audio.wav"), builds clean names + tags, trims leading silence,
        # measures when each sound really starts/peaks/ends, converts to mp3, writes sfx_library/index.json
  python scripts/fetch_sfx.py search punch         # test what the editor would find for a query
  python scripts/fetch_sfx.py vocab                # most common tags (paste into your n8n planner if you like)
  python scripts/fetch_sfx.py freesound            # auto-pull CC0 sounds for scripts/sfx_seed_queries.txt (needs FREESOUND_API_KEY)
  python scripts/fetch_sfx.py publish              # upload sfx_library/ to R2 (prefix sfx/) so GitHub Actions can use it
  python scripts/fetch_sfx.py stats
  python scripts/fetch_sfx.py download             # optional: fetch zips listed in scripts/sfx_sources.txt
"""
from __future__ import annotations
import argparse, glob, hashlib, json, re, sys, zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from editor.freesound import download_preview, key_from_env, search_cc0  # noqa: E402
from editor.sfxmeta import analyze  # noqa: E402
from editor.sfxname import parse as parse_name, _tokens  # noqa: E402
from editor.util import run  # noqa: E402

LIB = ROOT / "sfx_library"
AUDIO_EXT = {".wav", ".flac", ".ogg", ".mp3", ".aif", ".aiff", ".m4a"}


def _index() -> list[dict]:
    p = LIB / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(idx: list[dict]):
    LIB.mkdir(exist_ok=True)
    (LIB / "index.json").write_text(json.dumps(idx, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- spreadsheet metadata (optional)
def _load_sheet_meta(root: Path) -> dict[str, dict]:
    """Sonniss ships an .xlsx file list next to the audio. Use it to enrich tags when its columns are recognisable."""
    meta: dict[str, dict] = {}
    try:
        import openpyxl
    except Exception:
        return meta
    for x in list(root.glob("*.xlsx")) + list(root.glob("*/*.xlsx")):
        if x.name.startswith("~$"):
            continue
        try:
            wb = openpyxl.load_workbook(x, read_only=True, data_only=True)
            for ws in wb.worksheets:
                rows = ws.iter_rows(values_only=True)
                header = None
                for r in rows:
                    cells = [str(c).strip().lower() if c is not None else "" for c in r]
                    if header is None:
                        if any("file" in c for c in cells):
                            header = cells
                        continue
                    row = dict(zip(header, r))
                    fn = next((v for k, v in row.items() if k and "file" in k and v), None)
                    if not fn:
                        continue
                    text = " ".join(str(v) for k, v in row.items()
                                    if v and k and any(w in k for w in ("desc", "keyword", "tag", "categ", "title")))
                    meta[Path(str(fn)).stem.lower()] = {"text": text}
        except Exception as ex:
            print("  (could not read", x.name, ":", ex, ")")
    if meta:
        print(f"  spreadsheet metadata: {len(meta)} rows")
    return meta


# ---------------------------------------------------------------- ingest
def _expand_inputs(raws: list[str]) -> list[Path]:
    out = []
    for r in raws:
        hits = glob.glob(r) or [r]
        out += [Path(h) for h in hits if Path(h).exists()]
    return out


def _convert(item):
    src, rel, a = item
    h = hashlib.sha1((rel + str(src.stat().st_size)).encode()).hexdigest()[:10]
    info = parse_name(rel)
    stem = "-".join(_tokens(info["name"])[:4]) or "sfx"
    name = f"{stem}_{h}.mp3"
    out = LIB / "files" / name
    try:
        m = analyze(src)
        if not (a.min_sec <= m["duration"] <= a.max_sec) or m["duration"] <= 0:
            return None
        onset, end = m["onset"], max(m["active_end"], m["onset"] + 0.05)
        keep = (end - onset) + 0.12                     # real sound + a tiny tail, silence removed both ends
        if not out.exists():
            fade_st = max(0.0, keep - 0.1)
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{onset:.3f}", "-t", f"{keep:.3f}", "-i", str(src),
                 "-af", f"afade=t=out:st={fade_st:.3f}:d=0.1", "-ac", "2", "-ar", "44100", "-b:a", "160k", str(out)])
        peak = max(0.0, m["peak"] - onset)
        return {"id": f"sonniss:{h}", "file": name, "name": info["name"], "tags": info["tags"],
                "category": info["category"], "pack": info["pack"], "vendor": info["vendor"],
                "duration": round(keep, 3), "onset": 0.0, "peak": round(peak, 3), "active_end": round(end - onset, 3),
                "source": "sonniss", "license": "royalty-free (Sonniss GDC license)", "orig": rel, "_stem": src.stem.lower()}
    except Exception:
        return None


def cmd_ingest(a):
    roots = _expand_inputs(a.raw)
    if not roots:
        sys.exit("No input found. Example: --raw \"C:\\Users\\you\\Downloads\\Sonniss.com-GDC2026-GameAudioBundle*\"")
    (LIB / "files").mkdir(parents=True, exist_ok=True)
    items, sheet = [], {}
    for root in roots:
        if root.suffix.lower() == ".zip":
            ex = ROOT / "sfx_raw" / "_extracted" / root.stem
            if not ex.exists():
                print("extracting", root.name, flush=True)
                ex.mkdir(parents=True, exist_ok=True)
                zipfile.ZipFile(root).extractall(ex)
            root = ex
        sheet.update(_load_sheet_meta(root))
        for p in root.rglob("*"):
            if p.suffix.lower() in AUDIO_EXT:
                items.append((p, str(p.relative_to(root)), a))
    print(f"found {len(items)} audio files; keeping {a.min_sec}-{a.max_sec}s one-shots", flush=True)
    idx = {e["id"]: e for e in _index()}
    kept = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n, e in enumerate(ex.map(_convert, items), 1):
            if e:
                stem = e.pop("_stem")
                extra = (sheet.get(stem) or {}).get("text")
                if extra:
                    e["tags"] = list(dict.fromkeys(e["tags"] + _tokens(extra)))[:24]
                idx[e["id"]] = e
                kept += 1
            if n % 200 == 0:
                print(f"  {n}/{len(items)} (kept {kept})", flush=True)
                _save(list(idx.values()))
    _save(list(idx.values()))
    print("library size:", len(idx))


# ---------------------------------------------------------------- search / vocab / stats
def cmd_search(a):
    from editor.sfx import SfxLibrary
    from editor.util import Ctx
    lib = SfxLibrary(Ctx("search"), ROOT / "sfx_cache")
    q = " ".join(a.query)
    raw = set(_tokens(q))
    rows = []
    for e in lib.index:
        tags = set(e.get("tags", []))
        score = len(raw & tags) * 3 + len(raw & set(_tokens(e.get("name", "")))) * 2
        if score:
            rows.append((score, e))
    rows.sort(key=lambda x: -x[0])
    for sc, e in rows[:15]:
        print(f"{sc:>3}  {e['name'][:44]:<44} {e.get('category',''):<16} {e.get('active_end', e.get('duration', 0)):>5.2f}s  [{e.get('pack','')}]")
    print(f"{len(rows)} matches")


def cmd_vocab(a):
    c = Counter(t for e in _index() for t in e.get("tags", []))
    print(", ".join(f"{t}({n})" for t, n in c.most_common(a.top)))


def cmd_stats(a):
    idx = _index()
    by, cats = Counter(e["source"] for e in idx), Counter((e.get("category") or "uncategorised").split("/")[0] for e in idx)
    print(len(idx), "sounds", dict(by))
    print("top categories:", dict(cats.most_common(12)))


# ---------------------------------------------------------------- freesound / publish / download
def cmd_freesound(a):
    key = key_from_env()
    if not key:
        sys.exit("Set FREESOUND_API_KEY (free at freesound.org/apiv2/apply)")
    queries = [q.strip() for q in (ROOT / "scripts" / "sfx_seed_queries.txt").read_text().splitlines() if q.strip()]
    (LIB / "files").mkdir(parents=True, exist_ok=True)
    idx = {e["id"]: e for e in _index()}
    for q in queries:
        try:
            results = search_cc0(q, key, max_dur=a.max_sec)[: a.per]
        except Exception as ex:
            print("search failed", q, ex); continue
        for item in results:
            eid = f"freesound:{item['id']}"
            if eid in idx:
                continue
            try:
                f = download_preview(item, LIB / "files")
            except Exception as ex:
                print("  dl failed", item["id"], ex); continue
            if f:
                m = analyze(f)
                idx[eid] = {"id": eid, "file": f.name, "name": item.get("name", "")[:80],
                            "tags": list(dict.fromkeys(_tokens(q, " ".join(item.get("tags", [])[:8]))))[:16],
                            "category": "", "pack": "freesound", "vendor": "", "duration": m["duration"],
                            "onset": m["onset"], "peak": m["peak"], "active_end": m["active_end"],
                            "source": "freesound", "license": "CC0"}
        print(f"{q}: library now {len(idx)}", flush=True)
        _save(list(idx.values()))


def cmd_publish(a):
    import os
    from editor.publish import r2_client, r2_configured
    if not r2_configured():
        sys.exit("Set R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET")
    c, bucket = r2_client(), os.environ["R2_BUCKET"]
    remote = set()
    for page in c.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="sfx/files/"):
        remote |= {o["Key"] for o in page.get("Contents", [])}
    todo = [p for p in (LIB / "files").glob("*.mp3") if f"sfx/files/{p.name}" not in remote]
    print(f"uploading {len(todo)} new files")
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda p: c.upload_file(str(p), bucket, f"sfx/files/{p.name}"), todo))
    c.upload_file(str(LIB / "index.json"), bucket, "sfx/index.json", ExtraArgs={"ContentType": "application/json"})
    print("done. Set the SFX_BASE_URL secret to <your public R2 url>/sfx")


def cmd_download(a):
    src = ROOT / "scripts" / "sfx_sources.txt"
    urls = [l.strip() for l in src.read_text().splitlines() if l.strip() and not l.startswith("#")]
    if not urls:
        print("Paste direct zip URLs into scripts/sfx_sources.txt first."); return
    dest = ROOT / "sfx_raw"
    dest.mkdir(exist_ok=True)
    for u in urls:
        name = u.split("?")[0].rstrip("/").split("/")[-1] or hashlib.sha1(u.encode()).hexdigest()[:8] + ".zip"
        out = dest / name
        if out.exists():
            print("skip", name); continue
        print("downloading", name, flush=True)
        with requests.get(u, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(out, "wb") as f:
                for ch in r.iter_content(1 << 20):
                    f.write(ch)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("ingest", cmd_ingest), ("search", cmd_search), ("vocab", cmd_vocab), ("freesound", cmd_freesound),
                     ("publish", cmd_publish), ("stats", cmd_stats), ("download", cmd_download)]:
        p = sp.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--raw", nargs="+", default=["sfx_raw"], help="unzipped folders, zips or globs")
        p.add_argument("--max-sec", type=float, default=12.0)
        p.add_argument("--min-sec", type=float, default=0.08)
        p.add_argument("--per", type=int, default=12)
        p.add_argument("--top", type=int, default=150)
        if name == "search":
            p.add_argument("query", nargs="+")
    a = ap.parse_args()
    a.fn(a)
