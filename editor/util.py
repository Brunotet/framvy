from __future__ import annotations
import json, subprocess
from pathlib import Path


class Ctx:
    """Carries warnings and credits through the pipeline (the render never hard-fails on assets)."""
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.warnings: list[str] = []
        self.credits: list[dict] = []

    def warn(self, msg: str):
        print(f"[warn] {msg}", flush=True)
        self.warnings.append(msg)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def probe_duration(path: Path) -> float:
    try:
        r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", str(path)])
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0
