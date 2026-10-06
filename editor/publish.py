"""Optional: upload the finished video to Cloudflare R2 and ping n8n when done."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import requests

from .util import Ctx


def r2_client():
    import boto3
    return boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def r2_configured() -> bool:
    return all(os.environ.get(k) for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"))


def upload_video(path: Path, key: str, ctx: Ctx) -> Optional[str]:
    if not r2_configured():
        ctx.warn("R2 not configured; video stays in the workflow artifact")
        return None
    try:
        r2_client().upload_file(str(path), os.environ["R2_BUCKET"], key,
                                ExtraArgs={"ContentType": "video/mp4"})
        base = (os.environ.get("R2_PUBLIC_BASE") or "").rstrip("/")
        return f"{base}/{key}" if base else f"r2://{os.environ['R2_BUCKET']}/{key}"
    except Exception as ex:
        ctx.warn(f"R2 upload failed: {ex}")
        return None


def callback(url: Optional[str], payload: dict, ctx: Ctx):
    if not url:
        return
    try:
        requests.post(url, json=payload, timeout=30).raise_for_status()
    except Exception as ex:
        ctx.warn(f"callback failed: {ex}")
