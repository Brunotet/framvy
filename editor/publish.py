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


def put_presigned(path: Path, url: str, ctx: Ctx, tries: int = 3) -> bool:
    """Upload the finished video to a presigned PUT URL (the R2 pattern your other pipelines already use)."""
    import time
    last = None
    for i in range(tries):
        try:
            with open(path, "rb") as f:
                r = requests.put(url, data=f, headers={"Content-Type": "video/mp4"}, timeout=900)
            if r.status_code in (200, 201, 204):
                return True
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as ex:  # noqa
            last = str(ex)
        time.sleep(4 * (i + 1))
    ctx.warn(f"presigned upload failed: {last}")
    return False


def callback(url: Optional[str], payload: dict, ctx: Ctx):
    """Tell n8n (the Wait node's resume URL) the render is done. Retries, and prints exactly what n8n answered."""
    import time
    from urllib.parse import urlparse
    if not url:
        print("[callback] no callback_url was given, so n8n is not notified", flush=True)
        return
    last = None
    for i in range(3):
        try:
            r = requests.post(url, json=payload, timeout=30)
            print(f"[callback] n8n ({urlparse(url).netloc}) answered HTTP {r.status_code}", flush=True)
            if r.status_code < 300:
                return
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as ex:  # noqa
            last = str(ex)
            print(f"[callback] attempt {i + 1} failed: {last[:160]}", flush=True)
        time.sleep(5)
    ctx.warn(f"callback failed: {last}")
