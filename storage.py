"""Supabase Storage-e upload. Path format website-er moto: YYYY/MM/<32hex>.<ext>"""
import os
import secrets
from datetime import datetime, timezone

import httpx


async def upload(data: bytes, ext: str, content_type: str) -> str:
    """Bucket-e upload kore public URL ferot dey."""
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    bucket = os.getenv("SUPABASE_BUCKET", "media")

    now = datetime.now(timezone.utc)
    path = f"{now:%Y/%m}/{secrets.token_hex(16)}.{ext}"

    headers = {"apikey": key, "Content-Type": content_type, "x-upsert": "false", "cache-control": "max-age=31536000"}
    if not key.startswith("sb_"):  # purono JWT-style key hole Bearer-o lage
        headers["Authorization"] = f"Bearer {key}"

    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{base}/storage/v1/object/{bucket}/{path}", content=data, headers=headers)
    if r.status_code >= 300:
        raise RuntimeError(f"storage upload failed {r.status_code}: {r.text[:200]}")
    return f"{base}/storage/v1/object/public/{bucket}/{path}"
